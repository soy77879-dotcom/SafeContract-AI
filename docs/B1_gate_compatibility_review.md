# B-1 승인 게이트 연결 검토

판정: 현재 저장 데이터만으로 ResponseValidationGate의 승인 계약을 충족할 수 없다. 기존 차단을 유지한다. 신규 승인 함수나 프로세서, 가짜 receipt를 만들지 않았다. 이전 미커밋 구현은 그대로 보존했다.

## 실제 계약 비교

| 항목 | 현재 review_app / ReviewStore | 기존 TransferGate / ResponseValidationGate | 결과 |
|---|---|---|---|
| 소유자 | 세션 토큰으로 조회·수정·확인 제한 | 동일 owner로 receipt·response ticket 확인 | 소유자 값 전달은 가능. HTTP 인증/CSRF는 반드시 유지 |
| 이미지 | review_app에서 업로드를 서버 검증/PNG 재생성한 canonical 이미지를 임시 artifact에 보관. OCR 요청에서 artifact를 소비하고 store에는 바이트를 전달하지 않음 | 신뢰 가능한 processor가 만든 masked_image 바이트와 source와의 분리 검증 필요 | store만으로 재구성 불가 |
| 이미지 해시 | SHA256(concat(SHA256(upload_image_i).digest())). 서버 재생성 canonical 이미지 해시가 아니라 제출된 업로드 묶음 해시 | SHA256(masked_image) 단일 이미지 기준 | 한 장이어도 해시 알고리즘이 다름. 문자열 복사로 연결 금지 |
| OCR | build_review_document에 조항 및 연결된 원문 행 보존 | processor의 전체 OCR 행을 줄바꿈으로 연결한 text_hash | 전체 OCR 행 순서·비조항 영역 포함 여부를 store 기록만으로 보장 불가 |
| 최종 수정본 | edited_text 및 확인 당시 조항별 SHA-256 보존 | confirm_analysis_review는 요청 조항을 연결한 텍스트 해시가 최초 processor OCR text_hash와 같아야 함 | 사용자가 수정했거나 조항 구조화 범위가 다르면 불일치. OCR 원문을 수정본으로 가장하면 안 됨 |
| 버전 | save/invalidate마다 문서 version 증가 | masking_revision, generation, TTL에 티켓을 결합 | 문서 수정 버전과 마스킹 버전을 단순 동일시할 수 없음 |
| 사용자 확인 | challenge 및 edited_text 해시 검증 후 확인 ID 저장 | 서버 review hook이 이미지·텍스트·AnalyzeRequest를 receipt에 결합 | store 확인을 기존 게이트 승인 기록으로 자동 복제할 근거 없음 |
| 무효화 | store RLock, 버전·확인 해시·analysis_token 초기화 | gate 별도 RLock, generation 및 일회용 티켓 | 현재 두 저장소의 무효화가 연결되지 않음 |
| 개인정보 | 이미지 검사의 요약 상태 및 수정본 재검사 | 마스킹 이미지에서 processor가 산출한 전체 OCR 재검사 | 요약 상태만으로 기존 게이트의 processor 증빙을 대신할 수 없음 |

## 재사용 가능한 검증과 차단 유지

현재 analyze_rule_snapshot → prepare_rule_response → validate_candidate_response 경로는 기존 parse_response/validate_content를 호출한다. 이는 ResponseValidationGate.validate_response가 사용하는 최종 내용 검증 함수와 같다. 스키마, 근거 문자열, 조항 ID, 개인정보, 단정적 법률 표현 검증은 이미 적용되고 있으며 신규 테스트로 실제 호출과 실패 전파를 확인했다.

내용 검증 통과는 승인 티켓 검증 통과와 다르다. LocalRuleCandidate의 publication_allowed/external_llm_allowed는 false를 유지한다. 정상 후보라도 analysis_token을 ResponseValidationGate의 response ticket으로 전달하면 unapproved_response로 거부된다. 이 시도는 합성 데이터의 테스트에만 존재하며 운영 경로에 추가하지 않았다.

## 안전하게 연결하기 위한 최소 선행 조건

1. 업로드 묶음과 서버 검증된 canonical 이미지의 실제 바이트/해시/순서/페이지를 추적하는 서버 보관 정책을 결정한다. TTL·접근 권한·삭제 정책을 포함하며 원본 재업로드나 원본 로그 저장으로 대체하지 않는다.
2. 전체 OCR 원문과 조항별 최종 수정본의 해시를 구분하고, 사용자 확인 대상인 ID·페이지·수정본·문서 버전에 대한 서버 증빙을 기존 게이트가 어떤 계약으로 수용할지 합의한다. 현재 OCR 해시 일치 조건을 임의로 제거하지 않는다.
3. 문서 수정·만료·마스킹 변경 시 두 저장소의 승인/결과 티켓을 함께 무효화할 수 있는 원자적 연결과 잠금 순서를 정한다. 로컬 후보 생성 후의 변경도 공개 직전에 재검증한다.
4. 신뢰 가능한 서버 경로에서만 실제 게이트 receipt와 일회용 response ticket을 발행한다. 클라이언트 승인 플래그, 내부 analysis_token 또는 합성 processor로 대체하지 않는다.
5. 동일 인증 세션/CSRF 안에서 기존 최종 결과 게이트까지 통과한 경우에만 /api/analyze 연결을 검토한다. 이번에는 해당 라우트의 403을 변경하지 않았다.

위 내용은 새 파이프라인 구현이나 API 변경이 아니라 현재 계약 차이와 필요한 증빙을 기록한 것이다. 승인 증빙이 없는 현 상태에서는 신규 서버 연결 코드를 추가하지 않는 것이 최소 변경이다.

## 테스트

신규 tests/integration/test_review_gate_compatibility.py:
- 기존 최종 내용 검증 함수의 실제 재사용 및 거부 전파
- store에 이미지 바이트/게이트 receipt가 없고 기본 gate가 승인 발행 불가함
- 업로드 묶음 해시와 단일 canonical 이미지 해시 차이
- 내부 analysis_token/미발행/누락 티켓의 승인 거부 및 재사용 거부
- 사용자 수정본과 최초 OCR 해시의 차이 및 수정 시 확인 무효화

합성 문장과 합성 바이트만 사용. 모의 바이트를 실제 이미지 검증 통과나 운영 승인 증빙으로 사용하지 않았다. 승인 게이트 내부 레코드는 조작하지 않았다. 외부 LLM/네트워크 전송 추가 없음. 기존 HTTP 회귀 테스트의 loopback 통신만 실행.

실행 결과 (기존 .venv / Python 3.11.1): 신규 8 passed. 전체 416 passed, 18 failed, 2 skipped, 27 subtests passed. 기존 검토·내부 연결·로컬 분석·승인/응답 검증 회귀는 통과했다. 18건 실패는 이전과 동일한 OCR 임시 결과 파일 누락 15건, fitz 누락 2건, cv2 누락 1건이다. 환경 재설치나 누락 OCR 데이터 생성은 하지 않았다.
