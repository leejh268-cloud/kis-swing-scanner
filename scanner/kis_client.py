"""
한국투자증권 Open API 클라이언트

⚠️ 중요: 아래 TR_ID / 엔드포인트 값은 한투 공식 GitHub(koreainvestment/open-trading-api) 및
API 포탈(apiportal.koreainvestment.com) 문서를 기준으로 작성했지만, 한투 측에서 API 스펙을
예고 없이 바꾸는 경우가 있습니다. 자동화(GitHub Actions)를 켜기 전에 반드시
`python -m scanner.test_connection` 을 로컬에서 먼저 실행해 정상 응답을 확인하세요.

Rate limit: 실전투자 기준 초당 20건 (한투 공식 정책). 이 클라이언트는 안전하게 초당 15건으로 제한합니다.
"""
import os
import time
import json
import threading
from pathlib import Path

import requests

BASE_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_CACHE_PATH = Path(os.environ.get("KIS_TOKEN_CACHE", "/tmp/kis_token_cache.json"))

# 초당 15건으로 제한 (한투 공식 한도는 20건/초, 여유를 둠)
_MAX_CALLS_PER_SEC = 15
_lock = threading.Lock()
_call_timestamps: list = []


def _throttle():
    """슬라이딩 윈도우 방식으로 초당 호출 수를 제한"""
    with _lock:
        now = time.time()
        # 1초보다 오래된 기록은 제거
        while _call_timestamps and now - _call_timestamps[0] > 1.0:
            _call_timestamps.pop(0)
        if len(_call_timestamps) >= _MAX_CALLS_PER_SEC:
            sleep_time = 1.0 - (now - _call_timestamps[0]) + 0.02
            if sleep_time > 0:
                time.sleep(sleep_time)
        _call_timestamps.append(time.time())


class KisClient:
    def __init__(self, app_key: str = None, app_secret: str = None):
        self.app_key = app_key or os.environ["KIS_APP_KEY"]
        self.app_secret = app_secret or os.environ["KIS_APP_SECRET"]
        self.session = requests.Session()
        self.access_token = None
        self._load_or_issue_token()

    # ---------------------------------------------------------------- 인증
    def _load_or_issue_token(self):
        """
        한투는 접근토큰을 '1일 1회 발급'을 원칙으로 하고, 유효기간 내 잦은 재발급 시
        이용이 제한될 수 있다고 안내합니다. 따라서 토큰을 파일에 캐싱해 재사용합니다.
        (GitHub Actions는 매 실행마다 새 컨테이너라 캐시가 없을 수 있는데, 이 경우는
        하루 1회 스캔 정도로는 재발급 제한에 걸릴 가능성이 낮습니다.)
        """
        cached = self._read_cache()
        if cached and cached.get("expires_at", 0) > time.time() + 300:
            self.access_token = cached["access_token"]
            return
        self._issue_token()

    def _read_cache(self):
        try:
            if TOKEN_CACHE_PATH.exists():
                return json.loads(TOKEN_CACHE_PATH.read_text())
        except Exception:
            pass
        return None

    def _issue_token(self, retries: int = 3):
        """
        한투는 같은 앱키로 너무 짧은 간격에 토큰을 재발급하면 일시적으로
        403을 반환하는 경우가 있습니다 (공식 안내: 재발급은 분당 제한 있음).
        로컬 테스트 직후 바로 GitHub Actions를 돌리는 등 서로 다른 환경에서
        같은 앱키로 연달아 토큰을 발급받을 때 특히 발생하기 쉬워, 지수 백오프로
        재시도합니다.
        """
        url = f"{BASE_URL}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        last_err = None
        for attempt in range(retries):
            res = self.session.post(url, json=body, timeout=10)
            if res.status_code == 200:
                break
            if res.status_code in (403, 429) and attempt < retries - 1:
                wait = 15 * (attempt + 1)  # 15초, 30초 ...
                print(f"[토큰발급] {res.status_code} 응답, {wait}초 후 재시도 ({attempt + 1}/{retries})")
                time.sleep(wait)
                last_err = res
                continue
            res.raise_for_status()
        else:
            last_err.raise_for_status()
        data = res.json()
        self.access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 86400))
        cache = {
            "access_token": self.access_token,
            "expires_at": time.time() + expires_in,
        }
        try:
            TOKEN_CACHE_PATH.write_text(json.dumps(cache))
        except Exception:
            pass

    def _headers(self, tr_id: str, extra: dict = None):
        h = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
        if extra:
            h.update(extra)
        return h

    # ------------------------------------------------------------- 공통 GET
    def _get(self, path: str, tr_id: str, params: dict, retries: int = 3):
        url = f"{BASE_URL}{path}"
        last_err = None
        for attempt in range(retries):
            _throttle()
            try:
                res = self.session.get(url, headers=self._headers(tr_id), params=params, timeout=10)
                if res.status_code == 200:
                    return res.json()
                if res.status_code == 429:
                    # 유량 제한 - 잠깐 쉬고 재시도
                    time.sleep(1.0 + attempt)
                    continue
                res.raise_for_status()
            except Exception as e:
                last_err = e
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"KIS API 요청 실패: {path} ({last_err})")

    # ------------------------------------------------------- 일봉(기간별시세)
    def get_daily_ohlcv(self, code: str, start_date: str, end_date: str, adj: bool = True):
        """
        국내주식 기간별시세(일봉) 조회
        TR_ID: FHKST03010100
        endpoint: /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
        최대 약 100건(영업일 기준)까지 한 번에 반환됩니다.
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": start_date,  # YYYYMMDD
            "FID_INPUT_DATE_2": end_date,  # YYYYMMDD
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0" if adj else "1",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100",
            params,
        )
        rows = data.get("output2", [])
        return rows

    # ------------------------------------------------------------- 현재가
    def get_current_price(self, code: str):
        """
        주식현재가 시세 조회
        TR_ID: FHKST01010100
        endpoint: /uapi/domestic-stock/v1/quotations/inquire-price
        """
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            params,
        )
        return data.get("output", {})

    # --------------------------------------------------------- 거래량 순위
    def get_volume_rank(self, market_div: str = "J", top_n: int = 30):
        """
        거래량 순위
        TR_ID: FHPST01710000
        endpoint: /uapi/domestic-stock/v1/quotations/volume-rank
        ⚠️ 파라미터 조합(FID_COND_SCR_DIV_CODE 등)은 한투 문서에서 재확인 필요.
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": market_div,
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "0000000000",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": "",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            "FHPST01710000",
            params,
        )
        return data.get("output", [])[:top_n]

    # -------------------------------------------------- 외국인/기관 순매수 상위
    def get_investor_net_buy_rank(self, market_div: str = "J", top_n: int = 30):
        """
        외국인 기관 매매종목가집계 (수급 상위)
        TR_ID: FHPTJ04400000 (⚠️ 최신 문서 재확인 권장)
        endpoint: /uapi/domestic-stock/v1/quotations/foreign-institution-total
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": market_div,
            "FID_COND_SCR_DIV_CODE": "16449",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_RANK_SORT_CLS_CODE": "0",
            "FID_ETC_CLS_CODE": "0",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/quotations/foreign-institution-total",
            "FHPTJ04400000",
            params,
        )
        return data.get("output", [])[:top_n]
