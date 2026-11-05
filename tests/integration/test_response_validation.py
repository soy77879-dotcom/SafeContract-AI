"""Synthetic responses and trusted review mocks; no actual LLM or human approval."""
import contextlib
import copy
import io
import json
import socket
import unittest
from unittest.mock import patch
from backend.schemas import AnalyzeResponse, ErrorResponse
from integrations.response_validation import ResponseValidationGate, MAX_RESPONSE_BYTES, MAX_RESULTS

SOURCE=b'\x89PNG\r\n\x1a\nsynthetic-original'
IMAGE=b'\x89PNG\r\n\x1a\nsynthetic-masked'
REQUEST={'document_id':'synthetic_contract','clauses':[
    {'clause_id':'C001','page':1,'text':'임대인은 수리비를 부담한다.'},
    {'clause_id':'C002','page':2,'text':'임대인은 계약 종료 시 보증금을 반환한다.'}]}

def response():
    return {'document_id':REQUEST['document_id'],'status':'completed','results':[
        {'clause_id':c['clause_id'],'risk_type':'none','risk_status':'no_risk_detected','evidence':c['text'],
         'reason':'검사한 범위에서 위험 신호를 찾지 못했습니다.','possible_disadvantage':'','question':'','recommended_action':''}
        for c in REQUEST['clauses']], 'warnings':[]}

class ResponseTests(unittest.TestCase):
    def setUp(self):
        self.gate=ResponseValidationGate(lambda _: {'masked_image':IMAGE,'ocr_lines':[{'text':c['text'],'confidence':1} for c in REQUEST['clauses']]})
        self.receipt=self.gate.prepare('owner',REQUEST['document_id'],1,SOURCE)
        self.assertTrue(self.gate.confirm_analysis_review('owner',self.receipt['receipt_id'],REQUEST,self.receipt['image_sha256'],self.receipt['text_sha256']))
        self.started=self.gate.begin_analysis_mock('owner',self.receipt['receipt_id'],IMAGE,1,REQUEST)
        self.assertTrue(self.started['ok'])
    def check(self,value=None,raw=None,**kwargs):
        args={'owner':'owner','ticket':self.started['response_ticket'],'raw':json.dumps(response() if value is None else value,ensure_ascii=False) if raw is None else raw,
              'image_sha256':self.started['image_sha256'],'text_sha256':self.started['text_sha256'],'revision':1}
        args.update(kwargs);return self.gate.validate_response(**args)
    def reject(self,**kwargs):
        r=self.check(**kwargs);self.assertFalse(r['ok']);ErrorResponse.model_validate(r['error']);self.assertNotIn('response',r);return r
    def test_normal_schema(self):
        r=self.check();self.assertTrue(r['ok']);self.assertEqual(AnalyzeResponse.model_validate(r['response']).model_dump(),response())
    def test_syntax(self):self.reject(raw='{bad')
    def test_missing_field(self):r=response();del r['warnings'];self.reject(value=r)
    def test_wrong_type(self):r=response();r['results'][0]['reason']=1;self.reject(value=r)
    def test_invalid_status(self):r=response();r['results'][0]['risk_status']='safe';self.reject(value=r)
    def test_invalid_risk_type(self):r=response();r['results'][0]['risk_type']='contract_termination';self.reject(value=r)
    def test_unknown_clause(self):r=response();r['results'][0]['clause_id']='C999';self.reject(value=r)
    def test_document(self):r=response();r['document_id']='other';self.reject(value=r)
    def test_hallucinated_evidence(self):r=response();r['results'][0]['evidence']='실제 조항에 없는 합성 문장';self.reject(value=r)
    def test_other_clause_evidence(self):r=response();r['results'][0]['evidence']=REQUEST['clauses'][1]['text'];self.reject(value=r)
    def test_unreviewed_ocr(self):
        receipt=self.gate.prepare('owner',REQUEST['document_id'],2,SOURCE)
        self.assertFalse(self.gate.begin_analysis_mock('owner',receipt['receipt_id'],IMAGE,2,REQUEST)['ok'])
    def test_plain_review_not_clause_review(self):
        receipt=self.gate.prepare('owner',REQUEST['document_id'],2,SOURCE)
        self.gate.confirm_review('owner',receipt['receipt_id'],receipt['image_sha256'],receipt['text_sha256'])
        self.assertFalse(self.gate.begin_analysis_mock('owner',receipt['receipt_id'],IMAGE,2,REQUEST)['ok'])
    def test_private_email(self):r=response();r['warnings']=['synthetic@example.invalid'];self.assertEqual(self.reject(value=r)['error']['error']['code'],'PRIVACY_CHECK_FAILED')
    def test_private_phone(self):r=response();r['results'][0]['question']='010-0000-0000';self.reject(value=r)
    def test_private_name_context(self):r=response();r['results'][0]['reason']='성명: 합성인물';self.reject(value=r)
    def test_private_identifier(self):r=response();r['results'][0]['reason']='000000-0000000';self.reject(value=r)
    def test_image_hash(self):self.reject(image_sha256='a'*64)
    def test_text_hash(self):self.reject(text_sha256='a'*64)
    def test_version(self):self.reject(revision=2)
    def test_bool_version(self):self.reject(revision=True)
    def test_unauthorized(self):self.reject(ticket='forged')
    def test_owner(self):self.reject(owner='different')
    def test_duplicate_key(self):self.reject(raw='{"document_id":"a","document_id":"b"}')
    def test_nested_duplicate_key(self):self.reject(raw='{"results":[{"reason":"a","reason":"b"}]}')
    def test_too_large(self):self.reject(raw=' '* (MAX_RESPONSE_BYTES+1))
    def test_too_many_results(self):r=response();r['results']*=MAX_RESULTS;self.reject(value=r)
    def test_empty_results(self):r=response();r['results']=[];self.reject(value=r)
    def test_bad_array(self):r=response();r['results']={};self.reject(value=r)
    def test_nested_object(self):r=response();r['results'][0]['evidence']={'text':'bad'};self.reject(value=r)
    def test_code_fence(self):self.reject(raw='```json\n'+json.dumps(response())+'\n```')
    def test_mixed_explanation(self):self.reject(raw='설명: '+json.dumps(response()))
    def test_array_top(self):self.reject(raw='[]')
    def test_nan(self):self.reject(raw='{"document_id":NaN}')
    def test_extra_fields(self):r=response();r['debug']='hidden';self.reject(value=r)
    def test_replay(self):self.assertTrue(self.check()['ok']);self.reject()
    def test_failed_response_consumed(self):self.reject(raw='{bad');self.reject()
    def test_changed_document_revokes_response(self):self.gate.invalidate('owner',REQUEST['document_id']);self.reject()
    def test_expiry(self):self.gate._ttl=-1;self.reject()
    def test_changed_clause_mapping(self):
        receipt=self.gate.prepare('owner',REQUEST['document_id'],2,SOURCE)
        self.gate.confirm_analysis_review('owner',receipt['receipt_id'],REQUEST,receipt['image_sha256'],receipt['text_sha256'])
        changed=copy.deepcopy(REQUEST);changed['clauses'][0]['page']=2
        self.assertFalse(self.gate.begin_analysis_mock('owner',receipt['receipt_id'],IMAGE,2,changed)['ok'])
    def test_categorical_law(self):r=response();r['results'][0]['reason']='이 계약은 무효입니다.';self.reject(value=r)
    def test_empty_evidence(self):r=response();r['results'][0]['evidence']=' ';self.reject(value=r)
    def test_no_risk_pair(self):r=response();r['results'][0]['risk_type']='fee';self.reject(value=r)
    def test_missing_completed_clause(self):r=response();r['results'].pop();self.reject(value=r)
    def test_partial_without_warning(self):r=response();r['status']='partial';self.reject(value=r)
    def test_partial_valid(self):
        r=response();r['status']='partial';r['results'].pop();r['warnings']=['C002 추가 검토 필요'];self.assertTrue(self.check(value=r)['ok'])
    def test_duplicate_result(self):r=response();r['results'].append(r['results'][0]);self.reject(value=r)
    def test_multiple_risks_allowed(self):
        r=response();r['results'][0]['risk_type']='repair_cost';r['results'][0]['risk_status']='potential_risk'
        second=copy.deepcopy(r['results'][0]);second['risk_type']='other';r['results'].append(second);self.assertTrue(self.check(value=r)['ok'])
    def test_no_network_or_raw_logging(self):
        out=io.StringIO()
        with patch.object(socket.socket,'connect',side_effect=AssertionError('network')) as connect,patch('socket.create_connection',side_effect=AssertionError('network')) as create,contextlib.redirect_stdout(out),contextlib.redirect_stderr(out):
            r=response();r['warnings']=['synthetic@example.invalid'];value=self.reject(value=r);connect.assert_not_called();create.assert_not_called()
        self.assertEqual(out.getvalue(),'');self.assertNotIn('synthetic@example.invalid',json.dumps(value));self.assertNotIn('010-0000',json.dumps(value))

if __name__=='__main__':unittest.main()
