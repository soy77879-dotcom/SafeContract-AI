
"""Development-only, session-owned memory store. No analysis approval is issued."""

import copy
import hashlib
import secrets
import threading
import time
from contextlib import contextmanager

from backend.schemas import AnalyzeRequest
from integrations.adapter import (
    AdapterError,
    ocr_response,
    payload_hash,
    validate_upload,
)
from integrations.clause_review import build_review_document
from integrations.privacy_detection import scan_lines


def reject(code='VALIDATION_ERROR', status=422):
    raise AdapterError(
        status,
        code,
        '문서·버전·검토 입력을 확인하세요.',
    )


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ReviewStore:

    def __init__(self, ttl=3600, gate_invalidator=None):
        self.entries = {}
        self.ttl = ttl
        self.lock = threading.RLock()
        self._gate_invalidator = gate_invalidator

    def _invalidate_gate(self, owner, doc):
        """Revoke gate tickets before changing document state."""
        if self._gate_invalidator is None:
            return

        try:
            self._gate_invalidator(owner, doc)
        except Exception:
            reject('PRIVACY_CHECK_FAILED', 403)

    def _get(self, owner, doc):
        """Return an owned, unexpired document. Caller holds self.lock."""
        r = self.entries.get(doc)

        if not r or r['owner'] != owner:
            reject(status=404)

        if time.monotonic() - r['created'] > self.ttl:
            # B-1: Revoke tickets before deleting an expired document.
            # A gate failure blocks the deletion.
            self._invalidate_gate(owner, doc)
            self.entries.pop(doc, None)
            reject(status=410)

        return r

    def _reset(self, r):
        r['version'] += 1
        r['confirmed'] = set()
        r['challenges'] = {
            c['clause_id']: secrets.token_urlsafe(32)
            for c in r['data']['clauses']
        }
        r['confirmed_hashes'] = {}
        r['analysis_token'] = None
        r.pop('masking_evidence', None)

    def register(
        self,
        owner,
        structured,
        image_hash,
        privacy,
        *,
        masked_images=None,
        masked_hashes=None,
    ):
        # Trusted server hook only.
        # Hashes must come from mask verification, never request fields.
        # No image bytes are retained in this store or its API view.

        api = ocr_response(structured).model_dump()

        data = build_review_document(
            structured,
            {
                'document_id': structured['document_id'],
                'pages': structured['ocr_pages'],
            },
            api,
        )

        evidence = None

        if masked_images is not None or masked_hashes is not None:
            if (
                not isinstance(masked_images, (list, tuple))
                or not isinstance(masked_hashes, (list, tuple))
                or len(masked_images) != data['page_count']
                or len(masked_images) != len(masked_hashes)
                or not 1 <= len(masked_images) <= 5
            ):
                reject('PRIVACY_CHECK_FAILED')

            for image, expected in zip(masked_images, masked_hashes):
                if not isinstance(image, bytes) or sha(image) != expected:
                    reject('PRIVACY_CHECK_FAILED')

                validate_upload(
                    'masked-contract.png',
                    'image/png',
                    image,
                )

            if privacy == 'no_candidates':
                evidence = {
                    'document_id': api['document_id'],
                    'upload_bundle_sha256': image_hash,
                    'pages': [
                        {
                            'page': i,
                            'masked_image_sha256': sha(image),
                        }
                        for i, image in enumerate(masked_images, 1)
                    ],
                    'provenance': 'server_mask_verified_ocr_input',
                    'privacy_status': 'no_candidates',
                    'analysis_approved': False,
                    'external_llm_allowed': False,
                }

        with self.lock:
            # B-1: Identify expired entries before changing store contents.
            now = time.monotonic()

            expired = [
                (doc_id, entry)
                for doc_id, entry in self.entries.items()
                if now - entry['created'] >= self.ttl
            ]

            # Revoke all expired document tickets first.
            # If any revocation fails, keep the records unchanged.
            for doc_id, entry in expired:
                self._invalidate_gate(entry['owner'], doc_id)

            for doc_id, _ in expired:
                self.entries.pop(doc_id, None)

            document_id = api['document_id']
            existing = self.entries.get(document_id)

            if existing is not None:
                # A different owner must not replace a live document.
                if existing['owner'] != owner:
                    reject(status=409)

                # B-1: Revoke old tickets before replacing the document.
                self._invalidate_gate(owner, document_id)

            elif len(self.entries) >= 20:
                reject(status=503)

            r = {
                'owner': owner,
                'created': time.monotonic(),
                'data': data,
                'image_hash': image_hash,
                'version': 0,
                'privacy': privacy,
                'confirmed': set(),
                'source': copy.deepcopy(data),
                'source_hash': payload_hash(data),
                'registration_id': secrets.token_urlsafe(32),
                'ocr_pages_hash': payload_hash(structured['ocr_pages']),
            }

            self._reset(r)

            if evidence is not None:
                evidence['document_version'] = r['version']
                r['masking_evidence'] = evidence

            self.entries[document_id] = r

        return api

    def get_masking_evidence(self, owner, doc, binding):
        """Internal metadata only, valid for the exact reviewed revision.

        Not an approval ticket. After edit/invalidation require a new
        verified OCR registration; re-confirmation alone cannot revive
        historical masking evidence.
        """
        with self.lock:
            r, _ = self._analysis_request(owner, doc, binding)
            evidence = r.get('masking_evidence')

            if (
                not evidence
                or evidence['document_id'] != doc
                or evidence['document_version'] != r['version']
                or evidence['upload_bundle_sha256'] != r['image_hash']
            ):
                reject('PRIVACY_CHECK_FAILED', 403)

            return copy.deepcopy(evidence)

    def get_review_evidence(self, owner, doc, binding):
        """Server-only hash evidence, not a TransferGate receipt.

        Raw clauses, OCR page payload and edited request have separate
        hashes. Missing or invalid masking evidence fails closed.
        """
        with self.lock:
            r, request = self._analysis_request(owner, doc, binding)
            masking = self.get_masking_evidence(owner, doc, binding)

            rows = [
                {
                    'clause_id': c['clause_id'],
                    'page': c['page'],
                    'pages': list(c['pages']),
                    'raw_text_sha256': sha(c['raw_text'].encode()),
                    'edited_text_sha256': sha(c['edited_text'].encode()),
                    'confirmed_text_sha256': (
                        r['confirmed_hashes'][c['clause_id']]
                    ),
                }
                for c in r['data']['clauses']
            ]

            raw = {
                'document_id': doc,
                'clauses': [
                    {
                        'clause_id': c['clause_id'],
                        'page': c['page'],
                        'text': c['raw_text'],
                    }
                    for c in r['data']['clauses']
                ],
            }

            return {
                'format': 'server-review-evidence-v1',
                'registration_id': r['registration_id'],
                'document_id': doc,
                'document_version': r['version'],
                'image_sha256': r['image_hash'],
                'masking_evidence': masking,
                'clauses': rows,
                'ocr_pages_sha256': r['ocr_pages_hash'],
                'raw_request_sha256': payload_hash(raw),
                'edited_request_sha256': payload_hash(
                    request.model_dump()
                ),
                'privacy_status': 'no_candidates',
                'analysis_approved': False,
                'external_llm_allowed': False,
            }

    @contextmanager
    def review_evidence_guard(self, owner, doc, binding, evidence):
        """Recheck review evidence before and after internal use.

        This is not a one-use approval ticket. Result handling must
        also use the analysis input guard and existing validation gate.
        """
        with self.lock:
            current = self.get_review_evidence(owner, doc, binding)

            if not isinstance(evidence, dict) or evidence != current:
                reject(status=409)

            yield copy.deepcopy(current)

            if self.get_review_evidence(owner, doc, binding) != current:
                reject(status=409)

    def get(self, owner, doc):
        with self.lock:
            r = self._get(owner, doc)
            d = copy.deepcopy(r['data'])

            for c in d['clauses']:
                c['status'] = (
                    'user_confirmed'
                    if c['clause_id'] in r['confirmed']
                    else 'needs_review'
                )
                c['reviewed_by_user'] = (
                    c['clause_id'] in r['confirmed']
                )

            d['server_context'] = {
                'document_version': r['version'],
                'image_sha256': r['image_hash'],
                'review_challenges': dict(r['challenges']),
                'privacy_status': r['privacy'],
                'analysis_approved': False,
                'external_llm_allowed': False,
                'storage': 'development_memory',
            }

            return d

    def _binding(self, r, payload, doc):
        if (
            payload.get('document_id') != doc
            or type(payload.get('document_version')) is not int
            or payload['document_version'] != r['version']
            or payload.get('image_sha256') != r['image_hash']
        ):
            reject('VALIDATION_ERROR', 409)

    def invalidate(self, owner, doc, payload):
        with self.lock:
            r = self._get(owner, doc)
            self._binding(r, payload, doc)

            # Revoke gate tickets before resetting review state.
            self._invalidate_gate(owner, doc)

            self._reset(r)

            return self.get(owner, doc)

    def save(self, owner, doc, payload):
        with self.lock:
            r = self._get(owner, doc)
            self._binding(r, payload, doc)

            if (
                set(payload) != {
                    'document_id',
                    'document_version',
                    'image_sha256',
                    'clauses',
                }
                or not isinstance(payload['clauses'], list)
            ):
                reject()

            original = r['data']['clauses']
            incoming = payload['clauses']

            if (
                [
                    c.get('clause_id')
                    for c in incoming
                    if isinstance(c, dict)
                ] != [
                    c['clause_id']
                    for c in original
                ]
                or len(incoming) != len(original)
            ):
                reject()

            for saved, c in zip(original, incoming):
                if (
                    set(c) != {
                        'clause_id',
                        'raw_text',
                        'edited_text',
                    }
                    or c['raw_text'] != saved['raw_text']
                    or not isinstance(c['edited_text'], str)
                    or not c['edited_text'].strip()
                    or len(c['edited_text']) > 50000
                ):
                    reject()

            # Revoke tickets after validation, before mutation.
            self._invalidate_gate(owner, doc)

            # Invalidate review evidence before mutation and scanning.
            self._reset(r)

            for saved, c in zip(original, incoming):
                saved['edited_text'] = c['edited_text']

            status = scan_lines(
                [
                    {
                        'text': c['edited_text'],
                        'confidence': 1.0,
                    }
                    for c in original
                ]
            )['status']

            r['privacy'] = (
                'review_required'
                if (
                    r['privacy'] != 'no_candidates'
                    or status != 'no_candidates'
                )
                else 'no_candidates'
            )

            return self.get(owner, doc)

    def confirm(self, owner, doc, payload):
        with self.lock:
            r = self._get(owner, doc)
            self._binding(r, payload, doc)

            if set(payload) != {
                'document_id',
                'document_version',
                'image_sha256',
                'clause_id',
                'challenge',
                'text_sha256',
            }:
                reject()

            cid = payload['clause_id']

            c = next(
                (
                    c
                    for c in r['data']['clauses']
                    if c['clause_id'] == cid
                ),
                None,
            )

            if (
                not c
                or not r['challenges'].get(cid)
                or not secrets.compare_digest(
                    r['challenges'][cid],
                    str(payload['challenge']),
                )
                or sha(c['edited_text'].encode())
                != payload['text_sha256']
            ):
                reject(status=409)

            r['challenges'].pop(cid)
            r['confirmed'].add(cid)
            r['confirmed_hashes'][cid] = sha(
                c['edited_text'].encode()
            )

            return self.get(owner, doc)

    def _analysis_request(self, owner, doc, binding):
        """Caller holds lock. Never accept client text or approval flags."""
        r = self._get(owner, doc)

        if (
            not isinstance(binding, dict)
            or set(binding) != {
                'document_id',
                'document_version',
                'image_sha256',
            }
        ):
            reject()

        self._binding(r, binding, doc)

        source = r['source']
        data = r['data']
        clauses = data['clauses']

        if payload_hash(source) != r['source_hash']:
            reject(status=409)

        if data['document_id'] != doc:
            reject(status=409)

        if source['document_id'] != doc:
            reject(status=409)

        ids = [
            c['clause_id']
            for c in source['clauses']
        ]

        if (
            not ids
            or len(ids) != len(set(ids))
            or data['expected_clause_ids'] != ids
            or [c['clause_id'] for c in clauses] != ids
        ):
            reject(status=409)

        if (
            r['confirmed'] != set(ids)
            or set(r['confirmed_hashes']) != set(ids)
        ):
            reject(status=403)

        for original, c in zip(source['clauses'], clauses):
            if any(
                c[k] != original[k]
                for k in (
                    'clause_id',
                    'page',
                    'pages',
                    'raw_text',
                    'source_lines',
                )
            ):
                reject(status=409)

            if (
                not isinstance(c['edited_text'], str)
                or not c['edited_text'].strip()
                or sha(c['edited_text'].encode())
                != r['confirmed_hashes'][c['clause_id']]
            ):
                reject(status=409)

        if r['privacy'] != 'no_candidates':
            reject('PRIVACY_CHECK_FAILED', 403)

        try:
            scanned = scan_lines(
                [
                    {
                        'text': c['edited_text'],
                        'confidence': 1.0,
                    }
                    for c in clauses
                ]
            )
        except Exception:
            reject('PRIVACY_CHECK_FAILED', 403)

        if (
            not isinstance(scanned, dict)
            or scanned.get('status') != 'no_candidates'
            or scanned.get('found') is not False
        ):
            reject('PRIVACY_CHECK_FAILED', 403)

        try:
            request = AnalyzeRequest.model_validate(
                {
                    'document_id': doc,
                    'clauses': [
                        {
                            'clause_id': c['clause_id'],
                            'page': c['page'],
                            'text': c['edited_text'],
                        }
                        for c in clauses
                    ],
                },
                strict=True,
            )
        except Exception:
            reject()

        return r, request

    def get_analysis_input(self, owner, doc, binding):
        """Internal only: caller must provide an authenticated owner.

        Returns detached AnalyzeRequest data and a one-use server token.
        This does not grant analysis or external LLM approval.
        """
        with self.lock:
            r, request = self._analysis_request(
                owner,
                doc,
                binding,
            )

            token = secrets.token_urlsafe(32)

            r['analysis_token'] = (
                token,
                payload_hash(request.model_dump()),
            )

            return {
                'request': request.model_dump(),
                'analysis_token': token,
            }

    @contextmanager
    def analysis_input_guard(
        self,
        owner,
        doc,
        binding,
        snapshot,
    ):
        """One-use stale-input guard for internal result validation.

        Hold the lock through local result validation only.
        Do not run network operations or OCR inside this context.
        Do not publish results until the context exits cleanly.

        Input freshness is not an analysis or LLM approval.
        """
        with self.lock:
            r = self._get(owner, doc)
            receipt = r.get('analysis_token')
            r['analysis_token'] = None

            if (
                not isinstance(snapshot, dict)
                or set(snapshot) != {
                    'request',
                    'analysis_token',
                }
                or not receipt
            ):
                reject(status=409)

            if snapshot['analysis_token'] != receipt[0]:
                reject(status=409)

            _, request = self._analysis_request(
                owner,
                doc,
                binding,
            )

            if (
                snapshot['request'] != request.model_dump()
                or payload_hash(request.model_dump()) != receipt[1]
            ):
                reject(status=409)

            yield request.model_copy(deep=True)

            # Catch expiry or reentrant edits during validation.
            _, current = self._analysis_request(
                owner,
                doc,
                binding,
            )

            if payload_hash(current.model_dump()) != receipt[1]:
                reject(status=409)
