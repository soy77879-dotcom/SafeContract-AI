import hashlib
import json
import unittest
import socket
import threading
import time
import urllib.request
import urllib.error
import uuid
import uvicorn

class Response:
    def __init__(self,code,body): self.status_code=code;self.text=body.decode()
    def json(self): return json.loads(self.text)

class TestClient:
    # Actual loopback HTTP, no additional test dependencies.
    def __init__(self,app,base_url=None):
        self.sock=socket.socket();self.sock.bind(('127.0.0.1',0))
        self.base=f'http://127.0.0.1:{self.sock.getsockname()[1]}'
        self.server=uvicorn.Server(uvicorn.Config(app,log_level='critical',access_log=False))
        self.thread=threading.Thread(target=self.server.run,kwargs={'sockets':[self.sock]},daemon=True);self.thread.start()
        for _ in range(100):
            if self.server.started:break
            time.sleep(.01)
    def close(self): self.server.should_exit=True;self.thread.join(5);self.sock.close()
    def post(self,path,files,data,headers):
        boundary=uuid.uuid4().hex;parts=[]
        for k,v in data.items(): parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for key,(name,blob,mime) in (files.items() if isinstance(files,dict) else files):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode()+blob+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        headers=dict(headers)
        if headers.get('Origin')=='http://127.0.0.1:8011':headers['Origin']=self.base
        headers['Content-Type']='multipart/form-data; boundary='+boundary
        req=urllib.request.Request(self.base+path,data=b''.join(parts),headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=10) as r:return Response(r.status,r.read())
        except urllib.error.HTTPError as e:return Response(e.code,e.read())

from integrations.privacy_service import create_app, sanitize, PrivacyProcess
from integrations.privacy_detection import scan_lines

PNG=b'\x89PNG\r\n\x1a\nSYNTHETIC_ONLY_MOCK'
class PrivacyServiceTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        def runner(data):
            self.calls.append(data)
            return scan_lines([{'text':'synthetic@example.invalid','confidence':.99}])
        self.client=TestClient(create_app(runner),base_url='http://127.0.0.1:8011')
    def tearDown(self): self.client.close()
    def post(self,**changes):
        args={'files':{'files':('masked-contract.png',PNG,'image/png')},'data':{'image_sha256':hashlib.sha256(PNG).hexdigest(),'masking_revision':'3','mask_count':'1'},'headers':{'Origin':'http://127.0.0.1:8011','X-Privacy-Scan':'1'}}
        args.update(changes);return self.client.post('/local/privacy-scan',**args)
    def test_busy_fails_closed(self):
        process=PrivacyProcess();process.lock.acquire()
        try:self.assertEqual(process(PNG)['status'],'failed')
        finally:process.lock.release()
    def test_real_worker_corrupt_image(self):
        r=PrivacyProcess(timeout=20)(PNG);self.assertEqual(r['status'],'failed');self.assertTrue(r['external_transfer_blocked'])
    def test_timeout_cleanup(self):
        import subprocess
        from unittest.mock import patch,MagicMock
        from pathlib import Path
        proc=MagicMock();proc.pid=999999;proc.wait.side_effect=[subprocess.TimeoutExpired('worker',.01),0]
        with patch('integrations.privacy_service.subprocess.Popen',return_value=proc) as spawn,patch('integrations.privacy_service.os.killpg') as kill:
            process=PrivacyProcess(timeout=.01);r=process(PNG)
            self.assertEqual(r['status'],'failed');self.assertFalse(process.lock.locked());kill.assert_called_once()
            image=Path(spawn.call_args.args[0][2]);self.assertFalse(image.parent.exists())
    def test_scan(self):
        r=self.post();self.assertEqual(r.status_code,200);self.assertEqual(r.json()['status'],'review_required');self.assertTrue(r.json()['ocr_completed']);self.assertEqual(len(self.calls),1)
    def test_hash(self):
        r=self.post(data={'image_sha256':'0'*64,'masking_revision':'3','mask_count':'1'});self.assertEqual(r.status_code,422);self.assertFalse(self.calls)
    def test_no_mask(self): self.assertEqual(self.post(data={'image_sha256':hashlib.sha256(PNG).hexdigest(),'masking_revision':'3','mask_count':'0'}).status_code,422)
    def test_original_name(self): self.assertEqual(self.post(files={'files':('original.png',PNG,'image/png')}).status_code,422)
    def test_cross_origin(self): self.assertEqual(self.post(headers={'Origin':'https://example.invalid','X-Privacy-Scan':'1'}).status_code,403)
    def test_missing_header(self): self.assertEqual(self.post(headers={}).status_code,403)
    def test_extra_file(self): self.assertEqual(self.post(files=[('files',('masked-contract.png',PNG,'image/png')),('files',('original.png',PNG,'image/png'))]).status_code,422)
    def test_safe_failure(self):
        def fail(data):raise RuntimeError('synthetic@example.invalid')
        self.client.close()
        self.client=TestClient(create_app(fail),base_url='http://127.0.0.1:8011')
        r=self.post();self.assertFalse(r.json()['external_llm_allowed']);self.assertNotIn('synthetic',r.text)
    def test_no_raw_output(self): self.assertNotIn('synthetic',self.post().text)
    def test_allowlist(self):
        r=sanitize({'status':'no_candidates','findings':[],'raw':'synthetic@example.invalid','external_llm_allowed':True});self.assertNotIn('synthetic',json.dumps(r));self.assertFalse(r['external_llm_allowed'])
    def test_invalid_worker(self): self.assertEqual(sanitize({'status':'no_candidates','findings':'bad'})['status'],'failed')
    def test_hash_binding(self): self.assertEqual(self.post().json()['image_sha256'],hashlib.sha256(PNG).hexdigest())
    def test_failed_ocr(self):
        self.client.close()
        self.client=TestClient(create_app(lambda _: {'status':'failed'}),base_url='http://127.0.0.1:8011');r=self.post().json();self.assertFalse(r['ocr_completed']);self.assertTrue(r['external_transfer_blocked'])

if __name__=='__main__':unittest.main()
