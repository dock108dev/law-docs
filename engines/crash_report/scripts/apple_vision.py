"""On-device Apple Vision OCR. No custom vocabulary or language correction."""

import io
import Vision
from Foundation import NSData
import objc
import Quartz


def recognize(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data = buf.getvalue()
    with objc.autorelease_pool():
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(False)
        request.setRecognitionLanguages_(["en-US"])
        request.setMinimumTextHeight_(0.002)
        source = Quartz.CGImageSourceCreateWithData(
            NSData.dataWithBytes_length_(data, len(data)), None
        )
        cgimage = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cgimage, None)
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise RuntimeError(str(error))
        lines = []
        for obs in request.results() or []:
            cand = obs.topCandidates_(1)[0]
            b = obs.boundingBox()
            x, y, w, h = b.origin.x, b.origin.y, b.size.width, b.size.height
            lines.append(
                {
                    "text": str(cand.string()),
                    "confidence": float(cand.confidence()),
                    "rect": [x, 1 - y - h, x + w, 1 - y],
                }
            )
        return lines


if __name__ == "__main__":
    import sys, json
    from PIL import Image

    print(json.dumps(recognize(Image.open(sys.argv[1])), indent=2))
