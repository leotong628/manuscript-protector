#!/usr/bin/env python3
"""
CJK Font Gating Test — run before first bulk run (per he260703b §10).
Verifies:
  1. CJK characters render correctly with the system font
  2. fill_opacity / stroke_opacity are supported (Leo's API correction)
  3. morph parameter works for 45-degree diagonal rotation
"""

import math
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:
    print("FAIL: pymupdf not installed")
    sys.exit(1)

CJK_FONT_PATHS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Songti.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]

TEST_TEXT = "江俊傑  |  LT-260704-JKO  |  2026-07-04  |  v1"


def find_cjk_font():
    for p in CJK_FONT_PATHS:
        if Path(p).exists():
            return p
    return None


def test_cjk_rendering():
    """Test that CJK text can be inserted and renders visually."""
    fontfile = find_cjk_font()
    if fontfile:
        print(f"  Found CJK font: {fontfile}")
        fontname = "cjk"
    else:
        print("  No system CJK font found, trying built-in china_s")
        fontname = "china_s"
        fontfile = None

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    try:
        page.insert_text(
            pymupdf.Point(50, 100),
            TEST_TEXT,
            fontsize=20,
            fontname=fontname,
            fontfile=fontfile,
            color=(0.75, 0.75, 0.75),
            fill_opacity=0.25,
            stroke_opacity=0.25,
        )
    except Exception as e:
        print(f"  External font failed: {e}")
        print("  Falling back to china_s...")
        try:
            page.insert_text(
                pymupdf.Point(50, 100),
                TEST_TEXT,
                fontsize=20,
                fontname="china_s",
                color=(0.75, 0.75, 0.75),
                fill_opacity=0.25,
                stroke_opacity=0.25,
            )
            fontfile = None
            fontname = "china_s"
        except Exception as e2:
            print(f"  FAIL: china_s also failed: {e2}")
            return False, None, None

    # Extract text back
    extracted = page.get_text()
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in extracted)
    if has_chinese:
        print("  PASS: Chinese characters found in extracted text")
    else:
        print("  CAVEAT: Chinese not in extracted text (may still render visually)")

    # Render to PNG and check it's not blank
    pix = page.get_pixmap(dpi=150)
    png_path = "cjk_test_render.png"
    pix.save(png_path)

    # Count non-white pixels (text is rendering)
    non_white = 0
    samples = pix.samples
    stride = pix.n
    for i in range(0, len(samples), stride):
        if pix.n >= 3:
            r, g, b = samples[i], samples[i + 1], samples[i + 2]
            if r < 250 or g < 250 or b < 250:
                non_white += 1

    total_pixels = pix.width * pix.height
    if non_white > 100:
        print(f"  PASS: PNG has {non_white} non-white pixels / {total_pixels} total")
    else:
        print(f"  FAIL: PNG nearly blank ({non_white} non-white pixels)")
        return False, None, None

    doc.save("cjk_test.pdf")
    doc.close()
    print(f"  Test PDF: cjk_test.pdf  |  Render: {png_path}")
    return True, fontname, fontfile


def test_opacity():
    """Test that fill_opacity / stroke_opacity are supported on insert_text."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)

    try:
        page.insert_text(
            pymupdf.Point(50, 100),
            "OPACITY TEST 0.25",
            fontsize=20,
            fontname="helv",
            color=(1, 0, 0),
            fill_opacity=0.25,
            stroke_opacity=0.25,
        )
        doc.save("opacity_test.pdf")
        doc.close()
        print("  PASS: fill_opacity / stroke_opacity supported")
        return True
    except Exception as e:
        print(f"  FAIL: fill_opacity not supported: {e}")
        doc.close()
        return False


def test_morph_rotation():
    """Test that morph parameter works for 45-degree rotation."""
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=400)

    angle = math.radians(45)
    rot_matrix = pymupdf.Matrix(
        math.cos(angle), math.sin(angle),
        -math.sin(angle), math.cos(angle),
        0, 0
    )
    point = pymupdf.Point(100, 200)

    try:
        page.insert_text(
            point,
            "ROTATION 45 TEST",
            fontsize=20,
            fontname="helv",
            color=(0.75, 0.75, 0.75),
            morph=(point, rot_matrix),
            fill_opacity=0.25,
            stroke_opacity=0.25,
        )
        doc.save("rotation_test.pdf")
        doc.close()
        print("  PASS: morph parameter works for 45-degree rotation")
        return True
    except Exception as e:
        print(f"  CAVEAT: morph failed: {e}")
        print("  Will use horizontal watermark (no rotation) as fallback")
        doc.close()
        return False  # CAVEAT, not hard FAIL


def test_textbox_opacity():
    """Test that insert_textbox supports fill_opacity / stroke_opacity."""
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=200)
    rect = pymupdf.Rect(50, 50, 350, 150)

    try:
        page.insert_textbox(
            rect,
            "TEXTBOX OPACITY TEST",
            fontsize=16,
            fontname="helv",
            color=(0.4, 0.4, 0.4),
            align=pymupdf.TEXT_ALIGN_CENTER,
            overlay=True,
            fill_opacity=0.6,
            stroke_opacity=0.6,
        )
        doc.save("textbox_opacity_test.pdf")
        doc.close()
        print("  PASS: insert_textbox supports fill_opacity / stroke_opacity")
        return True
    except Exception as e:
        print(f"  FAIL: insert_textbox opacity not supported: {e}")
        doc.close()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("CJK Font Gating Test — Manuscript Protector v1")
    print("=" * 60)

    results = {}

    print("\n--- Test 1: CJK font rendering ---")
    passed, fontname, fontfile = test_cjk_rendering()
    results["CJK rendering"] = passed

    print("\n--- Test 2: Opacity on insert_text ---")
    results["Opacity (insert_text)"] = test_opacity()

    print("\n--- Test 3: Morph 45° rotation ---")
    results["Morph rotation"] = test_morph_rotation()

    print("\n--- Test 4: Opacity on insert_textbox ---")
    results["Opacity (insert_textbox)"] = test_textbox_opacity()

    print("\n" + "=" * 60)
    print("SUMMARY:")
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL/CAVEAT"
        print(f"  {name}: {status}")
        if not passed:
            all_pass = False
    print("=" * 60)
    if all_pass:
        print("OVERALL: PASS — safe to proceed with bulk run")
    else:
        print("OVERALL: CAVEAT — review failures above before bulk run")
