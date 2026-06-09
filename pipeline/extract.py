#!/usr/bin/env python3
"""
Extract the thesis PDF into structured, web-ready content.

Strategy (Hybrid):
- Use the PDF table of contents to build a chapter/section tree.
- Walk the pages in reading order. Classify each block as prose, heading,
  caption, figure/table, or display-equation.
- Prose text is cleaned: math letters are de-doubled and mapped to normal
  Unicode so inline math reads correctly and is searchable.
- Display equations, figures and tables are cropped from the page and saved
  as high-resolution PNGs (exact fidelity, no risky transcription).
- Emit JSON consumed by the Astro site, plus the cropped images.

Run: python3 pipeline/extract.py
"""
import json
import re
import shutil
import unicodedata
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "Angelo_Final_Project.pdf"
OUT_DIR = ROOT / "site" / "src" / "data"
IMG_DIR = ROOT / "site" / "public" / "figures"

LEFT_MARGIN = 108.0          # body text left edge
INDENT_MARGIN = 144.0        # first-line indent
PROSE_X_MAX = 152.0          # lines starting left of this are prose
TOP_MARGIN = 72.0            # above => header/page-number band
BOTTOM_MARGIN = 720.0        # below => footer/page-number band
CROP_DPI = 200               # resolution for cropped equation/figure images
CROP_PAD = 4.0               # padding (pt) around cropped regions


# --------------------------------------------------------------------------
# Text cleaning: de-double math glyphs and map math Unicode to normal letters
# --------------------------------------------------------------------------
def _is_math_italic(o: int) -> bool:
    return (
        0x1D434 <= o <= 0x1D467  # italic Latin A-Z a-z
        or 0x1D6E2 <= o <= 0x1D71B  # italic Greek
        or 0x1D44E <= o <= 0x1D467
    )


def _map_math(ch: str) -> str:
    o = ord(ch)
    if 0x1D44E <= o <= 0x1D467:  # italic small latin a-z
        return chr(ord("a") + o - 0x1D44E)
    if 0x1D434 <= o <= 0x1D44D:  # italic capital latin A-Z
        return chr(ord("A") + o - 0x1D434)
    if 0x1D6E2 <= o <= 0x1D6FA:  # italic capital greek Alpha-Omega
        return chr(0x0391 + o - 0x1D6E2)
    if 0x1D6FC <= o <= 0x1D714:  # italic small greek alpha-omega
        return chr(0x03B1 + o - 0x1D6FC)
    # a few italic specials
    specials = {0x1D715: "∂", 0x1D716: "ε", 0x1D70B: "π"}
    return specials.get(o, ch)


# Codepoint ranges that are only ever broken math layout glyphs (matrix
# brackets, fake combining marks) — safe to drop from English prose.
_JUNK_RANGES = [
    (0x0D00, 0x0DFF),  # Malayalam / Sinhala (matrix brackets ൥ ൩, hats)
    (0x1200, 0x137F),  # Ethiopic (fake wide-arrow bases)
    (0x0F00, 0x0FFF),  # Tibetan
]


def _is_junk(o: int) -> bool:
    return any(lo <= o <= hi for lo, hi in _JUNK_RANGES)


def clean_text(s: str) -> str:
    """De-double math letters, map math Unicode, strip broken layout glyphs."""
    out = []
    prev = None
    for ch in s:
        o = ord(ch)
        if _is_junk(o):
            prev = None
            continue
        if _is_math_italic(o) and ch == prev:
            # duplicated math glyph from the Word equation export — drop dupe
            continue
        prev = ch if _is_math_italic(o) else None
        out.append(_map_math(ch))
    txt = "".join(out)
    txt = txt.replace(" ", " ")
    txt = re.sub(r"[ \t]+", " ", txt)
    return txt


# --------------------------------------------------------------------------
# TOC -> section tree
# --------------------------------------------------------------------------
def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t or "section"


CHAPTER_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")


def norm_title(s: str) -> str:
    s = clean_text(s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def build_sections(doc):
    """Return ordered list of sections from the TOC.

    Each section: {idx, level, number, title, slug, chapter_idx,
                   start_page (0-based), end_page (exclusive)}
    """
    toc = doc.get_toc()
    sections = []
    chapter_idx = -1
    for level, title, page in toc:
        title = title.strip()
        m = CHAPTER_RE.match(title)
        number = None
        is_chapter = level == 1
        clean_title = title
        if m and is_chapter:
            number = m.group(1)
            clean_title = m.group(2).strip()
        if is_chapter:
            chapter_idx += 1
        sections.append(
            {
                "idx": len(sections),
                "level": level,
                "number": number,
                "title": clean_text(clean_title),
                "raw_title": title,
                "slug": slugify(title),
                "chapter_idx": chapter_idx,
                "start_page": page - 1,  # PyMuPDF is 0-based
            }
        )
    # de-dup slugs
    seen = {}
    for s in sections:
        base = s["slug"]
        if base in seen:
            seen[base] += 1
            s["slug"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 0
    # Prepend a Preface section for the front-matter prose (the page right
    # before the Introduction). Title/blank/contents pages are skipped.
    intro_start = sections[0]["start_page"]
    preface = {
        "idx": -1,
        "level": 1,
        "number": None,
        "title": "Preface",
        "raw_title": "Preface",
        "slug": "preface",
        "chapter_idx": -1,
        "start_page": max(0, intro_start - 1),
    }
    sections = [preface] + sections
    for i, s in enumerate(sections):
        s["idx"] = i  # renumber so preface is 0
    # end pages
    for i, s in enumerate(sections):
        s["end_page"] = (
            sections[i + 1]["start_page"] if i + 1 < len(sections) else doc.page_count - 1
        )
    return sections


# --------------------------------------------------------------------------
# Per-page block classification
# --------------------------------------------------------------------------
CAPTION_RE = re.compile(r"^\s*(Figure|Table)\s+[\dIVX]+([.\-]\d+)?", re.I)


def line_text(line):
    return "".join(span["text"] for span in line["spans"])


def classify_line(raw, bbox, page_number_str, toc_titles):
    txt = clean_text(raw).strip()
    if not txt:
        return "blank", txt
    x0, y0, x1, y1 = bbox
    # page number / running header
    if (y0 < TOP_MARGIN or y1 > BOTTOM_MARGIN) and len(txt) <= 6 and re.fullmatch(
        r"[\divxlcDIVXLC]+", txt
    ):
        return "pagenum", txt
    if norm_title(raw) in toc_titles:
        return "heading", txt
    # Lines starting at the left margin are body prose (a sentence that merely
    # opens with "Figure 3 shows..." is prose, not a caption).
    if x0 <= PROSE_X_MAX:
        return "prose", txt
    # Centered / indented line:
    #   - a real figure/table caption begins with "Figure|Table N";
    #   - a definition-list sentence has several words;
    #   - otherwise it is a display equation.
    if CAPTION_RE.match(txt):
        return "caption", txt
    words = re.findall(r"[A-Za-z]{2,}", txt)
    if len(words) >= 4:
        return "prose", txt
    return "math", txt


def keep_graphic(rect):
    """Filter out left-gutter list bullets and hairline rules."""
    r = fitz.Rect(rect)
    if r.width < 4 or r.height < 4:
        return False  # hairline rule / stray mark
    if r.x1 <= 150 and r.width < 40:
        return False  # list bullet / decoration in the left gutter
    return True


def rects_union(rects):
    r = fitz.Rect(rects[0])
    for x in rects[1:]:
        r |= fitz.Rect(x)
    return r


def crop_image(page, rect, path, dpi=CROP_DPI):
    rect = fitz.Rect(rect)
    rect = rect + (-CROP_PAD, -CROP_PAD, CROP_PAD, CROP_PAD)
    rect &= page.rect
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)
    pix.save(path)
    return {"w": pix.width, "h": pix.height}


def extract():
    fitz.TOOLS.mupdf_display_errors(False)  # silence harmless structure-tree warnings
    doc = fitz.open(PDF)
    sections = build_sections(doc)
    toc_titles = {norm_title(s["raw_title"]) for s in sections}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    for old in IMG_DIR.glob("*.png"):
        old.unlink()

    # map page -> section idx pointer using start pages; refined by headings
    blocks_by_section = {s["idx"]: [] for s in sections}
    cur = 0
    fig_counter = 0

    # Save the cover artwork (largest image on the title page) for the hero.
    try:
        cover_imgs = doc[0].get_images(full=True)
        if cover_imgs:
            xref = max(
                cover_imgs,
                key=lambda im: doc.extract_image(im[0])["width"]
                * doc.extract_image(im[0])["height"],
            )[0]
            pix = fitz.Pixmap(doc, xref)
            if pix.n - pix.alpha >= 4:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            pix.save(IMG_DIR / "cover.png")
    except Exception as exc:  # pragma: no cover
        print("cover extraction failed:", exc)

    first_content_page = sections[0]["start_page"]
    for pno in range(first_content_page, doc.page_count):
        page = doc[pno]
        # advance section pointer when entering a section's start page
        while cur + 1 < len(sections) and sections[cur + 1]["start_page"] <= pno:
            cur += 1

        page_num_str = str(pno)
        raw = page.get_text("dict")

        # collect ordered elements
        elements = []  # (y0, kind, payload)
        for b in raw["blocks"]:
            if b["type"] == 1:  # image
                if keep_graphic(b["bbox"]):
                    elements.append((b["bbox"][1], "graphic", fitz.Rect(b["bbox"])))
                continue
            for line in b["lines"]:
                bbox = line["bbox"]
                raw_txt = line_text(line)
                kind, txt = classify_line(raw_txt, bbox, page_num_str, toc_titles)
                if kind in ("blank", "pagenum"):
                    continue
                elements.append((bbox[1], kind, {"bbox": bbox, "text": txt, "raw": raw_txt}))

        # vector drawings contribute to graphic regions (figure borders, diagrams)
        for dr in page.get_drawings():
            if keep_graphic(dr["rect"]):
                elements.append((dr["rect"].y0, "graphic", fitz.Rect(dr["rect"])))

        elements.sort(key=lambda e: (round(e[0]), e[1] != "graphic"))

        # walk elements, build content blocks for current section(s)
        para_lines = []
        para_indent = False
        graphic_rects = []

        def flush_para():
            nonlocal para_lines, para_indent
            if para_lines:
                text = " ".join(para_lines).strip()
                text = re.sub(r"\s+", " ", text)
                # drop a stray heading line that repeats the section title
                if text and text.lower() != sections[cur]["title"].lower():
                    blocks_by_section[cur].append({"type": "p", "text": text})
            para_lines = []
            para_indent = False

        def flush_graphic():
            nonlocal graphic_rects, fig_counter
            if not graphic_rects:
                return
            rect = rects_union(graphic_rects)
            # ignore tiny stray rects (list-bullet icons, decorations)
            if rect.width < 40 and rect.height < 14:
                graphic_rects = []
                return
            fig_counter += 1
            name = f"p{pno:03d}-g{fig_counter:03d}.png"
            dim = crop_image(page, rect, IMG_DIR / name)
            blocks_by_section[cur].append(
                {
                    "type": "figure",
                    "src": name,
                    "w": dim["w"],
                    "h": dim["h"],
                    "page": pno,
                }
            )
            graphic_rects = []

        for y0, kind, payload in elements:
            if kind == "graphic" or kind == "math":
                flush_para()
                rect = payload if kind == "graphic" else fitz.Rect(payload["bbox"])
                graphic_rects.append(rect)
                continue
            # text flow element ends any graphic run
            flush_graphic()
            if kind == "heading":
                flush_para()
                # heading marks a (sub)section boundary; switch pointer if matches
                nt = norm_title(payload["raw"])
                for s in sections:
                    if norm_title(s["raw_title"]) == nt and s["start_page"] in (pno, pno - 1, pno + 1):
                        cur = s["idx"]
                        break
                continue
            if kind == "caption":
                flush_para()
                # attach caption to the most recent figure in this section
                sec_blocks = blocks_by_section[cur]
                if sec_blocks and sec_blocks[-1]["type"] == "figure":
                    sec_blocks[-1]["caption"] = payload["text"]
                else:
                    blocks_by_section[cur].append(
                        {"type": "caption", "text": payload["text"]}
                    )
                continue
            if kind == "prose":
                x0 = payload["bbox"][0]
                is_indent = abs(x0 - INDENT_MARGIN) < 12
                if is_indent and para_lines:
                    flush_para()
                para_lines.append(payload["text"])

        flush_graphic()
        flush_para()

    # assemble output
    sections_out = []
    for s in sections:
        blocks = blocks_by_section[s["idx"]]
        text_for_search = " ".join(
            b["text"] for b in blocks if b["type"] in ("p", "caption")
        )
        sections_out.append(
            {
                "idx": s["idx"],
                "level": s["level"],
                "number": s["number"],
                "title": s["title"],
                "slug": s["slug"],
                "chapter_idx": s["chapter_idx"],
                "start_page": s["start_page"],
                "blocks": blocks,
                "search_text": text_for_search,
            }
        )

    meta = {
        "title": "Statistical Principles and Orthogonality",
        "subtitle": "To the Flight of the Constellation",
        "author": doc.metadata.get("author") or "Angelo Perillo",
        "advisor": "Richard Fowles",
        "pages": doc.page_count,
        "pdf": PDF.name,
        "cover": "cover.png" if (IMG_DIR / "cover.png").exists() else None,
    }
    out = {"meta": meta, "sections": sections_out}
    (OUT_DIR / "thesis.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

    # Make the original PDF downloadable from the site.
    public = IMG_DIR.parent
    shutil.copy(PDF, public / PDF.name)

    # stats
    nfig = sum(1 for s in sections_out for b in s["blocks"] if b["type"] == "figure")
    npar = sum(1 for s in sections_out for b in s["blocks"] if b["type"] == "p")
    print(f"sections={len(sections_out)} paragraphs={npar} figures/eqs={nfig}")
    print(f"wrote {OUT_DIR/'thesis.json'}  images -> {IMG_DIR}")


if __name__ == "__main__":
    extract()
