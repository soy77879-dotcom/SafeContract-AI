"""A-2 위험 탐지 성능 평가 도구."""

import copy


LABELS = ("risk", "potential_risk", "ok", "unknown")

RISK_TYPES = (
    "deposit_return",
    "repair_cost",
    "contract_termination",
)


def validate_inputs(gold_cases, predictions):
    """정답·예측 형식과 연결을 검사하고 복사본을 반환한다."""
    if not isinstance(gold_cases, list) or not gold_cases:
        raise ValueError("gold_cases must be a nonempty list")

    if not isinstance(predictions, list):
        raise ValueError("predictions must be a list")

    gold_by_id = {}
    prediction_by_id = {}

    required_gold = {
        "case_id",
        "text",
        "risk_type",
        "gold_label",
        "label_reason",
        "source",
        "legal_basis",
        "review_status",
    }

    for case in gold_cases:
        if not isinstance(case, dict) or not required_gold <= case.keys():
            raise ValueError("invalid_gold_fields")

        for field in (
            "case_id", "text", "risk_type",
            "gold_label", "label_reason", "review_status",
        ):
            if not isinstance(case[field], str) or not case[field].strip():
                raise ValueError("invalid_gold_value")

        if not isinstance(case["source"], dict):
            raise ValueError("invalid_source")

        if not isinstance(case["legal_basis"], list):
            raise ValueError("invalid_legal_basis")

        if case["gold_label"] not in LABELS:
            raise ValueError("invalid_gold_label")

        if case["risk_type"] not in RISK_TYPES:
            raise ValueError("invalid_gold_risk_type")

        case_id = case["case_id"]
        if case_id in gold_by_id:
            raise ValueError("duplicate_gold_case_id")

        gold_by_id[case_id] = copy.deepcopy(case)

    for prediction in predictions:
        required = {"case_id", "risk_type", "pred_label"}
        if not isinstance(prediction, dict) or not required <= prediction.keys():
            raise ValueError("invalid_prediction_fields")

        for field in required:
            if not isinstance(prediction[field], str):
                raise ValueError("invalid_prediction_value")

        case_id = prediction["case_id"]
        if case_id in prediction_by_id:
            raise ValueError("duplicate_prediction_case_id")

        if case_id not in gold_by_id:
            raise ValueError("unknown_prediction_case_id")

        if prediction["pred_label"] not in LABELS:
            raise ValueError("invalid_prediction_label")

        if prediction["risk_type"] != gold_by_id[case_id]["risk_type"]:
            raise ValueError("risk_type_mismatch")

        prediction_by_id[case_id] = copy.deepcopy(prediction)

    if set(gold_by_id) != set(prediction_by_id):
        raise ValueError("missing_predictions")

    return gold_by_id, prediction_by_id

def evaluate_status(gold_cases, predictions):
    """개발 검사용 4개 위험 상태의 성능을 계산한다."""
    gold_by_id, prediction_by_id = validate_inputs(
        gold_cases, predictions
    )

    # 행은 정답, 열은 예측이다.
    confusion = {
        actual: {predicted: 0 for predicted in LABELS}
        for actual in LABELS
    }

    for case_id, gold in gold_by_id.items():
        actual = gold["gold_label"]
        predicted = prediction_by_id[case_id]["pred_label"]
        confusion[actual][predicted] += 1

    per_label = {}

    for label in LABELS:
        true_positive = confusion[label][label]

        false_positive = sum(
            confusion[actual][label]
            for actual in LABELS
            if actual != label
        )

        false_negative = sum(
            confusion[label][predicted]
            for predicted in LABELS
            if predicted != label
        )

        support = sum(confusion[label].values())

        precision_denominator = true_positive + false_positive
        recall_denominator = true_positive + false_negative
        f1_denominator = (
            2 * true_positive + false_positive + false_negative
        )

        per_label[label] = {
            "support": support,
            "tp": true_positive,
            "fp": false_positive,
            "fn": false_negative,
            "precision": (
                true_positive / precision_denominator
                if precision_denominator else 0.0
            ),
            "recall": (
                true_positive / recall_denominator
                if recall_denominator else 0.0
            ),
            "f1": (
                2 * true_positive / f1_denominator
                if f1_denominator else 0.0
            ),
        }

    macro_f1 = sum(
        metrics["f1"] for metrics in per_label.values()
    ) / len(LABELS)

    return {
        "evaluation_scope": "development_preview",
        "total_cases": len(gold_by_id),
        "label_order": list(LABELS),
        "zero_division": 0,
        "macro_f1_policy": "all_four_labels",
        "per_label": per_label,
        "macro_f1": macro_f1,
        "confusion_matrix": confusion,
    }

def load_evaluation_inputs(gold_path, prediction_path):
    """JSON 파일을 읽고 기존 입력 검증을 수행한다."""
    import json
    from pathlib import Path

    gold_cases = json.loads(
        Path(gold_path).read_text(encoding="utf-8-sig")
    )
    predictions = json.loads(
        Path(prediction_path).read_text(encoding="utf-8-sig")
    )

    validate_inputs(gold_cases, predictions)

    return gold_cases, predictions