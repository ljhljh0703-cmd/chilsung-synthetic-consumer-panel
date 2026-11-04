---
state: provisional
gate: gate_pending
proposed_by: external_ai (via Codex)
confirmed_by: null
---
# 2단계 가상 SNS 확산 시연

2026-11-04 추가: 작가가 공개 합성 속성 전송을 직접 승인했고 UUID는 전송에서 제거했다. 1명 실모델 시험과 세 방식 비교6호출 성공(새 실호출 합계7, 고유4명). 이전 권한 거절/오류 기록은 반환의 v1.1 기록에 보존한다.

규칙 모드 기본, Python 표준 라이브러리만 사용. **실제 확산 정답이 없어 검증 전 시연**이며 판매량·흥행 예측에 쓰지 않는다. 실제 1단계의 가상 선택 응답에서 시안을 선택한 UUID만 첫 구매자로 연결한다. 기존 `demo/` 파일은 읽기만 한다.

## 실행

`applications/lotte-ax-2026/`에서:

```bash
python3 diffusion/run.py --exp example --config diffusion/config/default.json
python3 diffusion/test_diffusion.py
```

비교 실험:

```bash
python3 diffusion/run.py --exp high --config diffusion/config/high_sensitivity.json --compare diffusion/out/terra_rules/summary.json
```

설정 파일 안 입력 경로는 현재 셸 위치와 무관하게 `applications/lotte-ax-2026/` 기준이다. `--config`, `--compare` 인자는 셸 기준이다. 이미 사용한 실험 이름에서 입력·설정·코드가 달라지면 중단하며 새 이름이 필요하다.

## 반응 방식 선택과 한 번에 비교

기본 설정은 `reaction_config=population/config/adopter.json`, `reaction_mode=two_axis_channel`이다. L6의 `reaction_values`를 그대로 불러 성향을 계산하므로 같은 설정과 인물이면 L6/L7 값이 같다. 실제 사용한 L6 설정 사본을 출력에 남긴다.

- `two_axis_channel`: 출시·바이럴 두 축과 SNS / 지인·TV 두 관계망. SNS는 취미, 지인·TV는 지역·나이 유사성 비중이 크다. 자기 선호 통로에서 후기를 내고, 다른 통로 노출은 `cross_channel_visibility`만큼 줄인다. 지인·TV는 실제 방송 모델을 재현한 것이 아니다.
- `two_axis_age`: 연령에 따른 두 반응 성향, 단일 관계망.
- `single_axis`: 유형별 한 값을 두 성향에 동일 적용, 단일 관계망.

```bash
python3 diffusion/run.py --exp mode_compare --config diffusion/config/default.json --compare-modes
```

`--compare-modes`는 같은 1단계·인물 입력을 세 방식으로 실행하고 누적 구매자 곡선을 하나의 PNG에 겹쳐 그린다. 언어모델 모드이면 `max_calls_total`과 `max_people_total`을 **세 모드 합산** 상한으로 보고 먼저 3등분한다. 할당량이 남아도 다른 모드로 옮겨 쓰지 않는다. 비교의 `comparison_modes.json`에 합산 사용량·설정 해시·모드별 결과를 남긴다.

로저스 유형 비율은 L6 설정과 같아야 한다. 반응 방식만 바꾸는 비교에서 유형 비율을 임의 변경하면 거절한다. 모든 새 계수는 근거 미정인 실험 가정이다.

## 입력과 L6 연결

- `sample_files`: 기존 시연판 형식의 JSON 배열. UUID·나이·지역·취미 등을 읽는다. 중복 UUID의 내용이 충돌하면 중단한다.
- 기본은 기존 음주자 1,500명+성인 1,000명의 합집합에서 최초 구매자를 모두 포함한 2,000명이다. 인구 대표 표본이 아니다.
- L6 `population/out/legacy_enriched.json`을 연결하면 기존 1단계 UUID와 유형·성향을 함께 쓸 수 있다. 새 무작위 L6 표본에 최초 구매자가 빠졌으면 중단한다. UUID를 복제하거나 새 구매자를 만들지 않는다.
- 입력 모두에 `adopter`, 숫자 `launch_sensitivity`, 숫자 `viral_sensitivity`가 있으면 먼저 읽는다. `reaction_config`가 지정된 최신 모드에서는 adopter·weight를 보존하고 성향은 공유 함수로 다시 계산한다. 없는 기존 표본은 설정의 문장 신호+나이 점수 순서에 정확한 유형 할당량을 붙인다. 동점은 UUID 순이다.
- `population.use_input_traits=false`이면 설정 비율을 바꿔 유형을 재배정할 수 있다. `population.types`의 숫자는 **근거 미정인 시연 가정**이다.
- `weight`는 보존하지만 노드는 현재 모두 같은 비중으로 작동한다. 노드 구매 비율을 대한민국 소비자 구매 비율로 환산하지 않는다.
- `stage1_file`, `product_id`, `stage1_rep`를 명시한다. SSR 변환 결과 파일이 아닌 원래 `choice`가 들어 있는 JSONL을 넣는다.

## 한 주의 동작

1. 기존 구매자가 설정 확률×바이럴 성향에 따라 후기를 올린다. 전주 재전파 대기도 포함한다.
2. 연결된 친구가 설정 확률로 후기를 본다. 한 주의 노출을 합쳐 구매·무시·재전파를 계산한다.
3. 노출당 구매 확률은 `purchase_multiplier × ((1-launch_influence) × viral_sensitivity + launch_influence × launch_sensitivity)`, 여러 번 봤을 때는 `1-(1-p)^노출수`다. 노출수는 상한을 둔다.
4. 기존 구매자의 재구매를 별도로 계산한다. 새 구매자와 재전파는 다음 주부터 전파에 참여한다.

관계망은 양방향, 자기 연결·중복 연결 없음. 각 인물이 무작위 후보군에서 지역·나이·취미 유사성의 가중치로 친구를 고른다. 평균 친구 수는 결과에서 실측한다. 나이 차는 지수 감소, 취미는 단어 집합 Jaccard 유사도다. 이 규칙의 계수와 행동 확률은 전부 설정 파일에 있으며 **실제 SNS로 검증하지 않았다**. 관계망은 고정이고, 음주자 여부·구매력·실제 제품 평가·부정 후기·재고·이탈은 아직 반영하지 않는다.

## 언어모델 모드와 제한

`mode=llm`이면 회차마다 일부 후기와 반응에 기존 `demo/llm.py`의 `ask_json`을 호출한다. Codex의 빈 임시 작업 폴더와 웹 검색 금지 옵션을 유지하고, 기존 모델·계정 설정을 사용한다. 나머지 인물은 규칙으로 계산한다.

- 전체 고유 인물, 회차 인물, 전체 호출 수, 호출 대기시간 상한이 각각 있다.
- 응답 없음·시간초과·잘못된 응답이면 **해당 회차 전체**를 규칙 모드로 다시 계산하고 원인을 기록한다. 일부 성공 응답을 적용한 상태로 계속하지 않는다.
- 응답 성공과 실패를 `llm_cache/`에 보존한다. 같은 입력의 재실행은 캐시를 재생한다. 새 모델 응답의 재현성을 난수 고정만으로 주장하지 않는다.
- 요청 backend·model·effort가 달라지면 기존 응답 캐시를 쓰지 않는다. 실제 모델명·생각 깊이는 호출 로그에서 추출한 경우만 저장하고, 못 받은 값은 unknown으로 둔다.
- 상한을 다 쓰면 남은 회차는 `rules_budget_exhausted`로 기록한다. 재전파 문장은 규칙 모드에서 지어내지 않는다.
- 이전 실모델 smoke는 권한 차단 후 fallback했고 상승 권한 재시도는 자동 검토가 거절했다. 이후 작가가 공개 합성 속성·상한·기존 Codex 경로 전송을 명시 승인했으며 UUID 제거 후 `terra_authorized_smoke`에서 1명 성공했다. 과거 `terra_live_smoke`와 거절 원문은 그대로 보존한다.

제품 속성 전체를 언어모델 프롬프트에 넣지는 않는다. 후기·반응 문장은 시연용이며 실제 맛·품질 평가로 쓰지 않는다.

## 산출물

`out/<실험>/report.md`, `curve.png`, `summary.json`, `people.json`, `network.json`, `input_locked.json`, `execution.json`.

- 보고서 첫 줄: `검증 전 시연`.
- 누적 구매자는 중복 없는 인물 수. 재구매는 사건 수여서 한 사람이 여러 번 포함될 수 있다.
- 전체 입력 경로·SHA-256, 설정·코드 해시, 최초 구매자 UUID, 회차별 구매·후기·재전파 UUID가 남는다.
- `execution.json`만 실행시간 때문에 달라진다. 규칙 모드 결과 5개 파일의 SHA-256 재현을 확인했다.
- PNG는 외부 이미지 편집 없이 표준 라이브러리로 그린 수치 선 그래프다.

## 구조 참고와 라이선스

2026-11-04 원문 확인. 외부 코드를 복사하거나 의존성으로 설치하지 않았다.

| 자료 | 확인한 구조 | 라이선스 |
|---|---|---|
| [MiroFish README](https://github.com/666ghj/MiroFish) | 관계망, 환경·인물 설정, 시뮬레이션, 보고를 분리. OASIS 사용 명시 | [AGPL-3.0](https://github.com/666ghj/MiroFish/blob/main/LICENSE) |
| [OASIS README](https://github.com/camel-ai/oasis) | 인물 관계망·회차 환경·수동/모델 행동, 후기·재전파 | [Apache-2.0](https://github.com/camel-ai/oasis/blob/main/LICENSE) |
| [NVIDIA Nemotron-Personas-Korea](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea) | 기존 합성 인물 원천. 이번 코드에서 유형·성향·망을 추가 | CC BY 4.0 |

이 참고는 독립 구현의 구성 아이디어에 한정한다. OASIS 재현이나 MiroFish 수준의 예측 성능을 주장하지 않는다.
