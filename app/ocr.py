"""Words from the page image (Tesseract, Georgian + English) for pages without a text layer —
scans and plans printed to an image — so their room labels ("საძინებელი 14.2 მ²", "OPEN OFFICE
114 27.54 m²") reach the same pipeline as vector text.

Room labels are scattered single words, so Tesseract runs in sparse-text mode (--psm 11) on a
page rendered at OCR_SCALE; words below MIN_CONF are dropped (hatching and door swings read as
stray letters at low confidence).
"""

import csv
import io
import shutil
import subprocess

import cv2
import fitz

from .image_walls import page_gray

OCR_SCALE = 4.0          # px per point (≈ 290 dpi): plan labels are ~6 pt, Tesseract wants ~25 px
LANGS = "kat+eng"
MIN_CONF = 55
TIMEOUT_S = 240


def available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_words(page: fitz.Page, scale: float = OCR_SCALE) -> list:
    """extract.Word list in display points (font "ocr", layer "")."""
    from .extract import Word
    if not available():
        return []
    ok, png = cv2.imencode(".png", page_gray(page, scale))
    if not ok:
        return []
    out = subprocess.run(["tesseract", "stdin", "stdout", "-l", LANGS, "--psm", "11", "tsv"],
                         input=png.tobytes(), capture_output=True, timeout=TIMEOUT_S, check=False)
    words = []
    for row in csv.DictReader(io.StringIO(out.stdout.decode("utf-8", "replace")), delimiter="\t",
                              quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if row.get("level") != "5" or not text or float(row.get("conf") or -1) < MIN_CONF:
            continue
        x, y, w, h = (int(row[k]) / scale for k in ("left", "top", "width", "height"))
        words.append(Word(text, None, (x, y, x + w, y + h), "", "ocr", h))
    return words
