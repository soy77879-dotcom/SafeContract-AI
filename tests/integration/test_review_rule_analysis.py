"""Actual unchanged rule engine on synthetic, server-confirmed clauses."""
from unittest.mock import patch
import threading
import pytest
from integrations.adapter import AdapterError
from integrations.review_store import ReviewStore, sha
from integrations.review_analysis import analyze_reviewed_rules, analyze_rule_snapshot
from scripts.risk_rules import analyze_document


@pytest.fixture
def reviewed():
    store=ReviewStore();doc='synthetic-rules'
    texts=['임대인은 보증금을 반환하지 않는다.', '임대인은 수리비를 부담한다.']
    structured={'document_id':doc,'clauses':[{'clause_id':f'C{i:03}', 'pages':[i], 'raw_text':t,'source_lines':[]} for i,t in enumerate(texts,1)],'ocr_pages':[{'page':i,'lines':[]} for i in (1,2)]}
    store.register('owner',structured,sha(b'synthetic-masked'),'no_candidates')
    d=store.get('owner',doc);ctx=d['server_context']
    binding={'document_id':doc,'document_version':ctx['document_version'],'image_sha256':ctx['image_sha256']}
    for c in d['clauses']:
        store.confirm('owner',doc,{**binding,'clause_id':c['clause_id'],'challenge':ctx['review_challenges'][c['clause_id']],'text_sha256':sha(c['edited_text'].encode())})
    return store,doc,binding


def run(fixture):
    s,d,b=fixture;return analyze_reviewed_rules(s,'owner',d,b)


def test_actual_rule_risk_evidence_and_harm(reviewed):
    candidate=run(reviewed);response=candidate.candidate_response
    risk=next(r for r in response.results if r.clause_id=='C001')
    assert risk.risk_type=='deposit_return' and risk.risk_status=='potential_risk'
    assert risk.evidence=='임대인은 보증금을 반환하지 않는다.'
    assert risk.possible_disadvantage and risk.question and risk.recommended_action
    assert candidate.publication_allowed is False and candidate.external_llm_allowed is False
    assert candidate.approval_status=='blocked_response_gate_not_bound'
    assert risk.evidence not in repr(candidate)


@pytest.mark.parametrize('field,value',[('document_version',99),('image_sha256','bad'),('document_id','other'),('approved',True)])
def test_invalid_binding(reviewed,field,value):
    s,d,b=reviewed;b[field]=value
    with patch('integrations.review_analysis.analyze_document') as engine:
        with pytest.raises(AdapterError):run(reviewed)
        engine.assert_not_called()


def test_unreviewed_blocks_engine(reviewed):
    s,d,b=reviewed;s.entries[d]['confirmed'].remove('C001')
    with patch('integrations.review_analysis.analyze_document') as engine:
        with pytest.raises(AdapterError):run(reviewed)
        engine.assert_not_called()


def test_other_session(reviewed):
    s,d,b=reviewed
    with pytest.raises(AdapterError):analyze_reviewed_rules(s,'other',d,b)


def test_modified_snapshot_blocked_before_analysis(reviewed):
    s,d,b=reviewed;snapshot=s.get_analysis_input('owner',d,b);snapshot['request']['clauses'][0]['text']='changed'
    with patch('integrations.review_analysis.analyze_document') as engine:
        with pytest.raises(AdapterError):analyze_rule_snapshot(s,'owner',d,b,snapshot)
        engine.assert_not_called()


@pytest.mark.parametrize('status',['review_required','error'])
def test_privacy_failure(reviewed,status):
    with patch('integrations.review_store.scan_lines',return_value={'status':status}):
        with pytest.raises(AdapterError):run(reviewed)


def test_scanner_exception_no_leak(reviewed,capsys):
    with patch('integrations.review_store.scan_lines',side_effect=ValueError('synthetic@example.invalid')):
        with pytest.raises(AdapterError) as e:run(reviewed)
    assert 'synthetic@example.invalid' not in str(e.value)
    assert capsys.readouterr()==('','')


@pytest.mark.parametrize('change',['invalidate','expire'])
def test_change_during_engine_discards_result(reviewed,change):
    s,d,b=reviewed
    def engine(request,review_ids):
        result=analyze_document(request,review_ids)
        if change=='invalidate':s.invalidate('owner',d,b)
        else:s.entries[d]['created']-=s.ttl+1
        return result
    with patch('integrations.review_analysis.analyze_document',side_effect=engine):
        with pytest.raises(AdapterError):run(reviewed)


def test_token_replay(reviewed):
    s,d,b=reviewed;snapshot=s.get_analysis_input('owner',d,b)
    analyze_rule_snapshot(s,'owner',d,b,snapshot)
    with pytest.raises(AdapterError):analyze_rule_snapshot(s,'owner',d,b,snapshot)


@pytest.mark.parametrize('corruption',['evidence','text','page','missing','private_result'])
def test_invalid_rule_result_blocks_entire_candidate(reviewed,corruption):
    def engine(request,review_ids):
        result=analyze_document(request,review_ids);row=result['clauses'][0]
        if corruption=='evidence':row['findings'][0]['evidence']='원문에 없는 문장'
        elif corruption=='text':row['analysis_text']='다른 문장'
        elif corruption=='page':row['page']=99
        elif corruption=='missing':result['clauses'].pop()
        else:row['findings'][0]['reason']='synthetic@example.invalid'
        return result
    with patch('integrations.review_analysis.analyze_document',side_effect=engine):
        with pytest.raises(AdapterError):run(reviewed)


def test_final_edited_text_and_ids_forwarded(reviewed):
    s,d,b=reviewed;doc=s.get('owner',d)
    clauses=[{k:c[k] for k in ('clause_id','raw_text','edited_text')} for c in doc['clauses']]
    clauses[0]['edited_text']='임대인은 보증금을 계약 종료와 동시에 반환한다.'
    updated=s.save('owner',d,{**b,'clauses':clauses});b['document_version']=updated['server_context']['document_version']
    for c in updated['clauses']:
        s.confirm('owner',d,{**b,'clause_id':c['clause_id'],'challenge':updated['server_context']['review_challenges'][c['clause_id']],'text_sha256':sha(c['edited_text'].encode())})
    with patch('integrations.review_analysis.analyze_document',wraps=analyze_document) as engine:
        candidate=run(reviewed)
    request=engine.call_args.args[0]
    assert engine.call_args.kwargs['review_ids']==['C001','C002']
    assert request['clauses']==[{'clause_id':c['clause_id'],'page':c['page'],'text':c['edited_text']} for c in updated['clauses']]
    assert candidate.candidate_response.results[0].risk_status=='no_risk_detected'


def test_no_network_or_approval_ticket_creation(reviewed):
    with patch('socket.socket',side_effect=AssertionError('network forbidden')),patch('integrations.response_validation.ResponseValidationGate.prepare',side_effect=AssertionError('no fabricated receipts')),patch('integrations.response_validation.ResponseValidationGate.begin_analysis_mock',side_effect=AssertionError('no fabricated tickets')):
        assert run(reviewed).publication_allowed is False


def test_lock_held_through_response_validation(reviewed):
    from integrations.result_merge import prepare_rule_response
    s,d,b=reviewed;started=threading.Event();done=threading.Event();threads=[]
    def change():
        started.set();s.invalidate('owner',d,b);done.set()
    def validate(request,result):
        t=threading.Thread(target=change);threads.append(t);t.start()
        assert started.wait(2) and not done.wait(.05)
        return prepare_rule_response(request,result)
    with patch('integrations.review_analysis.prepare_rule_response',side_effect=validate):
        assert run(reviewed).publication_allowed is False
    for t in threads:t.join(2)
    assert done.is_set()
