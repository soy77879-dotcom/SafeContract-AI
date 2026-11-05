"""Backend-env adapter; OCR remains in its existing Python 3.9 subprocess."""
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import uuid

from backend.schemas import AnalyzeRequest, AnalyzeResponse, OCRResponse
from scripts.risk_rules import analyze_document, to_api

ROOT=Path(__file__).resolve().parents[1]
MAX_FILE=10*1024*1024

class AdapterError(Exception):
    def __init__(self,status,code,message):
        self.status,self.code,self.message=status,code,message
        super().__init__(message)


def validate_upload(name,mime,data):
    ext=Path(name or '').suffix.lower()
    expected={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png'}.get(ext)
    if expected is None or mime not in (expected,'application/octet-stream',None,''):
        raise AdapterError(415,'UNSUPPORTED_FILE_TYPE','JPG/JPEG/PNG 이미지를 사용하세요.')
    if not data:raise AdapterError(422,'VALIDATION_ERROR','빈 이미지입니다.')
    if len(data)>MAX_FILE:raise AdapterError(413,'FILE_TOO_LARGE','이미지당 최대 10MiB입니다.')
    if not (data.startswith(b'\x89PNG\r\n\x1a\n') if expected=='image/png' else data.startswith(b'\xff\xd8\xff')):
        raise AdapterError(415,'UNSUPPORTED_FILE_TYPE','파일 확장자와 실제 이미지 형식이 다릅니다.')
    return '.png' if expected=='image/png' else '.jpg'


def payload_hash(payload):
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class ReviewLedger:
    """Local demo only; no public endpoint can approve text. Production needs session auth."""
    def __init__(self,ttl=3600,capacity=20):
        self.ttl,self.capacity=ttl,capacity
        self.entries={};self.lock=threading.Lock()
    def _expire(self):
        now=time.monotonic()
        self.entries={k:v for k,v in self.entries.items() if now-v['created']<self.ttl}
    def register(self,structured):
        api=ocr_response(structured).model_dump()
        with self.lock:
            self._expire()
            if len(self.entries)>=self.capacity:
                del self.entries[min(self.entries,key=lambda k:self.entries[k]['created'])]
            self.entries[api['document_id']]={'structured':copy.deepcopy(structured),'shape':[(c['clause_id'],c['page']) for c in api['clauses']],
                'review_hash':None,'created':time.monotonic()}
        return api
    def confirm(self,request):
        """Trusted server-side user-confirmation hook; never inferred from a client flag."""
        data=AnalyzeRequest.model_validate(request).model_dump()
        with self.lock:
            self._expire();entry=self.entries.get(data['document_id'])
            if entry is None or entry['shape']!=[(c['clause_id'],c['page']) for c in data['clauses']]:
                raise AdapterError(422,'VALIDATION_ERROR','확인할 원본 조항과 ID·페이지가 다릅니다.')
            entry['review_hash']=payload_hash(data)
    def approved(self,data):
        with self.lock:
            self._expire();entry=self.entries.get(data['document_id'])
            if entry is None:return False
            if entry['shape']!=[(c['clause_id'],c['page']) for c in data['clauses']]:
                raise AdapterError(422,'VALIDATION_ERROR','원본 조항과 ID·페이지가 다릅니다.')
            return entry['review_hash']==payload_hash(data)


def ocr_response(structured):
    result=OCRResponse.model_validate({'document_id':structured['document_id'],'clauses':[
        {'clause_id':c['clause_id'],'page':c['pages'][0],'text':c['raw_text']} for c in structured['clauses']]})
    if not result.clauses:raise AdapterError(422,'OCR_PROCESSING_ERROR','계약 조항을 분리하지 못했습니다. 원문 확인이 필요합니다.')
    return result


def analyze_request(request,ledger):
    data=AnalyzeRequest.model_validate(request).model_dump()
    reviewed=ledger.approved(data)
    internal=analyze_document(data,[c['clause_id'] for c in data['clauses']] if reviewed else [])
    return AnalyzeResponse.model_validate(to_api(internal))


class OCRProcess:
    def __init__(self,timeout=900,python=None,worker=None):
        self.timeout=timeout;self.python=Path(python or ROOT/'.venv/bin/python')
        self.worker=Path(worker or ROOT/'integrations/ocr_worker.py');self.lock=threading.Lock()
    def __call__(self,uploads):
        if not 1<=len(uploads)<=5:raise AdapterError(422,'VALIDATION_ERROR','이미지는 1~5장이어야 합니다.')
        suffixes=[validate_upload(*u) for u in uploads]
        if sum(len(u[2]) for u in uploads)>50*1024*1024:raise AdapterError(413,'FILE_TOO_LARGE','전체 최대 50MiB입니다.')
        if not self.lock.acquire(blocking=False):raise AdapterError(503,'OCR_BUSY','OCR 처리 중입니다. 잠시 후 다시 시도하세요.')
        try:
            with tempfile.TemporaryDirectory(prefix='safecontract_ocr_') as temp:
                folder=Path(temp);paths=[]
                for i,((_,_,data),suffix) in enumerate(zip(uploads,suffixes)):
                    path=folder/f'page_{i+1}{suffix}';path.write_bytes(data);paths.append(str(path))
                request={'document_id':uuid.uuid4().hex,'images':paths}
                req=folder/'request.json';out=folder/'response.json';req.write_text(json.dumps(request))
                try:
                    proc=subprocess.Popen([str(self.python),str(self.worker),str(req),str(out)],cwd=ROOT,
                        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                        start_new_session=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True'))
                except OSError as exc:raise AdapterError(503,'OCR_UNAVAILABLE','OCR 실행 환경을 확인하세요.') from exc
                try:proc.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    proc.wait()
                    raise AdapterError(504,'OCR_TIMEOUT','OCR 처리 시간이 초과됐습니다.')
                if not out.is_file() or out.stat().st_size>20*1024*1024:
                    raise AdapterError(500,'OCR_PROCESSING_ERROR','OCR 결과를 읽을 수 없습니다.')
                try:result=json.loads(out.read_text(encoding='utf-8'))
                except (ValueError,OSError) as exc:raise AdapterError(500,'OCR_PROCESSING_ERROR','OCR 결과 형식 오류입니다.') from exc
                if result.get('error'):
                    err=result['error'];raise AdapterError(err.get('status',500),err.get('code','OCR_PROCESSING_ERROR'),'이미지 검증 또는 OCR 처리에 실패했습니다.')
                if proc.returncode!=0 or result.get('document_id')!=request['document_id']:
                    raise AdapterError(500,'OCR_PROCESSING_ERROR','OCR 프로세스 응답 오류입니다.')
                try:
                    ocr_response(result)
                    if any(any(type(p) is not int or not 1<=p<=len(uploads) for p in c['pages']) for c in result['clauses']):
                        raise ValueError('OCR page outside submitted images')
                except (ValueError,KeyError,TypeError,IndexError) as exc:raise AdapterError(500,'OCR_PROCESSING_ERROR','OCR 조항 구조가 올바르지 않습니다.') from exc
                return result
        finally:self.lock.release()
