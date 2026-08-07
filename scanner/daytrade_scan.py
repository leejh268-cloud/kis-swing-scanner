"""
단타(당일) 후보 스캔 로직

전종목을 매번 훑는 대신, 한투가 제공하는 '순위' 계열 API(거래량순위, 외국인/기관 수급 상위)를
활용해 이미 시장에서 확인된 강세 종목 풀(각 30종목 내외)을 받아온 뒤 교집합을 구하는 방식입니다.
→ API 호출 수가 적어 장중에도 부담 없이 여러 번 돌릴 수 있습니다.

⚠️ 순위 API의 응답 필드명(stck_prpr, prdy_ctrt 등)은 한투 표준 필드명 기준으로 작성했으나,
실제 응답 JSON을 `python -m scanner.test_connection` 으로 먼저 찍어보고 필드명이 다르면
FIELD_MAP만 고쳐주세요.
"""
STOP_LOSS_PCT_DAYTRADE = -0.025  # 스윙(-3%)보다 타이트하게, 필요시 조정
TARGET_PCT_DAYTRADE = 0.035  # 당일 목표 수익률 기본값 (조정 가능)

FIELD_MAP = {
    "code": ["mksc_shrn_iscd", "code"],
    "name": ["hts_kor_isnm", "name"],
    "price": ["stck_prpr", "price"],
    "change_rate": ["prdy_ctrt", "change_rate"],
    "volume": ["acml_vol", "volume"],
}


def _pick(row: dict, key: str):
    for candidate in FIELD_MAP[key]:
        if candidate in row and row[candidate] not in (None, ""):
            return row[candidate]
    return None


def _to_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _tick_round(price: float) -> int:
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


def build_candidate_pool(volume_rank_rows, investor_rank_rows, min_change_rate=1.0):
    """
    거래량 상위 + 외국인/기관 수급 상위 교집합(또는 합집합 + 가중치)으로 후보 산출
    """
    vol_codes = {}
    for i, row in enumerate(volume_rank_rows):
        code = _pick(row, "code")
        if code:
            vol_codes[code] = {"row": row, "vol_rank": i + 1}

    inv_codes = {}
    for i, row in enumerate(investor_rank_rows):
        code = _pick(row, "code")
        if code:
            inv_codes[code] = {"row": row, "inv_rank": i + 1}

    candidates = []
    all_codes = set(vol_codes) | set(inv_codes)
    for code in all_codes:
        in_vol = code in vol_codes
        in_inv = code in inv_codes
        row = (vol_codes.get(code) or inv_codes.get(code))["row"]

        change_rate = _to_float(_pick(row, "change_rate"))
        price = _to_float(_pick(row, "price"))
        name = _pick(row, "name") or code

        if price <= 0:
            continue
        if change_rate < min_change_rate:
            continue

        # 교집합(둘 다 포함)이면 가점
        overlap_score = 60
        if in_vol:
            overlap_score += 20 - min(20, vol_codes[code]["vol_rank"])
        if in_inv:
            overlap_score += 20 - min(20, inv_codes[code]["inv_rank"])
        both_bonus = 15 if (in_vol and in_inv) else 0
        score = min(100, overlap_score + both_bonus)

        entry = price
        target = entry * (1 + TARGET_PCT_DAYTRADE)
        stop = entry * (1 + STOP_LOSS_PCT_DAYTRADE)

        candidates.append(
            {
                "code": code,
                "name": name,
                "score": round(score, 1),
                "current_price": int(price),
                "entry_price_range": [_tick_round(entry * 0.995), _tick_round(entry * 1.005)],
                "target_price": _tick_round(target),
                "stop_loss_price": _tick_round(stop),
                "expected_return_pct": round(TARGET_PCT_DAYTRADE * 100, 1),
                "risk_pct": round(STOP_LOSS_PCT_DAYTRADE * 100, 1),
                "change_rate_pct": round(change_rate, 2),
                "in_volume_rank": in_vol,
                "in_investor_rank": in_inv,
                "expected_timing": "당일 장중 (익일 오전까지)",
            }
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:15]
