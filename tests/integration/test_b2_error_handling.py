
"""B-2 5번: 파일 입력 오류 및 예외 처리 검증."""

import os
import subprocess
import unittest
from io import BytesIO
from unittest.mock import patch, MagicMock

from PIL import Image

from integrations.adapter import AdapterError, validate_upload


def make_png():
    """개인정보가 없는 정상 PNG 데이터를 생성한다."""
    buffer = BytesIO()
    Image.new("RGB", (20, 20), "white").save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


class TestUploadErrors(unittest.TestCase):

    def assert_adapter_error(self, code, status, name, mime, data):
        """예상한 오류 코드와 HTTP 상태를 검사한다."""
        with self.assertRaises(AdapterError) as caught:
            validate_upload(name, mime, data)

        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.status, status)

    def test_valid_png(self):
        """정상 PNG 파일은 허용한다."""
        result = validate_upload(
            "contract.png", "image/png", make_png()
        )
        self.assertEqual(result, ".png")

    def test_unsupported_extension(self):
        """지원하지 않는 확장자를 거부한다."""
        self.assert_adapter_error(
            "UNSUPPORTED_FILE_TYPE", 415,
            "contract.txt", "text/plain", b"test"
        )

    def test_mime_mismatch(self):
        """확장자와 MIME 타입 불일치를 거부한다."""
        self.assert_adapter_error(
            "UNSUPPORTED_FILE_TYPE", 415,
            "contract.png", "image/jpeg", make_png()
        )

    def test_empty_file(self):
        """빈 파일은 거부한다."""
        self.assert_adapter_error(
            "VALIDATION_ERROR", 422,
            "contract.png", "image/png", b""
        )

    def test_oversized_file(self):
        """10MiB 초과 파일은 거부한다."""
        data = b"\x89PNG\r\n\x1a\n" + (
            b"0" * (10 * 1024 * 1024)
        )

        self.assert_adapter_error(
            "FILE_TOO_LARGE", 413,
            "contract.png", "image/png", data
        )

    def test_invalid_signature(self):
        """이미지 확장자와 실제 시그니처 불일치를 거부한다."""
        self.assert_adapter_error(
            "UNSUPPORTED_FILE_TYPE", 415,
            "contract.png", "image/png", b"not-an-image"
        )


class TestOCRResponseErrors(unittest.TestCase):
    """OCR 결과를 API 응답으로 변환할 때의 오류를 검증한다."""

    def test_empty_clauses(self):
        """조항이 하나도 없으면 OCR 처리 오류로 거부한다."""
        from integrations.adapter import ocr_response

        structured = {
            "document_id": "test-document",
            "clauses": [],
        }

        with self.assertRaises(AdapterError) as caught:
            ocr_response(structured)

        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(
            caught.exception.code,
            "OCR_PROCESSING_ERROR",
        )

    def test_invalid_clause_page(self):
        """페이지 번호가 1 미만이면 응답 스키마 검증에 실패한다."""
        from integrations.adapter import ocr_response
        from pydantic import ValidationError

        structured = {
            "document_id": "test-document",
            "clauses": [
                {
                    "clause_id": "C001",
                    "pages": [0],
                    "raw_text": "테스트 조항",
                }
            ],
        }

        with self.assertRaises(ValidationError):
            ocr_response(structured)

    def test_duplicate_clause_id(self):
        """중복 조항 ID는 응답 스키마에서 거부한다."""
        from integrations.adapter import ocr_response
        from pydantic import ValidationError

        structured = {
            "document_id": "test-document",
            "clauses": [
                {
                    "clause_id": "C001",
                    "pages": [1],
                    "raw_text": "첫 번째 조항",
                },
                {
                    "clause_id": "C001",
                    "pages": [1],
                    "raw_text": "두 번째 조항",
                },
            ],
        }

        with self.assertRaises(ValidationError):
            ocr_response(structured)


class TestOCRWorkerErrors(unittest.TestCase):
    """OCR Worker 실행 과정에서 발생하는 오류를 검증한다."""

    def setUp(self):
        from integrations.adapter import OCRProcess

        self.worker = OCRProcess()
        self.uploads = [
            ("contract.png", "image/png", make_png())
        ]

    def test_worker_unavailable(self):
        """Worker 프로세스를 시작할 수 없으면 503 오류를 반환한다."""
        with patch(
            "integrations.adapter.subprocess.Popen",
            side_effect=OSError("가상 실행 오류"),
        ):
            with self.assertRaises(AdapterError) as caught:
                self.worker(self.uploads)

        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(
            caught.exception.code,
            "OCR_UNAVAILABLE",
        )

    def test_worker_timeout(self):
        """Worker 실행 시간이 초과되면 504 오류를 반환한다."""
        process = MagicMock()
        process.pid = 12345
        process.wait.side_effect = [
            subprocess.TimeoutExpired(
                cmd="ocr_worker",
                timeout=1,
            ),
            0,
        ]

        with patch(
            "integrations.adapter.subprocess.Popen",
            return_value=process,
        ), patch(
            "integrations.adapter.os.killpg",
        ) as mock_killpg:
            with self.assertRaises(AdapterError) as caught:
                self.worker(self.uploads)

        self.assertEqual(caught.exception.status, 504)
        self.assertEqual(
            caught.exception.code,
            "OCR_TIMEOUT",
        )

        if os.name == "nt":
            process.kill.assert_called_once()
            mock_killpg.assert_not_called()
        else:
            mock_killpg.assert_called_once_with(
                process.pid,
                __import__("signal").SIGKILL,
            )

        self.assertEqual(process.wait.call_count, 2)

    def test_worker_output_missing(self):
        """Worker 결과 파일이 없으면 500 오류를 반환한다."""
        process = MagicMock()
        process.wait.return_value = 0

        with patch(
            "integrations.adapter.subprocess.Popen",
            return_value=process,
        ):
            with self.assertRaises(AdapterError) as caught:
                self.worker(self.uploads)

        self.assertEqual(caught.exception.status, 500)
        self.assertEqual(
            caught.exception.code,
            "OCR_PROCESSING_ERROR",
        )


if __name__ == "__main__":
    unittest.main()
