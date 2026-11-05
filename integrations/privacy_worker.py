"""Python 3.9 local OCR privacy worker. Only redacted findings are serialized."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from integrations.ocr_worker import load_images
from integrations.privacy_detection import scan_lines, result


def run(path):
    images = load_images([path])
    # Reuse D-7 models/preprocessing. Require local caches before model initialization.
    cache = Path.home() / '.paddlex/official_models'
    for name in ('PP-OCRv5_server_det', 'korean_PP-OCRv5_mobile_rec'):
        if not (cache / name / 'inference.pdiparams').is_file():
            return result('failed')
    from scripts.ocr_pages import create_ocr
    from scripts.ocr_experiments import preprocess
    import numpy as np
    output = list(create_ocr().predict(np.array(preprocess(images[0], 'contrast_1.5'))))
    if len(output) != 1: return result('failed')
    r = output[0]
    if len(r['rec_texts']) != len(r['rec_scores']): return result('failed')
    return scan_lines([{'text': t, 'confidence': float(s)} for t, s in zip(r['rec_texts'], r['rec_scores'])])

if __name__ == '__main__':
    try:
        try: response = run(sys.argv[1])
        except Exception: response = result('failed')
        Path(sys.argv[2]).write_text(json.dumps(response, ensure_ascii=False), encoding='utf-8')
    except Exception: sys.exit(1)
