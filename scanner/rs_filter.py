"""
상대강도(Relative Strength) 필터

같은 상승장이라도 지수보다 덜 오르는 종목보다, 지수보다 더 강하게 오르는
"주도주"가 스윙에서 성과가 좋은 경향이 있습니다. 최근 RS_PERIOD 거래일 동안의
수익률을, 같은 기간 지수(코스피/코스닥) 수익률과 비교해서 지수를 못 이기면
제외합니다.
"""
from .data_utils import fetch_extended_index_ohlcv

KOSPI_INDEX_CODE = "0001"
KOSDAQ_INDEX_CODE = "1001"
RS_PERIOD = 20  # 최근 며칠 수익률을 비교할지 (거래일 기준)
RS_MARGIN = 0.0  # 지수 대비 최소 몇 %p 더 강해야 통과할지 (퍼센트포인트, 0 = 지수만 이기면 통과)


def build_index_return_lookup(client, extra_days: int = 120) -> dict:
    """
    {"KOSPI": {date_str: N일_수익률(%), ...}, "KOSDAQ": {...}}
    각 날짜에서 "그날 종가가 RS_PERIOD 거래일 전 종가보다 몇 % 올랐는지"를 미리 계산.
    """
    lookup = {}
    for market, code in [("KOSPI", KOSPI_INDEX_CODE), ("KOSDAQ", KOSDAQ_INDEX_CODE)]:
        try:
            df = fetch_extended_index_ohlcv(client, code, total_days=RS_PERIOD * 3 + extra_days)
            if "close" not in df.columns or len(df) < RS_PERIOD + 1:
                lookup[market] = {}
                continue
            df["ret_n"] = df["close"].pct_change(RS_PERIOD) * 100
            lookup[market] = dict(zip(df["date"], df["ret_n"]))
        except Exception:
            lookup[market] = {}
    return lookup


def compute_stock_return_n(df_with_ind, period: int = RS_PERIOD):
    """window(오래된 날짜 -> 최신)의 마지막 종가가 period 거래일 전 대비 몇 % 올랐는지"""
    if len(df_with_ind) < period + 1:
        return None
    last_close = float(df_with_ind.iloc[-1]["close"])
    past_close = float(df_with_ind.iloc[-1 - period]["close"])
    if past_close == 0:
        return None
    return (last_close / past_close - 1) * 100


def passes_rs_filter(df_with_ind, market: str, signal_date: str, index_return_lookup: dict) -> bool:
    """
    index_return_lookup이 없거나 해당 날짜 데이터가 없으면 관대하게 통과시킵니다
    (레짐 필터와 같은 원칙: 데이터 부족이 스캔 자체를 막으면 안 됨).
    """
    if not index_return_lookup:
        return True
    market_lookup = index_return_lookup.get(market)
    if not market_lookup:
        return True
    index_ret = market_lookup.get(signal_date)
    if index_ret is None:
        return True
    stock_ret = compute_stock_return_n(df_with_ind)
    if stock_ret is None:
        return True
    return (stock_ret - index_ret) >= RS_MARGIN
