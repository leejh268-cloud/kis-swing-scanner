"""
시장 레짐(국면) 필터

개별 종목 신호가 아무리 좋아도, 지수 자체가 하락 추세일 땐 스윙 승률이
크게 떨어지는 경향이 있습니다. 코스피/코스닥 지수가 각자의 50일 이동평균선
위에 있을 때만 "상승장"으로 판단하고, 그렇지 않으면 해당 시장 종목의 신호를
걸러냅니다 (완전 차단이 아니라 표시만 하고 싶다면 HARD_FILTER=False로 바꾸세요).
"""
from . import indicators as ind
from .data_utils import fetch_extended_index_ohlcv

KOSPI_INDEX_CODE = "0001"
KOSDAQ_INDEX_CODE = "1001"
REGIME_MA_PERIOD = 50

HARD_FILTER = True  # True: 하락장이면 해당 시장 신호 자체를 제외 / False: 표시만 하고 통과는 시킴


def get_market_regime(client) -> dict:
    """
    {"KOSPI": {"bullish": True/False, "close": ..., "ma50": ...}, "KOSDAQ": {...}}
    API 실패 시 보수적으로 bullish=True(필터 미적용)로 처리해 스캔 자체가 멈추지 않게 합니다.
    """
    result = {}
    for market, code in [("KOSPI", KOSPI_INDEX_CODE), ("KOSDAQ", KOSDAQ_INDEX_CODE)]:
        try:
            df = fetch_extended_index_ohlcv(client, code, total_days=120)
            if len(df) < REGIME_MA_PERIOD + 1:
                result[market] = {"bullish": True, "note": "데이터 부족, 필터 미적용"}
                continue
            df["ma"] = ind.sma(df["close"], REGIME_MA_PERIOD)
            last = df.iloc[-1]
            bullish = bool(last["close"] > last["ma"])
            result[market] = {
                "bullish": bullish,
                "close": round(float(last["close"]), 2),
                "ma50": round(float(last["ma"]), 2),
            }
        except Exception as e:
            result[market] = {"bullish": True, "note": f"조회 실패({e}), 필터 미적용"}
    return result


def apply_regime_filter(results: list, regime: dict) -> list:
    """스윙 신호 리스트에 레짐 정보를 붙이고, HARD_FILTER면 하락장 시장의 신호를 제외"""
    out = []
    for r in results:
        market_regime = regime.get(r["market"], {"bullish": True})
        r["market_regime_bullish"] = market_regime.get("bullish", True)
        if HARD_FILTER and not market_regime.get("bullish", True):
            continue
        out.append(r)
    return out
