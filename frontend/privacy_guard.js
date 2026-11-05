/* Advisory browser gate. Server approval is never inferred from client flags. */
(() => {
  function evaluatePrivacyState(state, current) {
    const deny=reason=>({allowed:false,reason,externalLLMAllowed:false});
    if(!state || !current)return deny('missing_state');
    if(state.status!=='no_candidates')return deny('scan_not_clear');
    if(state.ocr_completed!==true || state.found!==false || state.remasking_required!==false || state.review_required!==false ||
       !Array.isArray(state.findings) || state.findings.length)return deny('unreviewed_or_incomplete');
    if(!/^[a-f0-9]{64}$/.test(state.image_sha256 || '') || state.image_sha256!==current.image_sha256)return deny('image_mismatch');
    if(!Number.isSafeInteger(state.masking_revision) || state.masking_revision<1 || state.masking_revision!==current.masking_revision)return deny('revision_mismatch');
    // No JS object can attest server authorization. Even apparently passing states only
    // qualify for a server check; this module never authorizes an external network call.
    return deny('server_authorization_required');
  }
  async function evaluateCurrent() {
    try {
      const input=SafeContractMasking.getRedetectionInput();
      const digest=await crypto.subtle.digest('SHA-256',await input.file.arrayBuffer());
      const now=SafeContractMasking.getRedetectionInput();
      if(now.file!==input.file || now.maskingRevision!==input.maskingRevision)return {allowed:false,reason:'image_changed',externalLLMAllowed:false};
      return evaluatePrivacyState(SafeContractMasking.getPrivacyScanState(),{
        image_sha256:Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join(''),masking_revision:input.maskingRevision});
    } catch { return {allowed:false,reason:'missing_current_image',externalLLMAllowed:false}; }
  }
  window.SafeContractPrivacyGuard=Object.freeze({evaluatePrivacyState,evaluateCurrent});
})();
