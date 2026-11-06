"""Real loopback HTTP; trusted mask/OCR/review inputs are synthetic mocks."""
import base64
import json
import unittest
import urllib.request
import urllib.error
from test_privacy_service import TestClient
from integrations.privacy_service import create_app
from integrations.transfer_guard import TransferGate

SOURCE=b'\x89PNG\r\n\x1a\noriginal-synthetic'
MASKED=b'\x89PNG\r\n\x1a\nmasked-synthetic'
TEXT='임대인은 수리비를 부담한다.'

class TransferHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate=TransferGate(lambda _: {'masked_image':MASKED,'ocr_lines':[{'text':TEXT,'confidence':1}]})
        cls.client=TestClient(create_app(transfer_gate=cls.gate))
    @classmethod
    def tearDownClass(cls):cls.client.close()
    def setUp(self):
        self.receipt=self.gate.prepare('local-preview','doc',1,SOURCE)
    def approve(self):
        r=self.receipt;self.gate.confirm_review('local-preview',r['receipt_id'],r['image_sha256'],r['text_sha256'])
    def post(self,**changes):
        data={'receipt_id':self.receipt['receipt_id'],'image_base64':base64.b64encode(MASKED).decode(),'masking_revision':1,'text':TEXT}
        data.update(changes)
        request=urllib.request.Request(self.client.base+'/local/mock-transfer',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':self.client.base,'X-Privacy-Scan':'1'})
        try:
            with urllib.request.urlopen(request,timeout=5) as r:return r.status,json.loads(r.read())
        except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
    def test_allow_synthetic_mock(self):
        self.approve();code,r=self.post();self.assertEqual(code,200);self.assertTrue(r['allowed']);self.assertFalse(r['external_llm_called'])
    def test_unreviewed_frontend_bypass(self):self.assertEqual(self.post()[0],403)
    def test_fake_flags(self):self.approve();self.assertEqual(self.post(allowed=True,review_required=False)[0],403)
    def test_original(self):self.approve();self.assertEqual(self.post(image_base64=base64.b64encode(SOURCE).decode())[0],403)
    def test_forged_receipt(self):self.approve();self.assertEqual(self.post(receipt_id='forged')[0],403)
    def test_replay(self):self.approve();self.assertEqual(self.post()[0],200);self.assertEqual(self.post()[0],403)
    def test_empty(self):self.approve();self.assertEqual(self.post(text='')[0],403)
    def test_private_text_not_echoed(self):
        self.approve();code,r=self.post(text='synthetic@example.invalid');self.assertEqual(code,403);self.assertNotIn('synthetic',json.dumps(r))
    def test_new_revision(self):
        self.approve();self.gate.invalidate('local-preview','doc');self.assertEqual(self.post()[0],403)
    def test_wrong_version(self):self.approve();self.assertEqual(self.post(masking_revision=2)[0],403)

if __name__=='__main__':unittest.main()
