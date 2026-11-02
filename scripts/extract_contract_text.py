#!/usr/bin/env python3
"""Extract a reviewed block selection from the supplied blank contract, without OCR."""
import argparse
import hashlib
import json
from pathlib import Path

try:
    import fitz
except ImportError:
    raise SystemExit('PyMuPDF 필요: python -m pip install PyMuPDF==1.26.5')

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / 'data/contracts/original/standard_contract.pdf'
SAMPLE = ROOT / 'data/ocr/sample_contract.json'
REVIEW = ROOT / 'data/ocr/extraction_review.json'
EXPECTED_HASH = '9b514b8497bd2cde78969a1111718b1aea2bd9911c49710d7ac676e0683468d5'
CATEGORIES = {'deposit_return', 'repair_responsibility', 'termination', 'rent',
              'management_fee', 'contract_period', 'renewal', 'restoration', 'special_terms', 'other'}
# Explicit selection for this exact PDF/version only. Indices are zero-based text blocks.
# Keep block text unchanged; article 4's table is restored to its visual position.
PROFILE = [
    (1, list(range(26, 46)), 'rent', ['management_fee'], '제1조'),
    (1, [2, 3], 'contract_period', [], '제2조'),
    (1, list(range(4, 10)), 'repair_responsibility', [], '제3조'),
    (2, [1, 2, 3, 4, 41, 42, 43, 44, 5], 'repair_responsibility', [], '제4조'),
    (2, [6, 7], 'termination', [], '제5조'),
    (2, [8, 9], 'termination', [], '제6조'),
    (2, [10, 11, 12], 'termination', [], '제7조'),
    (2, list(range(13, 18)), 'renewal', [], '제8조'),
    (2, [18, 19], 'deposit_return', ['restoration'], '제9조'),
    (2, [20, 21, 22], 'management_fee', [], '제10조'),
    (2, [23, 24], 'other', [], '제11조'),
    (2, [25, 26], 'other', [], '제12조'),
    (2, [27, 28], 'other', [], '제13조'),
    (2, [30, 31], 'special_terms', [], 'Ÿ 주택을'),
    (2, [32, 33], 'special_terms', ['termination'], 'Ÿ 임대인이'),
    (2, [34, 35], 'special_terms', ['termination'], 'Ÿ 임대차계약을'),
    (2, [36, 37, 38], 'special_terms', [], 'Ÿ 주택임대차계약과'),
    (2, [39], 'special_terms', [], 'Ÿ 주택의'),
    (2, [40], 'special_terms', [], 'Ÿ 상세주소가'),
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def inspect_pdf(path):
    with fitz.open(path) as doc:
        if doc.needs_pass:
            raise ValueError('암호로 보호된 PDF: 텍스트 추출 불가')
        pages = []
        for number, page in enumerate(doc, 1):
            blocks = [b for b in page.get_text('blocks', sort=False) if b[6] == 0]
            text = page.get_text('text', sort=False)
            pages.append({'page': number, 'text': text, 'blocks': blocks,
                          'has_text': bool(text.strip())})
        return pages


def expected_clauses(pages):
    clauses = []
    for number, (page, indices, category, related, anchor) in enumerate(PROFILE, 1):
        blocks = pages[page - 1]['blocks']
        text = ''.join(blocks[index][4] for index in indices)
        if anchor not in text:
            raise ValueError(f'추출 레이아웃 불일치: {anchor}; PyMuPDF 버전 확인 필요')
        clauses.append({
            'clause_id': f'C{number:03d}', 'page': page, 'text': text,
            'category': category, 'related_categories': related,
            'verification_status': 'needs_review',
            'source_blocks': [{'index': index, 'bbox': list(blocks[index][:4])}
                              for index in indices],
        })
    return clauses


def make_review(clauses):
    items = []
    for c in clauses:
        reasons = ['사람의 원본 대조 미완료. 줄바꿈, 숫자, 조항 번호 및 조건 전체를 원본과 확인할 것.']
        types = ['human_verification_pending']
        if c['clause_id'] == 'C001':
            types += ['table_reading_order', 'glyph_mismatch', 'blank_fields']
            reasons += ['관리비 표가 1·3·5·7, 2·4·6·8 순서로 추출됨. 시각적 행·열 대응 확인 필요.',
                        '금액의 원화 기호가 역슬래시로 추출됨. 보정하지 않았으며 금액·날짜 빈칸은 실제 값이 아님.']
        if c['clause_id'] in {'C002', 'C003'}:
            types += ['blank_fields']
            reasons += ['입주일·종료일·수리 일정·선택란은 미기입 상태. 빈칸을 채우지 않았음.']
        if c['clause_id'] == 'C004':
            types += ['table_reading_order']
            reasons += ['원시 텍스트 끝에 추출된 임대인/임차인 부담 표를 제4조 ③과 ④ 사이에 배치. source_blocks 순서 및 표의 예시 문구를 확인할 것.']
        if c['category'] == 'special_terms':
            types += ['glyph_mismatch']
            reasons += ['원본 글머리표가 Ÿ로 추출됨. 임의 치환하지 않았음.']
        items.append({'clause_id': c['clause_id'], 'page': c['page'],
                      'problem_types': types, 'reason': ' '.join(reasons), 'status': 'needs_review'})
    items.append({'page': 5, 'clause_id': None, 'problem_types': ['printed_page_count_mismatch'],
                  'reason': '실제 PDF는 5쪽이지만 인쇄 쪽수는 - 5 / 4 - 등으로 표기됨. JSON은 물리적 PDF 페이지 번호 사용.',
                  'status': 'needs_review'})
    topics = [
        ('deposit_return_conditions', [9]), ('deposit_return_timing', [9]),
        ('repair_responsibility', [3, 4]), ('repair_cost_payer', [3, 4]),
        ('termination_conditions', [5, 6, 7, 15, 16]),
        ('early_termination_fixed_penalty', []), ('rent', [1]),
        ('management_fee', [1, 10]), ('contract_period', [2]), ('move_in_date', [2]),
        ('renewal', [8]), ('restoration', [9]), ('special_terms', list(range(14, 20))),
    ]
    return {
        'document_id': 'standard_contract_001',
        'dataset_role': 'ocr_reference_candidate_not_ocr_output',
        'human_verification_completed': False,
        'assistant_visual_inspection': {'pages': [1, 2, 3, 4, 5],
            'scope': '문서 분류, 빈 양식 확인, 표 배치 및 추출 기호 오류 확인. 사람의 문자 단위 검증을 대체하지 않음.'},
        'review_items': items,
        'topic_coverage': [{'topic': topic, 'status': 'found' if ids else 'not_found',
                            'clause_ids': [f'C{i:03d}' for i in ids]} for topic, ids in topics],
        'coverage_notes': [
            '중도해지의 정액 위약금은 계약 본문에서 발견하지 못함. 제5~7조의 해제·손해배상·해지와 동일시하지 않음.',
            '제1~13조 및 인쇄된 특약 6개를 수록. 별지의 법률 안내와 갱신거절통지서는 계약 조항에 혼합하지 않음.',
            '관리비 및 원상복구는 다른 주제와 중복되어 related_categories로도 표시. category는 개발용 분류.',
        ],
        'page_scope': [
            {'page': 1, 'role': 'contract_body', 'included': True},
            {'page': 2, 'role': 'contract_body_and_special_terms', 'included': True},
            {'page': 3, 'role': 'blank_other_terms_and_signature_form', 'included': False,
             'reason': '추가 특약란과 개인정보 기입란은 빈 양식. 서명·보관 문구는 이번 핵심 조항 선별 범위 밖.'},
            {'page': 4, 'role': 'legal_guidance_annex', 'included': False},
            {'page': 5, 'role': 'renewal_refusal_notice_template', 'included': False},
        ],
        'unverified': ['사람의 원문 문자 단위 대조', '공식 웹 첨부파일과 로컬 파일의 바이트 동일성'],
    }


def extract(pdf, output, review, force=False):
    if not force and (output.exists() or review.exists()):
        raise ValueError('기존 결과 보호: 별도 출력 경로 또는 --force 사용(검토 이력 초기화).')
    pages = inspect_pdf(pdf)
    empty = [p['page'] for p in pages if not p['has_text']]
    if empty:
        raise ValueError(f'텍스트 레이어 없는 페이지 {empty}: 이미지 기반/빈 페이지 여부 검토 필요. OCR 미실행.')
    if sha256(pdf) != EXPECTED_HASH:
        raise ValueError('지원 프로필과 다른 PDF. 임의 조항 선택 방지를 위해 중단; 원본별 선별 검토 필요.')
    if fitz.VersionBind != '1.26.5':
        raise ValueError('블록 재현성을 위해 PyMuPDF==1.26.5 사용 필요')
    clauses = expected_clauses(pages)
    sample = {'document_id': 'standard_contract_001', 'source_file': pdf.name,
              'document_type': 'housing_lease_contract', 'page_count': len(pages),
              'dataset_role': 'ocr_reference_candidate_not_ocr_output',
              'ground_truth_status': 'pending_human_verification',
              'source_sha256': sha256(pdf),
              'extraction': {'method': 'pdf_text_layer', 'library': 'PyMuPDF',
                             'version': fitz.VersionBind, 'ocr_executed': False,
                             'text_policy': '원본 블록의 문자·공백·줄바꿈 보존. source_blocks 순서로만 결합.'},
              'clauses': clauses}
    write_json(output, sample)
    write_json(review, make_review(clauses))
    return {'page_count': len(pages), 'text_pages': len(pages), 'clause_count': len(clauses),
            'human_verified': 0, 'needs_review': len(clauses)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, default=PDF)
    parser.add_argument('--output', type=Path, default=SAMPLE)
    parser.add_argument('--review', type=Path, default=REVIEW)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(extract(args.pdf, args.output, args.review, args.force), ensure_ascii=False))
    except Exception as exc:
        parser.exit(1, f'추출 실패: {exc}\n')


if __name__ == '__main__':
    main()
