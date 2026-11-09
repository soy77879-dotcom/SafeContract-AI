
"""합성 PDF 페이지를 기존 OCR 어댑터 입력으로 변환한다.

개발·테스트 전용이다. 개인정보 마스킹과 사용자 승인 절차를
수행하지 않으므로 실제 계약서 업로드 API에 연결하지 않는다.
"""

from io import BytesIO

from integrations.pdf_renderer import render_pdf_pages


def pdf_to_ocr_uploads(name, mime, data):
    """검증된 PDF를 페이지 순서대로 PNG 업로드 목록으로 변환한다."""

    images = render_pdf_pages(name, mime, data)
    uploads = []

    for page_number, image in enumerate(images, start=1):
        buffer = BytesIO()
        image.save(buffer, format="PNG")

        uploads.append(
            (
                f"page_{page_number:03}.png",
                "image/png",
                buffer.getvalue(),
            )
        )

    return uploads
