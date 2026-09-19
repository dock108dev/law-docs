"""Download OCR models at build time and verify the approved contents."""

import hashlib, json
from pathlib import Path
from rapidocr import RapidOCR, LangRec
import rapidocr

RapidOCR(params={"Global.log_level": "error", "Rec.lang_type": LangRec.EN})
folder = Path(rapidocr.__file__).parent / "models"
for name, digest in json.loads(
    (Path(__file__).resolve().parents[1] / "deploy/models.json").read_text()
).items():
    assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, (
        f"OCR model changed: {name}"
    )
print("OCR model checksums verified")
