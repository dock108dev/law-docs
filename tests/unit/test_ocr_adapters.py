import contextlib, sys
from types import SimpleNamespace as NS
from unittest.mock import Mock
import numpy as np
import pytest
from PIL import Image
import local_vision as v
import pdf_only
from source_paths import source_path, ROOT


def test_tesseract(monkeypatch):
    import pytesseract

    monkeypatch.setattr(v, "BACKEND", "tesseract")
    d = {
        "text": ["", "A", "B"],
        "block_num": [1] * 3,
        "par_num": [1] * 3,
        "line_num": [1] * 3,
        "conf": [0, 99, 95],
        "left": [0, 10, 30],
        "top": [0, 20, 20],
        "width": [0, 10, 10],
        "height": [0, 10, 10],
    }
    monkeypatch.setattr(pytesseract, "image_to_data", Mock(return_value=d))
    for size in [(100, 100), (100, 400)]:
        r = v.recognize(Image.new("RGB", size))
        assert r[0]["text"] == "A B"
        assert r[0]["confidence"] == 0.95


def test_rapidocr(monkeypatch):
    model = Mock(
        return_value=NS(
            boxes=np.array([[[10, 20], [40, 20], [40, 30], [10, 30]]]), txts=["TEST"], scores=[0.99]
        )
    )
    factory = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "rapidocr", NS(RapidOCR=factory, LangRec=NS(EN="en")))
    monkeypatch.setattr(v, "BACKEND", "rapidocr")
    monkeypatch.setattr(v, "_engine", None)
    assert v.recognize(Image.new("RGB", (100, 100)))[0]["rect"] == [0.1, 0.2, 0.4, 0.3]
    model.return_value = NS(boxes=None)
    assert v.recognize(Image.new("RGB", (100, 100))) == []
    factory.assert_called_once()


def test_apple_contract(monkeypatch):
    request = Mock()
    handler = Mock()
    handler.performRequests_error_.return_value = (True, None)
    candidate = Mock()
    candidate.string.return_value = "TEST"
    candidate.confidence.return_value = 0.9
    observation = Mock()
    observation.topCandidates_.return_value = [candidate]
    observation.boundingBox.return_value = NS(
        origin=NS(x=0.1, y=0.2), size=NS(width=0.3, height=0.1)
    )
    request.results.return_value = [observation]
    vision = NS(
        VNRecognizeTextRequest=Mock(),
        VNImageRequestHandler=Mock(),
        VNRequestTextRecognitionLevelAccurate=1,
    )
    vision.VNRecognizeTextRequest.alloc.return_value.init.return_value = request
    vision.VNImageRequestHandler.alloc.return_value.initWithCGImage_options_.return_value = handler
    for name, value in {
        "Vision": vision,
        "Foundation": NS(NSData=Mock()),
        "objc": NS(autorelease_pool=contextlib.nullcontext),
        "Quartz": Mock(),
    }.items():
        monkeypatch.setitem(sys.modules, name, value)
    import apple_vision

    monkeypatch.setattr(v, "BACKEND", "vision")
    assert v.recognize(Image.new("RGB", (50, 50)))[0]["text"] == "TEST"
    request.results.return_value = None
    assert apple_vision.recognize(Image.new("RGB", (50, 50))) == []
    handler.performRequests_error_.return_value = (False, "failure")
    with pytest.raises(RuntimeError):
        apple_vision.recognize(Image.new("RGB", (50, 50)))


def test_input_audit_and_paths(tmp_path):
    for event, args in [
        ("socket.connect", ()),
        ("open", ("example.xlsx", "r", 0)),
        ("open", ("pdf-reviewed.json", "r", 0)),
        ("open", (str(pdf_only.root / "review/corrections.json"), "r", 0)),
    ]:
        with pytest.raises(RuntimeError):
            pdf_only.audit(event, args)
    for args in [
        (str(tmp_path / "source.pdf"), "r", 0),
        (str(tmp_path / "output"), "w", 0),
        (3, None, 0),
        (str(tmp_path / "source.pdf"), None, 0),
    ]:
        pdf_only.audit("open", args)
    assert str(tmp_path / "source.pdf") in pdf_only.reads
    for prefix in [
        "/Users/michaelfuscoletti/Desktop/crash_report",
        "/Users/michaelfuscoletti/Desktop/report_workspace/engines/crash_report",
    ]:
        assert source_path(prefix + "/source.pdf") == ROOT / "source.pdf"
    assert source_path(tmp_path / "source.pdf") == tmp_path / "source.pdf"
