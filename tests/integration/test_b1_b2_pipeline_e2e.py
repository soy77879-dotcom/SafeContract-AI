"""Real HTTP handlers + mask worker + store/gate/rules; mocked OCR/privacy.
No actual PaddleOCR or external LLM. Public analyze remains forbidden.
"""
import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from integrations.review_app import create_app
from integrations.review_store import ReviewStore, sha
from integrations.review_gate_bridge import VerifiedLocalResponseGate
from integrations.review_local_pipeline import run_local_review_analysis
from test_masking_evidence import png
from test_review_http import binding, draft


@pytest.fixture
def flow():
    gate=VerifiedLocalResponseGate();store=ReviewStore(gate_invalidator=gate.invalidate)
    seen=[]
    def ocr(uploads):
        seen.extend(data for _,_,data in uploads)
        text='임대인은 보증금을 반환하지 않는다.'
        line={'line_id':'P001_L001','text':text,'confidence':1.,'polygon':None}
        return {'document_id':'synthetic-e2e','clauses':[{'clause_id':'C001','pages':[1],'raw_text':text+'\n','source_lines':[{'page':1,**line}]}], 'ocr_pages':[{'page':1,'lines':[line]}]}
    with TestClient(create_app(store=store,ocr=ocr,privacy=lambda _: {'status':'no_candidates'}),base_url='http://localhost',client=('127.0.0.1',50000)) as client:
        csrf=client.get('/api/session').json()['csrf_token']
        headers={'origin':'http://localhost','x-review-csrf':csrf}
        image=png();files={'files':('masked-contract.png',image,'image/png')}
        r=client.post('/api/masking/register',headers=headers,files=files,data={'mask_regions':json.dumps([[{'x':30,'y':30,'width':100,'height':50}]])})
        assert r.status_code==200
        ticket=r.json()['mask_ticket']
        h={**headers,'x-mask-ticket':ticket}
        r=client.post('/api/ocr',headers=h,files=files);assert r.status_code==200
        assert client.post('/api/ocr',headers=h,files=files).status_code==422
        assert len(seen)==1 and seen[0]!=image
        doc=client.get('/api/review-documents/synthetic-e2e').json()
        yield client,headers,store,gate,doc,seen


def confirm(client,headers,doc):
    for c in doc['clauses']:
        r=client.post('/api/review-documents/'+doc['document_id']+'/confirm',headers=headers,json={**binding(doc),'clause_id':c['clause_id'],'challenge':doc['server_context']['review_challenges'][c['clause_id']],'text_sha256':sha(c['edited_text'].encode())})
        assert r.status_code==200


def analyze(flow):
    client,headers,store,gate,doc,seen=flow
    return run_local_review_analysis(store=store,gate=gate,owner=client.cookies.get('sc_review'),document_id=doc['document_id'],binding=binding(doc))


def test_http_review_to_internal_validated_risk(flow):
    client,headers,store,gate,doc,seen=flow
    assert analyze(flow)['ok'] is False
    confirm(client,headers,doc)
    with patch('socket.socket',side_effect=AssertionError('no external network')):
        result=analyze(flow)
    assert result['ok'] is True and result['external_llm_allowed'] is False
    row=result['response']['results'][0]
    assert row['risk_type']=='deposit_return' and row['possible_disadvantage']
    assert row['evidence'] in doc['clauses'][0]['edited_text']
    assert gate._responses=={} # Final response validation consumed the ticket.
    assert client.post('/api/analyze',headers=headers,json={'approved':True}).status_code==403


def test_http_edit_reconfirm_keeps_masking_policy(flow):
    client,headers,store,gate,doc,seen=flow;confirm(client,headers,doc)
    owner=client.cookies.get('sc_review')
    ticket=gate.issue_local_ticket(store=store,owner=owner,document_id=doc['document_id'],binding=binding(doc));assert ticket
    p=draft(doc);p['clauses'][0]['edited_text']='임대인은 수리비를 부담한다.'
    r=client.post('/api/review-documents/'+doc['document_id']+'/draft',headers=headers,json=p);assert r.status_code==200
    new=r.json();confirm(client,headers,new)
    assert new['clauses'][0]['raw_text']==doc['clauses'][0]['raw_text']
    assert new['server_context']['document_version']>doc['server_context']['document_version']
    result=run_local_review_analysis(store=store,gate=gate,owner=owner,document_id=new['document_id'],binding=binding(new))
    assert result['ok'] is False # Existing policy deletes masking evidence on edit.
    assert not gate.validate_response(owner,ticket['response_ticket'],'{}',image_sha256=ticket['image_sha256'],text_sha256=ticket['text_sha256'],revision=ticket['revision'])['ok']


@pytest.mark.parametrize('action', ['expire', 'invalidate'])
def test_document_change_during_final_validation_is_not_published(flow, action):
    from integrations.response_validation import validate_content
    client,headers,store,gate,doc,seen=flow;confirm(client,headers,doc)
    def expire(response,request):
        result=validate_content(response,request)
        if action=='expire':
            store.entries[doc['document_id']]['created']-=store.ttl+1
        else:
            store.invalidate(client.cookies.get('sc_review'),doc['document_id'],binding(doc))
        return result
    with patch('integrations.response_validation.validate_content',side_effect=expire):
        result=analyze(flow)
    assert result['ok'] is False and 'response' not in result
