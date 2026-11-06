"""Real HTTP; mock tests separate from opt-in actual PaddleOCR flow."""
import copy
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import unittest
import urllib.error
import urllib.request
import uuid
from test_privacy_service import TestClient
from integrations.review_app import create_app, verify_mask
from integrations.adapter import AdapterError

PNG=b'\x89PNG\r\n\x1a\nsynthetic'
TEXT='제1조(수리 책임) 임대인은 수리비를 부담한다.'

def fake_ocr(uploads):
    line={'line_id':'P001_L001','text':TEXT,'confidence':1.,'polygon':None}
    return {'document_id':uuid.uuid4().hex,'clauses':[{'clause_id':'C001','pages':[1],'raw_text':TEXT+'\n','source_lines':[{'page':1,**line}]}],
            'ocr_pages':[{'page':1,'lines':[line]}]}

class Client:
    def __init__(self,base):
        self.base=base;self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf=self.request('/api/session')[1]['csrf_token']
    def request(self,path,data=None,headers=None):
        h={'Origin':self.base,'X-Review-CSRF':getattr(self,'csrf','')};h.update(headers or {})
        if isinstance(data,dict):data=json.dumps(data).encode();h['Content-Type']='application/json'
        r=urllib.request.Request(self.base+path,data=data,headers=h)
        try:
            with self.opener.open(r,timeout=300) as res:return res.status,json.loads(res.read()) if path!='/docs' else res.read()
        except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
    def upload(self,path,data,regions=False,token=None):
        b=uuid.uuid4().hex;body=(f'--{b}\r\nContent-Disposition: form-data; name="files"; filename="masked-contract.png"\r\nContent-Type: image/png\r\n\r\n').encode()+data+b'\r\n'
        if regions:body+=(f'--{b}\r\nContent-Disposition: form-data; name="mask_regions"\r\n\r\n'+json.dumps([[{'x':30,'y':30,'width':100,'height':50}]])+'\r\n').encode()
        body+=f'--{b}--\r\n'.encode();headers={'Content-Type':'multipart/form-data; boundary='+b}
        if token:headers['X-Mask-Ticket']=token
        return self.request(path,body,headers)
    def document(self,data=PNG):
        code,ticket=self.upload('/api/masking/register',data,True);assert code==200,(code,ticket)
        code,result=self.upload('/api/ocr',data,token=ticket['mask_ticket']);assert code==200,(code,result)
        code,doc=self.request('/api/review-documents/'+result['document_id']);assert code==200
        return doc

def binding(doc):
    c=doc['server_context'];return {'document_id':doc['document_id'],'document_version':c['document_version'],'image_sha256':c['image_sha256']}
def draft(doc):return {**binding(doc),'clauses':[{k:c[k] for k in ('clause_id','raw_text','edited_text')} for c in doc['clauses']]}

class ReviewHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.server=TestClient(create_app(ocr=fake_ocr,privacy=lambda _: {'status':'no_candidates'},masker=lambda data,r:data))
    @classmethod
    def tearDownClass(cls):cls.server.close()
    def setUp(self):self.client=Client(self.server.base);self.doc=self.client.document();self.path='/api/review-documents/'+self.doc['document_id']
    def test_health_docs(self):self.assertEqual(self.client.request('/api/health')[0],200);self.assertEqual(self.client.request('/docs')[0],200)
    def test_original_without_ticket(self):self.assertEqual(self.client.upload('/api/ocr',PNG)[0],422)
    def test_changed_image_ticket(self):
        _,t=self.client.upload('/api/masking/register',PNG,True);self.assertEqual(self.client.upload('/api/ocr',PNG+b'changed',token=t['mask_ticket'])[0],422)
    def test_draft_get(self):
        p=draft(self.doc);p['clauses'][0]['edited_text']='임대인은 수선 비용을 부담한다.'
        code,r=self.client.request(self.path+'/draft',p);self.assertEqual(code,200)
        _,again=self.client.request(self.path);self.assertEqual(again['clauses'][0]['edited_text'],p['clauses'][0]['edited_text']);self.assertEqual(again['clauses'][0]['raw_text'],TEXT+'\n');self.assertFalse(r['server_context']['analysis_approved'])
    def test_version(self):p=draft(self.doc);p['document_version']+=1;self.assertEqual(self.client.request(self.path+'/draft',p)[0],409)
    def test_image_hash(self):p=draft(self.doc);p['image_sha256']='bad';self.assertEqual(self.client.request(self.path+'/draft',p)[0],409)
    def test_other_document(self):p=draft(self.doc);p['document_id']='other';self.assertEqual(self.client.request(self.path+'/draft',p)[0],409)
    def test_other_session(self):other=Client(self.server.base);self.assertEqual(other.request(self.path)[0],404)
    def test_raw_tamper(self):p=draft(self.doc);p['clauses'][0]['raw_text']='tampered';self.assertEqual(self.client.request(self.path+'/draft',p)[0],422)
    def test_missing_clause(self):p=draft(self.doc);p['clauses']=[];self.assertEqual(self.client.request(self.path+'/draft',p)[0],422)
    def test_duplicate_clause(self):p=draft(self.doc);p['clauses']*=2;self.assertEqual(self.client.request(self.path+'/draft',p)[0],422)
    def test_boolean_review_not_approval(self):p=draft(self.doc);p['clauses'][0]['reviewed']=True;self.assertEqual(self.client.request(self.path+'/draft',p)[0],422)
    def test_private_edit_blocks(self):
        p=draft(self.doc);p['clauses'][0]['edited_text']='synthetic@example.invalid';_,r=self.client.request(self.path+'/draft',p)
        self.assertEqual(r['server_context']['privacy_status'],'review_required');self.assertFalse(r['server_context']['external_llm_allowed'])
    def test_confirmation_and_replay(self):
        c=self.doc['clauses'][0];p={**binding(self.doc),'clause_id':c['clause_id'],'challenge':self.doc['server_context']['review_challenges'][c['clause_id']],'text_sha256':hashlib.sha256(c['edited_text'].encode()).hexdigest()}
        code,r=self.client.request(self.path+'/confirm',p);self.assertEqual(code,200);self.assertEqual(r['clauses'][0]['status'],'user_confirmed');self.assertEqual(self.client.request(self.path+'/confirm',p)[0],409)
    def test_invalidation(self):_,r=self.client.request(self.path+'/invalidate',binding(self.doc));self.assertGreater(r['server_context']['document_version'],self.doc['server_context']['document_version']);self.assertEqual(self.client.request(self.path+'/draft',draft(self.doc))[0],409)
    def test_analysis_denied(self):self.assertEqual(self.client.request('/api/analyze',{'reviewed':True})[0],403)

class RealMaskVerification(unittest.TestCase):
    def test_white_region_rejected(self):
        data=(Path(__file__).resolve().parents[2]/'tmp/review_http/masked-contract.png').read_bytes()
        with self.assertRaises(AdapterError):verify_mask(data,[{'x':500,'y':700,'width':10,'height':10}])
    def test_missing_region_rejected(self):
        data=(Path(__file__).resolve().parents[2]/'tmp/review_http/masked-contract.png').read_bytes()
        with self.assertRaises(AdapterError):verify_mask(data,[])
    def test_corrupt_png_rejected(self):
        with self.assertRaises(AdapterError):verify_mask(PNG,[{'x':0,'y':0,'width':1,'height':1}])

@unittest.skipUnless(os.environ.get('RUN_REAL_REVIEW')=='1','actual PaddleOCR explicitly enabled separately')
class RealReviewHTTP(unittest.TestCase):
    def test_real_paddleocr_full_flow(self):
        server=TestClient(create_app());client=Client(server.base)
        try:
            data=(Path(__file__).resolve().parents[2]/'tmp/review_http/masked-contract.png').read_bytes()
            doc=client.document(data);self.assertGreaterEqual(len(doc['clauses']),1)
            self.assertTrue(all(c['source_lines'] for c in doc['clauses']))
            p=draft(doc);p['clauses'][0]['edited_text']='임대인은 수리 비용을 부담한다.'
            path='/api/review-documents/'+doc['document_id'];code,saved=client.request(path+'/draft',p);self.assertEqual(code,200)
            for c in saved['clauses']:
                confirmation={**binding(saved),'clause_id':c['clause_id'],'challenge':saved['server_context']['review_challenges'][c['clause_id']],'text_sha256':hashlib.sha256(c['edited_text'].encode()).hexdigest()}
                code,saved=client.request(path+'/confirm',confirmation);self.assertEqual(code,200)
            _,loaded=client.request(path);self.assertTrue(all(c['status']=='user_confirmed' for c in loaded['clauses']));self.assertFalse(loaded['server_context']['analysis_approved']);self.assertEqual(loaded['clauses'][0]['raw_text'],doc['clauses'][0]['raw_text'])
            out=Path(__file__).resolve().parents[2]/'tmp/review_http/actual_http_result.json';out.write_text(json.dumps({'actual_paddleocr':True,'clause_count':len(doc['clauses']),'save_reload':True,'confirmed':len(loaded['clauses']),'analysis_approved':False}))
        finally:server.close()

if __name__=='__main__':unittest.main()
