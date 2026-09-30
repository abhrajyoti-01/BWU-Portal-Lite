import sys

import cv2
import numpy as np

try:
    import ddddocr

    _OCR = ddddocr.DdddOcr(show_ad=False)
    ENGINE = "ddddocr"
except Exception:
    _OCR = None
    try:
        import pytesseract  # noqa: F401

        ENGINE = "tesseract"
    except Exception:
        ENGINE = "none"

_TESSERACT_CONFIG = (
    "--psm 8 -c tessedit_char_whitelist="
    "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
)


def engine():
    return ENGINE


def _decode(png_bytes: bytes):
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("cannot decode image")
    return img


def _encode(img) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("image encode failed")
    return buf.tobytes()


def _otsu2x(img) -> bytes:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.medianBlur(g, 3)
    _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if float(th.mean()) < 127.0:
        th = 255 - th
    th = cv2.resize(th, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    return _encode(th)


def _autocontrast(img) -> bytes:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lo, hi = np.percentile(g, [5, 95])
    if hi <= lo:
        hi = lo + 1.0
    g = np.clip((g.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
    return _encode(g)


def preprocess(png_bytes: bytes) -> bytes:
    return _otsu2x(_decode(png_bytes))


def solve(png_bytes: bytes, upper: bool = False) -> str:
    img = _decode(png_bytes)
    if ENGINE == "ddddocr":
        votes = {}
        for variant in (png_bytes, _otsu2x(img), _autocontrast(img)):
            text = "".join(_OCR.classification(variant).split())
            if text:
                votes.setdefault(text.upper(), []).append(text)
        if not votes:
            raise RuntimeError("ddddocr returned empty text")
        best_key = max(votes, key=lambda k: (len(votes[k]), len(k) == 6))
        text = max(votes[best_key], key=lambda t: sum(1 for c in t if c.isupper()))
    elif ENGINE == "tesseract":
        import pytesseract

        text = "".join(
            pytesseract.image_to_string(_otsu2x(img), config=_TESSERACT_CONFIG).split()
        )
    else:
        raise RuntimeError("no OCR engine available (install ddddocr or pytesseract+tesseract)")
    return text.upper() if upper else text


if __name__ == "__main__":
    import argparse
    import pathlib

    parser = argparse.ArgumentParser(description="Solve a text-captcha image")
    parser.add_argument("image")
    parser.add_argument("--upper", action="store_true")
    args = parser.parse_args()
    data = pathlib.Path(args.image).read_bytes()
    try:
        text = solve(data, upper=args.upper)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"engine: {engine()}")
    print(f"text:   {text}")
