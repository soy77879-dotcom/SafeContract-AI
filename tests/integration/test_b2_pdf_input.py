import hashlib
import unittest

import fitz

from integrations.pdf_input import (
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    PDFInputError,
    validate_pdf_upload,
)


def make_pdf(page_count=2, password=False):
    with fitz.open() as document:
        for _ in range(page_count):
            document.new_page(width=595, height=842)

        if password:
            return document.tobytes(
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw="mock-owner",
                user_pw="mock-user",
            )

        return document.tobytes()


class PDFInputTests(unittest.TestCase):
    def test_valid_pdf_returns_page_information(self):
        data = make_pdf()

        result = validate_pdf_upload(
            "contract.pdf", "application/pdf", data
        )

        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result["page_numbers"], [1, 2])
        self.assertEqual(
            result["source_sha256"],
            hashlib.sha256(data).hexdigest(),
        )

    def test_wrong_extension_is_rejected(self):
        with self.assertRaisesRegex(
            PDFInputError, "PDF_EXTENSION_INVALID"
        ):
            validate_pdf_upload(
                "contract.png", "application/pdf", make_pdf()
            )

    def test_wrong_mime_is_rejected(self):
        with self.assertRaisesRegex(
            PDFInputError, "PDF_MIME_INVALID"
        ):
            validate_pdf_upload(
                "contract.pdf", "image/png", make_pdf()
            )

    def test_empty_file_is_rejected(self):
        with self.assertRaisesRegex(
            PDFInputError, "PDF_EMPTY"
        ):
            validate_pdf_upload(
                "contract.pdf", "application/pdf", b""
            )

    def test_fake_pdf_signature_is_rejected(self):
        with self.assertRaisesRegex(
            PDFInputError, "PDF_SIGNATURE_INVALID"
        ):
            validate_pdf_upload(
                "contract.pdf",
                "application/pdf",
                b"not-a-pdf",
            )

    def test_unreadable_pdf_is_rejected(self):
        with self.assertRaisesRegex(
            PDFInputError, "PDF_UNREADABLE"
        ):
            validate_pdf_upload(
                "contract.pdf",
                "application/pdf",
                b"%PDF-1.7\nbroken",
            )

    def test_oversized_pdf_is_rejected(self):
        data = b"%PDF-" + b"0" * MAX_PDF_BYTES

        with self.assertRaisesRegex(
            PDFInputError, "PDF_TOO_LARGE"
        ):
            validate_pdf_upload(
                "contract.pdf", "application/pdf", data
            )

    def test_too_many_pages_are_rejected(self):
        data = make_pdf(MAX_PDF_PAGES + 1)

        with self.assertRaisesRegex(
            PDFInputError, "PDF_PAGE_LIMIT"
        ):
            validate_pdf_upload(
                "contract.pdf", "application/pdf", data
            )

    def test_password_required_pdf_is_rejected(self):
        data = make_pdf(password=True)

        with self.assertRaisesRegex(
            PDFInputError, "PDF_PASSWORD_REQUIRED"
        ):
            validate_pdf_upload(
                "contract.pdf", "application/pdf", data
            )


if __name__ == "__main__":
    unittest.main()