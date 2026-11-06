(() => {
  const $ = selector => document.querySelector(selector);
  const canvas = $('#mask-canvas'), status = $('#status');
  let originalUrl = null, resultUrl = null, drag = null, loadSequence = 0;
  let privacy=null;
  const editor = new ManualMasking.MaskEditor(canvas, update);
  privacy=new LocalPrivacy.PrivacyScan(editor, state => {
    $('#privacy-status').textContent=LocalPrivacy.messages[state.status];
    $('#privacy-findings').replaceChildren();
    for(const f of state.findings || []) {
      const item=document.createElement('li');
      item.textContent=`${LocalPrivacy.labels[f.type]} · OCR ${f.line_index+1}번째 줄, 문자 범위 ${f.start}–${f.end} (끝 제외). 원문 이미지에서 확인하세요.`;
      $('#privacy-findings').append(item);
    }
    $('#privacy-scan').disabled=!editor.output || state.status==='running';
  });
  function message(text, error=false) { status.textContent=text; status.dataset.error=String(error); }
  function clearOutput() {
    privacy?.reset();
    $('#privacy-scan').disabled=true;
    if (resultUrl) URL.revokeObjectURL(resultUrl); resultUrl=null;
    $('#masked-preview').removeAttribute('src'); $('#result').hidden=true;
    $('#download').removeAttribute('href');
  }
  function update() {
    window.dispatchEvent(new Event('safecontract:image-change'));
    clearOutput(); $('#manual-confirm').checked=editor.confirmed;
    $('#mask-count').textContent=`가린 영역 ${editor.count}개 · 개인정보 재탐지 미완료`;
    $('#undo').disabled=!editor.count; $('#reset').disabled=!editor.count;
    $('#manual-confirm').disabled=!editor.count;
    $('#export').disabled=!editor.confirmed || !editor.count;
    if (editor.ready) message('수동 편집 중입니다. 가릴 영역을 확인하세요. 개인정보 보호 완료 상태가 아닙니다.');
  }
  function cancelDrag() { drag=null; $('#selection').hidden=true; }
  function resize() {
    cancelDrag();
    if (!editor.ready) return;
    const fit=Math.min(1,$('#canvas-viewport').clientWidth/canvas.width);
    canvas.style.width=`${canvas.width*fit*Number($('#zoom').value)/100}px`;
    $('#zoom-value').textContent=`${$('#zoom').value}%`;
  }
  async function loadFile() {
    const sequence=++loadSequence; cancelDrag(); clearOutput(); editor.clear();
    if (originalUrl) URL.revokeObjectURL(originalUrl); originalUrl=null;
    $('#preview').removeAttribute('src'); $('#preview').hidden=true; $('#workspace').hidden=true;
    const file=$('#contract-image').files[0];
    $('#file-name').textContent=file ? file.name : '선택한 파일 없음';
    if (!file) { message('계약서 이미지를 선택해 주세요.'); return; }
    message('이미지를 확인하고 있습니다.');
    try {
      await editor.load(file); if (sequence!==loadSequence) return;
      originalUrl=URL.createObjectURL(file); $('#preview').src=originalUrl; $('#preview').hidden=false;
      $('#workspace').hidden=false; $('#zoom').value='100'; resize();
      message('원본이 로드됐습니다. 개인정보 영역을 드래그해 가려 주세요.');
    } catch (error) { if (sequence===loadSequence) message(error.message,true); }
  }
  canvas.addEventListener('pointerdown', event => {
    if (!editor.ready) return;
    if (drag || !event.isPrimary || event.button!==0) { cancelDrag(); return; }
    editor.confirm(false); event.preventDefault(); canvas.setPointerCapture(event.pointerId);
    drag={id:event.pointerId,start:editor.point(event.clientX,event.clientY)};
  });
  canvas.addEventListener('pointermove', event => {
    if (!drag || drag.id!==event.pointerId) return;
    const end=editor.point(event.clientX,event.clientY), b=canvas.getBoundingClientRect(), a=drag.start;
    const overlay=$('#selection'); overlay.hidden=false;
    Object.assign(overlay.style,{left:`${Math.min(a.x,end.x)*b.width/canvas.width}px`,top:`${Math.min(a.y,end.y)*b.height/canvas.height}px`,
      width:`${Math.abs(a.x-end.x)*b.width/canvas.width}px`,height:`${Math.abs(a.y-end.y)*b.height/canvas.height}px`});
  });
  canvas.addEventListener('pointerup', event => {
    if (!drag || drag.id!==event.pointerId) return;
    const start=drag.start; cancelDrag();
    editor.add(start,editor.point(event.clientX,event.clientY));
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointercancel',cancelDrag);
  canvas.addEventListener('lostpointercapture',cancelDrag);
  $('#cancel-selection').addEventListener('click',cancelDrag);
  document.addEventListener('keydown',event => { if (event.key==='Escape') cancelDrag(); });
  $('#undo').addEventListener('click',() => { cancelDrag();editor.undo(); });
  $('#reset').addEventListener('click',() => { cancelDrag();editor.reset(); });
  $('#zoom').addEventListener('input',resize); window.addEventListener('resize',resize);
  $('#manual-confirm').addEventListener('change',event => editor.confirm(event.target.checked));
  $('#export').addEventListener('click',async () => {
    $('#export').disabled=true;
    try {
      const file=await editor.exportFile();
      clearOutput(); resultUrl=URL.createObjectURL(file); $('#masked-preview').src=resultUrl;
      $('#download').href=resultUrl; $('#result').hidden=false; $('#privacy-scan').disabled=false;
      message('새 PNG를 생성했습니다. OCR 개인정보 재탐지 대기 중이며 외부 LLM 전송은 허용하지 않습니다.');
    } catch(error) { message(error.message,true); }
    finally { $('#export').disabled=!editor.confirmed; }
  });
  $('#privacy-scan').addEventListener('click',()=>privacy.run());
  $('#contract-image').addEventListener('change',loadFile);
  $('#file-form').addEventListener('submit',event => { event.preventDefault(); if (!editor.ready) loadFile(); else message('현재 이미지가 로드돼 있습니다. 마스킹 편집을 이어가세요.'); });
  // STEP 2 integration hook: returns ONLY the current exported PNG, never the input File.
  window.SafeContractMasking = Object.freeze({
    getRedetectionInput:() => editor.redetectionInput(),
    prepareOCRUpload:() => editor.ocrFormData(editor.output),
    getPrivacyScanState:()=>privacy.state,
    invalidatePrivacyForTextEdit:()=>privacy.reset(),
    externalLLMAllowed:false
  });
  window.addEventListener('pagehide',() => { loadSequence++;cancelDrag();editor.clear(); if(originalUrl)URL.revokeObjectURL(originalUrl);clearOutput(); });
})();
