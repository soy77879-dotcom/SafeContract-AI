"""Loopback-only STEP 2 preview; production backend/API unchanged."""
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from integrations.adapter import MAX_FILE, ROOT, validate_upload
from integrations.privacy_detection import result, TYPES
from integrations.transfer_guard import TransferGate, blocked

OCR_PYTHON = ROOT / (
    ".venv-ocr/Scripts/python.exe"
    if os.name == "nt"
    else ".venv/bin/python"
)

class PrivacyProcess:
    def __init__(self, timeout=900):
        self.timeout = timeout
        self.lock = threading.Lock()

    def __call__(self, data):
        if not self.lock.acquire(blocking=False): return result('failed')
        try:
            with tempfile.TemporaryDirectory(prefix='safecontract_privacy_') as folder:
                image, output = Path(folder)/'masked.png', Path(folder)/'result.json'
                image.write_bytes(data)
                proc = subprocess.Popen([str(OCR_PYTHON), str(ROOT/'integrations/privacy_worker.py'), str(image), str(output)],
                    cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True'))
                try:
                    proc.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name == "nt":
                            proc.kill()
                        else:
                            os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

                    proc.wait()
                    return result("failed")
                if proc.returncode or not output.is_file() or output.stat().st_size > 4*1024*1024: return result('failed')
                return sanitize(json.loads(output.read_text(encoding='utf-8')))
        except Exception: return result('failed')
        finally: self.lock.release()


def sanitize(value):
    """Allowlist fields; neither exception strings nor OCR values cross this boundary."""
    if not isinstance(value, dict) or value.get('status') not in ('no_candidates','review_required'): return result('failed')
    items = value.get('findings')
    if not isinstance(items, list) or len(items)>20000: return result('failed')
    safe=[]
    for item in items:
        if not isinstance(item,dict) or item.get('type') not in TYPES: return result('failed')
        if any(type(item.get(k)) is not int or item[k]<0 for k in ('line_index','start','end')) or item['end']<item['start']: return result('failed')
        safe.append({'type':item['type'],'page':1,**{k:item[k] for k in ('line_index','start','end')},'possible_false_positive':True,'review_required':True})
    return result('review_required' if safe else 'no_candidates', safe)


def create_app(runner=None, transfer_gate=None):
    app = FastAPI(title='Local privacy rescan', docs_url=None, redoc_url=None, openapi_url=None)
    process = runner or PrivacyProcess()
    gate = transfer_gate or TransferGate()

    @app.middleware('http')
    async def local_only(request, call_next):
        host = urlsplit('http://' + request.headers.get('host','')).hostname
        if host not in ('localhost','127.0.0.1') or request.client.host not in ('127.0.0.1','::1','testclient'):
            return JSONResponse(result('failed'), status_code=403)
        if request.method == 'POST' and (request.headers.get('origin') != 'http://' + request.headers.get('host') or request.headers.get('x-privacy-scan') != '1'):
            return JSONResponse(result('failed'), status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control']='no-store'
        return response

    @app.post('/local/privacy-scan')
    async def scan(request: Request):
        try:
            # Reject oversized bodies before multipart parsing, including chunked uploads.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>MAX_FILE+65536: return JSONResponse(result('failed'),status_code=413)
            request._body=bytes(body)
            async with request.form(max_files=1,max_fields=3) as form:
                if set(form.keys()) != {'files','image_sha256','masking_revision','mask_count'} or len(form.multi_items()) != 4: raise ValueError()
                file = form['files']
                if file.filename!='masked-contract.png' or file.content_type!='image/png': raise ValueError()
                data=await file.read(MAX_FILE+1)
                validate_upload(file.filename,file.content_type,data)
                digest=hashlib.sha256(data).hexdigest()
                if form['image_sha256']!=digest: raise ValueError()
                revision,count=int(form['masking_revision']),int(form['mask_count'])
                if not 1<=revision<=2**53-1 or not 1<=count<=10000: raise ValueError()
                response=sanitize(await run_in_threadpool(process,data))
                response.update(image_sha256=digest,masking_revision=revision,ocr_engine='local_paddleocr',ocr_completed=response['status']!='failed')
                return response
        except Exception:
            return JSONResponse(result('failed'),status_code=422)

    @app.post('/local/mock-transfer')
    async def mock_transfer(request: Request):
        # No public prepare/approve route. Default server has no approved records.
        try:
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>15*1024*1024:return JSONResponse(blocked('oversize'),status_code=413)
            data=json.loads(body)
            if not isinstance(data,dict) or set(data)!={'receipt_id','image_base64','masking_revision','text'}:raise ValueError()
            image=base64.b64decode(data['image_base64'],validate=True)
            if len(image)>MAX_FILE:raise ValueError()
            decision=gate.dispatch_mock('local-preview',data['receipt_id'],image,data['masking_revision'],data['text'])
            return JSONResponse(decision,status_code=200 if decision['allowed'] else 403)
        except Exception:return JSONResponse(blocked('invalid_request'),status_code=403)

    app.mount('/',StaticFiles(directory=ROOT/'frontend',html=True),name='frontend')
    return app

app=create_app()
