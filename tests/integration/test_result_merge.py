"""합성 데이터로 병합 후보 검증을 테스트한다."""

import json
import copy
import unittest

from integrations.result_merge import (
    deduplicate_results,
    finalize_analysis,
    finalize_rule_analysis,
    merge_analysis_responses,
    merge_clause_results,
    merge_same_risk,
    prepare_rule_response,
    validate_candidate_response,
    validate_evidence_span,
)
from integrations.response_validation import (
    Rejected,
    ResponseValidationGate,
)
from scripts.risk_rules import analyze_document, to_api

class ResultMergeTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "document_id": "synthetic_contract",
            "clauses": [
                {
                    "clause_id": "C001",
                    "page": 1,
                    "text": "임차인은 모든 수리비를 부담한다.",
                }
            ],
        }

        self.response = {
            "document_id": "synthetic_contract",
            "status": "completed",
            "results": [
                {
                    "clause_id": "C001",
                    "risk_type": "repair_cost",
                    "risk_status": "potential_risk",
                    "evidence": "임차인은 모든 수리비를 부담한다.",
                    "reason": "수리비 부담 범위가 넓게 정해져 있습니다.",
                    "possible_disadvantage": "예상하지 못한 수리비를 부담할 수 있습니다.",
                    "question": "노후화로 발생한 수리비도 포함되나요?",
                    "recommended_action": "수리 원인별 비용 부담 범위를 확인하세요.",
                }
            ],
            "warnings": [],
        }

    def test_valid_response_passes_without_changing_inputs(self):
        original_request = copy.deepcopy(self.request)
        original_response = copy.deepcopy(self.response)

        result = validate_candidate_response(
            self.request, self.response
        )

        self.assertEqual(result, original_response)
        self.assertEqual(self.request, original_request)
        self.assertEqual(self.response, original_response)

    def test_evidence_not_in_clause_is_rejected(self):
        self.response["results"][0]["evidence"] = (
            "임대인은 보증금을 반환하지 않는다."
        )

        with self.assertRaisesRegex(Rejected, "evidence_mismatch"):
            validate_candidate_response(
                self.request, self.response
            )

    def test_identical_duplicates_are_removed(self):
        row = self.response["results"][0]
        rows = [copy.deepcopy(row), copy.deepcopy(row)]
        original = copy.deepcopy(rows)

        result = deduplicate_results(rows)

        self.assertEqual(result, [row])
        self.assertEqual(rows, original)

        result[0]["reason"] = "복사 결과 수정"
        self.assertEqual(rows, original)

    def test_different_risk_types_are_preserved(self):
        first = copy.deepcopy(self.response["results"][0])
        second = copy.deepcopy(first)
        second["risk_type"] = "other"

        result = deduplicate_results([first, second])

        self.assertEqual(result, [first, second])

    def test_conflicting_duplicates_are_rejected(self):
        first = copy.deepcopy(self.response["results"][0])
        second = copy.deepcopy(first)
        second["risk_status"] = "needs_review"

        with self.assertRaisesRegex(
            Rejected, "same_source_conflict"
        ):
            deduplicate_results([first, second])

    def test_matching_evidence_span_passes(self):
        text = self.request["clauses"][0]["text"]

        validate_evidence_span(text, text, [0, len(text)])

    def test_wrong_evidence_span_is_rejected(self):
        text = self.request["clauses"][0]["text"]

        with self.assertRaisesRegex(
            Rejected, "evidence_span_mismatch"
        ):
            validate_evidence_span(text, text, [1, len(text)])

    def test_invalid_evidence_spans_are_rejected(self):
        text = self.request["clauses"][0]["text"]
        invalid_spans = [
            [-1, len(text)],
            [0, len(text) + 1],
            [0, 0],
            [True, len(text)],
            ["0", len(text)],
            [0],
            None,
        ]

        for span in invalid_spans:
            with self.subTest(span=span):
                with self.assertRaisesRegex(
                    Rejected, "invalid_evidence_span"
                ):
                    validate_evidence_span(text, text, span)


    def test_actual_rule_result_passes_validation(self):
        # 테스트 안에서만 검토 완료 상태를 가정한다.
        rule_result = analyze_document(
            self.request,
            review_ids=["C001"],
        )

        clause = rule_result["clauses"][0]
        self.assertFalse(clause["needs_review"])

        # 실제 규칙 엔진이 반환한 원문 위치를 검사한다.
        for finding in clause["findings"]:
            validate_evidence_span(
                clause["analysis_text"],
                finding["evidence"],
                finding["evidence_span"],
            )

        # 기존 변환 함수를 사용한 뒤 응답 전체를 검사한다.
        api_response = to_api(rule_result)
        checked = validate_candidate_response(
            self.request, api_response
        )

        self.assertEqual(checked["status"], "completed")
        self.assertTrue(
            any(
                row["risk_type"] == "repair_cost"
                and row["risk_status"] == "potential_risk"
                for row in checked["results"]
            )
        )

    def test_unreviewed_rule_result_stays_needs_review(self):
        # 검토 완료 정보를 전달하지 않는다.
        rule_result = analyze_document(self.request)

        self.assertTrue(
            rule_result["clauses"][0]["needs_review"]
        )

        checked = validate_candidate_response(
            self.request,
            to_api(rule_result),
        )

        self.assertEqual(checked["status"], "partial")
        self.assertTrue(checked["warnings"])
        self.assertTrue(
            all(
                row["risk_status"] == "needs_review"
                for row in checked["results"]
            )
        )

    def test_same_risk_is_merged_without_changing_inputs(self):
        rule_row = copy.deepcopy(self.response["results"][0])
        llm_row = copy.deepcopy(rule_row)
        original_rule = copy.deepcopy(rule_row)
        original_llm = copy.deepcopy(llm_row)

        merged, warnings = merge_same_risk(rule_row, llm_row)

        self.assertEqual(merged, original_rule)
        self.assertEqual(warnings, [])

        merged["reason"] = "병합 결과 수정"
        self.assertEqual(rule_row, original_rule)
        self.assertEqual(llm_row, original_llm)

    def test_different_judgments_require_review(self):
        rule_row = copy.deepcopy(self.response["results"][0])
        llm_row = copy.deepcopy(rule_row)
        llm_row["risk_status"] = "needs_review"

        merged, warnings = merge_same_risk(rule_row, llm_row)

        self.assertEqual(merged["risk_status"], "needs_review")
        self.assertEqual(merged["evidence"], rule_row["evidence"])
        self.assertEqual(merged["reason"], rule_row["reason"])
        self.assertTrue(warnings)

        candidate = copy.deepcopy(self.response)
        candidate["status"] = "partial"
        candidate["results"] = [merged]
        candidate["warnings"] = warnings

        validate_candidate_response(self.request, candidate)

    def test_rule_risk_and_llm_no_risk_require_review(self):
        rule_row = copy.deepcopy(self.response["results"][0])
        llm_row = copy.deepcopy(rule_row)
        llm_row["risk_type"] = "none"
        llm_row["risk_status"] = "no_risk_detected"
        llm_row["reason"] = "검사한 범위에서 위험을 찾지 못했습니다."

        rows, warnings = merge_clause_results(
            [rule_row], [llm_row]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["risk_type"], "repair_cost")
        self.assertEqual(rows[0]["risk_status"], "needs_review")
        self.assertEqual(rows[0]["evidence"], rule_row["evidence"])
        self.assertEqual(rule_row["risk_status"], "potential_risk")
        self.assertTrue(warnings)

        candidate = copy.deepcopy(self.response)
        candidate["status"] = "partial"
        candidate["results"] = rows
        candidate["warnings"] = warnings
        validate_candidate_response(self.request, candidate)

    def test_rule_no_risk_and_llm_risk_require_review(self):
        llm_row = copy.deepcopy(self.response["results"][0])
        rule_row = copy.deepcopy(llm_row)
        rule_row["risk_type"] = "none"
        rule_row["risk_status"] = "no_risk_detected"
        rule_row["reason"] = "검사한 범위에서 위험을 찾지 못했습니다."

        rows, warnings = merge_clause_results(
            [rule_row], [llm_row]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["risk_type"], "repair_cost")
        self.assertEqual(rows[0]["risk_status"], "needs_review")
        self.assertEqual(rows[0]["evidence"], llm_row["evidence"])
        self.assertTrue(warnings)

    def test_different_risks_survive_clause_merge(self):
        rule_row = copy.deepcopy(self.response["results"][0])
        llm_row = copy.deepcopy(rule_row)
        llm_row["risk_type"] = "other"

        rows, warnings = merge_clause_results(
            [rule_row], [llm_row]
        )

        self.assertEqual(
            {row["risk_type"] for row in rows},
            {"repair_cost", "other"},
        )
        self.assertEqual(warnings, [])

    def test_document_merge_with_matching_sources(self):
        result = merge_analysis_responses(
            self.request,
            rule_response=self.response,
            llm_response=copy.deepcopy(self.response),
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["warnings"], [])

    def test_rule_only_document_is_partial(self):
        result = merge_analysis_responses(
            self.request,
            rule_response=self.response,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["results"], self.response["results"]
        )
        self.assertTrue(result["warnings"])

    def test_invalid_llm_keeps_valid_rule_results(self):
        bad_llm = copy.deepcopy(self.response)
        bad_llm["results"][0]["evidence"] = (
            "계약서에 없는 가상 문장"
        )

        result = merge_analysis_responses(
            self.request,
            rule_response=self.response,
            llm_response=bad_llm,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["results"], self.response["results"]
        )
        self.assertTrue(result["warnings"])
        self.assertNotIn(
            "계약서에 없는 가상 문장",
            json.dumps(result, ensure_ascii=False),
        )

    def _make_approved_gate(self):
        source = b"\x89PNG\r\n\x1a\nsynthetic-original"
        image = b"\x89PNG\r\n\x1a\nsynthetic-masked"

        gate = ResponseValidationGate(
            lambda _: {
                "masked_image": image,
                "ocr_lines": [
                    {"text": clause["text"], "confidence": 1.0}
                    for clause in self.request["clauses"]
                ],
            }
        )

        receipt = gate.prepare(
            "owner", self.request["document_id"], 1, source
        )
        self.assertIsNotNone(receipt)

        approved = gate.confirm_analysis_review(
            "owner",
            receipt["receipt_id"],
            self.request,
            receipt["image_sha256"],
            receipt["text_sha256"],
        )
        self.assertTrue(approved)

        started = gate.begin_analysis_mock(
            "owner",
            receipt["receipt_id"],
            image,
            1,
            self.request,
        )
        self.assertTrue(started["ok"])

        return gate, started

    def _finalize_for_test(self, gate, started, **overrides):
        args = {
            "owner": "owner",
            "ticket": started["response_ticket"],
            "request": self.request,
            "rule_response": self.response,
            "llm_response": copy.deepcopy(self.response),
            "image_sha256": started["image_sha256"],
            "text_sha256": started["text_sha256"],
            "revision": 1,
        }
        args.update(overrides)
        return finalize_analysis(gate, **args)

    def test_final_merge_passes_approval_gate(self):
        gate, started = self._make_approved_gate()

        result = self._finalize_for_test(gate, started)

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["response"]["status"], "completed"
        )

    def test_final_merge_ticket_cannot_be_reused(self):
        gate, started = self._make_approved_gate()

        first = self._finalize_for_test(gate, started)
        second = self._finalize_for_test(gate, started)

        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertNotIn("response", second)

    def test_final_merge_rejects_wrong_image_hash(self):
        gate, started = self._make_approved_gate()

        result = self._finalize_for_test(
            gate, started, image_sha256="a" * 64
        )

        self.assertFalse(result["ok"])
        self.assertNotIn("response", result)

    def test_prepare_actual_rules_then_merge(self):
        rule_result = analyze_document(
            self.request, review_ids=["C001"]
        )
        original = copy.deepcopy(rule_result)

        prepared = prepare_rule_response(
            self.request, rule_result
        )
        merged = merge_analysis_responses(
            self.request,
            rule_response=prepared,
        )

        self.assertEqual(rule_result, original)
        self.assertEqual(merged["status"], "partial")
        self.assertEqual(
            merged["results"][0]["risk_type"], "repair_cost"
        )

    def test_prepare_rejects_unreviewed_rules(self):
        rule_result = analyze_document(self.request)

        with self.assertRaisesRegex(
            Rejected, "no_supported_rule_results"
        ):
            prepare_rule_response(self.request, rule_result)

    def test_bad_span_preserves_other_valid_clause(self):
        request = copy.deepcopy(self.request)
        request["clauses"].append({
            "clause_id": "C002",
            "page": 1,
            "text": "임차인은 모든 수리비를 부담한다.",
        })

        rule_result = analyze_document(
            request, review_ids=["C001", "C002"]
        )
        rule_result["clauses"][0]["findings"][0][
            "evidence_span"
        ] = [1, 2]

        prepared = prepare_rule_response(
            request, rule_result
        )

        self.assertEqual(prepared["status"], "partial")
        self.assertEqual(
            {row["clause_id"] for row in prepared["results"]},
            {"C002"},
        )
        self.assertTrue(prepared["warnings"])

    def test_actual_rules_merge_and_final_gate(self):
        rule_result = analyze_document(
            self.request, review_ids=["C001"]
        )
        prepared = prepare_rule_response(
            self.request, rule_result
        )
        gate, started = self._make_approved_gate()

        result = self._finalize_for_test(
            gate,
            started,
            rule_response=prepared,
            llm_response=copy.deepcopy(prepared),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["response"]["status"], "completed"
        )
        self.assertEqual(
            result["response"]["results"][0]["risk_type"],
            "repair_cost",
        )

    def test_private_llm_response_is_excluded(self):
        bad_llm = copy.deepcopy(self.response)
        marker = "synthetic@example.invalid"
        bad_llm["results"][0]["question"] = marker

        result = merge_analysis_responses(
            self.request,
            rule_response=self.response,
            llm_response=bad_llm,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["results"], self.response["results"]
        )
        self.assertTrue(result["warnings"])
        self.assertNotIn(
            marker, json.dumps(result, ensure_ascii=False)
        )

    def test_unknown_llm_clause_is_excluded(self):
        bad_llm = copy.deepcopy(self.response)
        bad_llm["results"][0]["clause_id"] = "C999"

        result = merge_analysis_responses(
            self.request,
            rule_response=self.response,
            llm_response=bad_llm,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["results"], self.response["results"]
        )
        self.assertNotIn(
            "C999", json.dumps(result, ensure_ascii=False)
        )

    def test_document_merge_is_repeatable_and_keeps_inputs(self):
        request = copy.deepcopy(self.request)
        rules = copy.deepcopy(self.response)
        llm = copy.deepcopy(self.response)
        originals = copy.deepcopy((request, rules, llm))

        first = merge_analysis_responses(
            request,
            rule_response=rules,
            llm_response=llm,
        )
        second = merge_analysis_responses(
            request,
            rule_response=rules,
            llm_response=llm,
        )

        self.assertEqual(first, second)
        self.assertEqual((request, rules, llm), originals)

    def test_llm_only_response_is_partial(self):
        result = merge_analysis_responses(
            self.request,
            llm_response=self.response,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["results"], self.response["results"]
        )
        self.assertTrue(result["warnings"])

    def test_missing_clause_is_not_marked_no_risk(self):
        request = copy.deepcopy(self.request)
        request["clauses"].append({
            "clause_id": "C002",
            "page": 2,
            "text": "임대인은 계약 종료 시 보증금을 반환한다.",
        })

        partial_response = copy.deepcopy(self.response)
        partial_response["status"] = "partial"
        partial_response["warnings"] = [
            "C002는 아직 분석되지 않았습니다."
        ]

        result = merge_analysis_responses(
            request,
            rule_response=partial_response,
            llm_response=copy.deepcopy(partial_response),
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            {row["clause_id"] for row in result["results"]},
            {"C001"},
        )
        self.assertTrue(
            any("C002" in warning for warning in result["warnings"])
        )

    def test_final_merge_rejects_unissued_ticket(self):
        gate = ResponseValidationGate()
        started = {
            "response_ticket": "unissued-test-ticket",
            "image_sha256": "a" * 64,
            "text_sha256": "b" * 64,
        }

        result = self._finalize_for_test(gate, started)

        self.assertFalse(result["ok"])
        self.assertNotIn("response", result)

    def test_final_merge_rejects_expired_ticket(self):
        gate, started = self._make_approved_gate()

        # 테스트에서만 만료 상태를 재현한다.
        gate._ttl = -1

        result = self._finalize_for_test(gate, started)

        self.assertFalse(result["ok"])
        self.assertNotIn("response", result)

    def test_categorical_llm_claim_is_excluded(self):
        bad_llm = copy.deepcopy(self.response)
        bad_llm["results"][0]["reason"] = "이 계약은 무효입니다."

        result = merge_analysis_responses(
            self.request,
            rule_response=self.response,
            llm_response=bad_llm,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["results"], self.response["results"]
        )
        self.assertNotIn(
            "무효입니다",
            json.dumps(result, ensure_ascii=False),
        )

    def test_merge_failure_also_consumes_ticket(self):
        gate, started = self._make_approved_gate()

        failed = self._finalize_for_test(
            gate,
            started,
            rule_response={},
        )
        retried = self._finalize_for_test(gate, started)

        self.assertFalse(failed["ok"])
        self.assertNotIn("response", failed)
        self.assertFalse(retried["ok"])

    def _finalize_rules_for_test(self, gate, started, rule_result):
        return finalize_rule_analysis(
            gate,
            owner="owner",
            ticket=started["response_ticket"],
            request=self.request,
            rule_result=rule_result,
            image_sha256=started["image_sha256"],
            text_sha256=started["text_sha256"],
            revision=1,
        )

    def test_rule_entry_runs_full_validation_path(self):
        rule_result = analyze_document(
            self.request, review_ids=["C001"]
        )
        gate, started = self._make_approved_gate()

        result = self._finalize_rules_for_test(
            gate, started, rule_result
        )

        self.assertTrue(result["ok"])
        # LLM 결과가 없으므로 부분 분석이다.
        self.assertEqual(
            result["response"]["status"], "partial"
        )
        self.assertEqual(
            result["response"]["results"][0]["risk_type"],
            "repair_cost",
        )

    def test_rule_entry_blocks_bad_span_and_consumes_ticket(self):
        rule_result = analyze_document(
            self.request, review_ids=["C001"]
        )
        rule_result["clauses"][0]["findings"][0][
            "evidence_span"
        ] = [1, 2]
        gate, started = self._make_approved_gate()

        failed = self._finalize_rules_for_test(
            gate, started, rule_result
        )

        self.assertFalse(failed["ok"])
        self.assertNotIn("response", failed)

        valid_rules = analyze_document(
            self.request, review_ids=["C001"]
        )
        retried = self._finalize_rules_for_test(
            gate, started, valid_rules
        )

        self.assertFalse(retried["ok"])

    def test_rule_entry_blocks_unreviewed_rule_results(self):
        rule_result = analyze_document(self.request)
        gate, started = self._make_approved_gate()

        result = self._finalize_rules_for_test(
            gate, started, rule_result
        )

        self.assertFalse(result["ok"])
        self.assertNotIn("response", result)

if __name__ == "__main__":
    unittest.main()