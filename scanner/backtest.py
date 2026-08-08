"""
스윙 전략 백테스트

지금까지 만든 스윙 신호 조건(추세+모멘텀+거래량)을 과거 데이터에 그대로 적용해서,
실제로 신호가 떴을 때 이후 최대 15거래일 동안 목표가/손절가 중 뭘 먼저 쳤는지를
시뮬레이션합니다. "이 규칙이 그럴듯해 보이는가"가 아니라 "실제로 통계적으로
맞는가"를 확인하는 단계입니다.

⚠️ 주의할 점
- 과거 성과가 미래 성과를 보장하지 않습니다.
- 슬리피지(체결가와 신호가의 차이), 수수료/세금은 반영하지 않은 단순화된 시뮬레이션입니다.
- 종목 수(SAMPLE_SIZE)와 기간(LOOKBACK_DAYS)에 따라 결과가 달라질 수 있으니,
  여러 조건으로 돌려보고 일관된 경향이 있는지 확인하는 걸 추천합니다.

실행법:
    python -m scanner.backtest
"""
import time
from datetime import datetime

import pandas as pd

from scanner.kis_client import KisClient
from scanner import universe
from scanner import indicators as ind
from scanner.data_utils import fetch_extended_stock_ohlcv, fetch_extended_index_ohlcv
from scanner.swing_scan import evaluate_swing_signal, MAX_HOLDING_DAYS
from scanner.regime_filter import KOSPI_INDEX_CODE, KOSDAQ_INDEX_CODE, REGIME_MA_PERIOD
from scanner.rs_filter import build_index_return_lookup

SAMPLE_SIZE = 150          # 시가총액 상위 몇 개 종목으로 백테스트할지 (너무 크면 시간이 오래 걸림)
LOOKBACK_DAYS = 450        # 달력일 기준 (영업일 약 300일 = 약 1.2년)
MIN_HISTORY_FOR_SIGNAL = 65  # 지표 계산에 필요한 최소 데이터 길이
USE_REGIME_FILTER = True   # True면 신호 발생일에 해당 시장 지수가 하락장이면 그 거래를 건너뜀
USE_RS_FILTER = False      # ⚠️ 백테스트 결과 손익비 악화(1.04→0.83) 확인되어 기본 비활성화
# 목표가 산출 방식(TARGET_MODE)은 scanner/swing_scan.py에서 관리합니다.
# 백테스트 결과: baseline 1.04 / lower_rr 0.94 / skip_if_capped 1.15(채택)


def build_regime_lookup(client) -> dict:
    """{'KOSPI': {date_str: bool_bullish, ...}, 'KOSDAQ': {...}} 형태로 날짜별 레짐을 미리 계산"""
    lookup = {}
    for market, code in [("KOSPI", KOSPI_INDEX_CODE), ("KOSDAQ", KOSDAQ_INDEX_CODE)]:
        try:
            df = fetch_extended_index_ohlcv(client, code, total_days=LOOKBACK_DAYS + 120)
            if "close" not in df.columns or len(df) < REGIME_MA_PERIOD + 1:
                print(f"  경고: {market} 지수 데이터를 못 가져왔습니다 (필드명 확인 필요). 레짐 필터 없이 진행합니다.")
                lookup[market] = {}
                continue
            df["ma"] = ind.sma(df["close"], REGIME_MA_PERIOD)
            df["bullish"] = df["close"] > df["ma"]
            lookup[market] = dict(zip(df["date"], df["bullish"]))
        except Exception as e:
            print(f"  경고: {market} 지수 조회 실패 ({e}). 레짐 필터 없이 진행합니다.")
            lookup[market] = {}
    return lookup


def simulate_ticker(
    df_with_ind: pd.DataFrame,
    code: str,
    name: str,
    market: str,
    regime_lookup: dict = None,
    index_return_lookup: dict = None,
) -> list:
    """
    한 종목의 전체 기간 동안, 매일 신호 조건을 평가하면서 가상매매를 시뮬레이션.
    신호가 뜨면 그 다음날부터 최대 MAX_HOLDING_DAYS 거래일 동안 목표가/손절가 중
    먼저 닿는 쪽으로 청산, 둘 다 안 닿으면 보유기간 만료 시 종가로 청산.
    regime_lookup이 주어지면, 신호 발생일에 해당 시장이 하락장이었던 거래는 건너뜀
    (실전 스캔의 레짐 필터와 동일 조건으로 비교하기 위함).
    """
    trades = []
    n = len(df_with_ind)
    i = MIN_HISTORY_FOR_SIGNAL
    while i < n - 1:
        window = df_with_ind.iloc[: i + 1]
        signal = evaluate_swing_signal(window, code, name, market, index_return_lookup=index_return_lookup)
        if signal is None:
            i += 1
            continue

        if regime_lookup is not None:
            market_lookup = regime_lookup.get(market, {})
            is_bullish = market_lookup.get(signal.get("signal_date"), True)  # 정보 없으면 통과
            if not is_bullish:
                i += 1
                continue

        entry_idx = i + 1  # 신호 다음날 진입 가정
        if entry_idx >= n:
            break
        entry_price = signal["entry_price"]
        target = signal["target_price"]
        stop = signal["stop_loss_price_fixed3pct"]

        exit_price = None
        exit_reason = None
        exit_idx = None
        for j in range(entry_idx, min(entry_idx + MAX_HOLDING_DAYS, n)):
            day = df_with_ind.iloc[j]
            # 저가가 손절가에 먼저 닿았는지, 고가가 목표가에 먼저 닿았는지 (보수적으로 손절 우선 체크)
            if day["low"] <= stop:
                exit_price, exit_reason, exit_idx = stop, "stop", j
                break
            if day["high"] >= target:
                exit_price, exit_reason, exit_idx = target, "target", j
                break
        if exit_price is None:
            last_j = min(entry_idx + MAX_HOLDING_DAYS - 1, n - 1)
            exit_price = float(df_with_ind.iloc[last_j]["close"])
            exit_reason = "time_exit"
            exit_idx = last_j

        ret_pct = (exit_price / entry_price - 1) * 100
        trades.append(
            {
                "code": code,
                "name": name,
                "signal_date": signal.get("signal_date"),
                "entry_price": entry_price,
                "exit_price": round(exit_price, 1),
                "exit_reason": exit_reason,
                "holding_days": exit_idx - entry_idx + 1,
                "return_pct": round(ret_pct, 2),
                "win": ret_pct > 0,
            }
        )
        i = exit_idx + 1  # 청산 이후부터 다음 신호 탐색 (중복 매매 방지)

    return trades


def main():
    client = KisClient()

    regime_lookup = None
    if USE_REGIME_FILTER:
        print("[0/3] 코스피/코스닥 지수 레짐(날짜별 상승장/하락장) 계산...")
        regime_lookup = build_regime_lookup(client)
        for market, lookup in regime_lookup.items():
            bullish_days = sum(1 for v in lookup.values() if v)
            print(f" -> {market}: 총 {len(lookup)}일 중 상승장 {bullish_days}일")

    index_return_lookup = None
    if USE_RS_FILTER:
        print("[0-1/3] 상대강도(RS) 필터용 지수 수익률 계산...")
        index_return_lookup = build_index_return_lookup(client, extra_days=LOOKBACK_DAYS)

    print("[1/3] 시가총액 상위 종목 선정...")
    df_universe = universe.load_universe(refresh=True)
    df_filtered = universe.filter_tradable_universe(df_universe)
    df_filtered = df_filtered.sort_values("시가총액_억", ascending=False).head(SAMPLE_SIZE)
    print(f" -> 백테스트 대상: {len(df_filtered)}종목")

    all_trades = []
    t0 = time.time()
    for idx, row in enumerate(df_filtered.itertuples()):
        code, name, market = row.단축코드, row.한글명, row.시장
        try:
            df = fetch_extended_stock_ohlcv(client, code, total_days=LOOKBACK_DAYS)
            if len(df) < MIN_HISTORY_FOR_SIGNAL + 10:
                continue
            df_ind = ind.compute_all(df)
            trades = simulate_ticker(
                df_ind, code, name, market, regime_lookup=regime_lookup, index_return_lookup=index_return_lookup
            )
            all_trades.extend(trades)
        except Exception as e:
            print(f"  경고: {code} 백테스트 실패 ({e})")
        if (idx + 1) % 30 == 0:
            print(f"  진행: {idx + 1}/{len(df_filtered)} ({time.time() - t0:.0f}초 경과, 누적 거래 {len(all_trades)}건)")

    print(f"[2/3] 시뮬레이션 완료. 총 가상매매 {len(all_trades)}건")

    if not all_trades:
        print("거래가 하나도 없습니다. 조건이 너무 까다롭거나 데이터가 부족할 수 있습니다.")
        return

    df_trades = pd.DataFrame(all_trades)
    win_rate = df_trades["win"].mean() * 100
    avg_return = df_trades["return_pct"].mean()
    avg_win = df_trades.loc[df_trades["win"], "return_pct"].mean()
    avg_loss = df_trades.loc[~df_trades["win"], "return_pct"].mean()
    avg_holding = df_trades["holding_days"].mean()
    profit_factor = (
        df_trades.loc[df_trades["win"], "return_pct"].sum()
        / abs(df_trades.loc[~df_trades["win"], "return_pct"].sum())
        if (~df_trades["win"]).any()
        else float("inf")
    )
    exit_reason_counts = df_trades["exit_reason"].value_counts().to_dict()

    print("\n[3/3] 결과 요약")
    print("=" * 50)
    print(f"총 거래 수        : {len(df_trades)}건")
    print(f"승률              : {win_rate:.1f}%")
    print(f"평균 수익률(전체)  : {avg_return:+.2f}%")
    print(f"평균 수익률(승리)  : {avg_win:+.2f}%")
    print(f"평균 수익률(패배)  : {avg_loss:+.2f}%")
    print(f"평균 보유일        : {avg_holding:.1f}거래일")
    print(f"손익비(Profit Factor): {profit_factor:.2f}")
    print(f"청산 사유 분포      : {exit_reason_counts}")
    print("=" * 50)
    print("\n※ Profit Factor가 1.0보다 커야 이론적으로 우위가 있는 전략입니다.")
    print("※ 수수료/세금/슬리피지는 반영되지 않았으니 실제 성과는 이보다 낮을 수 있습니다.")

    out_path = "backtest_trades.csv"
    df_trades.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n개별 거래 내역 저장: {out_path}")


if __name__ == "__main__":
    main()
