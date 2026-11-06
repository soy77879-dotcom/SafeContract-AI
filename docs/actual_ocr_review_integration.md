# 실제 OCR–FastAPI 연결 및 검토 저장

## 완료 범위와 운영 상태

**별도 FastAPI 검증 앱에서 실제 HTTP + 실제 PaddleOCR + 사용자 수정·확인 + 서버 저장·재조회 흐름을 완료했다.** 단순 어댑터 준비나 모의 OCR만으로 판정하지 않았다.

앱: `integrations.review_app:app`, 주소: http://127.0.0.1:8012

**운영 `backend.main:app`에는 아직 등록하지 않았다.** 보호 대상 파일을 수정하지 않았다. 담당자 B의 승인 및 라우터 연결이 필요하다. 규칙·LLM 병합 및 외부 LLM 호출은 구현하지 않았다.

## 실제 연결 기능

- 기존 `.venv-backend` FastAPI에서 `.venv`의 Python 3.9 PaddleOCR worker를 subprocess로 실행한다.
- `OCRProcess`, `ocr_worker.run`, 이미지 디코더, 기존 조항 구조화, `OCRResponse`, 조항 검토 sidecar를 재사용한다.
- `/api/ocr` 공개 응답은 기존 document_id/clauses(clause_id/page/text) 그대로다. 파일 필드명도 files다. 별도 개인정보 파일 권한은 헤더로 전달한다.
- worker timeout, 프로세스 종료, 오류 코드, 임시 디렉터리 정리는 기존 OCRProcess 경로를 사용한다.
- 서버 내부에는 원문 raw_text, 수정본 edited_text, 출처 OCR 줄/좌표, 문서 버전, 서버 계산 이미지 해시를 보관한다. 클라이언트는 원문을 변경할 수 없다.

## 실제 브라우저 사용

```sh
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m uvicorn integrations.review_app:app --host 127.0.0.1 --port 8012 --no-access-log --log-level critical
```

1. http://127.0.0.1:8012 를 연다.
2. 합성 계약서 이미지를 선택하고 개인정보 영역을 수동 마스킹한다.
3. 수동 확인 후 새 PNG를 생성한다.
4. **서버 OCR 실행 · 조항 불러오기**를 누른다. 서버 픽셀 검증·재탐지·OCR 때문에 시간이 걸린다.
5. 조항 수정 후 **수정본 서버 저장**을 누른다. 저장은 검토 완료가 아니다.
6. 각 **이 조항 검토 완료** 버튼으로 서버에 개별 확인 동작을 기록한다.
7. **서버 저장본 다시 불러오기**로 저장된 수정본과 확인 상태를 조회한다.

기존 로컬 JSON 열기·다운로드는 유지했다. 로컬 파일은 서버 문서 핸들을 만들지 않으므로 파일을 열었다고 서버 저장/검토 완료가 되지 않는다. 서버 확인 뒤 다시 수정하면 먼저 서버 저장 후 재확인해야 한다.

## 개인정보·서버 검증

### 이미지

- 브라우저가 현재 생성한 새 마스킹 File과 실제 영역 목록만 전달한다.
- 서버는 디코드 후 지정 영역의 픽셀이 실제 검은색인지 검사하고 새 PNG로 재인코딩한다. 형식/용량/픽셀 제한과 EXIF 미복사를 적용한다.
- 서버 로컬 OCR 재탐지 성공 후 세션에 묶인 10분 일회용 mask_ticket을 발급한다. 실패는 발급하지 않는다.
- `/api/ocr`는 해당 ticket과 업로드 바이트 전체를 비교한다. 원본·다른 이미지·다른 세션·재사용 ticket으로 요청하면 거부한다.
- 이미지 해시는 서버에서 계산한다. 복수 이미지의 순서까지 포함하도록 각 파일 SHA-256 digest를 연결한 값의 SHA-256을 사용한다. 브라우저의 단일 PNG 개인정보 검사 해시와 혼동하지 않는다.
- 후보가 있는 이미지는 사용자가 OCR 내용을 확인·재마스킹할 수 있도록 조항을 반환하지만 개인정보 검토 필요 상태를 유지한다. 외부 전송 허용은 항상 false다.

**한계:** 검은 영역과 파일 권한은 확인하지만 임의 클라이언트의 PNG가 원래 어느 파일에서 만들어졌는지 암호학적으로 증명하지는 않는다. 기존 검은 부분만 지정하거나 개인정보를 놓치는 경우가 있으므로 재탐지·사람 검토가 필요하다. 완전한 개인정보 보호를 주장하지 않는다.

### 수정본·검토

- 서버 보존 document_id/이미지 해시/document_version/raw_text/조항 순서·ID를 기준으로 제출을 확인한다.
- 누락/중복/다른 문서/이전 버전/원문 변조/임의 reviewed 플래그를 거부한다.
- 저장한 수정 텍스트에 기존 개인정보 탐지를 다시 수행한다. 의심 내용은 review_required로 유지하고 외부 전송을 허용하지 않는다.
- 개별 확인은 서버가 보관한 정확한 수정 텍스트 해시, 버전, 세션, 일회용 challenge로 검증한다. draft에 reviewed:true만 넣어서는 확인되지 않는다.
- user_confirmed는 인증된 개발 세션의 확인 요청을 기록한 것이며 실제 사람이 문장을 이해했거나 법률적으로 안전하다는 증명이 아니다. analysis_approved/external_llm_allowed는 항상 false다.
- `/api/analyze`는 이 앱에서 명시적으로 차단한다. 분석·LLM 병합은 이번 범위가 아니다.
- 편집 시 서버 확인 상태를 무효화하고 버전을 올린다. 저장 중/확인 중 추가 편집이 있으면 오래된 응답으로 새 수정본을 덮어쓰지 않는다. 이미지 변경 후 이전 UI/확인 상태도 초기화한다.
- 서버가 받지 못한 브라우저 변경(강제 종료/네트워크 단절 등)을 추측할 수는 없다. 그 경우에도 문서별 해시·버전·세션이 분리되어 다른 문서 승인에 사용되지 않고 분석은 차단된다.

## 저장·인증 정책

**개발용 메모리 저장소**다. 문서는 최대 20개, TTL 1시간이며 소유 세션으로 접근을 분리한다. 마스킹 대기 데이터는 최대 10건/10분이다. 만료 자료는 다음 접근/등록 시 정리한다. 재시작하면 세션과 문서가 모두 사라진다. 여러 worker 사이의 공유·지속성은 보장하지 않는다.

개발 세션은 HttpOnly/SameSite=Strict cookie와 서버 발급 CSRF 토큰을 사용한다. loopback Host/client와 POST Origin도 검사한다. 이는 운영 계정 인증을 대신하지 않으며 인터넷 공개용 설정이 아니다.

계약서/수정본을 Git 저장소에 파일로 저장하지 않는다. 처리 중 임시 PNG·worker 결과만 시스템 임시 디렉터리에 두고 삭제한다. 일반 서버 access log와 worker stdout/stderr는 출력하지 않는다. 오류는 고정 코드/안내만 반환한다. 승인된 소유 세션의 OCR/검토 조회 응답에는 필요한 원문과 수정본이 포함된다. 이는 로그나 외부 서비스 전송과 다르다.

## 새 개발용 API와 B 협의

기존 OCRResponse를 바꾸지 않고 별도 경로를 추가했다. 운영 등록 전 B와 합의해야 한다.

| 경로 | 역할 |
|---|---|
| GET /api/session | 개발 세션·CSRF 발급 |
| POST /api/masking/register | files + mask_regions 픽셀·재탐지 확인 및 일회용 ticket |
| POST /api/ocr | files, X-Mask-Ticket → 기존 OCRResponse |
| GET /api/review-documents/{id} | 원문·수정본·출처·서버 버전 조회 |
| POST /api/review-documents/{id}/draft | 전체 조항 수정본 저장 |
| POST /api/review-documents/{id}/confirm | 해당 조항·버전·challenge·텍스트 해시 확인 |
| POST /api/review-documents/{id}/invalidate | 확인 상태 무효화 및 버전 증가 |

라우터 등록 함수: `install_review_routes(app)`. 독립 `create_router()`만 등록하면 주변 세션 요청 보호/오류 처리 미들웨어까지 연결됐다고 볼 수 없으므로 installer를 사용한다.

B의 최소 개발용 등록안(실행하지 않음):

```python
from integrations.review_app import install_review_routes
install_review_routes(app)  # app 생성 후, catch-all static mount 전에
```

현재 backend/main의 `/static`과 frontend 상대 경로 및 `/local/privacy-scan` 연결도 필요하다. 검증 앱처럼 기존 privacy_service 앱을 마지막 경로 fallback으로 mount하거나 B가 정적 경로/개인정보 라우트를 명시 등록해야 한다. 기존 `/api/ocr`가 있으면 중복 등록하지 않는다. 운영에서는 이 개발 세션 대신 계정 인증·문서 권한, HTTPS, 영구 저장소/삭제 정책, 공유 원자적 버전 관리가 추가로 필요하다.

## 실제 테스트 결과

- 실제 HTTP + PaddleOCR: **1개 통합 시나리오 통과**. 실제 서버 재탐지와 OCR worker를 호출해 합성 이미지에서 **2개 조항** 생성, 수정본 저장, 2개 확인 기록, 재조회 및 원문 보존 확인. 분석 승인 false.
- 신규 모의 OCR HTTP 검증: **16개 통과**. 형식·ticket·세션·문서·버전·해시·원문·중복·누락·PII·확인 재사용·분석 차단.
- 실제 PNG 검증: **3개 통과**. 흰 영역을 마스킹이라고 주장, 영역 누락, 손상 PNG를 거부.
- 기존 Python: **175개 통과**.
- 백엔드 회귀: **119개 통과, 실제 OCR 1개는 별도 실행을 위해 skip**. 별도 실행한 실제 OCR 1개까지 합치면 고유 테스트 120개 통과다.
- 브라우저: 기존/추가 상태 검증 **82개 통과**, 별도로 실제 서버 OCR→편집→서버 저장→확인→재조회 **4개 통과**. 겹치는 회귀 실행은 중복 합산하지 않았다.
- **고유 테스트 합계 381개 통과, 실패 0개.** 실제 OCR skip 항목은 별도 RUN_REAL_REVIEW=1 실행에서 통과했으므로 미실행을 통과로 계산한 것이 아니다.
- 외부 LLM API 호출 없음. 실제 로컬 HTTP와 OCR 실행은 발생했다. 기존 개인정보·규칙·Canvas·LLM 응답 검증 테스트도 통과했다.

실제 HTTP 결과: `tmp/review_http/actual_http_result.json` (원문 없이 처리 결과만 기록).
실제 서버 브라우저 결과: `tmp/review_http/browser/results.json`.
추가 브라우저 상태 검증: `tmp/privacy_tests/browser/results.json`.

재현:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/create_review_http_fixture.py
RUN_REAL_REVIEW=1 PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m unittest discover -s tests/integration -p test_review_http.py -v
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m unittest discover -s tests/integration -q
# 개발 서버 8012 실행 후; 이전 조항 검토 캐시도 필요
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python tests/frontend/run_masking_browser.py --privacy-url http://127.0.0.1:8012 --server-review
```

합성 이미지 생성은 macOS AppleSDGothicNeo 글꼴과 기존 OCR 환경 Pillow를 사용한다. 실제 계약서나 Ground Truth는 사용하지 않았다.

## 이번 변경·GitHub Desktop 대상

신규:

- integrations/mask_verify_worker.py
- integrations/review_store.py
- integrations/review_app.py
- frontend/server_review.js
- scripts/create_review_http_fixture.py
- tests/integration/test_review_http.py
- tests/frontend/server_review_ui_checks.js
- docs/actual_ocr_review_integration.md

수정:

- frontend/masking.js
- frontend/index.html
- frontend/clause_review.js
- frontend/review_ui.js
- tests/frontend/run_masking_browser.py

이전 조항 검토 모듈이 아직 미추적이면 그 의존 파일도 별도로 확인하여 관리한다. 가상환경, tmp, 원본 PDF, 실제 개인정보 자료는 제외한다.

추천 메시지: `feat: connect real OCR API and session-scoped clause review storage`

dev/01 유지. backend/main.py, schemas.py, requirements.txt, API_SPEC.md, PDF, GT, 위험 규칙 및 가상환경을 변경하지 않았다. Git commit/push/merge는 실행하지 않았다.
