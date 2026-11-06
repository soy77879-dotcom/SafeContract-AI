# D-7 잔여 오류 2건 점검

## C001: 해결된 평가 범위와 잔여 OCR 오류

원본 OCR에는 P001_L056 `[계약내용]`이 존재하지만 제N조 시작부터 묶는 구조화 코드에서 제외되었다. GT C001에는 이 제목이 포함돼 있어 정확한 줄 집합 비교가 실패했다. 원본 OCR 누락이나 제2조 침범이 아니었다.

추가로 관리비 표의 GT 읽기 순서는 열 방향(1·3·5·7, 2·4·6·8), 원본 OCR 직렬화 순서는 행 방향이었다. 관리비 행 제목도 세로 중앙에 있어 본문 순서와 달랐다. 이는 글자 인식 오류와 구분되는 읽기 순서 문제다. 금액이 실제로 기입됐다는 뜻이 아니며 입력값은 여전히 unknown/null이다.

일반 규칙으로 인접한 독립 대괄호 구획 제목을 다음 제N조에 연결했다. 특정 페이지·조항 번호·제목 문자열·GT 조항 개수는 사용하지 않는다. 제목과 조항 사이의 위치·거리 및 중간 내용 유무로 결정한다. 새 문서 전체에 대한 일반화 성능을 입증한 것은 아니다.

구획 제목이 포함된 조항의 평가에서는 검증된 PDF source_blocks 좌표 및 순서에 OCR 줄을 대응시킨다. 제외/모호한 줄이 있으면 평가를 거부한다. 이번 C001은 모든 줄이 각 블록에 유일하게 대응했다. 이 정렬은 평가에서만 사용하며 API 원문·OCR 문자·GT를 변경하지 않는다. CER 계산식과 공백 정책은 그대로다.

| 평가 | Raw CER | Normalized CER |
|---|---:|---:|
| C001 (범위 및 평가 읽기 순서 정렬 후) | 55.1136% (485/880) | 5.2632% (18/342) |

범위만 수정하고 행 순서를 그대로 비교하면 57.7273% / 13.1579%였다. 이 차이를 OCR 모델 정확도 개선으로 보고하지 않는다. 빈칸·줄바꿈·통화 기호 등의 실제 인식 차이가 남아 있다.

C001~C019 모두 평가 가능, 누락·중복·역순 없음. C002~C019의 raw_text, source_lines, 기존 CER는 이전 structured_release와 동일함을 확인했다. 원본 PDF·GT·기존 OCR 캐시는 보존했다.

결과: `tmp/ocr_pages/c001_aligned/`의 structured_contract.json, api_ocr_response.json, validation_result.json. 블록별 line_id 대응은 validation_result.json의 reading_order_alignment에 기록했다.

## 백엔드: 미해결

실제 Python 3.9.6 가상환경에서 오류가 각각 재현됐다.

1. `backend/main.py:4`: `ModuleNotFoundError: No module named 'fastapi'`. FastAPI와 Uvicorn 미설치.
2. `backend/schemas.py:67`: `field: str | None = None`에서 TypeError. Python 3.9의 타입 union 문법 비호환. import 경로 문제는 아니다.
3. 기존 requirements 설치를 시도했지만 현재 Python용 배포판이 없어 실패했다. 네트워크 제한으로 실패한 첫 시도와 별개로, 네트워크 접근 후 PyPI 공식 메타데이터에서 다음 조건을 확인했다.

| 고정 의존성 | Python 요구사항 |
|---|---|
| fastapi==0.162.0 | >=3.10 |
| uvicorn==0.54.0 | >=3.10 |
| python-multipart==0.0.33 | >=3.11 |

확인 근거: 각 패키지의 `https://pypi.org/pypi/{package}/{version}/json` requires_python. 임의로 버전을 낮추거나 requirements를 변경하지 않았다.

승인 요청한 최소 스키마 수정안은 `Optional` import 추가와 `field: Optional[str] = None`이다. `tmp/d7_fixes/backend_python39.patch`에 저장했다. 제안된 전체 스키마를 메모리에서만 실행해 OCRResponse 19개 조항과 ErrorDetail의 null 기본값 검증은 통과했다. 실제 backend 파일은 수정하지 않았고 전체 import 해결로 보고하지 않는다.

담당자 B와 결정할 사항: (A) 고정 의존성을 유지하려면 Python 3.11 이상 환경을 별도 승인하여 마련하거나, (B) Python 3.9를 유지하려면 호환되는 의존성 버전을 합의하고 최소 스키마 변경을 승인해야 한다. 후자의 스키마 두 줄만 수정해도 의존성 문제는 별도로 남는다.

FastAPI 서버 실행 및 /api/health는 의존성 문제로 미검증. API 필드/응답 규격은 변경하지 않았다. 원본 OCRResponse의 분리 검증 및 API 대응 검사는 통과했으나 전체 백엔드 import 검증과 구분한다.

## 검증 및 커밋 대상

기존 56개 + 추가 3개 = 59개 테스트 통과. 보호 파일 22개 해시 변경 없음. dev/01 유지, commit/push/merge 미실행.

이번 변경 파일:
- scripts/structure_ocr.py
- tests/test_ocr_structure.py
- docs/d7_remaining_fixes.md

위 세 파일만 이번 수정에 해당한다. 기존 미추적 D-7 파일은 별도 작업 이력이다. tmp/, PDF, .venv/ 및 미승인 backend 수정안은 커밋에서 제외한다.

실제 Traceback 및 검증 기록: tmp/d7_fixes/. 기존 docs/ocr_structuring_report.md는 수정 전 결과 기록이며, C001의 최신 상태는 이 문서를 따른다.
