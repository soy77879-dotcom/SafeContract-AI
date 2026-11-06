"""Independent local integration preview. Does NOT modify backend.main.app."""
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from backend.main import health_check
from backend.schemas import AnalyzeRequest, AnalyzeResponse, OCRResponse
from integrations.adapter import AdapterError, MAX_FILE, OCRProcess, ReviewLedger, analyze_request, validate_upload


def install_routes(app,ocr_runner=None,ledger=None):
    if any(r.path in {'/api/ocr','/api/analyze'} for r in app.routes):
        raise ValueError('Integration routes already registered')
    runner=ocr_runner or OCRProcess();reviews=ledger or ReviewLedger()
    app.state.review_ledger=reviews
    @app.exception_handler(AdapterError)
    async def adapter_error(request,exc):
        return JSONResponse(status_code=exc.status,content={'status':'error','error':{'code':exc.code,'message':exc.message,'field':None}})
    @app.exception_handler(RequestValidationError)
    async def validation_error(request,exc):
        return JSONResponse(status_code=422,content={'status':'error','error':{'code':'VALIDATION_ERROR','message':'입력 형식과 필수 값을 확인하세요.','field':None}})
    @app.exception_handler(Exception)
    async def unexpected_error(request,exc):
        return JSONResponse(status_code=500,content={'status':'error','error':{'code':'INTERNAL_ERROR','message':'처리 중 오류가 발생했습니다.','field':None}})
    if not any(r.path=='/api/health' for r in app.routes):
        app.add_api_route('/api/health',health_check,methods=['GET'])
    @app.post('/api/ocr',response_model=OCRResponse)
    async def ocr(files:list[UploadFile]=File(...)):
        try:
            if not 1<=len(files)<=5:raise AdapterError(422,'VALIDATION_ERROR','이미지는 1~5장이어야 합니다.')
            uploads=[]
            for f in files:
                data=await f.read(MAX_FILE+1);validate_upload(f.filename,f.content_type,data)
                uploads.append((f.filename,f.content_type,data))
            structured=await run_in_threadpool(runner,uploads)
            return reviews.register(structured)
        finally:
            for f in files:await f.close()
    @app.post('/api/analyze',response_model=AnalyzeResponse)
    async def analyze(payload:AnalyzeRequest):
        return analyze_request(payload,reviews)
    return app

def create_app(ocr_runner=None,ledger=None):
    return install_routes(FastAPI(title='SafeContract AI integration preview'),ocr_runner,ledger)

app=create_app()
