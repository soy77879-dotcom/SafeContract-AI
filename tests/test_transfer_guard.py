import contextlib
import io
import json
import socket
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from integrations.transfer_guard import TransferGate

# Synthetic pipeline output; not a claim of actual OCR or a production mask attestation.
SOURCE=b'\x89PNG\r\n\x1a\nsynthetic-original'
MASKED=b'\x89PNG\r\n\x1a\nsynthetic-masked'
TEXT='임대인은 수리비를 부담한다.'

def processor(source):return {'masked_image':MASKED,'ocr_lines':[{'text':TEXT,'confidence':.99}]}

class TransferTests(unittest.TestCase):
    def setUp(self):
        self.gate=TransferGate(processor);self.receipt=self.gate.prepare('owner','doc',1,SOURCE)
    def approve(self):
        r=self.receipt;return self.gate.confirm_review('owner',r['receipt_id'],r['image_sha256'],r['text_sha256'])
    def send(self,**kwargs):
        args=dict(owner='owner',receipt_id=self.receipt['receipt_id'],image=MASKED,revision=1,text=TEXT);args.update(kwargs)
        return self.gate.dispatch_mock(**args)
    def test_default_disabled(self):self.assertIsNone(TransferGate().prepare('o','d',1,SOURCE))
    def test_unreviewed(self):self.assertFalse(self.send()['allowed'])
    def test_allow_mock(self):self.approve();self.assertTrue(self.send()['allowed'])
    def test_original(self):self.approve();self.assertFalse(self.send(image=SOURCE)['allowed'])
    def test_text_tamper(self):self.approve();self.assertFalse(self.send(text='synthetic@example.invalid')['allowed'])
    def test_empty(self):self.approve();self.assertFalse(self.send(text='')['allowed'])
    def test_missing(self):self.approve();self.assertFalse(self.send(text=None)['allowed'])
    def test_fake_receipt(self):self.approve();self.assertFalse(self.send(receipt_id='forged')['allowed'])
    def test_wrong_owner(self):self.approve();self.assertFalse(self.send(owner='other')['allowed'])
    def test_revision(self):self.approve();self.assertFalse(self.send(revision=2)['allowed'])
    def test_boolean_revision(self):self.approve();self.assertFalse(self.send(revision=True)['allowed'])
    def test_replay(self):self.approve();self.assertTrue(self.send()['allowed']);self.assertFalse(self.send()['allowed'])
    def test_changed_image(self):self.approve();self.assertFalse(self.send(image=MASKED+b'change')['allowed'])
    def test_invalidate(self):self.approve();self.gate.invalidate('owner','doc');self.assertFalse(self.send()['allowed'])
    def test_new_generation(self):self.approve();self.gate.prepare('owner','doc',2,SOURCE);self.assertFalse(self.send()['allowed'])
    def test_failed_new_scan_revokes(self):
        self.approve();self.gate._processor=lambda _: {};self.gate.prepare('owner','doc',2,SOURCE);self.assertFalse(self.send()['allowed'])
    def test_private_ocr_rejected(self):
        g=TransferGate(lambda _: {'masked_image':MASKED,'ocr_lines':[{'text':'synthetic@example.invalid','confidence':1}]})
        self.assertIsNone(g.prepare('o','d',1,SOURCE))
    def test_empty_ocr_rejected(self):
        g=TransferGate(lambda _: {'masked_image':MASKED,'ocr_lines':[]});self.assertIsNone(g.prepare('o','d',1,SOURCE))
    def test_unmasked_processor_rejected(self):
        g=TransferGate(lambda _: {'masked_image':SOURCE,'ocr_lines':[{'text':TEXT,'confidence':1}]});self.assertIsNone(g.prepare('o','d',1,SOURCE))
    def test_wrong_review_digest(self):self.assertFalse(self.gate.confirm_review('owner',self.receipt['receipt_id'],'fake','fake'));self.assertFalse(self.send()['allowed'])
    def test_expired(self):self.approve();self.gate._ttl=-1;self.assertFalse(self.send()['allowed'])
    def test_no_network_and_no_plaintext(self):
        self.approve();out=io.StringIO()
        with patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')) as connect,patch('socket.create_connection',side_effect=AssertionError('network forbidden')) as create,contextlib.redirect_stdout(out),contextlib.redirect_stderr(out):
            response=self.send();self.assertTrue(response['allowed']);connect.assert_not_called();create.assert_not_called()
        self.assertEqual(out.getvalue(),'');self.assertNotIn(TEXT,json.dumps(response,ensure_ascii=False))
    def test_concurrent_one_use(self):
        self.approve()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.send(),range(2)))
        self.assertEqual(sum(r['allowed'] for r in results),1)
    def test_exception_redacted(self):
        def fail(_):raise ValueError('synthetic@example.invalid')
        out=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(out):r=TransferGate(fail).prepare('o','d',1,SOURCE)
        self.assertIsNone(r);self.assertEqual(out.getvalue(),'')

if __name__=='__main__':unittest.main()
