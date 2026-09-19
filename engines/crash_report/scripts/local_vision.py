"""Local OCR adapter. Apple Vision on macOS; Tesseract on Linux."""

import os
import sys

os.environ.setdefault("OMP_THREAD_LIMIT", "1")
BACKEND = os.environ.get("CRASH_OCR", "vision" if sys.platform == "darwin" else "tesseract")
_engine = None


def recognize(image):
    global _engine
    if BACKEND == "vision":
        from apple_vision import recognize as apple_recognize

        return apple_recognize(image)
    if BACKEND == "rapidocr":
        import numpy as np
        from rapidocr import RapidOCR, LangRec

        if _engine is None:
            _engine = RapidOCR(
                params={
                    "Global.log_level": "error",
                    "Rec.lang_type": LangRec.EN,
                    "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                }
            )
        result = _engine(np.array(image.convert("RGB"))[:, :, ::-1])
        if result.boxes is None:
            return []
        return [
            {
                "text": str(text),
                "confidence": float(score),
                "rect": [
                    float(box[:, 0].min()) / image.width,
                    float(box[:, 1].min()) / image.height,
                    float(box[:, 0].max()) / image.width,
                    float(box[:, 1].max()) / image.height,
                ],
            }
            for box, text, score in zip(result.boxes, result.txts, result.scores)
        ]
    import pytesseract

    data = pytesseract.image_to_data(
        image,
        config="--psm 11" if image.height > 300 else "--psm 6",
        output_type=pytesseract.Output.DICT,
        timeout=60,
    )
    lines = {}
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        key = tuple(data[k][i] for k in ("block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(i)
    result = []
    for indexes in lines.values():
        x = min(data["left"][i] for i in indexes)
        y = min(data["top"][i] for i in indexes)
        right = max(data["left"][i] + data["width"][i] for i in indexes)
        bottom = max(data["top"][i] + data["height"][i] for i in indexes)
        result.append(
            {
                "text": " ".join(data["text"][i] for i in indexes),
                "confidence": min(float(data["conf"][i]) for i in indexes) / 100,
                "rect": [
                    x / image.width,
                    y / image.height,
                    right / image.width,
                    bottom / image.height,
                ],
            }
        )
    return result
