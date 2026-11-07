"""Windows 로컬 환경에서 합성 이미지로 OCR 실행 확인."""

import json
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from scripts.ocr_pages import create_ocr

def main():
    sentences = [
        "임차인은 모든 수리비를 부담한다.",
        "임대인은 계약 종료 시 보증금을 반환한다.",
        "계약 해지 조건은 별도 협의한다.",
    ]

    font_path = Path(os.environ["WINDIR"]) / "Fonts" / "malgun.ttf"
    font = ImageFont.truetype(str(font_path), 36)

    print("OCR 모델 준비 중...", flush=True)
    ocr = create_ocr()

    # 테스트 이미지는 임시 폴더에 만들고 종료 시 삭제한다.
    with tempfile.TemporaryDirectory(prefix="safecontract_ocr_") as folder:
        image_path = Path(folder) / "synthetic_contract.png"

        with Image.new("RGB", (1400, 400), "white") as image:
            draw = ImageDraw.Draw(image)

            for index, sentence in enumerate(sentences):
                draw.text(
                    (50, 50 + index * 100),
                    sentence,
                    font=font,
                    fill="black",
                )

            image.save(image_path)

        print("합성 이미지 OCR 실행 중...", flush=True)
        texts = []

        for result in ocr.predict(str(image_path)):
            data = result.json
            if isinstance(data, str):
                data = json.loads(data)

            data = data.get("res", data)
            texts.extend(data.get("rec_texts", []))

        if not texts:
            raise RuntimeError("OCR에서 추출된 문장이 없습니다.")

        print("\n[원래 문장]")
        for sentence in sentences:
            print(sentence)

        print("\n[실제 OCR 추출 결과]")
        for text in texts:
            print(text)

    print("\n테스트 이미지 임시 폴더 정리 완료")


if __name__ == "__main__":
    main()