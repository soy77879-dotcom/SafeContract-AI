"""Conservative rental-clause rules. Pure Python 3.9; no OCR/GT/backend imports.
Internal labels are diagnostic, never legal determinations. Original evidence is sliced.
"""
import copy
import re

VERSION = 'rental-rules-v1'
TYPES = ('deposit_return', 'repair_cost', 'contract_termination')
TOPICS = {'deposit_return': r'보증금', 'repair_cost': r'수리|수선|노후|원상복구|유지보수',
          'contract_termination': r'해지|해제|위약금|계약금.*몰수'}
QUESTIONS = {
    'deposit_return': '새 임차인 입주 여부와 무관하게 반환할 날짜와 공제 기준을 명확히 정할 수 있나요?',
    'repair_cost': '노후화와 임차인의 고의·과실을 구분하여 수리 책임과 비용 범위를 정할 수 있나요?',
    'contract_termination': '해지 사유별 권리, 예외 조건과 위약금 산정 근거를 확인할 수 있나요?',
    'unrelated': '이 조항과 연결된 계약 조건 및 검토 범위를 확인해 주세요.'}
ACTIONS = {
    'deposit_return': '반환 시기·조건·공제 항목을 구체적으로 기재하도록 요청하세요.',
    'repair_cost': '수리 원인과 시설별 비용 부담 주체를 구분해 기재하도록 요청하세요.',
    'contract_termination': '해지 사유별 절차와 위약금 범위를 구체적으로 기재하도록 요청하세요.',
    'unrelated': '필요한 다른 조항을 함께 검토하세요.'}


def compact(text):
    # Rule matching only. Never used to replace evidence or change OCR/CER policy.
    return re.sub(r'\s+', '', text)


def sentence_spans(text):
    start = 0
    for m in re.finditer(r'[.!?](?=\s|$)', text):
        end = m.end()
        if text[start:end].strip(): yield start, end
        start = end
    if text[start:].strip(): yield start, len(text)


def context_features(text):
    t = compact(text)
    return {'actors': [a for a in ('임대인', '임차인') if a in t],
            'actions': [a for a in ('반환','지급','부담','해지','해제','배상','공제') if a in t],
            'has_exception': bool(re.search(r'다만|예외|단,|제외', t)),
            'negations': re.findall(r'하지않\w*|할수없\w*|아니\w*', t),
            'numeric_expressions': re.findall(r'\d[\d,.]*\s*(?:만원|원|개월|년|월|일|회|기|%)', text)}


def judge(kind, text):
    """One sentence; unrecognized constructions stay unknown."""
    t = compact(text)
    if '부당' in t and kind == 'repair_cost':
        return 'unknown', 'ocr_term', '부당/부담의 의미가 달라질 수 있어 원본 이미지 확인이 필요합니다.'
    if re.search(r'다만|예외|단,|제외|아니다|아니한다', t):
        return 'unknown', 'exception_scope', '예외 또는 의미 반전의 적용 범위를 규칙만으로 확정하기 어렵습니다.'
    if kind == 'deposit_return':
        actor = bool(re.search(r'임대인(?:은|는|이|가)',t))
        if re.search(r'임대인.*임차인(?:은|는).*보증금.*반환|임차인이보증금.*반환',t):
            actor=False
        if '별도협의' in t or '추후협의' in t:
            return 'unknown', 'deposit_unspecified', '반환 시기나 조건이 구체적으로 확인되지 않습니다.'
        if actor and re.search(r'보증금.*반환하지않', t):
            return 'risk', 'deposit_refusal', '임대인의 보증금 반환을 부정하는 명시적 문구가 있습니다.'
        if actor and '공제' in t and re.search(r'임의|마음대로|제한없이', t):
            if re.search(r'공제하지않|공제할수없', t):
                return 'ok', 'deduction_negated', '임의 공제를 제한하는 표현이 확인됩니다.'
            return 'potential_risk', 'arbitrary_deduction', '공제 범위가 임대인의 재량에 맡겨질 가능성이 있습니다.'
        if actor and '반환' in t and re.search(r'(?:새|새로운|신규|후속)임차인', t):
            if re.search(r'관계없이|무관하게|기다리지않', t):
                return 'ok', 'independent_return', '새 임차인 조건과 무관하게 반환한다는 표현이 확인됩니다.'
            if re.search(r'입주|구해|계약|보증금', t) and re.search(r'이후|후에|후반환|경우에만|때에만', t):
                return 'potential_risk', 'new_tenant_dependency', '반환 시기가 새 임차인 확보 또는 입주 조건에 종속될 수 있습니다.'
        if actor and '반환' in t and re.search(r'유예|지연|연기|종료.*\d+(?:일|개월|년)(?:후|뒤)', t):
            if re.search(r'(?:유예|지연|연기)하지않',t):
                return 'ok', 'delay_negated', '반환을 지연하지 않는다는 표현이 확인됩니다.'
            return 'potential_risk', 'return_delay', '계약 종료와 반환 사이에 지연 조건이 있어 확인이 필요합니다.'
        if actor and re.search(r'보증금.*반환(?:한다|하여야|해야)',t) and re.search(r'종료|동시|즉시',t):
            return 'ok', 'return_on_end', '계약 종료와 반환의 관계가 명시되어 검사한 규칙상 위험 신호를 찾지 못했습니다.'
    elif kind == 'repair_cost':
        if re.search(r'임대인.*임차인에게.*(?:부담시키|부담시킨|전가)',t):
            if re.search(r'부담시키지않|전가하지않',t):
                return 'ok','transfer_negated','임차인에게 비용을 전가하지 않는다는 표현이 확인됩니다.'
            return 'potential_risk','repair_transfer','임대인이 임차인에게 수리비 부담을 넘기는 조건으로 범위 확인이 필요합니다.'
        tenant = bool(re.search(r'임차인(?:은|는|이|가).*(?:부담|책임)', t))
        landlord = bool(re.search(r'임대인(?:은|는|이|가).*(?:부담|책임)', t))
        if tenant and landlord:
            return 'unknown', 'mixed_responsibility', '여러 주체의 책임 범위를 더 세밀하게 확인해야 합니다.'
        if tenant and re.search(r'부담하지않|부담할수없', t):
            return 'ok', 'tenant_burden_negated', '임차인의 해당 수리비 부담을 부정하는 표현이 확인됩니다.'
        if landlord and not tenant and '부담' in t:
            if re.search(r'부담하지않|부담할수없|부담하지못',t):return 'unknown','landlord_exemption','임대인의 책임 면제 후 부담 주체가 불명확합니다.'
            return 'ok', 'landlord_repair', '임대인의 수리비 부담이 명시되어 검사한 규칙상 위험 신호를 찾지 못했습니다.'
        fault = bool(re.search(r'고의|과실',t))
        broad = bool(re.search(r'모든|전액|일체|전부|관계없이|무관하게',t))
        if tenant and '부담' in t and (('노후' in t) or (broad and (not fault or '관계없이' in t or '무관하게' in t))):
            return 'potential_risk', 'broad_tenant_repair', '노후화 또는 광범위한 수리비를 임차인에게 부담시키는 조건입니다.'
        if tenant and fault and '부담' in t:
            return 'ok', 'tenant_fault_only', '임차인의 고의·과실로 발생한 손상에 연결된 부담 조건입니다.'
        if re.search(r'추후협의|별도협의',t):
            return 'unknown', 'repair_unspecified', '수리 책임이나 부담 범위가 확정되지 않았습니다.'
    else:
        if '임차인' in t and re.search(r'해지|해제',t) and re.search(r'남은|잔여',t) and '월세' in t and '전액' in t and '위약금' in t:
            if re.search(r'지급하지않|부담하지않',t):return 'ok','penalty_negated','잔여 월세 전액의 위약금 지급을 부정하는 문구입니다.'
            if re.search(r'지급|부담',t):return 'potential_risk','remaining_rent_penalty','해지 시 남은 기간 월세 전액을 위약금으로 요구하는 조건입니다.'
        if re.search(r'임차인(?:은|는|이|가).*(?:해지|해제)(?:할수없|불가|하지못)',t):
            if re.search(r'어떠한|어떤경우|일체|중도',t):return 'risk','termination_prohibited','임차인의 해지권을 넓게 제한하는 명시적 문구입니다.'
            return 'unknown','conditional_prohibition','해지 제한의 적용 조건과 예외를 더 확인해야 합니다.'
        if '임대인' in t and '임차인' in t and re.search(r'조건.*임대인.*정한다|임대인.*마음대로.*해지|임대인만.*해지',t):
            return 'potential_risk','unilateral_termination','해지 조건이나 권한이 일방에게 편중될 수 있습니다.'
        if '계약금' in t and '몰수' in t:
            if re.search(r'몰수하지않|몰수할수없',t):return 'ok','forfeiture_negated','계약금 몰수를 부정하는 문구입니다.'
            if re.search(r'임차인.*(?:해지|해제)',t) and re.search(r'무조건|사유와관계없이|전액',t):return 'potential_risk','forfeiture','임차인의 해지에 계약금 몰수 조건이 연결되어 확인이 필요합니다.'
            return 'unknown','forfeiture_scope','몰수의 주체·사유·범위가 충분히 확인되지 않습니다.'
        if re.search(r'채무.*이행하지않|채무.*이행하지아니|채무불이행',t) and '최고' in t and re.search(r'해제할수있|해지할수있',t):
            return 'ok','breach_notice','채무 불이행과 이행 최고를 전제로 한 해제·해지 조건입니다.'
        if '위약금' in t:
            return 'unknown','penalty_context','위약금의 금액만으로 과도성을 판단하지 않으며 적용 사유·산정 근거 확인이 필요합니다.'
    return 'unknown', 'insufficient_context', '주체·행위·조건을 함께 확인하기에 정보 또는 규칙 적용 범위가 부족합니다.'


def analyze_text(text, *, reviewed=False):
    if not isinstance(text,str):raise TypeError('text must be str')
    findings=[]
    for kind in TYPES:
        spans=[(a,b) for a,b in sentence_spans(text) if re.search(TOPICS[kind],compact(text[a:b]))]
        if not spans:continue
        decisions=[(judge(kind,text[a:b]),a,b) for a,b in spans]
        # A clause-level exception can qualify a preceding sentence; do not ignore it.
        exception=bool(re.search(r'다만|예외|단\s*,',text))
        rank={'risk':3,'potential_risk':2,'unknown':1,'ok':0}
        decision,a,b=max(decisions,key=lambda x:rank[x[0][0]])
        status,rule,reason=decision
        if re.search(r'적용하지않|효력이없|삭제한다|배제한다',compact(text)):exception=True
        if exception:status,rule,reason='unknown','cross_sentence_exception','조항 내 예외가 앞 문장에 미치는 범위를 확인해야 합니다.'
        if not reviewed:status,rule,reason='unknown','ocr_review_required','OCR 원문이 검토되지 않아 주체·조건·부정 표현 확인 전 판단을 보류합니다.'
        evidence=text[a:b]
        findings.append({'risk_type':kind,'risk_status':status,'rule_id':rule,'evidence':evidence,
                         'evidence_span':[a,b],'reason':reason,'context':context_features(text),
                         'possible_disadvantage':{'deposit_return':'보증금 회수 시점이나 금액이 예상과 달라질 수 있습니다.',
                                                  'repair_cost':'예상하지 못한 수리비를 부담할 수 있습니다.',
                                                  'contract_termination':'계약 종료 시 비용이나 권리 행사에 제약이 생길 수 있습니다.'}[kind] if status in {'risk','potential_risk'} else '',
                         'followup_questions':[QUESTIONS[kind]] if status!='ok' else [],
                         'recommended_actions':[ACTIONS[kind]] if status!='ok' else []})
    if not findings:
        findings=[{'risk_type':'unrelated','risk_status':'unknown','rule_id':'out_of_scope' if text.strip() else 'empty_text',
                   'evidence':'','evidence_span':[0,0],'reason':'세 가지 위험 유형의 판단 근거가 없습니다. 안전 판정이 아닙니다.',
                   'context':context_features(text),'possible_disadvantage':'','followup_questions':[QUESTIONS['unrelated']],
                   'recommended_actions':[ACTIONS['unrelated']]}]
    return findings


def analyze_document(document, review_ids=()):
    if not isinstance(document,dict) or not isinstance(document.get('document_id'),str) or not document['document_id']:
        raise ValueError('document_id required')
    clauses=document.get('clauses')
    if not isinstance(clauses,list) or not clauses:raise ValueError('nonempty clauses required')
    ids=[c.get('clause_id') for c in clauses]
    if any(not isinstance(i,str) or not re.fullmatch(r'C\d{3,}',i) for i in ids) or len(ids)!=len(set(ids)):
        raise ValueError('invalid/duplicate clause IDs')
    if set(review_ids)-set(ids):raise ValueError('review metadata includes unknown clause IDs')
    output=[]
    for clause in clauses:
        if 'needs_review' in clause and type(clause['needs_review']) is not bool:
            raise ValueError('needs_review must be bool')
        raw=clause.get('raw_text',clause.get('text'))
        if not isinstance(raw,str):raise ValueError('raw_text or text required')
        pages=clause.get('pages',[clause.get('page')])
        if not pages or any(type(p) is not int or p<1 for p in pages):raise ValueError('positive pages required')
        verified=clause.get('verified_text')
        if verified is not None and not isinstance(verified,str):raise ValueError('verified_text must be str or null')
        reviewed=(verified is not None and clause.get('needs_review') is False) or clause['clause_id'] in review_ids
        # Explicit outstanding review cannot be bypassed by external metadata.
        if clause.get('needs_review') is True:reviewed=False
        text=verified if reviewed and verified is not None else raw
        results=analyze_text(text,reviewed=reviewed)
        output.append({'clause_id':clause['clause_id'],'pages':pages,'page':pages[0],'raw_text':raw,
                       'candidate_text':clause.get('candidate_text'),'candidate_regions':copy.deepcopy(clause.get('candidate_regions',[])),
                       'verified_text':verified,'analysis_text':text,'text_source':'verified_text' if reviewed and verified is not None else 'raw_text',
                       'needs_review':not reviewed,'review_reasons':copy.deepcopy(clause.get('review_reasons',[])),
                       'source_lines':copy.deepcopy(clause.get('source_lines',[])),'findings':results})
    return {'document_id':document['document_id'],'rule_version':VERSION,'clauses':output,
            'legal_determination':False}


def to_api(result):
    status_map={'risk':'potential_risk','potential_risk':'potential_risk','ok':'no_risk_detected','unknown':'needs_review'}
    rows=[];warnings=[]
    for clause in result['clauses']:
        if all(f['risk_status']=='ok' for f in clause['findings']):
            rows.append({'clause_id':clause['clause_id'],'risk_type':'none','risk_status':'no_risk_detected',
                         'evidence':clause['analysis_text'],'reason':'검사한 유형의 규칙 범위에서 위험 신호가 발견되지 않았습니다. 법적 안전 보장은 아닙니다.',
                         'possible_disadvantage':'','question':'','recommended_action':''})
            continue
        for f in clause['findings']:
            a,b=f['evidence_span']
            if clause['analysis_text'][a:b]!=f['evidence']:raise ValueError('Evidence is not an exact source slice')
            kind={'contract_termination':'termination','unrelated':'other'}.get(f['risk_type'],f['risk_type'])
            rows.append({'clause_id':clause['clause_id'],'risk_type':kind,'risk_status':status_map[f['risk_status']],
                         'evidence':f['evidence'],'reason':f['reason'],'possible_disadvantage':f['possible_disadvantage'],
                         'question':'\n'.join(f['followup_questions']),'recommended_action':'\n'.join(f['recommended_actions'])})
        if clause['needs_review']:warnings.append(clause['clause_id']+': OCR 원문 확인 필요; 검증 완료 결과가 아닙니다.')
    partial=any(f['risk_status']=='unknown' for c in result['clauses'] for f in c['findings'])
    if partial and not warnings:warnings.append('일부 조항은 규칙 범위 또는 문맥 부족으로 판단을 보류했습니다.')
    return {'document_id':result['document_id'],'status':'partial' if partial else 'completed','results':rows,'warnings':warnings}
