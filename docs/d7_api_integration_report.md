# D-7 API 통합 준비 및 검증

## 실제 백엔드 상태

.venv-backend Python 3.11.1에서 backend.main과 backend.schemas 전체 import 성공. FastAPI 0.162.0, Uvicorn 0.54.0, python-multipart 0.0.33, Pydantic 2.14.3 확인.

기존 127.0.0.1:8000 서버에 실제 HTTP 요청:

| 경로 | 상태 | 확인 |
|---|---:|---|
| /api/health | 200 | status=ok, service=SafeContract AI |
| /docs | 200 | Swagger HTML |
| /api/ocr | 404 | 원본 앱 라우트 미등록 |
| /api/analyze | 404 | 원본 앱 라우트 미등록 |

기존 서버를 중단하거나 재시작하지 않았다. 테스트 서버는 localhost 임의 포트(0번 바인딩)에서만 실행하고 종료했다. startup 성공만으로 HTTP 성공을 판단하지 않았다.

## 신규 독립 어댑터

- integrations/adapter.py: OCR subprocess 실행, 기존 OCRResponse/AnalyzeRequest/AnalyzeResponse 검증, 검토 상태 저장·확인, 규칙 호출.
- integrations/ocr_worker.py: 기존 Python3.9 OCR 환경에서 Pillow 실제 디코딩, 픽셀 검사, 기존 create_ocr/preprocess/structure 재사용.
- integrations/preview_app.py: 원본 backend.main.app을 수정하지 않는 독립 FastAPI 앱 및 승인 후 사용할 install_routes(app) 함수.

백엔드 환경에는 PaddleOCR와 Pillow가 설치되지 않았다. 전체 OCR 재설치 없이 .venv/bin/python을 명시적으로 실행한다. shell=True를 사용하지 않고 고정 워커와 서버 생성 임시 경로만 전달한다. 사용자 파일명은 실행 경로나 명령에 사용하지 않는다.

업로드는 1~5장, 장당 10MiB, 전체 50MiB, JPEG/PNG 확장자·MIME·매직바이트를 검사한다. 실제 워커는 이미지 디코딩·verify·2천만 픽셀 제한·단일 프레임을 검사하고 모든 입력 확인 뒤 모델을 로드한다. 일부 페이지 OCR 실패는 전체 오류로 반환한다. 출력 JSON의 문서ID·스키마·페이지 범위를 검사한다.

OCR timeout 기본900초, 초과 시 자식 프로세스 그룹을 종료하고 임시 파일을 삭제한다. 현재 프로세스 내 중복 OCR은 503 OCR_BUSY로 거부한다. 다중 Uvicorn worker 사이의 전역 잠금은 아니므로 시연은 workers=1을 사용한다. 원문/좌표/confidence/검토 상태는 내부 결과에 보존하며 API 응답에는 기존 필드만 전달한다.

임시 업로드/응답 파일은 작업 완료·실패·시간 초과 후 삭제한다. 검토용 내부 자료는 메모리에서 최대20문서/1시간으로 제한한다. 원문을 HTTP 오류나 터미널에 출력하지 않는다. 실제 개인정보 마스킹·인증·사용자별 세션 격리는 구현하지 않았으므로 인터넷에 공개하는 운영 서버가 아니라 로컬 통합 검증용이다.

## 사용자 확인 및 위험 분석

AnalyzeRequest에는 검토 상태 필드가 없으므로 클라이언트가 보내는 reviewed 플래그를 신뢰하지 않는다. 내부 ReviewLedger.confirm(request)를 신뢰 가능한 서버 측 사용자 확인 동작이 호출하도록 인터페이스만 제공한다. 현재 확인용 HTTP endpoint는 없다.

확인 기록은 document_id와 clause_id/page/text 전체 payload 해시에 연결된다. 문구 수정 후에는 기존 승인이 무효화되고 unknown으로 돌아간다. 조항 ID·페이지가 원본과 달라지면 오류를 반환한다. 레코드가 없거나 만료된 문서도 unreviewed로 취급한다. 후보 텍스트 또는 Ground Truth를 자동 적용하지 않는다.

실제 기존 API를 유지한다: internal risk/potential_risk→potential_risk, unknown→needs_review, ok→no_risk_detected, contract_termination→termination. 질문·행동 배열은 기존 question/recommended_action 문자열로 변환한다. 첨부 예시의 배열 필드나 다른 enum으로 백엔드 스키마를 바꾸지 않았다.

규칙은 직접 호출한다. 명시적으로 서버 측 승인한 합성 정상/위험 사례에서 각각 no_risk_detected/potential_risk HTTP 응답을 확인했다. 실제 OCR19개는 미검토 상태로 needs_review를 유지한다.

## 테스트 구분

| 테스트 | 통과 |
|---|---:|
| 기존 OCR·구조화·규칙 (.venv) | 111 |
| 신규 실제 HTTP (.venv-backend) | 16 |
| 신규 어댑터/분리 프로세스 | 10 |
| 합계 | 137 |

실패0. 신규 HTTP는 임의 포트의 독립 FastAPI 앱에 urllib로 실제 요청했다. health/docs, OCRResponse, 검토/미검토 분석, 원문 근거·ID, 잘못된 이미지·매직바이트·빈 입력·크기 초과·중복 ID·서버 오류를 검사했다.

OCR 성공 HTTP는 모의 OCR을 주입한 테스트다. 업로드부터 실제 PaddleOCR 추론까지의 성공을 검증한 것은 아니다. 실제 Python3.9 워커의 손상 이미지 거부, 유효 PNG 디코딩, subprocess timeout/잘못된 JSON/중복 실행은 별도로 검사했다. 단위 테스트의 느린 워커는 합성 스크립트이며 실제 OCR timeout 성능 측정이 아니다.

이번 작업에서 새 OCR 추론, 프론트엔드 업로드/분석 UI, 다중사용자 운영 환경은 미검증이다. 실행 근거와 로그: tmp/api_integration/verification.json.

## 재현

```bash
# 기존111개
.venv/bin/python -m unittest discover -s tests -v
# 신규26개: 실제 로컬 HTTP 서버를 만들고 테스트 후 종료
.venv-backend/bin/python -m unittest discover -s tests/integration -v
# 독립 통합 앱: 8001이 비어 있는지 확인한 뒤 실행
.venv-backend/bin/python -m uvicorn integrations.preview_app:app --host 127.0.0.1 --port 8001 --workers 1
```

독립 앱의 기본 OCR runner는 실제 Python3.9 모델을 호출하도록 구현돼 있다. 테스트 때만 모의 runner를 주입한다. /api/analyze에 일반 JSON을 POST하면 승인 기록 없이 자동 검증된 것으로 처리하지 않는다.

## 담당자 B 승인 후 최소 연결안 (미적용)

backend/main.py 하단, 기존 app 및 health_check 정의가 완료된 위치에서:

```python
from integrations.preview_app import install_routes
install_routes(app)
```

라우트가 이미 있으면 중복 등록을 거부한다. 기존 health는 유지한다. 위 함수는 오류 응답 핸들러도 등록하므로 담당자 B가 기존 인증·검증·예외 정책과 함께 검토해야 한다. backend/schemas.py, requirements.txt, API_SPEC.md 변경은 필요하지 않으며 이번에 수정하지 않았다.

확인·수정 workflow는 담당자 B가 인증된 사용자/문서 관계를 검증한 뒤 app.state.review_ledger.confirm(validated_request)를 호출하는 방식으로 연결할 수 있다. 승인 이벤트를 클라이언트의 임의 boolean으로 대체하면 안 된다. 운영용 세션 저장소·만료 정책·마스킹 완료 기준은 별도 합의가 필요하다.

## 프론트엔드와 시연 준비

현재 frontend/app.js는 로컬 이미지 확인/미리보기만 수행하며 fetch 업로드·OCR 수정·분석 요청·결과 표시가 없다. 프론트 파일을 이번에 수정하지 않았다.

시연 전 필요한 사항:
- 업로드 중 진행 상태와 버튼 비활성화, 취소/재시도 처리.
- OCR 완료 후 텍스트 확인·수정 및 서버 측 승인 기록 연결.
- /api/analyze 결과의 기존 API enum/필드 표시.
- reverse proxy 및 ASGI request body 크기 제한을 multipart 파싱 전에도 적용. 현재 앱은 파일 읽기 및 디코딩 단계에서 크기를 제한한다.
- 긴 OCR 요청에 맞춘 브라우저/프록시 timeout 합의. 900초는 구현 설정이며 성공 보장 시간이 아니다. 이전753.11초 기록은 타이밍 방식의 한계가 있어 현 성능 보장값으로 쓰지 않는다.
- 오류 시 재시도 전에 중복 실행 상태를 확인. 전체 비동기 job 시스템은 이번에 추가하지 않았다.

## GitHub Desktop

이번 신규 파일:
- integrations/adapter.py
- integrations/ocr_worker.py
- integrations/preview_app.py
- tests/integration/test_api_integration.py
- docs/d7_api_integration_report.md

기존 코드 수정 없음. 보호 대상22개 파일 해시 변경 없음. .venv/, .venv-backend/, tmp/, PDF, 모델 파일은 커밋 제외. 이전 미추적 개발 파일은 별도 이력으로 검토한다.

추천 커밋: feat: prepare OCR and risk engine API integration

dev/01 유지. commit/push/pull/merge/브랜치 전환/PR 생성 미실행.
