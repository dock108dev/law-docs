"""NJTR-1 extraction registered to printed labels, not PDF page positions."""

import io, re, hashlib, subprocess
from pathlib import Path
import numpy as np
import cv2
import pymupdf as fitz
from PIL import Image, ImageOps
from local_vision import recognize, BACKEND


def compact(s):
    return re.sub(r"\s+", " ", s).strip()


def center(r):
    return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)


def contains(r, p):
    return r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]


def grouped(values, tolerance):
    groups = []
    for v in sorted(values):
        if groups and v - groups[-1][-1] <= tolerance:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def focused_code(crop, recognizer=recognize):
    """Require two confident reads inside the value, excluding printed labels."""
    inner = crop.crop((18, 18, crop.width - 18, crop.height - 18))
    votes = []
    evidence = []
    for left, top in ((0.30, 0.28), (0.34, 0.35)):
        piece = inner.crop(
            (
                round(inner.width * left),
                round(inner.height * top),
                round(inner.width * 0.94),
                round(inner.height * 0.96),
            )
        )
        observations = recognizer(ImageOps.expand(piece, 18, "white"))
        text = " ".join(o["text"] for o in observations).strip()
        confidence = min((o["confidence"] for o in observations), default=0)
        evidence.append(
            {
                "method": "focused contributing code",
                "text": text,
                "confidence": confidence,
                "inset": [left, top, 0.94, 0.96],
            }
        )
        if re.fullmatch(r"\d{2}", text) and confidence >= 0.95:
            votes.append(text)
    return (votes[0] if len(votes) == 2 and len(set(votes)) == 1 else None), evidence


class Layout:
    def __init__(self, im, observations, anchors=None):
        self.im = im
        self.obs = observations
        self.anchor_obs = anchors or observations

    def anchor(self, pattern, near=None):
        found = [o for o in self.anchor_obs if re.search(pattern, o["text"], re.I)]
        if near is not None:
            found.sort(key=lambda o: abs(center(o["rect"])[1] - near))
        if not found:
            raise ValueError("Missing layout anchor: " + pattern)
        return found[0]["rect"]

    def select(self, r):
        vals = [o for o in self.obs if contains(r, center(o["rect"]))]
        # Reading order: clusters at a common baseline, then left to right.
        vals.sort(key=lambda o: round(center(o["rect"])[1] / 0.006))
        lines = []
        for o in vals:
            cy = center(o["rect"])[1]
            if lines and abs(cy - lines[-1][0]) < 0.006:
                lines[-1][1].append(o)
            else:
                lines.append([cy, [o]])
        return [o for _, line in lines for o in sorted(line, key=lambda x: x["rect"][0])]

    def horizontal(self, x0, x1, y0, y1):
        gray = np.array(self.im.convert("L"))
        h, w = gray.shape
        a = gray[int(y0 * h) : int(y1 * h), int(x0 * w) : int(x1 * w)] < 150
        positions = np.where(a.mean(axis=1) > 0.45)[0]
        return [y0 + y / h for y in grouped(positions.tolist(), 3)]


def read_field(key, r, method="lines", numeric=False, *, l, anchors, im, folder, out, record, page):
    fields = record["fields"]
    w, h = im.size
    r = [max(0, r[0]), max(0, r[1]), min(1, r[2]), min(1, r[3])]
    selected = l.select(r)
    native_selected = [o for o in anchors if o.get("native") and contains(r, center(o["rect"]))]
    if native_selected:
        selected = sorted(
            native_selected, key=lambda o: (round(center(o["rect"])[1] / 0.006), o["rect"][0])
        )
    crop = im.crop(tuple(round(v * s) for v, s in zip(r, [w, h, w, h])))
    crop = ImageOps.expand(crop, border=18, fill="white")
    crop.save(folder / f"{key}.png")
    if method == "crop" or not selected:
        lines = recognize(crop)
        text = " ".join(o["text"] for o in lines)
    else:
        lines = selected
        text = " ".join(o["text"] for o in selected)
    val = compact(text).strip("_ |")
    alternatives = []
    if key == "date":
        inner = crop.crop((18, 18, crop.width - 18, crop.height - 18))
        parts = []
        candidates = []

        def date_candidate(t):
            if re.search(r"[^0-9\s|\[\]()I.,/\-]", t):
                return
            digits = re.sub(r"\D", "", t)
            if len(digits) == 6:
                try:
                    from datetime import datetime

                    datetime.strptime(digits, "%m%d%y")
                    candidates.append(digits)
                except ValueError:
                    pass

        date_candidate(val)
        for o in anchors:
            if contains(r, center(o["rect"])):
                date_candidate(o["text"])
        for idx in range(3):
            piece = inner.crop(
                (
                    round(inner.width * (idx + 0.10) / 3),
                    round(inner.height * 0.25),
                    round(inner.width * (idx + 0.90) / 3),
                    round(inner.height * 0.95),
                )
            )
            piece = ImageOps.expand(piece, border=18, fill="white")
            piece.save(folder / f"date-part-{idx}.png")
            t = " ".join(o["text"] for o in recognize(piece))
            alternatives.append({"method": "date thirds", "text": t})
            parts.append(re.sub(r"\D", "", t))
        if all(re.fullmatch(r"\d{2}", v) for v in parts):
            date_candidate(" ".join(parts))
        for top in (0.15, 0.25, 0.35):
            for left in (0.03, 0.06, 0.10):
                piece = inner.crop(
                    (
                        round(left * inner.width),
                        round(top * inner.height),
                        round(0.86 * inner.width),
                        round(0.86 * inner.height),
                    )
                )
                t = " ".join(o["text"] for o in recognize(ImageOps.expand(piece, 18, "white")))
                alternatives.append(
                    {"method": "date border exclusion", "inset": [left, top, 0.86, 0.86], "text": t}
                )
                date_candidate(t)
        if not candidates:
            # Thin grid strokes disappear before bold numerals. Require agreement
            # at both neighboring kernel sizes; conflicting valid dates stay held.
            for kernel in (2, 3):
                a = 255 - np.array(inner.convert("L"))
                a = cv2.morphologyEx(a, cv2.MORPH_OPEN, np.ones((kernel, kernel), np.uint8))
                piece = Image.fromarray(255 - a).crop(
                    (
                        round(inner.width * 0.10),
                        round(inner.height * 0.20),
                        round(inner.width * 0.98),
                        round(inner.height * 0.94),
                    )
                )
                t = " ".join(o["text"] for o in recognize(ImageOps.expand(piece, 18, "white")))
                alternatives.append({"method": "thin-grid removal", "kernel": kernel, "text": t})
                date_candidate(t)
            if len(candidates) < 2:
                candidates = []
        if len(set(candidates)) == 1:
            val = " ".join(candidates[0][i : i + 2] for i in (0, 2, 4))
        elif len(set(candidates)) > 1:
            val = ""
            record["issues"].append("Conflicting date OCR: " + repr(sorted(set(candidates))))
    if key.endswith(("_street", "_cityzip")):
        cropped = " ".join(o["text"] for o in recognize(crop)).strip(" ._|")
        alternatives.append({"method": "local address crop", "text": cropped})
        if (
            key.endswith("_cityzip")
            and not re.fullmatch(r".+[, .]+[A-Z]{2}\s+\d{5}(?:-\d{4})?", val)
            and re.fullmatch(r".+[, .]+[A-Z]{2}\s+\d{5}(?:-\d{4})?", cropped)
        ):
            val = cropped
        if (
            key.endswith("_street")
            and re.sub(r"\s", "", val) == re.sub(r"\s", "", cropped)
            and len(cropped.split()) > len(val.split())
        ):
            val = cropped
        val = val.rstrip(" ._")
    if numeric:
        if key in ("118a", "118b", "119a", "119b"):
            val = re.sub(r"^" + key[:3] + r"\D*", "", val)
        val = val.strip(" |[](){}!¡\"'.,_")
        valid = (
            r"(?:\d{1,2}|[PB]\d)"
            if re.match(r"[A-D]_|vehicle", key)
            else r"\d{4}"
            if key == "municipality_code"
            else r"\d{2}"
        )
        fullvals = [o["text"].strip(" |[]()\"'.,_") for o in selected]
        fullvals = [v for v in fullvals if re.fullmatch(valid, v)]
        if len(fullvals) == 1:
            val = fullvals[0]
        if not re.fullmatch(valid, val):
            tilevals = {
                o["text"].strip(" |[]")
                for o in anchors
                if contains(r, center(o["rect"])) and re.fullmatch(valid, o["text"].strip(" |[]"))
            }
            if len(tilevals) == 1:
                val = next(iter(tilevals))
                alternatives.append({"method": "tile/native numeric", "text": val})
        if not re.fullmatch(valid, val):
            alt = subprocess.run(
                ["tesseract", str(folder / f"{key}.png"), "stdout", "--psm", "7"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            alternatives.append({"method": "tesseract psm7", "text": alt})
            alt = alt.strip(" |[](){}!¡\"'.,_")
            if re.fullmatch(valid, alt):
                val = alt
        if not re.fullmatch(valid, val) and (
            key == "municipality_code" or re.match(r"[A-D]_|vehicle", key)
        ):
            inner = crop.crop((18, 18, crop.width - 18, crop.height - 18))
            values = []
            insets = [(0.05, 0.1, 0.9), (0.1, 0.2, 0.9), (0.15, 0.3, 0.9)]
            if key == "municipality_code":
                insets += [(0, 0.28, 1), (0.02, 0.25, 0.98), (0.03, 0.3, 1)]
            for left, top, bottom in insets:
                piece = inner.crop(
                    (
                        round(left * inner.width),
                        round(top * inner.height),
                        round((1 - left) * inner.width),
                        round(bottom * inner.height),
                    )
                )
                t = " ".join(
                    o["text"] for o in recognize(ImageOps.expand(piece, 18, "white"))
                ).strip(" |[]()")
                alternatives.append(
                    {
                        "method": "municipality border exclusion",
                        "inset": [left, top, 1 - left, bottom],
                        "text": t,
                    }
                )
                if key == "municipality_code" and re.fullmatch(r"[0-9 ]+", t):
                    t = t.replace(" ", "")
                if re.fullmatch(valid, t):
                    values.append(t)
            if len(values) >= 2 and len(set(values)) == 1:
                val = values[0]
        if key in ("118a", "118b", "119a", "119b") and not re.fullmatch(valid, val):
            inner = crop.crop((18, 18, crop.width - 18, crop.height - 18))
            tight = inner.crop(
                (
                    round(inner.width * 0.30),
                    round(inner.height * 0.28),
                    round(inner.width * 0.94),
                    round(inner.height * 0.96),
                )
            )
            t = " ".join(o["text"] for o in recognize(ImageOps.expand(tight, 18, "white"))).strip(
                " |[]()\"'.,_"
            )
            alternatives.append({"method": "code border exclusion", "text": t})
            if re.fullmatch(valid, t):
                val = t
        if not re.fullmatch(valid, val):
            for psm in (11, 13):
                alt = subprocess.run(
                    [
                        "tesseract",
                        str((folder / f"{key}.png").resolve()),
                        "stdout",
                        "--psm",
                        str(psm),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                alternatives.append({"method": f"tesseract psm{psm}", "text": alt})
                alt = alt.strip(" |[](){}!¡\"'.,_")
                if re.fullmatch(valid, alt):
                    val = alt
                    break
        if not re.fullmatch(valid, val) and re.fullmatch(r"[A-D]_83|vehicle[12]", key):
            inner = crop.crop((18, 18, crop.width - 18, crop.height - 18))
            piece = inner.crop(
                (round(inner.width * 0.1), 0, round(inner.width * 0.80), inner.height)
            )
            piece = ImageOps.expand(piece.resize((piece.width * 3, piece.height * 3)), 30, "white")
            path = folder / f"{key}-single-character.png"
            piece.save(path)
            t = subprocess.run(
                ["tesseract", str(path.resolve()), "stdout", "--psm", "10"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            alternatives.append({"method": "isolated vehicle digit, 3x psm10", "text": t})
            if re.fullmatch(r"\d", t):
                val = t
        if not re.fullmatch(valid, val) and key in ("118a", "118b", "119a", "119b"):
            a = 255 - np.array(crop.convert("L"))
            grid = cv2.bitwise_or(
                cv2.morphologyEx(a, cv2.MORPH_OPEN, np.ones((int(crop.height * 0.6), 1), np.uint8)),
                cv2.morphologyEx(a, cv2.MORPH_OPEN, np.ones((1, int(crop.width * 0.6)), np.uint8)),
            )
            inner = Image.fromarray(255 - cv2.subtract(a, grid)).crop(
                (18, 18, crop.width - 18, crop.height - 18)
            )
            values = []
            for top in (0.2, 0.3):
                piece = inner.crop(
                    (
                        round(inner.width * 0.2),
                        round(inner.height * top),
                        round(inner.width * 0.95),
                        round(inner.height * 0.94),
                    )
                )
                t = " ".join(
                    o["text"] for o in recognize(ImageOps.expand(piece, 18, "white"))
                ).strip(" |[](){}!¡:\"'.,_")
                alternatives.append({"method": "code grid removal", "top": top, "text": t})
                if re.fullmatch(valid, t):
                    values.append(t)
            if len(values) == 2 and len(set(values)) == 1:
                val = values[0]
        if key in ("118a", "118b", "119a", "119b") and not re.fullmatch(valid, val):
            # Confirm printed dash strokes geometrically; never interpret an empty crop as '--'.
            inner = crop.crop((18, 18, crop.width - 18, crop.height - 18))
            a = np.array(inner.convert("L")) < 150
            a = a[
                round(a.shape[0] * 0.38) : round(a.shape[0] * 0.78),
                round(a.shape[1] * 0.25) : round(a.shape[1] * 0.90),
            ]
            n, labels, stats, cents = cv2.connectedComponentsWithStats(a.astype("uint8"), 8)
            dash = [
                (x, y, bw, bh)
                for x, y, bw, bh, area in stats[1:]
                if bw >= 1.8 * bh and bw >= 4 and bh <= inner.height * 0.2
            ]
            other = [1 for x, y, bw, bh, area in stats[1:] if bh > inner.height * 0.22 and bw > 4]
            if (len(dash) >= 2 and not other) or any(
                re.fullmatch(r"[-—]+", o["text"]) for o in native_selected
            ):
                val = "--"
    if key.endswith("_given"):
        alt = (
            subprocess.run(
                ["tesseract", str((folder / f"{key}.png").resolve()), "stdout", "--psm", "7"],
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .strip(" |[](){}\\_")
        )
        alternatives.append({"method": "given name segmentation", "text": alt})
        if re.sub(r"\s", "", alt) == re.sub(r"\s", "", val) and len(alt.split()) > len(val.split()):
            val = alt
    if key.endswith("_street"):
        val = re.sub(r"(?<=[a-z])(?=Apt\b)", " ", val)
    if BACKEND == "rapidocr" and key in ("118a", "118b", "119a", "119b"):
        focused, evidence = focused_code(crop)
        alternatives.extend(evidence)
        if focused is not None:
            val = focused
        elif val == "25":
            val = ""
            record["issues"].append(
                f"{key}: no-contributing-action code needs source review; focused readings did not agree."
            )
    fields[key] = {
        "raw": text,
        "normalized": val,
        "rect": [v * s for v, s in zip(r, [page.rect.width, page.rect.height] * 2)],
        "crop": str((folder / f"{key}.png").relative_to(out)),
        "method": method,
        "observations": lines,
        "alternatives": alternatives,
    }
    return val


def inspect_page(page, number, out):
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
    im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    folder = out / "evidence" / f"page-{number:02}"
    folder.mkdir(parents=True)
    im.save(folder / "source.png")
    obs = recognize(im)
    anchors = list(obs)
    # Uniform overlapping tiles recover small printed labels missed on the full image.
    # These are image-processing tiles, not report/page-specific field coordinates.
    for x0, y0 in [(0, 0), (0.4, 0), (0, 0.4), (0.4, 0.4)]:
        tile = im.crop(
            (
                round(x0 * im.width),
                round(y0 * im.height),
                round((x0 + 0.6) * im.width),
                round((y0 + 0.6) * im.height),
            )
        )
        for o in recognize(tile):
            a, b, c, d = o["rect"]
            o["rect"] = [x0 + 0.6 * a, y0 + 0.6 * b, x0 + 0.6 * c, y0 + 0.6 * d]
            o["tile"] = [x0, y0]
            anchors.append(o)
    native = page.get_text()
    if len(native) > 100:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = " ".join(s["text"] for s in line["spans"])
                r = line["bbox"]
                anchors.insert(
                    0,
                    {
                        "text": text,
                        "confidence": 1.0,
                        "rect": [v / s for v, s in zip(r, [page.rect.width, page.rect.height] * 2)],
                        "native": True,
                    },
                )
    record = {
        "source_page": number,
        "mode": f"selectable text + {BACKEND} anchors"
        if len(native) > 100
        else f"local {BACKEND} OCR",
        "render_sha256": hashlib.sha256(
            page.get_pixmap(matrix=fitz.Matrix(3, 3)).samples
        ).hexdigest(),
        "page_size": [page.rect.width, page.rect.height],
        "fields": {},
        "issues": [],
        "ocr_observations": obs,
        "anchor_observations": anchors,
        "native_text": native,
        "layout": "anchor-registered NJTR-1 P1",
    }
    (folder / "text.txt").write_text("\n".join(o["text"] for o in obs))
    l = Layout(im, obs, anchors)
    fields = record["fields"]
    w, h = im.size
    from functools import partial

    read = partial(
        read_field, l=l, anchors=anchors, im=im, folder=folder, out=out, record=record, page=page
    )
    if not re.search(r"NJTR.?1\s*P[1Il]", " ".join(o["text"] for o in anchors), re.I):
        record["issues"].append("Unsupported first-page form; no recipients selected")
        return record
    try:
        # Both printed field number and label establish the driver columns.
        names = [l.anchor(r"^26\W.*(?:Dr.ver|Drver)"), l.anchor(r"^56\W.*(?:Dr.ver|Drver)")]
        streets = [l.anchor(r"^27\W.*(?:Number|Street)"), l.anchor(r"^57\W.*(?:Number|Street)")]
        cities = []
        for number in [28, 58]:
            try:
                cities.append(l.anchor(r"^" + str(number) + r"\W.*City"))
            except ValueError:
                cities.append(None)
        if cities[0] is None and cities[1] is None:
            raise ValueError("Both driver City anchors missing")
        for i in (0, 1):
            if cities[i] is None:
                j = 1 - i
                dx = streets[i][0] - streets[j][0]
                dy = streets[i][1] - streets[j][1]
                cities[i] = [
                    cities[j][0] + dx,
                    cities[j][1] + dy,
                    cities[j][2] + dx,
                    cities[j][3] + dy,
                ]
        eyes = [l.anchor(r"^30\W.*Eyes"), l.anchor(r"^60\W.*Eyes")]
        shift = streets[1][0] - streets[0][0]
        bodyheight = np.median(
            [
                o["rect"][3] - o["rect"][1]
                for o in obs
                if 0.010 < o["rect"][3] - o["rect"][1] < 0.022
            ]
        )
        pad = float(bodyheight * 0.3)
        for v, (n, s, c, e) in enumerate(zip(names, streets, cities, eyes), 1):
            left = min(n[0], s[0], c[0]) - pad
            right = left + shift - pad
            last = l.anchor(r"^Last Name$", center(n)[1])
            lastx = last[0]
            # Find last-name header in this column and this driver row (never owner's row).
            lastheads = [
                o["rect"]
                for o in anchors
                if re.fullmatch("Last Name", o["text"], re.I)
                and left < o["rect"][0] < right
                and abs(center(o["rect"])[1] - center(n)[1]) < 0.01
            ]
            if not lastheads:
                other = [
                    o["rect"]
                    for o in anchors
                    if re.fullmatch("Last Name", o["text"], re.I)
                    and abs(center(o["rect"])[1] - center(n)[1]) < 0.015
                ]
                if not other:
                    raise ValueError("Missing driver last-name headers in both columns")
                dx = streets[v - 1][0] - streets[2 - v][0]
                lastheads = [[r[0] + dx, r[1], r[2] + dx, r[3]] for r in other]
            lastx = lastheads[0][0]
            sexheads = [
                o["rect"][0]
                for o in obs
                if re.search(r"\b(?:29|59)\W.*Sex", o["text"]) and left < o["rect"][0] < right
            ]
            name_right = min(sexheads, default=right - pad * 8)
            y0 = n[3]
            y1 = s[1]
            read(f"v{v}_given", [left, y0, lastx - pad, y1])
            if len(native) > 100:
                read(f"v{v}_name", [left, y0, name_right, y1])
            read(f"v{v}_last", [lastx - pad, y0, name_right, y1])
            read(f"v{v}_street", [left, s[3], right, c[1]])
            read(f"v{v}_cityzip", [left, c[3], right, e[1]])
        case = l.anchor(r"^1\W.*Case Number")
        dept = l.anchor(r"^2\W.*P[oa]lice Dept")
        station = l.anchor(r"^(?:1?3)\W.*Station")
        read("case", [case[0] - pad, case[1], names[0][0] + shift / 2, dept[1]], "lines")
        fields["case"]["normalized"] = re.sub(
            r"^1\W*Cas. Number\s*", "", fields["case"]["normalized"], flags=re.I
        )
        read("department", [dept[0] - pad, dept[3], dept[0] + shift * 0.40, station[1] + pad])
        veh = []
        for pattern in [r"^2[36]\W.*Veh", r"^53\W.*Ve[hIt]"]:
            try:
                veh.append(l.anchor(pattern))
            except ValueError:
                veh.append(None)
        if all(a is None for a in veh):
            raise ValueError("Both vehicle-number labels missing")
        for i in (0, 1):
            if veh[i] is None:
                j = 1 - i
                dx = names[i][0] - names[j][0]
                dy = names[i][1] - names[j][1]
                a = veh[j]
                veh[i] = [a[0] + dx, a[1] + dy, a[2] + dx, a[3] + dy]
                # Recover the crop from the paired printed columns, then OCR
                # the actual vehicle number. Never fill an assumed number.
                record["issues"].append(
                    f"Vehicle {i + 1} label located using the opposite printed column; verify source crop."
                )
        for v, a in enumerate(veh, 1):
            read(
                f"vehicle{v}",
                [a[0], a[3], a[0] + shift * 0.12, names[v - 1][1] - pad],
                "lines",
                True,
            )
        date = l.anchor(r"(?:Date|ate) of Crash")
        day = l.anchor(r"Day")
        try:
            muni = l.anchor(r"^(?:7\W.*Mun|.*Municip)")
        except ValueError:
            muni = l.anchor(r"^1?7\W", center(date)[1])
        read("date", [date[0] - pad, date[3], day[0] - pad, veh[0][1] - pad / 2], "crop")
        read(
            "municipality_code",
            [muni[0] - pad, muni[3], muni[2] + pad * 2, veh[0][1] - pad / 2],
            "crop",
            True,
        )
        # Right margin fields: use the printed B subfield labels and measured vertical spacing.
        b = l.anchor(r"^118b")
        codeanchors = []
        for idx, label in [(1, "119a"), (2, "119b"), (3, "120a"), (4, "120b")]:
            try:
                a = l.anchor(r"^" + label)
                codeanchors.append((a[1] - b[1]) / (idx + 0 if idx > 0 else 1))
            except ValueError:
                pass
        # 118b -> 119a is one row; all available labels vote on row pitch.
        spacing = float(np.median(codeanchors)) if codeanchors else 0
        if spacing <= 0:
            raise ValueError("Contributing-code row pitch unavailable")
        x0 = b[0] - pad
        x1 = b[0] + shift * 0.115
        for idx, key in enumerate(["118a", "118b", "119a", "119b"]):
            top = b[1] + (idx - 1) * spacing
            read(key, [x0, top + spacing * 0.15, x1, top + spacing * 0.97], "crop", True)
        # Occupant columns are anchored by the contiguous printed 83–95 header sequence.
        table = l.anchor(r"Names.*Address")
        headers = {}
        for k in ["83", "84", "85", "86", "87", "94", "95"]:
            try:
                rect = l.anchor(r"^" + k + r"\W*$", center(table)[1])
                headers[k] = rect
            except ValueError:
                pass
        known = [
            (int(k), center(r)[0])
            for k, r in headers.items()
            if int(k) <= 87 and abs(center(r)[1] - center(table)[1]) < 0.02
        ]
        if len(known) < 2:
            raise ValueError("Insufficient occupant column anchors")
        slope, intercept = np.polyfit(*zip(*known), 1)
        if slope <= 0:
            raise ValueError("Invalid occupant column order")
        for k in ["83", "84", "85", "86", "87"]:
            if k not in headers:
                x = slope * int(k) + intercept
                headers[k] = [x, table[1], x, table[3]]
        if not all(k in headers for k in ["94", "95"]):
            raise ValueError("Missing occupant name-column anchors")
        mids = {k: center(r)[0] for k, r in headers.items()}
        header_y = max(r[3] for r in headers.values())
        lines = l.horizontal(
            mids["83"], mids["95"] + shift * 0.75, header_y, min(0.995, header_y + shift * 0.4)
        )
        if len(lines) == 4:
            pitch = float(np.median(np.diff(lines)))
            indexes = [round((y - lines[0]) / pitch) for y in lines]
            if indexes[-1] == 4 and all(
                abs(y - (lines[0] + i * pitch)) < pitch * 0.12 for y, i in zip(lines, indexes)
            ):
                record["issues"].append(
                    "One broken occupant grid line reconstructed from four aligned boundaries"
                )
                lines = [lines[0] + i * pitch for i in range(5)]
        if len(lines) < 5:
            raise ValueError("Occupant row grid incomplete")
        lines = lines[:5]
        for letter, (y0, y1) in zip("ABCD", zip(lines, lines[1:])):
            for key in ["83", "84", "86"]:
                mid = mids[key]
                half = (mids[str(int(key) + 1)] - mid) / 2
                read(
                    f"{letter}_{key}",
                    [mid - half + pad / 3, y0 + pad / 2, mid + half - pad / 3, y1 - pad / 2],
                    "crop",
                    True,
                )
            nameleft = mids["95"] + (mids["95"] - mids["94"]) / 2
            read(f"{letter}_95", [nameleft, y0 + pad / 3, b[0] - pad, y1 - pad / 3])
        record["anchors"] = {
            "driver_names": names,
            "streets": streets,
            "cities": cities,
            "occupant_headers": headers,
            "occupant_rows": lines,
        }
    except ValueError as error:
        record["issues"].append(str(error))
    return record
