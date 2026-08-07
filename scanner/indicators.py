"""
기술적 지표 계산 모듈
- API와 무관한 순수 계산 로직이라 가장 신뢰도가 높은 부분입니다.
- 입력: 일봉 OHLCV DataFrame (컬럼: date, open, high, low, close, volume), 오래된 날짜가 먼저 오도록 정렬되어 있어야 함
"""
import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's smoothing
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    result = result.where(avg_loss != 0, 100.0)
    return result


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    """Wilder's ADX / +DI / -DI"""
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    tr = true_range(high, low, close)
    atr_val = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_val)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_val)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx_val, plus_di, minus_di


def bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    bandwidth = (upper - lower) / mid
    return upper, mid, lower, bandwidth


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).fillna(0).cumsum()


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    """당일 거래량 / 최근 N일 평균 거래량 (당일 제외)"""
    avg = volume.shift(1).rolling(window=window, min_periods=window).mean()
    return volume / avg


def recent_swing_high(high: pd.Series, window: int = 20) -> pd.Series:
    return high.rolling(window=window, min_periods=1).max()


def recent_swing_low(low: pd.Series, window: int = 20) -> pd.Series:
    return low.rolling(window=window, min_periods=1).min()


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV DataFrame에 모든 지표 컬럼을 추가해서 반환"""
    out = df.copy()
    out["ma5"] = sma(out["close"], 5)
    out["ma20"] = sma(out["close"], 20)
    out["ma60"] = sma(out["close"], 60)

    macd_line, signal_line, hist = macd(out["close"])
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist

    out["rsi14"] = rsi(out["close"], 14)
    out["atr14"] = atr(out["high"], out["low"], out["close"], 14)

    adx_val, plus_di, minus_di = adx(out["high"], out["low"], out["close"], 14)
    out["adx14"] = adx_val
    out["plus_di"] = plus_di
    out["minus_di"] = minus_di

    bb_upper, bb_mid, bb_lower, bb_width = bollinger(out["close"], 20, 2.0)
    out["bb_upper"] = bb_upper
    out["bb_mid"] = bb_mid
    out["bb_lower"] = bb_lower
    out["bb_width"] = bb_width

    out["obv"] = obv(out["close"], out["volume"])
    out["obv_ma20"] = sma(out["obv"], 20)
    out["vol_ratio20"] = volume_ratio(out["volume"], 20)

    out["swing_high20"] = recent_swing_high(out["high"].shift(1), 20)
    out["swing_low20"] = recent_swing_low(out["low"].shift(1), 20)

    return out
