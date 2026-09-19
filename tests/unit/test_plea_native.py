import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pymupdf
from app.extract import extract_calendar, text_table


class ExtractionTests(unittest.TestCase):
    def calendar(self, path, rotation=0):
        doc = pymupdf.open()
        page = doc.new_page(width=600, height=300)
        # Deliberately move the name column and place the table near the edge.
        xs = [8, 135, 290, 440, 590]
        ys = [60, 95, 140, 185]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        data = [
            ["Case Number", "Defendant Name", "Mun of Offense", "Offense"],
            ["S 2026 000001", "O'NEIL, Alex", "1217", "2C:20-11B(1)"],
            ["E26 000002", "EXAMPLE,\nSECOND A", "1217", "39:4-98 .24\n2C:18-3A\n2C:18-3A"],
        ]
        for r, row in enumerate(data):
            for c, value in enumerate(row):
                page.insert_text((xs[c] + 4, ys[r] + 14), value, fontsize=9)
        page.set_rotation(rotation)
        doc.save(path)
        doc.close()

    def test_native_columns_wraps_codes_and_rotated_proofs(self):
        for rotation in (0, 90):
            with self.subTest(rotation=rotation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.calendar(root / "source.pdf", rotation)
                with patch(
                    "app.extract.cell_ocr",
                    side_effect=AssertionError("Native text must bypass OCR"),
                ):
                    result = extract_calendar(root / "source.pdf", root / "out")
                self.assertEqual(len(result["rows"]), 2)
                first, second = result["rows"]
                self.assertEqual(first["name"], "O'NEIL, Alex")
                self.assertEqual(first["case_number"], "S 2026 000001")
                self.assertEqual(first["offenses"], ["2C:20-11B(1)"])
                self.assertEqual(second["name"], "EXAMPLE, SECOND A")
                self.assertEqual(second["offenses"], ["39:4-98 .24", "2C:18-3A", "2C:18-3A"])
                self.assertEqual(first["issues"], [])
                for row in result["rows"]:
                    pix = pymupdf.Pixmap(str(root / "out" / f"{row['id']}.png"))
                    self.assertGreater(pix.width, 50)
                    self.assertGreater(pix.height, 50)
                self.assertEqual(result["pages"][0]["extraction_method"], "pdf-text")

    def test_text_without_recognized_headers_uses_fallback(self):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((20, 30), "An unrelated document with selectable text")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(text_table(page, Path(tmp), 1))
        doc.close()

    def test_image_only_page_uses_fallback(self):
        doc = pymupdf.open()
        page = doc.new_page()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(text_table(page, Path(tmp), 1))
        doc.close()
