(() => {
  const $=s=>document.querySelector(s);let documentState=null,epoch=0,serverHandle=null,pending=Promise.resolve(),dirty=false;
  const status=$('#review-status'),list=$('#clause-list');
  function binding(h=serverHandle) {return {document_id:h.document_id,document_version:h.context.document_version,image_sha256:h.context.image_sha256};}
  function invalidatePrivacy(kind) {
    window.SafeContractMasking?.invalidatePrivacyForTextEdit();
    if(serverHandle && kind==='edit' && !dirty) {
      dirty=true;documentState.invalidateReviews();const h=serverHandle;
      pending=ServerReview.call('/api/review-documents/'+encodeURIComponent(h.document_id)+'/invalidate',binding(h)).then(doc=>{if(serverHandle===h)h.context=doc.server_context;}).catch(()=>{h.failed=true;status.textContent='서버 상태 갱신 실패. 서버 저장본을 다시 불러오세요.';});
      for(const card of list.querySelectorAll('.clause-card'))rowStatus(card,card.dataset.clauseId);
    }
  }
  function serverLoad(doc) {
    documentState=new LocalClauseReview.ReviewDocument(doc,invalidatePrivacy);
    serverHandle={document_id:doc.document_id,context:doc.server_context};dirty=false;
    for(const c of doc.clauses)if(c.status==='user_confirmed')documentState.review(c.clause_id);
    render();status.textContent='서버 저장본 로드 완료 · 사용자 확인 기록이며 분석 승인은 아닙니다.';
  }
  window.addEventListener('safecontract:server-document',event=>{epoch++;serverLoad(event.detail);});
  function progress() {
    const p=documentState?.progress || {reviewed:0,total:0};
    $('#review-progress').textContent=`사용자 확인 ${p.reviewed}/${p.total}개 · 서버 승인 없음`;
    $('#review-meter').max=p.total || 1;$('#review-meter').value=p.reviewed;
    $('#save-review').disabled=!documentState;$('#server-save').disabled=!serverHandle;$('#server-reload').disabled=!serverHandle;
  }
  function rowStatus(card,id) {
    const c=documentState.snapshot.clauses.find(c=>c.clause_id===id);
    card.querySelector('.clause-status').textContent=c.reviewed_by_user ? '사용자 검토 완료 · 법률적 안전 판정 아님' : 'needs_review · 직접 확인 필요';
    card.querySelector('[data-action="review"]').disabled=!c.edited_text.trim() || c.reviewed_by_user;
    card.querySelector('.diff-status').textContent=c.raw_text===c.edited_text ? '원문과 동일' : '원문과 다름 · 수정본을 확인하세요.';
    progress();
  }
  function render() {
    list.replaceChildren();if(!documentState){progress();return;}
    const doc=documentState.snapshot;
    $('#review-document').textContent=`문서 ${doc.document_id} · 총 ${doc.page_count}페이지 · 로컬 OCR 수정본`;
    for(const c of doc.clauses) {
      const card=document.createElement('article');card.className='clause-card';card.dataset.clauseId=c.clause_id;
      const title=document.createElement('h3');title.textContent=`${c.clause_id} · 페이지 ${c.pages.join(', ')}`;card.append(title);
      const state=document.createElement('p');state.className='clause-status';card.append(state);
      const compare=document.createElement('div');compare.className='clause-compare';
      const original=document.createElement('div');const label=document.createElement('h4');label.textContent='원본 OCR · 변경 불가';const pre=document.createElement('pre');pre.textContent=c.raw_text;original.append(label,pre);
      const edited=document.createElement('div');const editLabel=document.createElement('label');editLabel.htmlFor=`edit-${c.clause_id}`;editLabel.textContent='사용자 수정본';
      const input=document.createElement('textarea');input.id=editLabel.htmlFor;input.value=c.edited_text;input.maxLength=50000;input.rows=8;input.spellcheck=false;
      input.addEventListener('input',()=>{documentState.edit(c.clause_id,input.value);rowStatus(card,c.clause_id);});edited.append(editLabel,input);compare.append(original,edited);card.append(compare);
      const diff=document.createElement('p');diff.className='diff-status';card.append(diff);
      const source=document.createElement('details');const summary=document.createElement('summary');summary.textContent=`원문 출처 · OCR 줄 ${c.source_lines.length}개`;const refs=document.createElement('pre');
      refs.textContent=c.source_lines.length ? c.source_lines.map(l=>`페이지 ${l.page} / ${l.line_id} / ${l.polygon===null ? '좌표 없음' : 'OCR 입력 픽셀 '+JSON.stringify(l.polygon)}`).join('\n') : '원문 위치 좌표 없음';source.append(summary,refs);card.append(source);
      const actions=document.createElement('div');actions.className='actions';
      for(const [action,text] of [['cancel','수정 취소 · OCR 원문 복원'],['review','이 조항 검토 완료']]) {
        const button=document.createElement('button');button.type='button';button.dataset.action=action;button.textContent=text;
        button.addEventListener('click',async()=>{
          if(action==='review' && serverHandle) {
            if(dirty || serverHandle.failed){status.textContent='먼저 수정본을 서버에 저장한 뒤 조항 확인을 기록하세요.';return;}
            const h=serverHandle,localRevision=documentState.snapshot.document_revision;button.disabled=true;
            try {const doc=await ServerReview.call('/api/review-documents/'+encodeURIComponent(h.document_id)+'/confirm',{
              ...binding(h),clause_id:c.clause_id,challenge:h.context.review_challenges[c.clause_id],text_sha256:await ServerReview.hash(input.value)});
              if(serverHandle===h && !dirty && documentState.snapshot.document_revision===localRevision)serverLoad(doc);
            }catch {status.textContent='서버 확인 기록 실패. 버전이 바뀌었는지 재조회하세요.';button.disabled=false;}return;
          }
          if(action==='cancel'){documentState.cancel(c.clause_id);input.value=c.raw_text;}else documentState.review(c.clause_id);rowStatus(card,c.clause_id);
        });actions.append(button);
      }
      card.append(actions);list.append(card);rowStatus(card,c.clause_id);
    }
    progress();
  }
  function clear() {epoch++;if(serverHandle){const h=serverHandle;pending.then(()=>ServerReview.call('/api/review-documents/'+encodeURIComponent(h.document_id)+'/invalidate',binding(h))).catch(()=>{});}serverHandle=null;dirty=false;documentState=null;list.replaceChildren();$('#review-document').textContent='';$('#review-file').value='';status.textContent='이미지·마스킹 상태가 바뀌어 조항 검토를 초기화했습니다. 대응하는 OCR 검토 파일을 다시 여세요.';progress();}
  window.addEventListener('safecontract:image-change',clear);
  $('#review-file').addEventListener('change',async event=>{
    const mine=++epoch;serverHandle=null;dirty=false;documentState=null;render();invalidatePrivacy();const file=event.target.files[0];
    if(!file)return;
    try {
      if(file.size>5*1024*1024)throw Error();
      const value=JSON.parse(await file.text());if(mine!==epoch)return;
      documentState=new LocalClauseReview.ReviewDocument(value,invalidatePrivacy);render();
      status.textContent='로컬 OCR 파일을 열었습니다. 저장된 검토 완료 표시는 재사용하지 않습니다. 원문과 수정본을 직접 비교하세요.';
    } catch {if(mine===epoch){documentState=null;render();status.textContent='검토 파일의 형식·조항 ID·페이지·원문 연결을 확인하세요.';}}
  });
  $('#save-review').addEventListener('click',()=>{
    if(!documentState)return;
    const file=new Blob([JSON.stringify(documentState.snapshot,null,2)],{type:'application/json;charset=utf-8'});
    const url=URL.createObjectURL(file),a=document.createElement('a');a.href=url;a.download='local-ocr-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    status.textContent='로컬 수정본 저장을 요청했습니다. 개인정보가 포함될 수 있으므로 공유·Git 업로드하지 마세요. 서버에는 저장하지 않았습니다.';
  });
  $('#server-save').addEventListener('click',async()=>{
    const h=serverHandle;if(!h || !documentState)return;
    const version=documentState.snapshot.document_revision;$('#server-save').disabled=true;
    try {await pending;if(h.failed || serverHandle!==h)throw Error();
      const doc=await ServerReview.call('/api/review-documents/'+encodeURIComponent(h.document_id)+'/draft',{
        ...binding(h),clauses:documentState.snapshot.clauses.map(c=>({clause_id:c.clause_id,raw_text:c.raw_text,edited_text:c.edited_text}))});
      if(serverHandle===h && documentState.snapshot.document_revision===version)serverLoad(doc);
      else if(serverHandle===h){h.failed=true;status.textContent='저장 중 수정되었습니다. 서버본을 재조회하고 변경을 다시 확인하세요.';}
    }catch {status.textContent='서버 저장 실패. 문서 버전과 원문 연결을 확인하세요.';}finally{progress();}
  });
  $('#server-reload').addEventListener('click',async()=>{const h=serverHandle;if(!h)return;try{await pending;const doc=await ServerReview.call('/api/review-documents/'+encodeURIComponent(h.document_id));if(serverHandle===h)serverLoad(doc);}catch{status.textContent='서버 저장본을 조회하지 못했습니다.';}});
  window.addEventListener('pagehide',clear);progress();
})();
