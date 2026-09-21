"""Deterministic public-safe documents: invented people and case identifiers only."""

from pathlib import Path
import pymupdf as fitz


def calendar(path, scanned=False, sideways=False):
    document = fitz.open()
    page = document.new_page(width=612, height=500)
    xs = [25, 225, 355, 440, 587]
    ys = [60, 95, 150, 205]
    for x in xs:
        page.draw_line((x, 60), (x, 205), width=1)
    for y in ys:
        page.draw_line((25, y), (587, y), width=1)
    rows = [
        ["Defendant Name", "Case Number", "Municipality", "Offense"],
        ["EXAMPLE, ALEX", "S 2026 000001", "1821", "39:4-98"],
        ["SAMPLE, CASEY", "S 2026 000002", "1821", "39:4-97"],
    ]
    for i, row in enumerate(rows):
        for j, text in enumerate(row):
            page.insert_text((xs[j] + 7, ys[i] + 21), text, fontsize=9)
    if scanned:
        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
        raster = fitz.open()
        rp = raster.new_page(width=612, height=500)
        rp.insert_image(rp.rect, stream=pix.tobytes("png"))
        document.close()
        document = raster
        page = rp
    if sideways:
        page.set_rotation(90)
    document.save(path)
    document.close()


def crash(path):
    d = fitz.open()
    p = d.new_page(width=612, height=792)

    def text(x, y, value, size=8):
        p.insert_text((x * 612, y * 792), value, fontsize=size)

    text(0.74, 0.04, "NJTR-1 P1", 11)
    text(0.1, 0.025, "1 Case Number TEST-001")
    text(0.1, 0.055, "2 Police Dept")
    text(0.1, 0.077, "Example Police")
    text(0.1, 0.105, "3 Station")
    text(0.31, 0.105, "Date of Crash")
    text(0.47, 0.105, "Day")
    text(0.57, 0.105, "7 Municipality")
    text(0.32, 0.14, "08 18 26", 12)
    text(0.58, 0.14, "1821", 12)
    for v, left in [(1, 0.1), (2, 0.5)]:
        text(left, 0.18, "23 Vehicle" if v == 1 else "53 Vehicle")
        text(left, 0.205, str(v), 10)
        text(left, 0.23, "26 Driver First Name" if v == 1 else "56 Driver First Name")
        text(left + 0.18, 0.23, "Last Name")
        text(left, 0.267, "Alex Q" if v == 1 else "Blair")
        text(left + 0.18, 0.267, "Example" if v == 1 else "Demo")
        text(left, 0.295, "27 Number Street" if v == 1 else "57 Number Street")
        text(left, 0.327, f"{v}0 Sample St")
        text(left, 0.35, "28 City" if v == 1 else "58 City")
        text(left, 0.377, "Watchung, NJ 07069")
        text(left, 0.405, "30 Eyes" if v == 1 else "60 Eyes")
    for i, (label, code) in enumerate(
        [
            ("118a", "25"),
            ("118b", "--"),
            ("119a", "02"),
            ("119b", "--"),
            ("120a", "01"),
            ("120b", "--"),
        ]
    ):
        top = 0.45 + i * 0.043
        text(0.89, top, label, 4)
        text(0.911, top + 0.024, code, 10)
    for key, x in [
        (83, 0.14),
        (84, 0.172),
        (85, 0.204),
        (86, 0.236),
        (87, 0.268),
        (94, 0.50),
        (95, 0.535),
    ]:
        text(x, 0.735, str(key), 7)
    text(0.565, 0.735, "Names Address", 7)
    for y in [0.765, 0.795, 0.825, 0.855, 0.885]:
        p.draw_line((0.12 * 612, y * 792), (0.89 * 612, y * 792), width=1)
    for y, vehicle, seat, injury, name in [
        (0.787, "1", "01", "03", "Example, Alex-10 Sample St, Watchung, NJ 07069"),
        (0.817, "2", "03", "03", "Sample, Casey-20 Sample St, Watchung, NJ 07069"),
    ]:
        for x, val in [(0.14, vehicle), (0.172, seat), (0.236, injury)]:
            text(x, y, val, 8)
        text(0.56, y, name, 6)
    d.save(path)
    d.close()


if __name__ == "__main__":
    import sys

    dest = Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    calendar(dest / "calendar.pdf")
    calendar(dest / "calendar-scan.pdf", True, True)
    crash(dest / "crash.pdf")
