"""
KIS 일봉 API는 한 번 호출에 대략 100영업일 정도만 반환합니다.
백테스트나 지수 이평선 계산처럼 더 긴 기간이 필요할 때, 날짜 구간을 나눠서
여러 번 호출한 뒤 이어붙이는 공용 함수입니다.
"""
from datetime import datetime, timedelta

import pandas as pd

_RENAME_MAP = {
    "stck_bsop_date": "date",
    "stck_oprc": "open",
    "stck_hgpr": "high",
    "stck_lwpr": "low",
    "stck_clpr": "close",
    "acml_vol": "volume",
}

# ⚠️ 지수(코스피/코스닥) 일봉은 종목과 필드명이 다릅니다 (bstp_nmix_ 접두사).
# 실제 응답을 test_connection.py로 확인 후 필요시 후보를 추가하세요.
_INDEX_RENAME_MAP = {
    "stck_bsop_date": "date",
    "bsop_date": "date",
    "bstp_nmix_oprc": "open",
    "bstp_nmix_hgpr": "high",
    "bstp_nmix_lwpr": "low",
    "bstp_nmix_prpr": "close",
    "bstp_nmix_clpr": "close",
    "acml_vol": "volume",
}


def _normalize(rows: list, rename_map: dict = None) -> pd.DataFrame:
    rename_map = rename_map or _RENAME_MAP
    cols = ["date", "open", "high", "low", "close", "volume"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    df = df.rename(columns=rename_map)
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[cols]
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def fetch_extended_stock_ohlcv(client, code: str, total_days: int = 400, chunk_days: int = 95) -> pd.DataFrame:
    """종목 일봉을 total_days(달력일 기준) 만큼, 여러 번 나눠 호출해 이어붙임"""
    all_rows = []
    end = datetime.now()
    remaining = total_days
    while remaining > 0:
        start = end - timedelta(days=chunk_days)
        rows = client.get_daily_ohlcv(code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        if not rows:
            break
        all_rows.extend(rows)
        end = start - timedelta(days=1)
        remaining -= chunk_days

    df = _normalize(all_rows, rename_map=_RENAME_MAP)
    df = df.dropna(subset=["close"]).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df


def fetch_extended_index_ohlcv(client, index_code: str, total_days: int = 400, chunk_days: int = 95) -> pd.DataFrame:
    """지수(코스피/코스닥) 일봉을 total_days 만큼 나눠 호출해 이어붙임"""
    all_rows = []
    end = datetime.now()
    remaining = total_days
    while remaining > 0:
        start = end - timedelta(days=chunk_days)
        rows = client.get_daily_index_ohlcv(index_code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        if not rows:
            break
        all_rows.extend(rows)
        end = start - timedelta(days=1)
        remaining -= chunk_days

    df = _normalize(all_rows, rename_map=_INDEX_RENAME_MAP)
    df = df.dropna(subset=["close"]).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df
