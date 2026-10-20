"""Extrait les logos Bernabé de la charte vectorielle et prépare les versions pour fond bleu.

Usage (WSL, env generation_visuel) :
    python scripts/extract_bernabe_logos.py "data/sources/bernabe/BERNABE CHARTE GRAPHIQUE bis .pdf"

Officiels (rendus tels quels, fond transparent) : variante verticale, horizontale, verticale + « CÔTE D'IVOIRE ».
Dérivés (charte p. 15, « mise en situation » sur fond de couleur) : mot « Bernabé » et nom du pays en blanc,
filet blanc autour du carré.
"""
import sys
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "data" / "brands" / "bernabe" / "logos"
PREVIEW = 510.24 / 927  # points PDF par pixel des aperçus de page (927 px de large) utilisés pour les repères


def render(doc, page_number, box, width_px):
    """Rendu vectoriel d'une zone de page (repérée en pixels d'aperçu), recadré au plus juste."""
    clip = pymupdf.Rect(*(v * PREVIEW for v in box))
    zoom = width_px / clip.width
    pix = doc[page_number - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=True)
    img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
    return img.crop(img.getchannel("A").getbbox())


def square_extent(img, axis):
    """Longueur du carré bleu opaque depuis l'origine, en lignes (axis=0) ou colonnes (axis=1)."""
    alpha = np.asarray(img.getchannel("A"))
    opaque = (alpha > 250).mean(axis=1 - axis) > 0.9  # le bord peut être lissé : on part de la 1re ligne pleine
    start = int(np.argmax(opaque))
    rest = opaque[start:]
    return start + (int(np.argmin(rest)) if not rest.all() else len(rest))


def whiten(img, box):
    """Passe en blanc les pixels non rouges d'une zone (le rouge de l'accent est conservé), alpha inchangé."""
    a = np.asarray(img).copy()
    x0, y0, x1, y1 = box
    zone = a[y0:y1, x0:x1]
    red = (zone[:, :, 0] > 150) & (zone[:, :, 1] < 90)
    zone[~red, :3] = 255
    return Image.fromarray(a)


def with_filet(img, side):
    """Filet blanc autour du carré (côté `side` px), à l'extérieur du carré."""
    t = max(2, round(side * 0.02))
    out = Image.new("RGBA", (img.width + 2 * t, img.height + 2 * t), (0, 0, 0, 0))
    ImageDraw.Draw(out).rectangle((0, 0, side + 2 * t - 1, side + 2 * t - 1), outline=(255, 255, 255, 255), width=t)
    out.alpha_composite(img, (t, t))
    return out


def main(pdf: Path):
    doc = pymupdf.open(pdf)
    OUT.mkdir(parents=True, exist_ok=True)
    vertical = render(doc, 8, (355, 430, 650, 725), 1600)
    horizontal = render(doc, 8, (160, 895, 795, 1020), 2400)
    country = render(doc, 12, (72, 905, 220, 1080), 1200)
    vertical.save(OUT / "logo_vertical.png")
    horizontal.save(OUT / "logo_horizontal.png")
    country.save(OUT / "logo_vertical_cote_ivoire.png")

    # Cartouche des publications : carré + filet blanc, « CÔTE D'IVOIRE » en blanc dessous
    side = square_extent(country, axis=0)
    white_country = whiten(country, (0, side, country.width, country.height))
    with_filet(white_country, side).save(OUT / "logo_cartouche_blanc.png")

    # Horizontal pour fond bleu : « Bernabé » en blanc, filet autour du carré
    sq = square_extent(horizontal, axis=1)
    white_h = whiten(horizontal, (sq, 0, horizontal.width, horizontal.height))
    with_filet(white_h, sq).save(OUT / "logo_horizontal_blanc.png")
    for f in sorted(OUT.glob("*.png")):
        print(f.name, Image.open(f).size)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
