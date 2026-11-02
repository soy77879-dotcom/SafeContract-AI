# SafeContract-AI

청년 임차인을 위한 AI 기반 전월세 계약 사전 검토 시스템

## 프로젝트 소개

<!-- 프로젝트의 목적과 서비스 개요를 작성해 주세요. -->

## 제작 배경 및 목적

<!-- 해결하려는 문제와 프로젝트의 목표를 작성해 주세요. -->

## 주요 기능

<!-- 주요 기능을 작성해 주세요. -->

## 서비스 흐름

<!-- 계약서 업로드부터 검토 결과 확인까지의 흐름을 작성해 주세요. -->

## 기술 스택

<!-- 사용한 기술과 각 기술의 역할을 작성해 주세요. -->

## 시스템 구성

<!-- 시스템 구성도와 설명을 추가해 주세요. -->

## 실행 방법

<!-- 개발 환경, 설치 과정, 실행 명령어를 작성해 주세요. -->

## 개발 결과 및 기대 효과

<!-- 구현 결과와 기대 효과를 작성해 주세요. -->

## 팀 소개

<!-- 팀원과 역할을 작성해 주세요. -->

## D-8 PDF 데이터 및 OCR 기준 데이터 후보

사용자가 제공한 Desktop PDF 3개를 복사하여 보관했다. 원본 이름과 저장 이름,
SHA-256, 실제 페이지 수, 발행정보 및 공식 게시물 URL은
`data/metadata/document_manifest.json`에 기록되어 있다. PDF 원본은 수정하지 않았다.

```text
data/
├── contracts/original/standard_contract.pdf
├── legal/housing_lease_act.pdf
├── cases/dispute_cases.pdf
├── ocr/
│   ├── sample_contract.json
│   └── extraction_review.json
└── metadata/document_manifest.json
scripts/
├── extract_contract_text.py
└── validate_contract_json.py
```

- 표준계약서: 실제 5쪽, 텍스트 추출 가능. 제1~13조와 인쇄된 특약 6개를 선별했다.
- `housing_lease_act.pdf`: **2020년 8월 주택임대차보호법 해설집**(74쪽).
  법령 단독본이나 최신 법령으로 간주하지 않는다. 표지의 2020.7.31.은 대상 법의 개정일이다.
- 사례집: 2021년 12월 발행, 101쪽의 이미지 기반 PDF. 추출 가능한 텍스트가 없으며 OCR은 수행하지 않았다.
- 법률 해설집과 사례집은 원본·메타데이터만 보관한다. 계약 조항 데이터에 섞지 않았다.
- 공식 게시물은 확인했으나 웹 첨부파일과 로컬 PDF의 바이트 동일성은 검증하지 않았다.

### 데이터의 검증 수준

`sample_contract.json`은 **실제 OCR 출력이 아닌 OCR 결과 검증용 기준 데이터 후보**다.
19개 조항 모두 `needs_review`이며 사람의 원문 대조가 끝난 Ground Truth가 아니다.
자동 텍스트 대조 통과를 `verified`로 승격하지 않는다.

`text`는 PDF 텍스트 블록의 빈칸·줄바꿈을 보존하되, AI 시각 대조에서 확인한 원화·글머리표 오류 19곳을 수정했다. 변경 전 텍스트는 해당 조항의 `original_extracted_text`에 보존한다. 제4조 수선 책임 표는
원시 추출 순서상 페이지 끝에 있어 ③과 ④ 사이로 블록을 배치했다.
각 조항의 `source_blocks`는 0부터 시작하는 텍스트 블록 인덱스와 PDF 좌표를 기록하며,
`page`는 인쇄된 쪽수와 관계없이 1부터 시작하는 실제 PDF 페이지 번호다.
`category`와 `related_categories`는 개발용 분류로, 법률 해석이나 공식 분류가 아니다.
한 조항 안의 여러 조건과 표를 함께 보존해 문맥을 유지한다.

알려진 검토 사항은 `extraction_review.json`에 기록했다.
PDF 확대 이미지와 대조하여 C001의 역슬래시 13곳을 `₩`로, C014~C019의 `Ÿ` 6곳을 `•`로 수정했다. 문자별 변경 전후·위치·사유는 `character_corrections`에 기록했다. 시각적 기호의 Unicode 전사이며 사람의 승인은 아직 없다.
표의 읽기 순서·빈칸·줄바꿈·숫자와 조항 번호는 사람이 확인해야 한다.
입주일이나 금액 등 미기입 값은 생성하지 않는다. 정액 중도해지 위약금은 `not_found`로 기록했다.
3쪽의 빈 특약/서명 양식 및 4~5쪽 별지 안내·갱신거절통지서는 조항 선별에서 제외했다.

### 실행

Python 3.9 이상 및 PyMuPDF 1.26.5가 필요하다. 개발 환경에는 처음에 PDF 라이브러리가 없어
이번 작업은 프로젝트 밖 임시 가상환경에서 실행했다. 재실행 환경은 아래처럼 준비한다.

```bash
python3 -m venv /tmp/safecontract-pdf-env
/tmp/safecontract-pdf-env/bin/python -m pip install PyMuPDF==1.26.5
/tmp/safecontract-pdf-env/bin/python scripts/validate_contract_json.py --report data/ocr/extraction_review.json
```

결과를 새 경로에 재추출하여 비교하려면:

```bash
/tmp/safecontract-pdf-env/bin/python scripts/extract_contract_text.py \
  --output /tmp/sample_contract.json --review /tmp/extraction_review.json
```

기본 출력 경로는 `data/ocr/`이며 기존 파일이 있으면 추출을 중단한다.
`--force`는 기존 결과와 검토 이력을 초기화하므로 의도적으로 재생성할 때만 사용한다.
선별 프로필은 이번 원본 SHA-256과 PyMuPDF 버전에 한정되어 있다.
다른 PDF는 페이지/텍스트 레이어를 검사한 후 임의 추출을 중단한다.
스캔 PDF에 OCR을 실행하거나 내용을 만들어 채우지 않는다.

검증기는 필수 필드·타입·ID 중복·페이지·원본 파일·해시·조항 선별 범위·원문 블록·숫자를 확인한다.
공백 차이와 텍스트 불일치는 사람이 판단할 검토 항목으로 분리한다.
종료 코드 0은 자동 구조/원본 검사에서 확정 실패가 없다는 뜻이며 사람 검증 완료를 뜻하지 않는다.
실패는 코드 1로 반환한다. 출력의 `status`, `needs_review`, `unverified`도 반드시 확인한다.
`--report`는 기존 검토 항목을 유지하면서 `automatic_validation`을 갱신한다.

19개 전체 텍스트와 PDF 페이지·위치·사람 확인 항목은 `data/ocr/human_review.md`에 정리했다. 다음 단계는 이 목록으로 사람이 대조하고 기호·표 읽기 순서를 확인하는 것이다. 기존 검증기는 보정 전 텍스트 레이어를 비교하므로 수정한 7개 조항을 `text_difference`로 표시한다. 이 7건은 변경 이력 재적용 검증을 통과했으며 `visual_correction_validation`에 기록되어 있다.
승인된 조항은 검토자·검토일·방법을 `human_verification`에 기록한 뒤에만 `verified`로 변경한다.
OCR, FastAPI, AI 분석 및 프론트엔드는 이번 작업 범위에 포함하지 않는다.
