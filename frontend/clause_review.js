/* In-memory local review only. Imported approval fields are never trusted. */
(() => {
  class ReviewDocument {
    #source; #edits; #revision; #changed;
    constructor(value,onChange=()=>{}) {
      if(!value || value.format!=='safecontract-local-review-v1' || typeof value.document_id!=='string' || !value.document_id ||
         !Number.isSafeInteger(value.page_count) || value.page_count<1 || !Array.isArray(value.clauses) || !value.clauses.length || value.clauses.length>200 ||
         !Array.isArray(value.expected_clause_ids) || !Number.isSafeInteger(value.document_revision) || value.document_revision<0)throw Error('invalid_review');
      const ids=value.clauses.map(c=>c.clause_id);
      if(new Set(ids).size!==ids.length || ids.some((id,i)=>!/^C\d{3,}$/.test(id) || value.expected_clause_ids[i]!==id) || ids.length!==value.expected_clause_ids.length)throw Error('invalid_ids');
      for(const c of value.clauses) {
        if(typeof c.raw_text!=='string' || !c.raw_text.trim() || c.raw_text.length>50000 || typeof c.edited_text!=='string' || c.edited_text.length>50000 ||
           !Array.isArray(c.pages) || !c.pages.length || c.page!==c.pages[0] || new Set(c.pages).size!==c.pages.length || c.pages.some(p=>!Number.isInteger(p)||p<1||p>value.page_count) || !Array.isArray(c.source_lines))throw Error('invalid_clause');
        if(c.source_lines.length && c.source_lines.map(l=>l.text+'\n').join('')!==c.raw_text)throw Error('invalid_source');
        for(const l of c.source_lines) {
          if(!c.pages.includes(l.page) || typeof l.line_id!=='string' || typeof l.text!=='string' ||
             (l.polygon!==null && (!Array.isArray(l.polygon)||l.polygon.length<3||l.polygon.some(p=>!Array.isArray(p)||p.length!==2||p.some(v=>!Number.isFinite(v))))))throw Error('invalid_source');
        }
      }
      this.#source=structuredClone(value);this.#revision=value.document_revision+1;this.#changed=onChange;
      this.#edits=new Map(value.clauses.map(c=>[c.clause_id,{edited_text:c.edited_text,clause_revision:0,status:'needs_review',reviewed_by_user:false}]));
    }
    #entry(id) {const entry=this.#edits.get(id);if(!entry)throw Error('unknown_clause');return entry;}
    #touch(entry) {entry.clause_revision++;entry.status='needs_review';entry.reviewed_by_user=false;this.#revision++;this.#changed('edit');}
    edit(id,text) {if(typeof text!=='string'||text.length>50000)throw Error('invalid_text');const e=this.#entry(id);if(e.edited_text===text)return;e.edited_text=text;this.#touch(e);}
    cancel(id) {const e=this.#entry(id);e.edited_text=this.#source.clauses.find(c=>c.clause_id===id).raw_text;this.#touch(e);}
    review(id) {const e=this.#entry(id);if(!e.edited_text.trim())throw Error('empty_text');e.status='reviewed';e.reviewed_by_user=true;this.#revision++;this.#changed('review');}
    invalidateReviews() {for(const e of this.#edits.values()){e.status='needs_review';e.reviewed_by_user=false;}this.#revision++;}
    get snapshot() {return {...structuredClone(this.#source),document_revision:this.#revision,server_approved:false,privacy_scan_status:'pending',external_llm_allowed:false,
      clauses:this.#source.clauses.map(c=>({...structuredClone(c),...this.#edits.get(c.clause_id)}))};}
    get progress() {return {reviewed:[...this.#edits.values()].filter(c=>c.reviewed_by_user).length,total:this.#edits.size};}
  }
  window.LocalClauseReview=Object.freeze({ReviewDocument});
})();
