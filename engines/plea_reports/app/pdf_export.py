"""Group reviewed printed names across the calendar; four charges per sheet."""

from io import BytesIO
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject, ArrayObject, FloatObject
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "docs/TEMPLATE - Plea Agreement Slips.pdf"


def row_errors(row):
    errors = []
    for key, label in [("name", "Name"), ("case_number", "Case number")]:
        if not str(row.get(key, "")).strip():
            errors.append(f"{label} is blank")
    charges = row.get("offenses", [])
    if not charges or any(not str(c).strip() for c in charges):
        errors.append("Offense is blank")
    return errors


def person_key(row):
    # No fuzzy identity inference. Unreadable names never merge.
    name = " ".join(row.get("name", "").split()).casefold()
    return ("name", name) if name else ("unresolved", row["id"])


def build_slips(rows):
    groups = {}
    for row in rows:
        if row.get("excluded"):
            continue
        key = person_key(row)
        group = groups.setdefault(key, {"name": row.get("name", ""), "rows": [], "charges": []})
        group["rows"].append(row)
        # An unreadable offense still occupies a visible source-linked line.
        for offense in row.get("offenses", []) or [""]:
            group["charges"].append(
                {"offense": offense, "case_number": row.get("case_number", ""), "row": row}
            )
    slips = []
    for group in groups.values():
        parts = (len(group["charges"]) + 3) // 4
        for start in range(0, len(group["charges"]), 4):
            charges = group["charges"][start : start + 4]
            slips.append(
                {
                    "name": group["name"],
                    "charges": charges,
                    "part": start // 4 + 1,
                    "parts": parts,
                    "rows": list({c["row"]["id"]: c["row"] for c in charges}.values()),
                }
            )
    return slips


def make_pdf(rows, output, draft=True, automated=False):
    selected = [r for r in rows if not r.get("excluded")]
    if not selected:
        raise ValueError("No included rows to export.")
    for row in selected:
        if not draft and not automated and (row_errors(row) or not row.get("reviewed")):
            raise ValueError(f"{row['id']}: review and complete required fields first.")
    slips = build_slips(selected)
    writer = PdfWriter()
    template_bytes = TEMPLATE.read_bytes()
    for index, slip in enumerate(slips, 1):
        row = slip["rows"][0]
        errors = list(dict.fromkeys(e for source in slip["rows"] for e in row_errors(source)))
        reader = PdfReader(BytesIO(template_bytes))
        # Keep only page 2 widgets in the canonical field tree. Page 1 fields
        # otherwise survive invisibly when the template uses a top-level parent.
        widgets = ArrayObject(
            [
                ref
                for ref in reader.pages[1].get("/Annots", [])
                if ref.get_object().get("/Subtype") == "/Widget"
            ]
        )
        reader.trailer["/Root"]["/AcroForm"][NameObject("/Fields")] = widgets
        for ref in widgets:
            obj = ref.get_object()
            obj[NameObject("/V")] = TextStringObject("")
            obj.pop("/AA", None)
            obj.pop("/A", None)
        prefix = f"slip{index:04}"
        reader.add_form_topname(prefix)
        writer.append(reader, pages=[1])
        page = writer.pages[-1]
        values = {}
        for ref in page.get("/Annots", []):
            widget = ref.get_object()
            if widget.get("/Subtype") != "/Widget":
                continue
            short = widget.get("/T")
            value = ""
            if short == "defNameFull4":
                value = slip["name"]
            for line, charge in enumerate(slip["charges"], 1):
                if short == f"{line}complaintNo4":
                    value = charge["case_number"]
                if short == f"{line}chgOrig4":
                    value = charge["offense"]
            x1, y1, x2, y2 = [float(x) for x in widget["/Rect"]]
            if short == "defNameFull4":
                widget[NameObject("/Rect")] = ArrayObject(
                    [FloatObject(x1), FloatObject(y1 + 3), FloatObject(x2), FloatObject(y2 + 3)]
                )
            available = x2 - x1 - 5
            font = 10
            if value:
                width = stringWidth(value, "Helvetica", font)
                font = min(font, font * available / max(width, 1))
                if font < 7:
                    raise ValueError(
                        f"{row['id']}: {short} is too long to print legibly; shorten only after source review."
                    )
            widget[NameObject("/DA")] = TextStringObject(f"/Helv {font:.2f} Tf 0 g")
            widget.pop("/I", None)
            values[f"{prefix}.{short}"] = value
        writer.update_page_form_field_values(page, values, auto_regenerate=False)
        # Provenance and draft status sit in unused space, outside the unchanged slip.
        overlay = BytesIO()
        canvas = Canvas(overlay, pagesize=(612, 792))
        canvas.setFillColorRGB(0.35, 0.38, 0.40)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(
            30,
            128,
            f"Slip {index} of {len(slips)} | Person sheet {slip['part']} of {slip['parts']}",
        )
        for line, charge in enumerate(slip["charges"], 1):
            source = charge["row"]
            canvas.drawString(
                30,
                128 - line * 12,
                f"Charge line {line}: source calendar page {source['source_page']}, row {source['source_row']}",
            )
        if automated:
            canvas.drawString(
                30,
                56,
                "Source references and extraction notes are in the accompanying proof sheet.",
            )
        elif draft:
            canvas.setFillColorRGB(0.65, 0.29, 0.08)
            canvas.drawString(
                30,
                56,
                "REVIEW DRAFT - Verify printed source values and person grouping before use.",
            )
            if errors:
                canvas.drawString(30, 43, "Incomplete: " + "; ".join(errors)[:105])
        canvas.save()
        page.merge_page(PdfReader(BytesIO(overlay.getvalue())).pages[0])
    writer.add_metadata(
        {
            "/Title": "Plea slips"
            if automated
            else ("Plea Reports - Review draft" if draft else "Plea Reports - Reviewed slips"),
            "/Producer": "Plea Reports local app",
        }
    )
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    with output.open("wb") as handle:
        writer.write(handle)
    return output
