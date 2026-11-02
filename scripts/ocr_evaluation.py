"""Pure text evaluation under safecontract-ocr-normalization-v1; no OCR or file writes."""
POLICY_VERSION = 'safecontract-ocr-normalization-v1'
# Explicit allowlist: do not use broad Unicode normalization or str.isspace().
IGNORED_WHITESPACE = frozenset(' \t\n\r\v\f\u00a0\u3000')


def normalize_text(text):
    """Remove only the eight documented whitespace code points."""
    if not isinstance(text, str):
        raise TypeError('text must be a string')
    return ''.join(char for char in text if char not in IGNORED_WHITESPACE)


def edit_distance(reference, hypothesis):
    """Unit-cost Levenshtein distance on Python Unicode code points."""
    if not isinstance(reference, str) or not isinstance(hypothesis, str):
        raise TypeError('reference and hypothesis must be strings')
    # Distance is symmetric; keep the DP row on the shorter string.
    if len(reference) > len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(reference) + 1))
    for row, char in enumerate(hypothesis, 1):
        current = [row]
        for col, target in enumerate(reference, 1):
            current.append(min(current[-1] + 1, previous[col] + 1,
                               previous[col - 1] + (target != char)))
        previous = current
    return previous[-1]


def score(reference, hypothesis, *, normalized=False):
    """CER = edit distance / reference length; empty reference gives CER None."""
    if not isinstance(reference, str) or not isinstance(hypothesis, str):
        raise TypeError('reference and hypothesis must be strings')
    if normalized:
        reference, hypothesis = normalize_text(reference), normalize_text(hypothesis)
    errors = edit_distance(reference, hypothesis)
    length = len(reference)
    return {'edit_distance': errors, 'reference_characters': length,
            'hypothesis_characters': len(hypothesis),
            'cer': errors / length if length else None,
            'empty_reference': length == 0}


def evaluate(reference, hypothesis):
    """Return raw and normalized metrics together; inputs are never mutated."""
    return {'policy_version': POLICY_VERSION,
            'raw': score(reference, hypothesis),
            'normalized': score(reference, hypothesis, normalized=True)}


def evaluate_corpus(references, hypotheses):
    """Match clauses by ID; report micro CER without joining clause boundaries."""
    if not isinstance(references, dict) or not isinstance(hypotheses, dict):
        raise TypeError('corpus inputs must be dictionaries keyed by clause ID')
    if references.keys() != hypotheses.keys():
        raise ValueError('clause IDs must match; represent missing OCR text as an empty string')
    if not references:
        raise ValueError('corpus must contain at least one clause')
    clauses = {cid: evaluate(text, hypotheses[cid]) for cid, text in references.items()}
    totals = {}
    for mode in ('raw', 'normalized'):
        errors = sum(item[mode]['edit_distance'] for item in clauses.values())
        length = sum(item[mode]['reference_characters'] for item in clauses.values())
        totals[mode] = {'edit_distance': errors, 'reference_characters': length,
                        'cer': errors / length if length else None,
                        'empty_reference_ids': [cid for cid, item in clauses.items()
                                                if item[mode]['empty_reference']]}
    return {'policy_version': POLICY_VERSION, 'clauses': clauses, 'micro': totals}
