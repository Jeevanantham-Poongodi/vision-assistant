from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from ai import ocr


class FakeImage:
    def __init__(self, shape: tuple[int, int, int] = (100, 300, 3)) -> None:
        self.shape = shape


class FakeCv2(ModuleType):
    COLOR_BGR2GRAY = 1
    INTER_CUBIC = 2
    ADAPTIVE_THRESH_GAUSSIAN_C = 3
    THRESH_BINARY = 4

    def __init__(self) -> None:
        super().__init__("cv2")
        self.resize_calls: list[dict[str, Any]] = []

    def cvtColor(self, image: object, code: int) -> FakeImage:
        return FakeImage()

    def resize(
        self,
        image: FakeImage,
        destination: object,
        *,
        fx: float,
        fy: float,
        interpolation: int,
    ) -> FakeImage:
        self.resize_calls.append(
            {"fx": fx, "fy": fy, "interpolation": interpolation}
        )
        return FakeImage((300, 900, 1))

    def GaussianBlur(
        self, image: FakeImage, kernel: tuple[int, int], sigma: int
    ) -> FakeImage:
        return image

    def adaptiveThreshold(
        self,
        image: FakeImage,
        max_value: int,
        adaptive_method: int,
        threshold_type: int,
        block_size: int,
        constant: int,
    ) -> FakeImage:
        return image


def sample_tesseract_data() -> dict[str, list[object]]:
    return {
        "text": ["  WELCOME ", "CENTER", "", "OPEN", "noise"],
        "conf": ["92.0", "88", "-1", "76", "-1"],
        "left": ["10", "75", "0", "12", "0"],
        "top": ["20", "20", "0", "70", "0"],
        "width": ["60", "50", "0", "35", "0"],
        "height": ["15", "15", "0", "12", "0"],
        "block_num": ["1", "1", "1", "1", "2"],
        "par_num": ["1", "1", "1", "1", "1"],
        "line_num": ["1", "1", "1", "2", "1"],
    }


@pytest.fixture
def fake_ocr_modules(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeCv2, ModuleType]:
    cv2 = FakeCv2()
    pytesseract = ModuleType("pytesseract")
    pytesseract.Output = SimpleNamespace(DICT="dict")
    pytesseract.pytesseract = SimpleNamespace(tesseract_cmd="default")
    pytesseract.image_to_data = lambda image, **kwargs: sample_tesseract_data()
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setitem(sys.modules, "pytesseract", pytesseract)
    return cv2, pytesseract


def test_read_text_groups_words_into_lines_and_reports_bboxes(
    fake_ocr_modules: tuple[FakeCv2, ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, pytesseract = fake_ocr_modules
    monkeypatch.setenv("TESSERACT_CMD", r"C:\Tesseract\tesseract.exe")

    result = ocr.read_text(FakeImage())

    assert result["text"] == "WELCOME CENTER\nOPEN"
    assert result["lines"] == [
        {
            "text": "WELCOME CENTER",
            "confidence": 90.0,
            "bbox": {"x1": 3, "y1": 6, "x2": 42, "y2": 12},
        },
        {
            "text": "OPEN",
            "confidence": 76.0,
            "bbox": {"x1": 4, "y1": 23, "x2": 16, "y2": 28},
        },
    ]
    assert result["confidence"] == 83.0
    assert isinstance(result["latency_ms"], int)
    assert pytesseract.pytesseract.tesseract_cmd == r"C:\Tesseract\tesseract.exe"


def test_preprocessing_upscales_small_images(
    fake_ocr_modules: tuple[FakeCv2, ModuleType],
) -> None:
    cv2, _ = fake_ocr_modules

    result = ocr.read_text(FakeImage())

    assert cv2.resize_calls == [{"fx": 3.0, "fy": 3.0, "interpolation": 2}]
    assert result["text"].startswith("WELCOME CENTER")


def test_no_text_returns_empty_result(
    fake_ocr_modules: tuple[FakeCv2, ModuleType],
) -> None:
    _, pytesseract = fake_ocr_modules
    pytesseract.image_to_data = lambda image, **kwargs: {
        key: []
        for key in (
            "text",
            "conf",
            "left",
            "top",
            "width",
            "height",
            "block_num",
            "par_num",
            "line_num",
        )
    }

    result = ocr.read_text(FakeImage())

    assert result["text"] == ""
    assert result["lines"] == []
    assert result["confidence"] == 0.0


@pytest.mark.parametrize("image", [None, object()])
def test_invalid_image_returns_safe_empty_result(image: object) -> None:
    result = ocr.read_text(image)

    assert result["text"] == ""
    assert result["lines"] == []
    assert result["confidence"] == 0.0
    assert isinstance(result["latency_ms"], int)


def test_missing_tesseract_module_fails_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_import = ocr.importlib.import_module

    def import_without_tesseract(name: str) -> Any:
        if name == "pytesseract":
            raise ImportError("pytesseract missing")
        return original_import(name)

    monkeypatch.setattr(ocr.importlib, "import_module", import_without_tesseract)

    result = ocr.read_text(FakeImage())

    assert result["text"] == ""
    assert "OCR unavailable" in capsys.readouterr().err


def test_tesseract_runtime_failure_is_reported_and_safe(
    fake_ocr_modules: tuple[FakeCv2, ModuleType],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, pytesseract = fake_ocr_modules

    def fail_ocr(image: object, **kwargs: object) -> dict[str, list[object]]:
        raise RuntimeError("Tesseract binary missing")

    pytesseract.image_to_data = fail_ocr
    result = ocr.read_text(FakeImage())

    assert result["text"] == ""
    assert result["lines"] == []
    assert "Tesseract binary missing" in capsys.readouterr().err
