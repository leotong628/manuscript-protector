# Manuscript Protector

Convert manuscripts into watermarked, copy-protected, AES-encrypted PDFs.

## Features

- **Watermark** — semi-transparent diagonal grid + footer, baked into pixel data, auto-split into multiple lines for long text
- **Copy protection** — renders pages to JPEG images, removing the selectable text layer
- **AES-128 encryption** — password-protected, copy/extract/print blocked (viewer-enforced)
- **Web UI** — browser-based drag-and-drop interface with live preview
- **CLI** — command-line tool for scripting and batch processing
- **Profile system** — customizable page size, font, margins, watermark appearance
- **CJK support** — renders Chinese/Japanese/Korean text correctly using macOS system fonts
- **Source file integrity** — SHA-256 verified before and after; source file is never modified
- **Receipt** — paired .md receipt with all metadata, no password stored

## Requirements

- **macOS** (uses macOS system CJK fonts: STHeiti, Songti, Hiragino Sans GB)
- **Python 3.11+**

## Installation

```bash
git clone https://github.com/leotong628/manuscript-protector.git
cd manuscript-protector
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

## Usage

### Web UI (recommended)

```bash
.venv/bin/python app.py
```

Open http://localhost:5111 in your browser.

1. Drag a file (.md, .txt, or .pdf) onto the page
2. Fill in: receiver name, password (type twice to confirm), version
3. Optional: watermark text, profile, encryption, DPI, JPEG quality
4. Customize font size, line height, margins, watermark appearance
5. Click "Preview Sample Page" to see how it looks
6. Click "Protect Manuscript" to generate the protected PDF
7. Download the protected PDF + receipt

### CLI

```bash
# Single file
MANUSCRIPT_PASSWORD='yourPassword' .venv/bin/python protect_any.py manuscript.md \
  --consultant "Alice" --version v1 --profile mobile

# Batch mode
MANUSCRIPT_PASSWORD='pw' .venv/bin/python protect_any.py manuscript.pdf \
  --consultants "Alice,Bob,Charlie" \
  --passwords "pw1,pw2,pw3" --version v1

# Custom watermark
MANUSCRIPT_PASSWORD='pw' .venv/bin/python protect_any.py manuscript.md \
  --consultant "Alice" --version v1 \
  --watermark-text "FOR ALICE ONLY" --label "PRIVATE"

# Config file mode
.venv/bin/python protect_any.py manuscript.pdf --config consultants.json --version v1
```

### Password handling

- Password is obtained via hidden prompt or `MANUSCRIPT_PASSWORD` environment variable
- Password is **never** printed, written to receipt, stored in metadata, or logged
- Deliver the password via a different channel than the file

## Profiles

| Profile | Page | Font | Line Height | DPI | Use Case |
|---------|------|------|-------------|-----|----------|
| `default` | A4 | 12pt | 1.5 | 200 | Desktop reading |
| `mobile` | A5 | 14pt | 1.8 | 150 | Phone/mobile reading |
| `print` | A4 | 13pt | 1.6 | 200 | Printing |

Create your own profile by copying `profiles/default.json` to `profiles/myprofile.json` and editing.

## Output

Protected PDFs are saved to `exports/YYYY-MM-DD/` by default. Override with `MANUSCRIPT_EXPORTS_DIR` environment variable.

Each run produces:
- `{filename}_protected_{version}_{receiver}.pdf` — the protected PDF
- `{filename}_protected_{version}_{receiver}.receipt.md` — the receipt (no password)

## Testing

```bash
# CJK font gate test
.venv/bin/python test_watermark.py

# V1 workflow tests (9 tests)
.venv/bin/python test_v1_workflow.py

# Original build tests (8 tests)
.venv/bin/python run_all_tests.py
```

## How It Works

```
Input (.md/.txt/.pdf)
  → [If .md/.txt] Render to PDF with profile settings
  → Watermark every page (diagonal grid + footer)
  → Render to JPEG images (removes text layer)
  → Encrypt with AES-128
  → Write receipt
  → Verify source SHA-256 unchanged
  → Output
```

## Caveats

- PDF permissions are viewer-enforced deterrence, not DRM. The image conversion (no text layer) is the real copy-protection layer.
- Metadata can be stripped; it's an audit trail, not a security boundary.
- Screenshots cannot be prevented by software. The watermark provides traceability.
- AES-128 is used instead of AES-256 for macOS Preview compatibility.

## License

AGPL-3.0 — required because PyMuPDF (the PDF engine) is AGPL-3.0.
