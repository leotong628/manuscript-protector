#!/usr/bin/env python3
"""
Manuscript Protector v1 — Core PDF protection engine
Author: Makima (OpenCode GLM-5.2, Mac CLI)

Updated for V1 workflow:
  - protect_pdf and add_watermark now accept profile-based customization
  - Watermark text, font_size, opacity, angle, color, spacing configurable
  - Footer can be toggled on/off with custom settings
  - Backward compatible: profile params are optional with sensible defaults

API corrections (per Leo, 260704):
  - Opacity: native fill_opacity / stroke_opacity (NOT get_drawings mutation)
  - Permissions: NO PDF_PERM_COPY, NO PDF_PERM_ACCESSIBILITY
  - Minimal mask: PDF_PERM_PRINT only if allow_print, else 0

Caveats:
  - PDF permissions are viewer-enforced; deterrence, not DRM.
  - Metadata can be stripped; not a security boundary.
"""

import hashlib
import math
import sys
from datetime import datetime
from pathlib import Path

try:
    import pymupdf
except ImportError:
    print("ERROR: pymupdf not installed. Run: pip install pymupdf", file=sys.stderr)
    sys.exit(1)

CJK_FONT_PATHS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Songti.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]

CONSULTANT_REGISTRY = {
    # Add your own receiver names and initials here
    # "Alice Wong": "AW",
    # "Bob Chan": "BC",
}

# Default profile (used when no profile is specified)
DEFAULT_PROFILE = {
    "watermark": {
        "font_size": 20,
        "opacity": 0.25,
        "angle": 45,
        "color": [0.75, 0.75, 0.75],
        "spacing": 200,
    },
    "footer": {
        "enabled": True,
        "font_size": 8,
        "opacity": 0.6,
        "color": [0.4, 0.4, 0.4],
    },
}


def find_cjk_font(configured_path=None):
    candidates = []
    if configured_path:
        candidates.append(Path(configured_path))
    for p in CJK_FONT_PATHS:
        candidates.append(Path(p))
    for c in candidates:
        if c.exists() and c.is_file():
            return str(c)
    return None


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_tracking_id(consultant):
    date_str = datetime.now().strftime("%y%m%d")
    if consultant in CONSULTANT_REGISTRY:
        initials = CONSULTANT_REGISTRY[consultant]
    else:
        initials = "".join(w[0] for w in consultant.split() if w).upper()
    return f"LT-{date_str}-{initials}"


def _try_insert_text(page, point, text, fontsize, color, fontname, fontfile,
                     morph=None, fill_opacity=1.0, stroke_opacity=1.0):
    attempts = [
        {"fontname": fontname, "fontfile": fontfile, "morph": morph,
         "fill_opacity": fill_opacity, "stroke_opacity": stroke_opacity},
        {"fontname": fontname, "fontfile": fontfile, "morph": None,
         "fill_opacity": fill_opacity, "stroke_opacity": stroke_opacity},
        {"fontname": "china_s", "fontfile": None, "morph": morph,
         "fill_opacity": fill_opacity, "stroke_opacity": stroke_opacity},
        {"fontname": "china_s", "fontfile": None, "morph": None,
         "fill_opacity": fill_opacity, "stroke_opacity": stroke_opacity},
    ]
    for opts in attempts:
        try:
            page.insert_text(point, text, fontsize=fontsize, color=color,
                             overlay=True, **opts)
            return True
        except Exception:
            continue
    return False


def _try_insert_textbox(page, rect, text, fontsize, color, fontname, fontfile,
                        fill_opacity=1.0, stroke_opacity=1.0, align=None):
    if align is None:
        align = pymupdf.TEXT_ALIGN_CENTER
    attempts = [
        {"fontname": fontname, "fontfile": fontfile,
         "fill_opacity": fill_opacity, "stroke_opacity": stroke_opacity},
        {"fontname": "china_s", "fontfile": None,
         "fill_opacity": fill_opacity, "stroke_opacity": stroke_opacity},
    ]
    for opts in attempts:
        try:
            page.insert_textbox(rect, text, fontsize=fontsize, color=color,
                                align=align, overlay=True, **opts)
            return True
        except Exception:
            continue
    return False


def split_watermark_text(text, max_chars=20):
    """
    Split a long watermark text into multiple shorter lines.
    Breaks at spaces when possible, or hard-cuts for CJK.
    Returns a list of lines, each <= max_chars.
    """
    if len(text) <= max_chars:
        return [text]

    lines = []
    current = ""
    words = text.split(" ")

    for word in words:
        # If adding this word would exceed max_chars, start a new line
        if len(current) + len(word) + 1 > max_chars:
            if current:
                lines.append(current.strip())
            # If the word itself is too long, hard-cut it
            while len(word) > max_chars:
                lines.append(word[:max_chars])
                word = word[max_chars:]
            current = word
        else:
            current = current + " " + word if current else word

    if current:
        lines.append(current.strip())

    return lines


def add_watermark(page, watermark_text, footer_text, fontname, fontfile,
                  wm_profile=None, footer_profile=None):
    """
    Add diagonal grid watermark + optional footer watermark to a page.
    Long watermark text is auto-split into multiple lines to prevent overlap.
    """
    if wm_profile is None:
        wm_profile = DEFAULT_PROFILE["watermark"]
    if footer_profile is None:
        footer_profile = DEFAULT_PROFILE["footer"]

    rect = page.rect
    width = rect.width
    height = rect.height

    # Rotation matrix for diagonal watermark
    angle = math.radians(wm_profile.get("angle", 45))
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    rot_matrix = pymupdf.Matrix(cos_a, sin_a, -sin_a, cos_a, 0, 0)

    wm_fontsize = wm_profile.get("font_size", 20)
    wm_opacity = wm_profile.get("opacity", 0.25)
    wm_color = tuple(wm_profile.get("color", [0.75, 0.75, 0.75]))

    # Auto-split long watermark text into multiple lines
    # Max chars per line scales with font size: smaller font = more chars per line
    max_chars_per_line = max(15, int(250 / wm_fontsize))
    wm_lines = split_watermark_text(watermark_text, max_chars_per_line)

    # Calculate spacing based on the longest line
    longest_line = max(wm_lines, key=len) if wm_lines else watermark_text
    # Estimate text width: ASCII ~0.55*fontsize, CJK ~1.0*fontsize
    cjk_count = sum(1 for c in longest_line if ord(c) > 127)
    ascii_count = len(longest_line) - cjk_count
    est_text_width = cjk_count * wm_fontsize + ascii_count * wm_fontsize * 0.55

    # Spacing = text width + gap (so lines don't overlap)
    # Use profile spacing as minimum, but expand if text is long
    profile_spacing = wm_profile.get("spacing", 200)
    step = max(profile_spacing, int(est_text_width * 1.3))

    # Vertical offset between stacked lines
    line_offset = wm_fontsize * 1.3

    x_start = int(-height)
    x_end = int(width + height)
    y_start = 0
    y_end = int(height + width)

    for x in range(x_start, x_end, step):
        for y in range(y_start, y_end, step):
            for line_idx, wm_line in enumerate(wm_lines):
                point = pymupdf.Point(x, y + line_idx * line_offset)
                _try_insert_text(page, point, wm_line,
                                 fontsize=wm_fontsize, color=wm_color,
                                 fontname=fontname, fontfile=fontfile,
                                 morph=(point, rot_matrix),
                                 fill_opacity=wm_opacity, stroke_opacity=wm_opacity)

    # Footer watermark (optional)
    if footer_profile.get("enabled", True):
        footer_fontsize = footer_profile.get("font_size", 8)
        footer_opacity = footer_profile.get("opacity", 0.6)
        footer_color = tuple(footer_profile.get("color", [0.4, 0.4, 0.4]))
        footer_rect = pymupdf.Rect(width * 0.1, height - 30, width * 0.9, height - 10)
        _try_insert_textbox(page, footer_rect, footer_text,
                            fontsize=footer_fontsize, color=footer_color,
                            fontname=fontname, fontfile=fontfile,
                            fill_opacity=footer_opacity, stroke_opacity=footer_opacity)


def protect_pdf(source_path, consultant, password, version,
                tracking_id=None, dpi=200, allow_print=False,
                font_path=None, output_path=None,
                watermark_text=None, confidentiality_label="Confidential",
                profile=None, encryption="aes128", jpeg_quality=80):
    """
    Protect a single manuscript PDF.

    Parameters:
      jpeg_quality: JPEG compression quality 1-100 (default 80, ~300KB/page at 150 DPI)
      encryption: "aes128" (default, universal viewer compat) or "aes256"
    """
    source_path = Path(source_path).expanduser().resolve()

    if not source_path.exists():
        raise FileNotFoundError(f"Source PDF not found: {source_path}")

    if output_path is None:
        consultant_safe = "".join(c if c.isalnum() else "_" for c in consultant)
        output_path = source_path.with_name(
            f"{source_path.stem}_protected_{version}_{consultant_safe}.pdf"
        )
    else:
        output_path = Path(output_path).expanduser().resolve()

    if output_path.resolve() == source_path.resolve():
        raise RuntimeError("Refusing to overwrite source PDF")

    source_sha_before = sha256_file(source_path)

    cjk_font = find_cjk_font(font_path)
    if cjk_font:
        fontfile = cjk_font
        fontname = "cjk"
    else:
        fontfile = None
        fontname = "china_s"

    if tracking_id is None:
        tracking_id = generate_tracking_id(consultant)

    date_str = datetime.now().strftime("%Y-%m-%d")

    # Watermark text: custom or auto-generated
    if watermark_text is None:
        watermark_text = f"{consultant}  |  {tracking_id}  |  {date_str}  |  {version}"

    # Profile settings
    if profile is None:
        profile = DEFAULT_PROFILE
    wm_profile = profile.get("watermark", DEFAULT_PROFILE["watermark"])
    footer_profile = profile.get("footer", DEFAULT_PROFILE["footer"])

    try:
        doc = pymupdf.open(source_path)
    except Exception as e:
        raise ValueError(f"Cannot open PDF (may be corrupt): {e}")

    if doc.page_count == 0:
        doc.close()
        raise ValueError("PDF has no pages")

    if doc.page_count > 200 and dpi > 150:
        dpi = 150

    total_pages = doc.page_count

    # Layer 0: Watermark (in memory)
    for page_num in range(total_pages):
        page = doc[page_num]
        footer_text = (f"{confidentiality_label} — {consultant} — {tracking_id} — "
                       f"{version} — {date_str} — p.{page_num + 1}/{total_pages}")
        add_watermark(page, watermark_text, footer_text, fontname, fontfile,
                      wm_profile, footer_profile)

    # Layer 1: Text → Image conversion (JPEG for smaller file size)
    new_doc = pymupdf.open()
    for page_num in range(total_pages):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        # Use JPEG instead of PNG — 10-20x smaller file size
        # JPEG quality 80 gives ~300KB/page at 150 DPI on A5
        img_data = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
        new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(rect=new_page.rect, stream=img_data)

    doc.close()  # source file untouched on disk

    # Layer 2: Audit metadata
    new_doc.set_metadata({
        "producer": "Manuscript Protector v1 (D155 Makima)",
        "title": f"Protected Manuscript — {consultant} — {version}",
        "subject": f"Tracking ID: {tracking_id}",
        "keywords": (f"protected_by=D155_Makima;protected_at={datetime.now().isoformat()};"
                     f"watermark_text={watermark_text};source_sha256={source_sha_before}"),
    })

    # Layer 3: Encryption
    # AES-128 is the default for universal viewer compatibility (macOS Preview,
    # Adobe, Foxit, browser viewers, mobile). AES-256 (V=5, R=6) is stronger
    # but macOS Preview cannot open it — known compatibility issue.
    if allow_print:
        permissions = pymupdf.PDF_PERM_PRINT
    else:
        permissions = 0

    if encryption == "aes256":
        enc_method = pymupdf.PDF_ENCRYPT_AES_256
        enc_label = "AES-256 (V=5, R=6)"
    else:
        enc_method = pymupdf.PDF_ENCRYPT_AES_128
        enc_label = "AES-128 (V=4, R=4)"

    new_doc.save(
        str(output_path),
        encryption=enc_method,
        owner_pw=password,
        user_pw=password,
        permissions=permissions,
    )

    output_sha = sha256_file(output_path)
    new_doc.close()

    source_sha_after = sha256_file(source_path)
    if source_sha_after != source_sha_before:
        raise RuntimeError(
            f"SOURCE FILE MUTATED! Before: {source_sha_before}, After: {source_sha_after}"
        )

    return {
        "source_path": str(source_path),
        "output_path": str(output_path),
        "source_sha256_before": source_sha_before,
        "source_sha256_after": source_sha_after,
        "source_untouched": source_sha_before == source_sha_after,
        "output_sha256": output_sha,
        "consultant": consultant,
        "tracking_id": tracking_id,
        "version": version,
        "dpi": dpi,
        "allow_print": allow_print,
        "page_count": total_pages,
        "watermark_text": watermark_text,
        "confidentiality_label": confidentiality_label,
        "encryption": enc_label,
        "protected_at": datetime.now().isoformat(),
    }
