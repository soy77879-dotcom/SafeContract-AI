"""Prepare a local review sidecar from existing OCR; does not run OCR or use GT."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from integrations.clause_review import build_review_document
from scripts.structure_ocr import api_response


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,default=ROOT/'tmp/ocr_pages/c001_aligned/structured_contract.json')
    p.add_argument('--pages',type=Path,default=ROOT/'tmp/ocr_pages/ocr_pages_result.json')
    p.add_argument('--api',type=Path,default=ROOT/'tmp/ocr_pages/c001_aligned/api_ocr_response.json')
    p.add_argument('--output',type=Path,default=ROOT/'tmp/clause_review/review_document.json')
    a=p.parse_args()
    try:
        if a.output.resolve() in {a.input.resolve(),a.pages.resolve(),a.api.resolve()}:raise ValueError()
        structured=json.loads(a.input.read_text());pages=json.loads(a.pages.read_text());api=json.loads(a.api.read_text())
        if api_response(structured)!=api:raise ValueError()
        result=build_review_document(structured,pages,api)
        result['source_hashes']={'structured_sha256':hashlib.sha256(a.input.read_bytes()).hexdigest(),
                                 'ocr_pages_sha256':hashlib.sha256(a.pages.read_bytes()).hexdigest()}
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
        print(json.dumps({'clauses':len(result['clauses']),'page_count':result['page_count'],'status':'needs_review'}))
    except FileExistsError:print('Output already exists; choose a new --output path.',file=sys.stderr);return 1
    except Exception:print('Review preparation failed: check source files, IDs and pages.',file=sys.stderr);return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
