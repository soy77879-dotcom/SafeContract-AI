# D-6 STEP 1 — Canvas 수동 픽셀 마스킹

## 구현 및 사용

`frontend/index.html`을 Chrome에서 연다. JPG/PNG 선택 → 마우스 또는 터치로 개인정보 영역 드래그 → 수동 확인 체크 → 새 PNG 생성 → 다운로드 순서로 사용한다.

- 단일·다중 영역을 원본 해상도의 Canvas에 불투명 검은색으로 채운다.
- 표시 좌표를 Canvas 픽셀 좌표로 변환하며 50–200% 보기 배율을 지원한다.
- 선택 취소, 마지막 영역 취소, 전체 초기화 및 이미지 교체를 지원한다.
- 편집 상태가 바뀌면 이전 출력과 확인 상태를 무효화한다. 비동기 출력 도중 편집되는 경우도 거부한다.
- 원본 미리보기와 마스킹 출력 미리보기를 구분한다.
- Canvas에서 새 PNG로 인코딩하므로 원본 파일 바이트와 EXIF를 복사하지 않는다. 출력 이름은 `masked-contract.png`다.
- 입력 및 출력 용량은 10MiB 이하, 입력 해상도는 최대 2천만 픽셀이다.

## STEP 2 연결 인터페이스

```javascript
const input = SafeContractMasking.getRedetectionInput();
// input.file: 현재 편집 상태에서 생성한 새 PNG File
// maskingRevision, manualMaskCount
// privacyScanStatus: 'pending', needsPrivacyReview: true
// externalLLMAllowed: false
const formData = SafeContractMasking.prepareOCRUpload();
// 기존 API 필드명 files에 새 PNG 한 개만 포함. 실제 전송은 수행하지 않음.
```

파일이 생성되지 않았거나 취소·초기화·교체된 상태면 인터페이스가 오류를 발생시킨다. 내부 전달 함수는 원본 및 별도로 만든 File을 거부한다. 원본 input은 name이 없으며 기본 form submit도 차단한다. 네트워크 요청 코드는 추가하지 않았다.

STEP 2는 이 파일로 OCR 개인정보 재탐지를 수행하고 별도 결과를 관리해야 한다. `externalLLMAllowed: false`는 현재 인터페이스의 정책 값이며, 향후 서버와 전송 경로에서도 별도 강제가 필요하다. 외부 전송 차단 시스템 전체를 검증한 것은 아니다.

## 실제 검증

- Chrome headless 브라우저 테스트: **28개 통과, 0개 실패**.
- 기존 Python 테스트: **111개 통과, 0개 실패**. PyMuPDF 관련 DeprecationWarning이 있었으나 실패는 없다.
- 저장된 PNG를 다시 디코딩하여 선택 픽셀이 RGBA(0, 0, 0, 255)인지 확인했다.
- 영역 외 픽셀 보존, 다중 영역, 역방향 드래그, 취소·초기화, 이미지 교체, 출력/편집 경쟁 상태를 확인했다.
- 축소·확대 좌표, CDP 마우스 입력 및 모바일 터치 에뮬레이션을 확인했다.
- 원본과 새 File의 분리, 생성 파일만 포함하는 FormData, 원본·위조 복사본·오래된 출력 거부를 확인했다.
- 합성 JPEG에 넣은 EXIF 표식이 새 PNG에 남지 않음을 확인했다.
- 실제 휴대폰 및 Safari는 테스트하지 않았다. 모든 브라우저 입력은 합성 이미지로 검증했다.

재실행:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv-backend/bin/python tests/frontend/run_masking_browser.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

브라우저 테스트는 macOS Chrome 및 기존 `.venv-backend`의 websockets를 사용한다. 임시 Chrome 프로필을 생성하고 종료한다. 결과는 `tmp/masking_tests/results.json`, 화면은 `tmp/masking_tests/mobile_masking.png`에 저장한다.

## 보호 범위 및 남은 위험

원본은 되돌리기를 위해 브라우저 메모리에 유지된다. 사용자가 놓친 개인정보는 출력에 남을 수 있다. 수동 확인은 개인정보 보호 완료나 자동 탐지 완료가 아니다. OCR 재탐지, 외부 LLM 전송 경로 검증, LLM 응답 검증은 이번 단계에 포함하지 않는다.

`dev/01`을 유지했다. backend, OCR·위험 엔진, PDF, Ground Truth, 가상환경은 수정하지 않았다. commit/push/merge는 실행하지 않았다.

## 이번 작업의 커밋 대상

- frontend/index.html
- frontend/style.css
- frontend/app.js
- frontend/masking.js
- tests/frontend/masking_checks.js
- tests/frontend/run_masking_browser.py
- docs/d6_canvas_masking_report.md

추천 메시지: `feat: add manual canvas pixel masking`

기존 작업의 다른 미추적 파일 및 `.venv-backend/`, `tmp/`는 이번 커밋 대상에서 제외한다.
