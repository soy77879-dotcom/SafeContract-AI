
"""B-2: OCR 결과의 조항 ID와 페이지 연결 일관성 검증."""

import re

from backend.schemas import OCRResponse
from scripts.structure_ocr import api_response


def validate_ocr_consistency(result):
    """OCR Worker의 구조화 결과와 API 응답 간 일관성을 검사한다."""
    errors = []

    pages = result.get("ocr_pages", [])
    clauses = result.get("clauses", [])

    page_numbers = [page.get("page") for page in pages]
    expected_pages = list(range(1, len(pages) + 1))

    if page_numbers != expected_pages:
        errors.append("OCR 페이지 번호가 1부터 연속되지 않습니다.")

    valid_pages = set(page_numbers)
    seen_ids = set()

    for index, clause in enumerate(clauses, start=1):
        clause_id = clause.get("clause_id")
        expected_id = f"C{index:03}"

        if clause_id in seen_ids:
            errors.append(f"중복된 조항 ID: {clause_id}")

        seen_ids.add(clause_id)

        if not isinstance(clause_id, str) or not re.fullmatch(
            r"C\d{3,}", clause_id
        ):
            errors.append(f"잘못된 조항 ID 형식: {clause_id}")

        if clause_id != expected_id:
            errors.append(
                f"조항 ID 순서 오류: {clause_id}, 예상: {expected_id}"
            )

        clause_pages = clause.get("pages", [])
        source_lines = clause.get("source_lines", [])

        if not clause_pages:
            errors.append(f"{clause_id}: 페이지 정보가 없습니다.")
            continue

        if any(page not in valid_pages for page in clause_pages):
            errors.append(f"{clause_id}: 존재하지 않는 OCR 페이지가 있습니다.")

        if len(clause_pages) != len(set(clause_pages)):
            errors.append(f"{clause_id}: 페이지 번호가 중복되었습니다.")

        if not source_lines:
            errors.append(f"{clause_id}: 원본 OCR 줄 정보가 없습니다.")

        source_pages = {line.get("page") for line in source_lines}

        if source_pages != set(clause_pages):
            errors.append(f"{clause_id}: 조항 페이지와 원본 줄 페이지가 다릅니다.")

        if not clause.get("raw_text", "").strip():
            errors.append(f"{clause_id}: 조항 텍스트가 비어 있습니다.")

    if not errors:
        try:
            payload = api_response(result)
            OCRResponse.model_validate(payload)

            for clause, api_clause in zip(clauses, payload["clauses"]):
                if api_clause["page"] != clause["pages"][0]:
                    errors.append(
                        f"{clause['clause_id']}: API 페이지 번호 불일치"
                    )

        except (ValueError, KeyError, TypeError) as exc:
            errors.append(f"OCR API 스키마 검증 실패: {type(exc).__name__}")

    return {
        "valid": len(errors) == 0,
        "page_count": len(pages),
        "clause_count": len(clauses),
        "errors": errors,
    }
