# B-2 1번 — OCR 전처리·페이지별 추출 검증 결과

**프로젝트:** SafeContract AI
**작성 기준:** 2026-11-09
**작업 브랜치:** `dev/02`
**상태:** B-2 1번 완료(로컬 검증 기준).
B-2 2~7번 및 서비스 API 통합은 미완료.

## 1. 작업 목표

기존 OCR 코드를 재사용하면서 JPG/PNG 입력 처리, PDF 자동 페이지 이미지 변환, 별도 프로세스 OCR 실행 및 조항 구조화를 검증한다. 사용자 개인정보가 포함된 실제 계약서가 아니라 **개인정보 없는 공식 표준계약서 빈 서식**으로 실제 OCR을 확인한다.

## 2. 구현·확인한 내용

| 영역 | 확인 내용 |
|---|---|
| 실행 환경 | Windows, Python 3.11.9, `.venv-b2` 사용. PaddleOCR 모델 초기화 및 실제 추론 성공 |
| 이미지 전처리 | 기존 이미지 검증·RGB 변환·대비 1.5배 전처리 재사용 |
| PDF 검증 | `integrations/pdf_input.py`: 파일 형식·크기(10MiB)·암호 필요 여부·페이지 수(최대 5) 검사 |
| PDF 렌더링 | `integrations/pdf_renderer.py`: 150 DPI, 페이지당 500만 픽셀 및 전체 2,000만 픽셀 상한을 적용하여 페이지별 RGB 이미지 생성 |
| PDF↔OCR 연결 | `integrations/pdf_ocr_bridge.py`: PDF 각 페이지를 PNG 바이트로 변환해 기존 `OCRProcess` 입력 형식으로 전달 |
| 기존 OCR Worker | `integrations/ocr_worker.py` 및 `integrations/adapter.py` 재사용. 별도 프로세스 실행, 페이지별 OCR 및 조항 구조화 확인 |

## 3. 검증 결과

### 단위·Mock 테스트

- 이미지 로딩·전처리: **4개 통과**
- Mock OCR 처리 흐름: **3개 통과**
- PDF 입력 검증: **9개 통과**
- PDF 페이지 렌더링: **7개 통과**
- **총 23개 통과** (기존 사용자 실행 기록 기준)

### 실제 OCR 실행

- 작은 합성 PNG에서 **‘보증금 반환 조건’** 인식 성공
- 작은 합성 PDF → PNG → 실제 PaddleOCR 인식 성공
- 법무부 주택임대차 표준계약서의 **정상적으로 새로 다운로드한 PDF(`standard_contract_fresh.pdf`) 5페이지**를 기존 `OCRProcess`로 처리 성공

| 페이지 | OCR 텍스트 줄 수 |
|---|---:|
| 1 | 151 |
| 2 | 81 |
| 3 | 62 |
| 4 | 45 |
| 5 | 59 |
| **합계** | **398** |

- 구조화 결과: **조항 19개**
- 처음 5개 조항 ID: `C001` ~ `C005`
- 이 실행에서는 과거 Windows `0xC0000005` 비정상 종료가 재발하지 않음

> **주의:** 추출 줄 수·조항 수는 OCR의 정확도 지표가 아니다. 19개 조항 전체의 ID·페이지 일관성과 실제 원문 정확도는 별도 검증이 필요하다.

## 4. 문제와 해결

처음 사용한 표준계약서 PDF는 PyMuPDF에서 내부 참조(xref) 복구 및 압축·색상 프로파일 오류가 발생했고, 렌더링 이미지가 전부 흰색이어서 OCR 결과도 0개였다. 이후 **공식 PDF를 새로 다운로드**한 파일에서는 `IS REPAIRED: False`, 비흰색 픽셀 확인 및 실제 OCR 151줄(1페이지) 추출에 성공했다. 기존 OCR 모델이나 개인정보 보호 코드를 재작성하지 않았다.

## 5. 아직 완료되지 않은 범위

- B-2 2번: 조항 ID와 페이지 번호, 전체 조항 원문 연결 일관성 검증
- B-2 3~7번: FastAPI 연동, Mock 분석 응답 API 테스트, 예외 처리, 개인정보 보호·로그 검사, 회귀 테스트
- 실제 사용자 PDF 업로드 경로 및 마스킹·승인 흐름과의 통합 **미완료**
- 정량적 OCR 정확도(CER) 및 최종 서비스 성능 평가 **미완료**

## 6. 관련 파일

- `integrations/pdf_input.py`
- `integrations/pdf_renderer.py`
- `integrations/pdf_ocr_bridge.py`
- 기존 재사용: `integrations/adapter.py`, `integrations/ocr_worker.py`, `scripts/ocr_pages.py`, `scripts/ocr_experiments.py`, `scripts/structure_ocr.py`
- 테스트: `tests/integration/test_b2_ocr_preprocessing.py`, `test_b2_ocr_worker.py`, `test_b2_pdf_input.py`, `test_b2_pdf_renderer.py`

**다음 작업:** B-2 2번 — OCR 결과 JSON의 `clause_id`, `page`, 원문 연결 일관성 검증.
