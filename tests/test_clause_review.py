"""Cached actual OCR linkage tests; no OCR inference or GT mutation."""
import copy
import json
from pathlib import Path
import unittest
from integrations.clause_review import build_review_document
ROOT=Path(__file__).resolve().parents[1]

class ClauseReviewTests(unittest.TestCase):
    def setUp(self):
        self.s=json.loads((ROOT/'tmp/ocr_pages/c001_aligned/structured_contract.json').read_text())
        self.p=json.loads((ROOT/'tmp/ocr_pages/ocr_pages_result.json').read_text())
        self.a=json.loads((ROOT/'tmp/ocr_pages/c001_aligned/api_ocr_response.json').read_text())
    def build(self):return build_review_document(self.s,self.p,self.a)
    def test_actual_19_ids(self):self.assertEqual(self.build()['expected_clause_ids'],[f'C{i:03}' for i in range(1,20)])
    def test_actual_pages(self):
        d=self.build();self.assertEqual(d['page_count'],5);self.assertEqual([c['pages'] for c in d['clauses']],[c['pages'] for c in self.s['clauses']])
    def test_raw_preserved(self):self.assertEqual([c['raw_text'] for c in self.build()['clauses']],[c['raw_text'] for c in self.s['clauses']])
    def test_initial_needs_review(self):self.assertTrue(all(c['status']=='needs_review' and not c['reviewed_by_user'] for c in self.build()['clauses']))
    def test_no_mutation(self):
        before=copy.deepcopy((self.s,self.p,self.a));self.build();self.assertEqual((self.s,self.p,self.a),before)
    def test_source_coordinates(self):
        d=self.build();self.assertEqual(d['clauses'][0]['source_lines'][0]['polygon'],self.s['clauses'][0]['source_lines'][0]['polygon'])
    def test_no_coordinate_fabrication(self):
        line=self.s['clauses'][0]['source_lines'][0];line['polygon']=None
        next(l for p in self.p['pages'] if p['page']==line['page'] for l in p['lines'] if l['line_id']==line['line_id'])['polygon']=None
        self.assertIsNone(self.build()['clauses'][0]['source_lines'][0]['polygon'])
    def test_duplicate_id(self):self.s['clauses'][1]['clause_id']='C001';self.assertRaises(ValueError,self.build)
    def test_missing_id(self):self.s['clauses'].pop();self.assertRaises(ValueError,self.build)
    def test_page_mismatch(self):self.s['clauses'][0]['pages']=[5];self.assertRaises(ValueError,self.build)
    def test_missing_source(self):self.s['clauses'][0]['source_lines'][0]['line_id']='absent';self.assertRaises(ValueError,self.build)
    def test_text_mismatch(self):self.s['clauses'][0]['raw_text']='changed';self.assertRaises(ValueError,self.build)
    def test_source_text_tamper(self):self.s['clauses'][0]['source_lines'][0]['text']='changed';self.assertRaises(ValueError,self.build)
    def test_no_server_approval(self):self.assertFalse(self.build()['server_approved']);self.assertFalse(self.build()['external_llm_allowed'])

if __name__=='__main__':unittest.main()
