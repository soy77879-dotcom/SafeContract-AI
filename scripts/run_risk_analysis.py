"""Local review-only risk rules CLI; no server imports, no network, no OCR calls."""
import argparse
from collections import Counter
import json
from pathlib import Path
import tempfile
try:
    from .risk_rules import analyze_document,to_api
except ImportError:
    from risk_rules import analyze_document,to_api

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group()
    group.add_argument('--input',type=Path)
    group.add_argument('--text',help='Synthetic/manual text, not automatically verified')
    p.add_argument('--reviewed-test-text',action='store_true',help='Explicitly mark only --text as reviewed synthetic test input')
    p.add_argument('--output',type=Path,help='Fresh output directory')
    args=p.parse_args()
    if args.reviewed_test_text and args.text is None:p.error('--reviewed-test-text requires --text')
    if args.text is not None:
        document={'document_id':'synthetic_manual_test','clauses':[{'clause_id':'C001','page':1,'text':args.text}]}
        reviewed=['C001'] if args.reviewed_test_text else []
    else:
        path=args.input or ROOT/'tmp/ocr_pages/c001_aligned/structured_contract.json'
        document=json.loads(path.read_text(encoding='utf-8'));reviewed=[]
    result=analyze_document(document,reviewed);api=to_api(result)
    if args.output:
        output=args.output;output.mkdir(parents=True,exist_ok=False)
    else:
        parent=ROOT/'tmp/risk_analysis';parent.mkdir(parents=True,exist_ok=True)
        output=Path(tempfile.mkdtemp(prefix='run_',dir=parent))
    for name,data in [('internal_result.json',result),('analyze_response.json',api)]:
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'clauses':len(result['clauses']),
        'states':dict(Counter(f['risk_status'] for c in result['clauses'] for f in c['findings'])),
        'review_required':sum(c['needs_review'] for c in result['clauses']),
        'output':str(output)},ensure_ascii=False))

if __name__=='__main__':main()
