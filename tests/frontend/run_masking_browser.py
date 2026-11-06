"""Real Chrome pixel/PointerEvent tests. Uses existing backend websockets, no installs."""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.request
import websockets

ROOT=Path(__file__).resolve().parents[2]
CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

async def run(port,output,real_privacy=False,server_review=False):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list') as r:
        targets=json.load(r)
    page=next(x for x in targets if x['type']=='page')
    async with websockets.connect(page['webSocketDebuggerUrl'],max_size=20*1024*1024) as ws:
        seq=0
        async def send(method,params=None):
            nonlocal seq
            seq+=1;ident=seq;await ws.send(json.dumps({'id':ident,'method':method,'params':params or {}}))
            while True:
                msg=json.loads(await ws.recv())
                if msg.get('id')==ident:
                    if 'error' in msg:raise RuntimeError(msg['error'])
                    return msg.get('result',{})
        async def js(code):
            result=await send('Runtime.evaluate',{'expression':code,'awaitPromise':True,'returnByValue':True})
            if 'exceptionDetails' in result:raise RuntimeError(result['exceptionDetails'])
            return result['result'].get('value')
        await send('Page.enable')
        for _ in range(100):
            if await js("typeof ManualMasking !== 'undefined' && typeof SafeContractMasking !== 'undefined'"):break
            await asyncio.sleep(.05)
        results=await js((ROOT/'tests/frontend/masking_checks.js').read_text())
        async def check(name,expression):
            passed=bool(await js(expression));results.append({'name':name,'passed':passed})
            if not passed:raise AssertionError(name)
        load="""(async()=>{const c=document.createElement('canvas');c.width=400;c.height=240;const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,400,240);x.font='28px Arial';x.fillStyle='black';x.fillText('010-0000-0000',30,190);const blob=await new Promise(r=>c.toBlob(r));const dt=new DataTransfer();dt.items.add(new File([blob],'synthetic.png',{type:'image/png'}));const i=document.querySelector('#contract-image');i.files=dt.files;i.dispatchEvent(new Event('change'));await new Promise((resolve,reject)=>{let n=0;const t=setInterval(()=>{if(!document.querySelector('#workspace').hidden){clearInterval(t);resolve();}if(n++>100){clearInterval(t);reject('load timeout');}},20)});return true;})()"""
        await js(load)
        await check('UI source and export views separated',"!document.querySelector('#preview').hidden && document.querySelector('#result').hidden")
        async def bounds():
            await js("document.querySelector('#mask-canvas').scrollIntoView({block:'center'})")
            return await js("(()=>{const b=document.querySelector('#mask-canvas').getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height}})()")
        b=await bounds()
        for typ,dx,dy in [('mousePressed',.1,.1),('mouseMoved',.3,.3),('mouseReleased',.3,.3)]:
            await send('Input.dispatchMouseEvent',{'type':typ,'x':b['x']+b['w']*dx,'y':b['y']+b['h']*dy,'button':'left','clickCount':1})
        await check('real mouse drag masks source pixels',"document.querySelector('#mask-canvas').getContext('2d').getImageData(60,40,1,1).data[0]===0")
        await js("document.querySelector('#manual-confirm').click();document.querySelector('#export').click()")
        for _ in range(100):
            if await js("!document.querySelector('#result').hidden"):break
            await asyncio.sleep(.02)
        await check('UI upload capability uses generated PNG only',"SafeContractMasking.prepareOCRUpload().get('files').name==='masked-contract.png'")
        await js("document.querySelector('#undo').click()")
        await check('UI undo invalidates upload capability',"(()=>{try{SafeContractMasking.prepareOCRUpload();return false}catch{return document.querySelector('#result').hidden}})()")
        await send('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'deviceScaleFactor':2,'mobile':True})
        await send('Emulation.setTouchEmulationEnabled',{'enabled':True,'maxTouchPoints':2})
        await js("document.querySelector('#zoom').value='200';document.querySelector('#zoom').dispatchEvent(new Event('input'))")
        b=await bounds()
        for typ,dx,dy in [('touchStart',.05,.05),('touchMove',.2,.2),('touchEnd',.2,.2)]:
            points=[] if typ=='touchEnd' else [{'x':b['x']+b['w']*dx,'y':b['y']+b['h']*dy,'id':0}]
            await send('Input.dispatchTouchEvent',{'type':typ,'touchPoints':points})
        await check('real mobile touch and 200% zoom map to source',"document.querySelector('#mask-canvas').getContext('2d').getImageData(40,30,1,1).data[0]===0")
        count=await js("document.querySelector('#mask-count').textContent")
        await send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':b['x']+15,'y':b['y']+15,'id':0}]})
        await send('Input.dispatchTouchEvent',{'type':'touchCancel','touchPoints':[]})
        await check('touch cancellation creates no mask',f"document.querySelector('#mask-count').textContent==={json.dumps(count)}")
        screenshot=await send('Page.captureScreenshot',{'format':'png'})
        (output/'mobile_masking.png').write_bytes(base64.b64decode(screenshot['data']))
        await js("document.querySelector('#reset').click()")
        await check('UI reset restores white pixels',"document.querySelector('#mask-canvas').getContext('2d').getImageData(40,30,1,1).data[0]===255 && !document.querySelector('#manual-confirm').checked")
        await js(load)
        await check('UI image replacement clears export and selection',"document.querySelector('#result').hidden && document.querySelector('#mask-count').textContent.startsWith('가린 영역 0개')")
        await check('original input has no form submission name',"!document.querySelector('#contract-image').name")
        results.extend(await js((ROOT/'tests/frontend/privacy_checks.js').read_text()))
        results.extend(await js((ROOT/'tests/frontend/privacy_guard_checks.js').read_text()))
        await js('globalThis.reviewFixture='+ (ROOT/'tmp/clause_review/review_document.json').read_text())
        if not real_privacy:
            results.extend(await js((ROOT/'tests/frontend/clause_review_checks.js').read_text()))
        if real_privacy:
            b=await bounds()
            for typ,dx,dy in [('mousePressed',.01,.01),('mouseMoved',.05,.05),('mouseReleased',.05,.05)]:
                await send('Input.dispatchMouseEvent',{'type':typ,'x':b['x']+b['w']*dx,'y':b['y']+b['h']*dy,'button':'left','clickCount':1})
            await js("document.querySelector('#manual-confirm').click();document.querySelector('#export').click()")
            for _ in range(100):
                if await js("!document.querySelector('#privacy-scan').disabled"):break
                await asyncio.sleep(.02)
            await js("document.querySelector('#privacy-scan').click()")
            for _ in range(1800):
                if await js("!['pending','running'].includes(SafeContractMasking.getPrivacyScanState().status)"):break
                await asyncio.sleep(.5)
            await check('actual local OCR browser flow detects synthetic phone',"(()=>{const s=SafeContractMasking.getPrivacyScanState();return s.status==='review_required' && s.findings.some(f=>f.type==='phone') && !s.external_llm_allowed})()")
            await check('actual OCR findings blocked by client guard',"(async()=>!(await SafeContractPrivacyGuard.evaluateCurrent()).allowed)()")
            await check('UI findings do not expose synthetic phone',"!document.querySelector('#privacy-findings').textContent.includes('010-0000-0000')")
            results.extend(await js((ROOT/'tests/frontend/clause_review_checks.js').read_text()))
            await js("document.querySelector('#clause-review').scrollIntoView({block:'start'})")
            shot=await send('Page.captureScreenshot',{'format':'png'})
            (output/'clause_review_mobile.png').write_bytes(base64.b64decode(shot['data']))
            await js("document.querySelector('#reset').click()")
            await check('review image reset clears all clauses',"document.querySelectorAll('.clause-card').length===0")
            await check('reset blocks previous external transfer state',"(async()=>!(await SafeContractPrivacyGuard.evaluateCurrent()).allowed)()")
            await check('actual scan UI reset invalidates result',"SafeContractMasking.getPrivacyScanState().status==='pending'")
        if server_review:
            encoded=base64.b64encode((ROOT/'tmp/review_http/masked-contract.png').read_bytes()).decode()
            await js("(()=>{const bytes=Uint8Array.from(atob("+json.dumps(encoded)+"),c=>c.charCodeAt(0));const dt=new DataTransfer();dt.items.add(new File([bytes],'synthetic.png',{type:'image/png'}));const i=document.querySelector('#contract-image');i.files=dt.files;i.dispatchEvent(new Event('change'));})()")
            await asyncio.sleep(.5)
            b=await bounds()
            for typ,dx,dy in [('mousePressed',.025,.04),('mouseMoved',.05,.07),('mouseReleased',.05,.07)]:
                await send('Input.dispatchMouseEvent',{'type':typ,'x':b['x']+b['w']*dx,'y':b['y']+b['h']*dy,'button':'left','clickCount':1})
            await js("document.querySelector('#manual-confirm').click();document.querySelector('#export').click()")
            for _ in range(100):
                if await js("!document.querySelector('#result').hidden"):break
                await asyncio.sleep(.05)
            await js("document.querySelector('#server-ocr').click()")
            for _ in range(1800):
                if await js("!document.querySelector('#server-ocr').disabled"):break
                await asyncio.sleep(.5)
            await check('actual server OCR populates review UI',"document.querySelectorAll('.clause-card').length>0 && !document.querySelector('#server-save').disabled")
            raw=await js("document.querySelector('.clause-card pre').textContent")
            await js("(()=>{const t=document.querySelector('.clause-card textarea');t.value='임대인은 수리 비용을 부담한다.';t.dispatchEvent(new Event('input'));document.querySelector('#server-save').click();})()")
            for _ in range(100):
                if await js("!document.querySelector('#server-save').disabled"):break
                await asyncio.sleep(.05)
            await check('server save preserves edited text and original OCR',"document.querySelector('.clause-card textarea').value==='임대인은 수리 비용을 부담한다.' && document.querySelector('.clause-card pre').textContent==="+json.dumps(raw))
            await js("document.querySelector('.clause-card [data-action=review]').click()")
            for _ in range(100):
                if await js("document.querySelector('.clause-card .clause-status').textContent.includes('검토 완료')"):break
                await asyncio.sleep(.05)
            await check('server explicit clause confirmation recorded',"document.querySelector('.clause-card .clause-status').textContent.includes('검토 완료')")
            await js("document.querySelector('#server-reload').click()")
            await asyncio.sleep(.3)
            await check('server reload restores persisted review',"document.querySelector('.clause-card .clause-status').textContent.includes('검토 완료') && document.querySelector('.clause-card textarea').value==='임대인은 수리 비용을 부담한다.'")
        results.extend(await js((ROOT/'tests/frontend/server_review_ui_checks.js').read_text()))
        (output/'results.json').write_text(json.dumps({'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),'browser':'Chrome headless, real mouse/touch dispatch','tests':results},ensure_ascii=False,indent=2))
        print(json.dumps({'passed':len(results),'failed':0,'output':str(output)}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--privacy-url');parser.add_argument('--server-review',action='store_true');args=parser.parse_args()
    output=ROOT/('tmp/review_http/browser' if args.server_review else 'tmp/privacy_tests/browser' if args.privacy_url else 'tmp/masking_tests');output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mask-chrome-') as profile:
        proc=subprocess.Popen([CHROME,'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',f'--user-data-dir={profile}',args.privacy_url or (ROOT/'frontend/index.html').as_uri()],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            active=Path(profile)/'DevToolsActivePort'
            for _ in range(200):
                if active.exists():break
                if proc.poll() is not None:raise RuntimeError('Chrome exited')
                time.sleep(.05)
            asyncio.run(run(int(active.read_text().splitlines()[0]),output,bool(args.privacy_url),args.server_review))
        finally:
            try:oskill=signal.SIGTERM;__import__('os').killpg(proc.pid,oskill);proc.wait(timeout=10)
            except ProcessLookupError:pass
