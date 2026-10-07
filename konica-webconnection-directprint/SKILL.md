---
name: konica-webconnection-directprint
description: "Use when printing a local file through a Konica Minolta bizhub Web Connection (Direct Print) UI. Headless Chromium/CDP, no driver or CUPS needed."
version: 1.0.0
license: MIT
---

# Konica Minolta Web Connection Direct Print

Use this skill when the user wants a local file printed via a Konica Minolta Web Connection direct-print page. Handy when the local print stack (CUPS/drivers) is broken or missing.

## Known target

- Tested on: Konica Minolta `bizhub C3350i` (other i-Series bizhub models use the same Web Connection SPA)
- URL: `https://<printer-ip>/wcd/spa_main.html` (set `KM_WCD_URL` or pass `--url`)
- Web UI title: `Web Connection`
- Cert is old/weak; tooling must ignore HTTPS certificate errors.
- Direct-print SPA screen id: `013_000_DIP000`
- Direct-print template: `/wcd/spa_013_000_DIP000.tmpl.html`
- Login mode used by this workflow: `PublicUser` / public user access.

## Supported input formats

The device UI accepts directly: `xps`, `pdf`, `tif`, `tiff`, `pcl`, `txt`, `ps`, `jpg`, `jpeg`, `docx`, `xlsx`, `pptx`, `zip`, `ppml`, `vdx`.

## Safety rule

Direct print is a real-world side effect. If the user provided a concrete file and clearly asked to print it, execution is allowed. If intent is ambiguous, run the helper script without `--execute` first and ask before submitting.

## Preferred automation

Use the bundled helper script:

```bash
export KM_WCD_URL=https://<printer-ip>/wcd/spa_main.html
python scripts/km_directprint_cdp.py /absolute/path/to/file.pdf
```

This is a dry run. It logs into the web UI, opens Direktdruck, sets the file input, and verifies the file is ready without clicking OK.

To actually print:

```bash
python scripts/km_directprint_cdp.py /absolute/path/to/file.pdf --execute
```

Options:

- `--copies N` — number of copies, default `1`.
- `--duplex` — request duplex instead of default/simplex.
- `--tray Auto|...` — paper tray value; default UI value is `Auto`.
- `--url URL` — override the Web Connection URL.
- `--chrome PATH` — override Chromium path; default `/snap/bin/chromium`.

For a quick smoke-test PDF, use the bundled ReportLab generator:

```bash
python scripts/make_hello_world_pdf.py ~/print-tests/hello_world_test.pdf
python scripts/km_directprint_cdp.py ~/print-tests/hello_world_test.pdf --execute
```

## What the helper does

1. Starts headless Chromium with `--ignore-certificate-errors` and a temporary profile.
2. Navigates to the Web Connection URL.
3. Clicks public-user login button `ID_LGI_LOGIN_BT` inside the iframe.
4. Calls `spa_load_contents('013_000_DIP000')` to open Direct Print.
5. Finds the iframe context containing file input `P7_F_FI`.
6. Uses Chrome DevTools Protocol `DOM.setFileInputFiles` with the file input `objectId`.
7. Sets basic options, e.g. copies in `ID_P_PRI_BPN`.
8. With `--execute`, clicks `ID_OK_P_PRI_SET` and watches for `result.html` / `UpdatePrintExecuteFlgByCgi` signals.

## Important UI / endpoint details discovered

- File upload form: `FROM_ID_P7_DIP`, action `i_file.cgi`, method `POST`, multipart, file field `P7_F_FIL` / id `P7_F_FI`.
- Print settings form: `P_PRI_SUB`, action `user.cgi`, hidden `func=PSL_P_PRI_BST`, hidden token `h_token` (`h_tkn_p`).
- Page-init/inspection form: `P_PRI_IN`, `func=PSL_P_PRI_DIV`.
- The OK button triggers `spaTemplate.inherent.submitCGI()` via `ID_OK_P_PRI_SET`.
- Default useful values observed:
  - copies `ID_P_PRI_BPN = 1`
  - sort `ID_P_PRI_BSR` checked / On
  - tray `ID_P_PRI_BTR = Auto`
  - print side `ID_P_PRI_BDL = Simplex`
  - output mode `ID_P_PRI_R_OMD = Normal`
  - inspect data `inspect_data = 0`

## Verification before claiming success

- Dry-run success prints JSON with `"ready": true` and `filename` equal to the basename.
- Execute success should print JSON with `"submitted": true`; if `observed_result_signal` is false, say the job was submitted but the web UI did not expose a clear result signal before timeout.
- Do not claim the physical paper came out unless the user confirms or a job-history/status endpoint was separately checked.

## Path handling / Snap Chromium pitfall

Do **not** print files from `/tmp` when using `/snap/bin/chromium`. Snap Chromium can see a private `/tmp` namespace, so `file:///tmp/...` or file uploads from `/tmp` may resolve incorrectly and print a Chrome `ERR_FILE_NOT_FOUND` page instead of the intended document.

For generated print files, write them under a normal home path first, e.g.:

```bash
mkdir -p $HOME/print-tests
# create $HOME/print-tests/file.pdf
python scripts/km_directprint_cdp.py $HOME/print-tests/file.pdf --execute
```

If the user reports a page saying `Zugriff auf die Datei nicht möglich` / `ERR_FILE_NOT_FOUND`, regenerate the PDF under `$HOME/print-tests/` and submit that path.

## Troubleshooting

### Problematic PDFs that crash local print dialogs

When the user reports that a PDF crashes multiple local printer programs, first create a print-safe copy instead of sending the original unchanged. A reliable workflow is:

```bash
mkdir -p $HOME/print-fixes
SRC=/absolute/path/to/input.pdf
BASE=$(basename "$SRC" .pdf)

# Light repair/rewrite: normalizes PDF version/objects while preserving vectors/text.
gs -o "$HOME/print-fixes/${BASE}_repariert.pdf" \
  -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 -dPDFSETTINGS=/prepress \
  -dDetectDuplicateImages=true -dCompressFonts=true -dSubsetFonts=true "$SRC"

# Hard fallback: rasterize to PNG pages, then re-wrap as PDF; this avoids buggy PDF objects.
pdftocairo -png -r 300 "$SRC" "$HOME/print-fixes/${BASE}_page"
python3 - <<'PY'
from PIL import Image
from pathlib import Path
import os
outdir = Path.home() / 'print-fixes'
base = Path(os.environ.get('BASE', 'document')).stem
imgs = sorted(outdir.glob(f'{base}_page-*.png'))
images = [Image.open(p).convert('RGB') for p in imgs]
if not images:
    raise SystemExit('No rasterized pages found')
images[0].save(outdir / f'{base}_gerastert_300dpi.pdf', 'PDF', resolution=300.0, save_all=True, append_images=images[1:])
PY
```

## More troubleshooting

- If the user reports that **all programs freeze or hang when clicking Print/Drucken**, do not treat it as a document-specific PDF problem first. Inspect the local Linux print stack (CUPS, Snap CUPS, print portals, stale queues). This Web Connection workflow is a useful workaround because it bypasses the local print dialog entirely.
- If page hangs, verify the printer is reachable:
  ```bash
  python - <<'PY'
  import os, requests
  r=requests.get(os.environ['KM_WCD_URL'], verify=False, timeout=20)
  print(r.status_code, r.text[:80])
  PY
  ```
- If Chromium fails, check `/snap/bin/chromium`; fallback commands can use `chromium`, `chromium-browser`, or `google-chrome`.
- Do not rely on Snap Chromium `--print-to-pdf=/tmp/...` for generating smoke-test PDFs: in this environment it reported bytes written but the host `/tmp` file was missing. Use `scripts/make_hello_world_pdf.py` / ReportLab instead.
- If file input cannot be set, use `DOM.setFileInputFiles` with the `objectId` returned by evaluating `document.getElementById("P7_F_FI")` in the iframe context; `nodeId` can fail across iframes.
