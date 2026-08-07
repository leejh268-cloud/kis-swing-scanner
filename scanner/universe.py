"""
KOSPI / KOSDAQ 전종목 마스터 파일 다운로드 & 파싱

한투는 별도의 '전종목 목록 조회' REST API 대신, 매일 갱신되는 고정폭 텍스트 마스터 파일을
공식 배포합니다 (한투 공식 GitHub 샘플 코드 koreainvestment/open-trading-api 의
stocks_info/kis_kospi_code_mst.py 로직을 그대로 이식했습니다).

⚠️ KOSDAQ 필드 스펙(field_specs)은 KOSPI 스펙을 기준으로 구성한 값이라 실행 후
`validate_master_df()` 결과를 반드시 확인하세요. 컬럼이 깨져 보이면 GitHub 저장소에서
kis_kosdaq_code_mst.py 원본을 다시 받아 field_specs를 교체하면 됩니다.
"""
import os
import ssl
import zipfile
import urllib.request
from pathlib import Path

import pandas as pd

MASTER_DIR = Path(os.environ.get("KIS_MASTER_DIR", "/tmp/kis_master"))
MASTER_DIR.mkdir(parents=True, exist_ok=True)

_KOSPI_URL = "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
_KOSDAQ_URL = "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip"

_KOSPI_TAIL_WIDTH = 228
_KOSDAQ_TAIL_WIDTH = 222

_FIELD_SPECS = [
    2, 1, 4, 4, 4,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 1, 1, 1, 1,
    1, 9, 5, 5, 1,
    1, 1, 2, 1, 1,
    1, 2, 2, 2, 3,
    1, 3, 12, 12, 8,
    15, 21, 2, 7, 1,
    1, 1, 1, 1, 9,
    9, 9, 5, 9, 8,
    9, 3, 1, 1, 1,
]

_TAIL_COLUMNS = [
    "그룹코드", "시가총액규모", "지수업종대분류", "지수업종중분류", "지수업종소분류",
    "c1", "저유동성", "c2", "c3", "c4",
    "c5", "c6", "c7", "c8", "c9",
    "c10", "c11", "c12", "c13", "c14",
    "c15", "c16", "단기과열", "c17", "c18",
    "c19", "c20", "c21", "c22", "c23",
    "c24", "기준가", "매매수량단위", "시간외수량단위", "거래정지",
    "정리매매", "관리종목", "시장경고", "경고예고", "불성실공시",
    "우회상장", "락구분", "액면변경", "증자구분", "증거금비율",
    "신용가능", "신용기간", "전일거래량", "액면가", "상장일자",
    "상장주수", "자본금", "결산월", "공모가", "우선주",
    "공매도과열", "이상급등", "KRX300", "지수편입여부", "매출액",
    "영업이익", "경상이익", "당기순이익", "ROE", "기준년월",
    "시가총액", "그룹사코드", "회사신용한도초과", "담보대출가능", "대주가능",
]


def _download_and_extract(url: str, mst_filename: str) -> Path:
    ssl._create_default_https_context = ssl._create_unverified_context
    zip_path = MASTER_DIR / f"{mst_filename}.zip"
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(MASTER_DIR)
    zip_path.unlink(missing_ok=True)
    return MASTER_DIR / mst_filename


def _parse_master(mst_path: Path, tail_width: int, market: str) -> pd.DataFrame:
    head_rows = []
    tail_rows = []
    with open(mst_path, mode="r", encoding="cp949", errors="replace") as f:
        for row in f:
            row = row.rstrip("\n")
            head = row[: len(row) - tail_width]
            tail = row[-tail_width:]
            head_rows.append(
                {
                    "단축코드": head[0:9].strip(),
                    "표준코드": head[9:21].strip(),
                    "한글명": head[21:].strip(),
                }
            )
            tail_rows.append(tail)

    df_head = pd.DataFrame(head_rows)

    # fixed-width tail 파싱
    import io
    tail_text = "\n".join(tail_rows)
    df_tail = pd.read_fwf(io.StringIO(tail_text), widths=_FIELD_SPECS, names=_TAIL_COLUMNS)

    df = pd.concat([df_head.reset_index(drop=True), df_tail.reset_index(drop=True)], axis=1)
    df["시장"] = market
    return df


def load_universe(refresh: bool = True) -> pd.DataFrame:
    """KOSPI + KOSDAQ 전종목 마스터를 하나의 DataFrame으로 반환"""
    if refresh:
        kospi_path = _download_and_extract(_KOSPI_URL, "kospi_code.mst")
        kosdaq_path = _download_and_extract(_KOSDAQ_URL, "kosdaq_code.mst")
    else:
        kospi_path = MASTER_DIR / "kospi_code.mst"
        kosdaq_path = MASTER_DIR / "kosdaq_code.mst"

    df_kospi = _parse_master(kospi_path, _KOSPI_TAIL_WIDTH, "KOSPI")
    df_kosdaq = _parse_master(kosdaq_path, _KOSDAQ_TAIL_WIDTH, "KOSDAQ")
    df = pd.concat([df_kospi, df_kosdaq], ignore_index=True)

    for col in ["시가총액", "전일거래량", "기준가", "상장주수"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def validate_master_df(df: pd.DataFrame) -> dict:
    """파싱이 제대로 됐는지 자체 점검 (자동화 켜기 전 로컬에서 반드시 확인)"""
    report = {
        "총_종목수": len(df),
        "KOSPI_종목수": int((df["시장"] == "KOSPI").sum()),
        "KOSDAQ_종목수": int((df["시장"] == "KOSDAQ").sum()),
        "시가총액_결측비율": float(df["시가총액"].isna().mean()),
        "기준가_결측비율": float(df["기준가"].isna().mean()),
        "샘플_삼성전자_찾음": bool((df["단축코드"] == "005930").any()),
    }
    return report


def filter_tradable_universe(
    df: pd.DataFrame,
    min_market_cap_eok: float = 1000,  # 시가총액 1000억 이상 (단위: 억원)
    min_avg_trading_value_eok: float = 10,  # 참고용, 실제 거래대금은 API 시세로 재확인 필요
    exclude_spac: bool = True,
    exclude_admin_issue: bool = True,
) -> pd.DataFrame:
    """
    스캔 대상(유동성 있는 종목)만 남기는 1차 필터.
    - 관리종목/거래정지/정리매매/불성실공시 제외
    - 시가총액 하한 필터 (초소형주 노이즈 제거, 스윙매매 특성상 유동성 필수)
    - SPAC(기업인수목적회사) 제외
    """
    out = df.copy()

    out = out[out["거래정지"].astype(str).str.strip() != "1"]
    if exclude_admin_issue:
        out = out[out["관리종목"].astype(str).str.strip() != "1"]
        out = out[out["정리매매"].astype(str).str.strip() != "1"]
        out = out[out["불성실공시"].astype(str).str.strip() != "1"]

    if exclude_spac:
        out = out[~out["한글명"].str.contains("스팩|기업인수", na=False)]

    # 시가총액 단위는 마스터파일 기준 보통 '백만원' 단위인 경우가 많아
    # 억원으로 환산할 때 배율을 실제 값 확인 후 조정하세요.
    # (validate 스크립트로 삼성전자 시가총액이 상식적인 범위인지 반드시 확인)
    out["시가총액_억"] = out["시가총액"] / 100  # 백만원 -> 억원 가정, 검증 필요
    out = out[out["시가총액_억"] >= min_market_cap_eok]

    # ETF/ETN/우선주/리츠 등은 종목명 패턴으로 1차 제외 (선택)
    out = out[~out["한글명"].str.contains("리츠|ETN", na=False)]

    return out.reset_index(drop=True)
