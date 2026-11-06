"""Actual local FastAPI+PaddleOCR integration; protected backend is unchanged."""
import hashlib
import json
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from backend.schemas import OCRResponse
from backend.main import health_check
from integrations.adapter import AdapterError, OCRProcess, ROOT, MAX_FILE, validate_upload
from integrations.privacy_service import PrivacyProcess, create_app as privacy_app
from integrations.review_store import ReviewStore, reject, sha


def verify_mask(data,regions):
    with tempfile.TemporaryDirectory(prefix='safecontract_mask_') as folder:
        image,meta,out=(Path(folder)/name for name in ('input.png','regions.json','masked.png'))
        image.write_bytes(data);meta.write_text(json.dumps(regions))
        try:r=subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'integrations/mask_verify_worker.py'),str(image),str(meta),str(out)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
        except Exception:reject('PRIVACY_CHECK_FAILED')
        if r.returncode or not out.is_file() or out.stat().st_size>MAX_FILE:reject('PRIVACY_CHECK_FAILED')
        return out.read_bytes()


def create_router(ocr=None,privacy=None,masker=None,store=None):
    router=APIRouter();runner=ocr or OCRProcess();scanner=privacy or PrivacyProcess();mask=masker or verify_mask;records=store or ReviewStore()
    sessions={};artifacts={};lock=threading.Lock()
    def identity(request):
        token=request.cookies.get('sc_review');entry=sessions.get(token)
        if not entry or time.monotonic()-entry['created']>3600:reject(status=401)
        if request.method!='GET' and request.headers.get('x-review-csrf')!=entry['csrf']:reject(status=403)
        return token
    async def uploads(request,allow_manifest=False):
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>50*1024*1024+65536:reject('FILE_TOO_LARGE',413)
        request._body=bytes(body)
        async with request.form(max_files=5,max_fields=1 if allow_manifest else 0) as form:
            if set(form.keys())!=({'files','mask_regions'} if allow_manifest else {'files'}):reject()
            files=form.getlist('files')
            if not 1<=len(files)<=5:reject()
            result=[]
            for f in files:
                data=await f.read(MAX_FILE+1);validate_upload(f.filename,f.content_type,data)
                if f.filename!='masked-contract.png' or f.content_type!='image/png':reject('PRIVACY_CHECK_FAILED')
                result.append(data)
            regions=json.loads(form['mask_regions']) if allow_manifest else None
            if allow_manifest and (not isinstance(regions,list) or len(regions)!=len(result)):reject()
            return result,regions
    def images_hash(images):return sha(b''.join(hashlib.sha256(data).digest() for data in images))
    async def payload(request):
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>5*1024*1024:reject('FILE_TOO_LARGE',413)
        value=json.loads(body)
        if not isinstance(value,dict):reject()
        return value
    @router.get('/api/session')
    async def session(request:Request):
        token=request.cookies.get('sc_review');entry=sessions.get(token)
        if not entry or time.monotonic()-entry['created']>3600:
            with lock:
                expired=[k for k,v in sessions.items() if time.monotonic()-v['created']>3600]
                for k in expired:sessions.pop(k)
                if len(sessions)>=100:reject(status=503)
                token=secrets.token_urlsafe(32);entry={'csrf':secrets.token_urlsafe(32),'created':time.monotonic()};sessions[token]=entry
        response=JSONResponse({'csrf_token':entry['csrf'],'storage':'development_memory'})
        response.set_cookie('sc_review',token,httponly=True,samesite='strict',max_age=3600)
        return response
    @router.post('/api/masking/register')
    async def register(request:Request):
        owner=identity(request);images,regions=await uploads(request,True)
        canonical=[];statuses=[]
        for data,boxes in zip(images,regions):
            png=await run_in_threadpool(mask,data,boxes);canonical.append(png)
            checked=await run_in_threadpool(scanner,png)
            if checked.get('status') not in ('no_candidates','review_required'):reject('PRIVACY_CHECK_FAILED')
            statuses.append(checked['status'])
        token=secrets.token_urlsafe(32)
        with lock:
            for key in [k for k,v in artifacts.items() if time.monotonic()-v['created']>600]:artifacts.pop(key)
            if len(artifacts)>=10:reject(status=503)
            artifacts[token]={'owner':owner,'hash':images_hash(images),'images':canonical,'created':time.monotonic(),'privacy':'review_required' if 'review_required' in statuses else 'no_candidates'}
        return {'mask_ticket':token,'image_sha256':images_hash(images),'privacy_status':artifacts[token]['privacy'],'external_llm_allowed':False}
    @router.post('/api/ocr',response_model=OCRResponse,openapi_extra={'requestBody':{'required':True,'content':{'multipart/form-data':{'schema':{'type':'object','required':['files'],'properties':{'files':{'type':'array','items':{'type':'string','format':'binary'}}}}}}}})
    async def ocr_route(request:Request):
        owner=identity(request);images,_=await uploads(request)
        with lock:
            ticket=request.headers.get('x-mask-ticket');artifact=artifacts.get(ticket)
            if not artifact or artifact['owner']!=owner:reject('PRIVACY_CHECK_FAILED')
            artifacts.pop(ticket)
        if time.monotonic()-artifact['created']>600 or images_hash(images)!=artifact['hash']:reject('PRIVACY_CHECK_FAILED')
        structured=await run_in_threadpool(runner,[('masked-contract.png','image/png',data) for data in artifact['images']])
        return records.register(owner,structured,artifact['hash'],artifact['privacy'])
    @router.get('/api/review-documents/{doc}')
    async def get_doc(doc:str,request:Request):return records.get(identity(request),doc)
    @router.post('/api/review-documents/{doc}/draft')
    async def save(doc:str,request:Request):return records.save(identity(request),doc,await payload(request))
    @router.post('/api/review-documents/{doc}/confirm')
    async def confirm(doc:str,request:Request):return records.confirm(identity(request),doc,await payload(request))
    @router.post('/api/review-documents/{doc}/invalidate')
    async def invalidate(doc:str,request:Request):return records.invalidate(identity(request),doc,await payload(request))
    @router.post('/api/analyze')
    async def analyze(request:Request):
        identity(request);reject('PRIVACY_CHECK_FAILED',403) # No review flag enables analysis.
    return router


def install_review_routes(app,**kwargs):
    if any(getattr(r,'path',None) in ('/api/ocr','/api/review-documents/{doc}') for r in app.routes):raise ValueError('Review routes already installed')
    @app.middleware('http')
    async def protect(request,call_next):
        host=request.headers.get('host','')
        try:valid=urlsplit('http://'+host).hostname in ('localhost','127.0.0.1')
        except Exception:valid=False
        if not valid or request.client.host not in ('127.0.0.1','::1') or (request.method=='POST' and request.headers.get('origin')!='http://'+host):
            return JSONResponse({'status':'error','error':{'code':'VALIDATION_ERROR','message':'로컬 요청을 확인하세요.','field':None}},status_code=403)
        try:response=await call_next(request)
        except Exception:response=JSONResponse({'status':'error','error':{'code':'VALIDATION_ERROR','message':'입력 또는 처리 상태를 확인하세요.','field':None}},status_code=422)
        response.headers['Cache-Control']='no-store';return response
    @app.exception_handler(AdapterError)
    async def error(request,exc):return JSONResponse({'status':'error','error':{'code':exc.code,'message':exc.message,'field':None}},status_code=exc.status)
    app.include_router(create_router(**kwargs))
    return app

def create_app(**kwargs):
    app=FastAPI(title='SafeContract actual OCR + review (development)')
    app.add_api_route('/api/health',health_check,methods=['GET'])
    install_review_routes(app,**kwargs)
    app.mount('/',privacy_app())
    return app
app=create_app()
