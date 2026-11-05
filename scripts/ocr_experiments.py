"""D-7 local image OCR experiment runner. Never repairs OCR strings using GT."""
import argparse
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import statistics
import time

try:
    from .ocr_evaluation import evaluate_corpus, normalize_text
except ImportError:
    from ocr_evaluation import evaluate_corpus, normalize_text

ALIGNMENT_VERSION = 'pdf-regions-v2-row-height-0.65'
ROOT = Path(__file__).resolve().parents[1]
DET = 'PP-OCRv5_server_det'
REC = 'korean_PP-OCRv5_mobile_rec'
EXPERIMENTS = {
    'E00': ('baseline', {}),
    'E01': ('resize_1.5', {}),
    'E02': ('contrast_1.5', {}),
    'E03': ('unsharp', {}),
    'E04': ('otsu', {}),
    'E05': ('baseline', {'text_det_limit_side_len': 1600, 'text_det_limit_type': 'max'}),
    'E06': ('grayscale', {}),
    'E07': ('median_3', {}),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, data):
    # Outputs are created only in a fresh experiment/run directory.
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def regions_for_page(clauses, page):
    result = []
    for c in clauses:
        if c['page'] != page:
            continue
        if c['verification_status'] != 'verified':
            raise ValueError('Only human-verified GT is accepted')
        boxes = [b['bbox'] for b in c['source_blocks']]
        result.append({'clause_id': c['clause_id'], 'bbox': [min(b[0] for b in boxes),
                      min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]})
    if not result:
        raise ValueError('No GT on requested page')
    return result


def assign_lines(lines, regions, image_size, pdf_size):
    """Geometry-only matching. No GT text search, replacements or confidence filtering."""
    assigned = {r['clause_id']: [] for r in regions}
    excluded, ambiguous = [], []
    sx, sy = pdf_size[0] / image_size[0], pdf_size[1] / image_size[1]
    for line in lines:
        poly = line['polygon']
        x0, x1 = min(p[0] for p in poly)*sx, max(p[0] for p in poly)*sx
        y0, y1 = min(p[1] for p in poly)*sy, max(p[1] for p in poly)*sy
        cx, cy = (x0+x1)/2, (y0+y1)/2
        candidates = [r for r in regions if r['bbox'][0]-3 <= cx <= r['bbox'][2]+3
                      and r['bbox'][1]-3 <= cy <= r['bbox'][3]+3]
        entry = dict(line, pdf_bbox=[x0,y0,x1,y1])
        if not candidates:
            excluded.append(entry)
            continue
        if len(candidates) != 1:
            ambiguous.append({'line_id':line['line_id'],'candidates':[r['clause_id'] for r in candidates]})
            # Deterministic nearest region center; ambiguity is explicitly reported.
            candidates.sort(key=lambda r: abs(cy-(r['bbox'][1]+r['bbox'][3])/2))
        assigned[candidates[0]['clause_id']].append(entry)
    texts = {}
    for cid, entries in assigned.items():
        # Stable top-to-bottom row grouping, then left-to-right (table labels before values).
        remaining = sorted(entries, key=lambda e: ((e['pdf_bbox'][1]+e['pdf_bbox'][3])/2, e['pdf_bbox'][0]))
        ordered = []
        while remaining:
            first = remaining.pop(0)
            cy = (first['pdf_bbox'][1]+first['pdf_bbox'][3])/2
            tolerance = max(1, (first['pdf_bbox'][3]-first['pdf_bbox'][1])*0.65)
            row = [first]
            while remaining and abs((remaining[0]['pdf_bbox'][1]+remaining[0]['pdf_bbox'][3])/2-cy) <= tolerance:
                row.append(remaining.pop(0))
            ordered.extend(sorted(row,key=lambda e:e['pdf_bbox'][0]))
        assigned[cid] = ordered
        texts[cid] = ''.join(e['text']+'\n' for e in ordered)
    return {'texts':texts,'assigned':assigned,'excluded':excluded,'ambiguous':ambiguous}


def lines_at_offset(entries, start, end):
    matches = []
    offset = 0
    for entry in entries:
        size = len(normalize_text(entry['text']))
        if (start < offset+size and end > offset) or (start == end and offset <= start <= offset+size):
            matches.append({key:entry[key] for key in ['line_id','pdf_bbox','confidence','text']})
        offset += size
    return matches


def error_analysis(refs, texts, assigned):
    """Diagnostic diff only; CER is always computed with the existing Levenshtein code."""
    errors = []
    term_diffs = []
    whitespace_diffs = []
    terms = ['임대인','임차인','할수있다','할수없다','지급한다','지급하지않는다',
             '부담','해제','해지','반환','손해배상','수선','원상복구']
    for cid, ref in refs.items():
        a,b = normalize_text(ref),normalize_text(texts[cid])
        for tag,i,j,k,l in SequenceMatcher(None,a,b,autojunk=False).get_opcodes():
            if tag == 'equal':
                continue
            left,right=a[i:j],b[k:l]
            if any(ch.isdigit() for ch in left+right): kind='number_or_article_marker'
            elif any('\uac00'<=ch<='\ud7a3' for ch in left+right): kind='korean_or_missing_text'
            else: kind='symbol'
            errors.append({'clause_id':cid,'page':2,'type':kind,'operation':tag,'reference':left,
                           'ocr':right,'reference_offset':[i,j],'ocr_offset':[k,l],
                           'reference_context':a[max(0,i-20):j+20],
                           'ocr_context':b[max(0,k-20):l+20],
                           'ocr_lines':lines_at_offset(assigned[cid],k,l),
                           'possible_impact':'조항 번호·기간·조건 오독 가능; 법률 판단이 아닌 검토 신호' if kind=='number_or_article_marker' else '주체·의무·예외 조건 오독 가능; 사람 확인 필요'})
        for tag,i,j,k,l in SequenceMatcher(None,ref,texts[cid],autojunk=False).get_opcodes():
            if tag!='equal' and normalize_text(ref[i:j])==normalize_text(texts[cid][k:l]):
                whitespace_diffs.append({'clause_id':cid,'page':2,'type':'whitespace_or_linebreak',
                    'reference':ref[i:j],'ocr':texts[cid][k:l],'reference_offset':[i,j],'ocr_offset':[k,l],
                    'reference_context':ref[max(0,i-15):j+15],
                    'ocr_context':texts[cid][max(0,k-15):l+15],
                    'possible_impact':'Raw CER 차이에 반영. 기존 정책의 허용 공백만 normalized에서 제거.',
                    'ocr_lines':lines_at_offset(assigned[cid],len(normalize_text(texts[cid][:k])),len(normalize_text(texts[cid][:l])))})
        for term in terms:
            if a.count(term)!=b.count(term):
                term_diffs.append({'clause_id':cid,'term':term,'reference_count':a.count(term),'ocr_count':b.count(term)})
        ar=re.findall(r'\d+|[①-⑳]',a);br=re.findall(r'\d+|[①-⑳]',b)
        if ar!=br: term_diffs.append({'clause_id':cid,'term':'numeric_tokens','reference':ar,'ocr':br})
    return {'diff_method':'SequenceMatcher diagnostic spans, not CER alignment; offsets in normalized text',
            'differences':errors,'whitespace_differences':whitespace_diffs,'critical_differences':term_diffs,
            'critical_difference_count':len(term_diffs)}


def preprocess(image, method):
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    if method=='baseline': return image.copy()
    if method=='resize_1.5': return image.resize((round(image.width*1.5),round(image.height*1.5)),Image.Resampling.LANCZOS)
    if method=='contrast_1.5': return ImageEnhance.Contrast(image).enhance(1.5)
    if method=='unsharp': return image.filter(ImageFilter.UnsharpMask(radius=1.5,percent=150,threshold=3))
    if method=='grayscale': return ImageOps.grayscale(image).convert('RGB')
    if method=='median_3': return image.filter(ImageFilter.MedianFilter(3))
    if method=='otsu':
        import cv2
        import numpy as np
        gray=cv2.cvtColor(np.array(image),cv2.COLOR_RGB2GRAY)
        _,binary=cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        return Image.fromarray(binary).convert('RGB')
    raise ValueError(method)


def run(args):
    from PIL import Image
    import fitz
    os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
    from paddleocr import PaddleOCR
    out=args.output
    out.mkdir(parents=True,exist_ok=False)
    sample=json.loads(args.ground_truth.read_text(encoding='utf-8'))
    if digest(args.pdf)!=sample['source_sha256']: raise ValueError('PDF hash mismatch')
    with fitz.open(args.pdf) as doc: pdf_size=list(doc[1].rect)[2:]
    gt=[c for c in sample['clauses'] if c['page']==2]
    regions=regions_for_page(gt,2)
    refs={c['clause_id']:c['text'] for c in gt}
    image=Image.open(args.image).convert('RGB')
    # Full page, no crop/rotation accepted: dimensions must match PDF aspect ratio.
    if abs(image.width/image.height-pdf_size[0]/pdf_size[1])>0.002: raise ValueError('Image/PDF aspect ratio mismatch')
    kwargs=dict(lang='korean',use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=False)
    init_start=time.perf_counter();ocr=PaddleOCR(**kwargs);init_seconds=time.perf_counter()-init_start
    model_root=Path.home()/'.paddlex/official_models'
    model_hashes={name:{p.name:digest(p) for p in (model_root/name).iterdir() if p.is_file()} for name in [DET,REC]}
    resolved = ocr._merged_paddlex_config
    if resolved['SubModules']['TextDetection']['model_name'] != DET or resolved['SubModules']['TextRecognition']['model_name'] != REC:
        raise ValueError('Resolved models differ from the registered baseline; stop rather than mix models')
    meta={'created_at':datetime.now(timezone.utc).isoformat(),'versions':{p:version(p) for p in ['paddleocr','paddlepaddle','paddlex','PyMuPDF','Pillow']},
          'python':platform.python_version(),'platform':platform.platform(),'image':str(args.image),
          'image_sha256':digest(args.image),'image_size':list(image.size),'pdf_sha256':digest(args.pdf),
          'ground_truth_sha256':digest(args.ground_truth),'page':2,'clause_ids':list(refs),
          'regions':regions,'pdf_size':pdf_size,'constructor':kwargs,'models':[DET,REC],'model_file_sha256':model_hashes,
          'model_initialization_seconds':init_seconds,'repeat_count':args.repeats,
          'alignment_version':ALIGNMENT_VERSION,
          'mapping':'known-layout spatial evaluation, NOT production clause segmentation; 3pt margin; no text matching',
          'timing':'predict materialization wall time, image IO inside predict included; preprocessing/model init/CER excluded; first pass reported separately',
          'confidence_review_threshold':0.9,'confidence_is_accuracy':False}
    # Resolved config is evidence of models/defaults actually used.
    if hasattr(ocr,'_merged_paddlex_config'): meta['resolved_pipeline_config']=ocr._merged_paddlex_config
    save_json(out/'run_metadata.json',meta)
    summaries=[]
    for eid in args.experiments:
        method,options=EXPERIMENTS[eid]
        folder=out/eid;folder.mkdir()
        prep_start=time.perf_counter();processed=preprocess(image,method);prep_seconds=time.perf_counter()-prep_start
        image_path=args.image if method=='baseline' else folder/'input.png'
        if method!='baseline':processed.save(image_path)
        try:
            timings=[];repeat_scores=[]
            for repeat in range(args.repeats):
                start=time.perf_counter();results=list(ocr.predict(str(image_path),**options));seconds=time.perf_counter()-start
                if len(results)!=1: raise ValueError('Expected one page result')
                result=results[0]
                texts=result['rec_texts'];scores=result['rec_scores'];polys=result['rec_polys']
                if not(len(texts)==len(scores)==len(polys)):raise ValueError('OCR result lengths differ')
                lines=[{'line_id':i,'text':text,'confidence':float(conf),'polygon':poly.tolist(),
                        'needs_review':float(conf)<0.9} for i,(text,conf,poly) in enumerate(zip(texts,scores,polys))]
                assignment=assign_lines(lines,regions,processed.size,pdf_size)
                metrics=evaluate_corpus(refs,assignment['texts'])
                analysis=error_analysis(refs,assignment['texts'],assignment['assigned'])
                payload={'experiment_id':eid,'repeat':repeat,'method':method,'predict_options':options,
                         'image_path':str(image_path),'image_size':list(processed.size),'image_sha256':digest(image_path),
                         'preprocessing_seconds':prep_seconds,'ocr_seconds':seconds,'lines':lines,
                         'text_det_params':result.get('text_det_params'),'text_rec_score_thresh':result.get('text_rec_score_thresh'),
                         'assignment':assignment,'metrics':metrics,'error_analysis':analysis}
                save_json(folder/f'result_{repeat}.json',payload)
                (folder/f'text_{repeat}.txt').write_text('\n'.join(texts)+'\n',encoding='utf-8')
                timings.append(seconds);repeat_scores.append(metrics['micro'])
                print(json.dumps({'id':eid,'repeat':repeat,'seconds':seconds,'raw':metrics['micro']['raw']['cer'],
                                  'normalized':metrics['micro']['normalized']['cer'],'lines':len(lines),
                                  'critical':analysis['critical_difference_count']},ensure_ascii=False),flush=True)
            if eid=='E00':
                # Canonical baseline copies for convenient review; fresh run directory only.
                (out/'baseline_result.json').write_bytes((folder/'result_0.json').read_bytes())
                (out/'baseline_text.txt').write_bytes((folder/'text_0.txt').read_bytes())
            summaries.append({'id':eid,'method':method,'predict_options':options,'status':'completed',
                              'ocr_seconds':timings,'median_seconds':statistics.median(timings),'metrics':repeat_scores,
                              'critical_differences':analysis['critical_difference_count'],
                              'low_confidence_lines':sum(e['needs_review'] for e in lines),
                              'excluded_line_count':len(assignment['excluded']),'ambiguous_count':len(assignment['ambiguous'])})
        except Exception as exc:
            save_json(folder/'error.json',{'error':repr(exc)})
            summaries.append({'id':eid,'status':'failed','error':repr(exc)})
            print(eid,'FAILED',repr(exc),flush=True)
        save_json(out/f'progress_{eid}.json',summaries)
    save_json(out/'comparison.json',summaries)
    if any(item['status']=='failed' for item in summaries):
        raise SystemExit(1)


def rescore_run(run_dir, ground_truth, output):
    """Re-evaluate saved, unedited OCR with one frozen geometry mapping for all runs."""
    meta=json.loads((run_dir/'run_metadata.json').read_text(encoding='utf-8'))
    if digest(ground_truth)!=meta['ground_truth_sha256']:
        raise ValueError('GT changed since OCR run')
    sample=json.loads(ground_truth.read_text(encoding='utf-8'))
    refs={c['clause_id']:c['text'] for c in sample['clauses'] if c['page']==meta['page']}
    summaries=[]
    for path in sorted(run_dir.glob('E*/result_*.json')):
        result=json.loads(path.read_text(encoding='utf-8'))
        assignment=assign_lines(result['lines'],meta['regions'],result['image_size'],meta['pdf_size'])
        metrics=evaluate_corpus(refs,assignment['texts'])
        analysis=error_analysis(refs,assignment['texts'],assignment['assigned'])
        summaries.append({'experiment_id':result['experiment_id'],'repeat':result['repeat'],
                          'method':result['method'],'predict_options':result['predict_options'],
                          'source_result':str(path),'source_result_sha256':digest(path),
                          'ocr_seconds':result['ocr_seconds'],'preprocessing_seconds':result['preprocessing_seconds'],
                          'metrics':metrics,'assignment':assignment,'error_analysis':analysis})
    if not summaries:raise ValueError('No completed OCR results')
    save_json(output,{'alignment_version':ALIGNMENT_VERSION,'ground_truth_sha256':digest(ground_truth),
                      'policy_version':'safecontract-ocr-normalization-v1','results':summaries})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',type=Path,default=ROOT/'tmp/ocr_test/contract_page2.png')
    p.add_argument('--pdf',type=Path,default=ROOT/'data/contracts/original/standard_contract.pdf')
    p.add_argument('--ground-truth',type=Path,default=ROOT/'data/ocr/sample_contract.json')
    p.add_argument('--output',type=Path,required=True,help='New directory only; existing outputs never overwritten')
    p.add_argument('--experiments',nargs='+',choices=list(EXPERIMENTS),default=list(EXPERIMENTS))
    p.add_argument('--repeats',type=int,default=1)
    p.add_argument('--rescore-run',type=Path,help='Evaluate saved OCR only; output must be a new JSON file')
    args=p.parse_args()
    if args.repeats<1 or len(args.experiments)!=len(set(args.experiments)):p.error('positive repeats and unique experiments required')
    if args.rescore_run:
        rescore_run(args.rescore_run,args.ground_truth,args.output)
    else:
        run(args)


if __name__=='__main__':main()
