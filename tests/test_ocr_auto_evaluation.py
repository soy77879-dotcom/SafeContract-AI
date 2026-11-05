import json
import unittest
from unittest.mock import patch
from PIL import Image
from scripts.ocr_test_evaluation import ROOT, source_scope, assess, compare


class AutoEvaluationTests(unittest.TestCase):
    def test_wrong_image_rejected(self):
        with self.assertRaisesRegex(ValueError, '픽셀'):
            source_scope(Image.new('RGB', (1190,1682),'white'))

    def test_no_verified_page_rejected(self):
        with self.assertRaisesRegex(ValueError, 'No GT'):
            source_scope(Image.new('RGB',(10,10)),3)

    def test_missing_ocr_counts_as_deletion(self):
        scope={'page':1,'pdf_size':[10,10], 'regions':[{'clause_id':'C001','bbox':[0,0,10,10]}],
               'clauses':[{'clause_id':'C001','text':'임차인은 부담한다'}]}
        result=assess([],scope,[10,10])
        self.assertEqual(result['metrics']['micro']['normalized']['cer'],1)
        self.assertTrue(result['analysis']['term_checks'])
        self.assertEqual(result['analysis']['differences'][0]['page'],1)

    def test_d7_saved_output_reproduces_metrics(self):
        folder=ROOT/'tmp/ocr_experiments/d7_run01'
        if not (folder/'E02/result_0.json').exists(): self.skipTest('local D-7 evidence unavailable')
        with Image.open(ROOT/'tmp/ocr_test/contract_page2.png') as image:
            scope=source_scope(image.convert('RGB'))
        raw=json.loads((folder/'E02/result_0.json').read_text())
        result=assess(raw['lines'],scope,raw['image_size'])
        expected=next(r for r in json.loads((folder/'evaluation_v2.json').read_text())['results'] if r['experiment_id']=='E02')
        self.assertEqual(result['metrics'],expected['metrics'])
        self.assertEqual(len(result['metrics']['clauses']),16)

    def test_missing_comparison_evidence(self):
        with patch('scripts.ocr_test_evaluation.ROOT', ROOT/'nonexistent'):
            self.assertFalse(compare({}, {}, {}, ROOT/'missing')['comparable'])
