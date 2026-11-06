# D-7 STEP 3 핵심 위험 규칙 엔진

## 구현 범위

순수 Python 3.9 모듈 scripts/risk_rules.py와 독립 CLI scripts/run_risk_analysis.py를 추가했다. OCR·GT·FastAPI·백엔드 서버를 import하지 않는다. 기존 파일은 수정하지 않았다. 위험의 법적 확정, API 엔드포인트 및 OCR 수정은 수행하지 않는다.

입력은 구조화 JSON 또는 AnalyzeRequest 형태의 document_id/clauses다. API 입력만으로 사람 검토가 완료됐다고 추정하지 않는다. 내부 verified_text와 needs_review=False가 함께 있거나 호출자가 명시적으로 전달한 review_ids에 해당하는 경우만 검토 텍스트로 취급한다. needs_review=True가 있으면 review_ids로 우회할 수 없다. 검토되지 않은 candidate_text/candidate_regions는 보존만 하며 분석 원문을 대체하지 않는다.

## 규칙과 판단 기준

- 보증금 반환: 임대인·반환 행위·시기/조건을 함께 검사한다. 새 임차인 조건, 지연, 임의 공제는 potential_risk, 명시적 반환 거부는 내부 risk. 종료 시 반환, 입주 여부와 무관한 반환, 공제 부정은 제한된 규칙 범위에서 ok. 협의에 맡긴 조건이나 불명확한 주체는 unknown.
- 수리비: 임대인 부담, 임차인의 고의·과실에 연결된 부담은 ok. 노후화·모든 수리비 전가 또는 임대인이 임차인에게 비용을 부담시키는 조건은 potential_risk. 주체 혼재·별도 협의·부당/부담 의심 문구는 unknown. 비용을 전가하지 않는 부정 표현을 구별한다.
- 해지: 채무 불이행·최고를 전제로 한 해제는 ok. 광범위한 임차인 해지 불가는 내부 risk. 잔여 월세 전액 위약금·일방의 조건 결정·해지와 연결된 몰수는 potential_risk. 금액만 있는 위약금은 unknown이며 임의의 과도성 금액 기준을 만들지 않는다.

문장 단위 주체·행위·조건을 검사하고 조항 내 다만/예외/적용 배제는 보수적으로 unknown 처리한다. 부정 표현과 숫자·기간을 문맥 정보로 기록한다. 문장 분리 및 규칙 매칭용 공백 제거는 원문·OCR 평가 정책에 적용하지 않는다. evidence는 analysis_text의 정확한 slice이며 offset을 저장한다. 같은 조항·유형은 한 건으로 집계하고 서로 다른 유형은 복수 결과를 허용한다.

관련 단어만 있거나 검사 범위와 관계없는 조항은 안전 판정하지 않는다. unrelated/unknown으로 별도 기록한다. 빈 텍스트도 unknown이며 유효한 AnalyzeRequest가 아니라는 점은 입력 경계에서 별도 검증해야 한다.

## 실제 API와 첨부 예시 차이 처리

실제 backend/schemas.py 및 API_SPEC.md를 우선해 외부 API를 변경하지 않았다.

| 내부 | API |
|---|---|
| risk / potential_risk | potential_risk |
| ok | no_risk_detected |
| unknown | needs_review |
| contract_termination | termination |
| unrelated | other + needs_review |
| followup_questions 배열 | question 문자열(줄바꿈 결합) |
| recommended_actions 배열 | recommended_action 문자열(줄바꿈 결합) |

검사한 관련 유형이 모두 ok인 조항은 기존 규격대로 risk_type=none, no_risk_detected 한 건으로 반환한다. unknown이 있으면 응답 status=partial 및 warnings를 기록한다. API에 없는 페이지·원문·후보·review 상태·여러 질문은 내부 JSON에 보존한다.

입력과 실제 AnalyzeResponse 결과는 원본 스키마에서 필요한 클래스와 타입 정의만 분리 실행해 검증했다. 전체 backend 모듈 import나 서버 실행 성공과는 다르다. Python 버전/의존성 문제는 이전 상태 그대로이며 이 작업에서 수정하지 않았다.

## 실행

```bash
# 실제 구조화 OCR: 검토되지 않은 19개 조항의 판단은 보류
python scripts/run_risk_analysis.py

# 다른 구조화 JSON 또는 AnalyzeRequest JSON
python scripts/run_risk_analysis.py --input tmp/ocr_pages/structured_release/structured_contract.json

# 사람이 확인한 합성 개발 예시임을 명시하는 직접 입력
python scripts/run_risk_analysis.py --text '임차인이 중도해지하는 경우 남은 계약기간의 월세 전액을 위약금으로 지급한다.' --reviewed-test-text

python -m unittest discover -s tests -v
```

매번 tmp/risk_analysis/run_*에 internal_result.json과 analyze_response.json을 생성한다. 기존 출력 폴더를 덮어쓰지 않는다. 터미널에는 조항 수·상태 수·경로만 출력하며 계약서 전문을 출력하지 않는다. 결과 파일에는 원문이 있어 로컬 임시 폴더에서만 관리한다.

## 실제 결과

최종 실행: tmp/risk_analysis/step3_final/ (C001 정렬 이후 데이터). 이전 structured_release 입력도 tmp/risk_analysis/step3_release_cache/에서 실행 확인했다.

19개 조항 모두 needs_review인 입력이며, 21개 유형별 결과는 전부 unknown이다.

| 관련 유형 | 결과 수 | 상태 |
|---|---:|---|
| 보증금 반환 | 3 | unknown |
| 수리비 | 4 | unknown |
| 해지 | 6 | unknown |
| 세 유형 관련 근거 없음 | 8 | unknown |

중복 조항이 아니라 일부 조항에 여러 관련 유형이 존재한다. 공식 표준계약서라는 이유로 ok를 부여하거나 키워드만으로 위험을 판정하지 않았다. GT를 원문으로 치환하지 않았다.

별도 합성 예시 10건 실행: ok 2, potential_risk 3, risk 2, unknown 3. synthetic_examples.json에 원문과 결과를 보존했다. 이는 개발 예시이며 독립적인 사람 검증 위험 데이터나 정확도 지표가 아니다.

## 테스트

| 구분 | 통과 |
|---|---:|
| 기존 OCR/구조화 | 59 |
| 보증금 반환 | 11 |
| 수리비 | 13 |
| 계약 해지 | 10 |
| 공통·원문·검토·API | 18 |
| 합계 | 111 |

실패 0. 책임 주체 전환, 비용 전가의 사역 표현, 부정/이중부정, 예외, 미검토 OCR, 후보 비적용, 정확한 근거 offset, 중복 ID, schema field/type 검증을 포함한다. 보호 대상 22개 파일의 해시는 변경되지 않았다. 상세 실행 로그는 tmp/risk_analysis/step3_final/verification.json에 있다.

## 한계와 다음 연동

규칙은 제한된 한국어 표현을 다루는 개발용 휴리스틱이다. 복잡한 주체 생략·인용·교차 조항·대명사·다중 예외를 완전히 해석하지 못한다. 예외가 있으면 보수적으로 보류하여 미탐지/과도한 검토 요청이 생길 수 있다. ok는 검사한 표현에서 위험 신호 미탐지일 뿐 법적 안전을 뜻하지 않는다. 높은 confidence도 검토 승인을 대체하지 않는다.

다음 단계는 별도의 사람이 검토한 정상/잠재 위험/문맥 부족 사례를 확보해 독립 평가하는 것이다. 서버 연결 시 사용자 확인을 마친 텍스트와 신뢰 가능한 검토 메타데이터를 전달하고, 분석 텍스트와 AnalyzeRequest.text가 동일한지 확인한다. 현재 API에는 OCR 검토 메타데이터 필드가 없으므로 내부 전달 방식은 담당자 B와 합의해야 한다. 프런트 입력의 임의 review 표시를 신뢰해서는 안 된다.

## GitHub Desktop

이번 신규 파일만:
- scripts/risk_rules.py
- scripts/run_risk_analysis.py
- tests/test_risk_rules.py
- docs/d7_risk_rules_report.md

기존 파일 수정 없음. tmp/, PDF, .venv/ 제외. 이전 작업의 미추적 파일은 이번 변경과 별도로 검토한다.

추천 커밋: `feat: implement core rental contract risk rules`

dev/01 유지. commit/push/merge/PR 생성 미실행.
