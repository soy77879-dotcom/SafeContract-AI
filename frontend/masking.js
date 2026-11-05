/* Manual pixel masking only. No network, OCR, or automatic privacy detection. */
(() => {
  class MaskEditor {
    #image = null; #original = null; #file = null; #generation = 0;
    #revision = 0; #confirmed = false; #rectangles = [];
    constructor(canvas, onChange = () => {}) {
      this.canvas = canvas; this.onChange = onChange;
    }
    get count() { return this.#rectangles.length; }
    get ready() { return !!this.#image; }
    get confirmed() { return this.#confirmed; }
    get output() { return this.#file; }
    #invalidate() { this.#revision++; this.#file = null; this.#confirmed = false; this.onChange(); }
    clear() {
      this.#generation++; this.#image = null; this.#original = null; this.#rectangles = [];
      this.canvas.width = this.canvas.height = 0; this.#invalidate();
    }
    async load(file) {
      this.clear(); const generation = this.#generation;
      if (!(file instanceof File) || !/\.(jpe?g|png)$/i.test(file.name) ||
          !['image/jpeg', 'image/png', ''].includes(file.type)) throw new Error('JPG/JPEG/PNG 파일을 선택하세요.');
      if (!file.size || file.size > 10 * 1024 * 1024) throw new Error('파일은 0바이트보다 크고 10MiB 이하여야 합니다.');
      const header = new Uint8Array(await file.slice(0, 8).arrayBuffer());
      const png = [137,80,78,71,13,10,26,10].every((v,i) => header[i] === v);
      const jpeg = header[0] === 255 && header[1] === 216 && header[2] === 255;
      if (!png && !jpeg) throw new Error('실제 이미지 형식을 확인할 수 없습니다.');
      if ((png && !/\.png$/i.test(file.name)) || (jpeg && !/\.jpe?g$/i.test(file.name))) throw new Error('확장자와 이미지 형식이 다릅니다.');
      const url = URL.createObjectURL(file); const image = new Image();
      try {
        await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = () => reject(new Error('이미지를 읽을 수 없습니다.')); image.src = url; });
        if (generation !== this.#generation) throw new DOMException('이미지가 교체됐습니다.', 'AbortError');
        if (image.naturalWidth * image.naturalHeight > 20000000) throw new Error('이미지는 최대 2천만 픽셀입니다.');
        this.#image = image; this.#original = file;
        this.canvas.width = image.naturalWidth; this.canvas.height = image.naturalHeight;
        this.#render(); this.onChange();
      } finally { URL.revokeObjectURL(url); }
    }
    point(clientX, clientY) {
      const b = this.canvas.getBoundingClientRect();
      if (!b.width || !b.height) throw new Error('표시된 이미지가 없습니다.');
      return { x: Math.max(0, Math.min(this.canvas.width, (clientX-b.left)*this.canvas.width/b.width)),
        y: Math.max(0, Math.min(this.canvas.height, (clientY-b.top)*this.canvas.height/b.height)) };
    }
    add(a, b) {
      if (!this.ready || Math.abs(a.x-b.x)<1 || Math.abs(a.y-b.y)<1) return false;
      const x = Math.max(0, Math.floor(Math.min(a.x,b.x))), y = Math.max(0, Math.floor(Math.min(a.y,b.y)));
      const right = Math.min(this.canvas.width, Math.ceil(Math.max(a.x,b.x)));
      const bottom = Math.min(this.canvas.height, Math.ceil(Math.max(a.y,b.y)));
      if (![x,y,right,bottom].every(Number.isFinite) || right<=x || bottom<=y) return false;
      this.#rectangles.push({x,y,width:right-x,height:bottom-y}); this.#render(); this.#invalidate(); return true;
    }
    undo() { if (this.count) { this.#rectangles.pop(); this.#render(); this.#invalidate(); } }
    reset() { if (this.ready) { this.#rectangles = []; this.#render(); this.#invalidate(); } }
    confirm(value) { this.#file = null; this.#revision++; this.#confirmed = value === true && this.count > 0; this.onChange(); }
    #render() {
      const ctx = this.canvas.getContext('2d');
      ctx.clearRect(0,0,this.canvas.width,this.canvas.height);
      // Flatten transparency; export is a newly encoded raster, not original bytes.
      ctx.fillStyle = '#fff'; ctx.fillRect(0,0,this.canvas.width,this.canvas.height);
      ctx.drawImage(this.#image,0,0); ctx.fillStyle = '#000';
      for (const r of this.#rectangles) ctx.fillRect(r.x,r.y,r.width,r.height);
    }
    async exportFile() {
      if (!this.ready || !this.count || !this.#confirmed) throw new Error('영역을 가린 뒤 수동 확인을 체크하세요.');
      const revision = this.#revision;
      const blob = await new Promise(resolve => this.canvas.toBlob(resolve,'image/png'));
      if (revision !== this.#revision || !this.#confirmed) throw new Error('편집 상태가 바뀌었습니다. 다시 생성하세요.');
      if (!blob || blob.size > 10*1024*1024) throw new Error('출력 이미지 생성 실패 또는 10MiB 초과입니다.');
      this.#file = new File([blob], 'masked-contract.png', {type:'image/png'});
      return this.#file;
    }
    redetectionInput(file = this.#file) {
      if (!file || file !== this.#file || file === this.#original || !this.#confirmed || !this.count) throw new Error('현재 생성된 마스킹 파일만 사용할 수 있습니다.');
      return Object.freeze({file, maskingRevision:this.#revision, manualMaskCount:this.count,
        privacyScanStatus:'pending', needsPrivacyReview:true, externalLLMAllowed:false});
    }
    ocrFormData(file) {
      const input = this.redetectionInput(file);
      const form = new FormData(); form.append('files',input.file,input.file.name); return form;
    }
  }
  window.ManualMasking = Object.freeze({MaskEditor});
})();
