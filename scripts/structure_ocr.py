"""Structure cached OCR without Ground Truth; evaluation is a separate stage."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.ocr_experiments import assign_lines, digest, save_json, preprocess

ARTICLE=re.compile(r'^\s*제\s*(\d+)\s*조\s*\(([^)]*)\)')
FOOTER=re.compile(r'^\s*-?\s*\d+\s*/\s*\d+\s*-?\s*$')


def bbox(line):
    p=line['polygon']
    return [min(x[0] for x in p),min(x[1] for x in p),max(x[0] for x in p),max(x[1] for x in p)]


def ordered(lines):
    if not lines:return []
    width=max(bbox(l)[2] for l in lines)+1; height=max(bbox(l)[3] for l in lines)+1
    return assign_lines(lines,[{'clause_id':'all','bbox':[0,0,width,height]}],[width,height],[width,height])['assigned']['all']


def page_kind(lines):
    top=''.join(l['text'].replace(' ','') for l in lines[:8])
    alltext=''.join(l['text'].replace(' ','') for l in lines)
    if '계약갱신거절통지서' in top:return 'renewal_refusal_form'
    if lines and re.fullmatch(r'\s*별지\s*1\)?\s*',lines[0]['text']) and ('중요사항' in top or '확인' in top):return 'legal_guidance'
    if '서명' in alltext and '임대인' in alltext and '임차인' in alltext and not any(ARTICLE.match(l['text']) for l in lines):return 'party_information'
    if any(ARTICLE.match(l['text']) for l in lines):return 'contract_body'
    return 'unknown'


def structure(source):
    """Only raw OCR is accepted. No PDF/GT access or reference clause counts."""
    clauses=[];regions=[];fields=[];active=None; special=False;previous_y=None
    for page in source['pages']:
        number=page['page'];lines=ordered(page['lines']);kind=page_kind(lines)
        if kind in {'party_information','legal_guidance','renewal_refusal_form'}:
            regions.append({'page':number,'type':kind,'line_ids':[l['line_id'] for l in lines],
                            'privacy_sensitive':kind=='party_information','needs_review':True})
            active=None;special=False;continue
        pending_heading=None
        page_region={'page':number,'type':kind,'line_ids':[],'needs_review':True};regions.append(page_region)
        if page.get('status')!='completed':active=None;continue
        for line in lines:
            text=line['text'];box=bbox(line);m=ARTICLE.match(text)
            if FOOTER.match(text):
                regions.append({'page':number,'type':'unknown','line_ids':[line['line_id']],'reason':'footer'});continue
            if '특약사항' in text and len(text)<25:
                special=True;active=None;previous_y=None
                regions.append({'page':number,'type':'special_clause','line_ids':[line['line_id']],'needs_review':True});continue
            if not special and re.fullmatch(r'\s*\[[^\[\]\n]{1,40}\]\s*',text):
                pending_heading=line
                page_region['line_ids'].append(line['line_id'])
                continue
            leading=[]
            if pending_heading is not None:
                hb=bbox(pending_heading)
                if m and 0 <= box[1]-hb[3] <= 2*(hb[3]-hb[1]) and abs(box[0]-hb[0]) <= 2*(hb[3]-hb[1]):
                    leading=[pending_heading]
                    page_region['line_ids'].remove(pending_heading['line_id'])
                pending_heading=None
            start_special=False
            if special:
                is_note=text.lstrip().startswith('※')
                gap=box[1]-previous_y if previous_y is not None else 0
                start_special=active is None or (not is_note and (re.match(r'^\s*[•●·]',text) or gap>=29))
            if m or start_special:
                if m:special=False
                active={'clause_id':f'C{len(clauses)+1:03}','type':'special_clause' if special else 'contract_body',
                        'article_number':int(m[1]) if m else None,'title':m[2] if m else None,
                        'pages':[],'source_lines':[],'raw_text':'','candidate_text':None,'verified_text':None,
                        'needs_review':True,'review_reasons':['unverified_ocr']+(['heuristic_special_boundary'] if special else [])}
                if leading:
                    active['section_heading']=leading[0]['text']
                    active['pages'].append(number)
                    active['source_lines'].append({'page':number,**{k:leading[0][k] for k in ['line_id','text','confidence','polygon']}})
                clauses.append(active)
            if active is not None and (kind=='contract_body' or kind=='unknown'):
                active['source_lines'].append({'page':number,'line_id':line['line_id'],'text':text,
                                                'confidence':line.get('confidence'),'polygon':line['polygon']})
                if number not in active['pages']:active['pages'].append(number)
            else:page_region['line_ids'].append(line['line_id'])
            if special and (previous_y is None or box[1]>previous_y+4):previous_y=box[1]
            if any(t in text for t in ['보증금','계약금','중도금','잔금','월세','관리비','년','월','동의','있음','없음']):
                fields.append({'page':number,'line_id':line['line_id'],'bbox':box,'raw_text':text,
                               'type':'selection' if any(t in text for t in ['동의','있음','없음']) else 'amount_or_date_context',
                               'value':None,'state':'unknown','needs_review':True,
                               'reason':'OCR alone cannot distinguish blank input from missed text; label coordinates retained, input box not inferred'})
    for c in clauses:
        c['raw_text']=''.join(l['text']+'\n' for l in c['source_lines'])
        article_text=c['raw_text']
        if c.get('section_heading'):article_text=article_text[len(c['section_heading'])+1:]
        first=ARTICLE.match(article_text);c['body_text']=article_text[first.end():] if first else article_text
        scores=[l['confidence'] for l in c['source_lines'] if l['confidence'] is not None]
        c['confidence_min']=min(scores) if scores else None
        if scores and min(scores)<.9:c['review_reasons'].append('low_confidence_not_proof_of_error')
        if '부당' in c['raw_text']:c['review_reasons'].append('legal_term_visual_review')
        if c['type']=='special_clause':c['review_reasons'].append('checkbox_bullet_blank_uncertainty')
    nums=[c['article_number'] for c in clauses if c['article_number'] is not None]
    return {'document_id':source['document_id'],'clauses':clauses,'regions':regions,'form_fields':fields,
            'diagnostics':{'duplicate_articles':sorted({n for n in nums if nums.count(n)>1}),
                           'missing_between_detected':sorted(set(range(min(nums),max(nums)+1))-set(nums)) if nums else [],
                           'out_of_order':nums!=sorted(nums)},
            'analysis_ready':False,'note':'API preview only; user verification required before risk analysis'}


def api_response(data, for_analysis=False):
    if for_analysis and any(c['verified_text'] is None or c['needs_review'] for c in data['clauses']):
        raise ValueError('Unverified clauses cannot be sent for risk analysis')
    return {'document_id':data['document_id'],'clauses':[
        {'clause_id':c['clause_id'],'page':c['pages'][0],
         'text':c['verified_text'] if c['verified_text'] is not None else c['raw_text']} for c in data['clauses']]}


def isolated_schema_validate(payload):
    """Validate the exact Clause/OCRResponse AST without importing unrelated 3.10 unions."""
    import ast
    tree=ast.parse((ROOT/'backend/schemas.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom)) or
           isinstance(n,ast.ClassDef) and n.name in {'Clause','OCRResponse'}]
    namespace={'__name__':'isolated_ocr_schema'}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'backend/schemas.py','exec'),namespace)
    return namespace['OCRResponse'].model_validate(payload)


def fingerprint(source_path,pdf):
    from importlib.metadata import version
    modelroot=Path.home()/'.paddlex/official_models'
    return {'source_sha256':digest(source_path),'pdf_sha256':digest(pdf),
            'render_scale':2,'contrast':1.5,'versions':{x:version(x) for x in ['paddleocr','paddlepaddle','PyMuPDF','Pillow']},
            'models':{n:{f.name:digest(f) for f in (modelroot/n).glob('*') if f.is_file()} for n in ['PP-OCRv5_server_det','korean_PP-OCRv5_mobile_rec']},
            'code_sha256':digest(Path(__file__)), 'dependency_hashes':{n:digest(ROOT/'scripts'/n) for n in ['ocr_experiments.py','ocr_evaluation.py','ocr_test_evaluation.py']}, 'image_hashes':{p['image_path']:digest(Path(p['image_path'])) for p in json.loads(source_path.read_text())['pages'] if p.get('image_path')}}


def cache_matches(previous,current):return previous==current


def validate(source,data,pdf):
    import fitz
    from PIL import Image
    from scripts.ocr_test_evaluation import source_scope,assess
    from scripts.ocr_evaluation import evaluate_corpus
    validation={'pages':{},'schema':{},'structural_metrics':None,
                'structural_metrics_reason':'No independently human-labeled OCR boundaries/region classifications; counts are diagnostic only'}
    with fitz.open(pdf) as doc:
        for p in source['pages']:
            num=p['page'];entry={'ocr_status':p['status'],'cer':None};validation['pages'][str(num)]=entry
            pix=doc[num-1].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            rendered=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            path=Path(p['image_path'])
            with Image.open(path) as cached:
                match=cached.convert('RGB').tobytes()==preprocess(rendered,'contrast_1.5').tobytes() and cached.size==rendered.size
            entry['rendered_image_match']=match
            if not match:entry['reason']='PDF/render mismatch';continue
            try:scope=source_scope(rendered,num)
            except ValueError as exc:entry['reason']=str(exc);continue
            aligned=assess(p['lines'],scope,rendered.size)
            entry['geometry_cer']=aligned['metrics'];entry['term_checks']=aligned['analysis']['term_checks']
            refs={c['clause_id']:c['text'] for c in scope['clauses']}
            hypotheses={};issues=[]
            for gt in scope['clauses']:
                gtids={l['line_id'] for l in aligned['assignment']['assigned'][gt['clause_id']]}
                matches=[c for c in data['clauses'] if {l['line_id'] for l in c['source_lines']}==gtids and c['pages']==[num]]
                if len(matches)==1:
                    clause=matches[0]
                    if clause.get('section_heading'):
                        # Evaluation-only reading order from annotated PDF blocks.
                        # The serializer and original OCR text remain unchanged.
                        blocks=[{'clause_id':str(b['index']),'bbox':b['bbox']} for b in gt['source_blocks']]
                        mapped=assign_lines(clause['source_lines'],blocks,rendered.size,scope['pdf_size'])
                        if mapped['excluded'] or mapped['ambiguous']:
                            issues.append(gt['clause_id']);continue
                        hypotheses[gt['clause_id']]=''.join(mapped['texts'].values())
                        entry.setdefault('reading_order_alignment',{})[gt['clause_id']]={'method':'annotated PDF block order, evaluation only',
                            'line_ids_by_block':{k:[l['line_id'] for l in ls] for k,ls in mapped['assigned'].items()},
                            'raw_serialization_preserved':True}
                    else:hypotheses[gt['clause_id']]=clause['raw_text']
                else:issues.append(gt['clause_id'])
            if hypotheses:entry['matched_clause_cer']=evaluate_corpus({k:refs[k] for k in hypotheses},hypotheses)
            if issues:entry['reason']='Automatic segmentation differs from annotated evaluation regions';entry['unmatched']=issues
            else:entry['cer']=evaluate_corpus(refs,hypotheses)
    preview=api_response(data)
    validation['api_correspondence']=all(a['text']==c['raw_text'] and a['clause_id']==c['clause_id'] and a['page']==c['pages'][0] for a,c in zip(preview['clauses'],data['clauses'])) and len(preview['clauses'])==len(data['clauses'])
    try:
        from backend.schemas import OCRResponse
        OCRResponse.model_validate(preview);validation['schema']={'direct_import_valid':True}
    except (TypeError,ImportError) as exc:
        validation['schema']={'direct_import_valid':False,'reason':str(exc),'field_shape_valid':all(set(c)=={'clause_id','page','text'} and re.fullmatch(r'C\d{3,}',c['clause_id']) and isinstance(c['page'],int) and c['page']>=1 and isinstance(c['text'],str) and c['text'] for c in preview['clauses'])}
    isolated_schema_validate(preview)
    validation['schema']['isolated_original_OCRResponse_valid']=True
    return validation


def attach_candidates(data,source,path):
    """Attach prior actual re-recognition only when original lines exactly correspond."""
    result=json.loads(path.read_text());attached=0
    evidence=json.loads((path.parent.parent/'baseline.json').read_text())
    page=next(p for p in source['pages'] if p['page']==2)
    for review in result['reviews']:
        indices=review['source_line_ids']
        selected=[page['lines'][i] for i in indices]
        if any(page['lines'][i]['text']!=evidence['lines'][i]['text'] or page['lines'][i]['polygon']!=evidence['lines'][i]['polygon'] for i in indices):continue
        original=' '.join(l['text'] for l in sorted(selected,key=lambda l:min(pt[0] for pt in l['polygon'])))
        if original!=review['original']:continue
        ids={l['line_id'] for l in selected}
        for c in data['clauses']:
            if ids.issubset({l['line_id'] for l in c['source_lines']}):
                c.setdefault('candidate_regions',[]).append({'source_line_ids':sorted(ids),'raw_text':review['original'],
                  'candidate_text':review['candidate'],'confidence':review['confidence'],'status':'needs_review','evidence_file':str(path)})
                if review['changed']:c['review_reasons'].append('re_recognition_disagreement')
                attached+=1
    return attached


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=ROOT/'tmp/ocr_pages/ocr_pages_result.json')
    p.add_argument('--output',type=Path,default=ROOT/'tmp/ocr_pages/structured_run')
    p.add_argument('--candidates',type=Path)
    args=p.parse_args();pdf=ROOT/'data/contracts/original/standard_contract.pdf'
    source=json.loads(args.input.read_text());fp=fingerprint(args.input,pdf)
    fp['candidate_sha256']=digest(args.candidates) if args.candidates else None
    meta=args.output/'cache_manifest.json'
    if meta.exists() and cache_matches(json.loads(meta.read_text())['fingerprint'],fp) and all((args.output/n).is_file() and digest(args.output/n)==h for n,h in json.loads(meta.read_text()).get('output_hashes',{}).items()) and json.loads(meta.read_text()).get('output_hashes'):
        print('cached: structured output matches fingerprint; legacy OCR provenance remains unverified');return
    if args.output.exists():raise ValueError('Output exists or cache invalidated; choose a new --output directory')
    args.output.mkdir(parents=True)
    data=structure(source)
    if args.candidates:attach_candidates(data,source,args.candidates)
    validation=validate(source,data,pdf)
    validation['cache']={'status':'cached','provenance':'legacy_unverified_model_settings','reason':'Original OCR cache has no model/config/source hashes; current snapshot cannot attest historical execution'}
    save_json(args.output/'structured_contract.json',data)
    save_json(args.output/'api_ocr_response.json',api_response(data))
    save_json(args.output/'validation_result.json',validation)
    save_json(meta,{'fingerprint':fp,'historical_ocr_provenance_verified':False,'output_hashes':{n:digest(args.output/n) for n in ['structured_contract.json','api_ocr_response.json','validation_result.json']}})
    print(json.dumps({'mode':'cached OCR; executed structuring','clauses':len(data['clauses']),
        'body':sum(c['type']=='contract_body' for c in data['clauses']),
        'special':sum(c['type']=='special_clause' for c in data['clauses']),
        'needs_review':sum(c['needs_review'] for c in data['clauses']),'output':str(args.output)},ensure_ascii=False))

if __name__=='__main__':main()
