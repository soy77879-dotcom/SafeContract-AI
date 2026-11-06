(async()=>{
 const results=[];const check=(name,value)=>{results.push({name,passed:!!value});if(!value)throw Error(name);};
 const original=window.ServerReview;const fixture=structuredClone(globalThis.reviewFixture);
 fixture.server_context={document_version:1,image_sha256:'a'.repeat(64),review_challenges:Object.fromEntries(fixture.clauses.map(c=>[c.clause_id,'test-challenge']))};
 let finish,invalidations=0;
 window.ServerReview={hash:async()=> 'b'.repeat(64),call:async path=>{
   if(path.endsWith('/confirm'))return new Promise(resolve=>{finish=()=>{const saved=structuredClone(fixture);saved.clauses[0].status='user_confirmed';resolve(saved);};});
   if(path.endsWith('/invalidate')){invalidations++;const saved=structuredClone(fixture);saved.server_context.document_version=2;return saved;}
   return fixture;
 }};
 try {
   window.dispatchEvent(new CustomEvent('safecontract:server-document',{detail:fixture}));
   document.querySelector('.clause-card [data-action=review]').click();
   for(let i=0;i<100 && !finish;i++)await new Promise(r=>setTimeout(r,5));
   const text=document.querySelector('.clause-card textarea');text.value='검토 응답 대기 중 합성 수정';text.dispatchEvent(new Event('input'));
   finish();await new Promise(r=>setTimeout(r,20));
   check('server late confirmation cannot overwrite a new edit',document.querySelector('.clause-card textarea').value==='검토 응답 대기 중 합성 수정' && document.querySelector('#review-progress').textContent.includes('0/19'));
   check('server edit invalidates prior server review',invalidations===1);
   window.dispatchEvent(new Event('safecontract:image-change'));await new Promise(r=>setTimeout(r,20));
 } finally {window.ServerReview=original;}
 return results;
})()
