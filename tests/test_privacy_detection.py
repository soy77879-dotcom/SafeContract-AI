import contextlib
import io
import json
import unittest
from integrations.privacy_detection import scan_lines

class PrivacyTests(unittest.TestCase):
    def scan(self,text): return scan_lines([{'text':text,'confidence':.99}])
    def has(self,text,kind): self.assertIn(kind,[f['type'] for f in self.scan(text)['findings']])
    def test_identifier(self): self.has('식별번호 000000-0000000','identifier')
    def test_phone(self): self.has('010-0000-0000','phone')
    def test_landline(self): self.has('02 000 0000','phone')
    def test_service_phone(self): self.has('1588-0000','phone')
    def test_country_phone(self): self.has('+82 10 0000 0000','phone')
    def test_role_name(self): self.has('임차인 합성인물','name_context')
    def test_money_does_not_hide_number(self): self.has('보증금 1000000원 기타 999999999','numeric_candidate')
    def test_email(self): self.has('synthetic@example.invalid','email')
    def test_fragmented_email(self): self.has('s y n t h e t i c @ example . invalid','email')
    def test_account(self): self.has('계좌 999-000-000000','account_candidate')
    def test_spaces_hyphens(self): self.has('０１０ – ００００ ‐ ００００','phone')
    def test_confusable(self): self.has('O1O-OOOO-OOOO','phone')
    def test_money(self): self.assertEqual(self.scan('보증금 100000000원 월세 500000원')['status'],'no_candidates')
    def test_money_commas(self): self.assertEqual(self.scan('관리비 100,000원')['status'],'no_candidates')
    def test_dates(self): self.assertEqual(self.scan('계약기간 2026년 11월 1일부터 2028년 10월 31일까지')['status'],'no_candidates')
    def test_name(self): self.has('성명: 합성인물','name_context')
    def test_address(self): self.has('주소: 가상로 99 101호','address_context')
    def test_context_next_line(self):
        r=scan_lines([{'text':'성명','confidence':.99},{'text':'합성인물','confidence':.99}])
        self.assertTrue(any(f['line_index']==1 for f in r['findings']))
    def test_no_candidates_still_blocked(self):
        r=self.scan('임대인은 수리비를 부담한다.');self.assertEqual(r['status'],'no_candidates');self.assertTrue(r['review_required']);self.assertFalse(r['external_llm_allowed'])
    def test_empty_failed(self): self.assertEqual(scan_lines([])['status'],'failed')
    def test_whitespace_failed(self): self.assertEqual(self.scan('  ')['status'],'failed')
    def test_low_confidence(self): self.assertEqual(scan_lines([{'text':'정상','confidence':.4}])['status'],'review_required')
    def test_range(self):
        text='전화 010 – 0000 – 0000';r=self.scan(text);f=next(f for f in r['findings'] if f['type']=='phone');self.assertEqual(text[f['start']:f['end']],'010 – 0000 – 0000')
    def test_no_raw_or_logs(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output): r=self.scan('synthetic@example.invalid')
        self.assertEqual(output.getvalue(),'');self.assertNotIn('synthetic',json.dumps(r));self.assertNotIn('example.invalid',json.dumps(r))
    def test_unknown_number(self): self.has('999999999','numeric_candidate')
    def test_invalid_input(self): self.assertEqual(scan_lines([{'text':3}])['status'],'failed')

if __name__=='__main__': unittest.main()
