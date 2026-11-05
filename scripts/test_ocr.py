"""Run Korean image OCR; optional UTF-8 reference must cover the entire image."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import tempfile
import time

try:
    from .ocr_experiments import ROOT, DET, REC, preprocess, save_json
    from .ocr_evaluation import evaluate
except ImportError:
    from ocr_experiments import ROOT, DET, REC, preprocess, save_json
    from ocr_evaluation import evaluate


def run(input_path, reference_path=None, page=2):
    from PIL import Image

    if input_path.suffix.lower() not in {'.jpg', '.jpeg', '.png'}:
        raise ValueError('JPG/JPEG/PNG 이미지를 지정하세요.')
    with Image.open(input_path) as source:
        if source.format not in {'JPEG', 'PNG'}:
            raise ValueError('실제 이미지 형식이 JPEG/PNG가 아닙니다.')
        image = source.convert('RGB')
    reference = None
    if reference_path is not None:
        if reference_path.suffix.lower() != '.txt':
            raise ValueError('정답은 이미지 전체 범위와 읽기 순서가 일치하는 UTF-8 TXT여야 합니다.')
        with reference_path.open(encoding='utf-8', newline='') as stream:
            reference = stream.read()

    try:
        from .ocr_test_evaluation import source_scope, assess, environment, compare
    except ImportError:
        from ocr_test_evaluation import source_scope, assess, environment, compare
    scope, scope_error = None, None
    if reference is None:
        try:
            scope = source_scope(image, page)
        except (OSError, ValueError, KeyError, IndexError) as exc:
            scope_error = str(exc)

    os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
    from paddleocr import PaddleOCR

    root = ROOT / 'tmp/ocr_test'
    root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('run_%Y%m%d_%H%M%S_'), dir=root))
    try:
        preprocess(image, 'contrast_1.5').save(output / 'input.png')
        print('모델 초기화 중...', flush=True)
        ocr = PaddleOCR(lang='korean', text_detection_model_name=DET,
                        text_recognition_model_name=REC,
                        use_doc_orientation_classify=False, use_doc_unwarping=False,
                        use_textline_orientation=False)
        env = environment(ocr)
        save_json(output / 'environment.json', env)
        print('OCR 실행 중...', flush=True)
        start = time.perf_counter()
        results = list(ocr.predict(str(output / 'input.png')))
        seconds = time.perf_counter() - start
        if len(results) != 1:
            raise ValueError('이미지 1개에 대한 OCR 결과가 필요합니다.')
        result = results[0]
        texts, scores, polygons = result['rec_texts'], result['rec_scores'], result['rec_polys']
        if not len(texts) == len(scores) == len(polygons):
            raise ValueError('OCR 텍스트·좌표·신뢰도 개수가 다릅니다.')
        text = '\n'.join(texts) + ('\n' if texts else '')
        (output / 'text.txt').write_text(text, encoding='utf-8')
        lines = [{'line_id':i, 'text':t, 'confidence':float(s), 'polygon':p.tolist()}
                 for i,(t,s,p) in enumerate(zip(texts,scores,polygons))]
        metrics = evaluate(reference, text) if reference is not None else None
        evaluation = None
        comparison = {'comparable':False,'reason':'전체 TXT 평가 또는 확인되지 않은 입력 범위'}
        if scope is not None:
            try:
                evaluation = assess(lines, scope, image.size)
                metrics = evaluation['metrics']
                comparison = compare(metrics, scope, env, input_path)
                save_json(output / 'clause_errors.json', evaluation['analysis'])
            except ValueError as exc:
                scope_error = str(exc)
        save_json(output / 'evaluation.json', {'metrics':metrics,'reason':scope_error,
                  'page':page,'source_evidence':{k:v for k,v in scope.items() if k not in ('clauses','regions')} if scope else None,'assignment':evaluation['assignment'] if evaluation else None,
                  'scope': 'verified PDF clauses' if evaluation else 'user TXT' if reference is not None else None})
        save_json(output / 'comparison.json', comparison)
        save_json(output / 'result.json', {
            'input': str(input_path.resolve()), 'preprocessing': 'contrast_1.5',
            'models': [DET, REC], 'line_count': len(texts), 'ocr_seconds': seconds,
            'timing': 'predict only; initialization, preprocessing and evaluation excluded',
            'lines': [{'text': t, 'confidence': float(s), 'polygon': p.tolist()}
                      for t, s, p in zip(texts, scores, polygons)],
            'reference': str(reference_path.resolve()) if reference_path else None,
            'evaluation_scope': 'D-7 verified clause geometry' if evaluation else 'full image TXT' if reference is not None else 'unavailable',
            'metrics': metrics})
        print(f'인식 줄 수: {len(texts)} / OCR 처리 시간: {seconds:.2f}초')
        if metrics is None:
            print(f'CER: 평가 불가 ({scope_error})')
        else:
            for mode in ('raw', 'normalized'):
                cer = (metrics['micro'] if evaluation else metrics)[mode]['cer']
                print(f'{mode.capitalize()} CER: {cer:.4%}' if cer is not None
                      else f'{mode.capitalize()} CER: 계산 불가 (정답 문자 없음)')
        if evaluation:
            print('조항별 CER (Raw / Normalized):')
            for cid, score in metrics['clauses'].items():
                print(f"  {cid}: {score['raw']['cer']:.4%} / {score['normalized']['cer']:.4%}")
            print('주요 용어 차이 (법률적 의미 판정 아님):')
            for item in evaluation['analysis']['term_checks']:
                print(f"  {item['clause_id']} {item['type']}: {item['term']} ({item['reference_count']} → {item['ocr_count']})")
            for item in evaluation['analysis']['differences']:
                print(f"  {item['clause_id']} {item['type']}/{item['operation']}\n    정답: {item['reference_context']}\n    OCR: {item['ocr_context']}")
            print('미기입 금액·날짜 정확도는 확인할 수 없습니다.')
        print('D-7 비교:', comparison)
        print(f'결과: {output}')
        return output
    except Exception as exc:
        save_json(output / 'error.json', {'error': str(exc)})
        print(f'실패 기록: {output / "error.json"}')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'tmp/ocr_test/contract_page2.png',
                        help='JPG/PNG 이미지 (기본: 기존 계약서 2페이지)')
    parser.add_argument('--ground-truth', type=Path,
                        help='이미지 전체와 동일 범위·순서의 UTF-8 정답 TXT; 조항 JSON은 지원하지 않음')
    parser.add_argument('--page', type=int, choices=range(1,6), default=2, help='원본 PDF 물리적 페이지; 해당 페이지의 2배 렌더만 자동 평가')
    args = parser.parse_args()
    try:
        run(args.input, args.ground_truth, args.page)
    except Exception as exc:
        parser.exit(1, f'OCR 테스트 실패: {exc}\n')


if __name__ == '__main__':
    main()
