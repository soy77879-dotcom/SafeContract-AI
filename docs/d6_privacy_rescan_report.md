# D-6 STEP 2 — 로컬 OCR 개인정보 재탐지

## 실행 방법

```sh
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m uvicorn integrations.privacy_service:app --host 127.0.0.1 --port 8011 --no-access-log --log-level critical
```

브라우저에서 http://127.0.0.1:8011 을 연다. 이미지 선택 → 영역 마스킹 → 수동 확인 → 새 PNG 생성 → **로컬 OCR 개인정보 재탐지**를 실행한다. file://로 직접 연 화면에서는 실제 검사가 실패 상태로 표시된다. 기존 운영 backend 및 API 스키마는 변경하지 않았다. 별도 로컬 미리보기 서버의 `/local/privacy-scan`만 추가했다.

## 구현

- 기존 `ocr_worker.load_images`, `ocr_pages.create_ocr`, 대비 1.5배 전처리를 재사용한다. Python 3.11 서버에서 Python 3.9 OCR subprocess를 실행한다.
- 계약 조항으로 분리하기 전 모든 OCR 줄을 검사한다. 원문 OCR을 수정하거나 Ground Truth를 참조하지 않는다.
- 식별번호/유사 13자리, 휴대·일반전화·국가번호, 이메일, 계좌 의심 숫자열, 이름·주소 문맥, 분류되지 않는 긴 숫자열과 낮은 OCR 신뢰도를 검토 대상으로 다룬다.
- 공백, 하이픈 변형, 전각 문자, 일부 O/0·I/1 등의 혼동은 후보 탐지에만 사용한다. OCR 원문을 보정하지 않는다.
- 명시적인 금액 단위와 문맥을 구분한다. 계좌번호·이름·주소는 오탐 가능성이 있으며 개인정보 확정 판정이 아니다.
- 결과 위치는 원래 OCR 줄의 `line_index`(0부터), `start`, `end`(Python 문자 인덱스, 끝 제외)다. 범위에 해당하는 원문이나 사용자 파일명은 반환하지 않는다.

## 결과와 버전 연결

`status`: `pending` / `running`(브라우저), `no_candidates` / `review_required` / `failed`.

- `found`, `review_required`, `remasking_required`, `findings`, `image_sha256`, `masking_revision`을 사용한다. 실패하면 발견 여부는 null이다.
- 생성된 PNG의 SHA-256을 서버에서 다시 계산한다. 브라우저는 응답 해시·버전·현재 File 객체를 검사한다.
- 편집/취소/초기화/파일 교체 시 결과를 초기화하고 진행 중 요청을 취소한다. 늦게 도착한 이전 응답도 적용하지 않는다.
- 미탐지 결과도 직접 검토가 필요하다. 모든 결과에서 `external_llm_allowed=false`, `external_transfer_blocked=true`를 유지한다.

STEP 3 연결:

```javascript
const scan = SafeContractMasking.getPrivacyScanState();
// status, image_sha256, masking_revision, findings, found,
// remasking_required, review_required, external_llm_allowed:false,
// external_transfer_blocked:true
```

기존 `getRedetectionInput()`과 `prepareOCRUpload()`는 유지한다. 외부 LLM 호출은 없다. 이 클라이언트 상태는 향후 서버의 전송 권한을 대신하지 않는다. STEP 3에서 별도 정책 강제 및 검증이 필요하다.

## 실제 실행 및 테스트

- 실제 PaddleOCR subprocess: 합성 PNG의 전화번호·이메일을 탐지, `review_required`, 15.36초(모델 초기화 포함). `tmp/privacy_tests/real_ocr_result.json`에 원문 없는 결과 저장.
- 실제 브라우저 → Canvas 새 PNG → 로컬 HTTP → PaddleOCR → UI까지 연결하여 합성 전화번호 탐지와 초기화 후 무효화를 확인했다.
- Python: **137개 통과** = 기존 111 + 탐지 규칙 26. 합성 OCR 문자열 기반 단위 테스트다.
- API 통합: **42개 통과** = 기존 26 + 개인정보 경로 16. 개인정보 HTTP 정상 응답은 모의 OCR이며, 실제 worker 손상 이미지 거부·타임아웃 처리도 포함한다.
- 브라우저: **39개 통과** = Canvas 회귀 28 + 모의 응답 상태 관리 8 + 실제 로컬 OCR 흐름 3.
- 최종 자동 검증 합계: **218개 통과, 0개 실패**. 반복 실행한 동일 테스트는 중복 합산하지 않았다.
- 초기 TestClient 실행은 기존 환경에 httpx2가 없어 실패했다. 설치하지 않고 표준 라이브러리의 실제 루프백 HTTP 방식으로 바꾸어 최종 통과했다.
- PyMuPDF의 DeprecationWarning은 발생했으나 테스트 실패는 없다.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m unittest discover -s tests/integration -q
# 위 로컬 서버 실행 후:
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python tests/frontend/run_masking_browser.py --privacy-url http://127.0.0.1:8011
```

브라우저 결과: `tmp/privacy_tests/browser/results.json`. 기존 Canvas+모의 검사만 실행하려면 `--privacy-url` 옵션을 생략한다.

## 개인정보 원문 취급

- OCR 텍스트는 worker 메모리에서 검사하고 유형·위치만 직렬화한다. subprocess stdout/stderr는 버린다. 예외 내용과 원문을 응답·콘솔에 출력하지 않는다.
- 서버가 worker 응답 필드를 허용 목록으로 다시 제한한다. 브라우저 역시 원문이나 서버 메시지를 그대로 렌더링하지 않는다.
- 검사 중 새 마스킹 PNG는 임시 디렉터리에 보관하고 종료/실패/타임아웃 시 삭제한다. worker 결과 파일에는 개인정보 원문을 넣지 않는다.
- 합성 전화번호·이메일이 결과 JSON에 없음을 확인했다. 테스트용 합성 입력 PNG 및 테스트 소스에는 의도적으로 합성 값이 들어 있다. 실제 개인정보는 사용하지 않았다.
- 로컬 서버는 loopback Host/client 및 POST Origin·전용 헤더를 검사한다. 운영 인증 체계나 STEP 3 외부 전송 차단 전체 검증을 구현한 것은 아니다.

## 남은 한계

- OCR 미인식/오인식, 줄 분리, 불규칙한 계좌 형식, 문맥 없는 이름·주소는 누락될 수 있다. 정규식과 문맥 기반 후보 탐지는 개인정보 보호를 보장하지 않는다.
- 브라우저 경로는 현재 생성 File만 입력으로 받는다. 서버는 파일명·해시·마스킹 개수만으로 임의 클라이언트가 보낸 PNG의 Canvas 생성 이력을 증명할 수 없다. 이름을 바꾼 원본을 악의적으로 직접 요청하는 문제는 별도 서버 신뢰 경계 설계가 필요하다. 어떤 경우에도 이 검사로 외부 전송을 허용하지 않는다.
- 임시 입력 파일 삭제는 보안 삭제를 뜻하지 않는다. 운영 환경의 보관·권한·취소 정책은 별도 검토 대상이다.
- 실제 휴대폰/Safari 및 다양한 실제 계약서에서의 개인정보 재현율은 미검증이다. 실제 OCR 테스트는 합성 이미지이며 정량 탐지 성능 평가가 아니다.
- 운영 backend OCR/분석 엔드포인트 연결, 외부 LLM 전송 차단 전체 검증, LLM 응답 검증은 미완료다.

## 수정·신규 파일 및 커밋

이번 STEP 2 수정: `frontend/index.html`, `frontend/app.js`, `tests/frontend/run_masking_browser.py`.

신규:

- `frontend/privacy.js`
- `integrations/privacy_detection.py`
- `integrations/privacy_worker.py`
- `integrations/privacy_service.py`
- `tests/test_privacy_detection.py`
- `tests/integration/test_privacy_service.py`
- `tests/frontend/privacy_checks.js`
- `docs/d6_privacy_rescan_report.md`

STEP 1과 D-7 파일이 아직 미추적 상태이면 필요한 의존 파일도 먼저 확인하여 함께 관리해야 한다. `.venv/`, `.venv-backend/`, `tmp/`, 원본 PDF는 이번 커밋에 포함하지 않는다.

추천 커밋 메시지: `feat: add local OCR privacy rescan after masking`

브랜치 `dev/01` 유지. 보호 대상 backend/data/scripts 파일 22개를 해시 대조하여 변경 없음을 확인했다. PDF, Ground Truth, 위험 규칙, 평가 결과, 가상환경을 수정하거나 재설치하지 않았다. Git commit/push/merge는 수행하지 않았다.
