"""서버 환경에서 별도 OCR 프로세스 실행 확인."""

import subprocess
import tempfile
from pathlib import Path

from integrations.adapter import OCRProcess, ocr_response


IMAGE_SCRIPT = """
import os
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

font_path = Path(os.environ["WINDIR"]) / "Fonts" / "malgun.ttf"
font = ImageFont.truetype(str(font_path), 36)

sentences = [
    "제1조(수리비) 임차인은 모든 수리비를 부담한다.",
    "제2조(보증금) 임대인은 계약 종료 시 보증금을 반환한다.",
    "제3조(계약해지) 계약 해지 조건은 별도 협의한다.",
]

with Image.new("RGB", (1400, 400), "white") as image:
    draw = ImageDraw.Draw(image)
    for index, sentence in enumerate(sentences):
        draw.text(
            (50, 50 + index * 100),
            sentence,
            font=font,
            fill="black",
        )
    image.save(sys.argv[1])
"""


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path)
    args = parser.parse_args()

    process = OCRProcess(timeout=900)

    def run_ocr(image_path):
        if not image_path.is_file():
            raise FileNotFoundError(
                f"이미지를 찾을 수 없습니다: {image_path}"
            )

        if image_path.suffix.lower() != ".png":
            raise ValueError("이 테스트에는 PNG 파일을 사용하세요.")

        print(f"입력 이미지: {image_path}", flush=True)
        print("별도 OCR 프로세스 실행 중...", flush=True)

        structured = process([
            (
                image_path.name,
                "image/png",
                image_path.read_bytes(),
            )
        ])

        response = ocr_response(structured)

        print(f"\n추출된 조항: {len(response.clauses)}개")
        for clause in response.clauses:
            print(
                f"\n{clause.clause_id} / {clause.page}쪽\n"
                f"{clause.text}"
            )

        print("\nOCR 실행 및 응답 스키마 검증 성공")

    if args.image is not None:
        run_ocr(args.image.resolve())
    else:
        # 이미지 경로를 지정하지 않으면 기존 합성 테스트 실행
        with tempfile.TemporaryDirectory(
            prefix="safecontract_process_test_"
        ) as folder:
            image_path = Path(folder) / "synthetic_contract.png"

            subprocess.run(
                [
                    str(process.python),
                    "-c",
                    IMAGE_SCRIPT,
                    str(image_path),
                ],
                check=True,
                timeout=60,
            )

            run_ocr(image_path)

        print("테스트 이미지 임시 폴더 정리 완료")


if __name__ == "__main__":
    main()