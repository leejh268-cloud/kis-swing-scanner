"""
로컬에서 먼저 실행해 API 연결과 필드명이 맞는지 확인하는 스크립트입니다.

실행법:
    export KIS_APP_KEY="발급받은 앱키"
    export KIS_APP_SECRET="발급받은 앱시크릿"
    python -m scanner.test_connection

체크리스트:
1. 토큰 발급이 되는가
2. 삼성전자(005930) 현재가/일봉 조회가 정상인가
3. 마스터파일(KOSPI/KOSDAQ) 파싱이 정상인가 (validate_master_df 리포트 확인)
4. 거래량순위 / 수급상위 API 응답 필드명이 daytrade_scan.FIELD_MAP과 일치하는가
   -> 다르면 raw JSON을 보고 FIELD_MAP을 수정하세요.
"""
import json
from datetime import datetime, timedelta

from scanner.kis_client import KisClient
from scanner import universe
from scanner import indicators as ind


def main():
    print("=== 1. 토큰 발급 & 삼성전자 현재가 조회 ===")
    client = KisClient()
    price = client.get_current_price("005930")
    print(json.dumps(price, ensure_ascii=False, indent=2)[:1000])

    print("\n=== 2. 삼성전자 일봉(최근 100일) 조회 ===")
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=150)).strftime("%Y%m%d")
    rows = client.get_daily_ohlcv("005930", start, end)
    print(f"받아온 행 수: {len(rows)}")
    if rows:
        print("샘플(최근 1건):", json.dumps(rows[0], ensure_ascii=False, indent=2))

    print("\n=== 3. KOSPI/KOSDAQ 마스터파일 다운로드 & 파싱 검증 ===")
    df = universe.load_universe(refresh=True)
    report = universe.validate_master_df(df)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("⚠️ 시가총액_결측비율, 기준가_결측비율이 0에 가까워야 정상입니다.")
    print("⚠️ 삼성전자 시가총액(억원 환산) 확인:")
    samsung = df[df["단축코드"] == "005930"]
    if not samsung.empty:
        print(samsung[["한글명", "시가총액", "기준가", "상장주수"]].to_string(index=False))
        print("-> 시가총액 필드가 '백만원' 단위라면 실제 시총(약 300~500조원대)과 자릿수를 비교해보세요.")

    print("\n=== 4. 거래량순위 API 응답 필드 확인 ===")
    try:
        vol_rank = client.get_volume_rank(top_n=5)
        print(json.dumps(vol_rank, ensure_ascii=False, indent=2)[:1500])
    except Exception as e:
        print(f"❌ 거래량순위 API 오류: {e} — TR_ID/파라미터를 API 포탈에서 재확인하세요.")

    print("\n=== 5. 외국인/기관 수급 상위 API 응답 필드 확인 ===")
    try:
        inv_rank = client.get_investor_net_buy_rank(top_n=5)
        print(json.dumps(inv_rank, ensure_ascii=False, indent=2)[:1500])
    except Exception as e:
        print(f"❌ 수급상위 API 오류: {e} — TR_ID/파라미터를 API 포탈에서 재확인하세요.")

    print("\n=== 5-1. 코스피 지수 일봉 조회 (레짐 필터용) ===")
    try:
        idx_rows = client.get_daily_index_ohlcv("0001", start, end)
        print(f" -> {len(idx_rows)}건")
        if idx_rows:
            print("샘플(최근 1건):", json.dumps(idx_rows[-1], ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"❌ 지수 API 오류: {e} — TR_ID/파라미터를 API 포탈에서 재확인하세요.")

    print("\n=== 6. 지표 계산 테스트 ===")
    import pandas as pd

    df_ohlcv = pd.DataFrame(rows)
    if not df_ohlcv.empty:
        # 한투 표준 필드명으로 정리 (stck_bsop_date, stck_oprc, stck_hgpr, stck_lwpr, stck_clpr, acml_vol)
        df_ohlcv = df_ohlcv.rename(
            columns={
                "stck_bsop_date": "date",
                "stck_oprc": "open",
                "stck_hgpr": "high",
                "stck_lwpr": "low",
                "stck_clpr": "close",
                "acml_vol": "volume",
            }
        )
        for c in ["open", "high", "low", "close", "volume"]:
            df_ohlcv[c] = pd.to_numeric(df_ohlcv[c], errors="coerce")
        df_ohlcv = df_ohlcv.sort_values("date").reset_index(drop=True)
        result = ind.compute_all(df_ohlcv)
        print(result.tail(3)[["date", "close", "ma20", "ma60", "rsi14", "adx14", "macd", "macd_signal"]])
        print("✅ 지표 계산 정상 동작")

    print("\n모든 체크가 끝났으면 GitHub Actions 워크플로를 켜세요.")


if __name__ == "__main__":
    main()
