"""Draw one conceptual, horizontal EV recommendation flowchart.

Run: .venv/bin/python docs/flowcharts/build_single_flowchart.py
SVG is the editable source; PNG and PDF show the same single figure.
"""

from pathlib import Path
from html import escape
import hashlib
import json
import xml.etree.ElementTree as ET

import cairo
import gi
gi.require_version("Rsvg", "2.0")
from gi.repository import Rsvg
from PIL import Image

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
W, H = 1920, 900
STEM = "EV_RECOMMENDATION_HORIZONTAL"
INK = "#172B44"
BLUE = "#3067AF"
GREEN = "#238270"
PURPLE = "#7654A6"
SLATE = "#76859B"
parts = []


def text(x, y, value, size=18, color=INK, weight=400, anchor="middle"):
    parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
                 f'font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>')


def lines(x, y, values, size=17, gap=25, color=INK, weight=400, anchor="middle"):
    for i, value in enumerate(values):
        text(x, y + i * gap, value, size, color, weight, anchor)


def rect(x, y, w, h, fill, stroke="none", radius=16, width=1.6, dash=""):
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="{width}"{extra}/>')


def arrow(path, color=SLATE, dashed=False, width=2.3):
    marker = {SLATE: "slate", GREEN: "green", PURPLE: "purple", BLUE: "blue"}[color]
    extra = ' stroke-dasharray="7 6"' if dashed else ""
    parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}" '
                 f'stroke-linecap="round" stroke-linejoin="round" marker-end="url(#{marker})"{extra}/>')


def icon(name, x, y, color=BLUE, size=44):
    parts.append(f'<use href="#{name}" x="{x-size/2}" y="{y}" width="{size}" '
                 f'height="{size}" color="{color}"/>')


def card(x, w, symbol, title, color=BLUE, fill="#EFF5FE", subtitle=""):
    rect(x, 505, w, 148, fill, color)
    icon(symbol, x + w / 2, 522, color)
    lines(x + w / 2, 592, title, 18, 26, color, 700)
    if subtitle:
        text(x + w / 2, 639, subtitle, 12, "#5B6C83")


def local_box(x, y, w, h, labels, dashed=False):
    rect(x, y, w, h, "#FFFFFF", "#90BFAF", radius=12, dash="6 5" if dashed else "")
    lines(x + w / 2, y + h / 2 - (len(labels)-1)*11 + 6,
          labels, 16, 22, GREEN, 600)


def main():
    prior = json.loads((OUT / "manifest.json").read_text())
    hashes = {src: hashlib.sha256((ROOT / src).read_bytes()).hexdigest()
              for src in prior["source_sha256"]}
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
                 f'viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">')
    parts.append('<title id="title">Khuyến nghị xe đến trạm sạc dựa trên quan sát phân tán</title>')
    parts.append('<desc id="desc">Một flowchart nằm ngang: xe cần sạc, lọc trạm có thể đến, '
                 'dự báo tại từng trạm, Pareto–Minimax, khuyến nghị, xe tự quyết định, di chuyển '
                 'và đến trạm sạc. Trạng thái vật lý và lịch sử xe thực sự đến cung cấp dữ liệu '
                 'cho dự báo. Hiệu chỉnh học từ trạm lân cận là tùy chọn. Xe có thể chưa chọn '
                 'và chờ khuyến nghị sau. Khuyến nghị không giữ chỗ.</desc>')
    parts.append('<defs>')
    for name, color in (("slate", SLATE), ("green", GREEN), ("purple", PURPLE), ("blue", BLUE)):
        parts.append(f'<marker id="{name}" viewBox="0 0 10 10" refX="9" refY="5" '
                     f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                     f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>')
    # Simple vector icons: all labels remain editable text in the SVG.
    parts.append('<symbol id="car" viewBox="0 0 48 48"><g fill="none" stroke="currentColor" stroke-width="2.7" stroke-linejoin="round"><path d="M7 27 L12 16 H32 L39 27 V36 H7 Z M9 27 H38 M23 17 V27"/><circle cx="14" cy="36" r="4" fill="white"/><circle cx="33" cy="36" r="4" fill="white"/></g></symbol>')
    parts.append('<symbol id="map" viewBox="0 0 48 48"><g fill="none" stroke="currentColor" stroke-width="2.7" stroke-linejoin="round"><path d="M5 13 L17 8 L31 14 L43 9 V35 L31 40 L17 34 L5 39 Z M17 8 V34 M31 14 V40 M19 23 L24 28 L34 18"/></g></symbol>')
    parts.append('<symbol id="clock" viewBox="0 0 48 48"><g fill="none" stroke="currentColor" stroke-width="2.7" stroke-linecap="round"><circle cx="24" cy="24" r="18"/><path d="M24 12 V24 L33 29"/></g></symbol>')
    parts.append('<symbol id="balance" viewBox="0 0 48 48"><g fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round"><path d="M24 8 V39 M13 40 H35 M9 12 H39 M11 13 L4 28 H18 Z M37 13 L30 28 H44 Z"/><circle cx="24" cy="10" r="3" fill="white"/></g></symbol>')
    parts.append('<symbol id="pin" viewBox="0 0 48 48"><g fill="none" stroke="currentColor" stroke-width="2.7"><path d="M24 43 C20 35 9 25 9 18 A15 15 0 0 1 39 18 C39 25 28 35 24 43 Z"/><circle cx="24" cy="18" r="5"/></g></symbol>')
    parts.append('<symbol id="person" viewBox="0 0 48 48"><g fill="none" stroke="currentColor" stroke-width="2.7" stroke-linecap="round"><circle cx="24" cy="14" r="7"/><path d="M11 40 V34 A13 13 0 0 1 37 34 V40"/></g></symbol>')
    parts.append('<symbol id="travel" viewBox="0 0 48 48"><g fill="none" stroke="currentColor" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 24 L42 6 L27 42 L22 28 Z M22 28 L42 6"/></g></symbol>')
    parts.append('<symbol id="charger" viewBox="0 0 48 48"><g fill="none" stroke="currentColor" stroke-width="2.7" stroke-linejoin="round"><rect x="10" y="6" width="24" height="36" rx="3"/><path d="M34 13 H39 V33 A3 3 0 0 1 33 33 M24 17 L17 27 H26 L20 36 M15 12 H29"/></g></symbol>')
    parts.append('</defs><g font-family="DejaVu Sans, sans-serif">')
    rect(0, 0, W, H, "#FFFFFF", radius=0)
    text(52, 62, "KHUYẾN NGHỊ TRẠM SẠC PHÂN TÁN", 31, INK, 700, "start")
    text(52, 99, "Quan sát tại trạm • Pareto–Minimax • Xe tự quyết định", 19,
         "#5B6C83", anchor="start")

    # The station-owned predictor is visible as a mechanism, not a generic box.
    rect(448, 137, 650, 343, "#F3FAF7", "#9BC9B6", radius=20, dash="8 6")
    text(470, 166, "MỖI TRẠM TỰ DỰ BÁO", 15, GREEN, 700, "start")
    local_box(466, 195, 172, 68, ["Cổng sạc", "Hàng đợi"])
    local_box(671, 195, 180, 68, ["Lịch sử", "xe thực sự đến"])
    local_box(895, 195, 180, 68, ["Dự báo", "trạm lân cận"], dashed=True)
    local_box(671, 298, 180, 60, ["Dự báo tải"])
    local_box(895, 298, 180, 60, ["Hiệu chỉnh học"], dashed=True)
    text(987, 184, "TÙY CHỌN", 11, "#697F75", 700)
    rect(671, 387, 180, 80, "#FFFFFF", "#90BFAF", radius=12)
    text(761, 417, "Replay lịch sử", 16, GREEN, 600)
    text(761, 440, "Kiểm tra độ đại diện", 12, "#557968")
    arrow("M761 263 V294", GREEN)
    arrow("M985 263 V294", GREEN, dashed=True)
    arrow("M851 328 H891", GREEN, dashed=True)
    arrow("M761 358 V383", GREEN)
    arrow("M985 358 V371 Q985 378 978 378 H819 Q813 378 813 384", GREEN, dashed=True)
    arrow("M552 263 V501", GREEN)
    arrow("M761 467 V487 Q761 493 755 493 H655 Q648 493 648 501", GREEN)
    text(502, 405, "Fallback", 13, GREEN)
    lines(502, 427, ["khi replay", "không phù hợp"], 11, 18, "#617D70")
    arrow("M671 427 H570 Q552 427 552 443", GREEN, dashed=True)

    # Single left-to-right flow; only words needed to identify each stage.
    card(52, 160, "car", ["Xe yêu cầu", "sạc"])
    card(247, 190, "map", ["Lọc trạm", "khả thi"])
    card(470, 260, "clock", ["Dự báo chờ", "khi xe đến"], GREEN, "#E8F5EF")
    card(772, 260, "balance", ["Lọc Pareto", "Chọn Minimax"], PURPLE, "#F2EDFA")
    card(1073, 178, "pin", ["Khuyến nghị", "trạm"], subtitle="Không giữ chỗ")
    parts.append('<polygon points="1393,502 1501,577 1393,652 1285,577" '
                 'fill="#EAF2FF" stroke="#3067AF" stroke-width="2"/>')
    icon("person", 1393, 519, BLUE, 34)
    lines(1393, 582, ["Xe tự", "quyết định"], 17, 24, BLUE, 700)
    card(1535, 160, "travel", ["Di chuyển"])
    card(1730, 162, "charger", ["Đến trạm", "Chờ / sạc"], GREEN, "#E8F5EF")
    for path in ("M212 577 H243", "M437 577 H466", "M730 577 H768", "M1032 577 H1069",
                 "M1251 577 H1281", "M1501 577 H1531", "M1695 577 H1726"):
        arrow(path)

    # Four criteria, no cost formulas or economic weights.
    rect(772, 685, 260, 73, "#FAF7FE", "#D8CBEA", radius=12)
    lines(902, 716, ["Thời gian đi • Quãng đường", "Năng lượng • Thời gian chờ"], 14, 23, PURPLE)
    parts.append('<path d="M902 653 V681" fill="none" stroke="#AB95CB" '
                 'stroke-width="1.5" stroke-dasharray="4 4"/>')

    # Choosing can be deferred; no compulsory station assignment.
    arrow("M1393 652 V729", BLUE)
    text(1410, 706, "Chưa chọn", 13, BLUE, anchor="start")
    rect(1304, 734, 178, 55, "#F6F9FE", "#A8BDD9", radius=26)
    text(1393, 767, "Chờ đợt sau", 16, BLUE)
    arrow("M1304 762 H1180 Q1162 762 1162 744 V657", BLUE)

    # Feedback enters local arrival history, never the ranking block.
    arrow("M1811 653 V828 Q1811 850 1789 850 H56 Q34 850 34 828 V205 Q34 184 55 184 "
          "H644 Q652 184 652 194 V221 Q652 229 660 229 H667", GREEN)
    text(1200, 832, "Xe thực sự đến → cập nhật lịch sử tại trạm", 17, GREEN)
    parts.append('<path d="M1540 107 H1576" stroke="#238270" stroke-width="2" stroke-dasharray="6 5"/>')
    text(1588, 112, "Nét đứt: tùy chọn / fallback", 13, "#5B6C83", anchor="start")
    parts.append('</g></svg>')

    svg = OUT / f"{STEM}.svg"
    svg.write_text("\n".join(parts) + "\n", encoding="utf-8")
    ET.parse(svg)
    handle = Rsvg.Handle.new_from_file(str(svg))
    viewport = Rsvg.Rectangle()
    viewport.x, viewport.y, viewport.width, viewport.height = 0, 0, W, H
    png = OUT / f"{STEM}.png"
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W * 2, H * 2)
    ctx = cairo.Context(surface)
    ctx.scale(2, 2)
    assert handle.render_document(ctx, viewport)
    surface.write_to_png(str(png))
    surface.finish()
    pdf = OUT / f"{STEM}.pdf"
    pdf_surface = cairo.PDFSurface(str(pdf), W, H)
    assert handle.render_document(cairo.Context(pdf_surface), viewport)
    pdf_surface.finish()
    with Image.open(png) as im:
        assert im.size == (W * 2, H * 2)
        im.verify()
    assert hashes == {src: hashlib.sha256((ROOT / src).read_bytes()).hexdigest() for src in hashes}
    print(json.dumps({"image": str(png), "svg": str(svg), "pdf": str(pdf),
                      "size": [W * 2, H * 2], "source_files_unchanged": len(hashes)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
