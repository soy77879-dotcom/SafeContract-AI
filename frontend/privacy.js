/* Local rescan only. No raw OCR text or external LLM transport. */
(() => {
  const messages = {
    pending: '개인정보 재탐지 대기 · 외부 전송 차단',
    running: '로컬 OCR 검사 중 · 외부 전송 차단',
    failed: '검사를 완료하지 못했습니다. 로컬 검사 서버 실행 여부를 확인하세요. 외부 전송은 차단됩니다.',
    review_required: '의심 항목이 있습니다. 해당 영역을 확인하고 다시 마스킹한 뒤 재검사하세요.',
    no_candidates: '의심 패턴을 찾지 못했지만 개인정보 보호를 보장하지 않습니다. 직접 검토가 필요하며 외부 전송은 계속 차단됩니다.'
  };
  const labels = {identifier:'식별번호',phone:'전화번호',email:'이메일',account_candidate:'계좌번호 의심',name_context:'이름 문맥',address_context:'주소 문맥',numeric_candidate:'숫자열 의심',ocr_uncertain:'OCR 불확실'};
  class PrivacyScan {
    #epoch=0; #abort=null; #state={status:'pending',external_llm_allowed:false};
    constructor(editor, onChange=()=>{}, transport=null) { this.editor=editor;this.onChange=onChange;this.transport=transport; }
    get state() { return structuredClone(this.#state); }
    #set(state) { const found=['no_candidates','review_required'].includes(state.status) ? !!state.findings?.length : null; this.#state={...state,found,remasking_required:found,external_llm_allowed:false,external_transfer_blocked:true,review_required:true};this.onChange(this.state); }
    reset() { this.#epoch++;this.#abort?.abort();this.#abort=null;this.#set({status:'pending'}); }
    async run() {
      this.reset(); const epoch=this.#epoch; this.#abort=new AbortController();const signal=this.#abort.signal;
      this.#set({status:'running'});
      try {
        const input=this.editor.redetectionInput(); // Reject originals / unexported / stale files.
        const bytes=await input.file.arrayBuffer();
        const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
        if(epoch!==this.#epoch)return;
        const form=this.editor.ocrFormData(input.file);
        form.append('image_sha256',hash);form.append('masking_revision',String(input.maskingRevision));form.append('mask_count',String(input.manualMaskCount));
        let value;
        if(this.transport) value=await this.transport(form,signal);
        else {
          if(location.protocol!=='http:' || !['localhost','127.0.0.1'].includes(location.hostname))throw new Error();
          const response=await fetch('/local/privacy-scan',{method:'POST',body:form,signal,headers:{'X-Privacy-Scan':'1'},redirect:'error',credentials:'omit'});
          if(!response.ok)throw new Error(); value=await response.json();
        }
        if(epoch!==this.#epoch)return;
        const current=this.editor.redetectionInput(input.file);
        if(current.maskingRevision!==input.maskingRevision || value.image_sha256!==hash || value.masking_revision!==input.maskingRevision ||
           value.ocr_completed!==true || !['review_required','no_candidates'].includes(value.status) ||
           value.external_llm_allowed!==false || value.external_transfer_blocked!==true || !Array.isArray(value.findings))throw new Error();
        const findings=value.findings.map(f=>{
          if(!Object.hasOwn(labels,f.type) || !['line_index','start','end'].every(k=>Number.isInteger(f[k]) && f[k]>=0) || f.end<f.start)throw new Error();
          return {type:f.type,line_index:f.line_index,start:f.start,end:f.end};
        });
        if((findings.length>0)!==(value.status==='review_required'))throw new Error();
        this.#set({status:value.status,image_sha256:hash,masking_revision:input.maskingRevision,findings,ocr_completed:true});
      } catch { if(epoch===this.#epoch)this.#set({status:'failed',ocr_completed:false}); }
    }
  }
  window.LocalPrivacy=Object.freeze({PrivacyScan,messages:Object.freeze(messages),labels:Object.freeze(labels)});
})();
