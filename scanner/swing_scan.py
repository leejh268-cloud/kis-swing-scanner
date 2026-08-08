"""
스윙매매 스캔 로직

조건 (교집합 방식):
1. 추세: 정배열 조짐 (종가 > MA20 > MA60) + ADX14 >= 15 (횡보장 필터링, 기존 20에서 완화)
   + 과열 필터: 종가가 MA20 대비 8% 이상 떨어져(위로) 있으면 제외 (막 오른 종목 추격 매수 방지)
2. 모멘텀: MACD 골든크로스 (최근 3봉 이내) + RSI14가 35~70 구간 (기존 40~65에서 확대)
3. 거래량: 당일 거래량이 최근 20일 평균의 1.3배 이상 (기존 1.5배에서 완화) + OBV가 OBV 20일선 위

가격 산출:
- 진입가: 최근 종가 (지정가 매수 시 참고용)
- 손절가: 진입가 * 0.97 (요청하신 -3% 고정) — 단, ATR 기준 손절폭도 함께 표기해 비교 가능하게 함
- 목표가: 최근 20일 저항선(swing_high20)과 R:R 2:1 목표가 중 더 보수적인(가까운) 값
- 예상 보유기간: 신호 강도에 따라 5~15 거래일(약 1~3주) 범위로 제시
"""
import pandas as pd
from . import indicators as ind

STOP_LOSS_PCT = -0.03  # 요청하신 손절 기준 고정값
MAX_HOLDING_DAYS = 15  # 3주(거래일 기준 약 15일) 이내
MAX_EXTENSION_ABOVE_MA20 = 0.08  # 종가가 20일선보다 이 비율 이상 높으면 "과열"로 보고 제외


def _tick_round(price: float) -> int:
    """한국 주식 호가단위에 맞춰 대략 반올림 (참고용 근사치)"""
    if price < 2000:
        unit = 1
    elif price < 5000:
        unit = 5
    elif price < 20000:
        unit = 10
    elif price < 50000:
        unit = 50
    elif price < 200000:
        unit = 100
    elif price < 500000:
        unit = 500
    else:
        unit = 1000
    return int(round(price / unit) * unit)


def evaluate_swing_signal(df_with_ind: pd.DataFrame, code: str, name: str, market: str) -> dict | None:
    """
    지표가 계산된 일봉 DataFrame(오래된 날짜 -> 최신 날짜 순)을 받아
    스윙매매 신호 여부와 점수, 진입/목표/손절가를 반환. 조건 미충족이면 None.
    """
    if len(df_with_ind) < 65:
        return None  # MA60 계산에 필요한 최소 데이터 부족

    last = df_with_ind.iloc[-1]
    prev = df_with_ind.iloc[-2]

    if pd.isna(last[["ma20", "ma60", "adx14", "rsi14", "macd", "macd_signal", "vol_ratio20", "atr14"]]).any():
        return None

    close = float(last["close"])

    # --- 조건 1: 추세 ---
    not_overextended = close <= last["ma20"] * (1 + MAX_EXTENSION_ABOVE_MA20)
    trend_ok = close > last["ma20"] > last["ma60"] and last["adx14"] >= 15 and not_overextended
    trend_strength = min(100, max(0, (last["adx14"] - 15) * 3))  # 0~100 스케일 근사

    # --- 조건 2: 모멘텀 (최근 3봉 내 MACD 골든크로스) ---
    recent = df_with_ind.iloc[-4:]
    macd_cross_recent = (
        (recent["macd"] > recent["macd_signal"]).astype(int).diff().fillna(0) == 1
    ).any()
    rsi_ok = 35 <= last["rsi14"] <= 70
    momentum_ok = macd_cross_recent and rsi_ok

    # --- 조건 3: 거래량 ---
    volume_ok = last["vol_ratio20"] >= 1.3 and last["obv"] >= last.get("obv_ma20", float("inf"))

    if not (trend_ok and momentum_ok and volume_ok):
        return None

    # --- 점수 산출 (교집합 강도) ---
    score = 0
    score += 34 if trend_ok else 0
    score += 33 if momentum_ok else 0
    score += 33 if volume_ok else 0
    # 세부 가점
    if last["vol_ratio20"] >= 2.0:
        score += 5
    if last["macd_hist"] > prev["macd_hist"] > 0:
        score += 5
    score = min(100, score)

    # --- 가격 산출 ---
    entry = close
    stop_fixed = entry * (1 + STOP_LOSS_PCT)
    stop_atr = entry - 1.5 * float(last["atr14"])

    resistance = float(last["swing_high20"]) if not pd.isna(last["swing_high20"]) else entry * 1.1
    risk = entry - stop_fixed
    target_rr = entry + 2 * risk  # 손익비 2:1
    target = min(resistance, target_rr) if resistance > entry else target_rr

    if target <= entry * 1.01:
        return None  # 목표가가 사실상 없으면(저항이 바로 위) 스킵

    # 예상 보유기간: 점수가 높을수록 짧게, 낮을수록 길게 (최대 3주)
    if score >= 85:
        holding = "약 5~10거래일 (1~2주)"
    elif score >= 70:
        holding = "약 8~12거래일 (2주 내외)"
    else:
        holding = "약 10~15거래일 (2~3주)"

    return {
        "code": code,
        "name": name,
        "market": market,
        "score": round(score, 1),
        "close": int(close),
        "entry_price": _tick_round(entry),
        "target_price": _tick_round(target),
        "stop_loss_price_fixed3pct": _tick_round(stop_fixed),
        "stop_loss_price_atr_ref": _tick_round(stop_atr),
        "expected_return_pct": round((target / entry - 1) * 100, 1),
        "risk_pct": round(STOP_LOSS_PCT * 100, 1),
        "holding_period": holding,
        "rsi14": round(float(last["rsi14"]), 1),
        "adx14": round(float(last["adx14"]), 1),
        "vol_ratio20": round(float(last["vol_ratio20"]), 2),
        "ma20": int(last["ma20"]),
        "ma60": int(last["ma60"]),
        "signal_date": str(last["date"]) if "date" in last else None,
    }


def scan_universe(price_data: dict, universe_meta: dict) -> list:
    """
    price_data: {code: DataFrame(OHLCV, 지표포함)} 형태
    universe_meta: {code: {"name": ..., "market": ...}}
    """
    results = []
    for code, df in price_data.items():
        meta = universe_meta.get(code, {})
        try:
            r = evaluate_swing_signal(df, code, meta.get("name", code), meta.get("market", ""))
        except Exception:
            r = None
        if r:
            results.append(r)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results
