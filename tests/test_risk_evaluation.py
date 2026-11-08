import copy
import unittest
from pathlib import Path

from scripts.risk_evaluation import (
    evaluate_status,
    load_evaluation_inputs,
    validate_inputs,
)

class RiskEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.gold = [{
            "case_id": "MOCK-001",
            "text": "보증금 반환은 별도 약정에 따른다.",
            "risk_type": "deposit_return",
            "gold_label": "unknown",
            "label_reason": "평가기 개발용 가상 라벨입니다.",
            "source": {
                "kind": "synthetic",
                "document": None,
                "pdf_page": None,
                "provision": None,
            },
            "legal_basis": [],
            "review_status": "needs_review",
        }]

        self.predictions = [{
            "case_id": "MOCK-001",
            "risk_type": "deposit_return",
            "pred_label": "unknown",
        }]

    def test_valid_inputs(self):
        gold, predictions = validate_inputs(
            self.gold, self.predictions
        )
        self.assertEqual(set(gold), {"MOCK-001"})
        self.assertEqual(set(predictions), {"MOCK-001"})

    def test_duplicate_gold_id_is_rejected(self):
        duplicated = self.gold + copy.deepcopy(self.gold)
        with self.assertRaisesRegex(ValueError, "duplicate_gold_case_id"):
            validate_inputs(duplicated, self.predictions)

    def test_missing_prediction_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing_predictions"):
            validate_inputs(self.gold, [])

    def test_invalid_prediction_label_is_rejected(self):
        self.predictions[0]["pred_label"] = "no_risk_detected"
        with self.assertRaisesRegex(ValueError, "invalid_prediction_label"):
            validate_inputs(self.gold, self.predictions)

    def test_wrong_risk_type_is_rejected(self):
        self.predictions[0]["risk_type"] = "repair_cost"
        with self.assertRaisesRegex(ValueError, "risk_type_mismatch"):
            validate_inputs(self.gold, self.predictions)


    def _four_label_cases(self, predicted_labels):
        labels = ["risk", "potential_risk", "ok", "unknown"]
        gold_cases = []
        predictions = []

        for index, label in enumerate(labels, start=1):
            case = copy.deepcopy(self.gold[0])
            case["case_id"] = f"MOCK-{index:03d}"
            case["text"] = f"평가기 계산 검증용 합성 사례 {index}"
            case["gold_label"] = label
            gold_cases.append(case)

            predictions.append({
                "case_id": case["case_id"],
                "risk_type": case["risk_type"],
                "pred_label": predicted_labels[index - 1],
            })

        return gold_cases, predictions

    def test_perfect_predictions(self):
        gold, predictions = self._four_label_cases(
            ["risk", "potential_risk", "ok", "unknown"]
        )

        result = evaluate_status(gold, predictions)

        self.assertEqual(result["total_cases"], 4)
        self.assertEqual(result["macro_f1"], 1.0)

        for metrics in result["per_label"].values():
            self.assertEqual(metrics["precision"], 1.0)
            self.assertEqual(metrics["recall"], 1.0)
            self.assertEqual(metrics["f1"], 1.0)

    def test_all_predictions_wrong(self):
        gold, predictions = self._four_label_cases(
            ["potential_risk", "ok", "unknown", "risk"]
        )

        result = evaluate_status(gold, predictions)

        self.assertEqual(result["macro_f1"], 0.0)
        for metrics in result["per_label"].values():
            self.assertEqual(metrics["f1"], 0.0)

    def test_mixed_predictions_have_expected_scores(self):
        gold, predictions = self._four_label_cases(
            ["risk", "risk", "ok", "ok"]
        )

        result = evaluate_status(gold, predictions)
        risk = result["per_label"]["risk"]

        self.assertEqual(risk["tp"], 1)
        self.assertEqual(risk["fp"], 1)
        self.assertEqual(risk["fn"], 0)
        self.assertAlmostEqual(risk["precision"], 0.5)
        self.assertAlmostEqual(risk["recall"], 1.0)
        self.assertAlmostEqual(risk["f1"], 2 / 3)
        self.assertAlmostEqual(result["macro_f1"], 1 / 3)

        # 정답 potential_risk를 risk로 예측한 사례 1개
        self.assertEqual(
            result["confusion_matrix"]["potential_risk"]["risk"],
            1,
        )

    def test_absent_labels_do_not_cause_division_error(self):
        result = evaluate_status(
            self.gold, self.predictions
        )

        self.assertEqual(
            result["per_label"]["risk"]["support"], 0
        )
        self.assertEqual(
            result["per_label"]["risk"]["f1"], 0.0
        )
        # unknown만 정답이므로 네 상태 평균은 1 / 4
        self.assertAlmostEqual(result["macro_f1"], 0.25)

    def test_mock_files_produce_expected_metrics(self):
        root = Path(__file__).resolve().parents[1]
        folder = root / "data" / "metadata" / "mock"

        gold, predictions = load_evaluation_inputs(
            folder / "gold_mock.json",
            folder / "predictions_mock.json",
        )
        result = evaluate_status(gold, predictions)

        self.assertEqual(result["total_cases"], 4)
        self.assertAlmostEqual(result["macro_f1"], 0.5)

        expected_f1 = {
            "risk": 0.0,
            "potential_risk": 1.0,
            "ok": 0.0,
            "unknown": 1.0,
        }

        for label, expected in expected_f1.items():
            with self.subTest(label=label):
                metrics = result["per_label"][label]
                self.assertEqual(metrics["support"], 1)
                self.assertAlmostEqual(metrics["f1"], expected)
                self.assertAlmostEqual(
                    metrics["precision"], expected
                )
                self.assertAlmostEqual(
                    metrics["recall"], expected
                )

if __name__ == "__main__":
    unittest.main()