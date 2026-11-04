LOTTE AX Challenge 2026 개인 참가 제출물입니다. 롯데칠성음료의 공식 자료나 공식 저장소가 아니며 회사와 무관합니다.

# 칠성 합성 소비자 패널

정량 조사 전에 제품 콘셉트 후보를 비교하는 합성 소비자 패널입니다. 운영 화면에서 시안과 실험을 관리하고, 별도 설문으로 합성 패널이 기관의 주류 통계를 얼마나 재현하는지 확인합니다.

[사전 등록](preregistration-FIT.md)과 [승인 문항](research/fit-questionnaire.md)은 본 실행 전에 커밋했습니다. 날짜는 각 파일의 커밋 기록에서 확인할 수 있습니다. [T0](demo/results/T0/report.md), [T1](demo/results/T1/report.md), [T2](demo/results/T2/report.md), [T3](demo/results/T3/report.md)에서 기준에 미달한 실험과 한계도 공개합니다.

## 실행

Python 3.10 이상과 macOS 또는 Linux에서 저장소 루트를 기준으로 실행합니다. 운영 화면은 로컬 주소에 연결됩니다.

```sh
python3 ops-console/server.py --port 8765
```

브라우저에서 `http://127.0.0.1:8765`를 엽니다. 과거 보고서와 실험 설정은 저장소에 들어 있습니다. 새 시뮬레이션에는 별도로 생성한 모집단·표본과 호출 계정이 필요합니다.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r population/requirements.txt
.venv/bin/python population/download.py
.venv/bin/python population/build.py --config population/config/adopter.json
```

다운로드는 대용량입니다. [모집단 안내](population/README.md)에서 디스크 요구량과 출력물을, [확산 모형 안내](diffusion/README.md)에서 추가 입력과 실행 방법을 확인할 수 있습니다. 정합성 설문 코드는 `demo/fit/`에 있습니다. 실제 호출에는 승인된 표본·문항, 제공사 계정 및 키 설정이 필요합니다.

## 데이터 출처와 해석

- NVIDIA, [Nemotron-Personas-Korea](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). 원본에 성·연령·시도 인구 가중치와 가설 기반 특성을 더합니다.
- 행정안전부 주민등록인구현황, 국가통계포털 KOSIS [행정구역별 1세별 주민등록인구 DT_1B04006](https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1B04006&conn_path=I2), 2025년 12월. [정규화 기록](population/stats/README.md).
- 질병관리청 국민건강영양조사 2024 월간음주율·폭음률, 식품의약품안전처 주류 소비·섭취 실태조사 2020. 정의와 비교 기준은 [사전 등록](preregistration-FIT.md)에 적었습니다.
- 맥주 소매 판매액 점유율은 [aT 집계를 인용한 딜사이트 기사](https://dealsite.co.kr/articles/112698) 등을 참고했습니다. [시장 자료 목록](market-data-inventory.md).

설문 응답은 합성 인물의 모의 응답입니다. 공개 기관 통계와 비교하며, 그 결과만으로 실제 구매행동이나 신제품 판매량을 판단할 수 없습니다. 비교 자료마다 조사 시점과 연령 범위가 다릅니다. [MIT 라이선스](LICENSE)는 이 저장소의 자체 코드에 적용됩니다. 외부 데이터는 각각의 출처와 라이선스를 따릅니다.
