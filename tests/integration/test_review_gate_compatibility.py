"""Compatibility audit only. No invented production processor or approval record."""
import hashlib
import json
from unittest.mock import patch
import pytest
from test_review_rule_analysis import reviewed
from integrations.review_analysis import analyze_reviewed_rules, analyze_rule_snapshot
from integrations.response_validation import ResponseValidationGate, parse_response, validate_content
from integrations.adapter import AdapterError


def test_existing_final_content_validators_are_used(reviewed):
    store,doc,binding=reviewed
    with patch('integrations.result_merge.parse_response',wraps=parse_response) as parse, patch('integrations.result_merge.validate_content',wraps=validate_content) as validate:
        candidate=analyze_reviewed_rules(store,'owner',doc,binding)
    parse.assert_called_once();validate.assert_called_once()
    assert candidate.publication_allowed is False
    request=validate.call_args.args[1]
    assert request['document_id']==doc
    assert [(x['clause_id'],x['page']) for x in request['clauses']]==[('C001',1),('C002',2)]


def test_current_store_has_no_gate_image_or_receipt(reviewed):
    store,doc,binding=reviewed;entry=store.entries[doc]
    assert 'image_hash' in entry and 'confirmed_hashes' in entry
    assert not {'masked_image','images','receipt_id','response_ticket','ocr_lines'} & set(entry)
    assert ResponseValidationGate().prepare('owner',doc,binding['document_version'],b'synthetic') is None


def test_upload_bundle_hash_is_not_single_canonical_image_hash():
    # Exact algorithms in review_app.images_hash and TransferGate.digest.
    upload=b'\x89PNG\r\n\x1a\nsynthetic-upload'
    canonical=b'\x89PNG\r\n\x1a\nsynthetic-canonical'
    bundle=hashlib.sha256(hashlib.sha256(upload).digest()).hexdigest()
    assert bundle!=hashlib.sha256(upload).hexdigest()
    assert bundle!=hashlib.sha256(canonical).hexdigest()


@pytest.mark.parametrize('ticket_kind',['analysis_token','fabricated','missing'])
def test_valid_candidate_cannot_supply_missing_approval(reviewed,ticket_kind):
    store,doc,binding=reviewed;snapshot=store.get_analysis_input('owner',doc,binding)
    candidate=analyze_rule_snapshot(store,'owner',doc,binding,snapshot)
    gate=ResponseValidationGate()
    ticket={'analysis_token':snapshot['analysis_token'],'fabricated':'not-issued','missing':None}[ticket_kind]
    for _ in range(2):
        result=gate.validate_response('owner',ticket,json.dumps(candidate.candidate_response.model_dump()),
            image_sha256=binding['image_sha256'],text_sha256=hashlib.sha256('\n'.join(x['text'] for x in snapshot['request']['clauses']).encode()).hexdigest(),revision=binding['document_version'])
        assert result['ok'] is False and result['internal_reason']=='unapproved_response'
        assert 'response' not in result


def test_latest_confirmed_text_does_not_prove_original_ocr_hash(reviewed):
    store,doc,binding=reviewed;d=store.get('owner',doc)
    original='\n'.join(x['raw_text'] for x in d['clauses'])
    incoming=[{k:c[k] for k in ('clause_id','raw_text','edited_text')} for c in d['clauses']]
    incoming[0]['edited_text']='임대인은 보증금을 종료 시 반환한다.'
    store.save('owner',doc,{**binding,'clauses':incoming})
    edited='\n'.join(x['edited_text'] for x in store.get('owner',doc)['clauses'])
    assert hashlib.sha256(original.encode()).digest()!=hashlib.sha256(edited.encode()).digest()
    assert store.entries[doc]['confirmed_hashes']=={}


def test_rejected_final_content_prevents_candidate_return(reviewed):
    store,doc,binding=reviewed
    from integrations.response_validation import Rejected
    with patch('integrations.result_merge.validate_content',side_effect=Rejected('evidence_mismatch')):
        with pytest.raises(AdapterError):analyze_reviewed_rules(store,'owner',doc,binding)
    assert store.entries[doc]['analysis_token'] is None
