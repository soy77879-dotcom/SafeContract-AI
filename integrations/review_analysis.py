"""Trusted server-only local rule candidates, NOT public analysis approval.

No route, transport, fabricated review ledger or ResponseValidationGate ticket.
"""
from dataclasses import dataclass, field
from typing import Literal

from backend.schemas import AnalyzeResponse
from integrations.adapter import AdapterError
from integrations.response_validation import Rejected, strict_request
from integrations.result_merge import prepare_rule_response, validate_evidence_span
from scripts.risk_rules import analyze_document


@dataclass(frozen=True)
class LocalRuleCandidate:
    # Suppress document contents in accidental repr/logging.
    candidate_response: AnalyzeResponse = field(repr=False)
    publication_allowed: Literal[False] = field(default=False, init=False)
    external_llm_allowed: Literal[False] = field(default=False, init=False)
    approval_status: str = field(default='blocked_response_gate_not_bound', init=False)


def _check_complete_rule_result(request, result):
    """Require all original inputs; prepare_rule_response can otherwise drop bad rows."""
    rows=result.get('clauses')
    if result.get('document_id')!=request['document_id'] or not isinstance(rows,list):
        raise Rejected('rule_source_mismatch')
    if [r.get('clause_id') for r in rows]!=[c['clause_id'] for c in request['clauses']]:
        raise Rejected('rule_source_mismatch')
    for clause,row in zip(request['clauses'],rows):
        if (row.get('page')!=clause['page'] or row.get('pages')!=[clause['page']]
                or row.get('analysis_text')!=clause['text'] or row.get('needs_review') is not False):
            raise Rejected('rule_source_mismatch')
        if not isinstance(row.get('findings'),list) or not row['findings']:
            raise Rejected('missing_rule_findings')
        for finding in row['findings']:
            validate_evidence_span(clause['text'],finding.get('evidence'),finding.get('evidence_span'))


def analyze_rule_snapshot(store, owner, document_id, binding, snapshot):
    """Consume a server-issued snapshot once; return only an INTERNAL candidate.

    owner must come from the existing authenticated session/CSRF pipeline.
    Lock remains held through local analysis and response validation. Invalidation
    from other threads is serialized; reentrant edits and expiry reject on exit.
    No caller-provided approval flag or alternate text is trusted.
    """
    try:
        with store.analysis_input_guard(owner,document_id,binding,snapshot) as model:
            request=strict_request(model.model_dump())
            # These IDs derive only from the store's full-confirmation gate.
            result=analyze_document(request,review_ids=[c['clause_id'] for c in request['clauses']])
            _check_complete_rule_result(request,result)
            response=prepare_rule_response(request,result)
            # prepare_rule_response reuses strict response parsing, exact evidence,
            # privacy detection and categorical-legal-claim rejection.
            candidate=LocalRuleCandidate(AnalyzeResponse.model_validate(response,strict=True))
        # Context exit rechecks current input and expiry before anything is returned.
        return candidate
    except AdapterError:
        raise
    except Exception:
        # Never expose rule text, scanner output or parser exceptions.
        raise AdapterError(422,'VALIDATION_ERROR','규칙 분석 결과를 검증하지 못했습니다.') from None


def analyze_reviewed_rules(store, owner, document_id, binding):
    """Get exact server-stored edited text and run the one-use local candidate path.

    This is not a replacement for ResponseValidationGate.validate_response.
    Publication stays blocked until a genuine compatible gate context is available.
    """
    snapshot=store.get_analysis_input(owner,document_id,binding)
    return analyze_rule_snapshot(store,owner,document_id,binding,snapshot)
