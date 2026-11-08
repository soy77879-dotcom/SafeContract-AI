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

### 문자 인식 평가
- 같은 평가 사례 ID로 정답·예측 텍스트를 연결한다.
- 기존 safecontract-ocr-normalization-v1 정책을 재사용한다.
- Raw CER와 지정된 공백만 제거한 Normalized CER를 함께 계산한다.
- CER = 문자 편집 거리 / 정답 문자 수다.
- 전체 CER는 전체 편집 거리 / 전체 정답 문자 수로 계산한다.
- 정답이 빈 문자열이면 CER는 null이며, 빈 정답 ID를 기록한다.
- 예측 누락은 빈 문자열로 평가하고 누락 ID를 기록한다.
- 정답에 없는 예측 ID는 오류로 처리한다.
- CER는 삽입 오류가 많으면 1을 초과할 수 있다.

### 조항 분리 평가
- 정책: clause-exact-span-v1
- 동일한 페이지 ID와 동일한 기준 텍스트를 사용한다.
- 위치는 Python 문자열의 문자 인덱스이며 시작 포함·끝 제외다.
- 정답과 예측의 시작·끝 위치가 모두 같으면 TP다.
- 일치하지 않는 예측 구간은 FP, 찾지 못한 정답 구간은 FN이다.
- 중복·겹침·범위 밖 구간은 오류로 처리한다.
- Precision, Recall, F1과 페이지별 완전 일치율을 계산한다.
- 지표의 분모가 0이면 해당 지표는 0으로 처리한다.
- 예측 페이지 누락은 해당 페이지의 조항을 모두 미탐으로 계산한다.
- 정답에 없는 페이지 ID나 다른 기준 텍스트는 오류로 처리한다.

### 평가 범위
- 같은 텍스트의 분리 성능과 OCR 문자 인식 성능을 구분한다.
- 서로 다른 OCR 텍스트의 문자 위치를 그대로 비교하지 않는다.
- 실제 파이프라인 평가에는 공통 기준 텍스트의 위치와
  예측 조항을 연결하는 검증된 대응 정보가 필요하다.
- 합성 데이터 결과는 평가 도구 검증용이며 실제 OCR 성능이 아니다.

## 9. 위험 유형별 성능
- 정답의 risk_type으로 사례를 나누어 상태 분류 성능을 평가한다.
- 보증금 반환, 수리비, 계약 해지를 각각 집계한다.
- 전체 및 유형별 혼동행렬의 행은 정답, 열은 예측이다.
- 유형별 Macro F1도 항상 네 상태의 F1을 평균한다.
- 사례가 없는 유형은 not_evaluated, 건수 0, metrics null로 표시한다.
- 위험 유형 자체를 맞히는 분류 정확도와는 구분한다.
- Mock 점수는 평가기 검증용이며 실제 엔진 성능이 아니다.

## 10. 오류 사례 자동 추출
- error_analysis에 정답·오류 건수와 분류별 사례를 기록한다.
- false_positives: 정답 ok → 예측 risk 또는 potential_risk
- false_negatives: 정답 risk 또는 potential_risk → 예측 ok
- unknown_related: 정답과 예측이 다르고 어느 한쪽이 unknown
- risk_label_confusions: risk와 potential_risk 사이의 오분류
- 각 오류 사례에는 case_id, risk_type, text, gold_label,
  pred_label, label_reason을 포함한다.
- 사례는 case_id 순으로 출력하며 입력 데이터를 변경하지 않는다.
- unknown 관련 오류도 전체 상태 분류 지표에는 반영한다.