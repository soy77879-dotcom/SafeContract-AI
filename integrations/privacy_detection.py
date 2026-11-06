"""Conservative local candidates, not a guarantee of privacy. No raw text in results."""
import math
import re
import unicodedata

TYPES = ('identifier', 'phone', 'email', 'account_candidate', 'name_context', 'address_context', 'numeric_candidate', 'ocr_uncertain')
MESSAGES = {
    'review_required': '개인정보 의심 영역을 확인하고 필요한 부분을 다시 가려 주세요.',
    'no_candidates': '패턴 검사에서 의심 항목을 찾지 못했습니다. 누락 가능성이 있어 직접 검토가 필요합니다.',
    'failed': '검사를 완료하지 못했습니다. 외부 전송은 차단된 상태입니다.'}


def result(status, findings=None):
    findings = findings or []
    return {'status': status, 'findings': findings,
            'found': None if status == 'failed' else bool(findings),
            'review_required': True, 'remasking_required': None if status == 'failed' else bool(findings),
            'external_transfer_blocked': True, 'external_llm_allowed': False,
            'message': MESSAGES[status], 'policy_version': 'local-privacy-v1'}


def normalized(text):
    chars, offsets = [], []
    for i, char in enumerate(text):
        for c in unicodedata.normalize('NFKC', char):
            if c.isspace() or c in '-‐‑‒–—−·.,()':
                continue
            chars.append(c); offsets.append(i)
    return ''.join(chars), offsets


def scan_lines(lines):
    """Ranges are zero-based end-exclusive Python character offsets in each OCR line.
    Confusables are used only to find candidates, never to correct OCR text.
    """
    if not isinstance(lines, list) or not lines or len(lines) > 20000:
        return result('failed')
    findings = []
    previous_context = ''
    for index, line in enumerate(lines):
        if not isinstance(line, dict) or not isinstance(line.get('text'), str):
            return result('failed')
        text = line['text']
        if len(text) > 20000:
            return result('failed')
        compact, offsets = normalized(text)
        seen = set()
        def add(kind, start=0, end=None, ambiguous=False):
            end = len(text) if end is None else end
            key = (kind, start, end)
            if key in seen: return
            seen.add(key)
            # No text, match, filename, or caller-supplied line ID is returned.
            findings.append({'type': kind, 'page': 1, 'line_index': index,
                             'start': start, 'end': end, 'possible_false_positive': ambiguous,
                             'review_required': True})
        score = line.get('confidence')
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or score < .80:
            add('ocr_uncertain', ambiguous=True)
        context = previous_context + compact
        if re.search(r'성명|이름|서명|임대인[:：]|임차인[:：]|^(?:임대인|임차인)[가-힣]{0,4}$', compact):
            add('name_context', ambiguous=True)
        if re.search(r'주소|소재지|거주지|도로명|\d+(?:동|호)(?:$|[^가-힣])|[가-힣]+(?:로|길)\d+', compact):
            add('address_context', ambiguous=True)
        for match in re.finditer(r'[A-Za-z0-9_%+.-]+\s*[@＠]\s*[A-Za-z0-9.-]+\s*[.．]\s*[A-Za-z]{2,}', text):
            add('email', *match.span())
        if ('@' in compact or re.search(r'이메일|전자우편', compact)) and not any(k[0]=='email' for k in seen):
            add('email', ambiguous=True)
        # Includes OCR letter/digit confusion and full-width characters with original offsets.
        digits = compact.translate(str.maketrans({'O':'0','o':'0','I':'1','l':'1','|':'1','S':'5','B':'8'}))
        for match in re.finditer(r'\d{7,}', digits):
            value = match.group(); start = offsets[match.start()]; end = offsets[match.end()-1]+1
            account = bool(re.search(r'계좌|은행|입금|예금주|account', context, re.I))
            labelled_private = bool(re.search(r'주민|식별|연락|전화|휴대|계좌|은행', context))
            money = bool(re.search(r'보증금|월세|차임|관리비|금액', compact[:match.start()])) and (compact[match.end():].startswith('원') or compact[max(0,match.start()-1):match.start()]=='₩')
            # Explicit private context takes precedence over a monetary label.
            if len(value) == 13 and (not money or labelled_private): add('identifier', start, end, True)
            elif (value.startswith('0') and 9 <= len(value) <= 11) or (value.startswith('82') and 11 <= len(value) <= 12) or (value.startswith('1') and len(value)==8): add('phone', start, end, True)
            elif account: add('account_candidate', start, end, True)
            elif not money and not (len(value)==8 and re.search(r'계약기간', compact) and value.startswith(('19','20'))): add('numeric_candidate', start, end, True)
        if re.search(r'계좌|예금주', compact): add('account_candidate', ambiguous=True)
        if re.search(r'주민등록|식별번호|전화번호|휴대전화|연락처', compact) and not any(k[0] in ('identifier','phone') for k in seen):
            add('numeric_candidate', ambiguous=True)
        # Nearby OCR lines can split labels from values. Label itself remains a review item.
        if previous_context and compact and re.search(r'성명|이름|주소|소재지|계좌|전화|주민', previous_context):
            kind = 'name_context' if re.search(r'성명|이름', previous_context) else 'address_context' if re.search(r'주소|소재지', previous_context) else 'numeric_candidate'
            add(kind, ambiguous=True)
        previous_context = compact if re.search(r'성명|이름|주소|소재지|계좌|전화|주민|은행', compact) else ''
    if not any(line['text'].strip() for line in lines): return result('failed')
    return result('review_required' if findings else 'no_candidates', findings)
