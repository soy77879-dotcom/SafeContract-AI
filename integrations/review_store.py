"""Development-only, session-owned memory store. No analysis approval is issued."""
import copy
import hashlib
import secrets
import threading
import time
from integrations.adapter import AdapterError, ocr_response
from integrations.clause_review import build_review_document
from integrations.privacy_detection import scan_lines


def reject(code='VALIDATION_ERROR',status=422):raise AdapterError(status,code,'문서·버전·검토 입력을 확인하세요.')
def sha(data):return hashlib.sha256(data).hexdigest()

class ReviewStore:
    def __init__(self,ttl=3600):self.entries={};self.ttl=ttl;self.lock=threading.RLock()
    def _get(self,owner,doc):
        r=self.entries.get(doc)
        if not r or r['owner']!=owner:reject(status=404)
        if time.monotonic()-r['created']>self.ttl:self.entries.pop(doc,None);reject(status=410)
        return r
    def _reset(self,r):
        r['version']+=1;r['confirmed']=set();r['challenges']={c['clause_id']:secrets.token_urlsafe(32) for c in r['data']['clauses']}
    def register(self,owner,structured,image_hash,privacy):
        api=ocr_response(structured).model_dump()
        data=build_review_document(structured,{'document_id':structured['document_id'],'pages':structured['ocr_pages']},api)
        with self.lock:
            self.entries={k:v for k,v in self.entries.items() if time.monotonic()-v['created']<self.ttl}
            if len(self.entries)>=20:reject(status=503)
            r={'owner':owner,'created':time.monotonic(),'data':data,'image_hash':image_hash,'version':0,'privacy':privacy,'confirmed':set()}
            self._reset(r);self.entries[api['document_id']]=r
        return api
    def get(self,owner,doc):
        with self.lock:
            r=self._get(owner,doc);d=copy.deepcopy(r['data'])
            for c in d['clauses']:
                c['status']='user_confirmed' if c['clause_id'] in r['confirmed'] else 'needs_review'
                c['reviewed_by_user']=c['clause_id'] in r['confirmed']
            d['server_context']={'document_version':r['version'],'image_sha256':r['image_hash'],'review_challenges':dict(r['challenges']),
                'privacy_status':r['privacy'],'analysis_approved':False,'external_llm_allowed':False,'storage':'development_memory'}
            return d
    def _binding(self,r,payload,doc):
        if payload.get('document_id')!=doc or type(payload.get('document_version')) is not int or payload['document_version']!=r['version'] or payload.get('image_sha256')!=r['image_hash']:reject('VALIDATION_ERROR',409)
    def invalidate(self,owner,doc,payload):
        with self.lock:
            r=self._get(owner,doc);self._binding(r,payload,doc);self._reset(r);return self.get(owner,doc)
    def save(self,owner,doc,payload):
        with self.lock:
            r=self._get(owner,doc);self._binding(r,payload,doc)
            if set(payload)!={'document_id','document_version','image_sha256','clauses'} or not isinstance(payload['clauses'],list):reject()
            original=r['data']['clauses'];incoming=payload['clauses']
            if [c.get('clause_id') for c in incoming if isinstance(c,dict)]!=[c['clause_id'] for c in original] or len(incoming)!=len(original):reject()
            for saved,c in zip(original,incoming):
                if set(c)!={'clause_id','raw_text','edited_text'} or c['raw_text']!=saved['raw_text'] or not isinstance(c['edited_text'],str) or not c['edited_text'].strip() or len(c['edited_text'])>50000:reject()
            for saved,c in zip(original,incoming):saved['edited_text']=c['edited_text']
            status=scan_lines([{'text':c['edited_text'],'confidence':1.0} for c in original])['status']
            r['privacy']='review_required' if r['privacy']!='no_candidates' or status!='no_candidates' else 'no_candidates'
            self._reset(r);return self.get(owner,doc)
    def confirm(self,owner,doc,payload):
        with self.lock:
            r=self._get(owner,doc);self._binding(r,payload,doc)
            if set(payload)!={'document_id','document_version','image_sha256','clause_id','challenge','text_sha256'}:reject()
            cid=payload['clause_id'];c=next((c for c in r['data']['clauses'] if c['clause_id']==cid),None)
            if not c or not r['challenges'].get(cid) or not secrets.compare_digest(r['challenges'][cid],str(payload['challenge'])) or sha(c['edited_text'].encode())!=payload['text_sha256']:reject(status=409)
            r['challenges'].pop(cid);r['confirmed'].add(cid);return self.get(owner,doc)
