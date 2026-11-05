"""Python 3.9 worker: decode/validate all images before loading the cached OCR model."""
import json
from pathlib import Path
import sys
import warnings
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def load_images(paths):
    from PIL import Image
    images=[]
    for path in paths:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in {'JPEG','PNG'}:raise ValueError('Unsupported decoded format')
                if image.width*image.height>20_000_000 or getattr(image,'n_frames',1)!=1:raise ValueError('Image pixel/frame limit')
                image.verify()
            with Image.open(path) as image:images.append(image.convert('RGB'))
    return images


def run(request):
    images=load_images(request['images'])
    from scripts.ocr_pages import create_ocr
    from scripts.ocr_experiments import preprocess
    from scripts.structure_ocr import structure
    import numpy as np
    ocr=create_ocr();pages=[]
    for number,image in enumerate(images,1):
        results=list(ocr.predict(np.array(preprocess(image,'contrast_1.5'))))
        if len(results)!=1:raise ValueError('Expected one result per image')
        r=results[0]
        if not len(r['rec_texts'])==len(r['rec_scores'])==len(r['rec_polys']):raise ValueError('Inconsistent OCR output')
        lines=[{'line_id':f'P{number:03}_L{i+1:03}','text':text,'confidence':float(score),'polygon':poly.tolist()}
               for i,(text,score,poly) in enumerate(zip(r['rec_texts'],r['rec_scores'],r['rec_polys']))]
        pages.append({'page':number,'status':'completed','lines':lines})
    result=structure({'document_id':request['document_id'],'pages':pages})
    result['ocr_pages']=pages
    return result


if __name__=='__main__':
    try:
        request=json.loads(Path(sys.argv[1]).read_text())
        # Validation errors are returned without OCR text, filenames or traceback.
        try:load_images(request['images'])
        except Exception:
            result={'error':{'status':415,'code':'UNSUPPORTED_FILE_TYPE'}}
        else:
            try:result=run(request)
            except Exception:result={'error':{'status':500,'code':'OCR_PROCESSING_ERROR'}}
        Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    except Exception:sys.exit(1)
