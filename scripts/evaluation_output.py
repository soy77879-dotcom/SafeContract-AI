"""A-2 평가 결과 출력과 보고서 생성."""


def render_error_report(result):
    """검증된 평가 결과를 한국어 텍스트 보고서로 변환한다."""
    errors = result["error_analysis"]

    lines = [
        "SafeContract AI — A-2 위험 탐지 평가 보고서",
        "",
        f"평가 범위: {result['evaluation_scope']}",
        "development_preview는 개발 검증용 결과입니다.",
        "확정된 독립 테스트셋의 최종 성능과 구분해야 합니다.",
        "",
        f"전체 사례 수: {result['total_cases']}",
        f"맞힌 사례 수: {errors['correct_count']}",
        f"오류 사례 수: {errors['error_count']}",
        f"Macro F1: {result['macro_f1']:.6f}",
        "Macro F1은 네 상태의 F1을 동일한 비중으로 평균합니다.",
        "",
        "[상태별 성능]",
    ]

    for label in result["label_order"]:
        metrics = result["per_label"][label]
        lines.append(
            f"{label}: "
            f"정답 건수={metrics['support']}, "
            f"Precision={metrics['precision']:.6f}, "
            f"Recall={metrics['recall']:.6f}, "
            f"F1={metrics['f1']:.6f}"
        )

    lines.extend(["", "[전체 혼동행렬]", "행=정답, 열=예측"])
    labels = result["label_order"]
    lines.append("정답\\예측\t" + "\t".join(labels))

    for actual in labels:
        values = [
            str(result["confusion_matrix"][actual][predicted])
            for predicted in labels
        ]
        lines.append(actual + "\t" + "\t".join(values))

    lines.extend(["", "[위험 유형별 성능]"])

    for risk_type, group in result["by_risk_type"].items():
        if group["status"] == "not_evaluated":
            lines.append(f"{risk_type}: 평가 사례 없음")
        else:
            lines.append(
                f"{risk_type}: "
                f"사례 수={group['total_cases']}, "
                f"Macro F1={group['metrics']['macro_f1']:.6f}"
            )

    categories = (
        ("false_positives", "오탐"),
        ("false_negatives", "미탐"),
        ("unknown_related", "판단 불가 관련 오류"),
        ("risk_label_confusions", "위험 라벨 간 혼동"),
    )

    for key, title in categories:
        lines.extend([
            "",
            f"[{title}]",
            f"{title}: {errors['counts'][key]}건",
        ])

        if not errors["cases"][key]:
            lines.append("해당 없음.")
            continue

        for case in errors["cases"][key]:
            lines.extend([
                f"사례 ID: {case['case_id']}",
                f"위험 유형: {case['risk_type']}",
                f"정답: {case['gold_label']}",
                f"예측: {case['pred_label']}",
                f"정답 판단 이유: {case['label_reason']}",
                "원문:",
            ])
            lines.extend(
                "    " + line for line in case["text"].splitlines()
            )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"

def save_evaluation_outputs(result, output_dir):
    """평가 결과 JSON과 보고서를 새 폴더에 저장한다."""
    import json
    import tempfile
    from pathlib import Path

    output = Path(output_dir).resolve()

    if output.exists():
        raise FileExistsError(
            f"결과 경로가 이미 있습니다. 새 폴더를 지정하세요: {output}"
        )

    json_text = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"
    report_text = render_error_report(result)

    output.parent.mkdir(parents=True, exist_ok=True)

    # 두 파일을 준비한 뒤 결과 폴더로 이동한다.
    with tempfile.TemporaryDirectory(
        prefix=".a2-evaluation-",
        dir=output.parent,
    ) as folder:
        staged = Path(folder) / "result"
        staged.mkdir()

        (staged / "evaluation_result.json").write_text(
            json_text, encoding="utf-8"
        )
        (staged / "error_analysis.txt").write_text(
            report_text, encoding="utf-8"
        )

        staged.rename(output)

    return {
        "result_json": str(output / "evaluation_result.json"),
        "error_report": str(output / "error_analysis.txt"),
    }