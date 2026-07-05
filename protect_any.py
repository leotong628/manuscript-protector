#!/usr/bin/env python3
"""
protect_any.py — Manuscript Protector V1 user-facing wrapper
Author: Makima (OpenCode GLM-5.2, Mac CLI)

Accepts .md, .txt, or .pdf input:
  - .md/.txt: renders to PDF first (with profile settings), then protects
  - .pdf: protects directly

Features:
  - Password via hidden prompt (getpass) or MANUSCRIPT_PASSWORD env var
  - Never prints or writes the password
  - Output to Exports folder by default
  - Writes paired .md receipt beside output PDF
  - Profile-based customization (font size, line height, page size, margins,
    watermark text/opacity/angle, footer on/off)

Usage:
  python protect_any.py input.md --consultant "Alice" --version v1
  python protect_any.py input.txt --consultant "Alice" --version v1 --profile mobile
  python protect_any.py input.pdf --consultant "Alice" --version v1
  python protect_any.py input.md --consultant "Alice" --version v1 \
    --watermark-text "CUSTOM WATERMARK" --label "PRIVATE"
"""

import argparse
import getpass
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import pymupdf
except ImportError:
    print("ERROR: pymupdf not installed. Run: pip install pymupdf", file=sys.stderr)
    sys.exit(1)

# Import core protection engine
sys.path.insert(0, str(Path(__file__).parent))
from manuscript_protect import (
    protect_pdf, find_cjk_font, sha256_file, generate_tracking_id,
    _try_insert_textbox, DEFAULT_PROFILE
)

# --- Defaults ---
# Output directory: configurable via MANUSCRIPT_EXPORTS_DIR env var
# Defaults to "exports" in the current working directory
EXPORTS_BASE = Path(os.environ.get("MANUSCRIPT_EXPORTS_DIR", "exports"))
PROFILES_DIR = Path(__file__).parent / "profiles"


def load_profile(profile_name=None):
    """Load a profile by name from profiles/ directory, or return defaults."""
    if profile_name is None:
        return dict(DEFAULT_PROFILE)

    # Check profiles/<name>.json
    profile_path = PROFILES_DIR / f"{profile_name}.json"
    if not profile_path.exists():
        print(f"Warning: profile '{profile_name}' not found at {profile_path}", file=sys.stderr)
        print(f"  Using default profile.", file=sys.stderr)
        return dict(DEFAULT_PROFILE)

    with open(profile_path) as f:
        profile = json.load(f)

    # Merge with defaults so missing keys use defaults
    merged = dict(DEFAULT_PROFILE)
    if "watermark" in profile:
        merged["watermark"] = {**DEFAULT_PROFILE["watermark"], **profile["watermark"]}
    if "footer" in profile:
        merged["footer"] = {**DEFAULT_PROFILE["footer"], **profile["footer"]}
    # Pass through page/margins/body_text for md/txt rendering
    if "page" in profile:
        merged["page"] = profile["page"]
    if "margins" in profile:
        merged["margins"] = profile["margins"]
    if "body_text" in profile:
        merged["body_text"] = profile["body_text"]
    if "heading_scale" in profile:
        merged["heading_scale"] = profile["heading_scale"]
    # Pass through DPI and JPEG quality for file size control
    if "dpi" in profile:
        merged["dpi"] = profile["dpi"]
    if "jpeg_quality" in profile:
        merged["jpeg_quality"] = profile["jpeg_quality"]

    return merged


def get_password(env_var="MANUSCRIPT_PASSWORD"):
    """
    Get password from env var or hidden prompt.
    Never prints the password. Never writes it to any file.
    """
    pw = os.environ.get(env_var)
    if pw:
        return pw
    pw = getpass.getpass("Enter password for protected PDF: ")
    if not pw:
        print("Error: password is required", file=sys.stderr)
        sys.exit(1)
    return pw


def render_text_to_pdf(input_path, profile, output_path=None):
    """
    Render a .txt or .md file to a PDF using profile settings.
    Supports minimal markdown: # headings, ## subheadings, ### subsubheadings,
    --- horizontal rules, ``` code blocks, and body text.
    Handles CJK text with system font fallback.
    """
    input_path = Path(input_path).resolve()
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Profile settings for rendering
    page_cfg = profile.get("page", {"width": 595, "height": 842})  # A4 default
    margins = profile.get("margins", {"top": 50, "bottom": 50, "left": 50, "right": 50})
    body_cfg = profile.get("body_text", {"font_size": 12, "line_height": 1.5, "color": [0, 0, 0]})
    heading_scale = profile.get("heading_scale", {"h1": 1.8, "h2": 1.4, "h3": 1.2})

    page_w = page_cfg.get("width", 595)
    page_h = page_cfg.get("height", 842)
    margin_top = margins.get("top", 50)
    margin_bottom = margins.get("bottom", 50)
    margin_left = margins.get("left", 50)
    margin_right = margins.get("right", 50)

    body_fontsize = body_cfg.get("font_size", 12)
    line_height = body_cfg.get("line_height", 1.5)
    body_color = tuple(body_cfg.get("color", [0, 0, 0]))

    # CJK font
    cjk_font = find_cjk_font()
    fontfile = cjk_font
    fontname = "cjk" if cjk_font else "china_s"

    # Text area dimensions
    text_width = page_w - margin_left - margin_right
    text_height = page_h - margin_top - margin_bottom

    # Parse content into blocks
    lines = content.split("\n")
    blocks = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            blocks.append({"type": "code_marker", "text": stripped})
            continue

        if in_code_block:
            blocks.append({"type": "code", "text": line})
            continue

        if stripped.startswith("### "):
            blocks.append({"type": "h3", "text": stripped[4:]})
        elif stripped.startswith("## "):
            blocks.append({"type": "h2", "text": stripped[3:]})
        elif stripped.startswith("# "):
            blocks.append({"type": "h1", "text": stripped[2:]})
        elif stripped == "---":
            blocks.append({"type": "hr", "text": ""})
        elif stripped == "":
            blocks.append({"type": "blank", "text": ""})
        else:
            blocks.append({"type": "body", "text": line})

    # Render blocks to PDF pages
    doc = pymupdf.open()
    page = doc.new_page(width=page_w, height=page_h)
    y_cursor = margin_top

    def new_page_if_needed(needed_height):
        nonlocal page, y_cursor
        if y_cursor + needed_height > page_h - margin_bottom:
            page = doc.new_page(width=page_w, height=page_h)
            y_cursor = margin_top

    def insert_text_line(text, fontsize, color, font_bold=False):
        nonlocal y_cursor
        line_h = fontsize * line_height

        # Let insert_textbox handle wrapping — it has built-in CJK-aware
        # word wrapping that works correctly with full-width Chinese chars.
        # We just need to give it a rect tall enough for the expected lines.
        # Estimate: CJK chars are ~fontsize wide, ASCII ~fontsize*0.55
        cjk_count = sum(1 for c in text if ord(c) > 127)
        ascii_count = len(text) - cjk_count
        est_width = cjk_count * fontsize + ascii_count * fontsize * 0.55
        est_lines = max(1, int(est_width / text_width) + 1)
        needed_height = est_lines * line_h

        new_page_if_needed(needed_height)

        # Use a rect that spans the full text area and is tall enough
        rect = pymupdf.Rect(margin_left, y_cursor,
                            margin_left + text_width, y_cursor + needed_height)
        _try_insert_textbox(page, rect, text,
                            fontsize=fontsize, color=color,
                            fontname=fontname, fontfile=fontfile,
                            fill_opacity=1.0, stroke_opacity=1.0,
                            align=pymupdf.TEXT_ALIGN_LEFT)

        # Advance cursor by the estimated lines used
        y_cursor += needed_height

    for block in blocks:
        btype = block["type"]
        text = block["text"]

        if btype == "h1":
            fs = int(body_fontsize * heading_scale.get("h1", 1.8))
            insert_text_line(text, fs, body_color)
            y_cursor += fs * 0.5  # extra space after heading
        elif btype == "h2":
            fs = int(body_fontsize * heading_scale.get("h2", 1.4))
            insert_text_line(text, fs, body_color)
            y_cursor += fs * 0.4
        elif btype == "h3":
            fs = int(body_fontsize * heading_scale.get("h3", 1.2))
            insert_text_line(text, fs, body_color)
            y_cursor += fs * 0.3
        elif btype == "hr":
            y_cursor += 10
            new_page_if_needed(20)
            # Draw a horizontal line
            page.draw_line(pymupdf.Point(margin_left, y_cursor),
                          pymupdf.Point(margin_left + text_width, y_cursor),
                          color=(0.5, 0.5, 0.5), width=0.5)
            y_cursor += 15
        elif btype == "code":
            fs = int(body_fontsize * 0.9)
            insert_text_line(text, fs, (0.2, 0.2, 0.2))
        elif btype == "code_marker":
            y_cursor += 5  # small gap around code blocks
        elif btype == "blank":
            y_cursor += body_fontsize * 0.6
        elif btype == "body":
            insert_text_line(text, body_fontsize, body_color)

    # Save rendered PDF
    if output_path is None:
        output_path = input_path.with_suffix(".pdf")
    else:
        output_path = Path(output_path)

    doc.save(str(output_path))
    doc.close()
    return str(output_path)


def write_receipt(result, profile_name, input_path, output_pdf_path, receipt_path):
    """Write a .md receipt beside the output PDF. Never includes password."""
    receipt_path = Path(receipt_path)
    content = f"""# Manuscript Protector Receipt

**Generated:** {result['protected_at']}
**Tool:** Manuscript Protector v1 (D155 Makima)

## Input
- **Source file:** `{input_path}`
- **Source SHA-256:** `{result['source_sha256_before']}`

## Output
- **Protected PDF:** `{output_pdf_path}`
- **Output SHA-256:** `{result['output_sha256']}`
- **Pages:** {result['page_count']}
- **DPI:** {result['dpi']}

## Configuration
- **Profile:** {profile_name or 'default'}
- **Consultant:** {result['consultant']}
- **Tracking ID:** {result['tracking_id']}
- **Version:** {result['version']}
- **Watermark text:** {result['watermark_text']}
- **Confidentiality label:** {result['confidentiality_label']}
- **Allow print:** {result['allow_print']}

## Password Handling
Password was provided by Leo; not stored. The password is not included in
this receipt, any log, or any metadata. Leo must deliver the password to the
consultant via a separate channel (phone, SMS, separate message).

## Verification
- **Source untouched:** {result['source_untouched']}
- **Source SHA-256 after:** `{result['source_sha256_after']}`
- **Encryption:** {result.get('encryption', 'AES-128 (V=4, R=4)')}
- **Copy/extract permission:** NOT granted (deterrence, not DRM)

## Caveats
- PDF permissions are viewer-enforced and can be bypassed by some tools.
  This is deterrence, not DRM.
- Metadata can be stripped; not a security boundary.
- Screenshots cannot be prevented by software alone.
- The watermark is baked into pixel data and cannot be removed without re-OCR.

---
*Receipt generated by Manuscript Protector v1 (D155 Makima) on {result['protected_at']}*
"""
    with open(receipt_path, "w", encoding="utf-8") as f:
        f.write(content)
    return str(receipt_path)


def main():
    parser = argparse.ArgumentParser(
        description="Manuscript Protector V1 — protect .md, .txt, or .pdf files"
    )
    parser.add_argument("input", help="Input file (.md, .txt, or .pdf)")
    parser.add_argument("--consultant", required=True, help="Consultant name")
    parser.add_argument("--version", required=True, help="Version label (e.g. v1)")
    parser.add_argument("--id", help="Manual tracking ID override")
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI (default 200)")
    parser.add_argument("--allow-print", action="store_true", help="Allow printing")
    parser.add_argument("--font", help="CJK font file path override")
    parser.add_argument("--profile", help="Profile name (e.g. mobile) from profiles/")
    parser.add_argument("--watermark-text", help="Custom watermark text override")
    parser.add_argument("--label", default="Confidential",
                        help="Confidentiality label for footer (default: Confidential)")
    parser.add_argument("--output", help="Output PDF path override")
    parser.add_argument("--output-dir", help="Output directory override")
    parser.add_argument("--password", help="Password (NOT recommended on CLI; use env var or prompt)")
    parser.add_argument("--no-receipt", action="store_true", help="Skip receipt generation")
    parser.add_argument("--encryption", choices=["aes128", "aes256"], default="aes128",
                        help="Encryption method: aes128 (default, universal compat) or aes256 (stronger, may not open in macOS Preview)")
    parser.add_argument("--jpeg-quality", type=int, default=None,
                        help="JPEG quality 1-100 (default: 80, or from profile)")

    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    suffix = input_path.suffix.lower()

    # Load profile
    profile = load_profile(args.profile)
    profile_name = args.profile

    # Get password (never print it)
    if args.password:
        password = args.password
        print("Warning: password provided on command line. Consider using MANUSCRIPT_PASSWORD env var instead.", file=sys.stderr)
    else:
        password = get_password()

    # Determine output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = EXPORTS_BASE / date_str
    output_dir.mkdir(parents=True, exist_ok=True)

    # Compute original input file SHA before processing
    input_sha_before = sha256_file(input_path)

    # Step 1: If md/txt, render to PDF first
    if suffix in (".md", ".txt"):
        print(f"  Rendering {suffix} to PDF...")
        temp_pdf = output_dir / f"{input_path.stem}_rendered.pdf"
        render_text_to_pdf(input_path, profile, temp_pdf)
        source_pdf = temp_pdf
        print(f"  Rendered PDF: {temp_pdf}")
    elif suffix == ".pdf":
        source_pdf = input_path
    else:
        print(f"Error: unsupported file type '{suffix}'. Use .md, .txt, or .pdf", file=sys.stderr)
        sys.exit(1)

    # Step 2: Determine output path
    if args.output:
        output_pdf = Path(args.output)
    else:
        consultant_safe = "".join(c if c.isalnum() else "_" for c in args.consultant)
        output_pdf = output_dir / f"{input_path.stem}_protected_{args.version}_{consultant_safe}.pdf"

    # Get DPI and JPEG quality from profile or CLI args
    dpi = args.dpi
    jpeg_quality = args.jpeg_quality
    if profile:
        if dpi == 200 and "dpi" in profile:  # profile overrides default 200
            dpi = profile["dpi"]
        if jpeg_quality is None and "jpeg_quality" in profile:
            jpeg_quality = profile["jpeg_quality"]
    if jpeg_quality is None:
        jpeg_quality = 80  # final fallback

    # Step 3: Protect the PDF
    print(f"  Protecting PDF (DPI={dpi}, JPEG quality={jpeg_quality})...")
    try:
        result = protect_pdf(
            source_path=source_pdf,
            consultant=args.consultant,
            password=password,
            version=args.version,
            tracking_id=args.id,
            dpi=dpi,
            allow_print=args.allow_print,
            font_path=args.font,
            output_path=output_pdf,
            watermark_text=args.watermark_text,
            confidentiality_label=args.label,
            profile=profile,
            encryption=args.encryption,
            jpeg_quality=jpeg_quality,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        # Clean up temp rendered PDF if protection failed
        if suffix in (".md", ".txt") and source_pdf.exists():
            source_pdf.unlink()
        sys.exit(1)

    # Clean up temp rendered PDF (it was just an intermediate)
    if suffix in (".md", ".txt") and source_pdf.exists() and source_pdf != input_path:
        source_pdf.unlink()

    # Override result with original input file SHA (not the intermediate PDF SHA)
    input_sha_after = sha256_file(input_path)
    result['source_sha256_before'] = input_sha_before
    result['source_sha256_after'] = input_sha_after
    result['source_untouched'] = input_sha_before == input_sha_after
    result['input_path'] = str(input_path)

    # Step 4: Write receipt
    if not args.no_receipt:
        receipt_path = output_pdf.with_suffix(".receipt.md")
        write_receipt(result, profile_name, str(input_path), str(output_pdf), receipt_path)
        print(f"  Receipt: {receipt_path}")

    # Step 5: Report (never print password)
    print(f"\n✓ Protected: {result['output_path']}")
    print(f"  Input:          {input_path}")
    print(f"  Source SHA-256: {result['source_sha256_before']}")
    print(f"  Output SHA-256: {result['output_sha256']}")
    print(f"  Source untouched: {result['source_untouched']}")
    print(f"  Tracking ID:    {result['tracking_id']}")
    print(f"  Pages: {result['page_count']}  DPI: {result['dpi']}  Print: {result['allow_print']}")
    print(f"  Password: provided by Leo; not stored")


if __name__ == "__main__":
    main()
