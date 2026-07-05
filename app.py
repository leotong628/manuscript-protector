#!/usr/bin/env python3
"""
app.py — Manuscript Protector Web UI
Local Flask server for Leo to protect manuscripts via browser.
Author: D155 Makima (OpenCode GLM-5.2, Mac CLI)

Usage:
  .venv/bin/python app.py
  → open http://localhost:5111 in browser

No network calls. No cloud upload. Everything stays on this Mac.
"""

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_file, render_template

# Import core protection engine
sys.path.insert(0, str(Path(__file__).parent))
from manuscript_protect import protect_pdf, sha256_file, find_cjk_font
from protect_any import load_profile, render_text_to_pdf, write_receipt, EXPORTS_BASE

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB max upload

WORK_DIR = Path(__file__).parent
PROFILES_DIR = WORK_DIR / "profiles"
TEMP_DIR = Path(tempfile.gettempdir()) / "manuscript_protector_ui"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


@app.route("/")
def index():
    """Serve the main UI page."""
    return render_template("index.html")


@app.route("/api/profiles")
def list_profiles():
    """List available profiles."""
    profiles = []
    if PROFILES_DIR.exists():
        for f in sorted(PROFILES_DIR.glob("*.json")):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                profiles.append({
                    "name": f.stem,
                    "description": data.get("description", ""),
                    "dpi": data.get("dpi", 200),
                    "jpeg_quality": data.get("jpeg_quality", 80),
                    "page_size": f"{data.get('page', {}).get('width', 595)}x{data.get('page', {}).get('height', 842)}",
                })
            except Exception:
                pass
    return jsonify(profiles)


@app.route("/api/protect", methods=["POST"])
def protect():
    """
    Receive a file + parameters, protect it, return download links.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # Get parameters from form
    consultant = request.form.get("consultant", "").strip()
    version = request.form.get("version", "v1").strip()
    password = request.form.get("password", "").strip()
    watermark_text = request.form.get("watermark_text", "").strip()
    confidentiality_label = request.form.get("label", "Confidential").strip()
    profile_name = request.form.get("profile", "").strip()
    encryption = request.form.get("encryption", "aes128").strip()
    allow_print = request.form.get("allow_print") == "true"
    dpi_override = request.form.get("dpi", type=int)
    jpeg_quality_override = request.form.get("jpeg_quality", type=int)

    # Font/layout/watermark customization overrides
    font_size = request.form.get("font_size", type=int)
    line_height = request.form.get("line_height", type=float)
    margin_top = request.form.get("margin_top", type=int)
    margin_bottom = request.form.get("margin_bottom", type=int)
    margin_left = request.form.get("margin_left", type=int)
    margin_right = request.form.get("margin_right", type=int)
    wm_font_size = request.form.get("wm_font_size", type=int)
    wm_opacity = request.form.get("wm_opacity", type=float)
    wm_angle = request.form.get("wm_angle", type=int)
    wm_spacing = request.form.get("wm_spacing", type=int)
    footer_enabled = request.form.get("footer_enabled", "true") == "true"

    # Validate required fields
    if not consultant:
        return jsonify({"error": "Receiver name is required"}), 400
    if not password:
        return jsonify({"error": "Password is required"}), 400

    # Save uploaded file to temp
    input_filename = file.filename
    input_ext = Path(input_filename).suffix.lower()
    temp_input = TEMP_DIR / f"input_{datetime.now().strftime('%H%M%S')}_{input_filename}"
    file.save(str(temp_input))

    # Compute input SHA
    input_sha_before = sha256_file(temp_input)

    try:
        # Load profile
        profile = load_profile(profile_name if profile_name else None)

        # Apply font/layout/watermark overrides to profile
        if font_size:
            profile.setdefault("body_text", {})["font_size"] = font_size
        if line_height:
            profile.setdefault("body_text", {})["line_height"] = line_height
        if margin_top is not None:
            profile.setdefault("margins", {})["top"] = margin_top
        if margin_bottom is not None:
            profile.setdefault("margins", {})["bottom"] = margin_bottom
        if margin_left is not None:
            profile.setdefault("margins", {})["left"] = margin_left
        if margin_right is not None:
            profile.setdefault("margins", {})["right"] = margin_right
        if wm_font_size:
            profile.setdefault("watermark", {})["font_size"] = wm_font_size
        if wm_opacity is not None:
            profile.setdefault("watermark", {})["opacity"] = wm_opacity
        if wm_angle is not None:
            profile.setdefault("watermark", {})["angle"] = wm_angle
        if wm_spacing:
            profile.setdefault("watermark", {})["spacing"] = wm_spacing
        profile.setdefault("footer", {})["enabled"] = footer_enabled

        # Get DPI and JPEG quality from profile or overrides
        dpi = dpi_override if dpi_override else profile.get("dpi", 200)
        jpeg_quality = jpeg_quality_override if jpeg_quality_override else profile.get("jpeg_quality", 80)

        # Determine output directory
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = EXPORTS_BASE / date_str
        output_dir.mkdir(parents=True, exist_ok=True)

        # If md/txt, render to PDF first
        if input_ext in (".md", ".txt"):
            temp_pdf = TEMP_DIR / f"rendered_{datetime.now().strftime('%H%M%S')}.pdf"
            render_text_to_pdf(temp_input, profile, temp_pdf)
            source_pdf = temp_pdf
        elif input_ext == ".pdf":
            source_pdf = temp_input
        else:
            return jsonify({"error": f"Unsupported file type: {input_ext}. Use .md, .txt, or .pdf"}), 400

        # Determine output path
        consultant_safe = "".join(c if c.isalnum() else "_" for c in consultant)
        input_stem = Path(input_filename).stem
        output_pdf = output_dir / f"{input_stem}_protected_{version}_{consultant_safe}.pdf"

        # Protect
        result = protect_pdf(
            source_path=source_pdf,
            consultant=consultant,
            password=password,
            version=version,
            dpi=dpi,
            allow_print=allow_print,
            output_path=output_pdf,
            watermark_text=watermark_text if watermark_text else None,
            confidentiality_label=confidentiality_label,
            profile=profile,
            encryption=encryption,
            jpeg_quality=jpeg_quality,
        )

        # Override with original input SHA
        input_sha_after = sha256_file(temp_input)
        result["source_sha256_before"] = input_sha_before
        result["source_sha256_after"] = input_sha_after
        result["source_untouched"] = input_sha_before == input_sha_after

        # Write receipt
        receipt_path = output_pdf.with_suffix(".receipt.md")
        write_receipt(result, profile_name, str(temp_input), str(output_pdf), receipt_path)

        # Clean up temp files
        if input_ext in (".md", ".txt") and source_pdf.exists():
            source_pdf.unlink()
        temp_input.unlink(missing_ok=True)

        # Calculate file size
        file_size = output_pdf.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        per_page_kb = (file_size / result["page_count"]) / 1024

        return jsonify({
            "success": True,
            "output_path": str(output_pdf),
            "output_filename": output_pdf.name,
            "receipt_path": str(receipt_path),
            "receipt_filename": receipt_path.name,
            "output_sha256": result["output_sha256"],
            "source_sha256": input_sha_before,
            "source_untouched": result["source_untouched"],
            "page_count": result["page_count"],
            "file_size_bytes": file_size,
            "file_size_mb": round(file_size_mb, 2),
            "per_page_kb": round(per_page_kb, 1),
            "dpi": dpi,
            "jpeg_quality": jpeg_quality,
            "encryption": result.get("encryption", encryption),
            "tracking_id": result["tracking_id"],
            "watermark_text": result["watermark_text"],
            "download_url": f"/api/download/{output_pdf.name}",
            "receipt_url": f"/api/download/{receipt_path.name}",
        })

    except Exception as e:
        # Clean up temp files on error
        temp_input.unlink(missing_ok=True)
        if 'source_pdf' in locals() and source_pdf.exists() and source_pdf != temp_input:
            source_pdf.unlink(missing_ok=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/download/<filename>")
def download(filename):
    """Download a protected PDF or receipt from today's Exports folder."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = EXPORTS_BASE / date_str
    filepath = output_dir / filename

    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    return send_file(str(filepath), as_attachment=True, download_name=filename)


@app.route("/api/preview", methods=["POST"])
def preview():
    """
    Generate a preview PNG of one sample page with the given settings.
    Shows how the font size, line height, margins, and watermark will look
    before Leo commits to the full protection run.
    """
    import pymupdf
    import math

    # Get customization parameters
    profile_name = request.form.get("profile", "mobile")
    font_size = request.form.get("font_size", type=int)
    line_height = request.form.get("line_height", type=float)
    margin_top = request.form.get("margin_top", type=int)
    margin_bottom = request.form.get("margin_bottom", type=int)
    margin_left = request.form.get("margin_left", type=int)
    margin_right = request.form.get("margin_right", type=int)
    wm_text = request.form.get("watermark_text", "LEO REVIEW COPY")
    wm_font_size = request.form.get("wm_font_size", type=int)
    wm_opacity = request.form.get("wm_opacity", type=float)
    wm_angle = request.form.get("wm_angle", type=int)
    wm_spacing = request.form.get("wm_spacing", type=int)
    footer_enabled = request.form.get("footer_enabled", "true") == "true"

    # Load base profile
    profile = load_profile(profile_name if profile_name else "mobile")

    # Apply overrides
    if font_size:
        profile.setdefault("body_text", {})["font_size"] = font_size
    if line_height:
        profile.setdefault("body_text", {})["line_height"] = line_height
    if margin_top is not None:
        profile.setdefault("margins", {})["top"] = margin_top
    if margin_bottom is not None:
        profile.setdefault("margins", {})["bottom"] = margin_bottom
    if margin_left is not None:
        profile.setdefault("margins", {})["left"] = margin_left
    if margin_right is not None:
        profile.setdefault("margins", {})["right"] = margin_right
    if wm_font_size:
        profile.setdefault("watermark", {})["font_size"] = wm_font_size
    if wm_opacity is not None:
        profile.setdefault("watermark", {})["opacity"] = wm_opacity
    if wm_angle is not None:
        profile.setdefault("watermark", {})["angle"] = wm_angle
    if wm_spacing:
        profile.setdefault("watermark", {})["spacing"] = wm_spacing
    if not footer_enabled:
        profile.setdefault("footer", {})["enabled"] = False
    else:
        profile.setdefault("footer", {})["enabled"] = True

    # Sample text with English + Chinese
    sample_md = """# Sample Manuscript Page

This is a preview of how your protected PDF will look with the current settings.

## Chinese Test 中文字體測試

人物設定 — Character Settings
天地玄黃，宇宙洪荒。日月盈昃，辰宿列張。
寒來暑往，秋收冬藏。閏餘成歲，律呂調陽。

## Body Text

Lorem ipsum dolor sit amet, consectetur adipiscing elit.
Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.

Ut enim ad minim veniam, quis nostrud exercitation ullamco.
Duis aute irure dolor in reprehenderit in voluptate velit.

---

End of preview sample.
"""

    # Write sample to temp file
    sample_path = TEMP_DIR / "preview_sample.md"
    with open(sample_path, "w", encoding="utf-8") as f:
        f.write(sample_md)

    # Render to PDF
    temp_pdf = TEMP_DIR / "preview_output.pdf"
    try:
        render_text_to_pdf(sample_path, profile, temp_pdf)
    except Exception as e:
        return jsonify({"error": f"Render failed: {e}"}), 500

    # Apply watermark to the PDF
    try:
        doc = pymupdf.open(temp_pdf)
        cjk_font = find_cjk_font()
        fontfile = cjk_font
        fontname = "cjk" if cjk_font else "china_s"

        wm_profile = profile.get("watermark", {})
        footer_profile = profile.get("footer", {"enabled": True})

        from manuscript_protect import add_watermark
        for page_num in range(doc.page_count):
            page = doc[page_num]
            footer_text = f"Confidential — Preview — p.{page_num+1}/{doc.page_count}"
            add_watermark(page, wm_text, footer_text, fontname, fontfile,
                          wm_profile, footer_profile)

        # Render ALL pages and stitch them vertically into one PNG
        import io
        from PIL import Image

        page_pixmaps = []
        for page_num in range(doc.page_count):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=150)
            page_pixmaps.append(pix)

        doc.close()

        if len(page_pixmaps) == 1:
            # Single page — just save it
            png_path = TEMP_DIR / "preview_page1.png"
            page_pixmaps[0].save(str(png_path))
        else:
            # Multiple pages — stitch vertically
            images = []
            for pix in page_pixmaps:
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)

            total_height = sum(img.height for img in images)
            max_width = max(img.width for img in images)
            combined = Image.new("RGB", (max_width, total_height), (255, 255, 255))

            y_offset = 0
            for img in images:
                combined.paste(img, (0, y_offset))
                y_offset += img.height

            png_path = TEMP_DIR / "preview_all_pages.png"
            combined.save(str(png_path), "PNG")

        # Return the PNG with no-cache headers
        resp = send_file(str(png_path), mimetype="image/png")
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    except Exception as e:
        return jsonify({"error": f"Watermark/render failed: {e}"}), 500


if __name__ == "__main__":
    port = 5111
    print(f"\n{'='*50}")
    print(f"  Manuscript Protector Web UI")
    print(f"  Open: http://localhost:{port}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*50}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
