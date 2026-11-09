"""OCR 모델 대역으로 기존 작업 프로세스의 처리 흐름을 검증한다."""

import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from integrations.ocr_worker import run


class OCRWorkerFlowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.paths = []

        for number in (1, 2):
            path = Path(self.folder.name) / f"page_{number}.png"

            with Image.new(
                "RGB", (240, 80), (120, 120, 120)
            ) as image:
                image.paste(
                    (136, 136, 136),
                    (120, 0, 240, 80),
                )
                image.save(path)

            self.paths.append(str(path))

    def _prediction(self, text):
        return {
            "rec_texts": [text],
            "rec_scores": [0.98],
            "rec_polys": np.array(
                [[[10, 10], [230, 10], [230, 30], [10, 30]]],
                dtype=np.int32,
            ),
        }

    def _run_with_mock(self, texts):
        model = Mock()
        model.predict.side_effect = [
            [self._prediction(text)]
            for text in texts
        ]
        create_model = Mock(return_value=model)

        # 실제 PaddleOCR 모듈 대신 테스트용 생성 함수를 제공한다.
        fake_module = ModuleType("scripts.ocr_pages")
        fake_module.create_ocr = create_model

        request = {
            "document_id": "B2-MOCK-001",
            "images": self.paths[:len(texts)],
        }

        with patch.dict(
            sys.modules,
            {"scripts.ocr_pages": fake_module},
        ):
            result = run(request)

        return result, model, create_model

    def test_two_pages_are_processed_in_input_order(self):
        texts = [
            "제1조(수리비) 임차인은 모든 수리비를 부담한다.",
            "제2조(보증금) 임대인은 계약 종료 시 보증금을 반환한다.",
        ]

        result, model, create_model = self._run_with_mock(texts)

        self.assertEqual(result["document_id"], "B2-MOCK-001")
        self.assertEqual(
            [page["page"] for page in result["ocr_pages"]],
            [1, 2],
        )

        for number, page in enumerate(result["ocr_pages"], start=1):
            self.assertEqual(page["status"], "completed")
            self.assertEqual(len(page["lines"]), 1)
            self.assertEqual(
                page["lines"][0]["text"], texts[number - 1]
            )
            self.assertEqual(
                page["lines"][0]["line_id"],
                f"P{number:03}_L001",
            )

        self.assertEqual(len(result["clauses"]), 2)
        self.assertEqual(model.predict.call_count, 2)
        create_model.assert_called_once_with()

    def test_model_receives_contrast_processed_rgb_array(self):
        texts = [
            "제1조(수리비) 임차인은 모든 수리비를 부담한다."
        ]

        _, model, _ = self._run_with_mock(texts)

        pixels = model.predict.call_args.args[0]

        self.assertIsInstance(pixels, np.ndarray)
        self.assertEqual(pixels.shape, (80, 240, 3))
        self.assertEqual(pixels.dtype, np.dtype("uint8"))
        self.assertEqual(pixels[10, 10].tolist(), [116, 116, 116])
        self.assertEqual(pixels[10, 200].tolist(), [140, 140, 140])

    def test_extracted_clauses_still_require_user_review(self):
        texts = [
            "제1조(수리비) 임차인은 모든 수리비를 부담한다."
        ]

        result, _, _ = self._run_with_mock(texts)

        self.assertFalse(result["analysis_ready"])
        self.assertTrue(result["clauses"])

        for clause in result["clauses"]:
            self.assertTrue(clause["needs_review"])
            self.assertIsNone(clause["verified_text"])


if __name__ == "__main__":
    unittest.main()