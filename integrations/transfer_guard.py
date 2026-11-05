"""Server-owned, one-use mock dispatch boundary. No network transport is implemented.
Processor and review hooks are trusted server code, NEVER request fields.
Default configuration cannot issue an approved record.
"""
import hashlib
import secrets
import threading
import time
from integrations.privacy_detection import scan_lines


def digest(data): return hashlib.sha256(data).hexdigest()
def blocked(reason='not_authorized'):
    return {'allowed':False,'reason':reason,'mode':'mock','external_llm_called':False}


class TransferGate:
    def __init__(self, processor=None, ttl=300, clock=time.monotonic):
        self._processor=processor
        self._ttl=ttl;self._clock=clock;self._records={};self._latest={};self._lock=threading.RLock()

    def invalidate(self, owner, document):
        with self._lock:
            self._latest[(owner,document)]=secrets.token_hex(32)
            self._records={k:r for k,r in self._records.items() if (r['owner'],r['document'])!=(owner,document)}

    def prepare(self, owner, document, revision, source):
        """Trusted pipeline hook. Processor must derive masked PNG + ALL OCR lines
        from source server-side. No client scan, hash, text or allowed flag is accepted.
        Returns an opaque handle, not an approval. Production processor is not wired.
        """
        with self._lock:
            self.invalidate(owner,document)
            generation=self._latest[(owner,document)]
        if not self._processor or type(revision) is not int or revision<1 or not isinstance(source,bytes) or not source:return None
        try:
            prepared=self._processor(source)
            image=prepared['masked_image'];lines=prepared['ocr_lines']
            if not isinstance(image,bytes) or not image.startswith(b'\x89PNG\r\n\x1a\n') or image==source:return None
            scan=scan_lines(lines)
            if scan['status']!='no_candidates' or scan['found'] is not False:return None
            text='\n'.join(line['text'] for line in lines)
            if not text.strip():return None
            token=secrets.token_urlsafe(32)
            with self._lock:
                if self._latest.get((owner,document))!=generation:return None
                # Bounded memory and expiration. No records/text are persisted or logged.
                self._records={k:r for k,r in self._records.items() if self._clock()-r['created']<self._ttl}
                if len(self._records)>=100:return None
                self._records[token]={'owner':owner,'document':document,'generation':generation,'revision':revision,
                    'image_hash':digest(image),'text_hash':digest(text.encode()),'created':self._clock(),'reviewed':False}
            return {'receipt_id':token,'image_sha256':digest(image),'text_sha256':digest(text.encode()),'masking_revision':revision}
        except Exception:return None

    def confirm_review(self, owner, receipt_id, image_hash, text_hash):
        """Trusted authenticated human-review hook; intentionally NO public HTTP route.
        A future review UI must confirm exact image AND exact OCR text before calling.
        """
        with self._lock:
            r=self._records.get(receipt_id)
            if not r or r['owner']!=owner or self._clock()-r['created']>=self._ttl:return False
            if r['image_hash']!=image_hash or r['text_hash']!=text_hash:return False
            r['reviewed']=True;return True

    def dispatch_mock(self, owner, receipt_id, image, revision, text):
        """The only dispatch entry point; atomically consumes approval even on a bad attempt.
        Future real transport must remain disabled until production review/auth/egress
        are connected. This method never invokes user-provided transport callbacks.
        """
        with self._lock:
            r=self._records.get(receipt_id) if isinstance(receipt_id,str) else None
            if not r or r['owner']!=owner:return blocked()
            self._records.pop(receipt_id,None)
            if self._clock()-r['created']>=self._ttl or self._latest.get((owner,r['document']))!=r['generation']:return blocked('stale')
            if not r['reviewed']:return blocked('unreviewed')
            if type(revision) is not int or revision!=r['revision']:return blocked('version_mismatch')
            if not isinstance(image,bytes) or digest(image)!=r['image_hash']:return blocked('image_mismatch')
            if not isinstance(text,str) or not text.strip() or digest(text.encode())!=r['text_hash']:return blocked('text_mismatch')
            if scan_lines([{'text':line,'confidence':1.0} for line in text.split('\n')])['status']!='no_candidates':return blocked('privacy_candidate')
            return {'allowed':True,'mode':'mock','external_llm_called':False,'receipt_id':receipt_id,
                    'image_sha256':r['image_hash'],'text_sha256':r['text_hash'],'masking_revision':r['revision'],
                    'response':{'status':'mock_only','schema_version':'future-step4'}}
