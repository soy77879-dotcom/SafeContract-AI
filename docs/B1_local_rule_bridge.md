# B-1 STEP 2 — 내부 로컬 규칙 분석 후보

## 구현 범위

`integrations.review_analysis.analyze_reviewed_rules(store, owner, document_id, binding)`은 서버의 get_analysis_input으로 검토된 수정본을 조회한 뒤 analyze_rule_snapshot을 호출한다. owner는 기존 인증 세션에서 얻어야 한다. binding은 document_id/document_version/image_sha256만 허용한다. 공개 라우터는 추가하지 않았다.

`analyze_rule_snapshot(store, owner, document_id, binding, snapshot)`은 서버 발행 스냅샷을 한 번 소비한다. analysis_input_guard 잠금을 유지하며 실제 analyze_document에 서버가 검증한 모든 clause_id를 review_ids로 전달한다. AnalyzeRequest의 text는 서버 edited_text이며 ID·페이지를 유지한다. 기존 스키마와 규칙 엔진은 변경하지 않았다.

prepare_rule_response는 잘못된 조항 일부를 제외하고 부분 결과를 만들 수 있다. 이 연결부는 먼저 모든 조항의 ID·페이지·최종 텍스트 및 evidence_span을 확인하여 하나라도 잘못되면 전체 후보 반환을 거부한다. 이후 기존 prepare_rule_response를 호출해 응답 형식·원문 근거·개인정보·단정적 법률 표현을 검증한다.

반환값은 LocalRuleCandidate이며 candidate_response만 기존 AnalyzeResponse 모델이다. publication_allowed와 external_llm_allowed는 항상 false, approval_status는 blocked_response_gate_not_bound다. 응답 본문은 객체 repr에서 제외한다. 이 객체를 HTTP 응답으로 반환하거나 분석 완료 승인으로 사용해서는 안 된다.

## 승인 게이트 미연결 사유

ResponseValidationGate는 서버 프로세서가 처리한 마스킹 이미지 바이트, OCR 텍스트 해시, 원본과의 분리 검증 및 일회용 receipt/response ticket을 요구한다. ReviewStore는 묶음 이미지 해시와 사용자 수정본을 보관하며 해당 게이트의 마스킹 이미지·receipt를 보관하지 않는다. review_app의 이미지 묶음 해시와 TransferGate의 개별 이미지 해시 계산도 다르고, 수정본 텍스트는 최초 OCR 텍스트와 다를 수 있다.

이 차이를 해소하지 않은 상태에서 승인 레코드를 채우거나 mock processor를 만들어 정상 승인처럼 취급하지 않는다. 기존 ResponseValidationGate는 수정하지 않았고 승인 경로를 대체하지 않았다. 로컬 규칙 후보 생성은 완료했으나 최종 결과 공개 승인은 미완료다. /api/analyze는 기존 403 유지.

다음 단계에서는 실제 마스킹 산출물·사용자 수정본·문서 버전에 연결된 신뢰 가능한 서버 승인 문맥을 설계하고 기존 게이트와의 호환성을 검증해야 한다. 이후 결과 공개 시점의 최신성 및 세션/CSRF 검증을 연결한다. 현재 함수의 반환값이나 클라이언트 플래그를 그 승인으로 대체하지 않는다.

## 동시성 및 실패

로컬 규칙 실행과 응답 검증 동안 ReviewStore 잠금을 유지하여 다른 스레드의 수정·무효화를 직렬화한다. 검증 도중 재진입 수정이나 만료는 컨텍스트 종료 검사에서 거부되며 후보를 반환하지 않는다. 토큰 재사용과 텍스트 변조도 차단한다. 검증 이후의 후보는 여전히 공개 미승인이며 이후 편집에 대한 영구 승인으로 사용할 수 없다. 서버 메모리 저장소의 단일 프로세스 제한은 유지된다.

## 실제 테스트

Python 3.11.1의 기존 .venv 사용. 환경 재설치 없음. 합성 조항에 실제 로컬 규칙 엔진 실행; OCR과 LLM은 실행하지 않음.

- 신규 tests/integration/test_review_rule_analysis.py: 22 passed.
- 전체 tests: 408 passed, 18 failed, 2 skipped (27 subtests passed).
- 기존 B-1 STEP 1 및 요청된 검토/병합/응답 검증 테스트는 전체 실행에서 모두 통과.
- 실패 18건은 이전 실행과 동일: tmp/ocr_pages/c001_aligned/structured_contract.json 누락 15건, fitz 누락 2건, cv2 누락 1건.
- 신규 검사: 실제 위험·근거·예상 불이익, 최종 수정본 전달, 미확인/다른 소유자/버전/해시/가짜 승인 차단, 개인정보 및 재검사 오류, 만료/무효화, 토큰 재사용, 근거/페이지/문장/조항 누락 변조, 검증 잠금, 네트워크·가짜 티켓 생성 방지.
- 기존 데이터·backend·scripts·integrations 파일의 작업 시작 해시와 종료 해시 일치. 새 모듈만 추가.
