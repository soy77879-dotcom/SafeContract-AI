# A-2 평가 입력·출력 규격 v0.1

## 1. 정답 입력
최상위는 사례 객체의 배열이다.
팀에서 합의한 정답 JSON 형식을 유지한다.

필수 필드:
- case_id: 비어 있지 않은 고유 문자열
- text: 평가 대상 원문
- risk_type: deposit_return / repair_cost / contract_termination
- gold_label: risk / potential_risk / ok / unknown
- label_reason: 라벨 판단 이유
- source: 출처 정보 객체
- legal_basis: 근거 목록
- review_status: 라벨 검토 상태

하나의 사례는 하나의 위험 유형에 대한 판단을 나타낸다.
같은 문장을 여러 유형으로 평가하면 서로 다른 case_id를 사용한다.

## 2. 예측 입력
최상위는 예측 객체의 배열이다.

각 객체의 필수 필드:
- case_id: 대응하는 정답 사례 ID
- risk_type: 정답 사례와 같은 위험 유형
- pred_label: risk / potential_risk / ok / unknown

예측에 gold_label이나 label_reason을 복사하지 않는다.
예측 생성 시 정답 라벨을 분석 엔진에 제공하지 않는다.

## 3. 연결 및 오류 처리
- 배열 순서가 아닌 case_id로 연결한다.
- 중복 ID, 알 수 없는 ID, 잘못된 라벨, 위험 유형 불일치는 오류다.
- 예측 누락은 조용히 제외하지 않고 평가 실패로 알린다.
- 분석 실패를 unknown이나 ok로 임의 변환하지 않는다.
- unknown은 정상적인 판단 불가 라벨이며 처리 실패와 구분한다.

## 4. 위험 상태 지표
- 네 상태 각각을 대상으로 Precision, Recall, F1을 계산한다.
- 분모가 0이면 해당 지표는 0으로 처리한다.
- Macro F1은 항상 네 상태의 F1을 평균한다.
- 혼동행렬의 행은 정답, 열은 예측이다.
- 위험 유형별로도 같은 지표와 평가 건수를 제공한다.

## 5. 오탐·미탐
- 위험 탐지 양성: risk, potential_risk
- 정상: ok
- 오탐: 정답 ok → 예측 risk 또는 potential_risk
- 미탐: 정답 risk 또는 potential_risk → 예측 ok
- unknown과 관련된 오분류는 별도 목록으로 기록한다.
- risk와 potential_risk 사이의 혼동도 별도 오분류로 기록한다.

## 6. 평가 결과 출력
다음 정보를 JSON으로 저장하고 오류 분석 보고서를 생성한다.
- 평가 모드 및 입력 파일 정보
- 전체 평가 건수와 라벨 검토 상태 요약
- 라벨 순서 및 지표 계산 정책
- 상태별 Precision, Recall, F1과 정답 건수
- Macro F1 및 혼동행렬
- 위험 유형별 성능
- 오탐·미탐·unknown 관련 오류 및 기타 오분류 목록

## 7. 개발 평가와 최종 평가
- 합성 데이터의 결과는 평가기 개발·검증용으로 표시한다.
- needs_review 라벨을 확정 정답으로 보고하지 않는다.
- 최종 평가는 A-1이 확정한 독립 테스트셋으로 수행한다.
- 최종 평가 실행 전 검토 완료 표시와 데이터 분리 기준을 합의한다.

## 8. OCR 평가
- OCR 정답 원문과 예측 원문을 문서·페이지 등 합의된 키로 연결한다.
- CER은 문자 편집 거리 / 정답 문자 수로 계산한다.
- 공백·줄바꿈 처리, 빈 정답 처리 및 조항 경계 정답 형식은
  4번 작업에서 기존 OCR 평가 코드 확인 후 별도로 확정한다.
- 위험 라벨 평가용 JSON만으로 OCR CER이나 조항 추출 정확도를
  계산하지 않는다.