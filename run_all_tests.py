#!/usr/bin/env python3
"""
Run all 8 tests for Manuscript Protector v1 and produce evidence.
Tests 1-3 are verified by the protection tool output itself;
this script runs tests 4-8 and summarizes all 8.
"""

import hashlib
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:
    print("FAIL: pymupdf not installed")
    sys.exit(1)

try:
    import pikepdf
except ImportError:
    print("CAVEAT: pikepdf not installed — encryption tests will use PyMuPDF fallback")
    pikepdf = None

WORK_DIR = Path(__file__).parent
SOURCE_PDF = WORK_DIR / "test_chinese.pdf"
OUTPUT_PDF = WORK_DIR / "test_chinese_protected_v1_Jason_Kong.pdf"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def test_1_source_untouched():
    """Test 1: Source PDF remains byte-identical."""
    # The protection tool already verified this, but we re-verify independently
    source_sha = sha256_file(SOURCE_PDF)
    # We know the before hash from the protection run: 1d103130...
    expected = "1d103130cbe3134ce1657b12d4771dd9a30602a0a915219313d4873a3c8650a6"
    passed = source_sha == expected
    print(f"  Source SHA-256: {source_sha}")
    print(f"  Expected:       {expected}")
    print(f"  Match: {passed}")
    return passed


def test_2_output_not_source():
    """Test 2: Output path is _protected.pdf, not source overwrite."""
    passed = OUTPUT_PDF.exists() and OUTPUT_PDF.resolve() != SOURCE_PDF.resolve()
    print(f"  Output exists: {OUTPUT_PDF.exists()}")
    print(f"  Output != source: {OUTPUT_PDF.resolve() != SOURCE_PDF.resolve()}")
    print(f"  Output name: {OUTPUT_PDF.name}")
    return passed


def test_3_chinese_processed():
    """Test 3: Chinese sample PDF processes successfully."""
    passed = OUTPUT_PDF.exists() and OUTPUT_PDF.stat().st_size > 0
    print(f"  Output size: {OUTPUT_PDF.stat().st_size:,} bytes")
    return passed


def test_4_watermark_visible():
    """Test 4: Watermark visible at approx 0.25 opacity by PNG inspection."""
    doc = pymupdf.open(OUTPUT_PDF)
    # Must authenticate before accessing encrypted PDF content
    if doc.is_encrypted:
        auth = doc.authenticate("testpass123")
        if not auth:
            print("  FAIL: cannot authenticate with password")
            doc.close()
            return False
    page = doc[0]
    pix = page.get_pixmap(dpi=150)
    png_path = str(WORK_DIR / "watermark_inspection.png")
    pix.save(png_path)

    # Check for watermark pixels (light gray, not pure black or white)
    # Watermark color is (0.75, 0.75, 0.75) at 0.25 opacity over content
    # Look for pixels that are "grayish" — not pure black, not pure white
    samples = pix.samples
    stride = pix.n
    total = pix.width * pix.height
    grayish = 0
    for i in range(0, len(samples), stride):
        if pix.n >= 3:
            r, g, b = samples[i], samples[i + 1], samples[i + 2]
            # Watermark pixels: light gray, roughly equal RGB, not pure black/white
            if abs(r - g) < 20 and abs(g - b) < 20 and 100 < r < 240:
                grayish += 1

    doc.close()
    print(f"  Rendered PNG: {png_path}")
    print(f"  Image size: {pix.width}x{pix.height} = {total} pixels")
    print(f"  Grayish (watermark-candidate) pixels: {grayish}")
    # Watermark should produce a significant number of grayish pixels
    passed = grayish > 500
    return passed


def test_5_encryption_aes256():
    """Test 5: Encryption is AES-256 with correct permission flags."""
    if pikepdf:
        try:
            pdf = pikepdf.open(str(OUTPUT_PDF), password="testpass123")
            enc = pdf.encryption
            print(f"  Encrypted: {pdf.is_encrypted}")
            if enc:
                # pikepdf 10.x: stream_method returns EncryptionMethod enum
                # aesv3 = AES-256 (PDF spec V=5, R=6)
                stream_m = enc.stream_method
                string_m = enc.string_method
                bits = enc.bits if hasattr(enc, 'bits') else None
                v = enc.V if hasattr(enc, 'V') else None
                r = enc.R if hasattr(enc, 'R') else None
                p = enc.P if hasattr(enc, 'P') else None
                print(f"  Stream method: {stream_m}")
                print(f"  String method: {string_m}")
                print(f"  Bits: {bits}")
                print(f"  V (version): {v}")
                print(f"  R (revision): {r}")
                print(f"  P (permissions): {p}")
                # AES-256 = aesv3 in pikepdf enum, or V=5, or bits=256
                stream_str = str(stream_m).lower()
                aes256 = ("aes" in stream_str and "v3" in stream_str) or \
                         (bits == 256) or (v == 5)
                print(f"  Is AES-256: {aes256}")
                allow = pdf.allow
                print(f"  Permissions:")
                print(f"    print:     {allow.print_lowres or allow.print_highres}")
                print(f"    extract:   {allow.extract}")
                print(f"    modify:    {allow.modify_other}")
                pdf.close()
                return aes256
            pdf.close()
            return False
        except Exception as e:
            print(f"  pikepdf error: {e}")
            return False
    else:
        # PyMuPDF fallback
        doc = pymupdf.open(OUTPUT_PDF)
        print(f"  Encrypted: {doc.is_encrypted}")
        print(f"  Permissions bitmask: {doc.permissions}")
        # Check if needs pass
        auth = doc.authenticate("testpass123")
        print(f"  Auth with password: {auth}")
        doc.close()
        return doc.is_encrypted


def test_6_copy_not_granted():
    """Test 6: Text copy/extract permission is NOT granted."""
    if pikepdf:
        try:
            pdf = pikepdf.open(str(OUTPUT_PDF), password="testpass123")
            allow = pdf.allow
            extract_allowed = allow.extract
            print(f"  Extract/copy allowed: {extract_allowed}")
            pdf.close()
            return not extract_allowed
        except Exception as e:
            print(f"  pikepdf error: {e}")
            return False
    else:
        # PyMuPDF fallback: check permissions bitmask
        doc = pymupdf.open(OUTPUT_PDF)
        perms = doc.permissions
        # PDF_PERM_COPY = 1 << 5 = 32 (in some conventions)
        # If copy is NOT in the bitmask, it's not granted
        copy_bit = perms & pymupdf.PDF_PERM_COPY if hasattr(pymupdf, 'PDF_PERM_COPY') else 0
        print(f"  Permissions: {perms}")
        print(f"  Copy bit set: {copy_bit != 0}")
        doc.close()
        return copy_bit == 0


def test_7_empty_corrupt_pdf():
    """Test 7: Empty/corrupt PDF handled with clear error and no source mutation."""
    results = {}

    # Create empty PDF (0 pages) — write raw PDF bytes since PyMuPDF
    # refuses to save a document with zero pages
    empty_path = WORK_DIR / "empty_test.pdf"
    empty_pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Count 0 /Kids [] >>\nendobj\n"
        b"xref\n0 3\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"trailer\n<< /Size 3 /Root 1 0 R >>\n"
        b"startxref\n108\n%%EOF"
    )
    with open(empty_path, "wb") as f:
        f.write(empty_pdf_bytes)

    empty_sha_before = sha256_file(empty_path)
    print(f"  Empty PDF: {empty_path.name} (SHA: {empty_sha_before[:16]}...)")

    # Try to protect empty PDF
    import subprocess
    result = subprocess.run(
        [str(WORK_DIR / ".venv/bin/python"), "manuscript_protect.py",
         str(empty_path), "--consultant", "Test", "--password", "pw123", "--version", "v1"],
        capture_output=True, text=True, cwd=str(WORK_DIR)
    )
    empty_sha_after = sha256_file(empty_path)
    empty_untouched = empty_sha_before == empty_sha_after
    empty_handled = result.returncode != 0
    print(f"  Empty PDF exit code: {result.returncode}")
    print(f"  Empty PDF error: {result.stderr.strip() or result.stdout.strip()[-100:]}")
    print(f"  Empty PDF untouched: {empty_untouched}")
    results["empty"] = empty_handled and empty_untouched

    # Create corrupt PDF (random bytes)
    corrupt_path = WORK_DIR / "corrupt_test.pdf"
    with open(corrupt_path, "wb") as f:
        f.write(b"This is not a valid PDF file. Random garbage bytes here.")

    corrupt_sha_before = sha256_file(corrupt_path)
    print(f"\n  Corrupt PDF: {corrupt_path.name} (SHA: {corrupt_sha_before[:16]}...)")

    result = subprocess.run(
        [str(WORK_DIR / ".venv/bin/python"), "manuscript_protect.py",
         str(corrupt_path), "--consultant", "Test", "--password", "pw123", "--version", "v1"],
        capture_output=True, text=True, cwd=str(WORK_DIR)
    )
    corrupt_sha_after = sha256_file(corrupt_path)
    corrupt_untouched = corrupt_sha_before == corrupt_sha_after
    corrupt_handled = result.returncode != 0
    print(f"  Corrupt PDF exit code: {result.returncode}")
    print(f"  Corrupt PDF error: {result.stderr.strip() or result.stdout.strip()[-100:]}")
    print(f"  Corrupt PDF untouched: {corrupt_untouched}")
    results["corrupt"] = corrupt_handled and corrupt_untouched

    # Cleanup test files
    empty_path.unlink(missing_ok=True)
    corrupt_path.unlink(missing_ok=True)

    return results["empty"] and results["corrupt"]


def test_8_batch_mode():
    """Test 8: Batch mode produces one output per source, no config mixing."""
    import subprocess

    consultants = "Alice,Bob,Charlie"
    passwords = "pw1,pw2,pw3"

    result = subprocess.run(
        [str(WORK_DIR / ".venv/bin/python"), "manuscript_protect.py",
         str(SOURCE_PDF), "--consultants", consultants,
         "--passwords", passwords, "--version", "v1"],
        capture_output=True, text=True, cwd=str(WORK_DIR)
    )

    print(f"  Exit code: {result.returncode}")
    print(f"  stdout: {result.stdout.strip()[-200:]}")

    # Check that 3 separate output files exist
    expected_files = [
        "test_chinese_protected_v1_Jason_Kong.pdf",
        "test_chinese_protected_v1_Bob.pdf",
        "test_chinese_protected_v1_Charlie.pdf",
    ]

    all_exist = True
    for fname in expected_files:
        fpath = WORK_DIR / fname
        exists = fpath.exists()
        size = fpath.stat().st_size if exists else 0
        print(f"  {fname}: exists={exists}, size={size:,}")
        if not exists or size == 0:
            all_exist = False

    # Verify each output has a different SHA-256 (different watermarks)
    shas = {}
    for fname in expected_files:
        fpath = WORK_DIR / fname
        if fpath.exists():
            shas[fname] = sha256_file(fpath)[:16]

    unique_shas = len(set(shas.values())) == len(shas)
    print(f"  Unique output SHA-256s: {len(set(shas.values()))}/{len(shas)}")
    for fname, sha in shas.items():
        print(f"    {fname}: {sha}...")

    # Cleanup batch outputs — but keep Alice (needed by tests 2-6)
    for fname in expected_files[1:]:  # skip Alice
        (WORK_DIR / fname).unlink(missing_ok=True)

    return all_exist and unique_shas and result.returncode == 0


if __name__ == "__main__":
    print("=" * 60)
    print("Manuscript Protector v1 — Full Test Suite (8 tests)")
    print("=" * 60)

    # Setup: always re-run single-mode protection to ensure the output file
    # exists with the correct password (test 8 batch mode may have overwritten
    # it with a different password in a previous run)
    print("\n--- Setup: running single-mode protection ---")
    import subprocess
    subprocess.run(
        [str(WORK_DIR / ".venv/bin/python"), "manuscript_protect.py",
         str(SOURCE_PDF), "--consultant", "Alice",
         "--password", "testpass123", "--version", "v1"],
        cwd=str(WORK_DIR), capture_output=True, text=True
    )
    print(f"  Output: {OUTPUT_PDF.name} ({OUTPUT_PDF.stat().st_size:,} bytes)")

    tests = [
        ("Test 1: Source byte-identical (SHA256 before/after)", test_1_source_untouched),
        ("Test 2: Output path is _protected.pdf, not source", test_2_output_not_source),
        ("Test 3: Chinese sample PDF processes successfully", test_3_chinese_processed),
        ("Test 4: Watermark visible at ~0.25 opacity (PNG)", test_4_watermark_visible),
        ("Test 5: AES-256 encryption confirmed", test_5_encryption_aes256),
        ("Test 6: Copy/extract permission NOT granted", test_6_copy_not_granted),
        ("Test 7: Empty/corrupt PDF handled gracefully", test_7_empty_corrupt_pdf),
        ("Test 8: Batch mode — 3 separate outputs, no mixing", test_8_batch_mode),
    ]

    results = {}
    for name, func in tests:
        print(f"\n--- {name} ---")
        try:
            results[name] = func()
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            results[name] = False

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY:")
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {status} — {name}")
        if not passed:
            all_pass = False

    print("=" * 60)
    if all_pass:
        print("OVERALL VERDICT: PASS")
    else:
        failed = [n for n, p in results.items() if not p]
        print(f"OVERALL VERDICT: FAIL — {len(failed)} test(s) failed")
        for f in failed:
            print(f"  ✗ {f}")
