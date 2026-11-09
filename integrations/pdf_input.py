"""PDF 입력 검증. OCR이나 외부 전송은 수행하지 않는다."""

import hashlib
from pathlib import Path

import fitz


MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 5


class PDFInputError(ValueError):
    """나중에 API 경계에서 응답으로 변환할 내부 오류."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_pdf_upload(name, mime, data):
    """PDF 형식·용량·열기 가능 여부·페이지 수를 검사한다."""
    if not isinstance(name, str) or Path(name).suffix.lower() != ".pdf":
        raise PDFInputError("PDF_EXTENSION_INVALID")

    if mime not in (
        "application/pdf",
        "application/octet-stream",
        None,
        "",
    ):
        raise PDFInputError("PDF_MIME_INVALID")

    if not isinstance(data, bytes):
        raise PDFInputError("PDF_BYTES_REQUIRED")

    if not data:
        raise PDFInputError("PDF_EMPTY")

    if len(data) > MAX_PDF_BYTES:
        raise PDFInputError("PDF_TOO_LARGE")

    if not data.startswith(b"%PDF-"):
        raise PDFInputError("PDF_SIGNATURE_INVALID")

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception:
        # 파서 오류에 포함될 수 있는 원문·내부 정보를 노출하지 않는다.
        raise PDFInputError("PDF_UNREADABLE") from None

    with document:
        if document.needs_pass:
            raise PDFInputError("PDF_PASSWORD_REQUIRED")

        page_count = document.page_count

        if not 1 <= page_count <= MAX_PDF_PAGES:
            raise PDFInputError("PDF_PAGE_LIMIT")

    return {
        "page_count": page_count,
        "page_numbers": list(range(1, page_count + 1)),
        "source_sha256": hashlib.sha256(data).hexdigest(),
    }