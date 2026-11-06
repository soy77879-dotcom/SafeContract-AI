# D-6 STEP 4 — LLM 구조화 응답 검증

## 완료 범위

독립 응답 검증 모듈과 합성 응답 테스트를 완료했다. 외부 LLM을 호출하지 않았다. 운영 FastAPI 엔드포인트, 인증된 사람 검토 화면 및 실제 LLM 경로에는 연결하지 않았다.

신규 파일:

- `integrations/response_validation.py`
- `tests/integration/test_response_validation.py`
- `docs/d6_response_validation_report.md`

기존 backend, API_SPEC, OCR·위험 규칙, PDF, Ground Truth, 가상환경은 수정하지 않았다. 보호 대상 22개 파일의 SHA-256 변경 없음. dev/01 유지, commit/push/merge 미실행.

## 기존 스키마 호환성

`backend.schemas.AnalyzeRequest`, `AnalyzeResponse`, `RiskResult`, `ErrorResponse`를 그대로 사용한다. STEP 3 TransferGate를 상속하고 기존 adapter의 canonical `payload_hash`를 재사용한다.

정상 API 결과의 필드는 `document_id`, `status`, `results`, `warnings`다. 위험 유형과 상태는 기존 Pydantic Literal을 그대로 검사한다. `contract_termination`은 규칙 엔진 내부 값이며 API 응답에서는 허용하지 않는다(`termination` 사용).

검증 모듈의 `{ok, response}` / `{ok, internal_reason, error}`는 서버 내부 반환 형식이다. 새로운 API 응답 규격이 아니다. B는 성공 시 `response`만 반환하고 실패 시 기존 ErrorResponse를 적절한 HTTP 오류로 매핑해야 한다.

## 구조·근거 검증

- UTF-8 JSON 텍스트/바이트만 입력한다. 미리 파싱된 dict는 중복 키를 확인할 수 없으므로 거부한다.
- 최상위 객체, 정확한 필수 필드, 엄격한 타입, 기존 enum, 중첩 구조를 검사한다.
- 모든 깊이의 중복 JSON 키, NaN/Infinity, 코드블록, 설명이 섞인 출력, 알 수 없는 필드를 거부한다.
- 최대 응답 128KiB, 결과 1–200개, 문자열 필드 8,000자, warnings 50개. 이는 독립 검증기의 자원 제한이며 API 스키마 자체를 바꾸지 않았다.
- document_id와 clause_id를 승인된 요청 스냅샷과 비교한다.
- evidence는 해당 검토 완료 조항에 공백·문장부호까지 그대로 존재해야 한다. 다른 조항의 근거, 빈 근거, 임의 생성 근거는 거부한다. 자동 수정이나 Ground Truth 대체를 하지 않는다.
- 같은 조항의 서로 다른 위험 유형은 허용한다. 동일 clause_id/risk_type 중복, 위험 미탐지와 다른 위험의 혼합, none/no_risk_detected 불일치는 거부한다.
- completed는 모든 요청 조항을 포함해야 하며 partial은 안내 warning이 있어야 한다. 오류를 no_risk_detected로 바꾸지 않는다.
- 설명·질문·권장 행동·warnings의 일부 단정적인 법률 표현을 보수적으로 차단한다. 이는 의미 전체의 사실성·법률적 정확성을 검증하는 모델이 아니다. 근거가 존재한다고 설명의 추론까지 참인 것은 아니다.

## STEP 3 연결과 재사용 방지

`ResponseValidationGate`를 한 서버 인스턴스에서 사용한다.

1. 기존 `prepare()`에서 서버 processor의 마스킹 산출물과 OCR을 검사한다.
2. `confirm_analysis_review()`는 실제 사람 검토 후에만 호출하는 신뢰된 서버 훅이다. document_id, 조항 ID/페이지/텍스트를 정확히 묶는다. OCR 전체 텍스트 해시가 기존 STEP 3 기록과 일치해야 한다.
3. `begin_analysis_mock()`는 해당 요청·이미지·버전으로 기존 `dispatch_mock()`를 통과해야 응답 ticket을 발급한다. 클라이언트 allowed 플래그나 전송 결과 dict를 승인 근거로 받지 않는다.
4. `validate_response()`는 서버 ticket, 소유자, 최신 문서 세대, 만료, 이미지·텍스트 해시, 버전을 확인한 뒤 응답을 검사한다.
5. ticket은 성공/실패 모두 1회 소비된다. 이미지 변경 또는 새 검사 후의 오래된 응답은 거부한다. 잠금으로 검증과 무효화의 경쟁을 방지한다.

검토되지 않은 OCR 또는 조항별 검토를 거치지 않은 단순 STEP 3 승인만으로는 분석 응답 ticket을 발급하지 않는다. 테스트의 승인 훅은 합성 검토 대역이며 실제 사람이 확인했다고 주장하지 않는다.

## B 연결 예시

```python
from integrations.response_validation import ResponseValidationGate

gate = ResponseValidationGate(processor=trusted_server_mask_and_ocr)
receipt = gate.prepare(authenticated_owner, document_id, version, source_bytes)
# 실패하면 중단. 아래 훅은 실제 인증된 이미지·조항 검토를 완료한 뒤에만 실행.
reviewed = gate.confirm_analysis_review(
    authenticated_owner, receipt['receipt_id'], reviewed_request,
    receipt['image_sha256'], receipt['text_sha256'])
# reviewed가 False면 중단.
context = gate.begin_analysis_mock(
    authenticated_owner, receipt['receipt_id'], masked_bytes, version, reviewed_request)
# context['ok']가 False면 오류 처리. 현재는 합성 raw_json만 사용.
outcome = gate.validate_response(
    authenticated_owner, context['response_ticket'], synthetic_raw_json,
    image_sha256=context['image_sha256'], text_sha256=context['text_sha256'],
    revision=context['masking_revision'])
# ok=True일 때만 outcome['response']를 AnalyzeResponse로 반환.
# 실패 시 outcome['error']만 반환. internal_reason은 원문 없는 내부 분류용.
```

실제 운영에서는 요청별 인증·문서 소유권, 서버의 현재 버전, 신뢰할 수 있는 전체 OCR/마스킹 processor, 사용자 조항 검토를 연결해야 한다. 이미지/텍스트가 달라지면 새 검사·검토가 필요하다. 현재 전체 OCR 텍스트와 조항 텍스트를 줄바꿈으로 연결한 값이 정확히 일치해야 한다. 머리말·서명부 제외나 OCR 교정이 필요한 경우 임의 정규화로 우회하지 말고 변경된 분석 범위를 서버에서 다시 검토·승인하도록 확장해야 한다.

이 모듈은 메모리 저장소를 사용한다. 다중 프로세스 운영에는 인증된 공유 저장소의 원자적 일회 소비·만료 관리가 필요하다. 공개 승인 endpoint는 구현하지 않았다.

## 개인정보와 안전한 오류

STEP 2 `scan_lines`를 재사용하여 응답의 모든 표시 문자열과 warnings를 검사한다. 식별번호, 전화, 이메일, 이름 문맥 등 후보가 있으면 응답 전체를 차단한다. 원문 근거도 개인정보 검사에서 예외로 두지 않는다.

사용자 오류는 기존 `VALIDATION_ERROR` 또는 `PRIVACY_CHECK_FAILED`와 고정 안내 문구만 반환한다. JSON/Pydantic 예외 문자열, 응답 원문, 개인정보 매치는 출력하지 않는다. 내부 분류도 고정 코드만 사용한다.

개인정보 패턴 검사는 누락·오탐이 가능하며 완전한 보호를 보장하지 않는다. 검증 통과는 법률적 진실성 또는 위험 분석 정확성의 보장이 아니다.

## 실제 테스트 결과

| 묶음 | 통과 | 실패 |
|---|---:|---:|
| 기존 Python OCR·규칙·개인정보·전송 guard | 161 | 0 |
| 백엔드 환경 기존 통합 52 + 신규 응답 검증 48 | 100 | 0 |
| Chrome Canvas·guard·실제 로컬 PaddleOCR | 53 | 0 |
| 전체 | 314 | 0 |

신규 48개는 정상/partial/다중 위험, 잘못된 JSON·필드·자료형·상태, 다른 문서/조항, 허위 근거, 미검토 OCR, 개인정보, 이미지·텍스트 해시, 버전, 무승인, 중복 키, 크기/개수, 빈 결과, 중첩 구조, 코드블록, 재사용, 만료, 법률 단정, 원문 로그 및 네트워크 없음 검사를 포함한다.

정상 응답은 실제 AnalyzeResponse로 재검증했다. 실패 결과는 ErrorResponse와 호환되는지 검사했다. 개인정보를 포함한 실패 응답에서 원문이 오류·로그에 없음을 확인했다. socket 연결을 금지한 검사에서 네트워크 호출이 없었다.

LLM 응답은 전부 합성 대역이며 실제 LLM 호출은 0회다. 기존 브라우저 회귀는 실제 로컬 PaddleOCR를 사용했다. 로컬 HTTP 요청은 외부 LLM 호출과 다르다. 기존 PyMuPDF DeprecationWarning은 있었지만 실패는 없었다.

재실행:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m unittest discover -s tests/integration -p test_response_validation.py -v
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python -m unittest discover -s tests/integration -q
# 로컬 privacy_service 서버 실행 후
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python tests/frontend/run_masking_browser.py --privacy-url http://127.0.0.1:8011
```

## D-6 판정 및 커밋

STEP 1 Canvas, STEP 2 로컬 재탐지, STEP 3 전송 guard, STEP 4 구조화 응답 검증의 독립 기능 구현·검증을 완료했다. **운영 웹서비스 연동은 미완료**이며 위의 인증/서버 처리/검토/공유 저장소/API 연결이 남아 있다.

이번 커밋 대상은 상단 신규 파일 3개다. 선행 STEP 1–3 의존 파일이 아직 미추적이면 먼저 별도 관리해야 한다. 가상환경, tmp, 원본 PDF는 제외한다.

추천 커밋 메시지: `feat: validate structured analysis responses against reviewed clauses`
