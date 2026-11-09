
from pathlib import Path
import json
import time
import os

import fitz
from PIL import Image, ImageEnhance
from paddleocr import PaddleOCR


# 프로젝트 경로
ROOT = Path(__file__).resolve().parents[1]

PDF_PATH = ROOT / "data/contracts/original/standard_contract.pdf"
OUTPUT_DIR = ROOT / "tmp/ocr_pages"




def create_ocr():
    """공통 한글 모델을 사용하고 Windows 실행 옵션을 적용한다."""
    options = {
        "text_detection_model_name": "PP-OCRv5_server_det",
        "text_recognition_model_name": "korean_PP-OCRv5_mobile_rec",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }

    if os.name == "nt":
        options["device"] = "cpu"
        options["enable_mkldnn"] = False

    return PaddleOCR(**options)


def process_page(page, page_number, ocr):
    """PDF 페이지 한 장을 이미지로 변환하고 OCR 실행"""

    print(f"\n[{page_number}페이지] 이미지 변환 시작", flush=True)

    # PDF 페이지를 2배 해상도로 렌더링
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)

    image_path = OUTPUT_DIR / f"page_{page_number:03d}.png"
    pix.save(str(image_path))

    # 대비 1.5배 전처리
    with Image.open(image_path) as img:
        enhanced = ImageEnhance.Contrast(
            img.convert("RGB")
        ).enhance(1.5)

        processed_path = OUTPUT_DIR / f"page_{page_number:03d}_contrast.png"
        enhanced.save(processed_path)

    print(f"[{page_number}페이지] OCR 실행 중...", flush=True)

    start = time.perf_counter()
    results = list(ocr.predict(str(processed_path)))
    elapsed = time.perf_counter() - start

    lines = []

    for result in results:
        data = result.json

        if "res" in data:
            data = data["res"]

        texts = data.get("rec_texts", [])
        scores = data.get("rec_scores", [])
        polygons = data.get("rec_polys", [])

        for index, text in enumerate(texts):
            score = (
                float(scores[index])
                if index < len(scores)
                else None
            )

            polygon = (
                polygons[index].tolist()
                if index < len(polygons)
                and hasattr(polygons[index], "tolist")
                else (
                    polygons[index]
                    if index < len(polygons)
                    else None
                )
            )

            lines.append({
                "line_id": f"P{page_number:03d}_L{len(lines)+1:03d}",
                "text": text,
                "confidence": score,
                "polygon": polygon,
            })

    # 페이지별 TXT 저장
    full_text = "\n".join(line["text"] for line in lines)

    txt_path = OUTPUT_DIR / f"page_{page_number:03d}.txt"
    txt_path.write_text(full_text, encoding="utf-8")

    print(
        f"[{page_number}페이지] 완료 | "
        f"{len(lines)}줄 | {elapsed:.2f}초",
        flush=True
    )

    return {
        "page": page_number,
        "status": "completed",
        "image_path": str(processed_path),
        "processing_time_seconds": round(elapsed, 2),
        "lines": lines,
        "full_text": full_text,
    }


def main():
    import argparse
    import hashlib
    from importlib.metadata import version
    global OUTPUT_DIR
    parser = argparse.ArgumentParser(description="OCR selected pages into a new output folder")
    parser.add_argument('--pages', type=int, nargs='+', help='1-based page numbers')
    parser.add_argument('--retry-from', type=Path, help='Retry failed pages from prior result JSON')
    parser.add_argument('--output', type=Path, required=True, help='New folder; existing OCR is never overwritten')
    args = parser.parse_args()
    selected = args.pages
    if args.retry_from:
        if selected: parser.error('Choose --pages or --retry-from')
        previous = json.loads(args.retry_from.read_text())
        selected = [p['page'] for p in previous['pages'] if p['status'] != 'completed']
        if not selected:
            print('No failed pages to retry'); return
    with fitz.open(PDF_PATH) as document:
        selected = selected or list(range(1,len(document)+1))
        if any(p < 1 or p > len(document) for p in selected) or len(set(selected)) != len(selected):
            parser.error('Invalid or duplicate page numbers')
    OUTPUT_DIR = args.output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=False)
    metadata = {'status':'executed','pdf_sha256':hashlib.sha256(PDF_PATH.read_bytes()).hexdigest(),
        'render_scale':2,'contrast':1.5,'selected_pages':selected,
        'versions':{p:version(p) for p in ['paddleocr','paddlepaddle','PyMuPDF','Pillow']}}
    if not PDF_PATH.is_file():
        print(f"PDF 파일을 찾을 수 없습니다: {PDF_PATH}")
        return

    print("PaddleOCR 모델 초기화 중...", flush=True)
    ocr = create_ocr()

    pages = []

    with fitz.open(str(PDF_PATH)) as pdf:
        print(f"PDF 전체 페이지 수: {len(pdf)}", flush=True)

        for index in [p-1 for p in selected]:
            try:
                result = process_page(pdf[index], index + 1, ocr)
                pages.append(result)

            except Exception as error:
                page_number = index + 1

                print(
                    f"[{page_number}페이지] OCR 실패: {error}",
                    flush=True
                )

                pages.append({
                    "page": page_number,
                    "status": "failed",
                    "error": str(error),
                    "lines": [],
                    "full_text": "",
                })

    # 전체 OCR 결과 JSON 저장
    output_path = OUTPUT_DIR / "ocr_pages_result.json"

    output_path.write_text(
        json.dumps({
            "document_id": "standard_contract_test",
            "metadata": dict(metadata, resolved_pipeline_config=ocr._merged_paddlex_config),
            "pages": pages,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("\n===== 전체 OCR 완료 =====")
    print(f"결과 폴더: {OUTPUT_DIR}")
    print(f"통합 JSON: {output_path}")


if __name__ == "__main__":
    main()
