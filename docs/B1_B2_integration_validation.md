# B-1/B-2 통합 오류 수정 및 검증 (2026-11-10)

## 재현과 수정

작업 시작 환경: dev/01, .venv Python 3.11.1. 최초 재현은 358 passed, 1 failed, 2 skipped였다. 사용자 기존 변경인 test_b2_error_handling.py 및 test_b2_privacy_security.py는 작업 시작 바이트 그대로 보존했다.

1. test_masking_to_ocr_response의 422: review_app이 masked_images/ masked_hashes keyword 인자로 증빙을 전달하지만 FakeStore.register는 이 인자를 받지 않았다. inspect.signature(...).bind로 `TypeError: got an unexpected keyword argument 'masked_images'`를 직접 재현했다. 공통 middleware가 내부 예외를 안전한 422로 변환했다. 티켓/CSRF/이미지 해시 오류가 아니었다.
   - FakeStore를 ReviewStore 상속형 관찰용 저장소로 바꾸고 실제 register를 호출했다. mock OCR도 문서 ID만 반환하던 것을 조항·페이지·원문을 포함하는 유효 구조로 수정했다. 기존 진단 메시지는 보존했고 실제 전달 바이트/해시/응답 텍스트 검증을 추가했다.
   - 서버 검증, HTTP 기대 상태, API 스키마는 완화하지 않았다.
2. 새 E2E로 발견한 최종 검증 중 만료 오류: 기존 pipeline은 분석 중 검증은 했으나 최종 gate.validate_response가 진행되는 사이 문서 만료 시 성공을 반환할 수 있었다. RLock은 시간 경과를 막지 못한다.
   - 기존 review_evidence_guard를 전체 내부 파이프라인에 적용하여 최종 검증 직후에도 증빙을 재검증한다. 만료·동일 스레드 재진입 무효화 시 결과를 폐기하고 게이트 티켓도 무효화한다. 기존 실패 코드와 정보 비노출 정책 유지.

## 테스트 실행 결과

명령: `.venv/bin/python -m pytest tests/integration -q -rs --tb=short`

최종: 363 passed / 0 failed / 2 skipped, 7 subtests passed, 9 warnings.
신규 test_b1_b2_pipeline_e2e.py: 4개 모두 통과. 기존 B-2 error_handling 12개, privacy_security 11개, fastapi_io 3개 모두 통과.

기존 skip 유지 (새 skip 추가/테스트 삭제 없음):
- test_actual_structured_schema: tmp/ocr_pages/c001_aligned/structured_contract.json 과거 실제 OCR 결과 없음. 임의 데이터로 대체하지 않음.
- RealReviewHTTP.test_real_paddleocr_full_flow: RUN_REAL_REVIEW 명시 활성화가 필요한 실제 OCR 테스트. 현재 .venv에서 paddleocr/paddle도 설치되지 않음.

## 실제 연결 범위

| 단계 | 검증 상태 |
|---|---|
| 이미지 입력 | 실제 FastAPI ASGI 요청, session/CSRF/multipart 처리 검증 |
| 마스킹 | 기존 verify_mask subprocess 실제 실행. 합성 PNG의 검은 영역 검증·재인코딩 및 바이트 변경 확인 |
| OCR | 운영 OCRProcess 호출 경로 존재. 신규 E2E는 명시적 mock OCR로 원문/페이지/조항 구성; 실제 PaddleOCR 미실행 |
| 개인정보 재탐지 | E2E 이미지 OCR 스캐너는 mock no_candidates. 기존 개인정보 텍스트 검증 및 보안 회귀 통과 |
| 사용자 검토 | HTTP confirm으로 실제 challenge·텍스트 해시 검증; 미검토 분석 차단 |
| 사용자 수정 | HTTP draft 후 원문 보존·버전 증가·재확인 검증. 수정 시 마스킹 증빙 삭제 정책에 따라 분석은 계속 차단 |
| 내부 승인/분석 | 실제 ReviewStore + VerifiedLocalResponseGate를 테스트에서 연결하여 run_local_review_analysis 직접 호출. 실제 위험 규칙과 최종 응답 게이트 실행 |
| 공개 분석 API | /api/analyze는 403. run_local_review_analysis 호출 없음. 기본 review_app은 일반 ResponseValidationGate 사용이며 VerifiedLocalResponseGate 내부 흐름과 공개 연결 미완료 |
| PDF | 별도 scripts/ocr_pages.py의 PDF 이미지화/OCR 실험 경로 존재. review_app의 업로드는 masked PNG만 허용. PDF를 공개 API 입력으로 추가하지 않음 |

코드 검색에서 run_local_review_analysis의 호출자는 통합 테스트이며 공개 라우터 호출자는 없다. 신규 테스트가 내부 연결을 명시적으로 구성한 것이지 운영 앱이 자동 연결된 것은 아니다.

## E2E 네 가지

1. 합성 이미지 HTTP 입력 → 실제 마스킹 워커 → 모의 OCR → HTTP 사용자 확인 → 실제 내부 승인/로컬 규칙/응답 검증 성공. 미검토 시 거부, 마스킹 티켓 재사용 거부, 공개 API 403, 내부 분석 동안 socket 사용 금지 확인.
2. HTTP 수정·재확인 후 원문 불변 및 버전 증가 확인. 이전 티켓과 신규 분석을 기존 정책대로 차단.
3. 최종 결과 검증 도중 문서 만료 시 결과 미공개.
4. 최종 결과 검증 도중 문서 무효화 시 결과 미공개.

## 남은 작업

- 실제 PaddleOCR/PaddlePaddle 환경과 과거 OCR fixture를 복구하고 opt-in 실제 OCR 테스트를 별도로 실행.
- 편집 후 마스킹 증빙 재결합은 현재 정책에서 허용하지 않으므로 별도 승인된 설계 필요. 테스트 통과를 위해 증빙을 복원하지 않음.
- 공개 /api/analyze 연결은 별도 승인 작업. 서버 인증·CSRF·gate/store 인스턴스 연결 및 공개 시점 검증을 유지해야 함.
- PyMuPDF/SWIG deprecation 및 TestClient 수집 경고는 남아 있으나 이번 실패 원인은 아님.

## 변경 범위

이번 수정: integrations/review_local_pipeline.py, tests/integration/test_b2_fastapi_io.py.
이번 생성: tests/integration/test_b1_b2_pipeline_e2e.py, 본 문서.
기존 미커밋 error_handling/privacy_security 변경 보존. backend/main.py, API 스키마, 위험 규칙, 골든셋/법률 데이터, 기타 기존 파일은 작업 시작 해시와 동일. 가상환경 설치/변경 없음. 외부 LLM 호출 없음. commit/push/PR/merge/브랜치 전환 없음.

추천 커밋 메시지: `fix: B-1/B-2 저장소 인터페이스 정합성 및 최종 승인 만료 검증 보완`
