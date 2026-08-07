"""
단타(당일) 후보 스캔 실행 스크립트

거래량순위 + 외국인/기관 수급상위 API만 호출하므로 가볍습니다.
장중 여러 번(예: 09:30 / 11:30 / 14:00) 실행해도 API 부담이 크지 않습니다.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from scanner.kis_client import KisClient
from scanner.daytrade_scan import build_candidate_pool

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "daytrade_results.json"


def main():
    client = KisClient()

    print("거래량순위 조회...")
    volume_rank = client.get_volume_rank(top_n=30)
    print(f" -> {len(volume_rank)}건")

    print("외국인/기관 수급 상위 조회...")
    investor_rank = client.get_investor_net_buy_rank(top_n=30)
    print(f" -> {len(investor_rank)}건")

    candidates = build_candidate_pool(volume_rank, investor_rank)
    print(f"후보 종목 수: {len(candidates)}")

    output = {
        "generated_at": datetime.now().isoformat(),
        "candidates": candidates,
        "disclaimer": "본 결과는 당일 거래량/수급 데이터 기반 알고리즘 산출값이며 투자 조언이 아닙니다. 단타 매매는 변동성이 매우 크므로 반드시 손절 기준을 지키세요.",
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
