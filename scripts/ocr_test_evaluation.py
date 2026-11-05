"""Strict source matching and D-7 evaluation for the repeatable OCR CLI."""
import json
from importlib.metadata import version
from pathlib import Path

try:
    from .ocr_experiments import (ROOT, DET, REC, ALIGNMENT_VERSION, digest,
                                  regions_for_page, assign_lines, error_analysis)
    from .ocr_evaluation import evaluate_corpus, normalize_text, POLICY_VERSION
except ImportError:
    from ocr_experiments import (ROOT, DET, REC, ALIGNMENT_VERSION, digest,
                                 regions_for_page, assign_lines, error_analysis)
    from ocr_evaluation import evaluate_corpus, normalize_text, POLICY_VERSION


def source_scope(image, page=2):
    import fitz
    gt = ROOT / 'data/ocr/sample_contract.json'
    pdf = ROOT / 'data/contracts/original/standard_contract.pdf'
    sample = json.loads(gt.read_text(encoding='utf-8'))
    if digest(pdf) != sample['source_sha256']:
        raise ValueError('PDF와 Ground Truth 원본 해시가 다릅니다.')
    clauses = [c for c in sample['clauses'] if c['page'] == page]
    regions = regions_for_page(clauses, page)
    if page == 2 and [c['clause_id'] for c in clauses] != [f'C{i:03}' for i in range(4,20)]:
        raise ValueError('2페이지 평가 조항은 C004~C019여야 합니다.')
    with fitz.open(pdf) as doc:
        p = doc[page-1]
        pix = p.get_pixmap(matrix=fitz.Matrix(2,2), alpha=False)
        if image.size != (pix.width,pix.height) or image.tobytes() != pix.samples:
            raise ValueError('입력이 지정 PDF 페이지의 2배 렌더와 픽셀 단위로 일치하지 않습니다. 임의 이미지에 정답을 대응하지 않습니다.')
        size = [p.rect.width,p.rect.height]
    return {'page':page,'clauses':clauses,'regions':regions,'pdf_size':size,
            'ground_truth_sha256':digest(gt),'pdf_sha256':digest(pdf)}


def assess(lines, scope, image_size):
    refs = {c['clause_id']:c['text'] for c in scope['clauses']}
    assignment = assign_lines(lines,scope['regions'],image_size,scope['pdf_size'])
    if assignment['ambiguous']:
        raise ValueError('OCR 줄의 조항 대응이 모호하여 CER를 계산하지 않습니다.')
    metrics = evaluate_corpus(refs,assignment['texts'])
    analysis = error_analysis(refs,assignment['texts'],assignment['assigned'])
    for key in ('differences','whitespace_differences'):
        for item in analysis[key]: item['page'] = scope['page']
    terms = ['임대인','임차인','부담','부당','한다','하지않는다','해제','해지',
             '보증금','월세','관리비','계약기간','반환','위약금','수선','수리','특약']
    checks=[]
    for cid, ref in refs.items():
        hyp=assignment['texts'][cid]
        for term in terms:
            a,b=normalize_text(ref).count(term),normalize_text(hyp).count(term)
            if a!=b:
                checks.append({'clause_id':cid,'term':term,'type':'term_count_difference',
                               'reference_count':a,'ocr_count':b,'reference':ref,'ocr':hyp})
    analysis['term_checks']=checks
    analysis['clause_texts']={cid:{'reference':ref,'ocr':assignment['texts'][cid]} for cid,ref in refs.items()}
    analysis['limitations']=['문자 차이와 용어 횟수 검사는 법적 의미 동등성 판정이 아님',
                            '미기입 금액·날짜는 정확도 검증 불가; 값을 생성하지 않음',
                            '원문자·숫자 및 기간 차이는 differences/critical_differences에 기록']
    return {'metrics':metrics,'assignment':assignment,'analysis':analysis}


def environment(ocr):
    cache=Path.home()/'.paddlex/official_models'
    return {'versions':{p:version(p) for p in ['paddleocr','paddlepaddle','paddlex','PyMuPDF','Pillow']},
            'resolved_pipeline_config':ocr._merged_paddlex_config,
            'models':[DET,REC], 'model_file_sha256':{
                n:{p.name:digest(p) for p in (cache/n).iterdir() if p.is_file()} for n in [DET,REC]},
            'alignment_version':ALIGNMENT_VERSION,'policy_version':POLICY_VERSION}


def compare(metrics, scope, env, input_path):
    try:
        root=ROOT/'tmp/ocr_experiments/d7_run01'
        old=json.loads((root/'run_metadata.json').read_text())
        scored=json.loads((root/'evaluation_v2.json').read_text())
        checks={k:env[k]==old[k] for k in ['versions','models','model_file_sha256','resolved_pipeline_config']}
        checks.update({k:scope[k]==old[k] for k in ['page','ground_truth_sha256','pdf_sha256']})
        checks['input_hash']=digest(input_path)==old['image_sha256']
        checks['alignment']=env['alignment_version']==scored['alignment_version']
        checks['policy']=env['policy_version']==scored['policy_version']
        checks['clause_ids']=list(metrics['clauses'])==old['clause_ids']
        if not all(checks.values()):return {'comparable':False,'reason':'실험 조건 불일치','checks':checks}
        comparisons=[]
        for r in scored['results']:
            if r['experiment_id'] not in ['E00','E02']:continue
            comparisons.append({'experiment':r['experiment_id'],'previous':r['metrics']['micro'],
                'delta_percentage_points':{m:(metrics['micro'][m]['cer']-r['metrics']['micro'][m]['cer'])*100 for m in ['raw','normalized']}})
        return {'comparable':True,'checks':checks,'comparisons':comparisons,
                'preprocessing':'current contrast_1.5; E00 baseline versus E02 contrast_1.5'}
    except (OSError,KeyError,ValueError) as exc:
        return {'comparable':False,'reason':f'이전 실험 근거 확인 불가: {exc}'}
