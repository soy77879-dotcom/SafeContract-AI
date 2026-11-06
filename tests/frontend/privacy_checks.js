(async()=>{
 const results=[];const check=(name,value)=>{results.push({name,passed:!!value});if(!value)throw Error(name);};
 const canvas=document.createElement('canvas');canvas.width=100;canvas.height=100;
 canvas.getContext('2d').fillRect(0,0,100,100);
 const original=new File([await new Promise(r=>canvas.toBlob(r))],'original.png',{type:'image/png'});
 let scan;const editor=new ManualMasking.MaskEditor(canvas,()=>scan?.reset());
 const response=form=>({status:'no_candidates',findings:[],image_sha256:form.get('image_sha256'),masking_revision:Number(form.get('masking_revision')),ocr_completed:true,external_llm_allowed:false,external_transfer_blocked:true});
 let calls=0;scan=new LocalPrivacy.PrivacyScan(editor,()=>{},async form=>{calls++;return response(form);});
 await editor.load(original);await scan.run();check('privacy rejects unmasked input before transport',scan.state.status==='failed' && calls===0);
 editor.add({x:0,y:0},{x:10,y:10});editor.confirm(true);await editor.exportFile();await scan.run();
 check('privacy no candidates stays blocked',scan.state.status==='no_candidates' && scan.state.external_llm_allowed===false && scan.state.review_required);
 editor.add({x:20,y:20},{x:30,y:30});check('image edit invalidates scan',scan.state.status==='pending' && !scan.state.image_sha256);
 editor.confirm(true);await editor.exportFile();
 scan.transport=async form=>({...response(form),image_sha256:'wrong'});await scan.run();check('wrong image hash rejected',scan.state.status==='failed');
 scan.transport=async form=>({...response(form),masking_revision:999});await scan.run();check('wrong revision rejected',scan.state.status==='failed');
 scan.transport=async()=>{throw Error('SYNTHETIC_PRIVATE_SENTINEL');};await scan.run();check('failed scan hides exception and blocks',scan.state.status==='failed' && !JSON.stringify(scan.state).includes('SYNTHETIC'));
 scan.transport=async form=>({...response(form),status:'review_required',findings:[{type:'email',line_index:0,start:0,end:12,text:'SYNTHETIC_PRIVATE_SENTINEL'}]});
 await scan.run();check('findings expose positions only',scan.state.status==='review_required' && !JSON.stringify(scan.state).includes('SYNTHETIC'));
 let resolve;scan.transport=form=>new Promise(r=>{resolve=()=>r(response(form));});const pending=scan.run();
 while(!resolve)await new Promise(r=>setTimeout(r,5));editor.reset();resolve();await pending;
 check('late response cannot approve edited image',scan.state.status==='pending');
 return results;
})()
