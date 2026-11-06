# D-6 STEP 3-3 — 전송 차단 및 모의 통합 검증

## 판정

**클라이언트 차단 모듈, 서버 차단 모듈 및 독립/로컬 모의 통합 검증 완료. 운영 서비스 통합 미완료.**

시작 시 `frontend/privacy_guard.js`는 존재하지만 0바이트였다. 최소 구현을 작성했다. 실제 외부 LLM 호출 기능과 SDK는 추가하지 않았다. 현재 로컬 서비스에 승인된 전송 기록을 만드는 공개 API는 없으며 정상 사용 흐름도 계속 차단된다.

## 클라이언트 연결

`SafeContractPrivacyGuard.evaluatePrivacyState(state, current)`는 실제 STEP 2 필드명(`status`, `ocr_completed`, `found`, `findings`, `review_required`, `remasking_required`, `image_sha256`, `masking_revision`)을 검사한다.

`SafeContractPrivacyGuard.evaluateCurrent()`는 `SafeContractMasking.getPrivacyScanState()`와 `getRedetectionInput()`을 읽고 현재 생성 파일의 SHA-256을 직접 계산한다. 해시 계산 중 편집된 경우에도 거부한다.

없는 검사, pending, failed, 개인정보 후보, 추가 검토, 해시/버전 불일치, 필드 누락, 위조 허용 플래그를 차단한다. 실제 STEP 2는 미탐지여도 `review_required:true`이므로 허용 상태로 바꾸지 않았다.

로컬 조건을 모두 충족하는 JS 객체도 서버 승인 증명이 될 수 없다. 이 경우 `allowed:false`, `reason:server_authorization_required`를 반환한다. 클라이언트 객체 조작만으로 허용되는 분기를 만들지 않았다. 정상 합성 데이터의 **허용** 테스트는 서버의 실제 기록과 모의 검토 훅을 통해 수행한다.

## 서버 모듈과 신뢰 경계

`integrations/transfer_guard.py`의 `TransferGate`:

1. 기본 생성자는 processor가 없으므로 승인 가능한 기록을 만들 수 없다.
2. `prepare(owner, document, revision, source)`는 신뢰된 서버 processor를 직접 호출한다. 클라이언트 OCR 결과/해시/허용 플래그를 입력으로 받지 않는다.
3. processor는 서버에서 생성·검증한 마스킹 PNG와 전체 OCR 줄을 제공해야 한다. 원본과 동일 바이트 결과는 거부한다. 모듈은 서버 결과를 재탐지하고 이미지·텍스트 해시를 직접 계산한다.
4. 후보 없음만으로 허용하지 않는다. `confirm_review(owner, receipt_id, image_hash, text_hash)`를 별도 신뢰된 사람 검토 흐름에서 호출해야 한다. 이번 합성 테스트는 이 검토를 모의했다. 실제 사람의 개인정보 검토 완료를 주장하지 않는다.
5. `dispatch_mock(owner, receipt_id, image, revision, text)`가 유일한 전송 인터페이스다. 소유자, 기록 만료, 최신 문서 세대, 검토 상태, 실제 이미지 바이트, 텍스트, 버전을 검사한다.
6. 권한은 메모리의 난수 핸들이며 원자적으로 1회 소비된다. 재사용/동시 실행은 거부된다. 같은 문서 재처리 또는 `invalidate()`는 이전 기록을 폐기한다. 새 검사 실패도 이전 승인을 복원하지 않는다.
7. 허용 결과에도 `mode:mock`, `external_llm_called:false`다. 네트워크 transport 콜백을 받지 않는다. 원문과 이미지, 예외를 로그/반환값에 넣지 않는다.

별도 로컬 서버에 `/local/mock-transfer`를 추가했다. 엄격한 요청 필드, 실제 전달 이미지 해시, 서버 내부 기록으로 검사한다. 추가 `allowed` 플래그를 비롯한 임의 필드는 거부한다. 현재 기본 서버에는 승인 기록 발급/검토 API가 없으므로 직접 HTTP로 우회해도 차단된다. HTTP 허용 테스트는 테스트 서버에 합성 processor와 사전 검토 기록을 주입한 경우에만 수행했다.

**한계:** processor와 검토 훅은 신뢰된 서버 코드라는 전제다. 서버 processor의 실제 Canvas 마스킹 이력 증명, 전체 OCR 연결, 사용자 인증 및 사람이 이미지를 검토했다는 증명은 구현하지 않았다. 합성 processor의 PNG 바이트는 경계 테스트용 대역이며 실제 픽셀 마스킹/OCR 테스트가 아니다. 실제 Canvas/PaddleOCR 회귀 테스트는 별도로 실행했다.

## 테스트 결과

| 실행 묶음 | 통과 | 실패 |
|---|---:|---:|
| Python 규칙·기존 회귀·서버 guard | 161 | 0 |
| 실제 루프백 HTTP 통합(기존 포함) | 52 | 0 |
| Chrome Canvas·상태 관리·guard·실제 로컬 OCR | 53 | 0 |
| 합계 | 266 | 0 |

기존 218개에 신규 48개를 추가했다. 반복 실행 횟수는 합산하지 않았다.

신규 48개 구성:

- 서버 단위 24개 + 실제 HTTP 10개 = 34개. 이 중 6개 테스트는 정상 모의 허용 경로를 포함한다(재사용·동시성 테스트는 허용 후 차단도 확인). 나머지 28개는 거부/실패 안전성 시나리오다.
- 클라이언트 14개 = 차단 확인 13개 + 네트워크 요청 없음 확인 1개.
- 실제 개인정보 대신 합성 문자열만 사용했다.
- 실제 PaddleOCR로 합성 전화번호 탐지 후 브라우저 guard 차단, 초기화 후 차단을 확인했다.
- 서버 허용/거부 테스트의 OCR와 검토는 모의 입력이다. 실제 사람이 검토했다거나 운영 외부 전송이 연결됐다고 표시하지 않는다.

서버 guard 실행 중 socket connect/create_connection을 실패하도록 대체하고 호출 0회를 확인했다. 클라이언트 guard는 fetch를 감시하여 호출 0회를 확인했다. 코드 검색에서도 외부 LLM 호출 경로를 발견하지 않았다. **외부 LLM 네트워크 호출 0회**. 실제 HTTP/OCR 통합 테스트에서 로컬 서버 요청은 발생했다. 전체 OS의 네트워크 패킷 감사를 수행했다는 뜻은 아니다.

로그·결과에 개인정보 원문을 포함하지 않는 테스트가 통과했다. 테스트 소스에는 의도적인 합성 값이 있으며 실제 개인정보를 사용하지 않았다. 기존 PyMuPDF DeprecationWarning은 있으나 실패는 없다.

## 재실행

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m unittest discover -s tests/integration -q
# 별도 터미널에서 로컬 서버 실행
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m uvicorn integrations.privacy_service:app --host 127.0.0.1 --port 8011 --no-access-log --log-level critical
# 서버 실행 후 실제 브라우저 + 로컬 OCR 회귀
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python tests/frontend/run_masking_browser.py --privacy-url http://127.0.0.1:8011
```

브라우저 검증 결과: `tmp/privacy_tests/browser/results.json`.

## 담당자 B 연결 사항

보호 대상 backend/API 파일을 수정하지 않았다. 운영 연결 시 다음이 필요하다.

- 인증된 서버 사용자/문서 ID와 이미지 버전을 사용한다. 현재 미리보기의 `local-preview` 고정 소유자는 운영 인증을 대체하지 않는다.
- 서버가 신뢰할 수 있는 마스킹 산출물 생성·검증과 전체 OCR processor를 연결한다. 클라이언트가 전한 텍스트·검사 통과 플래그를 processor 결과로 사용하면 안 된다.
- 이미지 **및 OCR 텍스트**의 실제 검토를 서버에서 인증하고 정확한 두 해시에 대해 검토 훅을 호출한다. 외부 공개 승인 endpoint를 무조건 허용으로 구현하면 안 된다.
- 이미지 변경 알림은 서버 문서 버전 갱신과 `invalidate`에 연결한다. 서버에 알려지지 않은 로컬 편집은 서버가 추측할 수 없다.
- 모든 향후 LLM 경로를 같은 서버 차단 인터페이스에 연결한다. 다중 프로세스 운영에는 공유 저장소의 원자적 소비/만료 관리가 필요하다. 현재 기록은 프로세스 메모리에만 있다.
- 실제 네트워크 transport는 아직 만들지 않는다. 운영 승인/통합 및 STEP 4 응답 검증을 별도로 완료한다.

## STEP 4 입력 인터페이스

`dispatch_mock()`의 결과:

- 차단: `allowed:false`, 안전한 reason, `mode:mock`, `external_llm_called:false`.
- 모의 허용: `allowed:true`, `receipt_id`, `image_sha256`, `text_sha256`, `masking_revision`, `mode:mock`, `external_llm_called:false`, `response`.

현재 response는 `{"status":"mock_only","schema_version":"future-step4"}`인 고정 대역이다. LLM 출력이나 검증된 분석 결과가 아니다. STEP 4는 승인된 요청 해시·버전을 보존하면서 별도의 응답 스키마와 불일치/비정상 응답 거부를 구현해야 한다. 차단 결과에는 응답 검증기를 실행하지 않는다.

## 변경 파일 / GitHub Desktop 커밋 대상

- `frontend/privacy_guard.js` — 기존 빈 파일 구현
- `frontend/index.html` — guard 로드
- `integrations/transfer_guard.py` — 신규 서버 차단 모듈
- `integrations/privacy_service.py` — 독립 mock HTTP 경로
- `tests/test_transfer_guard.py`
- `tests/integration/test_transfer_http.py`
- `tests/frontend/privacy_guard_checks.js`
- `tests/frontend/run_masking_browser.py`
- `docs/d6_transfer_guard_report.md`

추천 메시지: `feat: enforce privacy gates for mock LLM dispatch`

선행 STEP 1/2 파일도 아직 미추적이면 의존 파일을 확인하여 별도 관리한다. `.venv`, `.venv-backend`, `tmp`, 원본 PDF는 커밋 대상이 아니다. `dev/01` 유지. commit/push/merge/브랜치 변경은 실행하지 않았다. 보호 대상 22개 파일 해시 변경 없음.
