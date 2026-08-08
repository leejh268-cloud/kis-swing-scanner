"""
스윙매매 스캔 실행 스크립트

흐름:
1. KOSPI+KOSDAQ 마스터 다운로드 -> 유동성 필터링으로 스캔 대상 압축
2. 대상 종목별로 일봉 90일치 조회 (초당 15건 제한, 자동 쓰로틀링)
3. 지표 계산 -> 스윙 신호 조건 평가
4. 결과를 docs/data/swing_results.json 으로 저장 (GitHub Pages가 이 파일을 읽음)

GitHub Actions에서 하루 1회(장 마감 후) 실행하는 것을 기본 전제로 합니다.
"""
import json
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from scanner.kis_client import KisClient
from scanner import universe
from scanner import indicators as ind
from scanner.swing_scan import scan_universe
from scanner.regime_filter import get_market_regime, apply_regime_filter
from scanner.rs_filter import build_index_return_lookup

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "swing_results.json"

# 테스트/디버그용: 환경변수로 스캔 종목 수를 제한할 수 있음 (예: 로컬 테스트시 50개만)
MAX_TICKERS = None  # 예: 300  (None이면 필터 통과 종목 전체)


def fetch_ohlcv_df(client: KisClient, code: str) -> pd.DataFrame:
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=150)).strftime("%Y%m%d")  # 영업일 90일 이상 확보용
    rows = client.get_daily_ohlcv(code, start, end)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.rename(
        columns={
            "stck_bsop_date": "date",
            "stck_oprc": "open",
            "stck_hgpr": "high",
            "stck_lwpr": "low",
            "stck_clpr": "close",
            "acml_vol": "volume",
        }
    )
    keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep]
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    return df


def main():
    client = KisClient()

    print("[0/4] 시장 레짐(코스피/코스닥 추세) 확인...")
    regime = get_market_regime(client)
    for market, info in regime.items():
        status = "상승장" if info.get("bullish") else "하락장(신호 제외)"
        print(f" -> {market}: {status} (종가 {info.get('close')} / 50일선 {info.get('ma50')})")

    print("[0-1/4] 상대강도(RS) 필터용 지수 수익률 조회...")
    index_return_lookup = build_index_return_lookup(client)

    print("[1/4] 종목마스터 다운로드 & 필터링...")
    df_universe = universe.load_universe(refresh=True)
    df_filtered = universe.filter_tradable_universe(df_universe)
    print(f" -> 필터 통과 종목 수: {len(df_filtered)} / 전체 {len(df_universe)}")

    codes = df_filtered["단축코드"].tolist()
    if MAX_TICKERS:
        codes = codes[:MAX_TICKERS]

    meta = {
        row["단축코드"]: {"name": row["한글명"], "market": row["시장"]}
        for _, row in df_filtered.iterrows()
    }

    print(f"[2/4] 일봉 데이터 수집 시작 (종목 수: {len(codes)}, 시간이 걸릴 수 있습니다)...")
    price_data = {}
    fail_count = 0
    t0 = time.time()
    for i, code in enumerate(codes):
        try:
            df = fetch_ohlcv_df(client, code)
            if len(df) >= 65:
                price_data[code] = ind.compute_all(df)
        except Exception as e:
            fail_count += 1
            if fail_count <= 5:
                print(f"  경고: {code} 조회 실패 ({e})")
        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            print(f"  진행: {i + 1}/{len(codes)} ({elapsed:.0f}초 경과)")

    print(f"[3/4] 신호 평가 중... (수집 성공 {len(price_data)}건, 실패 {fail_count}건)")
    results = scan_universe(price_data, meta, index_return_lookup=index_return_lookup)
    results_before_regime = len(results)
    results = apply_regime_filter(results, regime)
    print(f" -> 신호 종목 수: {results_before_regime} (레짐 필터 적용 후 {len(results)})")

    output = {
        "generated_at": datetime.now().isoformat(),
        "scanned_count": len(price_data),
        "universe_count": len(df_filtered),
        "signal_count": len(results),
        "market_regime": regime,
        "results": results,
        "disclaimer": "본 결과는 기술적 지표 기반 알고리즘 산출값이며 투자 조언이 아닙니다. 투자 판단과 책임은 본인에게 있습니다.",
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[4/4] 저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
