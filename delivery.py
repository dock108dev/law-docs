"""Generate downloadable results and source-linked proofs without review gates."""

import copy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import textwrap
import zipfile
import pymupdf as fitz

ROOT = Path(__file__).resolve().parent


def text_pages(doc, title, lines):
    page = None
    y = 800
    for line in lines:
        for part in textwrap.wrap(str(line), width=95, break_long_words=True) or [""]:
            if y > 735:
                page = doc.new_page(width=612, height=792)
                page.insert_text((36, 42), title, fontsize=17, color=(0.1, 0.3, 0.25))
                y = 75
            page.insert_text((36, y), part, fontsize=10)
            y += 15


def plea(directory, out):
    sys.path.insert(0, str(ROOT / "engines/plea_reports"))
    from app.pdf_export import make_pdf, build_slips, row_errors

    data = json.loads((directory / "result.json").read_text())
    if data["status"] != "ready":
        raise ValueError("Processing has not finished yet.")
    rows = copy.deepcopy(data["rows"])
    slips = build_slips(rows)
    if slips:
        make_pdf(rows, out / "plea-slips.pdf", automated=True)
    proof = fitz.open()
    lines = [
        f"Source: {data.get('filename', 'Calendar PDF')}",
        f"{len(data['pages'])} source pages | {len(rows)} detected rows | {len(slips)} output slips",
        "Each proof page lists the output values and shows the printed source for that slip.",
        "Automatically extracted. Source images support checking; they do not certify OCR accuracy.",
        "Blank fields remain blank. Notes below and beside each source show detected uncertainties.",
        "Grouping uses matching printed names across the calendar. Each charge keeps its case number.",
        "",
    ]
    if not slips:
        lines.append("NO SLIPS GENERATED: no included calendar rows were detected.")
    for page in data["pages"]:
        lines.append(
            f"Source page {page['number']}: {sum(r['source_page'] == page['number'] for r in rows)} detected rows."
        )
        lines.extend("  " + issue for issue in page.get("issues", []))
    excluded = [r for r in rows if r.get("excluded")]
    if excluded:
        lines.append("Previously excluded rows (not in output):")
        lines.extend(
            f"Page {r['source_page']}, row {r['source_row']}: {r.get('name', '')} - {r.get('exclusion_reason', '')}"
            for r in excluded
        )
    text_pages(proof, "Plea slips - proof sheet", lines)
    mapping = []
    for index, slip in enumerate(slips, 1):
        page = proof.new_page(width=612, height=792)
        page.insert_text(
            (36, 38),
            f"Slip {index} of {len(slips)} - source proof",
            fontsize=17,
            color=(0.1, 0.3, 0.25),
        )
        page.insert_textbox(
            fitz.Rect(36, 51, 576, 91), slip["name"] or "[Name unreadable]", fontsize=12
        )
        for line, charge in enumerate(slip["charges"], 1):
            row = charge["row"]
            top = 95 + (line - 1) * 164
            label = f"Line {line} | Source page {row['source_page']}, row {row['source_row']}"
            page.insert_text((36, top), label, fontsize=10)
            values = f"Case: {charge['case_number'] or '[blank]'} | Offense: {charge['offense'] or '[blank]'}"
            if page.insert_textbox(fitz.Rect(36, top + 7, 576, top + 41), values, fontsize=10) < 0:
                raise ValueError("A source value is too long for the proof sheet.")
            crop = directory / (f"{row['id']}.png")
            if crop.exists():
                page.insert_image(
                    fitz.Rect(36, top + 43, 576, top + 100),
                    filename=str(crop),
                    keep_proportion=True,
                )
            else:
                full = directory / f"page-{row['source_page']}.png"
                if full.exists():
                    page.insert_image(
                        fitz.Rect(36, top + 43, 576, top + 100),
                        filename=str(full),
                        keep_proportion=True,
                    )
                else:
                    page.insert_text(
                        (36, top + 65),
                        "Source image unavailable; see original-source.pdf.",
                        fontsize=10,
                    )
            notes = list(dict.fromkeys(row_errors(row) + row.get("issues", [])))
            note = "; ".join(notes) if notes else "No missing required fields detected."
            # Long notes continue on their own pages, never disappear through clipping.
            if (
                page.insert_textbox(
                    fitz.Rect(36, top + 105, 576, top + 155),
                    note,
                    fontsize=9,
                    color=(0.5, 0.25, 0.1),
                )
                < 0
            ):
                page.insert_text(
                    (36, top + 119),
                    "See detailed notes at the end of this proof sheet.",
                    fontsize=9,
                )
            mapping.append(
                {
                    "slip": index,
                    "line": line,
                    "row_id": row["id"],
                    "source_page": row["source_page"],
                    "source_row": row["source_row"],
                    "name": slip["name"],
                    "case_number": charge["case_number"],
                    "offense": charge["offense"],
                    "notes": notes,
                }
            )
        page.insert_text(
            (36, 774), "Output values above; original printed source below each charge.", fontsize=8
        )
    notes = [
        f"Slip {m['slip']}, line {m['line']}: " + "; ".join(m["notes"])
        for m in mapping
        if m["notes"]
    ]
    if notes:
        text_pages(proof, "Detailed source notes", notes)
    proof.save(out / "proof-sheet.pdf")
    proof.close()
    (out / "source-map.json").write_text(json.dumps(mapping, indent=2))
    if (directory / "source.pdf").exists():
        (out / "original-source.pdf").write_bytes((directory / "source.pdf").read_bytes())


def crash(directory, out):
    sys.path.insert(0, str(ROOT / "engines/crash_report/scripts"))
    import review_app as engine
    from export import export_bundle
    from verify_delivery import verify
    from extract import normalize
    from households import group_households, export_household_pages, verify_household_workbook

    if engine.read(directory / "batch.json")["status"] != "ready":
        raise ValueError("Processing has not finished yet.")
    raw = engine.read(directory / "extraction/raw.json")
    # Re-evaluate retained readings with current rules, without changing originals.
    model = normalize(raw)
    decisions = engine.read(directory / "decisions.json")
    people = {p["id"]: p for p in engine.candidates(model)}
    recipients = []
    omitted = []
    for ident in decisions["order"]:
        p = people[ident]
        decision = decisions["people"][ident]
        if decision["status"] == "excluded" or not (
            p["eligible"] or decision["status"] == "approved"
        ):
            omitted.append(
                f"{p.get('first_name', '')} {p.get('last_name', '')} (source page {p['first_page']}): "
                + (
                    "Previously excluded. " + decision.get("reason", "")
                    if decision["status"] == "excluded"
                    else p["selection"]
                )
            )
            continue
        p.update(decision["values"])
        p["manual_exception"] = not p["eligible"] and decision["status"] == "approved"
        if p["manual_exception"]:
            p["exception_reason"] = (
                decision.get("reason")
                or "Previously approved inclusion outside current automatic rules"
            )
            p["selection"] = "Manual inclusion: " + p["exception_reason"] + "; " + p["selection"]
        recipients.append(p)
    model["recipients"] = recipients
    model["households"] = group_households(recipients)
    model["source_pdf"] = str(directory / "source.pdf")
    model["correction_status"] = (
        "Automatic download; existing saved corrections retained. See proof sheet."
    )
    proof = fitz.open()
    lines = [
        f"{len(model['households'])} households | {len(recipients)} included people | {len(omitted)} entries not included",
        "Use the Household mailings sheet: one mailing per full address, including unit.",
        "Each household PDF contains the original first page of each distinct crash, once.",
        "Individual recipient rows remain supporting records, not separate mailings.",
        "Driver selection requires injury and no contributing action recorded (code 25).",
        "Injured passengers are considered independently of their driver. Unknown evidence is held.",
        "Letters and brochures are not included; add your mailing materials to the report pages.",
        "Automatically selected using the extraction rules, with existing saved corrections and exclusions retained.",
        "Source highlights support checking; they do not certify OCR accuracy.",
        "",
    ]
    if recipients:
        bundle = out / "bundle"
        export_bundle(model, raw, bundle)
        (bundle / "verification.json").write_text(json.dumps(verify(bundle, raw), indent=2))
        for name in ("recipients.xlsx", "verification.json"):
            (out / name).write_bytes((bundle / name).read_bytes())
        mapping = export_household_pages(model, out)
        verification = json.loads((out / "verification.json").read_text())
        verification["household_output"] = verify_household_workbook(model, out, mapping)
        (out / "verification.json").write_text(json.dumps(verification, indent=2))
        (out / "household-manifest.json").write_text(
            json.dumps({"households": model["households"], "report_pages": mapping}, indent=2)
        )
        for group in model["households"]:
            lines.append(
                f"{group['id']}: {group['names']} | {group['street_address']}, {group['mailing_city']} {group['state']} {group['zip_code']}"
            )
            lines.extend(group["notes"])
    else:
        lines.append(
            "NO RECIPIENT WORKBOOK GENERATED: no entries meet the extraction rules or prior explicit inclusion."
        )
    lines.append("Source coverage:")
    for report in model["reports"]:
        lines.append(
            "Pages "
            + str(report.get("source_pages", []))
            + ": "
            + "; ".join(report.get("issues", []))
        )
    lines.append("Entries not included:")
    lines.extend(omitted)
    text_pages(proof, "Crash reports - proof sheet", lines)
    if recipients:
        with fitz.open(out / "household-report-pages.pdf") as pages:
            proof.insert_pdf(pages)
    proof.save(out / "proof-sheet.pdf")
    proof.close()


def generate(kind, ident, out):
    if not (re.fullmatch("[a-f0-9]{32}", ident) or kind == "plea" and ident == "sample"):
        raise ValueError("Unknown file.")
    folder = ROOT / "engines" / ("crash_report" if kind == "crash" else "plea_reports") / "data"
    directory = (
        Path(os.environ.get("CRASH_BATCHES", folder / "batches"))
        if kind == "crash"
        else Path(os.environ.get("PLEA_DATA", folder))
    ) / ident
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (crash if kind == "crash" else plea)(directory, out)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    with zipfile.ZipFile(out / "results.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for p in out.iterdir():
            if p.is_file() and p.name != "results.zip":
                z.write(
                    p,
                    p.name
                    if p.name.startswith("household-") and p.suffix == ".pdf"
                    else f"{p.stem}-{stamp}{p.suffix}",
                )
    return out / "results.zip"


if __name__ == "__main__":
    try:
        generate(*sys.argv[1:])
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
