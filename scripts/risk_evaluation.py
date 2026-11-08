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

def extract_error_cases(gold_cases, predictions):
    """오분류 사례를 네 종류로 나누어 원문과 함께 반환한다."""
    gold_by_id, prediction_by_id = validate_inputs(
        gold_cases, predictions
    )

    positive_labels = {"risk", "potential_risk"}
    categories = (
        "false_positives",
        "false_negatives",
        "unknown_related",
        "risk_label_confusions",
    )
    cases = {category: [] for category in categories}
    correct_count = 0

    # 입력 배열 순서와 관계없이 같은 순서로 출력한다.
    for case_id in sorted(gold_by_id):
        gold = gold_by_id[case_id]
        prediction = prediction_by_id[case_id]
        actual = gold["gold_label"]
        predicted = prediction["pred_label"]

        if actual == predicted:
            correct_count += 1
            continue

        if actual == "ok" and predicted in positive_labels:
            category = "false_positives"
        elif actual in positive_labels and predicted == "ok":
            category = "false_negatives"
        elif "unknown" in (actual, predicted):
            category = "unknown_related"
        else:
            category = "risk_label_confusions"

        cases[category].append({
            "case_id": case_id,
            "risk_type": gold["risk_type"],
            "text": gold["text"],
            "gold_label": actual,
            "pred_label": predicted,
            "label_reason": gold["label_reason"],
        })

    counts = {
        category: len(items)
        for category, items in cases.items()
    }

    return {
        "total_cases": len(gold_by_id),
        "correct_count": correct_count,
        "error_count": sum(counts.values()),
        "counts": counts,
        "cases": cases,
    }

def evaluate_risk_report(gold_cases, predictions):
    """전체 및 위험 유형별 상태 분류 성능을 계산한다."""
    gold_by_id, prediction_by_id = validate_inputs(
        gold_cases, predictions
    )

    result = evaluate_status(gold_cases, predictions)
    result["by_risk_type"] = {}

    for risk_type in RISK_TYPES:
        selected_ids = [
            case_id
            for case_id, case in gold_by_id.items()
            if case["risk_type"] == risk_type
        ]

        if not selected_ids:
            result["by_risk_type"][risk_type] = {
                "status": "not_evaluated",
                "total_cases": 0,
                "metrics": None,
            }
            continue

        selected_gold = [
            gold_by_id[case_id] for case_id in selected_ids
        ]
        selected_predictions = [
            prediction_by_id[case_id]
            for case_id in selected_ids
        ]

        result["by_risk_type"][risk_type] = {
            "status": "evaluated",
            "total_cases": len(selected_ids),
            "metrics": evaluate_status(
                selected_gold, selected_predictions
            ),
        }

    result["error_analysis"] = extract_error_cases(
        gold_cases, predictions
    )

    return result

def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="A-2 개발용 위험 상태 성능 평가"
    )
    parser.add_argument("--gold", required=True)
    parser.add_argument("--predictions", required=True)
    args = parser.parse_args()

    try:
        gold, predictions = load_evaluation_inputs(
            args.gold, args.predictions
        )
        result = evaluate_risk_report(gold, predictions)
    except (OSError, ValueError) as error:
        parser.exit(2, f"평가 실행 실패: {error}\n")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
