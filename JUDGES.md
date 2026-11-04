# AI 심사위원용 검증 안내

[제출용 브리핑 PDF](briefing.pdf)

- LOTTE AX Challenge 2026 개인 참가 제출물입니다. 롯데칠성음료와 무관합니다.
- 용도는 정량 조사 전 콘셉트 스크리닝입니다.
- 사전 등록 FIT는 5개 조건을 각 3회, 동일한 합성 표본 300명에게 반복했습니다. 15회, 4,500개 판정 대상 응답 자리입니다.
- 주 분석의 V1·V2·V3 대표성 기준은 모두 미달했습니다. 주종 순위 상관은 0.96, 평균 절대 차이는 19.10%p였습니다.
- 운영 시연에서 대표성 미달로 신제품 가상 실행을 차단했습니다. 에이전트가 원인 진단과 선별을 수행했고, 작가가 새 검증을 승인했습니다.
- 문항·응답 방식을 바꾼 새 검증에서도 남성 고위험음주율은 실제 18.4% 대비 1~2%였습니다. 이후 음주 프로필·주음용 브랜드는 실측 자료로 부여하고, 모델에는 진열대 선택만 묻도록 바꿨습니다.
- [테라 결과]

## 주장과 근거

| 주장 | 수치 또는 관측 | 공개 저장소 상대 경로와 근거 커밋 | 종류 | 확인 방법 |
|---|---|---|---|---|
| 기준과 문항을 본 실행 전에 공개 | 09:20:43Z → 09:41:34Z | [preregistration-FIT.md][prereg], [research/fit-questionnaire.md][questions] · `750c6524951f00224a5a43df78fde8d53e93f7b5`; [docs/data/fit.json][snapshot] · `335676320c687f63c1409e62dcf3354765c21a75` | 공개 기록 및 실행 기록 | 커밋 시각, `prereg.locked_at`, `run.started_at` 대조 |
| 정합성 검증 완료 | 15회 · 4,500개 응답 자리, 전체 요청 4,526건 | [results/FIT/registered/report.md][fit] · `e5128090dd3fd965f2df21468af9eb40bac956fe`; [docs/data/fit.json][snapshot] · `335676320c687f63c1409e62dcf3354765c21a75` | 측정 | 호출 경로와 조합별 반복·응답 자리 확인 |
| 대표성 기준 미달 | 조합 3의 V1 16.99%p, V2 31.09%p, V3 19.10%p | [results/FIT/registered/report.md][fit] · `e5128090dd3fd965f2df21468af9eb40bac956fe` | 측정 | 조합 3 표를 아래 기준에 대입 |
| 경쟁 세트 재현 미달 | T2 최하위 1/5, 약한 짝 57.1%; T3 0/5, 42.9%; T4 주 지표 최하위 2/5 | [demo/results/T2/report.md][t2], [demo/results/T3/report.md][t3] · `6c01560106a73ecce5fcd6b6c9544f5b0df5e401`; [docs/data/T4.md][t4] · `335676320c687f63c1409e62dcf3354765c21a75` | 측정 | 최하위 적중 열과 약한 제품 포함 쌍대 정확도 확인 |
| 대표성 미달이면 실행 차단 | 공개 스냅샷 `gate.allowed=false`; 테스트에서 실행 거부와 감사 기록 확인 | [docs/data/overview.json][overview] · `335676320c687f63c1409e62dcf3354765c21a75`; [ops-console/test_gate.py][gate] · `047357ad501d970e7783af5d25bd562201585484` | 구현 및 시험 | 스냅샷과 서버 게이트 단위 시험 확인 |
| 실측으로 보정 후 재판정 | 문항 원문 대조 → 실측 확보 시 보정·검증 표본 분리 → 같은 대표성 기준으로 반복 검증 | [preregistration-FIT.md][prereg] · `750c6524951f00224a5a43df78fde8d53e93f7b5` (재판정 기준) | 계획 | 보정과 검증의 분리 여부, 공개된 최종 판정 확인 |

## 사전 등록과 판정 규칙

2026-11-04 UTC 기준 공개 사전 등록 커밋은 09:20:43Z, 본 실행 시작은 09:41:34.598098Z입니다. 시작 시각은 공개 스냅샷에 남긴 실행 기록입니다. 주 분석은 전체 서술 페르소나 + Terra + 문항 A입니다.

| 항목 | 사전 등록 규칙 | 결과 |
|---|---|---|
| RQ1 / V1 월간음주율 | 남녀 각각 절대 차이 10%p 이내 | 남자 +18.05%p, 여자 −15.92%p. 미달 |
| RQ1 / V2 폭음률 | 성별·연령 6칸 순위 상관 0.8 이상, 평균 절대 차이 10%p 이내 | 0.52, 31.09%p. 미달 |
| RQ1 / V3 주종 | 10종 순위 상관 0.8 이상, 평균 절대 차이 10%p 이내, 상위 2개 맥주·소주 | 0.96, 19.10%p, 상위 맥주·소주. 미달 |
| RQ1 종합 | 조합 3의 3회 평균으로 V1·V2·V3 모두 통과 | 대표성 미달 |
| RQ2 정보 기여 | 전체 서술의 평균 절대 차이가 정보 없음보다 작고 개선폭이 해당 조건 3회 반복의 변동폭보다 커야 함. 3개 중 2개 이상 충족 시 종합 기여. 정보 없음의 V1·V2 비교값은 전체 59.7%, 37.8% | V1·V2·V3 개선 23.31·6.71·1.34%p, 변동폭 1.92·0.65·0.16%p. 기여 있음. V2·V3에서는 인구통계만 제공한 조합보다 오차가 커져 단계별 감소 가설은 부분 지지 |
| RQ3 판정 안정성 | 조합 3·4·5의 RQ1 종합 판정 일치 | 모두 미달로 안정. 조합 4의 V2만 개별 통과 |
| H4 세그먼트 방향 | 혁신자·초기 수용자와 후기 다수·지체자 간 위스키·리큐르·과실주 선택률 차이가 반복 변동폭을 넘어야 함. 같은 연령군 안에서도 보고 | 종합 지지 없음. 연령 상관 −0.43 |

응답 자리 계산은 5개 조합 × 3회 × 300명입니다. 4,500개 자리에는 형식 제외 3건이 포함됩니다. 같은 300명을 반복하므로 95% 구간은 등록 보고서 방식대로 가장 작은 해당 분모를 사용한 Wilson 근사이며 기관 통계의 조사오차는 포함하지 않습니다.

## 구현과 검증 범위

- **구현** · 인구 분포 가중, 모의 응답 및 집계 실행기, 기존 경쟁 세트 재현과 자극물 민감도 점검, 운영 화면 8개, 설정 잠금, 역할별 승인, 감사 기록, 서버 실행 게이트. 공개 웹은 읽기 전용입니다.
- **실증한 운영 과정** · 사람이 기준·실행 범위를 승인하고, 에이전트가 승인된 시험을 실행·집계하며, 운영 서버가 판정에 따라 실행을 제어했습니다. 아래는 이 운영 과정의 공개 근거입니다.
- **검증 예정 범위** · 같은 문항의 실제 소비자 직접 대조, 출시 후 시장 예측 검증, 가격·용량 비교와 구전 확산의 실측 효과. 판매량·손익 추정은 범위 밖입니다.

### 운영 프로세스 실증

시각은 2026-11-04 한국 시각(KST)의 공개 커밋 시각입니다. 새 검증은 선별에 쓰지 않은 합성 응답자와 새 문항을 사용합니다.

| 단계 | 수행·승인 | 상태 | 공개 커밋 및 시각 |
|---|---|---|---|
| 사전 등록 | 작가가 문항과 기준을 확정하고 본 실행을 승인 | 등록 완료 | [750c652][ops-prereg] · 18:20:43 |
| 대표성 검증 | 에이전트가 설문 실행과 집계 | 미달 판정 기록 | [e512809][ops-fit] · 19:27:12 |
| 미달 시 차단 | 운영 서버가 시연에서 신제품 가상 실행 거부 | 차단 확인 | [3356763][ops-block] · 19:46:15 |
| 원인 진단 | 에이전트가 기관 문항 원문과 오차 패턴을 대조 | 진단과 시험 계획 공개 | [48d4b25][ops-diagnosis] · 20:53:59 |
| 30명 선별 | 작가가 사용할 실행 경로를 승인하고 에이전트가 보정 후보 선별 실행 | 선별 완료 | [9b09f31][ops-screen] · 21:07:38 |
| 새 표본·새 문항 검증 | 작가가 재설계와 실행 범위를 승인하고 에이전트가 검증 실행 | 결과 공개 · 기준 미달 | [da8d842][ops-holdout] · 21:18:31 (계획), [1e5aa02][holdout-result] · 21:56:17 (집계) |
| 통과 범주만 해제 | 운영 서버는 대표성과 같은 모델·모집단의 경쟁 세트 재현 등 실행 요건을 확인 | 조건부 운영 규칙 · 해제 사례 미확인 | [e512809][ops-rule] · 19:27:12 |

## 근거의 세 층

| 층 | 확인 대상 | 근거와 적용 범위 |
|---|---|---|
| 부여 정확도 | 인구·음주·주음용 브랜드 구성 | KOSIS 인구 가중, [실제 음주 프로필 부여와 검증용 70% 비교][assignment], [aT 목표 비율 대비 배정][terra-assignment]. 구성 점검과 신제품 선택 판정은 별도입니다. |
| 백테스트 | 2018년 4분기 출시 전 시장을 부여한 테라 진열대 | [사전 등록][terra-prereg]. 중립 7종, 이름 공개·가림 양쪽에서 테라가 카스보다 낮고 하이트·클라우드보다 높아야 통과. Claude는 참고입니다. |
| 검증 절차 | 승인과 사전 등록, 집계 대조, 차단과 실패 기록 | 위 운영 프로세스 표와 공개 실행 기록. 기존 FIT 집계는 봉인 응답으로 별도 재계산해 대조했습니다. |

- **부여 정확도** · [부여 정확도]
- **테라 백테스트 판정** · [테라 결과]
- **데이터 연결 계획** · 성·연령별 구매 자료는 브랜드 배정, 사내 조사 원자료는 보정·검증, 출시작 판매·단종은 과거 출시 검증, 실제 가격은 카드의 추정 칸 교체에 사용합니다.

## 재현 방법

저장소 루트에서 다음 명령을 실행합니다. 공개 집계를 읽고 판정을 확인하는 단계와 서버 시험은 키가 필요 없습니다.

```sh
git show -s --format='%H %aI %cI' 750c6524951f00224a5a43df78fde8d53e93f7b5
python3 - <<'PY'
import json
from pathlib import Path

fit = json.loads(Path("docs/data/fit.json").read_text())["data"]["fit"]["data"]
print(fit["prereg"]["locked_at"], fit["run"]["started_at"])
print(sum(c["reps"] for c in fit["combos"]), sum(c["responses"] for c in fit["combos"]))
print(fit["own_verdict"])
PY
python3 -B -m unittest discover -s ops-console -p test_gate.py
```

- **원 응답 재집계** · `python3 demo/fit/summarize.py --out fit-summary-rebuilt.json`. 원 실행의 체크포인트 DB, 실행 로그, 등록 보고서와 동일 모집단 파일이 로컬 경로에 있어야 합니다. 이미 확보한 원 응답을 읽는 단계라 키를 호출하지 않습니다. 체크포인트와 페르소나 응답 원문은 비공개이므로 공개 저장소만으로 이 단계의 재집계를 할 수 없습니다.
- **새 모의 응답 수집** · 동일 모집단과 표본을 준비하고 제공사 계정·키를 구성한 뒤 `python3 demo/fit/main_run.py --published-prereg-commit 750c6524951f00224a5a43df78fde8d53e93f7b5`를 실행합니다. 새 호출은 제공사 비용이 발생할 수 있으며 결과가 과거와 같다는 보장은 없습니다.

## 해석 한계

- 기관 통계와 합성 표본은 조사 시점·문항·연령 범위가 다릅니다. V3 기관 자료는 15세 이상, 합성 표본은 19세 이상입니다.
- 1순위 선택률은 콘셉트 매력도 지표입니다. 실제 점유율이나 매출로 환산하지 않습니다.
- T4 주음용 유효 선택은 133/750건이며 일부 세트에는 유효 선택이 없습니다. 사전 카드 스냅샷과 실행 전 카드 판본의 차이도 남아 있습니다.
- 공개 운영판의 실행 차단은 시스템 동작 증거입니다. 실제 조사비 절감이나 상용 운영 성과는 측정하지 않았습니다.

[prereg]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/750c6524951f00224a5a43df78fde8d53e93f7b5/preregistration-FIT.md
[questions]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/750c6524951f00224a5a43df78fde8d53e93f7b5/research/fit-questionnaire.md
[fit]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/e5128090dd3fd965f2df21468af9eb40bac956fe/results/FIT/registered/report.md
[snapshot]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/335676320c687f63c1409e62dcf3354765c21a75/docs/data/fit.json
[overview]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/335676320c687f63c1409e62dcf3354765c21a75/docs/data/overview.json
[t2]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/6c01560106a73ecce5fcd6b6c9544f5b0df5e401/demo/results/T2/report.md
[t3]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/6c01560106a73ecce5fcd6b6c9544f5b0df5e401/demo/results/T3/report.md
[t4]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/335676320c687f63c1409e62dcf3354765c21a75/docs/data/T4.md
[gate]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/047357ad501d970e7783af5d25bd562201585484/ops-console/test_gate.py
[ops-prereg]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/commit/750c6524951f00224a5a43df78fde8d53e93f7b5
[ops-fit]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/e5128090dd3fd965f2df21468af9eb40bac956fe/results/FIT/registered/report.md
[ops-block]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/335676320c687f63c1409e62dcf3354765c21a75/docs/data/overview.json
[ops-diagnosis]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/48d4b258af65bd3a58991564860f1425a78ca6d8/explore/PLAN.md
[ops-screen]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/9b09f31d969957d4119c2299c74cbb521a4536ef/explore/stage-c1.md
[ops-holdout]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/da8d8426506f2f8517ef59d0f14f1488f8525945/explore/PLAN.md
[ops-rule]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/e5128090dd3fd965f2df21468af9eb40bac956fe/ops-console/fit_console.py

[holdout-result]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/1e5aa02af4847979a6c8383cca2e33a965eb5325/explore/stage-c2.md
[assignment]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/10856ab92b36269022d422d0c8185592b7b18350/explore/stage-p-assign.md
[terra-assignment]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/f8fa7f2058d16b7b302cdccf2bc8487ddfe12e71/explore/stage-t-assign.md
[terra-prereg]: https://github.com/ljhljh0703-cmd/chilsung-synthetic-consumer-panel/blob/f8fa7f2058d16b7b302cdccf2bc8487ddfe12e71/preregistration-TERRA.md
