
"""Server-only local analysis response gate.

Uses verified ReviewStore evidence to issue a one-use LOCAL
response-validation ticket.

No network calls, no external LLM authorization, and no HTTP route.
"""

import copy
import secrets

from integrations.adapter import AdapterError, payload_hash
from integrations.response_validation import (
    ResponseValidationGate,
    strict_request,
)
from integrations.review_store import ReviewStore
from integrations.transfer_guard import digest


class VerifiedLocalResponseGate(ResponseValidationGate):
    """Response gate for server-verified local rule results only."""

    def issue_local_ticket(
        self,
        *,
        store,
        owner,
        document_id,
        binding,
    ):
        """Issue a local response ticket from current trusted evidence.

        The store must be connected to this gate's invalidator.
        Caller must use a server-authenticated owner.

        This does not authorize any external data transfer.
        """

        if not isinstance(store, ReviewStore):
            return None

        if not isinstance(owner, str) or not owner:
            return None

        if not isinstance(document_id, str) or not document_id:
            return None

        if not isinstance(binding, dict):
            return None

        callback = getattr(store, "_gate_invalidator", None)

        # A document mutation must revoke tickets on THIS gate.
        if (
            getattr(callback, "__self__", None) is not self
            or getattr(callback, "__name__", None) != "invalidate"
        ):
            return None

        try:
            # Store lock covers evidence verification AND ticket issue.
            with store.lock:
                evidence = store.get_review_evidence(
                    owner,
                    document_id,
                    binding,
                )

                snapshot = store.get_analysis_input(
                    owner,
                    document_id,
                    binding,
                )

                with store.review_evidence_guard(
                    owner,
                    document_id,
                    binding,
                    evidence,
                ):
                    with store.analysis_input_guard(
                        owner,
                        document_id,
                        binding,
                        snapshot,
                    ) as model:
                        request = strict_request(model.model_dump())

                        masking = evidence["masking_evidence"]

                        if (
                            evidence["document_id"] != document_id
                            or evidence["document_version"]
                            != binding["document_version"]
                            or evidence["image_sha256"]
                            != binding["image_sha256"]
                            or evidence["privacy_status"]
                            != "no_candidates"
                            or evidence["edited_request_sha256"]
                            != payload_hash(request)
                            or masking["privacy_status"]
                            != "no_candidates"
                            or masking["provenance"]
                            != "server_mask_verified_ocr_input"
                            or masking["upload_bundle_sha256"]
                            != binding["image_sha256"]
                            or masking["document_version"]
                            != binding["document_version"]
                            or masking["analysis_approved"] is not False
                            or masking["external_llm_allowed"] is not False
                        ):
                            return None

                        pages = masking.get("pages")

                        if (
                            not isinstance(pages, list)
                            or not 1 <= len(pages) <= 5
                        ):
                            return None

                        for index, page in enumerate(pages, 1):
                            image_hash = page.get(
                                "masked_image_sha256"
                            )

                            if (
                                page.get("page") != index
                                or not isinstance(image_hash, str)
                                or len(image_hash) != 64
                            ):
                                return None

                        checked_request = copy.deepcopy(request)

                # Context exits have revalidated the latest document.
                revision = binding["document_version"]
                text = "\n".join(
                    clause["text"]
                    for clause in checked_request["clauses"]
                )

                with self._lock:
                    # Revoke any older tickets for this document.
                    self.invalidate(owner, document_id)

                    self._responses = {
                        key: record
                        for key, record in self._responses.items()
                        if self._clock() - record["created"] < self._ttl
                    }

                    if len(self._responses) >= 100:
                        return None

                    ticket = secrets.token_urlsafe(32)

                    self._responses[ticket] = {
                        "owner": owner,
                        "document": document_id,
                        "generation": self._latest[
                            (owner, document_id)
                        ],
                        "revision": revision,
                        "image_hash": binding["image_sha256"],
                        "text_hash": digest(text.encode("utf-8")),
                        "created": self._clock(),
                        "reviewed": True,
                        "analysis_request": checked_request,
                        "analysis_hash": payload_hash(checked_request),
                        "local_only": True,
                        "registration_id": evidence["registration_id"],
                    }

                return {
                    "ok": True,
                    "response_ticket": ticket,
                    "image_sha256": binding["image_sha256"],
                    "text_sha256": digest(text.encode("utf-8")),
                    "revision": revision,
                    "mode": "local_only",
                    "external_llm_called": False,
                    "external_llm_allowed": False,
                }

        except (AdapterError, KeyError, TypeError, ValueError):
            return None
