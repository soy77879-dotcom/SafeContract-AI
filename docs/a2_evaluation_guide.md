# A-2 성능 평가 도구 실행 가이드

## 실행 환경
- Python 3.11
- 평가 코드 자체는 Python 기본 라이브러리만 사용한다.
- OCR 모델이나 외부 LLM API 없이 실행할 수 있다.
- 모든 명령은 프로젝트 최상위 폴더에서 실행한다.

## 위험 탐지 평가

터미널 출력:

    python -m scripts.risk_evaluation --gold "data/metadata/mock/gold_mock.json" --predictions "data/metadata/mock/predictions_mock.json"

파일 저장:

    python -m scripts.risk_evaluation --gold "data/metadata/mock/gold_mock.json" --predictions "data/metadata/mock/predictions_mock.json" --output-dir "reports/a2/mock_run_002"

입력:
- 정답은 팀에서 합의한 JSON 배열 형식을 사용한다.
- 예측은 case_id, risk_type, pred_label을 포함하는 배열이다.
- case_id로 연결하며 risk_type은 정답과 일치해야 한다.
- 위험 상태는 risk, potential_risk, ok, unknown이다.
- 중복·누락·잘못된 ID와 라벨은 평가 오류로 처리한다.

출력:
- evaluation_result.json: 전체 지표, 혼동행렬, 유형별 성능,
  오류 사례, 입력 파일 경로와 정답 검토 상태 요약
- error_analysis.txt: 사람이 읽는 지표 요약과 오류 사례 보고서
- 기존 결과 경로는 덮어쓰지 않는다. 재실행 시 새 폴더를 지정한다.

## Mock 데이터의 예상 결과
- 전체 사례: 4개
- 맞힌 사례: 2개
- Macro F1: 0.5
- 오탐: A2-M003
- 미탐: A2-M001

이는 의도적으로 만든 예측의 계산 검증 결과다.
실제 위험 분석 엔진의 성능을 뜻하지 않는다.

## OCR 평가
- scripts/ocr_metrics.py의 evaluate_ocr_texts()를 사용한다.
- 정답·예측 텍스트는 같은 평가 사례 ID로 연결한다.
- Raw CER와 Normalized CER를 함께 반환한다.
- 예측 누락은 빈 문자열로 평가한다.
- 정답이 빈 문자열이면 해당 CER는 null이다.

조항 분리 평가는 evaluate_clause_extraction()을 사용한다.
- 같은 페이지 ID와 같은 기준 텍스트의 start/end 위치를 비교한다.
- 시작 포함·끝 제외의 문자 인덱스를 사용한다.
- 완전히 일치하는 구간을 기준으로 Precision, Recall, F1을 계산한다.
- 서로 다른 OCR 텍스트의 위치를 직접 비교하지 않는다.
- 실제 OCR 결과 적용에는 기준 텍스트와 조항 위치의 검증된 대응이 필요하다.

OCR 평가는 현재 함수와 합성 테스트로 제공된다.
위험 평가 CLI에 OCR 입력 파일을 주는 방식은 지원하지 않는다.

## 테스트 명령

    python -m unittest discover -s tests -p "test_risk_evaluation.py" -v
    python -m unittest discover -s tests -p "test_ocr_metrics.py" -v
    python -m unittest discover -s tests -p "test_evaluation_output.py" -v

예상 테스트 수:
- 위험 평가: 19개
- OCR 평가: 14개
- 결과 출력: 6개

## 실제 데이터 연결 시 주의
- A-1의 정답 검토와 독립 테스트셋 확정은 별도로 필요하다.
- 예측 생성 시 정답 라벨과 label_reason을 엔진에 제공하지 않는다.
- 기존 API의 3개 상태에서 내부 4개 상태를 임의 복원하지 않는다.
- 분석 실패를 ok 또는 unknown으로 바꾸지 않는다.
- 현재 출력은 development_preview다.
- 확정 데이터와 실제 엔진 예측의 최종 성능 측정은 아직 수행하지 않았다.