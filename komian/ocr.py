"""Relecture OCR des textes composés (EasyOCR, CPU). Facultatif : absent = contrôle non concluant."""
import difflib
import unicodedata
from functools import lru_cache

import numpy as np
from PIL import Image

READABLE_SIMILARITY = 0.85


class OcrUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _reader():
    try:
        import easyocr
    except ImportError as exc:
        raise OcrUnavailable("EasyOCR n'est pas installé.") from exc
    return easyocr.Reader(["fr"], gpu=False, verbose=False)


def fold(text: str) -> str:
    """Sans accents, casse ni ponctuation : l'OCR sert ici à juger la lisibilité, pas l'orthographe."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in text.casefold()).split())


def read_region(image: Image.Image, bbox, margin: int = 12) -> str:
    x0, y0, x1, y1 = bbox
    crop = image.crop((max(0, x0 - margin), max(0, y0 - margin),
                       min(image.width, x1 + margin), min(image.height, y1 + margin)))
    return " ".join(_reader().readtext(np.array(crop.convert("RGB")), detail=0, paragraph=True))


def similarity(expected: str, read: str) -> float:
    return difflib.SequenceMatcher(None, fold(expected), fold(read)).ratio()
