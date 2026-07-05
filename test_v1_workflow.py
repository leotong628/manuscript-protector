#!/usr/bin/env python3
"""
test_v1_workflow.py — V1 workflow test suite (9 tests)
Tests the protect_any.py user-facing wrapper.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import pymupdf
except ImportError:
    print("FAIL: pymupdf not installed")
    sys.exit(1)

try:
    import pikepdf
except ImportError:
    pikepdf = None

WORK_DIR = Path(__file__).parent
VENV_PYTHON = str(WORK_DIR / ".venv/bin/python")
PROTECT_ANY = str(WORK_DIR / "protect_any.py")
EXPORTS_BASE = Path(os.environ.get("MANUSCRIPT_EXPORTS_DIR", "exports"))

# Test password — used via env var, never on command line
TEST_PASSWORD = "testpass123"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def run_protect(input_file, consultant="Test Consultant", version="v1test",
                profile=None, watermark_text=None, label=None,
                password=TEST_PASSWORD, extra_args=None):
    """Run protect_any.py with given args. Returns (returncode, stdout, stderr)."""
    env = os.environ.copy()
    env["MANUSCRIPT_PASSWORD"] = password

    cmd = [VENV_PYTHON, PROTECT_ANY, str(input_file),
           "--consultant", consultant, "--version", version]
    if profile:
        cmd.extend(["--profile", profile])
    if watermark_text:
        cmd.extend(["--watermark-text", watermark_text])
    if label:
        cmd.extend(["--label", label])
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(cmd, capture_output=True, text=True, env=env,
                           cwd=str(WORK_DIR))
    return result.returncode, result.stdout, result.stderr


def find_output(input_stem, consultant, version):
    """Find the output PDF in today's Exports folder."""
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    consultant_safe = "".join(c if c.isalnum() else "_" for c in consultant)
    pattern = f"{input_stem}_protected_{version}_{consultant_safe}"
    search_dir = EXPORTS_BASE / date_str
    if not search_dir.exists():
        return None, None
    for f in search_dir.iterdir():
        if f.stem.startswith(pattern) and f.suffix == ".pdf":
            receipt = f.with_suffix(".receipt.md")
            return f, receipt
    return None, None


def cleanup_outputs(consultant="Test Consultant", version="v1test"):
    """Clean up test outputs from Exports folder."""
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    search_dir = EXPORTS_BASE / date_str
    if not search_dir.exists():
        return
    consultant_safe = "".join(c if c.isalnum() else "_" for c in consultant)
    for f in search_dir.iterdir():
        if consultant_safe in f.name and version in f.name:
            f.unlink(missing_ok=True)
        elif "Test_Consultant" in f.name:
            f.unlink(missing_ok=True)


# --- Test files setup ---

def create_test_md():
    """Create a test markdown file."""
    path = WORK_DIR / "test_sample.md"
    content = """# Test Manuscript

This is a test manuscript for the V1 workflow test suite.

## Chapter 1

Lorem ipsum dolor sit amet, consectetur adipiscing elit.
Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.

中文測試文本：天地玄黃，宇宙洪荒。

## Chapter 2

Ut enim ad minim veniam, quis nostrud exercitation ullamco.
Duis aute irure dolor in reprehenderit in voluptate velit.

---

End of test manuscript.
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def create_test_txt():
    """Create a test text file."""
    path = WORK_DIR / "test_sample.txt"
    content = """Test Manuscript (Plain Text)

This is a test plain text file for the V1 workflow test suite.

Chapter 1: Lorem ipsum dolor sit amet, consectetur adipiscing elit.
Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.

中文測試文本：天地玄黃，宇宙洪荒。

Chapter 2: Ut enim ad minim veniam, quis nostrud exercitation ullamco.
Duis aute irure dolor in reprehenderit in voluptate velit.

End of test manuscript.
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def create_test_pdf():
    """Create a test PDF using make_test_pdf.py."""
    path = WORK_DIR / "test_sample.pdf"
    result = subprocess.run(
        [VENV_PYTHON, "make_test_pdf.py", "--name", "TestMan", "--output", str(path), "--pages", "2"],
        capture_output=True, text=True, cwd=str(WORK_DIR)
    )
    return path


# --- Tests ---

def test_1_md_to_protected_pdf():
    """Test 1: md input exports to protected PDF."""
    md_path = create_test_md()
    md_sha_before = sha256_file(md_path)

    rc, stdout, stderr = run_protect(md_path, consultant="TestMD", version="v1test")
    if rc != 0:
        print(f"  FAIL: exit code {rc}")
        print(f"  stderr: {stderr[:200]}")
        return False

    pdf, receipt = find_output("test_sample", "TestMD", "v1test")
    if not pdf or not pdf.exists():
        print(f"  FAIL: output PDF not found")
        return False

    # Verify it's a valid encrypted PDF
    doc = pymupdf.open(pdf)
    if not doc.is_encrypted:
        print(f"  FAIL: output not encrypted")
        doc.close()
        return False
    auth = doc.authenticate(TEST_PASSWORD)
    if not auth:
        print(f"  FAIL: cannot authenticate")
        doc.close()
        return False
    pages = doc.page_count
    doc.close()

    # Verify source md unchanged
    md_sha_after = sha256_file(md_path)
    if md_sha_before != md_sha_after:
        print(f"  FAIL: source md changed")
        return False

    print(f"  Output: {pdf.name} ({pdf.stat().st_size:,} bytes, {pages} pages)")
    print(f"  Source md SHA-256 unchanged: {md_sha_before == md_sha_after}")
    return True


def test_2_txt_to_protected_pdf():
    """Test 2: txt input exports to protected PDF."""
    txt_path = create_test_txt()
    txt_sha_before = sha256_file(txt_path)

    rc, stdout, stderr = run_protect(txt_path, consultant="TestTXT", version="v1test")
    if rc != 0:
        print(f"  FAIL: exit code {rc}")
        print(f"  stderr: {stderr[:200]}")
        return False

    pdf, receipt = find_output("test_sample", "TestTXT", "v1test")
    if not pdf or not pdf.exists():
        print(f"  FAIL: output PDF not found")
        return False

    doc = pymupdf.open(pdf)
    if not doc.is_encrypted:
        print(f"  FAIL: output not encrypted")
        doc.close()
        return False
    doc.close()

    txt_sha_after = sha256_file(txt_path)
    print(f"  Output: {pdf.name} ({pdf.stat().st_size:,} bytes)")
    print(f"  Source txt SHA-256 unchanged: {txt_sha_before == txt_sha_after}")
    return txt_sha_before == txt_sha_after


def test_3_pdf_direct_protect():
    """Test 3: pdf input protects directly."""
    pdf_path = create_test_pdf()
    pdf_sha_before = sha256_file(pdf_path)

    rc, stdout, stderr = run_protect(pdf_path, consultant="TestPDF", version="v1test")
    if rc != 0:
        print(f"  FAIL: exit code {rc}")
        print(f"  stderr: {stderr[:200]}")
        return False

    out, receipt = find_output("test_sample", "TestPDF", "v1test")
    if not out or not out.exists():
        print(f"  FAIL: output not found")
        return False

    pdf_sha_after = sha256_file(pdf_path)
    print(f"  Output: {out.name} ({out.stat().st_size:,} bytes)")
    print(f"  Source pdf SHA-256 unchanged: {pdf_sha_before == pdf_sha_after}")
    return pdf_sha_before == pdf_sha_after


def test_4_source_unchanged():
    """Test 4: source file unchanged after protection (all 3 types)."""
    results = []

    for ext, creator in [(".md", create_test_md), (".txt", create_test_txt), (".pdf", create_test_pdf)]:
        path = WORK_DIR / f"test_sample{ext}"
        if not path.exists():
            path = creator()
        sha_before = sha256_file(path)
        rc, _, _ = run_protect(path, consultant="TestUnchanged", version="v1test")
        sha_after = sha256_file(path)
        unchanged = sha_before == sha_after
        results.append(unchanged)
        print(f"  {ext}: SHA unchanged = {unchanged}")

    return all(results)


def test_5_password_required():
    """Test 5: password required — tool fails without it."""
    md_path = create_test_md()

    # Run without MANUSCRIPT_PASSWORD env var and without --password
    env = os.environ.copy()
    env.pop("MANUSCRIPT_PASSWORD", None)

    cmd = [VENV_PYTHON, PROTECT_ANY, str(md_path),
           "--consultant", "TestNoPass", "--version", "v1test"]
    # This will try to prompt for password via getpass, which will get EOF
    # in subprocess and should fail
    result = subprocess.run(cmd, capture_output=True, text=True, env=env,
                           cwd=str(WORK_DIR), input="")

    # Should fail (non-zero exit) because no password provided
    print(f"  Exit code without password: {result.returncode}")
    print(f"  stderr: {result.stderr.strip()[:100]}")
    return result.returncode != 0


def test_6_copy_blocked():
    """Test 6: copy/extract blocked in protected output."""
    md_path = create_test_md()
    rc, _, _ = run_protect(md_path, consultant="TestCopy", version="v1test")
    if rc != 0:
        print(f"  FAIL: protection failed")
        return False

    pdf, _ = find_output("test_sample", "TestCopy", "v1test")
    if not pdf:
        print(f"  FAIL: output not found")
        return False

    if pikepdf:
        pf = pikepdf.open(str(pdf), password=TEST_PASSWORD)
        extract_allowed = pf.allow.extract
        pf.close()
        print(f"  Extract allowed: {extract_allowed}")
        return not extract_allowed
    else:
        doc = pymupdf.open(pdf)
        auth = doc.authenticate(TEST_PASSWORD)
        # Try to extract text from page 0
        if auth:
            page = doc[0]
            text = page.get_text()
            # Image-based PDF should have no extractable text
            print(f"  Extracted text length: {len(text)}")
            doc.close()
            return len(text.strip()) == 0
        doc.close()
        return False


def test_7_mobile_profile_changes_layout():
    """Test 7: mobile profile changes font/layout vs default."""
    md_path = create_test_md()

    # Protect with default profile
    rc1, _, _ = run_protect(md_path, consultant="TestDefault", version="v1test",
                            profile="default")
    # Protect with mobile profile
    rc2, _, _ = run_protect(md_path, consultant="TestMobile", version="v1test",
                            profile="mobile")

    if rc1 != 0 or rc2 != 0:
        print(f"  FAIL: protection failed (default rc={rc1}, mobile rc={rc2})")
        return False

    pdf_default, _ = find_output("test_sample", "TestDefault", "v1test")
    pdf_mobile, _ = find_output("test_sample", "TestMobile", "v1test")

    if not pdf_default or not pdf_mobile:
        print(f"  FAIL: outputs not found")
        return False

    # Compare page sizes — mobile should be A5 (420x595), default A4 (595x842)
    doc_d = pymupdf.open(pdf_default)
    doc_d.authenticate(TEST_PASSWORD)
    page_d = doc_d[0]
    d_w, d_h = page_d.rect.width, page_d.rect.height
    doc_d.close()

    doc_m = pymupdf.open(pdf_mobile)
    doc_m.authenticate(TEST_PASSWORD)
    page_m = doc_m[0]
    m_w, m_h = page_m.rect.width, page_m.rect.height
    doc_m.close()

    print(f"  Default page: {d_w}x{d_h}")
    print(f"  Mobile page:  {m_w}x{m_h}")

    # Mobile should have different (smaller) page dimensions
    return (d_w != m_w) or (d_h != m_h)


def test_8_custom_watermark():
    """Test 8: custom watermark appears in protected output."""
    md_path = create_test_md()
    custom_wm = "CUSTOM_WATERMARK_TEST_XYZ"

    rc, _, _ = run_protect(md_path, consultant="TestCustomWM", version="v1test",
                           watermark_text=custom_wm)
    if rc != 0:
        print(f"  FAIL: protection failed")
        return False

    pdf, _ = find_output("test_sample", "TestCustomWM", "v1test")
    if not pdf:
        print(f"  FAIL: output not found")
        return False

    # Check that custom watermark text is in the PDF metadata
    doc = pymupdf.open(pdf)
    doc.authenticate(TEST_PASSWORD)
    meta = doc.metadata
    doc.close()

    # The watermark text should appear in metadata keywords
    keywords = meta.get("keywords", "")
    print(f"  Metadata keywords: {keywords[:100]}...")
    return custom_wm in keywords


def test_9_receipt_no_password():
    """Test 9: receipt is written and contains no password."""
    md_path = create_test_md()
    rc, _, _ = run_protect(md_path, consultant="TestReceipt", version="v1test")
    if rc != 0:
        print(f"  FAIL: protection failed")
        return False

    pdf, receipt = find_output("test_sample", "TestReceipt", "v1test")
    if not receipt or not receipt.exists():
        print(f"  FAIL: receipt not found")
        return False

    receipt_content = receipt.read_text(encoding="utf-8")

    # Check receipt contains required fields
    has_input = "Source file" in receipt_content
    has_output = "Protected PDF" in receipt_content
    has_source_sha = "Source SHA-256" in receipt_content
    has_output_sha = "Output SHA-256" in receipt_content
    has_profile = "Profile" in receipt_content
    has_consultant = "Consultant" in receipt_content
    has_password_note = "not stored" in receipt_content.lower()
    has_verification = "Source untouched" in receipt_content

    # Check password is NOT in the receipt
    password_not_in_receipt = TEST_PASSWORD not in receipt_content

    print(f"  Receipt: {receipt.name} ({receipt.stat().st_size} bytes)")
    print(f"  Has input path:      {has_input}")
    print(f"  Has output path:     {has_output}")
    print(f"  Has source SHA-256:  {has_source_sha}")
    print(f"  Has output SHA-256:  {has_output_sha}")
    print(f"  Has profile:         {has_profile}")
    print(f"  Has consultant:      {has_consultant}")
    print(f"  Has password note:   {has_password_note}")
    print(f"  Has verification:    {has_verification}")
    print(f"  Password NOT in receipt: {password_not_in_receipt}")

    return (has_input and has_output and has_source_sha and has_output_sha
            and has_profile and has_consultant and has_password_note
            and has_verification and password_not_in_receipt)


# --- Main ---

if __name__ == "__main__":
    print("=" * 60)
    print("Manuscript Protector V1 — Workflow Test Suite (9 tests)")
    print("=" * 60)

    # Cleanup any previous test outputs
    cleanup_outputs()

    tests = [
        ("Test 1: md input → protected PDF", test_1_md_to_protected_pdf),
        ("Test 2: txt input → protected PDF", test_2_txt_to_protected_pdf),
        ("Test 3: pdf input → protected directly", test_3_pdf_direct_protect),
        ("Test 4: source file unchanged (all types)", test_4_source_unchanged),
        ("Test 5: password required", test_5_password_required),
        ("Test 6: copy/extract blocked", test_6_copy_blocked),
        ("Test 7: mobile profile changes layout", test_7_mobile_profile_changes_layout),
        ("Test 8: custom watermark appears", test_8_custom_watermark),
        ("Test 9: receipt written, no password", test_9_receipt_no_password),
    ]

    results = {}
    for name, func in tests:
        print(f"\n--- {name} ---")
        try:
            results[name] = func()
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False

    # Cleanup
    cleanup_outputs()

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
