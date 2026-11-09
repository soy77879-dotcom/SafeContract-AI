
"""Isolated security tests for the server-only local response bridge.

No public routes, real LLM, network transport, or production changes.
"""

import json

import pytest

from integrations.review_gate_bridge import VerifiedLocalResponseGate
from integrations.privacy_detection import scan_lines
from test_masking_evidence import evidence
from test_review_http import binding, draft


@pytest.fixture
def connected(evidence):
    """Build a store and a gate linked through revocation."""

    store, document, _ = evidence

    gate = VerifiedLocalResponseGate()
    store._gate_invalidator = gate.invalidate

    owner = "owner"
    document_id = document["document_id"]
    context = binding(document)

    return store, gate, owner, document_id, context


def issue(fixture, **changes):
    """Issue a local ticket from server-side review evidence."""

    store, gate, owner, document_id, context = fixture

    arguments = {
        "store": store,
        "owner": owner,
        "document_id": document_id,
        "binding": context,
    }

    arguments.update(changes)

    return gate.issue_local_ticket(**arguments)


def valid_response(store, owner, document_id):
    """Build a complete synthetic response for gate validation."""

    document = store.get(owner, document_id)
    clauses = document["clauses"]

    return {
        "document_id": document_id,
        "status": "completed",
        "results": [
            {
                "clause_id": clause["clause_id"],
                "risk_type": "none",
                "risk_status": "no_risk_detected",
                "evidence": clause["edited_text"],
                "reason": (
                    "검사한 범위에서 위험 신호를 찾지 못했습니다."
                ),
                "possible_disadvantage": (
                    "추가 확인이 필요한 상황이 발생할 수 있습니다."
                ),
                "question": (
                    "계약 조건을 다시 확인하셨나요?"
                ),
                "recommended_action": (
                    "계약서의 관련 내용을 확인하세요."
                ),
            }
            for clause in clauses
        ],
        "warnings": [],
    }


def validate(fixture, ticket, response=None):
    """Validate a candidate using the existing one-use response gate."""

    store, gate, owner, document_id, _ = fixture

    if response is None:
        response = valid_response(
            store,
            owner,
            document_id,
        )

    return gate.validate_response(
        owner=owner,
        ticket=ticket["response_ticket"],
        raw=json.dumps(
            response,
            ensure_ascii=False,
            allow_nan=False,
        ),
        image_sha256=ticket["image_sha256"],
        text_sha256=ticket["text_sha256"],
        revision=ticket["revision"],
    )


def assert_approved(result):
    """Expose only the gate's constant rejection reason on failure."""

    assert result["ok"] is True, (
        "Response gate rejected valid result: "
        f"{result.get('internal_reason', 'unknown')}"
    )

    assert "response" in result


def assert_rejected(result):
    """Rejected results must never contain publishable content."""

    assert result["ok"] is False
    assert "response" not in result
    assert "error" in result


def test_verified_evidence_issues_local_ticket(connected):
    ticket = issue(connected)

    assert ticket is not None
    assert ticket["ok"] is True
    assert ticket["mode"] == "local_only"
    assert ticket["external_llm_called"] is False
    assert ticket["external_llm_allowed"] is False

    result = validate(connected, ticket)

    assert_approved(result)

    assert result["response"]["document_id"] == connected[3]


def test_ticket_replay_rejected(connected):
    ticket = issue(connected)

    assert ticket is not None

    first = validate(connected, ticket)

    # Replay protection matters only after successful validation.
    assert_approved(first)

    second = validate(connected, ticket)

    assert_rejected(second)

    assert second.get("internal_reason") == (
        "unapproved_response"
    )


def test_wrong_owner_cannot_issue(connected):
    assert issue(
        connected,
        owner="other-owner",
    ) is None


def test_wrong_document_cannot_issue(connected):
    assert issue(
        connected,
        document_id="other-document",
    ) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("document_id", "wrong"),
        ("document_version", 999),
        ("image_sha256", "bad"),
    ],
)
def test_invalid_binding_cannot_issue(
    connected,
    field,
    value,
):
    context = dict(connected[4])
    context[field] = value

    assert issue(
        connected,
        binding=context,
    ) is None


def test_missing_confirmation_cannot_issue(connected):
    store, _, _, document_id, _ = connected

    store.entries[document_id]["confirmed"].clear()

    assert issue(connected) is None


def test_missing_masking_evidence_cannot_issue(connected):
    store, _, _, document_id, _ = connected

    store.entries[document_id].pop(
        "masking_evidence",
        None,
    )

    assert issue(connected) is None


def test_privacy_required_cannot_issue(connected):
    store, _, _, document_id, _ = connected

    store.entries[document_id]["privacy"] = (
        "review_required"
    )

    assert issue(connected) is None


def test_unconnected_store_cannot_issue(connected):
    store, _, _, document_id, _ = connected

    another_gate = VerifiedLocalResponseGate()

    assert another_gate.issue_local_ticket(
        store=store,
        owner="owner",
        document_id=document_id,
        binding=connected[4],
    ) is None


def test_document_invalidation_revokes_ticket(connected):
    store, _, owner, document_id, context = connected

    ticket = issue(connected)

    assert ticket is not None

    store.invalidate(
        owner,
        document_id,
        context,
    )

    result = validate(connected, ticket)

    assert_rejected(result)


def test_document_save_revokes_ticket(connected):
    store, _, owner, document_id, _ = connected

    ticket = issue(connected)

    assert ticket is not None

    document = store.get(owner, document_id)

    store.save(
        owner,
        document_id,
        draft(document),
    )

    result = validate(connected, ticket)

    assert_rejected(result)


def test_expired_document_cannot_issue(connected):
    store, _, _, document_id, _ = connected

    store.entries[document_id]["created"] -= (
        store.ttl + 1
    )

    assert issue(connected) is None


def test_expired_ticket_rejected(connected):
    _, gate, _, _, _ = connected

    ticket = issue(connected)

    assert ticket is not None

    gate._ttl = -1

    result = validate(connected, ticket)

    assert_rejected(result)


def test_invalid_response_consumes_ticket(connected):
    ticket = issue(connected)

    assert ticket is not None

    invalid = valid_response(
        connected[0],
        "owner",
        connected[3],
    )

    invalid["results"][0]["evidence"] = (
        "원문에 존재하지 않는 근거"
    )

    first = validate(
        connected,
        ticket,
        invalid,
    )

    assert_rejected(first)

    assert first.get("internal_reason") == (
        "evidence_mismatch"
    )

    # Failed validation must consume the original ticket.
    second = validate(connected, ticket)

    assert_rejected(second)

    assert second.get("internal_reason") == (
        "unapproved_response"
    )


def test_private_response_is_rejected(connected):
    ticket = issue(connected)

    assert ticket is not None

    response = valid_response(
        connected[0],
        "owner",
        connected[3],
    )

    response["warnings"] = [
        "synthetic@example.invalid"
    ]

    result = validate(
        connected,
        ticket,
        response,
    )

    assert_rejected(result)

    assert result["error"]["error"]["code"] == (
        "PRIVACY_CHECK_FAILED"
    )

    assert result.get("internal_reason") == (
        "privacy_candidate"
    )

    # Rejected output must not disclose the synthetic email.
    assert "synthetic@example.invalid" not in json.dumps(
        result,
        ensure_ascii=False,
    )


def test_no_network_dispatch(connected, monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError(
            "Network or dispatch is forbidden"
        )

    monkeypatch.setattr(
        "integrations.transfer_guard.TransferGate.dispatch_mock",
        forbid,
    )

    ticket = issue(connected)

    assert ticket is not None
    assert ticket["ok"] is True
    assert ticket["mode"] == "local_only"
    assert ticket["external_llm_called"] is False
    assert ticket["external_llm_allowed"] is False


def test_diagnose_synthetic_response_privacy(connected):
    """Ensure no synthetic output field triggers the privacy scanner."""

    store, _, owner, document_id, _ = connected

    response = valid_response(
        store,
        owner,
        document_id,
    )

    fields = {
        "document_id": response["document_id"],
    }

    for index, row in enumerate(response["results"]):
        for key, value in row.items():
            fields[f"result_{index}_{key}"] = value

    for index, warning in enumerate(response["warnings"]):
        fields[f"warning_{index}"] = warning

    flagged = []

    for name, value in fields.items():
        scan = scan_lines(
            [
                {
                    "text": value,
                    "confidence": 1.0,
                }
            ]
        )

        if scan.get("status") != "no_candidates":
            # Store field name and status only.
            # Do not print contract text or scanner findings.
            flagged.append(
                {
                    "field": name,
                    "status": scan.get("status"),
                }
            )

    assert not flagged, (
        "Synthetic response failed privacy scanning: "
        f"{flagged}"
    )

    # Also check the exact combined string list used by
    # ResponseValidationGate.validate_content().
    strings = [
        response["document_id"],
        *response["warnings"],
    ]

    for row in response["results"]:
        strings.extend(row.values())

    combined = scan_lines(
        [
            {
                "text": value,
                "confidence": 1.0,
            }
            for value in strings
        ]
    )

    assert combined.get("status") == "no_candidates", (
        "Combined synthetic response privacy scan failed: "
        f"{combined.get('status')}"
    )

    assert combined.get("found") is False
