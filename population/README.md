# 분포를 맞춘 한국 합성 페르소나

state: provisional  
gate: gate_pending

## 최신 변경 (2026-11-04 14시·14시30분·14시35분 지시)

- 유형 비율은 **로저스 2.5/13.5/34/34/16%로 고정**합니다. 다른 비율 설정은 거절합니다.
- `keywords_file`의 L9 한국 소비 성향 사전에서 성향마다 앞쪽+1/뒤쪽−1을 셉니다. 연구 상관계수를 키워드 점수로 사용하지 않습니다. `_` 메타/보류 항목은 제외합니다. 앞쪽 매치 뒤20자 안, 마침표·쉼표 전의 「보다」는 제외하고 새것 회피 정규식은 별도 뒤쪽 신호로 셉니다.
- `keyword_enabled`는 사전 on/off, `age_signal_enabled`는 보조나이 on/off입니다. 기본 보조나이는 꺼져 있습니다. 사전이 없으면 빈 사전으로 진행하고 요약에 missing을 명시합니다.
- `age_tilt=1`은 사전순위를 보존, 0은 10세 나이대 안의 백분위 순위를 씁니다. 중간값은 전체순위와 나이대내순위를 섞습니다. 성별 보정과 같이 켜면 성별 안에서 나이대 순위를 만듭니다. 나이대 **사이** 영향은 제거하지만 나이대 안 세부연령의 상관까지 0을 보장하지 않습니다.
- `sex_balance=within_sex` 기본: 성별 안에서 따로 점수순으로 고정 유형비율을 배정합니다. 모든 유형의 원본 인원 성비가 전체 성비와 거의 같아지며 반올림1명 오차는 남습니다. `none`은 사전순위 그대로입니다. **drinker_ratio 옵션은 폐기**했습니다.
- 음주자 표본은 인구가중치×성·연령 음주확률의 기존 추출을 유지합니다. 전체의 유형 성비를 음주자 성비로 바꾸지 않습니다. 요약에 유형별 평균나이·원본 여성비율·음주자가중 여성비율·원점수/조정순위 나이상관을 같이 적습니다.
- `reaction_mode`: `two_axis_channel` 기본(두 축, 바이럴 크기는 같고 SNS/지인·TV 통로 차이), `two_axis_age`(두 축의 나이효과 큼), `single_axis`(유형 하나값을 두 축에 공용). 세 모드 모두 같은 두 민감도 및 `viral_channel`을 출력합니다. L7과 표준 라이브러리 `traits.py` 함수를 공유합니다.
- **활성 계수는 `reaction_models`**입니다. 이전 `sensitivities`는 이력 호환용 비활성 키이며 계산에 사용하지 않습니다. 모든 반응계수·나이경계는 근거 미정 가설입니다.

실존 인물이 아닌 NVIDIA 합성 페르소나 전체를 공개 인구 통계의 성×연령×시도 분포에 사후 가중합니다. 유형과 반응 성향은 실제 측정치가 아닌 설정 가능한 가설입니다. 판매량 예측 또는 개인별 실제 성향으로 해석하지 않습니다.

## 실행

프로젝트 폴더 `applications/lotte-ax-2026/`에서 실행합니다. parquet 처리에는 Python 3.10 이상과 pyarrow가 필요합니다. 의존성 가상환경은 Vault 밖에 만듭니다. 이번 검증 환경은 `/private/tmp/lotte-l6-env/bin/python`이며 재부팅 후 없어질 수 있습니다. 영구 근거는 `population/`과 반환 폴더에 있습니다.

```bash
python3 -m venv /private/tmp/lotte-l6-env
/private/tmp/lotte-l6-env/bin/pip install -r population/requirements.txt
/private/tmp/lotte-l6-env/bin/python population/download.py
/private/tmp/lotte-l6-env/bin/python population/build.py --config population/config/adopter.json
```

의존성이 준비된 Python에서는 요청한 한 줄로 재생성합니다.

```bash
python3 population/build.py --config population/config/adopter.json
```

- `download.py`: 공개 저장소 revision을 고정하고 전체 shard의 실제 크기 및 SHA256을 확인합니다. 원본+같은 크기의 산출 추정량에 2배의 여유가 없으면 받기 전에 중단합니다. 원본 약 1.98 GB, 보수적으로 필요한 여유 약 7.93 GB. 세부 실측은 `source_manifest.json`.
- `build.py`: 원본 전건 해시 확인 → 칸별 인원 → 신호 점수 순 정렬 → 비율대로 유형 배정 → 통계비율/원본비율 가중 → 전체 parquet 및 시연 표본. 동일 설정·원본·통계·실행환경이면 동일 결과입니다.
- `config/adopter.json`: 로저스 원비율 2.5/13.5/34/34/16%, 문장·나이 신호, 반응 방식, 난수 seed, 표본 수를 모두 설정합니다. 원비율과 다르거나 민감도가 0~1 밖이면 거부합니다. 각 신호와 성향의 근거는 검증 전 가설 또는 미정으로 표시했습니다.
- `stats/population_cells.csv`: KOSIS에서 얻은 성×연령대×시도 인구. 정규화 출처·원자료·기준 시점은 `stats/source.json` 및 같은 폴더의 수집 기록.
- 통계에만 있고 원본에는 없는 양수 인구 칸, 통계가 빠진 원본 칸, 중복 UUID/통계 칸은 조용히 보정하지 않고 중단합니다.

## 산출물

- `out/population.parquet`: 원본 전 열에 `name`, `age_band`, `weight`, `drinker`(0~1 확률), `adopter`, `adopter_score`, `adopter_signals`, `launch_sensitivity`, `viral_sensitivity`, `sensitivity_basis` 추가.
- `out/sample_adults_2000.json`, `out/sample_beer_2000.json`: 시연판 `simulate.py`가 읽는 필드를 보존한 표본. 음주 표본 추출확률은 인구 가중치×월간음주확률에 비례합니다. `drinker`는 개인의 음주 여부 관측치가 아닙니다.
- `out/legacy_enriched.json`: 기존 adults/drinkers 표본 UUID가 전체 원본에 있으면 새 필드를 부착. 1단계 응답과 확산 시연을 정확한 UUID로 연결하기 위한 자료입니다.
- `out/summary.md`, `summary.json`, `cells.csv`: 전 칸의 가중 전후 비교, 유형 비율, 표본 수, 원본 revision과 입력/산출 SHA256.

## 범위와 한계

모집단은 19~99세입니다. 원본에 없는 100세 이상은 통계 모집단에서도 제외하며 제외량은 통계 수집 기록에 남깁니다. 19세는 별도 10대 칸입니다. 월간음주율은 기존 `demo/config/drink_rates.json` 그대로 사용합니다. 기존 코드와 동일하게 19세에는 20대 값을, 70세 이상에는 70대 이상 값을 대입하며 연령별 관측 사실로 주장하지 않습니다.

가중 후 인구분포 일치는 인구 통계의 칸 합을 맞췄다는 뜻입니다. 응답·취향·구매행동이 실제 사람과 같다는 검증은 아닙니다. 유형 비율 검사는 전체 원본의 인원 기준이고 가중치 적용 후 유형 비율과는 다릅니다. 2,000명 시연 표본에는 표본 오차가 있습니다.

문장 신호와 나이 신호는 작업 가설이며, 사용자가 고정한 로저스 비율을 실제 한국 소비자 관측 비율로 해석하지 않습니다. 기존 음주율 파일은 지정된 입력 자산으로 재사용했고 이번 작업에서 조사 원문 수치를 독립 재검증한 것은 아닙니다.

## 출처와 표시

NVIDIA, [Nemotron-Personas-Korea](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea), CC BY 4.0. 원본 자체는 변경하지 않고 별도 산출물에 가중치 및 가설 필드를 추가했습니다. 원본 제작자를 이 파생 결과의 검증자로 표시하지 않습니다. [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

공식 통계는 KOSIS 원본과 기준 시점이 확보된 경우에만 입력으로 사용합니다. 완료 여부와 실측 결과는 반환 README와 `out/summary.json`을 확인합니다.
