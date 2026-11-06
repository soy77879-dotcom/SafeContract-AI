/* Development loopback only; cookies/CSRF are server-issued, never analysis approval. */
(() => {
  let csrf=null;
  async function call(path,body=null,headers={}) {
    if(location.protocol!=='http:' || !['localhost','127.0.0.1'].includes(location.hostname))throw Error('local_server_required');
    if(!csrf){const r=await fetch('/api/session',{credentials:'same-origin',redirect:'error'});if(!r.ok)throw Error();csrf=(await r.json()).csrf_token;}
    const options={credentials:'same-origin',redirect:'error',headers:{'X-Review-CSRF':csrf,...headers}};
    if(body!==null){options.method='POST';if(body instanceof FormData)options.body=body;else {options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}}
    const r=await fetch(path,options);if(!r.ok)throw Error('server_review_failed');return r.json();
  }
  window.ServerReview=Object.freeze({call,hash:async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),b=>b.toString(16).padStart(2,'0')).join('')});
  const button=document.querySelector('#server-ocr'),status=document.querySelector('#server-ocr-status');let sequence=0;
  window.addEventListener('safecontract:image-change',()=>{sequence++;status.textContent='이미지 변경됨 · 새 마스킹 PNG로 OCR을 다시 요청하세요.';});
  button.addEventListener('click',async()=>{
    const mine=++sequence;button.disabled=true;status.textContent='서버 픽셀 확인·개인정보 재탐지·OCR 처리 중입니다.';
    try {
      const input=SafeContractMasking.getRedetectionInput();const body=SafeContractMasking.prepareOCRUpload();body.append('mask_regions',JSON.stringify([input.maskRegions]));
      const ticket=await call('/api/masking/register',body);
      if(mine!==sequence || SafeContractMasking.getRedetectionInput().file!==input.file)return;
      const result=await call('/api/ocr',SafeContractMasking.prepareOCRUpload(),{'X-Mask-Ticket':ticket.mask_ticket});
      if(mine!==sequence)return;
      const doc=await call('/api/review-documents/'+encodeURIComponent(result.document_id));if(mine!==sequence)return;
      window.dispatchEvent(new CustomEvent('safecontract:server-document',{detail:doc}));
      status.textContent='실제 서버 OCR 완료. 아래에서 수정본 저장 후 각 조항의 확인을 기록하세요. 외부 전송은 차단됩니다.';
    } catch {if(mine===sequence)status.textContent='서버 OCR을 완료하지 못했습니다. 마스킹 PNG와 개발용 서버 실행 상태를 확인하세요.';}
    finally {button.disabled=false;}
  });
})();
