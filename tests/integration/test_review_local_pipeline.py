
"""Tests for the B-1 server-only local analysis pipeline."""

import pytest

from integrations.review_gate_bridge import VerifiedLocalResponseGate
from integrations.review_local_pipeline import (
    run_local_review_analysis,
)

from test_masking_evidence import evidence
from test_review_http import binding


@pytest.fixture
def connected(evidence):
    store, document, _ = evidence

    gate = VerifiedLocalResponseGate()
    store._gate_invalidator = gate.invalidate

    return (
        store,
        gate,
        "owner",
        document["document_id"],
        binding(document),
    )


def execute(context):
    store, gate, owner, document_id, data = context

    return run_local_review_analysis(
        store=store,
        gate=gate,
        owner=owner,
        document_id=document_id,
        binding=data,
    )


def test_local_analysis_is_validated(connected):
    result = execute(connected)

    assert result["ok"] is True, result.get(
        "internal_reason"
    )

    assert result["mode"] == "local_only"
    assert result["external_llm_called"] is False
    assert result["external_llm_allowed"] is False

    response = result["response"]

    assert response["document_id"] == connected[3]
    assert response["results"]


def test_wrong_owner_is_rejected(connected):
    store, gate, _, document_id, data = connected

    result = run_local_review_analysis(
        store=store,
        gate=gate,
        owner="another-owner",
        document_id=document_id,
        binding=data,
    )

    assert result["ok"] is False
    assert "response" not in result


def test_unconfirmed_document_is_rejected(connected):
    store, _, _, document_id, _ = connected

    store.entries[document_id]["confirmed"].clear()

    result = execute(connected)

    assert result["ok"] is False
    assert "response" not in result


def test_wrong_binding_is_rejected(connected):
    store, gate, owner, document_id, data = connected

    bad = dict(data)
    bad["image_sha256"] = "invalid"

    result = run_local_review_analysis(
        store=store,
        gate=gate,
        owner=owner,
        document_id=document_id,
        binding=bad,
    )

    assert result["ok"] is False
    assert "response" not in result


def test_unconnected_gate_is_rejected(connected):
    store, _, owner, document_id, data = connected

    unrelated_gate = VerifiedLocalResponseGate()

    result = run_local_review_analysis(
        store=store,
        gate=unrelated_gate,
        owner=owner,
        document_id=document_id,
        binding=data,
    )

    assert result["ok"] is False
    assert "response" not in result


def test_local_rule_failure_is_not_published(
    connected,
    monkeypatch,
):
    def broken(*args, **kwargs):
        raise RuntimeError("Synthetic local failure")

    monkeypatch.setattr(
        "integrations.review_local_pipeline."
        "analyze_reviewed_rules",
        broken,
    )

    result = execute(connected)

    assert result["ok"] is False
    assert "response" not in result

    assert "Synthetic local failure" not in str(result)


def test_no_external_dispatch(connected, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "External dispatch must not run"
        )

    monkeypatch.setattr(
        "integrations.transfer_guard."
        "TransferGate.dispatch_mock",
        forbidden,
    )

    result = execute(connected)

    assert result["external_llm_called"] is False

    if result["ok"]:
        assert result["mode"] == "local_only"

