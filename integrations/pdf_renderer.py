
"""검증된 PDF의 페이지를 OCR용 RGB 이미지로 변환한다."""

import math

import fitz
from PIL import Image

from integrations.pdf_input import PDFInputError, validate_pdf_upload


RENDER_DPI = 150
MAX_PAGE_PIXELS = 5_000_000


def render_pdf_page(name, mime, data, page_number):
    """PDF의 지정된 페이지를 메모리에서 RGB 이미지로 변환한다."""

    metadata = validate_pdf_upload(name, mime, data)

    if type(page_number) is not int:
        raise PDFInputError("PDF_PAGE_INVALID")

    if not 1 <= page_number <= metadata["page_count"]:
        raise PDFInputError("PDF_PAGE_INVALID")

    with fitz.open(stream=data, filetype="pdf") as document:
        page = document.load_page(page_number - 1)

        scale = RENDER_DPI / 72
        width = math.ceil(page.rect.width * scale)
        height = math.ceil(page.rect.height * scale)

        # 큰 페이지를 이미지로 만들기 전에 예상 픽셀 수를 검사한다.
        if width <= 0 or height <= 0:
            raise PDFInputError("PDF_PAGE_SIZE_INVALID")

        if width * height > MAX_PAGE_PIXELS:
            raise PDFInputError("PDF_RENDER_PIXEL_LIMIT")

        try:
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                colorspace=fitz.csRGB,
                alpha=False,
            )
            if pixmap.width * pixmap.height > MAX_PAGE_PIXELS:
                raise PDFInputError("PDF_RENDER_PIXEL_LIMIT")

            image = Image.frombytes(
                "RGB",
                (pixmap.width, pixmap.height),
                pixmap.samples,
            )
        except PDFInputError:
            raise
        except Exception:
            # PDF 내부 정보나 원문을 오류 메시지로 노출하지 않는다.
            raise PDFInputError("PDF_RENDER_FAILED") from None

    return image



MAX_TOTAL_PIXELS = 20_000_000



def render_pdf_pages(name, mime, data):
    """전체 페이지의 예상 픽셀 수를 검사한 후 순서대로 렌더링한다."""

    metadata = validate_pdf_upload(name, mime, data)
    scale = RENDER_DPI / 72
    total_pixels = 0

    # 렌더링 전에 모든 페이지의 예상 픽셀 수를 확인한다.
    with fitz.open(stream=data, filetype="pdf") as document:
        for page_number in metadata["page_numbers"]:
            page = document.load_page(page_number - 1)

            width = math.ceil(page.rect.width * scale)
            height = math.ceil(page.rect.height * scale)

            if width <= 0 or height <= 0:
                raise PDFInputError("PDF_PAGE_SIZE_INVALID")

            pixels = width * height

            if pixels > MAX_PAGE_PIXELS:
                raise PDFInputError("PDF_RENDER_PIXEL_LIMIT")

            total_pixels += pixels

            if total_pixels > MAX_TOTAL_PIXELS:
                raise PDFInputError("PDF_TOTAL_PIXEL_LIMIT")

    # 모든 페이지가 제한을 통과한 경우에만 이미지를 생성한다.
    images = []

    for page_number in metadata["page_numbers"]:
        image = render_pdf_page(name, mime, data, page_number)
        images.append(image)

    return images
