"""Real loopback HTTP against an isolated preview app; OCR inference is stubbed."""
import base64
import copy
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import uvicorn
from backend.schemas import AnalyzeResponse, OCRResponse
from integrations.adapter import AdapterError, OCRProcess, ReviewLedger, analyze_request, validate_upload
from integrations.preview_app import create_app

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVR4nGP8//8/AwMDEwMYAAAkBgMBXaJOiAAAAABJRU5ErkJggg==')


def internal(doc='fixture',text='임대인은 새로운 임차인이 입주한 이후 보증금을 반환한다.'):
    return {'document_id':doc,'clauses':[{'clause_id':'C001','pages':[1],'raw_text':text,'needs_review':True,'verified_text':None,'candidate_text':None,'source_lines':[]}]}


def request(doc='fixture',text='임대인은 새로운 임차인이 입주한 이후 보증금을 반환한다.'):
    return {'document_id':doc,'clauses':[{'clause_id':'C001','page':1,'text':text}]}


def multipart(name='test.png',data=PNG,mime='image/png'):
    boundary='test-'+uuid.uuid4().hex
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n').encode()+data+f'\r\n--{boundary}--\r\n'.encode()
    return body,'multipart/form-data; boundary='+boundary


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger=ReviewLedger()
        cls.ledger.register(internal('reviewed'))
        cls.ledger.confirm(request('reviewed'))
        normal='임대인은 계약 종료 시 보증금을 반환한다.'
        cls.ledger.register(internal('normal',normal));cls.ledger.confirm(request('normal',normal))
        def fake_ocr(uploads):
            if uploads[0][0]=='failure.png':raise RuntimeError('synthetic worker failure')
            return internal('mock-ocr')
        cls.app=create_app(fake_ocr,cls.ledger)
        cls.sock=socket.socket();cls.sock.bind(('127.0.0.1',0))
        cls.base=f'http://127.0.0.1:{cls.sock.getsockname()[1]}'
        cls.server=uvicorn.Server(uvicorn.Config(cls.app,log_level='critical',access_log=False))
        cls.thread=threading.Thread(target=cls.server.run,kwargs={'sockets':[cls.sock]},daemon=True);cls.thread.start()
        for _ in range(100):
            if cls.server.started:break
            time.sleep(.05)
        if not cls.server.started:raise RuntimeError('Test server did not start')
    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit=True;cls.thread.join(5);cls.sock.close()
    def http(self,path,data=None,content_type='application/json'):
        body=json.dumps(data).encode() if isinstance(data,dict) else data
        req=urllib.request.Request(self.base+path,data=body,headers={'Content-Type':content_type})
        try:
            with urllib.request.urlopen(req,timeout=5) as r:return r.status,r.read()
        except urllib.error.HTTPError as e:return e.code,e.read()
    def test_health_http(self):
        code,body=self.http('/api/health');self.assertEqual(code,200);self.assertEqual(json.loads(body)['status'],'ok')
    def test_docs_http(self):
        code,body=self.http('/docs');self.assertEqual(code,200);self.assertIn(b'SwaggerUIBundle',body)
    def test_ocr_mock_http_schema(self):
        data,mime=multipart();code,body=self.http('/api/ocr',data,mime)
        self.assertEqual(code,200);result=OCRResponse.model_validate_json(body);self.assertEqual(result.clauses[0].clause_id,'C001')
    def test_analyze_unreviewed_http(self):
        code,body=self.http('/api/analyze',request('unreviewed'))
        self.assertEqual(code,200);result=AnalyzeResponse.model_validate_json(body)
        self.assertEqual(result.results[0].risk_status,'needs_review');self.assertEqual(result.status,'partial')
    def test_reviewed_risk_http(self):
        code,body=self.http('/api/analyze',request('reviewed'));self.assertEqual(code,200)
        r=json.loads(body)['results'][0];self.assertEqual(r['risk_status'],'potential_risk')
        self.assertIn(r['evidence'],request('reviewed')['clauses'][0]['text']);self.assertEqual(r['clause_id'],'C001')
    def test_reviewed_normal_http(self):
        code,body=self.http('/api/analyze',request('normal','임대인은 계약 종료 시 보증금을 반환한다.'))
        self.assertEqual(code,200);self.assertEqual(json.loads(body)['results'][0]['risk_status'],'no_risk_detected')
    def test_review_hash_invalidated_http(self):
        code,body=self.http('/api/analyze',request('reviewed','임대인은 보증금을 반환하지 않는다.'))
        self.assertEqual(code,200);self.assertEqual(json.loads(body)['results'][0]['risk_status'],'needs_review')
    def test_client_flag_cannot_approve(self):
        data=request('unknown');data['reviewed']=True
        code,body=self.http('/api/analyze',data);self.assertEqual(json.loads(body)['results'][0]['risk_status'],'needs_review')
    def test_bad_type_http(self):
        data,mime=multipart('bad.pdf',b'%PDF-test','application/pdf')
        code,body=self.http('/api/ocr',data,mime);self.assertEqual(code,415)
    def test_bad_magic_http(self):
        data,mime=multipart(data=b'not png');code,_=self.http('/api/ocr',data,mime);self.assertEqual(code,415)
    def test_empty_upload_http(self):
        data,mime=multipart(data=b'');code,_=self.http('/api/ocr',data,mime);self.assertEqual(code,422)
    def test_oversize_http(self):
        data,mime=multipart(data=PNG+b'0'*(10*1024*1024));code,_=self.http('/api/ocr',data,mime);self.assertEqual(code,413)
    def test_empty_clauses_http(self):
        code,body=self.http('/api/analyze',{'document_id':'x','clauses':[]});self.assertEqual(code,422)
        self.assertEqual(json.loads(body)['error']['code'],'VALIDATION_ERROR')
    def test_duplicate_ids_http(self):
        data=request();data['clauses']*=2;code,_=self.http('/api/analyze',data);self.assertEqual(code,422)
    def test_missing_files_http(self):
        code,_=self.http('/api/ocr',b'','multipart/form-data; boundary=empty');self.assertEqual(code,422)
    def test_server_error_http(self):
        data,mime=multipart('failure.png');code,body=self.http('/api/ocr',data,mime)
        self.assertEqual(code,500);self.assertNotIn(b'synthetic worker failure',body)


class AdapterTests(unittest.TestCase):
    def test_backend_routes_unchanged(self):
        from backend.main import app
        self.assertNotIn('/api/ocr',[r.path for r in app.routes])
        self.assertNotIn('/api/analyze',[r.path for r in app.routes])
    def test_duplicate_route_registration_rejected(self):
        from integrations.preview_app import install_routes
        with self.assertRaises(ValueError):install_routes(create_app())
    def test_expiry(self):
        ledger=ReviewLedger(ttl=-1);ledger.register(internal())
        self.assertFalse(ledger.approved(request()))
    def test_shape_change_rejected(self):
        ledger=ReviewLedger();ledger.register(internal());data=request();data['clauses'][0]['page']=2
        with self.assertRaises(AdapterError):ledger.confirm(data)
    def test_timeout_and_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            worker=Path(d)/'slow.py';worker.write_text('import time\ntime.sleep(10)\n')
            runner=OCRProcess(timeout=.1,python=sys.executable,worker=worker)
            with self.assertRaises(AdapterError) as cm:runner([('x.png','image/png',PNG)])
            self.assertEqual(cm.exception.status,504);self.assertFalse(runner.lock.locked())
    def test_invalid_worker_output(self):
        with tempfile.TemporaryDirectory() as d:
            worker=Path(d)/'bad.py';worker.write_text('import sys\nfrom pathlib import Path\nPath(sys.argv[2]).write_text("not json")\n')
            with self.assertRaises(AdapterError) as cm:OCRProcess(python=sys.executable,worker=worker)([('x.png','image/png',PNG)])
            self.assertEqual(cm.exception.status,500)
    def test_real_worker_rejects_corrupt_image_without_ocr(self):
        with self.assertRaises(AdapterError) as cm:OCRProcess(timeout=10)([('x.png','image/png',b'\x89PNG\r\n\x1a\ncorrupt')])
        self.assertEqual(cm.exception.status,415)
    def test_real_decoder_accepts_valid_image(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            image=Path(d)/'image.png';image.write_bytes(PNG)
            code="from integrations.ocr_worker import load_images; import sys,json; print(json.dumps(load_images([sys.argv[1]])[0].size))"
            result=subprocess.run([str(ROOT/'.venv/bin/python'),'-c',code,str(image)],cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),[2,2])
    def test_busy(self):
        runner=OCRProcess();runner.lock.acquire()
        try:
            with self.assertRaises(AdapterError) as cm:runner([('x.png','image/png',PNG)])
            self.assertEqual(cm.exception.status,503)
        finally:runner.lock.release()
    def test_actual_structured_schema(self):
        path=ROOT/'tmp/ocr_pages/c001_aligned/structured_contract.json'
        data=json.loads(path.read_text());ledger=ReviewLedger();before=copy.deepcopy(data)
        payload=ledger.register(data);self.assertEqual(len(payload['clauses']),19)
        result=analyze_request(payload,ledger)
        self.assertTrue(all(r.risk_status=='needs_review' for r in result.results));self.assertEqual(data,before)


if __name__=='__main__':unittest.main()
