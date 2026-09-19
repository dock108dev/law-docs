"""Local, coordinate-based OCR for the supplied ruled municipal calendar format.
No names, row totals, charges, or calendar-specific row coordinates are baked in.
"""

import os

os.environ.setdefault("OMP_THREAD_LIMIT", "1")
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import cv2
import numpy as np
import pymupdf
import pytesseract

if os.environ.get("PLEA_TESSERACT"):
    pytesseract.pytesseract.tesseract_cmd = os.environ["PLEA_TESSERACT"]

VERSION = "ruled-calendar-2"


def text_table(page, directory, number):
    """Use embedded text only when a ruled table identifies the required headers.

    Return None for image-only or unrecognized pages so each page can use OCR.
    Coordinates stay paired with the rendered source, including PDF rotation.
    """
    if page.rotation:
        # Table detection expects unrotated PDF coordinates. Render proofs in
        # that same space, then restore the in-memory page's display rotation.
        original_rotation = page.rotation
        page.set_rotation(0)
        try:
            return text_table(page, directory, number)
        finally:
            page.set_rotation(original_rotation)
    if not page.get_text().strip():
        return None
    tables = page.find_tables().tables
    matched = []
    for table in tables:
        cells = table.extract()
        if not cells:
            continue
        headers = [" ".join((s or "").split()).casefold() for s in cells[0]]
        required = ["defendant name", "case number", "offense"]
        if not all(headers.count(label) == 1 for label in required):
            continue
        matched.append((table, cells, [headers.index(label) for label in required]))
    if not matched:
        return None
    pix = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), colorspace=pymupdf.csRGB)
    pix.save(str(directory / f"page-{number}.png"))
    image = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
    rows = []
    for table, cells, columns in sorted(matched, key=lambda item: item[0].bbox[1]):
        for position, values in enumerate(cells[1:], 1):
            raw = [values[c] or "" for c in columns]
            name, case, offense = [" ".join(value.split()) for value in raw]
            charges = []
            for line in raw[2].splitlines():
                line = " ".join(line.split())
                if not line:
                    continue
                if charges and not re.match(r"^\d+[A-Za-z]?(?::|-)", line):
                    charges[-1] += " " + line
                else:
                    charges.append(line)
            fields = {"name": name, "case_number": case, "offenses": charges}
            issues = [
                f"Missing printed {label}."
                for label, value in [
                    ("defendant name", name),
                    ("case number", case),
                    ("offense", offense),
                ]
                if not value
            ]
            rects = [table.rows[position].cells[c] for c in columns]
            rect = pymupdf.Rect(rects[0])
            for box in rects[1:]:
                rect |= pymupdf.Rect(box)
            rect = rect * page.rotation_matrix * pymupdf.Matrix(3, 3)
            x0, y0, x1, y1 = [int(round(v)) for v in rect]
            ordinal = len(rows) + 1
            ident = f"p{number:02}-r{ordinal:02}"
            crop = image[
                max(0, y0 - 3) : min(pix.height, y1 + 3), max(0, x0 - 3) : min(pix.width, x1 + 3)
            ]
            cv2.imwrite(str(directory / f"{ident}.png"), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
            rows.append(
                {
                    "id": ident,
                    "source_page": number,
                    "source_row": ordinal,
                    "bbox": [x0, y0, x1, y1],
                    **fields,
                    "ocr": fields.copy(),
                    "extraction_method": "pdf-text",
                    "raw_text": dict(zip(["name", "case_number", "offenses"], raw)),
                    "issues": issues,
                    "reviewed": False,
                    "excluded": False,
                    "exclusion_reason": "",
                    "review_note": "",
                    "manual": False,
                }
            )
    return rows, {
        "number": number,
        "rotation": page.rotation,
        "deskew": 0,
        "issues": [],
        "reconciled": False,
        "detected_rows": len(rows),
        "width": pix.width,
        "height": pix.height,
        "extraction_method": "pdf-text",
    }


def groups(values, gap=6):
    result = []
    for v in values:
        if result and v - result[-1][-1] <= gap:
            result[-1].append(int(v))
        else:
            result.append([int(v)])
    return [int(np.median(g)) for g in result]


def upright(page):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), colorspace=pymupdf.csRGB)
    image = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    # OSD is evidence, not an assumption that every portrait PDF is sideways.
    try:
        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT, timeout=30)
        rotation = int(osd["rotate"])
    except pytesseract.TesseractError:
        rotation = 0
    for _ in range((rotation // 90) % 4):
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    bw = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)[1]
    lines = cv2.HoughLinesP(
        bw, 1, np.pi / 1800, 150, minLineLength=image.shape[1] * 0.5, maxLineGap=20
    )
    angles = (
        []
        if lines is None
        else [np.degrees(np.arctan2(y2 - y1, x2 - x1)) for x1, y1, x2, y2 in lines.reshape(-1, 4)]
    )
    angles = [a for a in angles if abs(a) < 4]
    angle = float(np.median(angles)) if angles else 0
    image = cv2.warpAffine(
        image,
        cv2.getRotationMatrix2D((image.shape[1] / 2, image.shape[0] / 2), angle, 1),
        (image.shape[1], image.shape[0]),
        borderValue=(255, 255, 255),
    )
    return image, rotation, angle


def geometry(image):
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    light = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)[1]
    dark = cv2.threshold(gray, 115, 255, cv2.THRESH_BINARY_INV)[1]
    vert = cv2.morphologyEx(light, cv2.MORPH_OPEN, np.ones((70, 1), np.uint8))
    xs = groups(np.where(np.sum(vert > 0, axis=0) > h * 0.06)[0], 10)
    xs = [x for x in xs if w * 0.025 < x < w * 0.985]
    if len(xs) < 5:
        raise ValueError(
            "Could not identify the printed table columns; inspect this page and add rows manually."
        )

    def horizontal(bw):
        mask = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((1, 70), np.uint8))
        return cv2.dilate(mask, np.ones((9, 1), np.uint8))

    hm = horizontal(dark)
    ys = groups(np.where(np.sum(hm > 0, axis=1) > w * 0.65)[0])
    if len(ys) < 2:
        raise ValueError("Could not identify row borders; inspect this page and add rows manually.")
    # Recover a faint border, but reject scan folds extending outside the table.
    bright = horizontal(light)
    candidates = groups(np.where(np.sum(bright > 0, axis=1) > w * 0.65)[0])
    v_support = np.sum(vert[:, xs[0] : xs[4] + 1] > 0, axis=1)
    active = np.where(v_support >= 6)[0]
    bottom = int(active[-1]) if len(active) else ys[-1]
    for y in candidates:
        outer = np.concatenate(
            [bright[y, : max(xs[0] - 15, 1)], bright[y, min(xs[-1] + 15, w - 1) :]]
        )
        if (
            max(ys) + 30 < y <= bottom + 10
            and min(abs(y - z) for z in ys) > 30
            and np.mean(outer > 0) < 0.2
        ):
            ys.append(y)
    ys.sort()
    return xs, ys


def cell_ocr(image):
    # Reading only inside printed cells excludes marginal handwritten additions.
    data = pytesseract.image_to_data(
        image, config="--psm 6", output_type=pytesseract.Output.DICT, timeout=30
    )
    lines = {}
    conf = []
    for j, text in enumerate(data["text"]):
        text = text.strip()
        if not text:
            continue
        key = (data["block_num"][j], data["par_num"][j], data["line_num"][j])
        lines.setdefault(key, []).append(text)
        if float(data["conf"][j]) >= 0:
            conf.append(float(data["conf"][j]))
    return {
        "lines": [" ".join(words) for words in lines.values()],
        "confidence": round(min(conf), 1) if conf else 0,
    }


def parse_cells(results):
    name, case, offense = results
    flags = []
    # Lowercase handwriting-like lines are withheld, never treated as printed text.
    clean_names = []
    for line in name["lines"]:
        stripped = re.sub(r"\[Assoc\.\]", "", line)
        if re.search("[a-z]", stripped):
            flags.append("Name contains possible handwriting or OCR noise; compare printed text.")
        else:
            clean_names.append(line)
    case_lines = []
    for line in case["lines"]:
        if re.fullmatch(r"[A-Z0-9 \-]+", line):
            case_lines.append(line)
        else:
            flags.append(
                "Case number contains possible handwriting or OCR noise; compare printed text."
            )
    charges = []
    for line in offense["lines"]:
        if re.fullmatch(r"\d+[A-Za-z]?(?::|-)\s*[0-9A-Za-z()., :\-]+", line):
            charges.append(line)
        else:
            flags.append(
                "Offense contains unrecognized text; enter the printed code from the image."
            )
    if any(re.search(r"[|_!\\=~]", line) for line in clean_names):
        flags.append("Name has suspicious OCR punctuation; verify initials and printed letters.")
    values = {
        "name": " ".join(clean_names),
        "case_number": " ".join(case_lines),
        "offenses": charges,
    }
    for key, res in zip(["Name", "Case number", "Offense"], results):
        if res["confidence"] < 85:
            flags.append(f"{key}: low OCR confidence ({res['confidence']:.0f}%).")
    if not values["name"]:
        flags.append("Missing printed defendant name.")
    if not values["case_number"]:
        flags.append("Missing printed case number.")
    if not charges:
        flags.append("Missing printed offense.")
    if len(charges) > 4:
        flags.append(
            "More than four offenses: resolve before PDF export; nothing will be truncated."
        )
    return values, list(dict.fromkeys(flags))


def extract_calendar(source, directory, progress=lambda message: None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(Path(source).read_bytes()).hexdigest()
    rows = []
    pages = []
    with pymupdf.open(source) as document:
        if document.page_count > 60:
            raise ValueError("This first version supports up to 60 pages per upload.")
        if document.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")
        for index, page in enumerate(document):
            number = index + 1
            progress(f"Reading page {number} of {len(document)}")
            native = text_table(page, directory, number)
            if native is not None:
                native_rows, entry = native
                rows.extend(native_rows)
                pages.append(entry)
                progress(f"Page {number}: {len(native_rows)} printed rows read directly from PDF")
                continue
            image, rotation, angle = upright(page)
            cv2.imwrite(
                str(directory / f"page-{number}.png"), cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            )
            entry = {
                "number": number,
                "rotation": rotation,
                "deskew": round(angle, 3),
                "issues": [],
                "reconciled": False,
                "detected_rows": 0,
                "width": image.shape[1],
                "height": image.shape[0],
                "extraction_method": "ocr",
            }
            pages.append(entry)
            try:
                xs, ys = geometry(image)
            except ValueError as exc:
                entry["issues"].append(str(exc))
                continue
            entry["columns"] = xs
            entry["borders"] = ys
            # Read the first band to distinguish a header from a row. Do not discard by name/plea/status.
            bands = []
            for top, bottom in zip(ys, ys[1:]):
                if bottom - top < 25:
                    entry["issues"].append(
                        "Very short table band detected; confirm row boundaries."
                    )
                    continue
                crop = image[top + 6 : bottom - 6, xs[0] + 6 : xs[4] - 6]
                if not bands:
                    first = cell_ocr(crop)
                    text = " ".join(first["lines"]).lower()
                    if "defendant" in text and ("case" in text or "offense" in text):
                        continue
                bands.append((top, bottom))
            # OCR independent cells concurrently; deterministic collection preserves source order.
            jobs = []
            with ThreadPoolExecutor(max_workers=6) as pool:
                for top, bottom in bands:
                    jobs.append(
                        [
                            pool.submit(
                                cell_ocr, image[top + 7 : bottom - 7, xs[a] + 8 : xs[b] - 8]
                            )
                            for a, b in [(0, 1), (1, 2), (3, 4)]
                        ]
                    )
                for ordinal, ((top, bottom), futures) in enumerate(zip(bands, jobs), 1):
                    results = [f.result() for f in futures]
                    values, issues = parse_cells(results)
                    ident = f"p{number:02}-r{ordinal:02}"
                    cv2.imwrite(
                        str(directory / f"{ident}.png"),
                        cv2.cvtColor(
                            image[max(0, top - 3) : bottom + 3, max(0, xs[0] - 4) : xs[4] + 4],
                            cv2.COLOR_RGB2BGR,
                        ),
                    )
                    rows.append(
                        {
                            "id": ident,
                            "source_page": number,
                            "source_row": ordinal,
                            "bbox": [xs[0], top, xs[4], bottom],
                            **values,
                            "ocr": values.copy(),
                            "raw_ocr": dict(zip(["name", "case_number", "offenses"], results)),
                            "issues": issues,
                            "reviewed": False,
                            "excluded": False,
                            "exclusion_reason": "",
                            "review_note": "",
                            "manual": False,
                        }
                    )
            entry["detected_rows"] = len(bands)
            progress(f"Page {number}: {len(bands)} printed row candidates")
    return {
        "source_sha256": digest,
        "extractor_version": VERSION,
        "pages": pages,
        "rows": rows,
        "status": "ready",
        "message": "Extraction complete. Compare rows and page counts with the source.",
    }
