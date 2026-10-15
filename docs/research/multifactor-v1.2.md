# BTC Multi-Factor Risk Overlay v1.2 — 구현 및 검증

| Variant | CAGR | MDD | Sharpe | Calmar | PF | Trades | Positive Folds |
|---|---:|---:|---:|---:|---:|---:|---:|
| A — Technical | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| B — Macro | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| C — Macro + Funding | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| D — Full | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

**판정: NEED MORE DATA.** 이 표는 실데이터 연구 결과가 아직 없다는 뜻이며, 수익률 0을 뜻하지 않습니다. 사용자는 Macro 판정 조건과 데이터가 아직 없음을 확인하고 **구현·검증부터 진행**하도록 지정했습니다. 테스트 fixture의 합성 성과를 실제 성과로 제시하지 않습니다.

기준 요구사항은 [Issue #4](https://github.com/seungminbluebox/autoBit/issues/4)와 사용자 제공 v1.2 명세입니다. 이번 변경은 연구 전용입니다. Paper/Live/OCI 배포, 실제 주문, API 키 접근, 실전 잠금 변경은 없습니다.

## 구현 범위

- `src/autobit/risk/multifactor.py`: 불변 Variant A/B/C/D, FactorSnapshot, 순수 위험 축소 함수.
- `src/autobit/backtest/engine.py`: 기존 canonical RiskDecision 이후, 공통 StrategyEngine 직전에 선택적 주입. 기본 A는 기존 경로 그대로입니다. Overlay 결과를 RiskState에 재저장하지 않아 다음 봉에 배수가 누적되지 않습니다.
- `src/autobit/data/factor_dataset.py`: 시점 검증, 만료, Funding rolling percentile, 알려진 이벤트 일정 버전, 실제 판단 시각별 snapshot builder.
- `tools/research/run_multifactor.py`: 동일 기간 A/B/C/D × 등록된 기본/20bps 비용 비교, 기존 Walk-forward·metrics·provenance·원시 셀 저장 재사용.
- 신규 테스트: `test_multifactor.py`, `test_factor_dataset.py`, `test_multifactor_research.py`, `test_multifactor_backtest.py`, `test_multifactor_research_pipeline.py`.

Core의 EMA200, Donchian50/20, ATR14, 초기 2.5ATR, +2R/3ATR 추적, 정체/최대보유 청산, 기존 drawdown risk/recovery, position sizer, 체결 모델은 수정하지 않았습니다. 기존 7년 Baseline 문서와 결과도 덮어쓰지 않았습니다.

## 고정 정책과 판단 범위

Macro는 VIX, US2Y, broad USD, Nasdaq 순서의 엄격한 boolean stress 입력입니다. 각 True는 1점입니다. 문자열, 숫자 0/1, 누락값은 정상 false로 바꾸지 않습니다. 원시 가격으로 stress를 산출하는 판정식은 아직 정의되지 않았으며, 이 구현에서 임의로 추가하지 않았습니다.

Funding percentile은 0~100 단위입니다. 정확히 80은 0점, 80 초과~95 이하는 1점, 95 초과는 총 2점입니다. score 0/1/2/3/4 이상은 1/.75/.50/.25/.10을 기존 risk_rate와 exposure_cap 양쪽에 곱합니다. 기존 0, halt 시각, 모든 기존 risk reason을 보존합니다.

필요 데이터가 없으면 해당 Variant의 신규 진입만 0 risk/cap으로 차단하고 `overlay_data_unavailable`을 기록합니다. 이벤트 blackout은 `overlay_event_blackout`으로 진입만 차단합니다. 이 두 사유는 SYSTEM_EXIT/RISK_EXIT가 아니며 기존 보유 포지션의 보호·추적·종가·위험·시스템 청산은 그대로 유지합니다.

## 데이터와 인과성 계약

이번 체크아웃에는 실제 7년 BTC 원본, macro, funding, 시점별 event calendar가 없습니다. 실데이터 source와 common_start는 **미확정**입니다. 사용한 실행 검증 자료는 저장소의 합성 `tests/fixtures/*.csv`입니다.

1. 캔들 index는 UTC 봉 **시작**입니다. Overlay 판단 T는 `index + 4시간`이며 다음 봉 시가 체결의 실제 경계와 같습니다. 기존 엔진의 기록용 timestamp는 바꾸지 않았습니다.
2. 모든 observation에 `observed_at`, `available_at`, `valid_until`, `evidence`가 필요합니다. timezone 없는 시각은 거부합니다. `observed_at <= available_at < valid_until`이어야 합니다.
3. T에서 `available_at <= T < valid_until`인 가장 최근 입력만 사용합니다. 아직 발표되지 않은 값을 과거에 채워 넣지 않습니다. 만료된 값 또는 새로운 invalid 값이 있으면 이전 정상 값으로 되돌아가지 않습니다.
4. 관측/발표 순서가 단조인 미수정 자료 스트림만 지원합니다. 중복 관측, 사후 수정 vintage, 순서가 뒤집힌 발표는 거부합니다. 수정된 최종 macro 시계열을 원발표 시각으로 위장해서 넣으면 안 됩니다. 빈 evidence는 거부하지만 문자열만으로 실제 출처를 증명할 수는 없으므로, 원본 문서/파일 및 공개 시각의 별도 검토가 필수입니다.
5. Funding은 현재 관측 직전 **90일**의 동일 간격 관측을 요구하고 현재 값은 기준 표본에서 제외합니다. percentile = `100 × count(history < current) / count(history)`입니다. 동률은 초과 점수로 계산하지 않습니다. 이력 중 하나라도 누락/비정상이면 해당 시점은 invalid입니다. 미래 관측을 추가/변경해도 과거 rank는 바뀌지 않습니다.
6. Funding cadence는 입력 명세의 `funding_interval_hours`에 고정합니다. Python API 기본값은 8시간이나 실제 거래소 선택을 뜻하지 않습니다. JSON에는 필수로 명시해야 하며 90일을 정수 개 관측으로 나누는 간격만 지원합니다. 최신 funding은 다음 예정 관측 시각 이후까지 무제한 전방 채움하지 않습니다. 자료의 `valid_until`이 더 짧으면 더 엄격하게 적용합니다.
7. 이벤트는 FOMC/CPI/NFP의 **일정**만 사용하고 발표 결과는 읽지 않습니다. CalendarSnapshot은 당시 알려진 일정 전체와 `available_at`, 완전성을 보증하는 coverage 구간을 담습니다. 알려진 빈 캘린더와 자료 없음은 다릅니다. T±2시간 전체의 coverage가 없으면 D는 진입 차단합니다. blackout 양 끝은 포함합니다. 일정 수정본은 수정본 공개 이후에만 유효합니다.
8. Macro formula, source venue, publication 지연, 유효기간, 원본 provenance가 확정되기 전에는 실제 성과를 해석하거나 채택하지 않습니다. 같은 날짜의 종가를 자정에 이미 알았다고 가정하는 입력은 허용되지 않습니다.

## 입력 파일 계약

UTF-8 JSON schema 1입니다. 아래는 구조 설명용이며 실제 성과 실험용 데이터가 아닙니다. 네 macro key의 observation에는 boolean value, funding에는 숫자 value(비율 단위)를 사용합니다. `evidence`는 보존된 원본 파일/행 또는 공개 시각 증거의 식별자여야 합니다. `source_specification`은 결과를 보기 전에 고정한 정의·출처 문서의 식별자입니다.

```json
{
  "schema": 1,
  "source_specification": "pre-registered-source-and-stress-definition-id",
  "funding_interval_hours": 8,
  "macro": {"vix": [], "us2y": [], "usd": [], "nasdaq": []},
  "funding": [],
  "calendars": []
}
```

Observation 형식:

```json
{
  "observed_at": "2025-01-02T21:00:00+00:00",
  "available_at": "2025-01-02T21:10:00+00:00",
  "valid_until": "2025-01-03T21:10:00+00:00",
  "value": true,
  "evidence": "archived-source-row-id"
}
```

CalendarSnapshot 형식(시각은 예시일 뿐 실제 발표 일정이 아님):

```json
{
  "available_at": "2025-01-01T00:00:00+00:00",
  "coverage_start": "2025-01-01T00:00:00+00:00",
  "coverage_end": "2025-02-01T00:00:00+00:00",
  "events": [{"kind": "CPI", "scheduled_at": "2025-01-15T13:30:00+00:00"}],
  "evidence": "archived-complete-calendar-version-id"
}
```

## 공통 기간과 실행

먼저 전체 BTC prefix로 기존 기술 지표를 계산합니다. 기술 warmup과 모든 D factor가 유효한 첫/마지막 봉으로 하나의 공통 기간을 정합니다. Funding의 완전한 90일 이력도 이 조건에 포함됩니다. 경계 안의 일시적 누락 봉을 삭제하거나 후보별로 기간을 바꾸지 않습니다. 해당 모드만 신규 진입을 차단하며 보고서에 누락 봉 수를 기록합니다. 유효한 이벤트 blackout은 coverage 부족이 아니므로 기간 계산에서 제거하지 않습니다.

공통 기간에 기존 2년 TRAIN / 5일 embargo / 3개월 OOS·step을 사용합니다. 각 fold는 독립 초기자산 100과 terminal liquidation을 사용하고, 지표만 과거 prefix를 봅니다. FULL 비교도 terminal liquidation을 명시하여 모든 후보에 동일 적용합니다. 과거 7년 baseline의 terminal 정책이나 결과를 수정하는 작업은 아닙니다.

코드를 커밋하고 Python 3.12/잠긴 의존성을 준비한 뒤, 저장소 루트에서:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python -m tools.research.run_multifactor \
  --input data/processed/my-data/processed.csv \
  --factors data/processed/my-factors/factors.json \
  --output reports/multifactor-unique-run
```

입력 BTC 폴더에는 기존 형식의 `quality.json`이 필요합니다. 입력 검증 후 clean tracked source만 허용합니다. 기존 출력 폴더는 거부하며 이 실행기는 resume을 지원하지 않습니다. 실패 출력은 삭제하지 않고 보존합니다.

`experiment.json`, tracked `source.zip`, 입력 gzip 사본, 원시 full/TRAIN/OOS 셀과 개별 체크섬, 후보·비용 식별자가 있는 OOS 파일, `comparison.json`, `report.md`, 최종 `SHA256SUMS.json`을 생성합니다. 모든 최종 파일이 만들어져야 완료로 취급합니다. 실제 run에 사용한 source/config/input hash를 기준으로 재현합니다.

## Metrics, 비용, OOS 한계

기존 metrics의 Total Return, annualized return, MDD, Sharpe, Sortino, Calmar, PF, expectancy, win rate, trades, exposure, turnover, fee/slippage를 재사용합니다. 기존 함수가 undefined ratio를 0으로 출력하는 계약도 유지하므로 무거래 PF=0은 성과 증거가 아닙니다. stitched OOS의 exposure/turnover는 기존 stitching 산식에 따른 값이며 per-fold 원시 주문도 보존합니다.

- 기본: 등록된 `baseline` — fee 0.05%, slippage 0.05%.
- Stress: 등록된 `stress_20bps` — fee 0.05%, slippage 0.20%.
- Buy & Hold도 같은 공통 입력 기간과 비용으로 계산합니다.
- Positive Folds는 기존 연구와 동일하게 OOS expectancy > 0인 fold 수입니다.
- DSR은 최소 2개 complete fold가 있을 때 4개 고정 후보 기준으로 계산합니다. 과거 전체 연구 시도 수를 포함한 공식 DSR이라고 주장하지 않습니다.
- **Overlay 전용 purged CPCV 재실행/PBO는 아직 구현·산출하지 않았습니다.** 과거 9개 기술 trial의 PBO를 이번 후보에 붙이지 않으며 `null`과 사유를 출력합니다. 따라서 PBO 악화 없음이라는 채택 조건은 아직 검증 불가합니다.
- 사전 채택 원칙은 MDD·Sharpe·Calmar 개선, PF 유지/개선, positive folds 증가, PBO 악화 없음, 비용 stress 유지입니다. CAGR의 “큰 희생”에 대한 정량 허용치는 미정이므로 결과를 본 뒤 유리하게 정하지 않고 별도 사전 정의가 필요합니다. 기존 validation 기준을 완화하지 않습니다.

## A vs B / B vs C / C vs D

- A vs B: Macro stress 정의와 실제 인과적 데이터가 없어 효과 판단 불가.
- B vs C: 실제 Funding source·90일 warmup·공통 기간이 없어 추가 기여 판단 불가.
- C vs D: 과거 시점별 완전한 일정 snapshot이 없어 Event Guard의 추가 기여 판단 불가.

**v1.2: NEED MORE DATA.** VIX, US2Y, USD, Nasdaq, Funding, Event Guard 모두 **NEED MORE DATA**입니다. 개별 Macro ablation도 하지 않았으므로 B의 집합 효과를 개별 factor 성과로 추정하지 않습니다. 실데이터 성과가 좋더라도 Paper/Live로 자동 전환하지 않습니다.

## 검증 기록

테스트 결과와 환경 제약은 이 절에 최종 기록합니다. 새로운 테스트는 구현 전 실패를 확인한 뒤 구현해 통과시켰습니다. Core golden, default=A의 실제 주문/거래 동등성, 낮아진 실제 체결 수량, blackout 중 기존 hard/trailing/close exit, 시점 경계·누락·invalid·90일 warmup·동일 기간/비용·실제 fold 실행을 검증합니다.

2026-10-16 검증 환경: macOS arm64, CPython 3.12.14, 저장소 지정 uv 0.12.10과 `uv.lock` (`--locked --extra dev`). 기준 `main`은 `d8466e3be8d53a5a388b9cb8db2043e23afc8ec8`입니다.

| 검사 | 결과 |
|---|---|
| 신규 Overlay / dataset / runner / backtest / 실제 OOS·비용·artifact 검증 | **54 passed** |
| 전체 검사, 장시간 validation golden 제외 | **1577 passed, 19 failed, 11 skipped** |
| 별도 장시간 validation golden | **1 failed** — PBO 기대값 불일치 |
| 변경 전 main의 배포 관련 두 테스트 파일 | **40 passed, 동일한 19 failed, 5 skipped** |
| 변경 전 main의 장시간 validation golden | **동일한 PBO 불일치로 1 failed** |

검사 범위가 중복되므로 위 숫자를 합산하지 않습니다. 전체 검사 실행 후 추가한 두 경계/산출물 테스트는 신규 54개 묶음에 포함해 최종 코드로 통과시켰습니다.

배포 19개 실패는 Linux 전용 `/proc/self/fd`, GNU `readlink -m` 및 chmod 동작을 요구하는 기존 테스트가 macOS에서 실행되며 발생했습니다. 11개 skip은 PowerShell 7 부재 6개와 root 권한 요구 5개입니다. 배포 코드를 이번 연구 범위에서 수정하거나 테스트를 무력화하지 않았습니다.

장시간 golden의 실제 PBO는 **0.26666667**, 저장된 기대값은 **0.28888889**였습니다. 변경 전 main에서도 같은 값이 나왔습니다. 이 차이의 세부 원인은 이번 작업에서 해결하지 않았고 기대값을 변경하지 않았습니다. 해당 테스트는 PBO assertion에서 중단되어 후속 바이트 동일성 assertion까지 통과했다고 주장하지 않습니다. 별도 Core/Paper golden, 공통 엔진과 Live 안전성 검사는 전체 검사에서 통과했습니다.

로그는 Git 제외 대상 `reports/multifactor-validation-20261016/`에 보존했습니다. 이것은 검증 로그이며 실데이터 수익률 보고서가 아닙니다. 실제 source/기간 확정, 사전 Macro 정의, 실데이터 A/B/C/D·OOS·stress, Overlay 전용 과적합 검증과 기존 golden 불일치 조사가 다음 연구 단계입니다.

재실행 명령:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests \
  --ignore=tests/regression/test_validation_golden.py -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/regression/test_validation_golden.py -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/unit/test_multifactor.py tests/unit/test_factor_dataset.py \
  tests/unit/test_multifactor_research.py tests/integration/test_multifactor_backtest.py \
  tests/integration/test_multifactor_research_pipeline.py -q
```
