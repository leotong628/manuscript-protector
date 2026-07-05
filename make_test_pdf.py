#!/usr/bin/env python3
"""
Generate a test PDF with Chinese text for CJK watermark testing.
Per he260703b §10 gating test.
"""

import argparse
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:
    print("ERROR: pymupdf not installed")
    sys.exit(1)

CJK_FONT_PATHS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Songti.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]


def find_cjk_font():
    for p in CJK_FONT_PATHS:
        if Path(p).exists():
            return p
    return None


def make_test_pdf(name="江俊傑", output="test_chinese.pdf", num_pages=3):
    """Create a test PDF with Chinese text."""
    fontfile = find_cjk_font()
    fontname = "cjk" if fontfile else "china_s"

    doc = pymupdf.open()

    for i in range(num_pages):
        page = doc.new_page(width=595, height=842)  # A4

        text = (
            f"測試文稿 第{i + 1}頁\n"
            f"顧問：{name}\n\n"
            f"這是一份測試用的中文文稿，用於驗證水印工具是否能正確渲染中文字符。\n"
            f" Manuscript Protector Test — Page {i + 1}\n"
            f"保護文稿測試 — 江俊傑\n\n"
            f"Lorem ipsum dolor sit amet, consectetur adipiscing elit.\n"
            f"中文測試內容：天地玄黃，宇宙洪荒。日月盈昃，辰宿列張。\n"
            f"寒來暑往，秋收冬藏。閏餘成歲，律呂調陽。\n"
        )

        rect = pymupdf.Rect(50, 80, 545, 780)
        try:
            page.insert_textbox(
                rect, text, fontsize=20,
                fontname=fontname, fontfile=fontfile,
                color=(0, 0, 0), align=pymupdf.TEXT_ALIGN_LEFT,
            )
        except Exception:
            page.insert_textbox(
                rect, text, fontsize=20,
                fontname="china_s",
                color=(0, 0, 0), align=pymupdf.TEXT_ALIGN_LEFT,
            )

    doc.save(output)
    doc.close()
    print(f"Test PDF created: {output}")
    print(f"  Pages: {num_pages}")
    print(f"  Font:  {fontfile or 'china_s (built-in)'}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate test PDF with Chinese text")
    parser.add_argument("--name", default="江俊傑", help="Chinese name to include")
    parser.add_argument("--output", default="test_chinese.pdf", help="Output path")
    parser.add_argument("--pages", type=int, default=3, help="Number of pages")
    args = parser.parse_args()
    make_test_pdf(args.name, args.output, args.pages)
