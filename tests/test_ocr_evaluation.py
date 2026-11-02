import unittest
from scripts.ocr_evaluation import normalize_text, edit_distance, score, evaluate, evaluate_corpus


class EvaluationTests(unittest.TestCase):
    def test_explicit_whitespace(self):
        self.assertEqual(normalize_text(' 가\t나\r\n다\v라\f마\u00a0바\u3000 '), '가나다라마바')

    def test_unlisted_unicode_is_preserved(self):
        self.assertEqual(normalize_text('가\u200b\ufeff\u2009나'), '가\u200b\ufeff\u2009나')

    def test_raw_and_normalized_separate(self):
        result = evaluate('가 나\n', '가나')
        self.assertEqual(result['raw']['cer'], 0.5)
        self.assertEqual(result['normalized']['cer'], 0)

    def test_won_not_backslash(self):
        self.assertEqual(evaluate('₩', '\\')['normalized']['cer'], 1)

    def test_bullet_not_y_diaeresis(self):
        self.assertEqual(evaluate('•', 'Ÿ')['normalized']['cer'], 1)

    def test_no_unicode_or_width_normalization(self):
        for left, right in [('가', '\u1100\u1161'), ('１', '1'), ('①', '1'), ('·', '․'), ('A', 'a')]:
            with self.subTest(left=left):
                self.assertGreater(evaluate(left, right)['normalized']['cer'], 0)

    def test_numeric_and_negation_differences_survive(self):
        for left, right in [('10만원', '100만원'), ('2026.11.02', '2026.11.03'),
                            ('2년', '3년'), ('할 수 없다', '할 수 있다'), ('1,000', '1000')]:
            with self.subTest(left=left):
                self.assertGreater(evaluate(left, right)['normalized']['cer'], 0)

    def test_blank_underscores_preserved(self):
        self.assertEqual(normalize_text('___ 년 □'), '___년□')

    def test_known_levenshtein(self):
        self.assertEqual(edit_distance('kitten', 'sitting'), 3)
        self.assertEqual(score('kitten', 'sitting')['cer'], 0.5)

    def test_insertion_deletion_substitution(self):
        for ref, hyp in [('가', '가나'), ('가나', '가'), ('가', '나')]:
            self.assertEqual(edit_distance(ref, hyp), 1)

    def test_cer_can_exceed_one(self):
        self.assertEqual(score('가', '가나다라')['cer'], 3)

    def test_empty_reference(self):
        self.assertIsNone(score('', '')['cer'])
        self.assertIsNone(score('', '가')['cer'])
        self.assertEqual(score('', '가')['edit_distance'], 1)
        self.assertIsNone(evaluate(' \n', '가')['normalized']['cer'])

    def test_missing_ocr_text_is_deletion(self):
        self.assertEqual(score('계약서', '')['cer'], 1)

    def test_symmetric_normalization_idempotent(self):
        self.assertEqual(evaluate(' 가\n나 ', '가\t나')['normalized']['cer'], 0)
        text = ' ₩\n• □ 10만원 '
        self.assertEqual(normalize_text(normalize_text(text)), normalize_text(text))

    def test_invalid_inputs(self):
        for value in [None, 123, [], b'text']:
            with self.assertRaises(TypeError):
                evaluate('text', value)

    def test_corpus_micro_not_average(self):
        result = evaluate_corpus({'C001': '가', 'C002': '나다라'}, {'C002': '나다라', 'C001': ''})
        self.assertEqual(result['micro']['raw']['cer'], 0.25)

    def test_corpus_boundaries_preserved(self):
        result = evaluate_corpus({'A': '가', 'B': '나'}, {'A': '가나', 'B': ''})
        self.assertEqual(result['micro']['raw']['cer'], 1)

    def test_corpus_empty_reference_insertions_counted(self):
        result = evaluate_corpus({'A': '', 'B': '가'}, {'A': '나', 'B': '가'})
        self.assertEqual(result['micro']['raw']['cer'], 1)
        self.assertEqual(result['micro']['raw']['empty_reference_ids'], ['A'])

    def test_corpus_ids_and_empty_input(self):
        with self.assertRaises(ValueError):
            evaluate_corpus({'A': '가'}, {})
        with self.assertRaises(ValueError):
            evaluate_corpus({}, {})


if __name__ == '__main__':
    unittest.main()
