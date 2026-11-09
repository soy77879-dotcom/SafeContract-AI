
import time

from integrations import review_app, review_store
from integrations.review_store import ReviewStore
from integrations.response_validation import ResponseValidationGate


def make_store():
    gate = ResponseValidationGate()
    store = ReviewStore(gate_invalidator=gate.invalidate)

    owner = "user-a"
    doc = "doc-001"

    store.entries[doc] = {
        "owner": owner,
        "created": time.monotonic(),
        "data": {
            "clauses": [
                {
                    "clause_id": "C001",
                    "raw_text": "계약 기간 1년",
                    "edited_text": "계약 기간 1년",
                }
            ]
        },
        "image_hash": "test-image-hash",
        "version": 1,
        "privacy": "no_candidates",
        "confirmed": {"C001"},
        "confirmed_hashes": {},
        "challenges": {},
        "analysis_token": None,
    }

    gate._responses = {
        "old-ticket": {
            "owner": owner,
            "document": doc,
        },
        "other-ticket": {
            "owner": "user-b",
            "document": "doc-002",
        },
    }

    binding = {
        "document_id": doc,
        "document_version": 1,
        "image_sha256": "test-image-hash",
    }

    return store, gate, owner, doc, binding


def test_review_invalidate_clears_gate_ticket():
    store, gate, owner, doc, binding = make_store()

    store.invalidate(owner, doc, binding)

    assert "old-ticket" not in gate._responses
    assert "other-ticket" in gate._responses
    assert store.entries[doc]["version"] == 2


def test_review_save_clears_gate_ticket(monkeypatch):
    store, gate, owner, doc, binding = make_store()

    monkeypatch.setattr(
        review_store,
        "scan_lines",
        lambda lines: {"status": "no_candidates"},
    )

    payload = {
        **binding,
        "clauses": [
            {
                "clause_id": "C001",
                "raw_text": "계약 기간 1년",
                "edited_text": "계약 기간 2년",
            }
        ],
    }

    store.save(owner, doc, payload)

    assert "old-ticket" not in gate._responses
    assert "other-ticket" in gate._responses
    assert store.entries[doc]["version"] == 2
    assert (
        store.entries[doc]["data"]["clauses"][0]["edited_text"]
        == "계약 기간 2년"
    )


def test_default_router_connects_same_gate(monkeypatch):
    captured = {}

    class SpyGate:
        def __init__(self):
            captured["gate"] = self

        def invalidate(self, owner, doc):
            pass

    class SpyStore:
        def __init__(self, gate_invalidator=None):
            captured["invalidator"] = gate_invalidator

    monkeypatch.setattr(
        review_app, "ResponseValidationGate", SpyGate
    )
    monkeypatch.setattr(
        review_app, "ReviewStore", SpyStore
    )

    review_app.create_router(
        ocr=object(),
        privacy=object(),
        masker=object(),
    )

    assert captured["invalidator"] is not None
    assert (
        captured["invalidator"].__self__
        is captured["gate"]
    )
