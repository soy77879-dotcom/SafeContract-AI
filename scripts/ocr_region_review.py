"""Development-only region re-recognition; candidates never overwrite original OCR."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
import time

try:
    from .ocr_experiments import ROOT, REC, preprocess, save_json, digest
    from .ocr_test_evaluation import source_scope, assess
except ImportError:
    from ocr_experiments import ROOT, REC, preprocess, save_json, digest
    from ocr_test_evaluation import source_scope, assess


def row_groups(lines):
    """Group visual rows using OCR geometry only, including fragmented blank fields."""
    groups=[]
    for line in sorted(lines,key=lambda l:min(p[1] for p in l['polygon'])):
        pts=line['polygon'];box=[min(p[0] for p in pts),min(p[1] for p in pts),max(p[0] for p in pts),max(p[1] for p in pts)]
        cy=(box[1]+box[3])/2
        if groups and abs(cy-groups[-1]['cy']) < 0.45*(box[3]-box[1]):
            g=groups[-1];g['ids'].append(line['line_id']);g['bbox']=[min(g['bbox'][0],box[0]),min(g['bbox'][1],box[1]),max(g['bbox'][2],box[2]),max(g['bbox'][3],box[3])]
        else:groups.append({'ids':[line['line_id']],'bbox':box,'cy':cy})
    return groups


def visual_candidates(image):
    import cv2
    import numpy as np
    gray=cv2.cvtColor(np.array(image),cv2.COLOR_RGB2GRAY)
    binary=cv2.threshold(gray,160,255,cv2.THRESH_BINARY_INV)[1]
    contours,hierarchy=cv2.findContours(binary,cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)
    squares=[]
    for i,c in enumerate(contours):
        x,y,w,h=cv2.boundingRect(c)
        if 8<=w<=30 and 8<=h<=30 and .75<=w/h<=1.3 and hierarchy[0][i][2]>=0:
            squares.append({'bbox':[x,y,x+w,y+h],'type':'square_candidate','checked':None,'status':'needs_review'})
    horizontal=cv2.morphologyEx(binary,cv2.MORPH_OPEN,np.ones((1,25),np.uint8))
    cnt,_=cv2.findContours(horizontal,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    rules=[]
    for c in cnt:
        x,y,w,h=cv2.boundingRect(c)
        if w>=25 and h<=5:rules.append({'bbox':[x,y,x+w,y+h],'type':'horizontal_rule_or_blank','status':'needs_review'})
    return {'square_candidates':squares,'horizontal_candidates':rules,
            'limitation':'Geometric candidates include table borders/glyphs. No checkbox state or underscore character count inferred.'}


def run(output=None):
    from PIL import Image, ImageOps
    os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
    from paddleocr import TextRecognition
    basepath=ROOT/'tmp/ocr_experiments/d7_run01/E02/result_0.json'
    base=json.loads(basepath.read_text())
    image=Image.open(ROOT/'tmp/ocr_test/contract_page2.png').convert('RGB')
    scope=source_scope(image)
    baseline=assess(base['lines'],scope,image.size)
    out=Path(output) if output else Path(tempfile.mkdtemp(prefix='region_',dir=ROOT/'tmp/ocr_test'))
    out.mkdir(parents=True,exist_ok=True)
    save_json(out/'baseline.json',base)
    save_json(out/'visual_candidates.json',visual_candidates(image))
    targets={'C004','C007','C008','C010','C014','C016','C017','C018','C019'}
    selected=[]
    for cid,lines in baseline['assignment']['assigned'].items():
        if cid in targets:
            for g in row_groups(lines):
                # Only marker lines and the burden row in main clauses; all special-term rows.
                if cid in {'C004','C007','C008','C010'} and not any(i in {0,2,4,11,12,18,20,21,25,28,32,33} for i in g['ids']):continue
                g['clause_id']=cid;selected.append(g)
    model=TextRecognition(model_name=REC)
    from importlib.metadata import version
    save_json(out/'environment.json', {'versions':{p:version(p) for p in ['paddleocr','paddlepaddle','Pillow']},
        'recognition_model':REC,'batch_size':1,'input_sha256':digest(ROOT/'tmp/ocr_test/contract_page2.png'),
        'source_scope':{k:v for k,v in scope.items() if k not in ('clauses','regions')},
        'selection':'Fixed development line IDs from diagnosed errors; GT text never passed to recognizer',
        'automatic_adoption':False})
    summary={'baseline_seconds':base['ocr_seconds'],'baseline_metrics':baseline['metrics'],
             'source_sha256':digest(basepath),'scope':'C004-C019; targeted development crops; no automatic adoption',
             'experiments':[]}
    for name,scale,method in [('R1',2,'contrast_1.5'),('R2',3,'baseline')]:
        folder=out/name;folder.mkdir()
        paths=[];boxes=[]
        for idx,g in enumerate(selected):
            x0,y0,x1,y1=g['bbox']
            # Margin includes symbols just outside original detector box.
            box=[max(0,int(x0)-12),max(0,int(y0)-3),min(image.width,int(x1)+12),min(image.height,int(y1)+3)]
            crop=preprocess(image.crop(box),method)
            crop=crop.resize((crop.width*scale,crop.height*scale),Image.Resampling.LANCZOS)
            crop=ImageOps.expand(crop,border=8,fill='white')
            path=folder/f'crop_{idx:02}.png';crop.save(path);paths.append(str(path));boxes.append(box)
        start=time.perf_counter();results=list(model.predict(paths,batch_size=1));seconds=time.perf_counter()-start
        if len(results)!=len(selected):raise ValueError('Crop result count mismatch')
        removed={i for g in selected for i in g['ids']}
        candidate=[copy.deepcopy(l) for l in base['lines'] if l['line_id'] not in removed]
        reviews=[]
        for idx,(g,r,box) in enumerate(zip(selected,results,boxes)):
            text=r['rec_text'];score=float(r['rec_score'])
            old=' '.join(l['text'] for l in sorted(base['lines'],key=lambda l:min(p[0] for p in l['polygon'])) if l['line_id'] in g['ids'])
            x0,y0,x1,y1=g['bbox']
            candidate.append({'line_id':1000+idx,'text':text,'confidence':score,'polygon':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]})
            reviews.append({'clause_id':g['clause_id'],'source_line_ids':g['ids'],'original':old,'candidate':text,
                            'confidence':score,'crop_bbox':box,'crop_file':paths[idx],
                            'changed':old!=text,'status':'needs_review' if old!=text else 'unchanged',
                            'reason':'Re-recognition disagreement; legal terms, numbers and symbols require visual human review. No automatic replacement.'})
        evaluation=assess(candidate,scope,image.size)
        save_json(folder/'candidate.json',{'lines':candidate,'reviews':reviews,'evaluation':evaluation,'recognition_seconds':seconds})
        (folder/'candidate.txt').write_text('\n'.join(l['text'] for l in sorted(candidate,key=lambda l:(min(p[1] for p in l['polygon']),min(p[0] for p in l['polygon'])))),encoding='utf-8')
        summary['experiments'].append({'id':name,'scale':scale,'preprocessing':method,'recognition_seconds':seconds,
            'estimated_total_seconds':base['ocr_seconds']+seconds,'metrics':evaluation['metrics'],
            'term_checks':evaluation['analysis']['term_checks'],'changed_rows':sum(r['changed'] for r in reviews)})
        print(name,seconds,evaluation['metrics']['micro'],flush=True)
        if name=='R1':
            # A separately reported development candidate: preserve special-term OCR intact.
            main_indices=[i for i,g in enumerate(selected) if g['clause_id'] in {'C004','C007','C008','C010'}]
            main_ids={lid for i in main_indices for lid in selected[i]['ids']}
            main_lines=[copy.deepcopy(l) for l in base['lines'] if l['line_id'] not in main_ids]
            main_lines += [copy.deepcopy(l) for l in candidate if l['line_id'] in {1000+i for i in main_indices}]
            main_eval=assess(main_lines,scope,image.size)
            save_json(out/'R3_main_only.json',{'lines':main_lines,'evaluation':main_eval,
                 'status':'needs_review','source':'R1 actual crops; special terms retain baseline OCR',
                 'timing':'Reuses full R1 crop pass, no new inference; total estimate includes full R1 cost'})
            summary['experiments'].append({'id':'R3_main_only','recognition_seconds':seconds,
                 'estimated_total_seconds':base['ocr_seconds']+seconds,'metrics':main_eval['metrics'],
                 'term_checks':main_eval['analysis']['term_checks']})
    save_json(out/'summary.json',summary)
    print('Results:',out,flush=True)
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);args=p.parse_args();run(args.output)
