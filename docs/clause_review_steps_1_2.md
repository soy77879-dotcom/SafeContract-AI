# 조항 원문 연결 및 OCR 수정 UI — STEP 1~2

## 범위

이번 네 가지 과제 중 STEP 1(조항 원문 연결), STEP 2(사용자 수정 UI)만 완료했다. STEP 3 규칙·LLM 결과 병합과 STEP 4 원문 근거 검증 통합은 진행하지 않았다. 기존 D-6 응답 검증 모듈도 수정하지 않았다. 자동 분석 요청·외부 LLM 호출은 없다.

## STEP 1

기존 `structure_ocr.api_response()`와 저장된 구조화 결과/API 미리보기를 재사용한다. `integrations/adapter.py`의 OCR API 규격은 변경하지 않았다. 별도 로컬 검토 문서(sidecar)를 만들어 아래 정보를 보존한다.

- document_id, clause_id, 시작 page 및 전체 pages
- 변경 불가 raw_text와 별도 edited_text
- source_lines의 페이지, 실제 line_id, 원문, 기존 polygon
- 구조화 파일 및 OCR 페이지 파일의 SHA-256
- expected_clause_ids와 문서·조항 수정 버전

ID 중복·누락·순서, 문서 및 페이지 일치, 원문과 실제 출처 줄의 일치를 검사한다. 좌표가 없으면 null이며 임의 생성하지 않는다. 좌표 단위는 PDF 포인트가 아니라 기존 OCR 입력 이미지 픽셀이다.

실제 캐시 `tmp/ocr_pages/c001_aligned/structured_contract.json`, `api_ocr_response.json`, `tmp/ocr_pages/ocr_pages_result.json`을 사용했다. 총 5페이지를 처리한 문서에서 C001~C019 19개 조항은 1~2페이지에 있다. 3~5페이지의 내용을 조항으로 임의 생성하지 않았다. 모든 조항을 needs_review로 시작하며 Ground Truth의 검증 상태를 사용자 검토로 복사하지 않았다.

## STEP 2

로컬 파일 선택 → ID/페이지 목록 → 원본 OCR와 수정본 나란히 비교 → 개별 수정/취소 → 개별 검토 완료 → 진행률 → 로컬 JSON 저장 흐름이다. 모바일에서는 비교 영역을 세로로 배치한다.

- 원문은 읽기 전용이고 수정본은 textarea로 편집한다.
- 수정 취소는 해당 OCR 원문으로 돌아가며 다시 needs_review가 된다.
- 검토 완료는 해당 버튼을 눌렀을 때만 설정한다. 빈 수정본은 검토 완료할 수 없다.
- 완료 후 수정하면 해당 조항의 확인 상태를 취소한다. 다른 조항을 자동 완료시키지 않는다.
- 이미지·마스킹 상태 변경은 전체 조항 UI를 초기화한다. 오래된 비동기 파일 읽기도 무효화한다.
- 파일 가져오기, 수정, 취소, 검토 동작은 기존 개인정보 검사 상태를 pending으로 돌린다. 이 동작은 개인정보 재검사를 실제로 수행했다는 뜻이 아니다.
- 사용자 입력은 textContent/value로 표시하며 HTML로 해석하지 않는다. OCR·수정 문장을 로그로 출력하거나 서버에 보내지 않는다.
- 기존 마스킹·로컬 OCR 재탐지 UI와 전송 guard를 유지한다.

## 저장 및 버전 정책

수정 상태는 현재 브라우저 탭 메모리에만 둔다. localStorage/서버 자동 저장은 없다. 새로고침하면 저장하지 않은 수정이 사라진다.

사용자가 저장 버튼을 누를 때만 `local-ocr-review.json`을 다운로드한다. 원문·수정본·출처·검토 상태가 포함되므로 개인정보가 있을 수 있으며 Git에 업로드하거나 공유하면 안 된다.

`document_revision`은 파일을 열거나 편집/취소/확인할 때 증가한다. 각 조항 `clause_revision`은 편집·취소 시 증가한다. 이는 로컬 수정 이력 번호이며 서버가 인증한 이미지 버전이 아니다. raw_text는 변하지 않는다. 저장 파일을 다시 열면 edited_text는 복원하지만 기존 reviewed_by_user는 신뢰하지 않고 모두 needs_review로 초기화한다.

항상 `server_approved:false`, `external_llm_allowed:false`, `privacy_scan_status:pending`이다. 검토 완료는 법률적 안전·개인정보 보호 완료·서버 승인과 다르다.

## 화면 실행 방법

이미 만들어진 검토 파일: `tmp/clause_review/review_document.json`.

로컬 서버가 실행 중이면 http://127.0.0.1:8011 에서 **OCR 조항 수정·검토 → OCR 검토 파일 열기**로 위 파일을 선택한다. 파일 경로를 입력하는 기능이 아니라 파일 선택 창에서 선택하는 방식이다.

서버 실행:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m uvicorn integrations.privacy_service:app --host 127.0.0.1 --port 8011 --no-access-log --log-level critical
```

검토 파일 재생성(기존 파일 덮어쓰기 금지):

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/prepare_clause_review.py --output tmp/clause_review/review_document_v2.json
```

위 명령은 기존 실제 OCR 캐시를 필요로 한다. 새 OCR 실행이나 PDF/GT 추출이 아니다. `frontend/index.html`을 직접 열어 로컬 수정 UI만 사용할 수도 있지만 실제 개인정보 OCR 검사는 로컬 서버 주소에서 실행해야 한다.

현재 선택한 단일 Canvas 이미지와 가져온 5페이지 OCR 문서는 자동 연결되지 않는다. UI에도 이를 표시했다. 파일의 문서 ID·페이지를 직접 확인해야 한다. 실제 운영에서 서버가 이미지 문서와 OCR 출처를 결합하는 연결은 B와 협의가 필요하다.

## 실제 검증 결과

| 테스트 | 통과 | 실패 |
|---|---:|---:|
| Python OCR·규칙·개인정보·기존 guard + 원문 연결 14개 | 175 | 0 |
| 기존 API·개인정보·LLM 응답 검증 통합 | 100 | 0 |
| Chrome 기존 53 + 조항 모델/UI 27개 | 80 | 0 |
| 전체 | 355 | 0 |

실제 데이터 검증: 저장된 PaddleOCR 결과의 19개 ID·페이지·raw_text·출처 줄·좌표를 대조했다. 이번 조항 검증을 위해 OCR를 새로 실행한 것은 아니다.

합성 동작 검증: 수정/취소, 개별·전체 진행률, 빈 텍스트, 위조 저장 상태 재가져오기, ID 오류, XSS 형태 문자열의 안전한 표시, 수정본 Blob 저장, 버전 증가를 검증했다. 사용자 검토 동작은 자동화 테스트에서 모의했으며 실제 사람 검토 완료로 기록하지 않는다.

브라우저 회귀에는 실제 로컬 PaddleOCR 합성 전화번호 탐지, 개인정보 상태 무효화, Canvas 픽셀·좌표·터치 테스트도 포함했다. 모바일은 Chrome 에뮬레이션이며 실제 휴대폰/Safari는 미검증이다.

브라우저 결과: `tmp/privacy_tests/browser/results.json`.
화면: `tmp/privacy_tests/browser/clause_review_mobile.png`.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m unittest discover -s tests/integration -q
# 검토 JSON 및 로컬 서버가 준비된 상태에서
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python tests/frontend/run_masking_browser.py --privacy-url http://127.0.0.1:8011
```

실제 OCR 검증 테스트는 tmp의 원본 OCR 캐시와 검토 JSON을 필요로 한다. 새 체크아웃에는 해당 로컬 자료를 별도로 준비해야 하며 누락된 상태를 테스트 통과로 처리하지 않는다. 기존 PyMuPDF 경고는 있으나 실패는 없다.

## 담당자 B 협의 사항

기존 API Clause는 clause_id/page/text만 가지므로 raw_text·수정본·모든 페이지·출처 좌표는 별도 서버 내부 문서로 관리해야 한다. 이번 sidecar 형식을 기존 API 스키마에 임의 추가하지 않았다.

B는 인증된 문서/이미지 버전, 불변 원본 OCR, 사용자 수정본, 조항별 명시적 검토 이력을 서버에 연결해야 한다. 클라이언트의 reviewed_by_user 또는 다운로드 파일만으로 승인하지 않는다. 수정 텍스트 개인정보 재검사 및 기존 전송 guard의 서버 재승인이 필요하다. 현재 로컬 수정본은 분석 API로 전송하지 않는다.

## 변경 파일 / GitHub Desktop 커밋 대상

수정:

- frontend/index.html
- frontend/style.css
- frontend/app.js
- tests/frontend/run_masking_browser.py

신규:

- frontend/clause_review.js
- frontend/review_ui.js
- integrations/clause_review.py
- scripts/prepare_clause_review.py
- tests/test_clause_review.py
- tests/frontend/clause_review_checks.js
- docs/clause_review_steps_1_2.md

추천 메시지: `feat: link OCR clauses and add local text review UI`

가상환경, tmp, 원본 PDF, 사용자가 저장한 local-ocr-review.json은 제외한다. 기존 미추적 작업과 이번 파일을 구분하여 선택한다. 이번 작업에서 Git commit/push/merge/브랜치 변경을 하지 않았다. dev/01 유지, 보호 대상 22개 파일 변경 없음.

네 가지 과제 중 앞의 두 단계(요청 범위 50%)에서 종료한다. 결과 병합 및 원문 근거 검증 통합은 미진행이다.
