"""Local review sidecar; never a server approval or analysis request."""
import copy
import math
import re


def build_review_document(structured, pages, api):
    clauses=structured.get('clauses',[])
    page_list=pages.get('pages',[])
    page_numbers=[p['page'] for p in page_list]
    if not page_numbers or sorted(page_numbers)!=list(range(1,len(page_numbers)+1)):raise ValueError('Invalid page sequence')
    if structured.get('document_id')!=api.get('document_id') or structured.get('document_id')!=pages.get('document_id'):raise ValueError('Document mismatch')
    ids=[c.get('clause_id') for c in clauses]
    if not ids or len(ids)!=len(set(ids)) or any(not isinstance(i,str) or not re.fullmatch(r'C\d{3,}',i) for i in ids):raise ValueError('Invalid clause IDs')
    if ids!=[c['clause_id'] for c in api['clauses']]:raise ValueError('Missing or reordered clause IDs')
    source={}
    for page in page_list:
        for line in page['lines']:
            key=(page['page'],line['line_id'])
            if key in source:raise ValueError('Duplicate source line')
            source[key]=line
    records=[]
    for clause,preview in zip(clauses,api['clauses']):
        nums=clause['pages'];raw=clause['raw_text'];lines=clause.get('source_lines',[])
        if not nums or len(nums)!=len(set(nums)) or any(type(n) is not int or n not in page_numbers for n in nums):raise ValueError('Invalid clause page')
        if preview['page']!=nums[0] or preview['text']!=raw:raise ValueError('API source mismatch')
        if not isinstance(raw,str) or not raw.strip():raise ValueError('Empty OCR text')
        if lines and raw!=''.join(l['text']+'\n' for l in lines):raise ValueError('Raw source mismatch')
        refs=[]
        for line in lines:
            original=source.get((line['page'],line['line_id']))
            if not original or line['page'] not in nums or original['text']!=line['text']:raise ValueError('Source line mismatch')
            polygon=original.get('polygon')
            if polygon is not None and (not isinstance(polygon,list) or len(polygon)<3 or any(not isinstance(p,list) or len(p)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in polygon)):raise ValueError('Invalid polygon')
            refs.append({'page':line['page'],'line_id':line['line_id'],'text':original['text'],
                         'polygon':copy.deepcopy(polygon),'coordinate_space':'ocr_input_pixels' if polygon is not None else None})
        records.append({'clause_id':clause['clause_id'],'page':nums[0],'pages':list(nums),'raw_text':raw,
                        'edited_text':raw,'source_lines':refs,'status':'needs_review','reviewed_by_user':False})
    return {'format':'safecontract-local-review-v1','document_id':structured['document_id'],'page_count':len(page_list),
            'expected_clause_ids':ids,'document_revision':0,'source_kind':'cached_actual_ocr',
            'server_approved':False,'privacy_scan_status':'pending','external_llm_allowed':False,'clauses':records}
