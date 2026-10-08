"""Run OCR against sample sign or label images."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from ai.ocr import read_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "images",
        nargs="+",
        type=Path,
        help="Paths to sample sign or label images",
    )
    args = parser.parse_args()
    cv2 = importlib.import_module("cv2")
    failed = False

    for image_path in args.images:
        image = cv2.imread(str(image_path))
        if image is None:
            print(f"{image_path}: unable to read image")
            failed = True
            continue

        result = read_text(image)
        print(
            f"{image_path}: {result['confidence']:.2f}% "
            f"in {result['latency_ms']} ms"
        )
        print(result["text"] or "(no readable text)")
        for line in result["lines"]:
            print(
                f"  {line['confidence']:.2f}% {line['bbox']}: "
                f"{line['text']}"
            )
        if not result["text"]:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
