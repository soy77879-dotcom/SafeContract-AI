(async()=>{
 const results=[];const check=(name,v)=>{results.push({name,passed:!!v});if(!v)throw Error(name);};
 const fixture=globalThis.reviewFixture;const before=JSON.stringify(fixture);let changes=0;
 const doc=new LocalClauseReview.ReviewDocument(fixture,()=>changes++);const first=fixture.clauses[0];
 check('review cached actual OCR 19 IDs',doc.snapshot.clauses.map(c=>c.clause_id).join()===Array.from({length:19},(_,i)=>'C'+String(i+1).padStart(3,'0')).join());
 check('review retains 5 page document and clause pages',doc.snapshot.page_count===5 && JSON.stringify(doc.snapshot.clauses.map(c=>c.pages))===JSON.stringify(fixture.clauses.map(c=>c.pages)));
 check('review initial needs review',doc.progress.reviewed===0 && doc.snapshot.clauses.every(c=>c.status==='needs_review'));
 doc.edit('C001','합성 수정 문장');check('review edit preserves raw',doc.snapshot.clauses[0].raw_text===first.raw_text && doc.snapshot.clauses[0].edited_text==='합성 수정 문장');
 doc.review('C001');check('review explicit human action only',doc.progress.reviewed===1 && !doc.snapshot.server_approved);
 doc.edit('C001','다른 합성 문장');check('review edit revokes completion',doc.progress.reviewed===0);
 doc.review('C001');doc.cancel('C001');check('review cancel restores raw without approval',doc.snapshot.clauses[0].edited_text===first.raw_text && doc.progress.reviewed===0);
 check('review source fixture immutable',JSON.stringify(fixture)===before);
 const snapshot=doc.snapshot;snapshot.clauses[0].raw_text='tampered';check('review returned snapshots isolated',doc.snapshot.clauses[0].raw_text===first.raw_text);
 doc.review('C001');const imported=new LocalClauseReview.ReviewDocument(doc.snapshot);check('review saved approval not trusted on reload',imported.progress.reviewed===0);
 check('review actions invalidate privacy callback',changes>=6 && doc.snapshot.privacy_scan_status==='pending');
 function rejects(value){try{new LocalClauseReview.ReviewDocument(value);return false}catch{return true;}}
 const duplicate=structuredClone(fixture);duplicate.clauses[1].clause_id='C001';check('review duplicate ID rejected',rejects(duplicate));
 const missing=structuredClone(fixture);missing.clauses.pop();check('review missing ID rejected',rejects(missing));
 const badPage=structuredClone(fixture);badPage.clauses[0].pages=[99];badPage.clauses[0].page=99;check('review invalid page rejected',rejects(badPage));
 doc.edit('C001','');let empty=false;try{doc.review('C001')}catch{empty=true;}check('review empty text cannot be approved',empty);
 const dt=new DataTransfer();dt.items.add(new File([JSON.stringify(fixture)],'review.json',{type:'application/json'}));
 const input=document.querySelector('#review-file');input.files=dt.files;input.dispatchEvent(new Event('change'));
 for(let i=0;i<100 && document.querySelectorAll('.clause-card').length!==19;i++)await new Promise(r=>setTimeout(r,10));
 check('review UI 19 clauses displayed',document.querySelectorAll('.clause-card').length===19);
 const card=document.querySelector('.clause-card');const area=card.querySelector('textarea');
 card.querySelector('[data-action="review"]').click();check('review UI progress explicit confirmation',document.querySelector('#review-progress').textContent.includes('1/19'));
 area.value='합성 수정 <img src=x onerror=alert(1)>';area.dispatchEvent(new Event('input'));
 check('review UI edit resets progress',document.querySelector('#review-progress').textContent.includes('0/19'));
 check('review UI preserves raw and renders text safely',card.querySelector('pre').textContent===first.raw_text && !document.querySelector('#clause-list img'));
 check('review UI invalidates actual privacy state',SafeContractMasking.getPrivacyScanState().status==='pending');
 card.querySelector('[data-action="cancel"]').click();check('review UI cancel restores text',area.value===first.raw_text);
 card.querySelector('[data-action="review"]').click();check('review UI re-review works',document.querySelector('#review-progress').textContent.includes('1/19'));
 for(const c of doc.snapshot.clauses) {if(!c.edited_text.trim())doc.cancel(c.clause_id);doc.review(c.clause_id);}
 check('review full progress remains local only',doc.progress.reviewed===19 && !doc.snapshot.server_approved && !doc.snapshot.external_llm_allowed);
 let savedBlob;const create=URL.createObjectURL,click=HTMLAnchorElement.prototype.click;
 try {URL.createObjectURL=blob=>{savedBlob=blob;return 'blob:review-test';};HTMLAnchorElement.prototype.click=()=>{};document.querySelector('#save-review').click();}
 finally {URL.createObjectURL=create;HTMLAnchorElement.prototype.click=click;}
 const saved=JSON.parse(await savedBlob.text());
 check('review saved JSON preserves raw and explicit local review',saved.clauses[0].raw_text===first.raw_text && saved.clauses[0].reviewed_by_user===true && saved.server_approved===false);
 check('review document version advances on user actions',saved.document_revision>fixture.document_revision && doc.snapshot.document_revision>saved.document_revision);
 check('review no persistent storage',!localStorage.getItem('local-ocr-review'));
 return results;
})()
