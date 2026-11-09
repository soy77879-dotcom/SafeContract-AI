"""Server-internal bridge tests: synthetic text, no OCR or external transport."""
import copy
import threading
from unittest.mock import patch
import pytest
from backend.schemas import AnalyzeRequest
from integrations.adapter import AdapterError
from integrations.review_store import ReviewStore, sha


def structured():
    texts=['임대인은 수리비를 부담한다.', '계약 종료 시 보증금을 반환한다.']
    return {'document_id':'synthetic-document','clauses':[
        {'clause_id':f'C{i:03}', 'pages':[i], 'raw_text':text, 'source_lines':[]}
        for i,text in enumerate(texts,1)],
        'ocr_pages':[{'page':i,'lines':[]} for i in range(1,3)]}


def binding(doc):
    ctx=doc['server_context']
    return {'document_id':doc['document_id'],'document_version':ctx['document_version'],'image_sha256':ctx['image_sha256']}


@pytest.fixture
def ready():
    store=ReviewStore();store.register('owner',structured(),sha(b'synthetic-masked-image'),'no_candidates')
    doc=store.get('owner','synthetic-document')
    for c in doc['clauses']:
        store.confirm('owner',doc['document_id'],{**binding(doc),'clause_id':c['clause_id'],
            'challenge':doc['server_context']['review_challenges'][c['clause_id']], 'text_sha256':sha(c['edited_text'].encode())})
    return store,doc,binding(doc)


def fetch(ready):
    s,d,b=ready
    return s.get_analysis_input('owner',d['document_id'],b)


def test_success_exact_final_input(ready):
    s,d,b=ready;snap=fetch(ready)
    assert AnalyzeRequest.model_validate(snap['request']).document_id==d['document_id']
    assert snap['request']['clauses']==[{'clause_id':c['clause_id'],'page':c['page'],'text':c['edited_text']} for c in d['clauses']]
    with s.analysis_input_guard('owner',d['document_id'],b,snap) as request:
        assert request.model_dump()==snap['request']
    assert s.get('owner',d['document_id'])['server_context']['analysis_approved'] is False
    with pytest.raises(AdapterError):
        with s.analysis_input_guard('owner',d['document_id'],b,snap):pass


@pytest.mark.parametrize('field,value',[('document_id','other'),('document_version',2),('document_version',True),('image_sha256','bad')])
def test_bad_binding(ready,field,value):
    s,d,b=ready;b[field]=value
    with pytest.raises(AdapterError):fetch(ready)


def test_other_owner(ready):
    s,d,b=ready
    with pytest.raises(AdapterError):s.get_analysis_input('other',d['document_id'],b)


@pytest.mark.parametrize('flag',['approved','reviewed','analysis_approved'])
def test_fake_flags_cannot_approve(ready,flag):
    s,d,b=ready;s.entries[d['document_id']]['confirmed'].clear();b[flag]=True
    with pytest.raises(AdapterError):fetch(ready)


def test_partial_confirmation(ready):
    s,d,b=ready;s.entries[d['document_id']]['confirmed'].remove('C002')
    with pytest.raises(AdapterError):fetch(ready)


@pytest.mark.parametrize('status',['review_required','error','pending',None])
def test_privacy_state_blocks(ready,status):
    s,d,b=ready;s.entries[d['document_id']]['privacy']=status
    with pytest.raises(AdapterError):fetch(ready)


@pytest.mark.parametrize('scan',[{'status':'review_required','found':True},{'status':'error'}, {'status':'no_candidates','found':True},{}])
def test_rescan_blocks(ready,scan):
    with patch('integrations.review_store.scan_lines',return_value=scan),pytest.raises(AdapterError):fetch(ready)


def test_scan_error_safe_no_logs(ready,capsys):
    with patch('integrations.review_store.scan_lines',side_effect=RuntimeError('synthetic@example.invalid')):
        with pytest.raises(AdapterError) as exc:fetch(ready)
    assert 'synthetic@example.invalid' not in str(exc.value)
    assert capsys.readouterr()==('','')


@pytest.mark.parametrize('field,value',[('page',2),('pages',[2]),('raw_text','changed'),('clause_id','C003'),('edited_text','changed')])
def test_server_shape_or_confirmed_text_drift(ready,field,value):
    s,d,b=ready;s.entries[d['document_id']]['data']['clauses'][0][field]=value
    with pytest.raises(AdapterError):fetch(ready)


@pytest.mark.parametrize('action',['save','invalidate','expire','image','version'])
def test_old_snapshot_rejected(ready,action):
    s,d,b=ready;snap=fetch(ready)
    if action=='save':
        s.save('owner',d['document_id'],{**b,'clauses':[{k:c[k] for k in ('clause_id','raw_text','edited_text')} for c in d['clauses']]})
    elif action=='invalidate':s.invalidate('owner',d['document_id'],b)
    elif action=='expire':s.entries[d['document_id']]['created']-=s.ttl+1
    elif action=='image':s.entries[d['document_id']]['image_hash']='changed'
    else:s.entries[d['document_id']]['version']+=1
    with pytest.raises(AdapterError):
        with s.analysis_input_guard('owner',d['document_id'],b,snap):pass


def test_edited_text_used_after_reconfirmation(ready):
    s,d,b=ready;incoming=[{k:c[k] for k in ('clause_id','raw_text','edited_text')} for c in d['clauses']]
    incoming[0]['edited_text']='임대인은 수선 비용을 부담한다.'
    updated=s.save('owner',d['document_id'],{**b,'clauses':incoming})
    with pytest.raises(AdapterError):s.get_analysis_input('owner',d['document_id'],binding(updated))
    for c in updated['clauses']:
        s.confirm('owner',d['document_id'],{**binding(updated),'clause_id':c['clause_id'],'challenge':updated['server_context']['review_challenges'][c['clause_id']],'text_sha256':sha(c['edited_text'].encode())})
    result=s.get_analysis_input('owner',d['document_id'],binding(updated))
    assert result['request']['clauses'][0]['text']==incoming[0]['edited_text']
    assert s.get('owner',d['document_id'])['clauses'][0]['raw_text']==d['clauses'][0]['raw_text']


def test_actual_private_edit_blocks_after_confirmation(ready):
    s,d,b=ready;c=s.entries[d['document_id']]['data']['clauses'][0]
    c['edited_text']='synthetic@example.invalid'
    s.entries[d['document_id']]['confirmed_hashes']['C001']=sha(c['edited_text'].encode())
    with pytest.raises(AdapterError):fetch(ready)


def test_tampered_snapshot(ready):
    s,d,b=ready;snap=fetch(ready);snap['request']['clauses'][0]['text']='changed'
    with pytest.raises(AdapterError):
        with s.analysis_input_guard('owner',d['document_id'],b,snap):pass
    assert s.get('owner',d['document_id'])['clauses'][0]['edited_text']==d['clauses'][0]['edited_text']


def test_concurrent_invalidation_rejects_old_work(ready):
    s,d,b=ready;snap=fetch(ready)
    thread=threading.Thread(target=s.invalidate,args=('owner',d['document_id'],b))
    thread.start();thread.join(timeout=2);assert not thread.is_alive()
    with pytest.raises(AdapterError):
        with s.analysis_input_guard('owner',d['document_id'],b,snap):pass


def test_guard_serializes_invalidation(ready):
    s,d,b=ready;snap=fetch(ready);started=threading.Event();done=threading.Event()
    def invalidate():
        started.set();s.invalidate('owner',d['document_id'],b);done.set()
    with s.analysis_input_guard('owner',d['document_id'],b,snap):
        thread=threading.Thread(target=invalidate);thread.start();assert started.wait(2)
        assert not done.wait(.05)
    thread.join(2);assert done.is_set()


def test_reentrant_invalidation_rejected_on_exit(ready):
    s,d,b=ready;snap=fetch(ready)
    with pytest.raises(AdapterError):
        with s.analysis_input_guard('owner',d['document_id'],b,snap):s.invalidate('owner',d['document_id'],b)
