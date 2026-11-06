"""Synthetic development cases, not legal ground truth or held-out accuracy evidence."""
import ast
import copy
import json
from pathlib import Path
import unittest
from scripts.risk_rules import analyze_text,analyze_document,to_api

ROOT=Path(__file__).resolve().parents[1]


def status(text,kind):
    return next(f['risk_status'] for f in analyze_text(text,reviewed=True) if f['risk_type']==kind)


class DepositTests(unittest.TestCase):
    def test_regular(self):
        self.assertEqual(status('임대차계약이 종료되면 임차인은 주택을 반환하고 임대인은 보증금을 반환한다.','deposit_return'),'ok')
    def test_delay(self):
        self.assertEqual(status('임대인은 계약 종료 후 30일 후에 보증금을 반환한다.','deposit_return'),'potential_risk')
    def test_new_tenant(self):
        self.assertEqual(status('임대인은 새로운 임차인이 입주한 이후 보증금을 반환한다.','deposit_return'),'potential_risk')
    def test_arbitrary_deduction(self):
        self.assertEqual(status('임대인은 보증금에서 임의로 비용을 공제한다.','deposit_return'),'potential_risk')
    def test_unclear(self):
        self.assertEqual(status('보증금 반환은 별도 협의에 따른다.','deposit_return'),'unknown')
    def test_negation(self):
        self.assertEqual(status('임대인은 새 임차인 입주 여부와 관계없이 보증금을 반환한다.','deposit_return'),'ok')
    def test_deduction_negation(self):
        self.assertEqual(status('임대인은 보증금에서 임의로 공제하지 않는다.','deposit_return'),'ok')
    def test_explicit_refusal(self):
        self.assertEqual(status('임대인은 보증금을 반환하지 않는다.','deposit_return'),'risk')
    def test_wrong_actor(self):
        self.assertEqual(status('임차인은 새로운 임차인이 입주한 이후 보증금을 반환한다.','deposit_return'),'unknown')
    def test_subject_switch(self):
        self.assertEqual(status('임대인은 계약서를 보관하고 임차인은 계약 종료 시 보증금을 반환한다.','deposit_return'),'unknown')
    def test_keyword_only(self):
        self.assertEqual(status('보증금 1000만원.','deposit_return'),'unknown')


class RepairTests(unittest.TestCase):
    def test_landlord(self):
        self.assertEqual(status('노후화된 시설의 수리비는 임대인이 부담한다.','repair_cost'),'ok')
    def test_tenant_fault(self):
        self.assertEqual(status('임차인의 고의 또는 과실로 발생한 파손은 임차인이 수리비를 부담한다.','repair_cost'),'ok')
    def test_aging(self):
        self.assertEqual(status('주택의 노후화로 발생하는 모든 수리비는 임차인이 부담한다.','repair_cost'),'potential_risk')
    def test_all_costs(self):
        self.assertEqual(status('모든 수리비는 임차인이 부담한다.','repair_cost'),'potential_risk')
    def test_unclear_actor(self):
        self.assertEqual(status('수리비는 추후 협의한다.','repair_cost'),'unknown')
    def test_ocr_error(self):
        self.assertEqual(status('임차인이 모든 수리비를 부당한다.','repair_cost'),'unknown')
    def test_negated_burden(self):
        self.assertEqual(status('임차인은 노후화 수리비를 부담하지 않는다.','repair_cost'),'ok')
    def test_fault_irrelevant(self):
        self.assertEqual(status('고의 과실과 관계없이 모든 수리비는 임차인이 부담한다.','repair_cost'),'potential_risk')
    def test_exceptions(self):
        self.assertEqual(status('임차인은 모든 수리비를 부담한다. 다만 노후화는 제외한다.','repair_cost'),'unknown')
    def test_causative_cost_transfer(self):
        self.assertEqual(status('임대인은 노후화된 시설의 모든 수리비를 임차인에게 부담시킨다.','repair_cost'),'potential_risk')
    def test_landlord_cannot_bear(self):
        self.assertEqual(status('임대인은 수리비를 부담할 수 없다.','repair_cost'),'unknown')
    def test_negated_transfer(self):
        self.assertEqual(status('임대인은 수리비를 임차인에게 전가하지 않는다.','repair_cost'),'ok')
    def test_double_negation(self):
        self.assertEqual(status('임차인은 모든 수리비를 부담하지 않는 것은 아니다.','repair_cost'),'unknown')


class TerminationTests(unittest.TestCase):
    def test_notice(self):
        text='당사자 일방이 채무를 이행하지 않는 경우 상대방은 상당한 기간을 정하여 이행을 최고하고 계약을 해제할 수 있다.'
        self.assertEqual(status(text,'contract_termination'),'ok')
    def test_prohibited(self):
        self.assertEqual(status('임차인은 어떠한 경우에도 계약을 해지할 수 없다.','contract_termination'),'risk')
    def test_remaining_rent(self):
        self.assertEqual(status('임차인이 중도해지하는 경우 남은 계약기간의 월세 전액을 위약금으로 지급한다.','contract_termination'),'potential_risk')
    def test_unilateral(self):
        self.assertEqual(status('임차인의 중도해지 조건은 임대인이 정한다.','contract_termination'),'potential_risk')
    def test_forfeit(self):
        self.assertEqual(status('임차인이 중도해지하면 계약금 전액을 몰수한다.','contract_termination'),'potential_risk')
    def test_conditional(self):
        self.assertEqual(status('임차인은 조건을 이행하기 전에는 계약을 해지할 수 없다.','contract_termination'),'unknown')
    def test_exception(self):
        self.assertEqual(status('임차인은 중도해지할 수 없다. 다만 합의한 경우는 예외로 한다.','contract_termination'),'unknown')
    def test_penalty_negated(self):
        self.assertEqual(status('임차인이 중도해지해도 남은 기간 월세 전액을 위약금으로 지급하지 않는다.','contract_termination'),'ok')
    def test_amount_not_threshold(self):
        self.assertEqual(status('계약 해지 시 위약금 100만원.','contract_termination'),'unknown')
    def test_revoked(self):
        self.assertEqual(status('임차인은 어떠한 경우에도 계약을 해지할 수 없다. 이 조항은 적용하지 않는다.','contract_termination'),'unknown')


class CommonTests(unittest.TestCase):
    def document(self,text='임대인은 보증금을 반환하지 않는다.'):
        return {'document_id':'synthetic','clauses':[{'clause_id':'C001','page':2,'text':text}]}
    def test_unrelated(self):
        f=analyze_text('벽지는 흰색이다.',reviewed=True)[0]
        self.assertEqual((f['risk_type'],f['risk_status']),('unrelated','unknown'))
    def test_multiple_types(self):
        f=analyze_text('임대인은 보증금을 반환하지 않는다. 모든 수리비는 임차인이 부담한다.',reviewed=True)
        self.assertEqual({x['risk_type'] for x in f},{'deposit_return','repair_cost'})
    def test_empty(self):
        self.assertEqual(analyze_text('',reviewed=True)[0]['risk_status'],'unknown')
    def test_unreviewed(self):
        r=analyze_document(self.document());self.assertEqual(r['clauses'][0]['findings'][0]['risk_status'],'unknown')
        self.assertEqual(to_api(r)['status'],'partial')
    def test_no_candidate_substitution(self):
        d=self.document();d['clauses'][0].update(raw_text=d['clauses'][0]['text'],candidate_text='확인된 안전한 조항',needs_review=True)
        old=copy.deepcopy(d);r=analyze_document(d,['C001'])
        self.assertEqual(d,old);self.assertEqual(r['clauses'][0]['analysis_text'],d['clauses'][0]['raw_text'])
        self.assertTrue(r['clauses'][0]['needs_review'])
    def test_verified_selection(self):
        d=self.document();d['clauses'][0].update(verified_text='임대인은 계약 종료 시 보증금을 반환한다.',needs_review=False)
        r=analyze_document(d);self.assertEqual(r['clauses'][0]['text_source'],'verified_text');self.assertEqual(r['clauses'][0]['findings'][0]['risk_status'],'ok')
    def test_exact_evidence(self):
        text='임대인은 새로운\n임차인이 입주한 이후 보증금을 반환한다.'
        for f in analyze_text(text,reviewed=True):
            a,b=f['evidence_span'];self.assertEqual(text[a:b],f['evidence']);self.assertIn(f['evidence'],text)
    def test_page_id(self):
        r=analyze_document(self.document(),['C001']);c=r['clauses'][0]
        self.assertEqual((c['clause_id'],c['page'],c['pages']),('C001',2,[2]))
    def test_duplicate_id_rejected(self):
        d=self.document();d['clauses']*=2
        with self.assertRaises(ValueError):analyze_document(d)
    def test_duplicate_findings_prevented(self):
        r=analyze_text('임대인은 보증금을 반환하지 않는다. 임대인은 보증금을 반환하지 않는다.',reviewed=True)
        self.assertEqual(len(r),1)
    def test_unknown_review_id(self):
        with self.assertRaises(ValueError):analyze_document(self.document(),['C999'])
    def test_api_mapping(self):
        r=to_api(analyze_document(self.document('임차인은 어떠한 경우에도 해지할 수 없다.'),['C001']))
        f=r['results'][0];self.assertEqual((f['risk_type'],f['risk_status']),('termination','potential_risk'))
        self.assertEqual(set(f),{'clause_id','risk_type','risk_status','evidence','reason','possible_disadvantage','question','recommended_action'})
    def test_json_roundtrip(self):
        r=to_api(analyze_document(self.document()));self.assertEqual(r,json.loads(json.dumps(r,ensure_ascii=False)))
    def test_original_api_schema(self):
        # Exact source definitions, no backend module/server import or source mutation.
        tree=ast.parse((ROOT/'backend/schemas.py').read_text())
        names={'Clause','OCRResponse','AnalyzeRequest','RiskResult','AnalyzeResponse'}
        body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.Assign)) or isinstance(n,ast.ClassDef) and n.name in names]
        ns={'__name__':'isolated_risk_schema_test'}
        exec(compile(ast.Module(body=body,type_ignores=[]),'original_backend_schema','exec'),ns)
        d=self.document();ns['AnalyzeRequest'].model_validate(d)
        result=to_api(analyze_document(d,['C001']));ns['AnalyzeResponse'].model_validate(result)
    def test_api_ok_is_none(self):
        d=self.document('임대인은 계약 종료 시 보증금을 반환한다.')
        result=to_api(analyze_document(d,['C001']))
        self.assertEqual(result['results'][0]['risk_type'],'none')
        self.assertEqual(result['results'][0]['risk_status'],'no_risk_detected')
    def test_string_review_flag_rejected(self):
        d=self.document();d['clauses'][0]['needs_review']='false'
        with self.assertRaises(ValueError):analyze_document(d)
    def test_low_confidence_not_risk(self):
        d=self.document();d['clauses'][0].update(confidence_min=.1,needs_review=True)
        self.assertEqual(analyze_document(d)['clauses'][0]['findings'][0]['risk_status'],'unknown')
    def test_no_unreviewed_verified_override(self):
        d=self.document();d['clauses'][0].update(verified_text='임대인은 계약 종료 시 보증금을 반환한다.',needs_review=True)
        self.assertEqual(analyze_document(d)['clauses'][0]['analysis_text'],d['clauses'][0]['text'])
