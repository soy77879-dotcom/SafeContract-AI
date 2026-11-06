# D-7 OCR 조항 구조화 결과

5페이지의 기존 OCR 380줄을 재사용했다(cached). 이번 작업에서는 OCR을 새로 실행하지 않고 구조화·평가를 실행했다. GT는 평가 모듈에서만 읽으며 구조화 함수에는 전달하지 않는다.

## 구현과 구조

제N조 제목 패턴과 페이지 내 위치·순서로 본문 13개, 특약 제목 이후 행 간격으로 특약 6개를 탐지했다. GT의 조항 개수나 텍스트로 생성 결과를 채우지 않았다. 특약의 29px 행 간격 기준은 현재 2배 렌더 개발 문서에 맞춘 휴리스틱이며 일반 문서에서 검증되지 않았다.
1페이지 3개, 2페이지 16개. 3페이지는 당사자/서명 영역, 4페이지는 legal_guidance, 5페이지는 renewal_refusal_form으로 분류했다. 분류는 페이지 번호가 아닌 제목·서명·조항 패턴을 사용한다. 각 영역의 원본 line_id를 보존한다.
19개 모두 needs_review. confidence는 정확도나 법적 신뢰도를 의미하지 않는다. raw_text, 페이지 목록, 좌표, confidence와 검토 사유를 보존한다. verified_text는 전부 null이다.
기존 R1 후보는 원본 줄의 텍스트·좌표가 일치할 때만 candidate_regions에 연결한다. 원본과 후보를 따로 저장하고 후보를 API text에 자동 적용하지 않는다. 임대인/임차인·서명 페이지는 API 조항에서 제외한다.
금액·날짜·선택 영역은 OCR 줄 좌표와 value=null/state=unknown으로 보존한다. 실제 미기입과 OCR 누락을 자동 구분하는 검출기는 미구현이며, 빈 금액이나 체크 상태를 생성하지 않는다.

## 정확도

모든 캐시 페이지 이미지가 현재 PDF의 2배 렌더 + 대비1.5 이미지와 픽셀 일치함을 확인했다. 이는 OCR 실행 당시 모델 설정의 증명은 아니다.
2페이지 구조화된 조항의 원본 line_id 집합이 GT 평가 영역과 일치한다. Raw CER 12.4373%, Normalized CER 2.4976%로 D-7 수치가 재현된다. 단 기존 전체 페이지 캐시에 모델/설정/원본 해시가 없어 실행 조건까지 같은 직접 비교라고 확정할 수 없다.
1페이지 C001은 자동 분리와 GT 영역의 줄 집합이 달라 전체 페이지의 구조화 CER는 계산하지 않았다. GT 영역 기반 진단 geometry_cer와 구조화 성공 조항의 matched_clause_cer를 구분해서 저장했다.
3~5페이지는 대응 GT가 없어 CER 미계산. OCR 성공을 정확도 검증으로 간주하지 않는다.
부담→부당, 원문자 번호, 밑줄·글머리표·체크박스 오류는 원본에 남아 있다. R1 후보 및 별도 R3 평가(정규화 CER 2.0264%)는 검토용 기존 실험이며 이번 구조화 점수에 섞지 않았다.

| 조항 | Raw CER | Normalized CER |
|---|---:|---:|
| C002 | 39.8601% | 1.3514% |
| C003 | 51.5493% | 16.2162% |
| C004 | 23.5641% | 2.1687% |
| C005 | 1.9048% | 0.0000% |
| C006 | 1.8405% | 0.0000% |
| C007 | 4.4025% | 0.8621% |
| C008 | 8.9806% | 0.9772% |
| C009 | 1.9481% | 0.0000% |
| C010 | 4.8485% | 0.8000% |
| C011 | 2.8571% | 0.0000% |
| C012 | 19.5122% | 2.7027% |
| C013 | 24.4094% | 2.3810% |
| C014 | 17.2131% | 16.3265% |
| C015 | 2.5862% | 1.1628% |
| C016 | 5.9633% | 4.7337% |
| C017 | 7.3620% | 2.4590% |
| C018 | 33.7500% | 7.3171% |
| C019 | 16.9492% | 7.3171% |

조항 검출 Precision/Recall, 경계·영역 분류 정확도는 독립적으로 사람 검증된 경계/분류 정답이 없어 미계산. 19개 개수 일치는 이들 지표의 대체물이 아니다.

## API와 연동 제한

API 프리뷰는 기존 document_id + clauses(clause_id,page,text) 구조이며 내부 19개 조항과 ID·개수·원문이 일치한다. 여러 페이지 조항은 시작 페이지를 API에 사용한다.
Python3.9에서 backend/schemas.py 전체 import는 str | None 표현 때문에 실패한다. 백엔드는 수정하지 않았다. 원본 파일의 import 및 Clause/OCRResponse 클래스 AST만 분리 실행하여 실제 모델 검증을 통과했다. 전체 백엔드 런타임 호환성 통과로 보고하지 않는다.
api_response(..., for_analysis=True)는 미검토 조항을 거부한다. API 프리뷰는 사용자 검토 화면용이며 /api/analyze에 직접 보내면 안 된다. 엔드포인트 연결·위험 규칙은 구현하지 않았다.

## 캐시와 재실행

구조화 캐시는 OCR JSON, PDF, 렌더/대비 조건, 패키지·모델 파일, 이미지, 코드, 후보 해시가 같고 결과 파일 해시도 정상일 때 재사용한다. 변경 시 기존 출력을 덮어쓰지 않고 새 --output을 요구한다. 과거 OCR 캐시의 실행 이력은 legacy_unverified로 표시한다.
ocr_pages.py에 --pages, --retry-from, 신규 --output을 추가했다. 기존 소스의 predict generator를 list로 완료한 뒤 시간을 재도록 수정했다. 기존 753.11초는 저장값이며 수정 전 타이밍 위치 때문에 이번 작업에서 실측 검증한 수치로 인용하지 않는다.
```bash
python scripts/structure_ocr.py --output tmp/ocr_pages/structured_release --candidates tmp/ocr_test/region_sg0tszng/R1/candidate.json
# 특정 페이지만 새 폴더에 OCR (이번 작업에서 재실행하지 않음)
python scripts/ocr_pages.py --pages 1 --output tmp/ocr_pages/retry_page1
# 실패 페이지 재실행
python scripts/ocr_pages.py --retry-from tmp/ocr_pages/ocr_pages_result.json --output tmp/ocr_pages/retry_failed
python -m unittest discover -s tests -v
```

## 검증과 파일

기존37 + 추가19 = 56개 테스트 통과, 실패0. 캐시 재사용 CLI 확인. 보호 대상22개 파일 해시 변경 없음. 실제 신규 OCR 및 엔드포인트 호출은 미실행.
출력: tmp/ocr_pages/structured_release/{structured_contract.json,api_ocr_response.json,validation_result.json,cache_manifest.json}. 원본 캐시/TXT는 변경하지 않았다.
이번 소스 변경: scripts/structure_ocr.py(신규), tests/test_ocr_structure.py(신규), scripts/ocr_pages.py(보완), docs/ocr_structuring_report.md(신규). 기존 미추적 D-7 파일과 구분해 검토한다.
GitHub Desktop에 위 소스·테스트·문서만 포함. tmp/, PDF, .venv/ 제외. 추천 커밋: feat: structure OCR clauses and validate extraction. Git 변경 작업 미실행.

## 남은 작업

C001의 표 경계·읽기 순서 검토, 특약 경계의 사람 검증, 빈칸/체크 영역 라벨링, 캐시 실행 provenance 보강, Python 런타임 합의가 필요하다. 따라서 위험 엔진으로 검증 완료 데이터를 자동 전달하는 단계는 아직 준비되지 않았다.
