
"""Synthetic pixels; actual mask worker, mock OCR/privacy explicitly separated."""

import io
import json
import time
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw, PngImagePlugin

from integrations.review_store import ReviewStore, sha
from integrations.review_app import create_app, verify_mask
from integrations.adapter import AdapterError
from integrations.privacy_detection import scan_lines

from test_review_http import Client, fake_ocr, binding, draft
from test_privacy_service import TestClient as HTTPServer


# Fixed synthetic ID for deterministic privacy gate tests.
# Do not use real document identifiers or random digit-heavy IDs.
SYNTHETIC_DOCUMENT_ID = "synthetic_contract"


def png():
    image = Image.new("RGB", (200, 120), "white")

    ImageDraw.Draw(image).rectangle(
        (30, 30, 129, 79),
        fill="black",
    )

    info = PngImagePlugin.PngInfo()
    info.add_text("synthetic", "metadata-to-remove")

    out = io.BytesIO()
    image.save(out, format="PNG", pnginfo=info)

    return out.getvalue()


def confirm(store, owner, doc):
    for clause in doc["clauses"]:
        store.confirm(
            owner,
            doc["document_id"],
            {
                **binding(doc),
                "clause_id": clause["clause_id"],
                "challenge": doc["server_context"][
                    "review_challenges"
                ][clause["clause_id"]],
                "text_sha256": sha(
                    clause["edited_text"].encode()
                ),
            },
        )


@pytest.fixture
def evidence():
    """Build stable, fully confirmed server-side masking evidence."""

    store = ReviewStore()
    image = png()

    structured = fake_ocr([])

    # Avoid random identifiers being interpreted as private
    # numeric sequences by the conservative privacy scanner.
    structured["document_id"] = SYNTHETIC_DOCUMENT_ID

    # Do not disable or mock the privacy scanner.
    id_scan = scan_lines(
        [
            {
                "text": structured["document_id"],
                "confidence": 1.0,
            }
        ]
    )

    assert id_scan["status"] == "no_candidates"
    assert id_scan["found"] is False

    store.register(
        "owner",
        structured,
        sha(b"upload-bundle"),
        "no_candidates",
        masked_images=[image],
        masked_hashes=[sha(image)],
    )

    document = store.get(
        "owner",
        structured["document_id"],
    )

    confirm(store, "owner", document)

    return store, document, image


def test_evidence_exact_hash_metadata_only(evidence):
    store, document, image = evidence

    result = store.get_masking_evidence(
        "owner",
        document["document_id"],
        binding(document),
    )

    assert result["pages"] == [
        {
            "page": 1,
            "masked_image_sha256": sha(image),
        }
    ]

    assert result["document_id"] == document["document_id"]
    assert result["document_version"] == 1
    assert result["analysis_approved"] is False

    assert "masking_evidence" not in store.get(
        "owner",
        document["document_id"],
    )

    assert not any(
        isinstance(value, bytes)
        for value in store.entries[
            document["document_id"]
        ].values()
    )

    result["pages"][0]["masked_image_sha256"] = "bad"

    fresh = store.get_masking_evidence(
        "owner",
        document["document_id"],
        binding(document),
    )

    assert fresh["pages"][0]["masked_image_sha256"] == sha(
        image
    )


@pytest.mark.parametrize(
    "mode",
    ["hash", "tamper", "missing", "count", "nonbytes"],
)
def test_registration_evidence_failure(mode):
    store = ReviewStore()
    image = png()

    images = [image]
    hashes = [sha(image)]

    if mode == "hash":
        hashes = ["bad"]

    elif mode == "tamper":
        images = [image + b"changed"]

    elif mode == "missing":
        images = None

    elif mode == "count":
        images *= 2
        hashes *= 2

    else:
        images = ["not-bytes"]

    with pytest.raises(AdapterError):
        store.register(
            "owner",
            fake_ocr([]),
            "bundle",
            "no_candidates",
            masked_images=images,
            masked_hashes=hashes,
        )

    assert store.entries == {}


@pytest.mark.parametrize(
    "status",
    ["review_required", "failed", "error"],
)
def test_privacy_never_produces_usable_evidence(status):
    store = ReviewStore()
    image = png()

    registered = store.register(
        "owner",
        fake_ocr([]),
        "bundle",
        status,
        masked_images=[image],
        masked_hashes=[sha(image)],
    )

    document = store.get(
        "owner",
        registered["document_id"],
    )

    confirm(store, "owner", document)

    with pytest.raises(AdapterError):
        store.get_masking_evidence(
            "owner",
            document["document_id"],
            binding(document),
        )

    assert "masking_evidence" not in store.entries[
        document["document_id"]
    ]


@pytest.mark.parametrize(
    "mode",
    ["owner", "version", "image", "unreviewed"],
)
def test_context_binding(evidence, mode):
    store, document, _ = evidence

    context = binding(document)
    owner = "owner"

    if mode == "owner":
        owner = "other"

    elif mode == "version":
        context["document_version"] += 1

    elif mode == "image":
        context["image_sha256"] = "bad"

    else:
        store.entries[
            document["document_id"]
        ]["confirmed"].clear()

    with pytest.raises(AdapterError):
        store.get_masking_evidence(
            owner,
            document["document_id"],
            context,
        )


@pytest.mark.parametrize(
    "mode",
    ["save", "invalidate"],
)
def test_reconfirmation_cannot_revive_evidence(evidence, mode):
    store, document, _ = evidence

    if mode == "save":
        updated = store.save(
            "owner",
            document["document_id"],
            draft(document),
        )
    else:
        updated = store.invalidate(
            "owner",
            document["document_id"],
            binding(document),
        )

    confirm(store, "owner", updated)

    with pytest.raises(AdapterError):
        store.get_masking_evidence(
            "owner",
            document["document_id"],
            binding(updated),
        )

    assert "masking_evidence" not in store.entries[
        document["document_id"]
    ]


def test_scan_exception_also_invalidates_evidence(evidence):
    store, document, _ = evidence

    with patch(
        "integrations.review_store.scan_lines",
        side_effect=RuntimeError("scanner failed"),
    ):
        with pytest.raises(RuntimeError):
            store.save(
                "owner",
                document["document_id"],
                draft(document),
            )

    assert "masking_evidence" not in store.entries[
        document["document_id"]
    ]

    assert not store.entries[
        document["document_id"]
    ]["confirmed"]


def test_expired_document_removes_record(evidence):
    store, document, _ = evidence

    store.entries[
        document["document_id"]
    ]["created"] -= store.ttl + 1

    with pytest.raises(AdapterError):
        store.get_masking_evidence(
            "owner",
            document["document_id"],
            binding(document),
        )

    assert document["document_id"] not in store.entries


def test_no_evidence_without_server_images():
    store = ReviewStore()

    registered = store.register(
        "owner",
        fake_ocr([]),
        "bundle",
        "no_candidates",
    )

    document = store.get(
        "owner",
        registered["document_id"],
    )

    confirm(store, "owner", document)

    with pytest.raises(AdapterError):
        store.get_masking_evidence(
            "owner",
            document["document_id"],
            binding(document),
        )


def test_real_mask_worker_http_link_no_public_evidence(capsys):
    store = ReviewStore()
    seen = []

    def ocr(uploads):
        seen.extend(
            data
            for _, _, data in uploads
        )
        return fake_ocr(uploads)

    server = HTTPServer(
        create_app(
            store=store,
            ocr=ocr,
            privacy=lambda _: {
                "status": "no_candidates"
            },
        )
    )

    try:
        client = Client(server.base)
        original = png()

        document = client.document(original)

        # Actual worker strips PNG metadata by re-encoding.
        assert seen[0] != original

        image = Image.open(
            io.BytesIO(seen[0])
        )

        assert image.getpixel((40, 40)) == (0, 0, 0)
        assert "synthetic" not in image.info

        owner = next(
            iter(store.entries.values())
        )["owner"]

        confirm(store, owner, document)

        result = store.get_masking_evidence(
            owner,
            document["document_id"],
            binding(document),
        )

        assert result["pages"][0][
            "masked_image_sha256"
        ] == sha(seen[0])

        assert result["pages"][0][
            "masked_image_sha256"
        ] != binding(document)["image_sha256"]

        assert set(document["server_context"]) == {
            "document_version",
            "image_sha256",
            "review_challenges",
            "privacy_status",
            "analysis_approved",
            "external_llm_allowed",
            "storage",
        }

        assert "masked_image_sha256" not in json.dumps(
            document
        )

        assert client.request(
            "/api/analyze",
            {"approved": True},
        )[0] == 403

    finally:
        server.close()

    captured = capsys.readouterr()

    assert "metadata-to-remove" not in (
        captured.out + captured.err
    )


def test_idle_artifact_timer_removes_ticket():
    with patch(
        "integrations.review_app.MASK_ARTIFACT_TTL",
        0.05,
    ):
        server = HTTPServer(
            create_app(
                ocr=fake_ocr,
                privacy=lambda _: {
                    "status": "no_candidates"
                },
            )
        )

        try:
            client = Client(server.base)
            image = png()

            code, ticket = client.upload(
                "/api/masking/register",
                image,
                True,
            )

            assert code == 200

            time.sleep(0.1)

            # Timer removes idle artifacts without another request.
            result = client.upload(
                "/api/ocr",
                image,
                token=ticket["mask_ticket"],
            )

            assert result[0] == 422

        finally:
            server.close()
