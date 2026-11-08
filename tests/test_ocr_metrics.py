import copy
import unittest

from scripts.ocr_metrics import (
    evaluate_clause_extraction,
    evaluate_ocr_texts,
)

class OCRMetricsTests(unittest.TestCase):
    def test_perfect_text(self):
        result = evaluate_ocr_texts(
            {"OCR-M001": "보증금 반환"},
            {"OCR-M001": "보증금 반환"},
        )

        self.assertEqual(result["micro"]["raw"]["cer"], 0.0)
        self.assertEqual(result["micro"]["normalized"]["cer"], 0.0)

    def test_character_substitutions(self):
        result = evaluate_ocr_texts(
            {"OCR-M001": "가나다"},
            {"OCR-M001": "가마라"},
        )

        self.assertEqual(
            result["micro"]["raw"]["edit_distance"], 2
        )
        self.assertAlmostEqual(
            result["micro"]["raw"]["cer"], 2 / 3
        )

    def test_whitespace_difference_is_reported_separately(self):
        result = evaluate_ocr_texts(
            {"OCR-M001": "임대인 부담"},
            {"OCR-M001": "임대인부담"},
        )

        self.assertGreater(result["micro"]["raw"]["cer"], 0)
        self.assertEqual(
            result["micro"]["normalized"]["cer"], 0.0
        )

    def test_missing_prediction_counts_as_deletion(self):
        result = evaluate_ocr_texts(
            {"OCR-M001": "가나"},
            {},
        )

        self.assertEqual(result["micro"]["raw"]["cer"], 1.0)
        self.assertEqual(
            result["missing_prediction_ids"], ["OCR-M001"]
        )

    def test_unknown_prediction_id_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError, "unknown_ocr_case_id"
        ):
            evaluate_ocr_texts(
                {"OCR-M001": "가나"},
                {"OCR-M999": "가나"},
            )

    def test_empty_reference_has_no_defined_cer(self):
        result = evaluate_ocr_texts(
            {"OCR-M001": ""},
            {"OCR-M001": "가"},
        )

        self.assertIsNone(result["micro"]["raw"]["cer"])
        self.assertEqual(
            result["micro"]["raw"]["empty_reference_ids"],
            ["OCR-M001"],
        )

    def test_micro_cer_uses_total_character_count(self):
        result = evaluate_ocr_texts(
            {"OCR-M001": "가나", "OCR-M002": "다라마바"},
            {"OCR-M001": "가다", "OCR-M002": "다라마바"},
        )

        self.assertEqual(
            result["micro"]["raw"]["reference_characters"], 6
        )
        self.assertAlmostEqual(
            result["micro"]["raw"]["cer"], 1 / 6
        )

    def test_cer_can_exceed_one(self):
        result = evaluate_ocr_texts(
            {"OCR-M001": "가"},
            {"OCR-M001": "가나다"},
        )

        self.assertEqual(result["micro"]["raw"]["cer"], 2.0)

class ClauseExtractionTests(unittest.TestCase):
    def setUp(self):
        self.reference = {
            "DOC001-P001": {
                "text": "가나다라마바",
                "spans": [[0, 2], [2, 4], [4, 6]],
            }
        }

    def test_perfect_boundaries(self):
        result = evaluate_clause_extraction(
            self.reference, copy.deepcopy(self.reference)
        )

        self.assertEqual(result["tp"], 3)
        self.assertEqual(result["fp"], 0)
        self.assertEqual(result["fn"], 0)
        self.assertEqual(result["f1"], 1.0)
        self.assertEqual(result["exact_page_accuracy"], 1.0)

    def test_merged_clauses_are_not_exact_matches(self):
        predicted = copy.deepcopy(self.reference)
        predicted["DOC001-P001"]["spans"] = [[0, 4], [4, 6]]

        result = evaluate_clause_extraction(
            self.reference, predicted
        )

        self.assertEqual(result["tp"], 1)
        self.assertEqual(result["fp"], 1)
        self.assertEqual(result["fn"], 2)
        self.assertAlmostEqual(result["precision"], 0.5)
        self.assertAlmostEqual(result["recall"], 1 / 3)
        self.assertAlmostEqual(result["f1"], 0.4)

    def test_split_clause_is_not_an_exact_match(self):
        reference = {
            "DOC001-P001": {
                "text": "가나다라",
                "spans": [[0, 4]],
            }
        }
        predicted = {
            "DOC001-P001": {
                "text": "가나다라",
                "spans": [[0, 2], [2, 4]],
            }
        }

        result = evaluate_clause_extraction(reference, predicted)

        self.assertEqual(result["tp"], 0)
        self.assertEqual(result["fp"], 2)
        self.assertEqual(result["fn"], 1)

    def test_missing_page_counts_as_missed_clauses(self):
        result = evaluate_clause_extraction(
            self.reference, {}
        )

        self.assertEqual(result["fn"], 3)
        self.assertEqual(result["recall"], 0.0)
        self.assertEqual(result["exact_page_accuracy"], 0.0)

    def test_different_page_text_is_rejected(self):
        predicted = copy.deepcopy(self.reference)
        predicted["DOC001-P001"]["text"] = "가나다라마사"

        with self.assertRaisesRegex(
            ValueError, "page_text_mismatch"
        ):
            evaluate_clause_extraction(self.reference, predicted)

    def test_duplicate_span_is_rejected(self):
        predicted = copy.deepcopy(self.reference)
        predicted["DOC001-P001"]["spans"].append([0, 2])

        with self.assertRaisesRegex(
            ValueError, "duplicate_clause_span"
        ):
            evaluate_clause_extraction(self.reference, predicted)

if __name__ == "__main__":
    unittest.main()