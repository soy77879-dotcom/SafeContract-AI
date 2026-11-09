# B-1 STEP 1: 서버 내부 분석 입력

공개 API는 변경하지 않았다. `/api/analyze`는 계속 403이며 외부 전송 승인을 만들지 않는다.

## 다음 단계의 호출 계약

1. 기존 HTTP 세션·CSRF·마스킹 검증을 통과한 서버 코드만 `ReviewStore.get_analysis_input(owner, document_id, binding)`을 호출한다. `owner`는 요청 본문이 아닌 기존 세션 검증 결과여야 한다.
2. `binding`에는 `document_id`, `document_version`, `image_sha256`만 넣는다. 승인 플래그나 클라이언트 텍스트는 받지 않는다.
3. 반환값의 `request`는 기존 AnalyzeRequest 형태다. 모든 조항의 서버 저장 `edited_text`를 사용한다. `analysis_token`은 내부 일회용 입력 식별자이며 클라이언트나 로그에 노출하지 않는다.
4. 다음 단계에서 분석을 수행하더라도 결과는 아직 승인된 결과가 아니다. 결과 수용 직전에 `analysis_input_guard(owner, document_id, binding, snapshot)`을 사용해 현재 상태를 재검증해야 한다. 컨텍스트 안에서 기존 결과·근거 검증을 수행하고, 정상 종료 전에는 결과를 외부에 표시하지 않는다. 컨텍스트 안에서 네트워크나 장시간 OCR을 실행하지 않는다.
5. 이 검사는 입력 최신성만 확인한다. 기존 ResponseValidationGate, 결과·근거 검증, 외부 전송 정책을 대체하지 않는다. 그 모듈들과 운영 API의 연결은 다음 단계 작업이다.

조회·수용 시 소유자, 문서 버전·이미지 해시, 필수 조항 전체 확인, 원본 ID·페이지·OCR 원문 출처, 확인 당시 텍스트 해시, 개인정보 재검사(no_candidates 및 found=false)를 검사한다. 확인 해시는 서버가 확인 요청을 검증한 뒤 보관한다.

수정·무효화는 확인 해시와 내부 토큰을 초기화한다. 새 조회는 이전 토큰을 대체한다. 수용 검사는 일회용 토큰을 소모하며 잠금으로 다른 요청의 수정과 직렬화한다. 종료 시 만료 및 재진입 수정도 다시 검사한다. 반환된 객체를 고쳐도 서버 원문은 바뀌지 않는다.

저장소는 기존 개발용 메모리 저장소다. 서버 재시작 시 데이터가 사라지며, 서로 다른 서버 프로세스 간 공유·잠금은 제공하지 않는다. 운영용 인증과 저장소 연결은 별도 작업이다.

## 실제 검증 (Python 3.11.1, 기존 .venv)

- 신규 `test_review_analysis_input.py`: 35 passed.
- 요청한 기존 review_http/result_merge/response_validation: 104 passed, 1 skipped.
- 위 네 파일 합계: 139 passed, 1 skipped.
- 전체 `tests`: 386 passed, 18 failed, 2 skipped.
- 전체 실행 실패: `tmp/ocr_pages/c001_aligned/structured_contract.json` 누락 15건, PyMuPDF(fitz) 누락 2건, OpenCV(cv2) 누락 1건.
- 초기 샌드박스 실행은 loopback 포트 바인딩 제한으로 HTTP setup 오류가 발생했다. 로컬 서버 실행 권한으로 재실행한 결과가 위 수치다.
- 합성 조항과 모의 OCR 기반 검증이다. 실제 PaddleOCR 및 외부 LLM은 실행하지 않았다.
