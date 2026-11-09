
from integrations.response_validation import ResponseValidationGate


def test_invalidate_only_target_document():
    gate = ResponseValidationGate()

    gate._responses = {
        "ticket-a": {"owner": "user-1", "document": "doc-1"},
        "ticket-b": {"owner": "user-1", "document": "doc-2"},
        "ticket-c": {"owner": "user-2", "document": "doc-1"},
    }

    gate.invalidate("user-1", "doc-1")

    assert "ticket-a" not in gate._responses
    assert "ticket-b" in gate._responses
    assert "ticket-c" in gate._responses


def test_invalidate_clears_transfer_records():
    gate = ResponseValidationGate()

    gate._records = {
        "receipt-a": {"owner": "user-1", "document": "doc-1"},
        "receipt-b": {"owner": "user-2", "document": "doc-1"},
    }

    gate.invalidate("user-1", "doc-1")

    assert "receipt-a" not in gate._records
    assert "receipt-b" in gate._records
