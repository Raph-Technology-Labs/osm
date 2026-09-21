"""Session report as PDF.

reportlab rather than a HTML-to-PDF converter: this document is a table and a
few summary lines, and platypus does that in-process with no headless browser
to install, run or keep patched on a machine that sits on a shop floor.

Landscape A4 -- the report is wide (identity, station, camera, then the result
detail) and a portrait page would either drop columns or shrink the type past
reading size.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

_HERE = os.path.dirname(os.path.abspath(__file__))

# The brand mark stamped bottom-right on every page. Tried in order: an env
# override (for a customer-specific build), the backend's own copy, then the
# frontend's source tree -- which works in this repo layout but not once the
# frontend is built and deployed separately, so the backend copy is the one
# to rely on. A missing file is not an error: the footer falls back to text,
# because a report failing to generate over a decorative asset would be absurd.
_LOGO_CANDIDATES = [
    os.getenv("OSM_REPORT_LOGO"),
    os.path.join(_HERE, "..", "assets", "raph_logo.png"),
    os.path.join(_HERE, "..", "..", "..", "frontend", "src", "assets",
                 "assets", "logo", "raph-logo.png"),
]


def _logo_path() -> str | None:
    for candidate in _LOGO_CANDIDATES:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


FOOTER_HEIGHT = 16 * mm

# Columns, and how wide each gets. Narrower than the CSV on purpose: the CSV
# is for filtering in a spreadsheet, the PDF is for reading and signing.
#
# No "pipeline" column: the detail cell already says what kind of result it is
# ("diameter_mm: 18.12mm ..." vs "Air_5044 x3"), so a column repeating the word
# measurement/defect on every row costs width and tells the reader nothing.
_COLUMNS = [
    ("Time", 26),
    ("Part #", 14),
    ("Station", 16),
    ("Camera", 16),
    ("Result detail", 92),
    ("Camera", 16),
    ("Station", 16),
    ("Rej.", 12),
]


def _detail(row: dict) -> str:
    """One readable cell per row -- the PDF's answer to the CSV's column split.

    A printed page has no filter box, so a reader wants the number in prose
    next to its limits, not spread across eight columns they must scan back to
    a header to identify.
    """
    if row.get("pipeline") == "measurement":
        unit = row.get("unit") or ""
        parts = [f"{row.get('measurement_name')}: {row.get('measured')}{unit}"]
        if row.get("nominal") is not None:
            parts.append(f"nom {row['nominal']}{unit}")
        lo, hi = row.get("lower_limit"), row.get("upper_limit")
        if lo is not None or hi is not None:
            parts.append(f"limits {lo}-{hi}{unit}")
        if row.get("ovality") is not None:
            parts.append(f"ovality {row['ovality']}{unit}")
        return " · ".join(parts)

    if row.get("pipeline") == "defect":
        if row.get("defect_label"):
            out = str(row["defect_label"])
            if row.get("detection_count"):
                out += f" ×{row['detection_count']}"
            if row.get("defect_confidence") is not None:
                out += f" ({row['defect_confidence']:.2f})"
            return out
        return "no defect above threshold"

    if row.get("pipeline") == "aggregation":
        return "final verdict"

    return ""


def _verdict(value) -> str:
    if value is True:
        return "OK"
    if value is False:
        return "NOK"
    return "—"


def _p(value, style) -> Paragraph:
    """Every data cell goes through here.

    reportlab parses Paragraph text as mini-XML, so a single '&' or '<' in a
    part name or a defect label aborts the entire document with a paraparser
    syntax error. Escaping at the one place all data enters is the only
    reliable guard.
    """
    return Paragraph(escape("" if value is None else str(value)), style)


def _draw_footer(canvas, doc):
    """Runs on every page -- the brand mark and the page number.

    Drawn on the canvas rather than flowed into the story: a flowable would
    appear once, after the last row. This has to appear on page 7 of 7 too.
    """
    canvas.saveState()
    width, _ = landscape(A4)

    canvas.setStrokeColor(colors.HexColor("#d7dce3"))
    canvas.setLineWidth(0.5)
    canvas.line(15 * mm, FOOTER_HEIGHT, width - 15 * mm, FOOTER_HEIGHT)

    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#7b8794"))
    canvas.drawString(15 * mm, FOOTER_HEIGHT - 9, f"Page {canvas.getPageNumber()}")

    right = width - 15 * mm
    logo = _logo_path()
    logo_drawn = False
    if logo:
        try:
            img = ImageReader(logo)
            iw, ih = img.getSize()
            h = 9 * mm
            w = h * (iw / ih)
            canvas.drawImage(
                img,
                right - w,
                FOOTER_HEIGHT - h - 1 * mm,
                width=w,
                height=h,
                mask="auto",
                preserveAspectRatio=True,
            )
            right -= w + 3 * mm
            logo_drawn = True
        except Exception:
            logo_drawn = False  # a bad asset must not fail the report

    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#7b8794"))
    label = "Powered by" if logo_drawn else "Powered by Raph Technology Labs"
    canvas.drawRightString(right, FOOTER_HEIGHT - 9, label)

    canvas.restoreState()


def build_session_pdf(rows: list[dict], analysis: dict, buffer) -> None:
    """Write the report into `buffer` (a BytesIO or file object)."""
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], fontSize=15, spaceAfter=2)
    sub = ParagraphStyle("s", parent=styles["Normal"], fontSize=8.5,
                         textColor=colors.HexColor("#5a6773"))
    h2 = ParagraphStyle("h", parent=styles["Heading2"], fontSize=10, spaceBefore=8,
                        spaceAfter=3)
    cell = ParagraphStyle("c", parent=styles["Normal"], fontSize=7.2, leading=9)

    doc = BaseDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=FOOTER_HEIGHT + 4 * mm,
        title="OSM session report",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="report", frames=[frame], onPage=_draw_footer)])

    first = rows[0] if rows else {}
    story = [
        Paragraph("Optical Sorting Machine — session report", title),
        Paragraph(
            f"Part <b>{escape(str(first.get('part_code') or '—'))}</b> "
            f"{escape(str(first.get('part_name') or ''))} &nbsp;·&nbsp; "
            f"session #{escape(str(first.get('session_id') or '—'))} &nbsp;·&nbsp; "
            f"generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            sub,
        ),
    ]

    stations = (analysis or {}).get("stations") or {}
    if stations:
        story += [Paragraph("Per station", h2)]
        data = [["Station", "OK", "NOK", "Rejected", "Pass rate"]]
        for sid, s in stations.items():
            # .get, not [] -- a station dict that predates a field must not
            # take the whole report down with a KeyError.
            ok, nok = s.get("ok", 0), s.get("nok", 0)
            tot = ok + nok
            data.append([
                sid, ok, nok, s.get("rejected", 0),
                f"{(ok / tot * 100):.1f}%" if tot else "—",
            ])
        t = Table(data, colWidths=[40 * mm, 20 * mm, 20 * mm, 22 * mm, 24 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dce3")),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story += [t]

    story += [Paragraph("Part detail", h2)]

    body = [[c[0] for c in _COLUMNS]]
    for r in rows:
        body.append([
            _p(str(r.get("fired_at") or "")[:19], cell),
            _p(r.get("ring_part_id"), cell),
            _p(r.get("station_id"), cell),
            _p(r.get("camera_id"), cell),
            _p(_detail(r), cell),
            _p(_verdict(r.get("camera_passed")), cell),
            _p(_verdict(r.get("station_passed")), cell),
            _p("yes" if r.get("rejected") else "", cell),
        ])

    table = Table(body, colWidths=[c[1] * mm for c in _COLUMNS], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.6),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dde2e8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    story += [table, Spacer(1, 4)]

    doc.build(story)