#!/usr/bin/env python3
"""Validate schema and PDF correspondence; automatic matching is not human verification."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from extract_contract_text import (PDF, SAMPLE, REVIEW, CATEGORIES, EXPECTED_HASH,
                                   inspect_pdf, expected_clauses, sha256, write_json)


def normalized(text):
    return re.sub(r'\s+', '', text)


def numbers(text):
    return re.findall(r'\d+|[①-⑳]', text)


def validate(sample, pdf):
    report = {'passed': [], 'failed': [], 'needs_review': [], 'unverified': [],
              'automatic_match_is_human_verification': False}

    def add(bucket, check, detail, clause_id=None):
        report[bucket].append({'check': check, 'clause_id': clause_id, 'detail': detail})

    try:
        data = json.loads(Path(sample).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        add('failed', 'json_read', str(exc))
        return finish(report)
    if not isinstance(data, dict):
        add('failed', 'root_type', 'JSON 최상위는 object이어야 함')
        return finish(report)
    required = {'document_id': str, 'source_file': str, 'document_type': str,
                'page_count': int, 'clauses': list}
    for key, kind in required.items():
        if type(data.get(key)) is not kind or (kind is str and not data[key].strip()):
            add('failed', 'required_field', key)
    if report['failed']:
        return finish(report)
    add('passed', 'json_schema_root', '필수 루트 필드 타입 정상')
    if data['document_type'] != 'housing_lease_contract':
        add('failed', 'document_type', data['document_type'])
    if data['page_count'] < 1:
        add('failed', 'page_count', '양의 정수 필요')
    pages = None
    expected = {}
    try:
        if data['source_file'] != Path(pdf).name:
            add('failed', 'source_file', 'JSON 파일명과 지정 PDF 파일명 불일치')
        pages = inspect_pdf(pdf)
        digest = sha256(pdf)
        add('passed', 'source_exists', str(pdf))
        if data.get('source_sha256') and data['source_sha256'] != digest:
            add('failed', 'source_hash', 'PDF 해시 불일치')
        if len(pages) != data['page_count']:
            add('failed', 'actual_page_count', f"JSON={data['page_count']}, PDF={len(pages)}")
        else:
            add('passed', 'actual_page_count', len(pages))
        if digest == EXPECTED_HASH:
            expected = {c['clause_id']: c for c in expected_clauses(pages)}
        else:
            add('unverified', 'selection_completeness', '알려진 선별 프로필과 다른 PDF')
    except Exception as exc:
        add('failed', 'source_read', str(exc))
    seen = set()
    text_seen = set()
    exact_count = 0
    for index, c in enumerate(data['clauses'], 1):
        if not isinstance(c, dict):
            add('failed', 'clause_type', index)
            continue
        cid = c.get('clause_id')
        fields = {'clause_id': str, 'page': int, 'text': str,
                  'category': str, 'verification_status': str}
        bad = [key for key, kind in fields.items() if type(c.get(key)) is not kind]
        if bad:
            add('failed', 'clause_fields', bad, str(cid))
            continue
        if not re.fullmatch(r'C\d{3,}', cid):
            add('failed', 'clause_id_format', cid, cid)
        if cid in seen:
            add('failed', 'duplicate_clause_id', cid, cid)
        seen.add(cid)
        if not c['text'].strip():
            add('failed', 'empty_text', '빈 text', cid)
        key = (c['page'], normalized(c['text']))
        if key in text_seen:
            add('needs_review', 'duplicate_text', '동일 페이지의 중복 텍스트', cid)
        text_seen.add(key)
        if c['category'] not in CATEGORIES:
            add('failed', 'category', c['category'], cid)
        if c['verification_status'] not in {'verified', 'needs_review', 'not_verified'}:
            add('failed', 'verification_status', c['verification_status'], cid)
        if c['verification_status'] == 'verified':
            proof = c.get('human_verification')
            if not isinstance(proof, dict) or not all(isinstance(proof.get(k), str) and proof[k].strip()
                                                     for k in ['reviewer', 'reviewed_at', 'method']):
                add('failed', 'human_verification_evidence', 'verified에 대한 사람의 검토 기록 없음', cid)
            else:
                add('unverified', 'human_verification_authenticity', '검토 기록의 진위는 자동 검증 불가', cid)
        else:
            add('needs_review', 'human_verification', '사람의 원본 대조 미완료', cid)
        limit = len(pages) if pages is not None else data['page_count']
        if not 1 <= c['page'] <= limit:
            add('failed', 'page_range', c['page'], cid)
            continue
        if not pages:
            add('unverified', 'source_text', 'PDF 읽기 실패로 대조 불가', cid)
            continue
        reference = expected.get(cid)
        if reference:
            if c['page'] != reference['page']:
                add('failed', 'page_mapping', f"예상 페이지 {reference['page']}", cid)
                continue
            target = reference['text']
            if c.get('source_blocks') != reference['source_blocks']:
                add('failed', 'source_blocks', '원본 블록 인덱스/좌표 불일치', cid)
            if c['text'] == target:
                exact_count += 1
                add('passed', 'exact_source_match', '선별한 원본 블록 전체와 문자 단위 일치', cid)
            elif normalized(c['text']) == normalized(target):
                add('needs_review', 'whitespace_only_difference', '공백·줄바꿈 차이; 의미 오류로 확정하지 않음', cid)
            else:
                add('needs_review', 'text_difference', '원본 선별 범위와 불일치; 사람이 대조해야 함', cid)
            if numbers(c['text']) != numbers(target):
                add('needs_review', 'number_or_article_difference',
                    {'source': numbers(target), 'json': numbers(c['text'])}, cid)
            else:
                add('passed', 'numbers_and_article_markers', '숫자·조항 번호 토큰 일치', cid)
        else:
            raw = pages[c['page'] - 1]['text']
            if c['text'] and c['text'] in raw:
                add('passed', 'page_substring_match', '해당 페이지 원시 텍스트에 존재', cid)
            elif normalized(c['text']) and normalized(c['text']) in normalized(raw):
                add('needs_review', 'normalized_page_match', '공백 정규화 후 일치', cid)
            else:
                add('needs_review', 'page_text_not_matched', '해당 페이지 자동 일치 없음; 오류 확정 아님', cid)
            add('unverified', 'clause_completeness', '원문 범위 프로필 없어 숫자·문장 누락 확정 불가', cid)
    if not data['clauses']:
        add('failed', 'clauses_empty', '조항 목록이 비어 있음')
    if expected and seen != set(expected):
        add('failed', 'selection_coverage', {'missing': sorted(set(expected) - seen),
                                          'unexpected': sorted(seen - set(expected))})
    report['summary'] = {'clause_count': len(data['clauses']), 'exact_source_matches': exact_count,
                         'category_counts': dict(Counter(c.get('category') for c in data['clauses']
                                                         if isinstance(c, dict) and isinstance(c.get('category'), str))),
                         'verified_clauses': sum(isinstance(c, dict) and c.get('verification_status') == 'verified'
                                                 for c in data['clauses'])}
    add('unverified', 'visual_glyph_fidelity', '텍스트 레이어끼리의 일치는 원화·글머리표 등 시각적 기호 정확성을 보장하지 않음')
    return finish(report)


def finish(report):
    report['structure_valid'] = not report['failed']
    report['status'] = 'failed' if report['failed'] else ('needs_review' if report['needs_review'] or report['unverified'] else 'passed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', type=Path, default=SAMPLE)
    parser.add_argument('--pdf', type=Path, default=PDF)
    parser.add_argument('--report', type=Path, help='기존 검토 파일에 automatic_validation 항목 저장')
    args = parser.parse_args()
    report = validate(args.json, args.pdf)
    if args.report:
        try:
            existing = json.loads(args.report.read_text(encoding='utf-8')) if args.report.exists() else {}
            if not isinstance(existing, dict):
                raise ValueError('검토 보고서 최상위 object 필요')
            existing['automatic_validation'] = report
            write_json(args.report, existing)
        except (OSError, ValueError) as exc:
            parser.exit(1, f'검토 보고서 저장 실패: {exc}\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # 0: machine checks passed (human review can still be pending); 1: failure.
    raise SystemExit(1 if report['failed'] else 0)


if __name__ == '__main__':
    main()
