import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.evaluation_output import (
    render_error_report,
    save_evaluation_outputs,
)
from scripts.risk_evaluation import (
    evaluate_risk_report,
    load_evaluation_inputs,
)


class EvaluationOutputTests(unittest.TestCase):
    def setUp(self):
        folder = (
            Path(__file__).resolve().parents[1]
            / "data" / "metadata" / "mock"
        )

        self.gold, self.predictions = load_evaluation_inputs(
            folder / "gold_mock.json",
            folder / "predictions_mock.json",
        )

    def test_report_contains_metrics_and_error_cases(self):
        result = evaluate_risk_report(
            self.gold, self.predictions
        )

        report = render_error_report(result)

        self.assertIn("전체 사례 수: 4", report)
        self.assertIn("맞힌 사례 수: 2", report)
        self.assertIn("오류 사례 수: 2", report)
        self.assertIn("Macro F1: 0.500000", report)
        self.assertIn("오탐: 1건", report)
        self.assertIn("미탐: 1건", report)
        self.assertIn("A2-M003", report)
        self.assertIn("A2-M001", report)
        self.assertIn("행=정답, 열=예측", report)

    def test_perfect_predictions_report_no_errors(self):
        predictions = [
            {
                "case_id": case["case_id"],
                "risk_type": case["risk_type"],
                "pred_label": case["gold_label"],
            }
            for case in self.gold
        ]

        result = evaluate_risk_report(self.gold, predictions)
        report = render_error_report(result)

        self.assertIn("오류 사례 수: 0", report)
        self.assertIn("오탐: 0건", report)
        self.assertIn("미탐: 0건", report)
        self.assertIn("Macro F1: 1.000000", report)

    def test_report_is_repeatable_and_keeps_result(self):
        result = evaluate_risk_report(
            self.gold, self.predictions
        )
        original = copy.deepcopy(result)

        first = render_error_report(result)
        second = render_error_report(result)

        self.assertEqual(first, second)
        self.assertEqual(result, original)


    def test_saves_json_and_report(self):
        result = evaluate_risk_report(
            self.gold, self.predictions
        )
        original = copy.deepcopy(result)

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "run"
            paths = save_evaluation_outputs(result, output)

            saved_result = json.loads(
                Path(paths["result_json"]).read_text(
                    encoding="utf-8"
                )
            )
            saved_report = Path(paths["error_report"]).read_text(
                encoding="utf-8"
            )

            self.assertEqual(saved_result, result)
            self.assertIn("Macro F1: 0.500000", saved_report)
            self.assertIn("A2-M003", saved_report)
            self.assertIn("A2-M001", saved_report)

        self.assertEqual(result, original)

    def test_existing_output_directory_is_preserved(self):
        result = evaluate_risk_report(
            self.gold, self.predictions
        )

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "existing"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("기존 파일", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                save_evaluation_outputs(result, output)

            self.assertEqual(
                marker.read_text(encoding="utf-8"),
                "기존 파일",
            )
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"keep.txt"},
            )

    def test_invalid_number_does_not_create_output(self):
        result = evaluate_risk_report(
            self.gold, self.predictions
        )
        result["macro_f1"] = float("nan")

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "invalid"

            with self.assertRaises(ValueError):
                save_evaluation_outputs(result, output)

            self.assertFalse(output.exists())

if __name__ == "__main__":
    unittest.main()