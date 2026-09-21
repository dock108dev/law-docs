#!/usr/bin/env python3
"""Regenerate Excel and per-recipient proofs together from one ordered list."""

import argparse, hashlib, json, subprocess, os
import uuid
from pathlib import Path
from source_paths import source_path
from safe_paths import contained
import pymupdf as fitz


def export_bundle(model, raw, out):
    target = contained(out)
    if target.exists():
        raise FileExistsError(f"Choose a new output directory: {target}")
    out = contained(target.with_name(target.name + ".building-" + uuid.uuid4().hex[:8]))
    out.mkdir(parents=True, exist_ok=False)
    data = source_path(model["source_pdf"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == model["source_sha256"], "Source PDF changed"
    source = fitz.open(stream=data, filetype="pdf")
    proof = fitz.open()
    manifest = []
    for i, r in enumerate(model["recipients"], 1):
        report = next(x for x in model["reports"] if x["id"] == r["report"])
        assert r["first_page"] == report["first_page"]
        p = source[r["first_page"] - 1]
        new = proof.new_page(width=p.rect.width, height=p.rect.height + 48)
        new.show_pdf_page(
            fitz.Rect(0, 48, p.rect.width, p.rect.height + 48), source, r["first_page"] - 1
        )
        name = f"{r['first_name']} {r['last_name']}"
        label = f"Recipient row {i} | {name}"
        new.insert_text((14, 17), label, fontsize=10)
        new.insert_text(
            (14, 33),
            f"Report {report['case']} | Source page {r['first_page']} | Proof page {i}",
            fontsize=9,
        )
        fields = raw["pages"][r["first_page"] - 1]["fields"]
        highlights = []
        for key in r["evidence_fields"]:
            field = fields[key]
            rect = fitz.Rect(field["rect"]) + fitz.Rect(0, 48, 0, 48)
            new.draw_rect(rect, color=(1, 0.65, 0), fill=(1, 0.9, 0), fill_opacity=0.16, width=0.6)
            highlights.append({"field": key, "rect": list(rect), "source_rect": field["rect"]})
        manifest.append(
            {
                "recipient_row": i,
                "recipient_id": r["id"],
                "name": name,
                "report": report["case"],
                "source_page": r["first_page"],
                "proof_page": i,
                "highlights": highlights,
                "label": label,
            }
        )
    if not len(proof):
        raise ValueError("No confirmed recipients; inspect review information")
    proof.save(contained(out / "recipient-proofs.pdf", out))
    proof.close()
    contained(out / "final.json", out).write_text(json.dumps(model, indent=2))
    contained(out / "proof-manifest.json", out).write_text(json.dumps(manifest, indent=2))
    from export_workbook_portable import export_workbook

    export_workbook(model, out)
    # Reopen the saved proof; labels, source copies, counts and rectangles are checked after serialization.
    with fitz.open(contained(out / "recipient-proofs.pdf", out)) as saved:
        assert len(saved) == len(model["recipients"]) == len(manifest)
        for p, m in zip(saved, manifest):
            assert m["label"] in p.get_text()
            assert len(p.get_drawings()) >= len(m["highlights"])
            p.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).save(
                contained(out / f"proof-{m['proof_page']:02d}.png", out)
            )
    contained(out / "COMPLETE.json", out).write_text(
        json.dumps(
            {
                "recipient_count": len(manifest),
                "proof_pages": len(manifest),
                "source_sha256": model["source_sha256"],
                "excel_sha256": hashlib.sha256(
                    contained(out / "recipients.xlsx", out).read_bytes()
                ).hexdigest(),
                "proof_sha256": hashlib.sha256(
                    contained(out / "recipient-proofs.pdf", out).read_bytes()
                ).hexdigest(),
            },
            indent=2,
        )
    )
    contained(out).rename(contained(target))
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", type=Path)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    export_bundle(json.loads(a.model.read_text()), json.loads(a.raw.read_text()), a.output)


if __name__ == "__main__":
    main()
