"""표준계약서 테스트 이미지용 OCR 작업 프로세스 진단."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from integrations.adapter import OCRProcess


def main():
    image_path = Path(sys.argv[1]).resolve()
    if not image_path.is_file():
        raise FileNotFoundError(image_path)

    worker = OCRProcess()

    with tempfile.TemporaryDirectory(
        prefix="safecontract_debug_"
    ) as folder:
        folder = Path(folder)
        image = folder / "page_1.png"
        request = folder / "request.json"
        output = folder / "response.json"

        shutil.copyfile(image_path, image)
        request.write_text(
            json.dumps({
                "document_id": "standard_contract_debug",
                "images": [str(image)],
            }),
            encoding="utf-8",
        )

        print("OCR 작업 프로세스 진단 중...", flush=True)

        completed = subprocess.run(
            [
                str(worker.python),
                "-u",
                "-X",
                "faulthandler",
                str(worker.worker),
                str(request),
                str(output),
            ],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            env=dict(
                os.environ,
                PYTHONDONTWRITEBYTECODE="1",
                PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True",
            ),
        )

        print("종료 코드:", completed.returncode)
        print(
            "종료 코드(16진수):",
            f"0x{completed.returncode & 0xFFFFFFFF:08X}",
        )
        print("결과 파일 존재:", output.is_file())

        if output.is_file():
            print("결과 파일 크기:", output.stat().st_size)
            data = json.loads(output.read_text(encoding="utf-8"))
            print("오류 정보:", data.get("error"))
            print("조항 개수:", len(data.get("clauses", [])))

        print("\n[작업 프로세스 출력]")
        print(completed.stdout[-2000:])
        print("\n[오류 출력]")
        print(completed.stderr)

    print("진단용 임시 폴더 정리 완료")



if __name__ == "__main__":
    main()