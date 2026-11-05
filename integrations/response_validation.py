"""Python 3.11 independent mock-response validation. No LLM/network calls.
All review methods are trusted server hooks, never public request authorization.
"""
import copy
import json
import re
import secrets
from backend.schemas import AnalyzeRequest, AnalyzeResponse, ErrorResponse, RiskResult
from integrations.adapter import payload_hash
from integrations.privacy_detection import scan_lines
from integrations.transfer_guard import TransferGate, digest

MAX_RESPONSE_BYTES=128*1024
MAX_RESULTS=200
MAX_TEXT=8000
MAX_WARNINGS=50


class Rejected(Exception):
    pass


def fail(reason):
    privacy=reason=='privacy_candidate'
    error=ErrorResponse.model_validate({'error':{
        'code':'PRIVACY_CHECK_FAILED' if privacy else 'VALIDATION_ERROR',
        'message':'응답에 추가 개인정보 확인이 필요합니다.' if privacy else '분석 응답 검증에 실패했습니다. 결과를 표시하지 않습니다.',
        'field':None}}).model_dump()
    # Internal classification is a constant, never a parser exception or model value.
    return {'ok':False,'internal_reason':reason,'error':error}


def strict_request(value):
    if not isinstance(value,dict) or set(value)!={'document_id','clauses'}:raise Rejected('request_schema')
    if not isinstance(value['clauses'],list) or not 1<=len(value['clauses'])<=MAX_RESULTS:raise Rejected('request_schema')
    if any(not isinstance(c,dict) or set(c)!={'clause_id','page','text'} for c in value['clauses']):raise Rejected('request_schema')
    request=AnalyzeRequest.model_validate(value,strict=True).model_dump()
    if any(not c['text'].strip() or len(c['text'])>MAX_TEXT for c in request['clauses']):raise Rejected('request_schema')
    return request


def parse_response(raw):
    if not isinstance(raw,(str,bytes)):raise Rejected('json_object_required')
    try:
        data=raw.encode('utf-8') if isinstance(raw,str) else raw
        if len(data)>MAX_RESPONSE_BYTES:raise Rejected('response_too_large')
        text=data.decode('utf-8')
        def pairs(items):
            obj={}
            for key,value in items:
                if key in obj:raise Rejected('duplicate_json_key')
                obj[key]=value
            return obj
        def constant(_):raise Rejected('invalid_json_constant')
        value=json.loads(text,object_pairs_hook=pairs,parse_constant=constant)
    except Rejected:raise
    except Exception:raise Rejected('invalid_json') from None
    if not isinstance(value,dict):raise Rejected('json_object_required')
    if set(value)!=set(AnalyzeResponse.model_fields):raise Rejected('response_schema')
    rows=value['results'];warnings=value['warnings']
    if not isinstance(rows,list) or not 1<=len(rows)<=MAX_RESULTS:raise Rejected('result_count')
    if not isinstance(warnings,list) or len(warnings)>MAX_WARNINGS:raise Rejected('warnings_schema')
    if any(type(w) is not str or len(w)>MAX_TEXT for w in warnings):raise Rejected('warnings_schema')
    for row in rows:
        if not isinstance(row,dict) or set(row)!=set(RiskResult.model_fields):raise Rejected('result_schema')
        if any(type(v) is not str or len(v)>MAX_TEXT for v in row.values()):raise Rejected('result_schema')
        if not row['reason'].strip() or not row['evidence'].strip():raise Rejected('empty_evidence_or_reason')
    try:return AnalyzeResponse.model_validate(value,strict=True).model_dump()
    except Exception:raise Rejected('response_schema') from None


def validate_content(response, request):
    if response['document_id']!=request['document_id']:raise Rejected('document_mismatch')
    clauses={c['clause_id']:c['text'] for c in request['clauses']}
    seen=set();types={}
    for row in response['results']:
        cid=row['clause_id']
        if cid not in clauses:raise Rejected('unknown_clause')
        if row['evidence'] not in clauses[cid]:raise Rejected('evidence_mismatch')
        key=(cid,row['risk_type'])
        if key in seen:raise Rejected('duplicate_result')
        seen.add(key);types.setdefault(cid,set()).add(row['risk_type'])
        if (row['risk_status']=='no_risk_detected') != (row['risk_type']=='none'):raise Rejected('inconsistent_risk_state')
        if 'none' in types[cid] and len(types[cid])>1:raise Rejected('contradictory_results')
    covered={r['clause_id'] for r in response['results']}
    if response['status']=='completed' and covered!=set(clauses):raise Rejected('incomplete_completed_response')
    if response['status']=='partial' and not any(w.strip() for w in response['warnings']):raise Rejected('missing_partial_warning')
    # Scan all human-readable values, including warnings and IDs; do not echo matches.
    strings=[response['document_id']]+response['warnings']
    for row in response['results']:strings.extend(row.values())
    if scan_lines([{'text':s,'confidence':1.0} for s in strings])['status']!='no_candidates':raise Rejected('privacy_candidate')
    # A deterministic conservative filter, not semantic/legal truth verification.
    narratives=response['warnings']+[r[k] for r in response['results'] for k in ('reason','possible_disadvantage','question','recommended_action')]
    assertion=re.compile(r'(?:위법|불법|무효|사기)(?:입니다|이다|로확정)|법적으로(?:완전히)?안전|반드시승소|법적효력(?:이|은)?없(?:다|습니다)|(?:확실|명백)한사기')
    if any(assertion.search(re.sub(r'\s+','',s)) for s in narratives):raise Rejected('categorical_legal_claim')
    return response


class ResponseValidationGate(TransferGate):
    """STEP 3 extension: binds exact reviewed AnalyzeRequest to a one-use response ticket."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self._responses={}

    def confirm_analysis_review(self,owner,receipt_id,request,image_hash,text_hash):
        """Only after authenticated human review of clause IDs/pages/text. No HTTP route."""
        try:
            request=strict_request(request)
            with self._lock:
                record=self._records.get(receipt_id)
                if not record or record['owner']!=owner or request['document_id']!=record['document']:return False
                text='\n'.join(c['text'] for c in request['clauses'])
                if digest(text.encode())!=record['text_hash']:return False
                if not self.confirm_review(owner,receipt_id,image_hash,text_hash):return False
                record['analysis_request']=copy.deepcopy(request)
                record['analysis_hash']=payload_hash(request)
                return True
        except Exception:return False

    def begin_analysis_mock(self,owner,receipt_id,image,revision,request):
        try:
            request=strict_request(request)
            with self._lock:
                record=self._records.get(receipt_id)
                if not record or record['owner']!=owner or not record.get('reviewed') or record.get('analysis_hash')!=payload_hash(request):return fail('unapproved_request')
                context=copy.deepcopy(record)
                decision=self.dispatch_mock(owner,receipt_id,image,revision,'\n'.join(c['text'] for c in request['clauses']))
                if not decision['allowed']:return fail('unapproved_request')
                self._responses={k:r for k,r in self._responses.items() if self._clock()-r['created']<self._ttl}
                if len(self._responses)>=100:return fail('capacity')
                ticket=secrets.token_urlsafe(32);self._responses[ticket]=context
                return {'ok':True,'response_ticket':ticket,'mode':'mock','external_llm_called':False,
                        'image_sha256':context['image_hash'],'text_sha256':context['text_hash'],'masking_revision':revision}
        except Exception:return fail('unapproved_request')

    def validate_response(self,owner,ticket,raw,*,image_sha256,text_sha256,revision):
        # Lock spans validation so concurrent invalidation cannot race approval.
        with self._lock:
            try:
                context=self._responses.get(ticket) if isinstance(ticket,str) else None
                if not context or context['owner']!=owner:return fail('unapproved_response')
                self._responses.pop(ticket,None) # Failures also consume the ticket.
                if self._clock()-context['created']>=self._ttl or self._latest.get((owner,context['document']))!=context['generation']:return fail('stale_response')
                if type(revision) is not int or revision!=context['revision']:return fail('version_mismatch')
                if image_sha256!=context['image_hash'] or text_sha256!=context['text_hash']:return fail('hash_mismatch')
                response=validate_content(parse_response(raw),context['analysis_request'])
                return {'ok':True,'response':response}
            except Rejected as exc:return fail(str(exc))
            except Exception:return fail('validation_failed')
