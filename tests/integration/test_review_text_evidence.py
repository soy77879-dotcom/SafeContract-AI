"""Hash-only server evidence; synthetic fixtures, never approval gate tickets."""
import copy
from unittest.mock import patch
import pytest
from test_masking_evidence import evidence, confirm
from test_review_http import binding, draft
from integrations.review_store import sha
from integrations.adapter import AdapterError, payload_hash


def get(fixture):
    s,d,_=fixture;return s.get_review_evidence('owner',d['document_id'],binding(d))


def test_normal_separate_hashes_no_text_disclosure(evidence):
    s,d,_=evidence;e=get(evidence);c=d['clauses'][0]
    assert e['clauses'][0]['raw_text_sha256']==sha(c['raw_text'].encode())
    assert e['clauses'][0]['edited_text_sha256']==e['clauses'][0]['confirmed_text_sha256']==sha(c['edited_text'].encode())
    assert e['raw_request_sha256']==e['edited_request_sha256'] # No edit in fixture.
    assert e['analysis_approved'] is False
    assert c['raw_text'] not in str(e)
    assert 'registration_id' not in s.get('owner',d['document_id'])
    with s.review_evidence_guard('owner',d['document_id'],binding(d),e) as checked:assert checked==e


@pytest.mark.parametrize('field',['raw_text_sha256','edited_text_sha256','confirmed_text_sha256'])
def test_altered_evidence_hash_rejected(evidence,field):
    s,d,_=evidence;e=get(evidence);e['clauses'][0][field]='0'*64
    with pytest.raises(AdapterError):
        with s.review_evidence_guard('owner',d['document_id'],binding(d),e):pass


@pytest.mark.parametrize('field',['raw_text','edited_text','clause_id','page'])
def test_live_source_or_edit_tamper(evidence,field):
    s,d,_=evidence;s.entries[d['document_id']]['data']['clauses'][0][field]=2 if field=='page' else 'changed'
    with pytest.raises(AdapterError):get(evidence)


def test_both_source_copies_modified_still_rejected(evidence):
    s,d,_=evidence;r=s.entries[d['document_id']]
    for k in ['source','data']:r[k]['clauses'][0]['raw_text']='changed'
    with pytest.raises(AdapterError):get(evidence)


@pytest.mark.parametrize('mode',['unconfirmed','owner','version','image','privacy','missing_mask','expired'])
def test_required_context(evidence,mode):
    s,d,_=evidence;b=binding(d);owner='owner';r=s.entries[d['document_id']]
    if mode=='unconfirmed':r['confirmed'].clear()
    elif mode=='owner':owner='other'
    elif mode=='version':b['document_version']+=1
    elif mode=='image':b['image_sha256']='changed'
    elif mode=='privacy':r['privacy']='review_required'
    elif mode=='missing_mask':r.pop('masking_evidence')
    else:r['created']-=s.ttl+1
    with pytest.raises(AdapterError):s.get_review_evidence(owner,d['document_id'],b)


@pytest.mark.parametrize('action',['save','invalidate'])
def test_old_evidence_after_reconfirmation(evidence,action):
    s,d,_=evidence;e=get(evidence)
    if action=='save':
        p=draft(d);p['clauses'][0]['edited_text']='임대인은 수선비를 부담한다.'
        new=s.save('owner',d['document_id'],p)
    else:new=s.invalidate('owner',d['document_id'],binding(d))
    confirm(s,'owner',new)
    with pytest.raises(AdapterError):
        with s.review_evidence_guard('owner',d['document_id'],binding(new),e):pass
    # Keep existing masking policy: text reconfirmation is NOT renewed image evidence.
    with pytest.raises(AdapterError):s.get_review_evidence('owner',d['document_id'],binding(new))


def test_reentrant_change_during_guard_rejected(evidence):
    s,d,_=evidence;e=get(evidence)
    with pytest.raises(AdapterError):
        with s.review_evidence_guard('owner',d['document_id'],binding(d),e):s.invalidate('owner',d['document_id'],binding(d))


def test_scan_failure_no_evidence(evidence):
    with patch('integrations.review_store.scan_lines',side_effect=RuntimeError('synthetic@example.invalid')):
        with pytest.raises(AdapterError) as exc:get(evidence)
    assert 'synthetic@example.invalid' not in str(exc.value)


def test_evidence_is_copy(evidence):
    e=get(evidence);e['masking_evidence']['pages'][0]['masked_image_sha256']='bad'
    assert get(evidence)['masking_evidence']['pages'][0]['masked_image_sha256']!='bad'
