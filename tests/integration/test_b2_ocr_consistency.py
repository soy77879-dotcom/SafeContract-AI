
"""B-2 OCR 결과의 조항 ID 및 페이지 일관성 테스트."""

import copy
import unittest

from integrations.ocr_consistency import validate_ocr_consistency


def make_result():
    """정상적인 2페이지 OCR 결과를 생성한다."""
    return {
        "document_id": "test-document",
        "ocr_pages": [
            {"page": 1, "status": "completed", "lines": []},
            {"page": 2, "status": "completed", "lines": []},
        ],
        "clauses": [
            {
                "clause_id": "C001",
                "pages": [1],
                "source_lines": [
                    {"page": 1, "line_id": "P001_L001"}
                ],
                "raw_text": "첫 번째 조항",
                "verified_text": None,
            },
            {
                "clause_id": "C002",
                "pages": [1, 2],
                "source_lines": [
                    {"page": 1, "line_id": "P001_L002"},
                    {"page": 2, "line_id": "P002_L001"},
                ],
                "raw_text": "두 페이지에 걸친 조항",
                "verified_text": None,
            },
        ],
    }


class TestOCRConsistency(unittest.TestCase):

    def test_valid_result(self):
        """정상 OCR JSON은 검증을 통과한다."""
        result = validate_ocr_consistency(make_result())

        self.assertTrue(result["valid"])
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result["clause_count"], 2)
        self.assertEqual(result["errors"], [])

    def test_duplicate_clause_id(self):
        """조항 ID가 중복되면 검증에 실패한다."""
        data = make_result()
        data["clauses"][1]["clause_id"] = "C001"

        result = validate_ocr_consistency(data)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("중복" in error for error in result["errors"])
        )

    def test_wrong_clause_order(self):
        """조항 ID가 순서대로 생성되지 않으면 실패한다."""
        data = make_result()
        data["clauses"][1]["clause_id"] = "C003"

        result = validate_ocr_consistency(data)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("순서" in error for error in result["errors"])
        )

    def test_invalid_page(self):
        """실제 OCR 결과에 없는 페이지는 허용하지 않는다."""
        data = make_result()
        data["clauses"][1]["pages"] = [1, 3]

        result = validate_ocr_consistency(data)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("존재하지 않는" in error for error in result["errors"])
        )

    def test_source_page_mismatch(self):
        """원본 OCR 줄과 조항 페이지가 다르면 실패한다."""
        data = make_result()
        data["clauses"][1]["source_lines"][1]["page"] = 1

        result = validate_ocr_consistency(data)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("원본 줄 페이지" in error for error in result["errors"])
        )

    def test_empty_clause_text(self):
        """조항의 OCR 텍스트가 비어 있으면 실패한다."""
        data = make_result()
        data["clauses"][0]["raw_text"] = ""

        result = validate_ocr_consistency(data)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("텍스트가 비어" in error for error in result["errors"])
        )

    def test_nonsequential_ocr_pages(self):
        """OCR 페이지가 1부터 연속되지 않으면 실패한다."""
        data = make_result()
        data["ocr_pages"][1]["page"] = 3

        result = validate_ocr_consistency(data)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("연속되지" in error for error in result["errors"])
        )

    def test_duplicate_clause_page(self):
        """동일 조항의 페이지가 중복되면 실패한다."""
        data = make_result()
        data["clauses"][1]["pages"] = [1, 1, 2]

        result = validate_ocr_consistency(data)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any("페이지 번호가 중복" in error for error in result["errors"])
        )


if __name__ == "__main__":
    unittest.main()
