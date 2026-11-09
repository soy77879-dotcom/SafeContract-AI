
import time

import pytest

from integrations.adapter import AdapterError
from integrations.review_store import ReviewStore
from integrations.response_validation import ResponseValidationGate


def make_store(ttl=3600, invalidator=None):
    gate = ResponseValidationGate()
    callback = gate.invalidate if invalidator is None else invalidator
    store = ReviewStore(ttl=ttl, gate_invalidator=callback)

    owner = "owner-a"
    doc = "doc-a"

    store.entries[doc] = {
        "owner": owner,
        "created": time.monotonic(),
        "data": {"clauses": []},
        "image_hash": "image-a",
        "version": 1,
        "privacy": "no_candidates",
        "confirmed": set(),
        "confirmed_hashes": {},
        "challenges": {},
        "analysis_token": None,
    }

    gate._responses["old-ticket"] = {
        "owner": owner,
        "document": doc,
    }
    gate._responses["other-ticket"] = {
        "owner": "owner-b",
        "document": "doc-b",
    }

    return store, gate, owner, doc


def test_expiry_revokes_target_ticket():
    store, gate, owner, doc = make_store(ttl=1)
    store.entries[doc]["created"] -= 10

    with pytest.raises(AdapterError) as exc:
        store.get(owner, doc)

    assert exc.value.status == 410
    assert doc not in store.entries
    assert "old-ticket" not in gate._responses
    assert "other-ticket" in gate._responses


def test_revocation_failure_blocks_invalidation():
    def broken_gate(owner, doc):
        raise RuntimeError("simulated gate failure")

    store, _, owner, doc = make_store(invalidator=broken_gate)

    binding = {
        "document_id": doc,
        "document_version": 1,
        "image_sha256": "image-a",
    }

    with pytest.raises(AdapterError) as exc:
        store.invalidate(owner, doc, binding)

    assert exc.value.status == 403
    assert exc.value.code == "PRIVACY_CHECK_FAILED"
    assert store.entries[doc]["version"] == 1


def test_revocation_failure_blocks_expiry_cleanup():
    def broken_gate(owner, doc):
        raise RuntimeError("simulated gate failure")

    store, _, owner, doc = make_store(
        ttl=1,
        invalidator=broken_gate,
    )
    store.entries[doc]["created"] -= 10

    with pytest.raises(AdapterError) as exc:
        store.get(owner, doc)

    assert exc.value.status == 403
    assert doc in store.entries


def test_other_owner_cannot_invalidate():
    store, gate, _, doc = make_store()

    binding = {
        "document_id": doc,
        "document_version": 1,
        "image_sha256": "image-a",
    }

    with pytest.raises(AdapterError) as exc:
        store.invalidate("owner-b", doc, binding)

    assert exc.value.status == 404
    assert "old-ticket" in gate._responses
    assert store.entries[doc]["version"] == 1
