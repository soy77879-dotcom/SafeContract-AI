
"""B-2 FastAPI 입출력 및 OCR 연결 자동화 테스트."""

import json
import unittest
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from backend.schemas import OCRResponse
from integrations.review_app import create_app


def make_png():
    """개인정보가 없는 테스트 이미지를 생성한다."""
    buffer = BytesIO()
    Image.new("RGB", (100, 100), "white").save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


class FakeStore:
    """OCR 결과를 API 응답으로 반환하는 테스트용 저장소."""

    def register(self, owner, structured, image_hash, privacy):
        return {
            "document_id": structured["document_id"],
            "clauses": [
                {
                    "clause_id": "C001",
                    "page": 1,
                    "text": "Mock OCR clause",
                }
            ],
        }


class TestFastAPIIO(unittest.TestCase):

    def setUp(self):
        self.calls = []

        def fake_mask(data, boxes):
            return data

        def fake_privacy(data):
            return {"status": "no_candidates"}

        def fake_ocr(uploads):
            self.calls.append(uploads)
            return {"document_id": "mock-document"}

        self.app = create_app(
            ocr=fake_ocr,
            privacy=fake_privacy,
            masker=fake_mask,
            store=FakeStore(),
        )

        self.client = TestClient(
            self.app,
            base_url="http://localhost",
            client=("127.0.0.1", 50000),
        )
        self.client.__enter__()

        self.png = make_png()
        response = self.client.get("/api/session")
        self.assertEqual(response.status_code, 200)

        self.csrf = response.json()["csrf_token"]
        self.headers = {
            "origin": "http://localhost",
            "x-review-csrf": self.csrf,
        }

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_session_issued(self):
        """세션 쿠키와 CSRF 토큰이 정상 발급되는지 확인한다."""
        self.assertTrue(self.csrf)
        self.assertIn("sc_review", self.client.cookies)

    def test_missing_mask_ticket(self):
        """마스킹 티켓이 없으면 OCR 요청이 차단된다."""
        response = self.client.post(
            "/api/ocr",
            headers=self.headers,
            files={
                "files": (
                    "masked-contract.png",
                    self.png,
                    "image/png",
                )
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["error"]["code"],
            "PRIVACY_CHECK_FAILED",
        )
        self.assertEqual(len(self.calls), 0)

    def test_masking_to_ocr_response(self):
        """마스킹 등록 후 OCR 응답이 스키마에 맞는지 확인한다."""
        registration = self.client.post(
            "/api/masking/register",
            headers=self.headers,
            files={
                "files": (
                    "masked-contract.png",
                    self.png,
                    "image/png",
                )
            },
            data={"mask_regions": json.dumps([[]])},
        )

        self.assertEqual(registration.status_code, 200)

        ticket = registration.json()["mask_ticket"]

        response = self.client.post(
            "/api/ocr",
            headers={
                **self.headers,
                "x-mask-ticket": ticket,
            },
            files={
                "files": (
                    "masked-contract.png",
                    self.png,
                    "image/png",
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.calls), 1)

        result = OCRResponse.model_validate(response.json())

        self.assertEqual(result.document_id, "mock-document")
        self.assertEqual(len(result.clauses), 1)
        self.assertEqual(result.clauses[0].clause_id, "C001")


if __name__ == "__main__":
    unittest.main()
