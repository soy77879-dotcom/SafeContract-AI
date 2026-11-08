"""A-2 독립 OCR 텍스트 평가. OCR 모델 설치 없이 실행한다."""

from scripts.ocr_evaluation import evaluate_corpus


def evaluate_ocr_texts(references, hypotheses):
    """같은 평가 사례 ID로 연결된 정답·OCR 텍스트를 평가한다.

    이 함수는 문자 인식 성능을 평가한다.
    조항 경계가 정확히 추출됐는지는 별도 평가해야 한다.
    """
    if not isinstance(references, dict) or not references:
        raise ValueError("references must be a nonempty dictionary")

    if not isinstance(hypotheses, dict):
        raise ValueError("hypotheses must be a dictionary")

    for mapping in (references, hypotheses):
        for case_id, text in mapping.items():
            if not isinstance(case_id, str) or not case_id.strip():
                raise ValueError("invalid_ocr_case_id")
            if not isinstance(text, str):
                raise ValueError("ocr_text_must_be_string")

    if set(hypotheses) - set(references):
        raise ValueError("unknown_ocr_case_id")

    missing = sorted(set(references) - set(hypotheses))

    # 누락 결과를 제외하지 않고 전체 글자가 빠진 것으로 평가한다.
    aligned = {
        case_id: hypotheses.get(case_id, "")
        for case_id in references
    }

    result = evaluate_corpus(references, aligned)
    result["evaluation_scope"] = "development_preview"
    result["missing_prediction_ids"] = missing

    return result

def _validate_page_spans(page):
    """동일 페이지 텍스트상의 겹치지 않는 조항 위치를 검사한다."""
    if not isinstance(page, dict):
        raise ValueError("invalid_page")

    text = page.get("text")
    spans = page.get("spans")

    if not isinstance(text, str) or not isinstance(spans, list):
        raise ValueError("invalid_page_fields")

    checked = []

    for span in spans:
        if not isinstance(span, list) or len(span) != 2:
            raise ValueError("invalid_clause_span")

        start, end = span

        if type(start) is not int or type(end) is not int:
            raise ValueError("invalid_clause_span")

        if not 0 <= start < end <= len(text):
            raise ValueError("invalid_clause_span")

        checked.append((start, end))

    if len(checked) != len(set(checked)):
        raise ValueError("duplicate_clause_span")

    ordered = sorted(checked)
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise ValueError("overlapping_clause_spans")

    return text, set(checked)


def evaluate_clause_extraction(reference_pages, predicted_pages):
    """같은 페이지 본문에서 조항 시작·끝 위치의 완전 일치를 평가한다."""
    if not isinstance(reference_pages, dict) or not reference_pages:
        raise ValueError("reference_pages must be a nonempty dictionary")

    if not isinstance(predicted_pages, dict):
        raise ValueError("predicted_pages must be a dictionary")

    for page_id in reference_pages:
        if not isinstance(page_id, str) or not page_id.strip():
            raise ValueError("invalid_page_id")

    if set(predicted_pages) - set(reference_pages):
        raise ValueError("unknown_page_id")

    total_tp = total_fp = total_fn = 0
    exact_pages = 0
    per_page = {}
    missing = []

    for page_id, reference in reference_pages.items():
        text, expected = _validate_page_spans(reference)

        if page_id in predicted_pages:
            predicted_text, actual = _validate_page_spans(
                predicted_pages[page_id]
            )
            if predicted_text != text:
                raise ValueError("page_text_mismatch")
        else:
            actual = set()
            missing.append(page_id)

        tp = len(expected & actual)
        fp = len(actual - expected)
        fn = len(expected - actual)

        total_tp += tp
        total_fp += fp
        total_fn += fn
        exact_pages += int(expected == actual)

        per_page[page_id] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "false_positive_spans": [
                list(span) for span in sorted(actual - expected)
            ],
            "false_negative_spans": [
                list(span) for span in sorted(expected - actual)
            ],
        }

    precision_denominator = total_tp + total_fp
    recall_denominator = total_tp + total_fn
    f1_denominator = 2 * total_tp + total_fp + total_fn

    return {
        "evaluation_scope": "development_preview",
        "policy_version": "clause-exact-span-v1",
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "precision": (
            total_tp / precision_denominator
            if precision_denominator else 0.0
        ),
        "recall": (
            total_tp / recall_denominator
            if recall_denominator else 0.0
        ),
        "f1": (
            2 * total_tp / f1_denominator
            if f1_denominator else 0.0
        ),
        "exact_page_accuracy": exact_pages / len(reference_pages),
        "missing_prediction_ids": sorted(missing),
        "per_page": per_page,
    }

"""같은 페이지 본문에서 조항 시작·끝 위치의 완전 일치를 평가한다."""
