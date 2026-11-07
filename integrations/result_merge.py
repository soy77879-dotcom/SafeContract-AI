"""규칙·LLM 결과 병합 지원 모듈.

내부 데이터 검증 함수는 사용자 승인 절차를 대신하지 않는다.
최종 결과 표시는 기존 ResponseValidationGate를 거쳐야 한다.
"""

import json
import copy

from integrations.response_validation import (
    Rejected,
    parse_response,
    strict_request,
    validate_content,
)
from scripts.risk_rules import to_api

def validate_candidate_response(request, response):
    """병합 후보 결과를 기존 요청·응답 규격과 원문에 대조한다.

    검증 실패 시 예외를 발생시키며 입력 객체는 수정하지 않는다.
    이 함수의 성공은 사용자 승인 또는 결과 표시 허가를 뜻하지 않는다.
    """
    checked_request = strict_request(request)

    raw_response = json.dumps(
        response,
        ensure_ascii=False,
        allow_nan=False,
    )

    checked_response = parse_response(raw_response)

    return validate_content(checked_response, checked_request)

def deduplicate_results(results):
    """한 출처 안의 동일 결과를 제거하고, 내용이 다른 중복은 거부한다.

    입력은 사전에 구조 검증을 통과한 결과 목록이어야 한다.
    사용자 승인이나 최종 응답 검증을 대신하지 않는다.
    """
    unique = {}

    for row in results:
        key = (row["clause_id"], row["risk_type"])

        if key in unique:
            if unique[key] != row:
                raise Rejected("same_source_conflict")
            continue

        unique[key] = copy.deepcopy(row)

    return list(unique.values())

def validate_evidence_span(text, evidence, span):
    """원문의 지정된 위치와 근거 문장이 정확히 일치하는지 검사한다."""
    if not isinstance(text, str) or not isinstance(evidence, str):
        raise Rejected("invalid_evidence_type")

    if not evidence.strip():
        raise Rejected("empty_rule_evidence")

    if not isinstance(span, (list, tuple)) or len(span) != 2:
        raise Rejected("invalid_evidence_span")

    start, end = span

    # bool도 Python에서는 int로 취급되므로 정확한 타입을 확인한다.
    if type(start) is not int or type(end) is not int:
        raise Rejected("invalid_evidence_span")

    if not 0 <= start < end <= len(text):
        raise Rejected("invalid_evidence_span")

    if text[start:end] != evidence:
        raise Rejected("evidence_span_mismatch")

def merge_same_risk(rule_row, llm_row):
    """검증된 동일 조항·위험 유형의 결과 두 개를 병합한다.

    risk_type='none'과 조항 전체의 충돌은 상위 병합 단계에서 처리한다.
    이 함수는 사용자 승인 또는 입력 검증을 대신하지 않는다.
    """
    rule_key = (rule_row["clause_id"], rule_row["risk_type"])
    llm_key = (llm_row["clause_id"], llm_row["risk_type"])

    if rule_key != llm_key:
        raise Rejected("different_merge_keys")

    if rule_row["risk_type"] == "none":
        raise Rejected("no_risk_requires_clause_merge")

    merged = copy.deepcopy(rule_row)

    if rule_row == llm_row:
        return merged, []

    # 설명의 의미를 임의로 판단하지 않고 보수적으로 확인을 요청한다.
    merged["risk_status"] = "needs_review"

    warning = (
        f"{rule_row['clause_id']}: 규칙과 LLM 결과에 차이가 있어 "
        "규칙의 원문 근거를 유지하고 추가 확인이 필요합니다."
    )

    return merged, [warning]

def merge_clause_results(rule_rows, llm_rows):
    """검증된 한 조항의 규칙·LLM 결과를 병합한다."""
    rule_rows = deduplicate_results(rule_rows)
    llm_rows = deduplicate_results(llm_rows)
    all_rows = rule_rows + llm_rows

    if not all_rows:
        raise Rejected("empty_clause_results")

    clause_ids = {row["clause_id"] for row in all_rows}
    if len(clause_ids) != 1:
        raise Rejected("mixed_clause_results")

    # 한 출처 내부의 모순은 병합 전에 거부한다.
    for rows in (rule_rows, llm_rows):
        types = {row["risk_type"] for row in rows}
        if "none" in types and len(types) > 1:
            raise Rejected("same_source_contradiction")

    rule_by_type = {
        row["risk_type"]: row for row in rule_rows
    }
    llm_by_type = {
        row["risk_type"]: row for row in llm_rows
    }

    risk_types = (
        set(rule_by_type) | set(llm_by_type)
    ) - {"none"}

    # 제공된 결과가 모두 위험 미탐지인 경우.
    if not risk_types:
        source = rule_rows if rule_rows else llm_rows
        return [copy.deepcopy(source[0])], []

    merged_rows = []
    warnings = []

    for risk_type in sorted(risk_types):
        rule_row = rule_by_type.get(risk_type)
        llm_row = llm_by_type.get(risk_type)

        if rule_row is not None and llm_row is not None:
            row, row_warnings = merge_same_risk(
                rule_row, llm_row
            )
            warnings.extend(row_warnings)
        else:
            source = rule_row if rule_row is not None else llm_row
            row = copy.deepcopy(source)

        merged_rows.append(row)

    # 위험 미탐지와 구체적인 위험 결과를 함께 표시하지 않는다.
    if "none" in rule_by_type or "none" in llm_by_type:
        for row in merged_rows:
            row["risk_status"] = "needs_review"

        clause_id = all_rows[0]["clause_id"]
        warnings.append(
            f"{clause_id}: 위험 미탐지와 위험·확인 필요 결과가 "
            "상충하여 원문 근거를 유지하고 추가 확인이 필요합니다."
        )

    return merged_rows, warnings

def _prepare_source_response(request, response):
    """출처별 응답 형식을 검사하고 동일 중복을 제거한다."""
    parsed = parse_response(
        json.dumps(response, ensure_ascii=False, allow_nan=False)
    )
    parsed["results"] = deduplicate_results(parsed["results"])

    return validate_content(parsed, request)


def merge_analysis_responses(
    request,
    rule_response=None,
    llm_response=None,
):
    """규칙·LLM의 API 형식 응답을 문서 단위로 병합한다.

    반환값은 내부 병합 후보이며 사용자 승인 결과가 아니다.
    규칙의 evidence_span 검사는 이 함수를 호출하기 전에 수행해야 한다.
    """
    checked_request = strict_request(request)
    warnings = []
    sources = []

    # 규칙 결과가 잘못됐다면 조용히 성공 처리하지 않는다.
    if rule_response is not None:
        rules = _prepare_source_response(
            checked_request, rule_response
        )
        sources.append(rules)
        warnings.extend(rules["warnings"])
    else:
        rules = None
        warnings.append(
            "규칙 분석 결과가 없어 LLM 결과만 검토했습니다."
        )

    # LLM 응답 오류는 유효한 규칙 결과까지 없애지 않는다.
    if llm_response is not None:
        try:
            llm = _prepare_source_response(
                checked_request, llm_response
            )
        except (Rejected, ValueError, TypeError):
            llm = None
            warnings.append(
                "LLM 응답 검증에 실패하여 규칙 결과만 반영했습니다."
            )
    else:
        llm = None
        warnings.append(
            "LLM 결과가 제공되지 않아 규칙 결과만 반영했습니다."
        )

    if llm is not None:
        sources.append(llm)
        warnings.extend(llm["warnings"])

    if not sources:
        raise Rejected("no_valid_analysis_results")

    results = []

    for clause in checked_request["clauses"]:
        clause_id = clause["clause_id"]

        rule_rows = [
            row for row in rules["results"]
            if row["clause_id"] == clause_id
        ] if rules is not None else []

        llm_rows = [
            row for row in llm["results"]
            if row["clause_id"] == clause_id
        ] if llm is not None else []

        if not rule_rows and not llm_rows:
            warnings.append(
                f"{clause_id}: 분석 결과가 없어 추가 검토가 필요합니다."
            )
            continue

        rows, clause_warnings = merge_clause_results(
            rule_rows, llm_rows
        )
        results.extend(rows)
        warnings.extend(clause_warnings)

    if not results:
        raise Rejected("no_valid_analysis_results")

    # 경고 중복을 제거하면서 순서를 유지한다.
    warnings = list(dict.fromkeys(warnings))

    partial = (
        bool(warnings)
        or any(source["status"] == "partial" for source in sources)
        or any(
            row["risk_status"] == "needs_review"
            for row in results
        )
    )

    if partial and not warnings:
        warnings.append(
            "일부 판단이 보류되어 추가 검토가 필요합니다."
        )

    candidate = {
        "document_id": checked_request["document_id"],
        "status": "partial" if partial else "completed",
        "results": results,
        "warnings": warnings,
    }

    return validate_candidate_response(
        checked_request, candidate
    )

def finalize_analysis(
    gate,
    *,
    owner,
    ticket,
    request,
    rule_response,
    image_sha256,
    text_sha256,
    revision,
    llm_response=None,
):
    """병합 후보를 기존 승인 게이트로 최종 검증한다."""
    try:
        candidate = merge_analysis_responses(
            request,
            rule_response=rule_response,
            llm_response=llm_response,
        )
        raw = json.dumps(
            candidate,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (Rejected, ValueError, TypeError):
        # 병합 실패도 기존 게이트에서 실패 처리하고 티켓을 소모한다.
        # 잘못된 원문이나 내부 예외 내용은 응답에 넣지 않는다.
        raw = "{}"

    return gate.validate_response(
        owner=owner,
        ticket=ticket,
        raw=raw,
        image_sha256=image_sha256,
        text_sha256=text_sha256,
        revision=revision,
    )

def prepare_rule_response(request, rule_result):
    """규칙 원본의 검토 상태·최종 원문·근거 위치를 검사한다.

    서버 내부에서 생성한 규칙 결과를 입력받는 함수다.
    사용자 승인 게이트를 대신하지 않는다.
    """
    checked_request = strict_request(request)
    expected = {
        clause["clause_id"]: clause["text"]
        for clause in checked_request["clauses"]
    }

    if not isinstance(rule_result, dict):
        raise Rejected("invalid_rule_result")

    if rule_result.get("document_id") != checked_request["document_id"]:
        raise Rejected("document_mismatch")

    clauses = rule_result.get("clauses")
    if not isinstance(clauses, list):
        raise Rejected("invalid_rule_clauses")

    accepted = []
    seen = set()
    warnings = []

    for clause in clauses:
        if not isinstance(clause, dict):
            raise Rejected("invalid_rule_clause")

        clause_id = clause.get("clause_id")

        if not isinstance(clause_id, str) or clause_id not in expected:
            raise Rejected("unknown_clause")

        if clause_id in seen:
            raise Rejected("duplicate_rule_clause")

        seen.add(clause_id)

        try:
            if clause.get("needs_review") is not False:
                raise Rejected("ocr_review_required")

            text = clause.get("analysis_text")
            if text != expected[clause_id]:
                raise Rejected("analysis_text_mismatch")

            findings = clause.get("findings")
            if not isinstance(findings, list) or not findings:
                raise Rejected("missing_rule_findings")

            for finding in findings:
                if not isinstance(finding, dict):
                    raise Rejected("invalid_rule_finding")

                validate_evidence_span(
                    text,
                    finding.get("evidence"),
                    finding.get("evidence_span"),
                )

        except Rejected:
            warnings.append(
                f"{clause_id}: 규칙의 검토 상태 또는 원문 근거를 "
                "확인하지 못해 해당 조항의 규칙 결과를 제외했습니다."
            )
            continue

        accepted.append(copy.deepcopy(clause))

    for clause_id in expected:
        if clause_id not in seen:
            warnings.append(
                f"{clause_id}: 규칙 분석 결과가 누락되었습니다."
            )

    if not accepted:
        raise Rejected("no_supported_rule_results")

    filtered = copy.deepcopy(rule_result)
    filtered["clauses"] = accepted

    # 기존 변환 로직을 그대로 재사용한다.
    response = to_api(filtered)

    if warnings:
        response["status"] = "partial"
        response["warnings"].extend(warnings)

    return validate_candidate_response(
        checked_request, response
    )

def finalize_rule_analysis(
    gate,
    *,
    owner,
    ticket,
    request,
    rule_result,
    image_sha256,
    text_sha256,
    revision,
    llm_response=None,
):
    """규칙 원본의 근거 검사부터 최종 승인까지 순서대로 처리한다.

    서버 내부 규칙 결과를 받는다.
    실제 LLM 호출이나 사용자 승인 생성은 수행하지 않는다.
    """
    try:
        rule_response = prepare_rule_response(
            request, rule_result
        )
    except (Rejected, ValueError, TypeError, KeyError):
        # 근거 검사에 실패하면 결과를 반환하지 않는다.
        # 기존 게이트를 통해 실패 처리하고 티켓도 소모한다.
        return gate.validate_response(
            owner=owner,
            ticket=ticket,
            raw="{}",
            image_sha256=image_sha256,
            text_sha256=text_sha256,
            revision=revision,
        )

    return finalize_analysis(
        gate,
        owner=owner,
        ticket=ticket,
        request=request,
        rule_response=rule_response,
        image_sha256=image_sha256,
        text_sha256=text_sha256,
        revision=revision,
        llm_response=llm_response,
    )