"""Server-only B-1 local rule analysis pipeline.

Connects verified ReviewStore evidence, local rule analysis,
and the existing one-use response validation gate.

No HTTP routes, external LLM calls, or network transport.
"""

import json

from integrations.response_validation import fail
from integrations.review_analysis import (
    LocalRuleCandidate,
    analyze_reviewed_rules,
)
from integrations.review_gate_bridge import VerifiedLocalResponseGate
from integrations.review_store import ReviewStore


def run_local_review_analysis(
    *,
    store,
    gate,
    owner,
    document_id,
    binding,
):
    """Execute one verified local analysis and validate its response.

    The caller must provide an owner authenticated by trusted
    server-side session handling.

    The store must be connected to gate.invalidate.

    Only a response accepted by the existing response validation
    gate is returned. No client-provided analysis response or
    approval flag is trusted.
    """

    if not isinstance(store, ReviewStore):
        return fail("unapproved_request")

    if not isinstance(gate, VerifiedLocalResponseGate):
        return fail("unapproved_request")

    if not isinstance(owner, str) or not owner:
        return fail("unapproved_request")

    if not isinstance(document_id, str) or not document_id:
        return fail("unapproved_request")

    if not isinstance(binding, dict):
        return fail("unapproved_request")

    callback = getattr(
        store,
        "_gate_invalidator",
        None,
    )

    if (
        getattr(callback, "__self__", None) is not gate
        or getattr(callback, "__name__", None) != "invalidate"
    ):
        return fail("unapproved_request")

    try:
        # The store lock covers ticket issuance, local analysis,
        # and final validation.
        #
        # Document save/invalidate/expiry cannot race this flow
        # from another thread.
        # Keep the exact evidence live through the final gate's validation, too.
        # A lock prevents other threads editing, but does not stop time expiring
        # or trusted same-thread callbacks invalidating the document.
        with store.lock, store.review_evidence_guard(
            owner,
            document_id,
            binding,
            store.get_review_evidence(owner, document_id, binding),
        ):
            ticket = gate.issue_local_ticket(
                store=store,
                owner=owner,
                document_id=document_id,
                binding=binding,
            )

            if not ticket or ticket.get("ok") is not True:
                return fail("unapproved_request")

            if (
                ticket.get("mode") != "local_only"
                or ticket.get("external_llm_called") is not False
                or ticket.get("external_llm_allowed") is not False
            ):
                gate.invalidate(owner, document_id)
                return fail("unapproved_request")

            try:
                # Uses the exact confirmed edited text from
                # ReviewStore, not caller-submitted clauses.
                candidate = analyze_reviewed_rules(
                    store,
                    owner,
                    document_id,
                    binding,
                )

                if not isinstance(
                    candidate,
                    LocalRuleCandidate,
                ):
                    raise ValueError(
                        "Invalid local candidate"
                    )

                if (
                    candidate.publication_allowed is not False
                    or candidate.external_llm_allowed is not False
                ):
                    raise ValueError(
                        "Unexpected candidate permission"
                    )

                response = (
                    candidate.candidate_response.model_dump()
                )

                raw = json.dumps(
                    response,
                    ensure_ascii=False,
                    allow_nan=False,
                )

                # Existing gate performs final validation:
                # schema, original evidence, privacy, legal claims,
                # document binding, revision, hash and replay.
                #
                # This consumes the ticket even on failure.
                result = gate.validate_response(
                    owner=owner,
                    ticket=ticket["response_ticket"],
                    raw=raw,
                    image_sha256=ticket["image_sha256"],
                    text_sha256=ticket["text_sha256"],
                    revision=ticket["revision"],
                )

                if not isinstance(result, dict):
                    raise ValueError(
                        "Invalid gate result"
                    )

                if result.get("ok") is not True:
                    return result

                if "response" not in result:
                    raise ValueError(
                        "Missing validated response"
                    )

                # Return only the already validated response.
                return {
                    "ok": True,
                    "response": result["response"],
                    "mode": "local_only",
                    "external_llm_called": False,
                    "external_llm_allowed": False,
                }

            except Exception:
                # Fail closed; revoke any remaining tickets.
                gate.invalidate(owner, document_id)
                return fail("validation_failed")

    except Exception:
        # Never disclose internal document contents or exceptions.
        try:
            gate.invalidate(owner, document_id)
        except Exception:
            pass  # Still fail closed; no response leaves this function.
        return fail("unapproved_request")
