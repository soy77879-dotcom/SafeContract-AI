import copy
import unittest
from scripts.structure_ocr import structure,api_response,page_kind,cache_matches,isolated_schema_validate
from scripts.ocr_evaluation import evaluate_corpus


def line(text,y=10,i='L1'):
    return {'line_id':i,'text':text,'confidence':.99,'polygon':[[0,y],[600,y],[600,y+20],[0,y+20]]}
def source(*pages):
    return {'document_id':'test','pages':[{'page':i+1,'status':'completed','lines':ls} for i,ls in enumerate(pages)]}


class StructureTests(unittest.TestCase):
    def test_article_title_body(self):
        d=structure(source([line('제1조(계약) 내용'),line('계속',35,'L2'),line('제2조(종료) 종료',70,'L3')]))
        self.assertEqual(len(d['clauses']),2);self.assertEqual(d['clauses'][0]['title'],'계약')
        self.assertEqual(d['clauses'][0]['body_text'],' 내용\n계속\n')
    def test_cross_page(self):
        d=structure(source([line('제1조(계약) 내용')],[line('이어지는 내용',10,'P2L1')]))
        self.assertEqual(d['clauses'][0]['pages'],[1,2])
        self.assertEqual(api_response(d)['clauses'][0]['page'],1)
    def test_special_gap(self):
        d=structure(source([line('[특약사항]'),line('첫 특약',50,'L2'),line('계속',74,'L3'),line('둘째 특약',110,'L4')]))
        self.assertEqual(len(d['clauses']),2)
        self.assertTrue(all(c['needs_review'] for c in d['clauses']))
    def test_ambiguous_special_not_forced(self):
        d=structure(source([line('[특약사항]'),line('내용',50,'L2'),line('추가',74,'L3')]))
        self.assertEqual(len(d['clauses']),1)
    def test_missing_duplicate(self):
        d=structure(source([line('제1조(가) 가'),line('제3조(나) 나',50,'L2'),line('제3조(다) 다',90,'L3')]))
        self.assertEqual(d['diagnostics']['missing_between_detected'],[2]);self.assertEqual(d['diagnostics']['duplicate_articles'],[3])
    def test_guidance(self):
        self.assertEqual(page_kind([line('별지1)'),line('중요사항 확인',40,'L2')]),'legal_guidance')
    def test_cross_reference_not_guidance(self):
        self.assertEqual(page_kind([line('별지1을 확인'),line('제1조(계약) 본문',40,'L2')]),'contract_body')
    def test_refusal(self):
        self.assertEqual(page_kind([line('계약갱신 거절통지서')]),'renewal_refusal_form')
    def test_party_not_clause(self):
        d=structure(source([line('임대인 임차인 서명')]))
        self.assertEqual(d['clauses'],[]);self.assertTrue(d['regions'][0]['privacy_sensitive'])
    def test_uncertain_fields(self):
        d=structure(source([line('제1조(금액) 보증금 원정'),line('동의 미동의',40,'L2')]))
        self.assertTrue(all(f['state']=='unknown' and f['value'] is None for f in d['form_fields']))
    def test_gt_not_used(self):
        raw=source([line('제31조(임의) 관측한 내용')]);before=copy.deepcopy(raw)
        d=structure(raw);self.assertEqual(raw,before);self.assertEqual(d['clauses'][0]['article_number'],31)
    def test_candidate_not_applied(self):
        d=structure(source([line('제1조(계약) 원문')]))
        d['clauses'][0]['candidate_text']='수정 후보'
        self.assertEqual(api_response(d)['clauses'][0]['text'],d['clauses'][0]['raw_text'])
        with self.assertRaises(ValueError):api_response(d,for_analysis=True)
    def test_api_fields(self):
        d=structure(source([line('제1조(계약) 원문')]))
        self.assertEqual(set(api_response(d)['clauses'][0]),{'clause_id','page','text'})
    def test_cache_invalidation(self):
        self.assertTrue(cache_matches({'pdf':'a'},{'pdf':'a'}));self.assertFalse(cache_matches({'pdf':'a'},{'pdf':'b'}))
    def test_original_schema_validation(self):
        d=structure(source([line('제1조(계약) 원문')]))
        result=isolated_schema_validate(api_response(d))
        self.assertEqual(result.clauses[0].clause_id,'C001')
    def test_duplicate_api_id_rejected(self):
        with self.assertRaises(ValueError):
            isolated_schema_validate({'document_id':'x','clauses':[{'clause_id':'C001','page':1,'text':'가'}]*2})
    def test_order_warning(self):
        d=structure(source([line('제2조(가) 가'),line('제1조(나) 나',50,'L2')]))
        self.assertTrue(d['diagnostics']['out_of_order'])
    def test_failed_page_does_not_continue_clause(self):
        data=source([line('제1조(가) 가')],[]);data['pages'][1]['status']='failed'
        result=structure(data);self.assertEqual(result['clauses'][0]['pages'],[1])
    def test_adjacent_heading_general_article(self):
        d=structure(source([line('[지급 조건]',10,'H'),line('제31조(지급) 원문',35,'A')]))
        c=d['clauses'][0]
        self.assertEqual(c['article_number'],31)
        self.assertEqual(c['raw_text'],'[지급 조건]\n제31조(지급) 원문\n')
        self.assertEqual(c['body_text'],' 원문\n')
    def test_far_heading_not_attached(self):
        d=structure(source([line('[다른 구역]',10,'H'),line('제7조(내용) 원문',200,'A')]))
        self.assertNotIn('section_heading',d['clauses'][0])
    def test_heading_separated_by_text_not_attached(self):
        d=structure(source([line('[다른 구역]',10,'H'),line('설명',35,'B'),line('제7조(내용) 원문',60,'A')]))
        self.assertNotIn('section_heading',d['clauses'][0])
    def test_evaluation_scope(self):
        self.assertEqual(evaluate_corpus({'C1':'가'},{'C1':'나'})['micro']['raw']['cer'],1)
        with self.assertRaises(ValueError):evaluate_corpus({'C1':'가'},{'C2':'가'})
