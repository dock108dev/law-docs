#!/usr/bin/env python3
"""Local NJTR-1 P1 R01/22 bounded extractor. No reference-workbook access."""

import argparse, csv, hashlib, io, json, re, subprocess, os, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import pymupdf as fitz
from PIL import Image
from PIL import ImageOps
import cv2
import numpy as np


def digest(data):
    return hashlib.sha256(data).hexdigest()


def clean(s):
    return re.sub(r"\s+", " ", s).strip(" |")


def passenger_status(vehicle, seat, injury):
    if seat.zfill(2) == "01":
        return "driver already handled"
    if not re.fullmatch(r"0?[1-9]|[1-9][0-9]", vehicle):
        return "review required: vehicle association unknown or nonmotorist"
    if seat.zfill(2) not in {f"{i:02}" for i in range(2, 13)}:
        return "review required: seating position unknown"
    if injury.zfill(2) == "05":
        return "no apparent injury"
    if injury.zfill(2) in {"01", "02", "03", "04"}:
        return "injured passenger"
    return "review required: injury evidence unreadable or unknown"


def parse_person(f, v):
    get = lambda key: f.get(key, {}).get("normalized", "")
    first, last, middle = get(f"v{v}_first"), get(f"v{v}_last"), get(f"v{v}_middle")
    if get(f"v{v}_given"):
        parts = get(f"v{v}_given").split()
        middle = parts.pop() if len(parts) > 1 and len(parts[-1].strip(".")) == 1 else ""
        first = " ".join(parts)
    if get(f"v{v}_name"):
        parts = get(f"v{v}_name").split()
        first = parts[0]
        last = parts[-1]
        middle = " ".join(parts[1:-1])
    cityzip = get(f"v{v}_cityzip")
    m = re.fullmatch(r"(.+?)[, .]+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)", cityzip)
    return {
        "first_name": first,
        "last_name": last,
        "middle": middle,
        "street_address": get(f"v{v}_street"),
        "mailing_city": m[1].strip(" ,.") if m else "",
        "state": m[2] if m else "",
        "zip_code": m[3] if m else "",
        "raw_cityzip": cityzip,
    }


def normalize(raw):
    codebook = json.loads(
        (Path(__file__).resolve().parents[1] / "data/njtr1-codes.json").read_text()
    )
    reports = []
    recipients = []
    review = []
    seen = {}
    drivers = []
    occupants = []
    for p in raw["pages"]:
        if p["render_sha256"] in seen:
            seen[p["render_sha256"]]["source_pages"].append(p["source_page"])
            continue
        f = p["fields"]
        get = lambda key: f.get(key, {}).get("normalized", "")
        report = {
            "id": f"p{p['source_page']:02d}",
            "first_page": p["source_page"] if f else None,
            "source_pages": [p["source_page"]],
            "case": get("case"),
            "department": get("department"),
            "municipality_code": get("municipality_code"),
            "date_raw": get("date"),
            "codes": {k: get(k) for k in ["118a", "118b", "119a", "119b"]},
            "issues": list(p["issues"])
            + ["Only first page supplied; continuation completeness unverified"],
        }
        # Public NJ codebook, bundled locally; never infer municipality from a person's address.
        muni = json.loads(
            (Path(__file__).resolve().parents[1] / "data/municipalities.json").read_text()
        )["codes"].get(get("municipality_code"), "")
        report["municipality"] = muni
        report["code_descriptions"] = {
            k: codebook["contributing"].get(
                v, "Not applicable" if re.fullmatch(r"[-—]+", v) else "Unreadable/unrecognized"
            )
            for k, v in report["codes"].items()
        }
        nums = re.findall(r"\d+", get("date"))
        date = ""
        try:
            if len(nums) == 3:
                date = datetime.strptime(" ".join(nums), "%m %d %y").date().isoformat()
            elif len("".join(nums)) == 6:
                date = datetime.strptime("".join(nums), "%m%d%y").date().isoformat()
        except ValueError:
            pass
        report["crash_date"] = date
        seen[p["render_sha256"]] = report
        reports.append(report)
        for v, box in [(1, "118"), (2, "119")]:
            codes = [get(box + "a"), get(box + "b")]
            extracted = parse_person(f, v)
            extracted.update(
                {
                    "id": f"{report['id']}-driver-{v}",
                    "report": report["id"],
                    "vehicle": get(f"vehicle{v}"),
                    "role": "driver"
                    if get(f"vehicle{v}")
                    else "unresolved driver/nonmotorist form entry",
                    "source_page": p["source_page"],
                    "codes": codes,
                    "crash_date": date,
                    "crash_municipality": muni,
                    "evidence_fields": [k for k in f if k.startswith(f"v{v}_")],
                }
            )
            drivers.append(extracted)
            extracted["disposition"] = (
                "No code 25 in this vehicle column"
                if all(re.fullmatch(r"\d{2}|[-—]+", c) for c in codes)
                else "Contributing-code evidence unresolved"
            )
            if "25" not in codes:
                if any(not re.fullmatch(r"\d{2}|[-—]+", c) for c in codes):
                    review.append(
                        {
                            "report": report["id"],
                            "vehicle": v,
                            "reason": "Missing/unreadable contributing code",
                        }
                    )
                continue
            person = parse_person(f, v)
            person.update(
                {
                    "id": f"{report['id']}-driver-{v}",
                    "report": report["id"],
                    "vehicle": get(f"vehicle{v}"),
                    "role": "driver",
                    "crash_date": date,
                    "crash_municipality": muni,
                    "first_page": p["source_page"],
                    "selection": f"{box} A/B = " + "/".join(codes),
                    "evidence_fields": [box + "a", box + "b", f"vehicle{v}"]
                    + [k for k in f if k.startswith(f"v{v}_")],
                    "support_pages": [p["source_page"]],
                }
            )
            problems = []
            injury_rows = [
                letter
                for letter in "ABCD"
                if get(f"{letter}_83").zfill(2) == person["vehicle"].zfill(2)
                and get(f"{letter}_84").zfill(2) == "01"
            ]
            if len(injury_rows) != 1:
                problems.append(
                    "Driver injury needs checking: missing or conflicting occupant association"
                )
            else:
                letter = injury_rows[0]
                injury = get(f"{letter}_86").zfill(2)
                person["injury"] = injury
                person["evidence_fields"] += [f"{letter}_{k}" for k in ("83", "84", "86")]
                person["selection"] += f"; occupant {letter}: driver, injury {injury}"
                if injury not in {"01", "02", "03", "04"}:
                    problems.append(
                        "No apparent driver injury"
                        if injury == "05"
                        else "Driver injury needs checking: unknown or unreadable"
                    )
            if not report["case"] or not report["department"]:
                problems.append("Missing report identity")
            if any(
                c not in ("25", "--", "---", "----", "—", "-", "") and re.search(r"\d", c)
                for c in codes
            ):
                problems.append("Conflicting contributing evidence")
            if person["vehicle"].zfill(2) != f"{v:02}":
                problems.append("Vehicle association unreadable or conflicts with form column")
            if any(not re.fullmatch(r"\d{2}|[-—]+", c) for c in codes):
                problems.append("Missing or unreadable contributing subfield")
            for k in [
                "first_name",
                "last_name",
                "street_address",
                "mailing_city",
                "state",
                "zip_code",
                "crash_date",
                "crash_municipality",
            ]:
                if not person[k]:
                    problems.append("Missing " + k)
            extracted["disposition"] = (
                "Held: " + "; ".join(problems)
                if problems
                else "Selected driver: recorded injury and no contributing action recorded (code 25)"
            )
            if problems:
                review.append({"candidate": person, "reason": "; ".join(problems)})
            else:
                recipients.append(person)
        for letter in "ABCD":
            vals = {k: get(f"{letter}_{k}") for k in ["83", "84", "86", "95"]}
            if not vals["95"] or not re.search("[A-Za-z]{3}", vals["95"]):
                continue
            match = re.fullmatch(
                r"([^,]+),\s*(.+?)[-\s]+(\d[^,]+),\s*(.+?),?\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
                vals["95"],
            )
            occupants.append(
                {
                    "id": f"{report['id']}-occupant-{letter}",
                    "report": report["id"],
                    "source_page": p["source_page"],
                    "occupant_row": letter,
                    "vehicle": vals["83"],
                    "seat": vals["84"],
                    "injury": vals["86"],
                    "seat_description": codebook["seat"].get(vals["84"].zfill(2), "Unresolved"),
                    "injury_description": codebook["injury"].get(vals["86"].zfill(2), "Unresolved"),
                    "raw_name_address": vals["95"],
                    "first_name": match[2].strip(" -") if match else "",
                    "last_name": match[1].strip() if match else "",
                    "street_address": match[3].strip() if match else "",
                    "mailing_city": match[4].strip(" ,") if match else "",
                    "state": match[5] if match else "",
                    "zip_code": match[6] if match else "",
                    "parse_issue": "" if match else "Name/address did not parse; raw text retained",
                }
            )
            seat = vals["84"].zfill(2)
            injury = vals["86"].zfill(2)
            role = (
                "driver"
                if seat == "01"
                else "passenger"
                if seat in {f"{i:02}" for i in range(2, 13)}
                else "unknown"
            )
            status = passenger_status(vals["83"], vals["84"], vals["86"])
            if role == "driver" and vals["83"].zfill(2) not in ("01", "02"):
                status = "review required: driver vehicle contributing-code page not supplied or supported"
                report["issues"].append(
                    f"Occupant {letter}: vehicle {vals['83']} contributing codes unavailable"
                )
            if status == "injured passenger":
                m = re.fullmatch(
                    r"([^,]+),\s*([A-Za-z .]+)-(\d[^,]+),\s*(.+?),?\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
                    vals["95"],
                )
                if m and date and muni:
                    names = m[2].strip().split()
                    person = {
                        "id": f"{report['id']}-occupant-{letter}",
                        "report": report["id"],
                        "first_name": names[0],
                        "middle": " ".join(names[1:]),
                        "last_name": m[1].strip(),
                        "street_address": m[3].strip(),
                        "mailing_city": m[4].strip(" ,"),
                        "state": m[5],
                        "zip_code": m[6],
                        "vehicle": vals["83"],
                        "role": "passenger",
                        "crash_date": date,
                        "crash_municipality": muni,
                        "first_page": p["source_page"],
                        "support_pages": [p["source_page"]],
                        "selection": f"Occupant {letter}: vehicle {vals['83']}, seat {seat}, injury {injury}",
                        "evidence_fields": [f"{letter}_{k}" for k in vals],
                    }
                    same_report_drivers = [parse_person(f, v) for v in (1, 2)]
                    if any(
                        (d["first_name"].casefold(), d["last_name"].casefold())
                        == (person["first_name"].casefold(), person["last_name"].casefold())
                        for d in same_report_drivers
                    ):
                        status = "review required: passenger name duplicates driver; conflicting seating evidence"
                    else:
                        recipients.append(person)
                        status = "included injured passenger"
                else:
                    status = "injured passenger candidate; name/address parsing requires review"
            review.append(
                {
                    "report": report["id"],
                    "occupant_row": letter,
                    "fields": vals,
                    "role": role,
                    "reason": status,
                    "source_page": p["source_page"],
                    "evidence_fields": [f"{letter}_{k}" for k in vals],
                }
            )
    # Same identity with different pixels is never silently deduplicated.
    for r in reports:
        peers = [
            x
            for x in reports
            if x is not r
            and (x["case"], x["department"], x["crash_date"])
            == (r["case"], r["department"], r["crash_date"])
        ]
        if peers:
            r["issues"].append("Different source version of same report; review before inclusion")
            held = [x for x in recipients if x["report"] == r["id"]]
            review.extend(
                {"candidate": x, "reason": "Materially different report version"} for x in held
            )
            recipients = [x for x in recipients if x["report"] != r["id"]]
    return {
        "source_pdf": raw["source_pdf"],
        "source_sha256": raw["source_sha256"],
        "reports": reports,
        "recipients": recipients,
        "review": review,
        "drivers": drivers,
        "occupants": occupants,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.pdf.suffix.lower() != ".pdf":
        ap.error("Only a PDF is accepted as extraction input")
    args.output.mkdir(parents=True, exist_ok=False)
    data = args.pdf.read_bytes()
    doc = fitz.open(stream=data, filetype="pdf")
    raw = {"source_pdf": str(args.pdf.resolve()), "source_sha256": digest(data), "pages": []}
    for i, p in enumerate(doc):
        print(f"Inspecting source page {i + 1}/{len(doc)}", flush=True)
        if os.environ.get("CRASH_ISOLATE_PAGES") == "1":
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("page_worker.py")),
                    str(args.pdf.resolve()),
                    str(i),
                    str(args.output.resolve()),
                ],
                check=True,
            )
            raw["pages"].append(
                json.loads((args.output / f"page-{i + 1:02}-result.json").read_text())
            )
        else:
            from anchored import inspect_page as inspect_anchored

            raw["pages"].append(inspect_anchored(p, i + 1, args.output))
    (args.output / "raw.json").write_text(json.dumps(raw, indent=2))
    normalized = normalize(raw)
    (args.output / "automatic.json").write_text(json.dumps(normalized, indent=2))
    print(f"Saved PDF-only extraction: {len(normalized['recipients'])} automatic recipients")


if __name__ == "__main__":
    main()
