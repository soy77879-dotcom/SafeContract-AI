
"""B-2 6번: 개인정보 마스킹 및 외부 전송 보호 검증."""

import json
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from integrations.transfer_guard import TransferGate


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv-b2" / "Scripts" / "python.exe"
WORKER = ROOT / "integrations" / "mask_verify_worker.py"


def make_image(masked=True):
    """개인정보가 없는 합성 테스트 이미지를 만든다."""
    image = Image.new("RGB", (100, 100), "white")

    if masked:
        for x in range(10, 50):
            for y in range(10, 30):
                image.putpixel((x, y), (0, 0, 0))

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class TestMaskVerification(unittest.TestCase):
    """실제 마스킹 픽셀 검증 Worker를 테스트한다."""

    def run_worker(self, image_bytes, regions):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            image_path = folder / "input.png"
            regions_path = folder / "regions.json"
            output_path = folder / "output.png"

            image_path.write_bytes(image_bytes)
            regions_path.write_text(json.dumps(regions), encoding="utf-8")

            result = subprocess.run(
                [
                    str(PYTHON),
                    str(WORKER),
                    str(image_path),
                    str(regions_path),
                    str(output_path),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )

            output = (
                output_path.read_bytes()
                if output_path.exists()
                else None
            )

            return result.returncode, output

    def test_black_mask_passes(self):
        """검정색으로 가린 영역은 검증을 통과한다."""
        regions = [
            {"x": 10, "y": 10, "width": 40, "height": 20}
        ]

        code, output = self.run_worker(make_image(True), regions)

        self.assertEqual(code, 0)
        self.assertIsNotNone(output)

        with Image.open(BytesIO(output)) as image:
            self.assertEqual(
                image.crop((10, 10, 50, 30)).getextrema(),
                ((0, 0), (0, 0), (0, 0)),
            )

    def test_unmasked_region_rejected(self):
        """마스킹되지 않은 영역은 거부한다."""
        regions = [
            {"x": 10, "y": 10, "width": 40, "height": 20}
        ]

        code, output = self.run_worker(make_image(False), regions)

        self.assertNotEqual(code, 0)
        self.assertIsNone(output)

    def test_invalid_region_rejected(self):
        """이미지 밖의 잘못된 영역은 거부한다."""
        regions = [
            {"x": 90, "y": 90, "width": 30, "height": 30}
        ]

        code, output = self.run_worker(make_image(True), regions)

        self.assertNotEqual(code, 0)
        self.assertIsNone(output)


class TestTransferGuard(unittest.TestCase):
    """서버의 외부 전송 승인 및 차단 정책을 검증한다."""

    def setUp(self):
        self.image = make_image(True)
        self.text = "보증금 반환 조건 확인"

        def processor(source):
            return {
                "masked_image": self.image,
                "ocr_lines": [
                    {"text": self.text, "confidence": 1.0}
                ],
            }

        self.gate = TransferGate(processor=processor)

    def prepare_receipt(self):
        """서버에서 검증 가능한 승인 준비 기록을 생성한다."""
        receipt = self.gate.prepare(
            owner="test-user",
            document="test-document",
            revision=1,
            source=b"original-document",
        )
        self.assertIsNotNone(receipt)
        return receipt

    def test_without_approval_rejected(self):
        """승인 기록 없이 전송하면 차단한다."""
        result = self.gate.dispatch_mock(
            "test-user", "invalid-receipt",
            self.image, 1, self.text,
        )

        self.assertFalse(result["allowed"])
        self.assertFalse(result["external_llm_called"])

    def test_before_review_rejected(self):
        """사용자 검토 전에 전송하면 차단한다."""
        receipt = self.prepare_receipt()

        result = self.gate.dispatch_mock(
            "test-user", receipt["receipt_id"],
            self.image, 1, self.text,
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "unreviewed")
        self.assertFalse(result["external_llm_called"])

    def test_approved_mock_dispatch(self):
        """검토 완료된 요청도 실제 외부 LLM을 호출하지 않는다."""
        receipt = self.prepare_receipt()

        reviewed = self.gate.confirm_review(
            "test-user",
            receipt["receipt_id"],
            receipt["image_sha256"],
            receipt["text_sha256"],
        )
        self.assertTrue(reviewed)

        result = self.gate.dispatch_mock(
            "test-user", receipt["receipt_id"],
            self.image, 1, self.text,
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["mode"], "mock")
        self.assertFalse(result["external_llm_called"])

    def test_receipt_reuse_rejected(self):
        """이미 사용한 승인 기록을 재사용할 수 없다."""
        receipt = self.prepare_receipt()

        self.gate.confirm_review(
            "test-user",
            receipt["receipt_id"],
            receipt["image_sha256"],
            receipt["text_sha256"],
        )

        first = self.gate.dispatch_mock(
            "test-user", receipt["receipt_id"],
            self.image, 1, self.text,
        )

        second = self.gate.dispatch_mock(
            "test-user", receipt["receipt_id"],
            self.image, 1, self.text,
        )

        self.assertTrue(first["allowed"])
        self.assertFalse(second["allowed"])
        self.assertFalse(second["external_llm_called"])


class TestPrivacyExposure(unittest.TestCase):
    """오류 응답 및 로그의 민감정보 노출 여부를 검증한다."""

    def test_worker_error_does_not_expose_internal_message(self):
        """Worker 실행 오류가 내부 문자열을 노출하지 않는다."""
        from unittest.mock import patch
        from integrations.adapter import AdapterError, OCRProcess

        secret = "FAKE_PRIVATE_ID_123456"
        worker = OCRProcess()

        with patch(
            "integrations.adapter.subprocess.Popen",
            side_effect=OSError(secret),
        ):
            with self.assertRaises(AdapterError) as caught:
                worker([("masked-contract.png", "image/png", make_image(True))])

        self.assertNotIn(secret, caught.exception.message)
        self.assertEqual(caught.exception.code, "OCR_UNAVAILABLE")

    def test_unregistered_image_does_not_reach_ocr(self):
        """마스킹 등록 없이 OCR Worker가 호출되지 않는다."""
        from fastapi.testclient import TestClient
        from integrations.review_app import create_app

        calls = []

        def fake_ocr(uploads):
            calls.append(uploads)
            raise AssertionError("OCR Worker must not run")

        app = create_app(ocr=fake_ocr)

        with TestClient(
            app,
            base_url="http://localhost",
            client=("127.0.0.1", 50000),
        ) as client:
            session = client.get("/api/session")
            response = client.post(
                "/api/ocr",
                headers={
                    "origin": "http://localhost",
                    "x-review-csrf": session.json()["csrf_token"],
                },
                files={
                    "files": (
                        "masked-contract.png",
                        make_image(True),
                        "image/png",
                    )
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"]["code"],
            "PRIVACY_CHECK_FAILED",
        )
        self.assertEqual(calls, [])

    def test_blocked_transfer_does_not_expose_text(self):
        """차단된 외부 전송 응답에 OCR 원문이 포함되지 않는다."""
        secret = "FAKE_PRIVATE_ID_123456"
        gate = TransferGate()

        result = gate.dispatch_mock(
            "test-user",
            "invalid-receipt",
            make_image(True),
            1,
            secret,
        )

        self.assertFalse(result["allowed"])
        self.assertNotIn(secret, json.dumps(result))

    def test_error_response_does_not_expose_private_input(self):
        """API 오류 응답에 가상 민감정보가 노출되지 않는다."""
        from fastapi.testclient import TestClient
        from integrations.review_app import create_app

        secret = "FAKE_PRIVATE_ID_123456"
        app = create_app()

        with TestClient(
            app,
            base_url="http://localhost",
            client=("127.0.0.1", 50000),
        ) as client:
            session = client.get("/api/session")
            response = client.post(
                "/api/analyze",
                headers={
                    "origin": "http://localhost",
                    "x-review-csrf": session.json()["csrf_token"],
                },
                json={
                    "document_id": "test-document",
                    "clauses": [
                        {
                            "clause_id": "C001",
                            "page": 1,
                            "text": secret,
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(secret, response.text)


if __name__ == "__main__":
    unittest.main()
