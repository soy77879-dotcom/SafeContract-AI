
"""PDF 페이지 렌더링 단위 테스트."""

import unittest

import fitz

from unittest.mock import patch
from integrations.pdf_input import PDFInputError
from integrations.pdf_renderer import (
    render_pdf_page,
    render_pdf_pages,
)


class TestPDFRenderer(unittest.TestCase):
    """PDF 렌더링 결과와 입력 제한을 검사한다."""

    @staticmethod
    def make_pdf(page_count=2):
        """개인정보가 없는 합성 PDF를 생성한다."""
        document = fitz.open()

        try:
            for number in range(1, page_count + 1):
                page = document.new_page(width=300, height=400)
                page.insert_text(
                    (30, 40),
                    f"Test page {number}",
                )

            return document.tobytes()
        finally:
            document.close()

    def test_first_page_rgb_image(self):
        """첫 번째 페이지를 RGB 이미지로 변환한다."""
        pdf_data = self.make_pdf()

        image = render_pdf_page(
            "sample.pdf",
            "application/pdf",
            pdf_data,
            1,
        )

        self.assertEqual(image.mode, "RGB")
        self.assertGreater(image.width, 0)
        self.assertGreater(image.height, 0)

    def test_second_page_is_different(self):
        """서로 다른 PDF 페이지는 다른 이미지를 생성한다."""
        pdf_data = self.make_pdf()

        first = render_pdf_page(
            "sample.pdf", "application/pdf", pdf_data, 1
        )
        second = render_pdf_page(
            "sample.pdf", "application/pdf", pdf_data, 2
        )

        self.assertNotEqual(first.tobytes(), second.tobytes())

    def test_page_number_out_of_range(self):
        """존재하지 않는 페이지 번호를 거부한다."""
        pdf_data = self.make_pdf()

        with self.assertRaises(PDFInputError) as context:
            render_pdf_page(
                "sample.pdf", "application/pdf", pdf_data, 3
            )

        self.assertEqual(context.exception.code, "PDF_PAGE_INVALID")

    def test_original_pdf_is_unchanged(self):
        """렌더링 후에도 원본 PDF 바이트가 유지된다."""
        pdf_data = self.make_pdf()
        original = bytes(pdf_data)

        render_pdf_page(
            "sample.pdf", "application/pdf", pdf_data, 1
        )

        self.assertEqual(pdf_data, original)


    def test_oversized_page_is_rejected(self):
        """허용 픽셀 수를 초과하는 페이지를 렌더링 전에 거부한다."""
        document = fitz.open()

        try:
            # 150 DPI에서 500만 픽셀을 초과하는 큰 페이지를 만든다.
            document.new_page(width=2000, height=2000)
            pdf_data = document.tobytes()
        finally:
            document.close()

        with self.assertRaises(PDFInputError) as context:
            render_pdf_page(
                "sample.pdf",
                "application/pdf",
                pdf_data,
                1,
            )

        self.assertEqual(
            context.exception.code,
            "PDF_RENDER_PIXEL_LIMIT",
        )


    def test_render_three_pages_in_order(self):
        """PDF 세 페이지를 순서대로 RGB 이미지로 변환한다."""
        pdf_data = self.make_pdf(page_count=3)

        images = render_pdf_pages(
            "sample.pdf",
            "application/pdf",
            pdf_data,
        )

        self.assertEqual(len(images), 3)
        self.assertTrue(all(image.mode == "RGB" for image in images))
        self.assertNotEqual(images[0].tobytes(), images[1].tobytes())
        self.assertNotEqual(images[1].tobytes(), images[2].tobytes())

    def test_total_pixel_limit_is_enforced(self):
        """전체 페이지 픽셀 합계가 제한을 초과하면 거부한다."""
        pdf_data = self.make_pdf(page_count=3)

        with unittest.mock.patch(
            "integrations.pdf_renderer.MAX_TOTAL_PIXELS",
            1_000_000,
        ):
            with self.assertRaises(PDFInputError) as context:
                render_pdf_pages(
                    "sample.pdf",
                    "application/pdf",
                    pdf_data,
                )

        self.assertEqual(
            context.exception.code,
            "PDF_TOTAL_PIXEL_LIMIT",
        )


if __name__ == "__main__":
    unittest.main()
