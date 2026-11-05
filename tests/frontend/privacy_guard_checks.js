(async()=>{
 const results=[];const check=(name,condition)=>{results.push({name,passed:!!condition});if(!condition)throw Error(name);};
 const current={image_sha256:'a'.repeat(64),masking_revision:3};
 const ready={status:'no_candidates',ocr_completed:true,found:false,remasking_required:false,review_required:false,findings:[],...current};
 const cases=[['missing result',null],['pending',{...ready,status:'pending'}],['OCR failure',{...ready,status:'failed'}],['PII detected',{...ready,status:'review_required',findings:[{type:'phone'}]}],['needs review',{...ready,review_required:true}],['hash mismatch',{...ready,image_sha256:'b'.repeat(64)}],['version mismatch',{...ready,masking_revision:4}],['missing field',{...ready,ocr_completed:undefined}],['forged allow flag',{...ready,allowed:true,external_llm_allowed:true}],['passing fields still require server authority',ready]];
 let networkCalls=0;const originalFetch=window.fetch;window.fetch=()=>{networkCalls++;throw Error('network forbidden');};
 try {
   for(const [name,state] of cases)check('guard '+name,SafeContractPrivacyGuard.evaluatePrivacyState(state,current).allowed===false);
   check('actual STEP2 state remains blocked',(await SafeContractPrivacyGuard.evaluateCurrent()).allowed===false);
   check('guard emits no network requests',networkCalls===0);
 } finally {window.fetch=originalFetch;}
 return results;
})()
