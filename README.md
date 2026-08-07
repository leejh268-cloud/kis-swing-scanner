# 종목 스캐너 (스윙 + 단타)

한국투자증권 Open API로 KOSPI+KOSDAQ 전종목을 스캔해서
- **스윙 탭**: 추세(이평선)+모멘텀(MACD/RSI)+거래량 조건이 겹치는 종목, 진입가/목표가/손절가(-3%), 예상 보유기간(3주 이내)
- **단타 탭**: 거래량·외국인/기관 수급 상위 교집합 종목, 당일 매수/목표/손절가

를 매일 자동으로 계산해서 **GitHub Pages 정적 페이지**로 띄우고, 아이폰에서 그 URL만 열어보면 되는 구조입니다.
(GitHub Actions가 서버 역할, 아이폰은 결과만 보는 뷰어입니다. 매매 자체는 이 앱에서 하지 않습니다.)

---

## ⚠️ 시작하기 전에 꼭 읽어주세요

1. **이건 확정된 예측이 아니라 알고리즘 산출값입니다.** 매수가/목표가/보유기간은 기술적 지표 규칙으로 계산한 값이지 미래를 보장하지 않습니다. 최종 투자 판단과 책임은 본인에게 있습니다.
2. **한투 API 스펙은 예고 없이 바뀔 수 있습니다.** 이 코드의 TR_ID/필드명은 한투 공식 GitHub(`koreainvestment/open-trading-api`)와 API 포탈 문서를 기준으로 작성했지만, 실행 전 **반드시 로컬에서 연결 테스트**를 해보세요 (아래 3단계).
3. 초당 요청 제한(실전투자 기준 20건/초)이 있어서, KOSPI+KOSDAQ 전체를 유동성 필터링 없이 다 돌리면 시간이 오래 걸립니다. 기본값은 시가총액 1000억 이상 종목만 스캔하도록 설정되어 있습니다 (`scanner/universe.py`의 `min_market_cap_eok`에서 조정 가능).

---

## 1. 준비물

- GitHub 계정 (무료)
- 한국투자증권 실전투자 계좌 + Open API 앱키/앱시크릿 ([apiportal.koreainvestment.com](https://apiportal.koreainvestment.com)에서 발급)
- 로컬 PC에 Python 3.11+ (최초 연결 테스트용, 이후엔 필요 없음)

## 2. 로컬 설치 (연결 테스트용)

```bash
git clone <이 저장소를 올린 본인의 GitHub repo 주소>
cd kis-swing-scanner
python -m venv .venv && source .venv/bin/activate   # Windows는 .venv\Scripts\activate
pip install -r requirements.txt

export KIS_APP_KEY="발급받은 앱키"
export KIS_APP_SECRET="발급받은 앱시크릿"
```

## 3. 연결 테스트 (자동화 켜기 전 필수)

```bash
python -m scanner.test_connection
```

체크할 것:
- 삼성전자 현재가/일봉이 정상적으로 나오는지
- KOSPI/KOSDAQ 마스터파일 파싱 리포트에서 `시가총액_결측비율`, `기준가_결측비율`이 0에 가까운지
- 삼성전자 시가총액 값이 상식적인 범위인지 (자릿수 확인 → 안 맞으면 `scanner/universe.py`의 단위 환산 배율 조정)
- 거래량순위 / 수급상위 API가 정상 응답하는지 (오류 나면 API 포탈에서 최신 TR_ID 확인 후 `scanner/kis_client.py` 수정)

여기서 문제가 없으면 다음 단계로 넘어가세요.

## 4. 스캔 로컬 실행해보기 (선택)

```bash
python -m scanner.run_swing      # docs/data/swing_results.json 생성 (시간 꽤 걸림)
python -m scanner.run_daytrade   # docs/data/daytrade_results.json 생성 (금방 끝남, 장중에만 의미 있음)

# 결과 확인
cd docs && python -m http.server 8000
# 브라우저에서 http://localhost:8000 접속
```

## 5. GitHub에 올리고 자동화 켜기

1. GitHub에 새 저장소 생성 (Public 권장 — 시크릿은 안전하게 암호화되어 저장되고, 결과 데이터도 민감정보가 아니라서 공개해도 무방합니다. 비공개로 하고 싶다면 GitHub Pages 사용을 위해 Pro 이상 플랜이 필요합니다.)
2. 이 폴더 전체를 push
   ```bash
   git init
   git add .
   git commit -m "init"
   git remote add origin <저장소 주소>
   git push -u origin main
   ```
3. **Settings → Secrets and variables → Actions → New repository secret** 에서 등록
   - `KIS_APP_KEY`
   - `KIS_APP_SECRET`
4. **Settings → Pages** 에서 Source를 "Deploy from a branch", Branch를 `main` / `docs` 폴더로 설정
5. **Actions** 탭에서 `Swing Scan`, `Daytrade Scan` 워크플로를 확인하고, 우측 상단 "Run workflow"로 수동 1회 실행해서 정상 작동하는지 확인
6. Pages URL(예: `https://<아이디>.github.io/<저장소명>/`)이 생성되면, 아이폰 Safari에서 열고 **공유 → 홈 화면에 추가**로 앱처럼 쓸 수 있습니다.

## 6. 실행 주기 조정

- `swing_scan.yml`: 기본 평일 15:45 KST 1회 (장 마감 후)
- `daytrade_scan.yml`: 기본 평일 09:35 / 11:30 / 14:00 KST 3회

cron은 UTC 기준이라 KST는 -9시간입니다. `.github/workflows/*.yml`의 `cron:` 값을 수정하면 됩니다.
GitHub Actions 무료 한도(Public repo는 무제한, Private repo는 월 2,000분)를 고려해서 주기를 정하세요.

---

## 스윙 신호 로직 요약

- **추세**: 종가 > 20일선 > 60일선, ADX(14) ≥ 20
- **모멘텀**: 최근 3봉 내 MACD 골든크로스, RSI(14) 40~65구간
- **거래량**: 당일 거래량이 최근 20일 평균의 1.5배 이상, OBV가 OBV 20일선 위
- **손절**: 고정 -3% (요청하신 기준) + 참고용 ATR 기반 손절가도 함께 표시
- **목표가**: 최근 20일 저항선과 손익비 2:1 목표가 중 보수적인 값
- **보유기간**: 신호 강도에 따라 5~15거래일(약 1~3주)

## 단타 후보 로직 요약

- 거래량 순위 상위 + 외국인/기관 순매수 상위 교집합
- 목표수익률/손절 기준은 `scanner/daytrade_scan.py` 상단 상수에서 조정 가능 (기본 +3.5% / -2.5%)

## 개선 아이디어 (필요하면 추가로 만들어드릴 수 있어요)

- 백테스트 스크립트 (과거 데이터로 이 로직의 승률/손익비 검증)
- 스윙 신호에 상대강도(RS, KOSPI 대비 초과수익률) 필터 추가
- 카카오톡/텔레그램으로 매일 결과 요약 자동 발송
- 관심종목 즐겨찾기, 알림 설정 (프론트엔드 로컬 저장)
