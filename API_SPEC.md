# SafeContract AI — API 입·출력 규격 정의서

> **문서 버전:** v0.2.0 (A/B 합의 전 초안)  
> **작성일:** 2026-11-02 (D-8)  
> **담당:** B — FastAPI·Pydantic·위험 분석 / A — 업로드·OCR·입력 UI  
> **분석 범위:** **계약서 자체만** 분석. 상담 내용 입력·비교·일치/불일치 판정 기능은 포함하지 않음.  
> **목표:** A/B 합의 후 API Contract v1.0.0 확정

## 1. 목적 및 범위

SafeContract AI는 사용자가 업로드한 **전월세 계약서의 조항만을** 검토하여 잠재적 위험 표현을 찾고, 원문 근거·위험 사유·예상 불이익·확인 질문·권장 행동을 설명하는 사전 검토 보조 웹서비스다. **법률적 효력이나 사기 여부를 확정하지 않는다.**

- **포함:** 계약서 이미지 업로드, 개인정보 마스킹, OCR, 사용자 OCR 문구 확인·수정, 규칙+LLM 조항 분석, 근거 하이라이트, 결과 표시.
- **제외:** 상담 원문 입력, 상담 조건 추출, 상담 내용과 계약서 비교, `match`/`mismatch` 판정.
- **D-8 범위:** API 계약·테스트 데이터 확정과 서버 실행. 실제 OCR/LLM 완성은 후속 단계.

## 2. 파이프라인과 API

```text
사용자 계약서 이미지 선택
  → [A] 브라우저 개인정보 마스킹·업로드
  → POST /api/ocr (multipart/form-data)
  → [A] 조항 분리 및 OCRResponse JSON 생성
  → [A] OCR 텍스트 사용자 확인·수정
  → [B] 최종 개인정보 검사
  → POST /api/analyze (application/json)
  → [B] 규칙 검사 + 필요한 경우 LLM 분석 + 근거 검증
  → AnalyzeResponse JSON
  → [A/B] 원문 하이라이트·설명 결과 UI
```

| Method | Endpoint | 입력 | 정상 응답 | 담당 |
|---|---|---|---|---|
| GET | `/api/health` | 없음 | `{"status":"ok","service":"SafeContract AI"}` | B |
| POST | `/api/ocr` | `multipart/form-data` 이미지 배열 `files` | `OCRResponse` | A |
| POST | `/api/analyze` | `AnalyzeRequest` JSON | `AnalyzeResponse` | B |

**원칙:** `/api/ocr`는 텍스트 추출만 담당하며 위험 판정을 하지 않는다. `/api/analyze`는 **사용자가 확인·수정한 조항 텍스트**만 받고, 이미지 자체는 받지 않는다. 문서 내 조항 ID는 변경하지 않는다.

## 3. 공통 데이터 규칙 (A/B 반드시 준수)

| 필드 | 타입 | 필수 | 규칙 |
|---|---|---|---|
| `document_id` | string | 예 | 문서마다 고유한 비식별 ID; 이름·주소·주민번호를 포함하지 않음 |
| `clauses` | array | 예 | 계약서에서 추출한 조항 배열, 원문 순서 유지. 0개면 분석 요청 거절 |
| `clause_id` | string | 예 | 문서 내 고유 ID: `C001`, `C002` 등. OCR과 분석 결과 간 동일하게 유지 |
| `page` | integer | 예 | 원문 페이지, **1부터 시작** |
| `text` | string | 예 | 비어 있지 않은 OCR 조항 원문, UTF-8, 사용자 수정 반영 |

- JSON 필드: `snake_case`; 문자 인코딩: UTF-8; JSON 요청은 `Content-Type: application/json`.
- `document_id`는 같은 문서의 OCR 응답·분석 요청·분석 응답에서 동일하다.
- `clause_id`는 **해당 문서 안에서 중복 금지**. OCR 수정으로 내용만 변경되었다면 ID는 그대로 유지한다.
- PDF 원본 페이지에서 조항이 여러 페이지에 걸친 경우 MVP에서는 **시작 페이지**를 `page`에 기록한다.
- OCR이 글을 읽지 못한 부분을 임의로 만들어 채우지 않는다. 문구가 불분명하다면 사용자가 확인·수정하도록 안내한다.
- OCR의 `text`는 의미상 요약본이 아니라 **계약서 원문에 가까운 텍스트**를 저장한다.

## 4. A 담당: `POST /api/ocr`

### 4.1 요청

- Content-Type: `multipart/form-data`
- 필드: **`files` (반복)** — JPG/JPEG/PNG 이미지 1~5장.
- 파일 크기: 장당 최대 **10 MiB**, 전체 최대 **50 MiB**, 장당 최대 **2천만 픽셀**.
- 서버는 확장자·실제 파일 형식·파일 크기·픽셀 수를 재검증한다.
- 클라이언트는 브라우저에서 개인정보를 마스킹한 이미지 전송을 목표로 한다. 프론트엔드 마스킹만으로 개인정보 보호가 완료된 것으로 간주하지 않는다.

### 4.2 정상 응답: `OCRResponse` (HTTP 200)

**A는 아래 JSON을 최우선으로 구현한다. 이 구조를 바꾸려면 B와 합의해야 한다.**

```json
{
  "document_id": "sample_contract_001",
  "clauses": [
    {
      "clause_id": "C001",
      "page": 1,
      "text": "임대인은 계약 종료 후 새로운 임차인이 입주한 경우에만 보증금을 반환한다."
    },
    {
      "clause_id": "C002",
      "page": 1,
      "text": "임차인은 고장의 원인과 관계없이 모든 시설물의 수리비를 부담한다."
    },
    {
      "clause_id": "C003",
      "page": 1,
      "text": "임차인은 어떠한 사유로도 계약기간 중 계약을 해지할 수 없다."
    }
  ]
}
```

**OCR 단계에서 A가 지켜야 할 것**

1. 이미지 한 장에 여러 조항이 있다면 `clauses`를 여러 개 만든다.
2. 한 조항에 고유 `clause_id`를 부여하고, 원문 순서를 보존한다.
3. 분석 전 화면에서 사용자가 `text`를 확인·수정할 수 있게 한다.
4. 이미지의 실제 이름·연락처·주소·주민번호 등을 테스트 데이터에 넣지 않는다.
5. 위험 등급·예상 불이익 등은 OCR JSON에 추가하지 않는다. 그 판단은 B의 책임이다.
6. OCR 완성 전에는 이 샘플 JSON을 **모의 OCR 응답(mock)** 으로 사용해도 된다.

### 4.3 OCR 실패

HTTP 오류 응답은 §7의 공통 형식을 사용한다. 일부 이미지만 성공한 경우에는 **이번 MVP에서 불완전한 OCR 응답을 성공으로 가장하지 않고**, 사용자에게 실패 이미지를 재확인하게 한다. 부분 성공 처리를 추가하려면 A/B 합의 후 별도 필드를 도입한다.

## 5. B 담당: `POST /api/analyze`

### 5.1 요청: `AnalyzeRequest`

- Content-Type: `application/json`
- **상담 내용, 상담 ID, 비교 모드 필드 없음.**
- 요청 형식은 사용자 확인을 거친 **OCRResponse와 완전히 동일**하다.
- `clauses` 배열이 비어 있으면 HTTP 422로 거절한다.

```json
{
  "document_id": "sample_contract_001",
  "clauses": [
    {
      "clause_id": "C001",
      "page": 1,
      "text": "임대인은 계약 종료 후 새로운 임차인이 입주한 경우에만 보증금을 반환한다."
    },
    {
      "clause_id": "C002",
      "page": 1,
      "text": "임차인은 고장의 원인과 관계없이 모든 시설물의 수리비를 부담한다."
    },
    {
      "clause_id": "C003",
      "page": 1,
      "text": "임차인은 어떠한 사유로도 계약기간 중 계약을 해지할 수 없다."
    }
  ]
}
```

### 5.2 상태값 정의

**중요: 계약서만 분석하므로 `일치`/`불일치` 분류를 사용하지 않는다.**

| 필드 | 허용 값 | 뜻 | 화면 표시 |
|---|---|---|---|
| `status` (API 처리) | `completed` | 모든 대상 조항 처리 완료 | 분석 완료 |
| `status` (API 처리) | `partial` | 일부 조항을 분석하지 못함 | 일부 결과 확인 필요 |
| `risk_status` (조항 판정) | `potential_risk` | 잠재적 위험 또는 불리할 수 있는 조항 | 위험 |
| `risk_status` (조항 판정) | `needs_review` | 문구가 모호하거나 근거 부족 | 확인필요 |
| `risk_status` (조항 판정) | `no_risk_detected` | **검사한 범위**에서 위험 미탐지 | 위험 미탐지 |

`no_risk_detected`는 법적으로 안전하다는 보장이 아니다. 기술적 오류·LLM 장애는 `no_risk_detected`가 아니라 `partial` 또는 HTTP 오류로 표현한다.

### 5.3 분석 결과 필드: `RiskResult`

| 필드 | 타입 | 필수 | 규칙 |
|---|---|---|---|
| `clause_id` | string | 예 | 요청의 `clauses[].clause_id` 중 하나와 동일 |
| `risk_type` | string | 예 | `deposit_return`, `repair_cost`, `termination`, `restoration`, `fee`, `other`, `none` 중 하나로 시작 (추가 시 합의) |
| `risk_status` | enum | 예 | `potential_risk` / `needs_review` / `no_risk_detected` |
| `evidence` | string | 예 | **해당 `clause_id`의 `text`에 실제 존재하는 원문 문구** |
| `reason` | string | 예 | 해당 상태로 분류한 구체적 이유 |
| `possible_disadvantage` | string | 예 | 실제로 예상 가능한 불이익; 불명확하면 빈 문자열 `""` |
| `question` | string | 예 | 계약 전 확인할 질문; 해당 없으면 `""` |
| `recommended_action` | string | 예 | 사용자 권장 행동; 해당 없으면 `""` |

- 위험 유형이 **여러 개**인 조항은 같은 `clause_id`의 `RiskResult`가 여러 개 나올 수 있다.
- 한 조항에 위험이 없으면 `risk_type: "none"`, `risk_status: "no_risk_detected"` 1건을 반환한다.
- 명확하지 않은 조항은 `needs_review`로 표시하며 **위험 미탐지로 대체하지 않는다**.
- `evidence`는 원문에서 문자 그대로 찾을 수 있어야 하며, 근거 없는 문장을 만들어 내면 안 된다.
- 화면 하이라이트는 `clause_id`와 `evidence`를 이용한다. OCR 오탈자 때문에 근거를 찾기 어렵다면 사용자 확인을 요청한다.

### 5.4 정상 응답: `AnalyzeResponse` (HTTP 200)

아래는 **테스트용 합성 계약서**에 대한 예시 결과다. 법률적 확정 판단이나 실제 모델 출력이 아니다.

```json
{
  "document_id": "sample_contract_001",
  "status": "completed",
  "results": [
    {
      "clause_id": "C001",
      "risk_type": "deposit_return",
      "risk_status": "potential_risk",
      "evidence": "새로운 임차인이 입주한 경우에만 보증금을 반환한다",
      "reason": "보증금 반환을 새로운 임차인의 입주 여부에 연동하고 있습니다.",
      "possible_disadvantage": "새로운 임차인이 구해지지 않을 경우 보증금 반환이 지연될 수 있습니다.",
      "question": "새 임차인이 입주하지 않아도 계약 종료 시 보증금을 반환받을 수 있나요?",
      "recommended_action": "보증금 반환 조건과 시점을 임대인·중개인에게 확인하고 필요하다면 특약 수정을 요청하세요."
    },
    {
      "clause_id": "C002",
      "risk_type": "repair_cost",
      "risk_status": "potential_risk",
      "evidence": "고장의 원인과 관계없이 모든 시설물의 수리비를 부담한다",
      "reason": "고장 원인이나 책임 소재를 구분하지 않고 임차인에게 수리비를 부담시키고 있습니다.",
      "possible_disadvantage": "임차인의 귀책사유가 없는 고장에도 수리비를 부담하도록 요구받을 수 있습니다.",
      "question": "노후화나 자연적인 고장도 임차인이 전부 부담하나요?",
      "recommended_action": "수리 책임 범위와 예외를 확인하고 계약서에 명확히 기재하도록 요청하세요."
    },
    {
      "clause_id": "C003",
      "risk_type": "termination",
      "risk_status": "potential_risk",
      "evidence": "어떠한 사유로도 계약기간 중 계약을 해지할 수 없다",
      "reason": "계약 중 해지 가능성을 예외 없이 제한하는 문구입니다.",
      "possible_disadvantage": "불가피한 사정이 생겼을 때 해지 조건을 둘러싼 분쟁이 발생할 수 있습니다.",
      "question": "법령상 또는 계약상 정당한 해지 사유에도 이 조항을 적용하나요?",
      "recommended_action": "해지 예외 사유와 위약금 조건을 확인하고 필요하면 전문가에게 검토를 요청하세요."
    }
  ],
  "warnings": []
}
```

**`AnalyzeResponse` 필수 필드:** `document_id`(string), `status`(`completed`/`partial`), `results`(RiskResult 배열), `warnings`(string 배열).

처리가 `partial`일 때는 실패한 조항 ID나 이유를 `warnings`에 기재하여 사용자가 해당 조항을 재검토하도록 한다. 전체 분석 실패는 HTTP 오류 (§7)로 처리한다.

### 5.5 분석 품질 원칙

1. 금액·기간·숫자 등 명시적 정보는 가능하면 규칙 기반으로 확인한다.
2. LLM은 복잡한 문구의 의미 파악과 설명 생성을 지원한다.
3. LLM 출력은 Pydantic 구조 검증을 통과해야 한다.
4. `evidence`가 실제 요청 원문에 포함되는지 프로그램으로 검사한다.
5. 판정이 불충분하면 `needs_review`를 사용한다. 임의 확신도 숫자를 만들어 표시하지 않는다.
6. 향후 성능은 위험 탐지 Precision/Recall/F1, 원문 근거 연결 정확도, JSON 검증 통과율로 평가한다.

## 6. A 담당 화면 구현을 위한 매핑 규칙

- 업로드 후 `POST /api/ocr` → `clauses`를 수정 가능한 텍스트 영역으로 표시.
- 사용자가 확인 버튼을 누르면 수정된 `document_id` + `clauses`를 `POST /api/analyze`에 그대로 전달.
- 분석 결과 `results`의 `clause_id`로 OCR 조항과 연결.
- 각 결과의 `risk_status`에 따라 **위험 / 확인필요 / 위험 미탐지** 표시.
- 결과 카드에 `evidence`, `reason`, `possible_disadvantage`, `question`, `recommended_action` 노출.
- `status: "partial"`이면 `warnings`를 화면에 표시하고 **전체 분석 완료로 표시하지 않음**.
- 마스킹된 문서만 업로드하며 테스트·디버그 로그에 계약서 전문을 출력하지 않는다.

## 7. 공통 오류 응답

성공 응답 모델과 오류 응답 모델을 구분한다. HTTP 오류 시 다음 포맷을 사용한다.

```json
{
  "status": "error",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "요청 데이터를 확인해 주세요.",
    "field": "clauses"
  }
}
```

| HTTP | `error.code` | 설명 |
|---|---|---|
| 400 | `INVALID_REQUEST` | 잘못된 입력 또는 조항 ID 중복 |
| 413 | `FILE_TOO_LARGE` | 업로드 크기 제한 초과 |
| 415 | `UNSUPPORTED_FILE_TYPE` | 허용되지 않는 파일 |
| 422 | `VALIDATION_ERROR` | Pydantic 필드/자료형/빈 조항 등 유효성 실패 |
| 422 | `PRIVACY_CHECK_FAILED` | 추가 개인정보 확인 필요 |
| 500 | `OCR_PROCESSING_ERROR` | OCR 실패 |
| 500 | `ANALYSIS_ERROR` | 내부 분석 오류 |
| 503 | `LLM_SERVICE_UNAVAILABLE` | 외부 모델 서비스 이용 불가 |

FastAPI 기본 422 응답은 위 JSON과 다르므로 **B가 공통 예외 핸들러를 구현할 때** 규격에 맞게 변환해야 한다. 현재는 합의된 목표 형식이며 구현 완료를 의미하지 않는다.

## 8. 개인정보 및 운영 원칙

- 실제 신분 정보, 연락처, 상세 주소 등은 **합성 테스트 문서에 포함하지 않는다**.
- 프론트엔드 마스킹 → 서버 최종 검사 → 필요 최소화된 분석 입력 전달.
- 이미지·OCR 전문·LLM 요청 본문·API 키를 일반 로그에 남기지 않는다.
- 소스 저장소에 `.env`, `uploads/`, `temp/`, `private_data/`, `.venv/`를 업로드하지 않는다.
- 이미지 및 OCR 텍스트는 원칙적으로 영구 저장하지 않는다. 임시 저장이 불가피하면 별도 보안 및 삭제 절차를 둔다.
- 외부 OCR/LLM 사업자 사용 시 데이터 전송·보존 정책을 별도로 검토한다.
- 개인정보 자동 마스킹의 정확성이 입증된 것은 아니며, 사용자 확인 절차가 필요하다.

## 9. D-8 공동 검증 (체크리스트)

- [ ] A와 B가 **상담 비교 없이 계약서만 분석**하는 범위에 합의
- [ ] A의 `/api/ocr` 응답이 §4.2 JSON과 동일
- [ ] A의 OCR 결과에서 `clause_id` 중복 없음, `page >= 1`, `text` 비어 있지 않음
- [ ] B의 `backend/schemas.py`에서 `OCRResponse`/`AnalyzeRequest` 검증 통과
- [ ] A가 OCR 텍스트를 수정한 뒤 `/api/analyze` 요청 생성 가능
- [ ] B의 `AnalyzeResponse`가 §5.4 형식과 일치
- [ ] `RiskResult.clause_id`가 실제 OCR 조항에 존재
- [ ] `RiskResult.evidence`가 해당 OCR 조항 `text`의 원문에 존재
- [ ] `/api/health` 정상 응답
- [ ] A/B 각각 `dev/01`·`dev/02`에서 작업, PR로 공통 스키마 병합

## 10. 변경 관리 및 합의 사항

- 이 문서는 **v0.2.0 초안**이다. A와 검토 후 **v1.0.0**으로 확정한다.
- 필드명·타입·필수 여부·상태값 변경 시 **반드시 A/B 합의**, 문서·`schemas.py`·샘플 JSON·테스트 동시 변경.
- 문서 수정만 하면 `v1.0.1`, 호환되는 선택 필드 추가는 `v1.1.0`, 기존 연동을 깨는 변경은 `v2.0.0`처럼 관리할 수 있다.
- **주의:** 기존 `schemas.py`에는 `AnalyzeResponse.warnings`가 없을 수 있으며, 조항 중복·원문 근거 검사도 구현되지 않았을 수 있다. 이 문서는 목표 계약이므로 **현재 코드가 자동으로 이 전부를 만족하는 것은 아니다**.

### A와 우선 합의할 항목

1. OCR 조항 분리 단위(한 문장/한 조/특약 묶음).
2. 문서 ID 생성 주체(A의 `/api/ocr`) 및 사용자가 OCR 문구 수정 시 ID 유지 규칙.
3. 기본 위험 유형 코드(`deposit_return`, `repair_cost`, `termination` 등)와 결과 UI 표시 문구.
4. 일부 조항 OCR 실패 시 전체 요청 재시도 원칙과 향후 부분 성공 확장 여부.

---

**최종 핵심:** A는 **§4.2의 OCRResponse JSON**을 출력하고, 사용자 수정 후 **§5.1의 AnalyzeRequest JSON**을 B에게 전달한다. B는 **§5.4의 AnalyzeResponse JSON**을 반환한다. 상담 관련 필드는 어느 API에도 들어가지 않는다.
