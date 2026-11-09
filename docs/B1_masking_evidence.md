# B-1 마스킹 이미지 증빙 연결

## 구현

기존 서버 verify_mask가 픽셀을 검증하고 재인코딩한 PNG에 대해 페이지별 SHA-256을 생성한다. review_app의 내부 artifact에 실제 PNG와 해시를 함께 보관하고 OCR 직전에 다시 비교한다. 같은 바이트를 OCR worker에 전달한 후 ReviewStore.register가 해시와 페이지 수를 재확인한다. 장시간 OCR 후에는 identity(request)를 다시 호출하여 세션 만료 및 소유권/CSRF 검증도 유지한다.

- 기존 공개 image_sha256: 업로드 이미지 묶음 해시. API 호환성을 위해 유지.
- 신규 내부 pages[].masked_image_sha256: 서버가 실제 검증·재인코딩하여 OCR에 사용한 개별 PNG의 해시.
- 두 해시는 다른 목적이며 동일시하지 않는다.

ReviewStore.register의 masked_images/masked_hashes는 서버 내부 keyword-only 인자다. 요청 JSON이나 클라이언트 승인 플래그에서 가져오지 않는다. 기존 register 호출은 계속 가능하지만 이미지 증빙이 없으면 get_masking_evidence에서 실패한다.

get_masking_evidence(owner, document_id, binding)는 서버 내부 조회 함수다. 기존 _analysis_request를 통해 소유자·문서·버전·업로드 묶음 해시·원본 조항 대응·전체 사용자 확인·최종 수정본 해시·개인정보 재검사를 확인한 다음 현재 문서 버전의 증빙 사본을 반환한다. API 라우트는 없다. 반환값은 승인 티켓이 아니며 analysis_approved/external_llm_allowed는 false다.

## 저장 및 수명

ReviewStore에는 PNG 바이트를 저장하지 않는다. 문서 ID, 문서 버전, 페이지별 해시, 업로드 묶음 해시, 서버 검증 경로 표시, 개인정보 상태만 메모리에 저장한다. 소유자는 기존 서버 문서 레코드에 결합된다. 기존 get/API 응답에는 새 증빙 필드나 바이트를 포함하지 않는다. 이미지나 OCR 텍스트를 새 로그에 출력하지 않는다.

마스킹 artifact의 PNG는 기존처럼 OCR을 위한 일시적 메모리에만 존재한다. 새 daemon 타이머가 미사용 artifact를 600초 후 제거한다. OCR 요청이 artifact를 소비하면 타이머를 취소하며, 처리 중 바이트 참조는 요청/worker가 끝나면 해제된다. worker는 기존 timeout을 유지한다. Python 메모리의 물리적 zeroization을 보장하는 구현은 아니다.

문서 만료 시 기존 _get 또는 다음 register 정리에서 레코드·증빙이 제거된다. 문서 저장소에는 민감 이미지 바이트가 없으므로 문서 만료를 기다리는 추가 이미지 보관은 없다.

save는 입력 구조 검증 후 실제 수정/개인정보 검사 전에 _reset을 수행한다. 스캐너 예외가 발생하더라도 이전 확인 해시·analysis_token·masking_evidence는 남지 않는다. invalidate도 증빙을 제거한다. 재확인 버튼만으로 이전 증빙을 복원하지 않는다. 새 서버 마스킹 검증과 OCR 등록이 필요하다.

개인정보 review_required/오류 상태에는 사용 가능한 이미지 증빙을 부여하지 않는다. 기존 재검토용 OCR 동작은 유지하되 증빙 조회와 분석 승인은 차단한다.

## 남은 승인 게이트 조건

이번에는 이미지가 어떤 문서의 OCR 입력이었는지에 대한 신뢰 가능한 서버 경로와 해시 메타데이터를 연결했다. 원본 바이트를 임의로 만들어 기존 TransferGate에 주입하지 않는다. 기존 게이트는 실제 masked_image 및 전체 OCR 원문 해시를 요구하므로, 이 메타데이터만으로 prepare/confirm_analysis_review/begin_analysis_mock를 호출할 수 없다.

후속 작업은 실제 이미지 수명 내에서 게이트와 연결할 증빙 계약, 전체 OCR 원문과 사용자 수정본의 별도 해시/확인 증빙, 문서 버전과 masking_revision의 구분, 두 게이트의 무효화 및 일회용 승인 연결이다. /api/analyze는 계속 403이다. 외부 LLM 허용 상태도 변경하지 않았다.

## 실제 검증

- 신규 test_masking_evidence.py: 20 passed.
- 전체 Python tests: 436 passed, 18 failed, 2 skipped; 27 subtests passed.
- 실패는 이전과 동일: OCR 임시 structured_contract.json 누락 15건, fitz 누락 2건, cv2 누락 1건.
- 실제 픽셀 검증: 합성 PNG를 기존 verify_mask subprocess로 검증·재인코딩. 검은 픽셀 유지, PNG 메타데이터 제거, OCR 전달 바이트와 증빙 해시 일치 확인.
- 해당 HTTP 테스트의 OCR 및 개인정보 스캐너는 모의 함수다. 실제 PaddleOCR 재실행으로 보고하지 않는다.
- 나머지 증빙 단위 테스트는 합성 PNG와 서버 내부 등록 fixture를 사용했다.
- 해시 불일치·이미지 변조·누락·페이지 수 불일치·다른 사용자·버전 불일치·개인정보 상태·만료·수정/무효화 후 재확인·스캐너 예외·API 증빙 비노출·미사용 artifact 만료·403 유지 검증.
- 기존 미커밋 파일 중 review_app.py/review_store.py만 필요한 범위로 수정. 데이터, backend, 규칙 엔진 및 이전 테스트/문서는 작업 시작 해시와 동일.
