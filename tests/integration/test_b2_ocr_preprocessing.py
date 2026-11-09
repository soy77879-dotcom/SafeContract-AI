"""합성 이미지로 기존 이미지 로딩·전처리를 검증한다."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from integrations.ocr_worker import load_images
from scripts.ocr_experiments import preprocess


class OCRPreprocessingTests(unittest.TestCase):
    def _load(self, paths):
        images = load_images([str(path) for path in paths])
        for image in images:
            self.addCleanup(image.close)
        return images

    def test_grayscale_png_becomes_rgb_without_changing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "grayscale.png"

            with Image.new("L", (3, 2), 127) as image:
                image.save(path)

            original_bytes = path.read_bytes()
            images = self._load([path])

            self.assertEqual(len(images), 1)
            self.assertEqual(images[0].mode, "RGB")
            self.assertEqual(images[0].size, (3, 2))
            self.assertEqual(
                images[0].getpixel((0, 0)), (127, 127, 127)
            )

            pixels = np.asarray(images[0])
            self.assertEqual(pixels.shape, (2, 3, 3))
            self.assertEqual(pixels.dtype, np.dtype("uint8"))
            self.assertEqual(path.read_bytes(), original_bytes)

    def test_input_image_order_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "first.png"
            second = Path(folder) / "second.png"

            with Image.new("RGB", (2, 3), (20, 20, 20)) as image:
                image.save(first)

            with Image.new("RGB", (4, 2), (220, 220, 220)) as image:
                image.save(second)

            # 파일 이름 순서가 아닌 전달한 순서를 따라야 한다.
            images = self._load([second, first])

            self.assertEqual(
                [image.size for image in images],
                [(4, 2), (2, 3)],
            )
            self.assertEqual(
                images[0].getpixel((0, 0)), (220, 220, 220)
            )
            self.assertEqual(
                images[1].getpixel((0, 0)), (20, 20, 20)
            )

    def test_contrast_changes_pixels_as_expected(self):
        with Image.new("RGB", (2, 1)) as original:
            original.putpixel((0, 0), (120, 120, 120))
            original.putpixel((1, 0), (136, 136, 136))

            processed = preprocess(original, "contrast_1.5")
            self.addCleanup(processed.close)

            self.assertEqual(processed.mode, "RGB")
            self.assertEqual(processed.size, original.size)
            self.assertEqual(
                processed.getpixel((0, 0)), (116, 116, 116)
            )
            self.assertEqual(
                processed.getpixel((1, 0)), (140, 140, 140)
            )

    def test_preprocessing_does_not_change_original(self):
        with Image.new("RGB", (2, 1)) as original:
            original.putpixel((0, 0), (120, 120, 120))
            original.putpixel((1, 0), (136, 136, 136))
            before = original.tobytes()

            processed = preprocess(original, "contrast_1.5")
            self.addCleanup(processed.close)

            self.assertIsNot(processed, original)
            self.assertEqual(original.tobytes(), before)

            processed.putpixel((0, 0), (0, 0, 0))
            self.assertEqual(original.tobytes(), before)


if __name__ == "__main__":
    unittest.main()