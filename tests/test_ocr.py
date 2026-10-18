"""OCR réel (lent : chargement du modèle EasyOCR). Ignoré si EasyOCR est absent."""
import pytest
from PIL import Image

from komian import ocr
from komian.brands import load_profile
from komian.compose import compose
from komian.models import Brief

pytest.importorskip("easyocr")


def test_composed_text_is_readable():
    brief = Brief(brand_id="mr_bricolage", objective="motiver", channel="Instagram", format_id="post_carre",
                  headline="L'envie vient souvent après l'action.",
                  exact_visual_text="LA MOTIVATION SUIT L'ACTION, PAS L'INVERSE",
                  visual_direction="Formes géométriques")
    comp = compose(load_profile("mr_bricolage"), brief, (1440, 1440), "citation_centree",
                   lambda size: Image.new("RGB", size, "white"))
    layer = next(l for l in comp.layers if l["role"] == "texte_exact")
    read = ocr.read_region(comp.image, layer["bbox"])
    assert ocr.similarity(brief.exact_visual_text, read) >= ocr.READABLE_SIMILARITY


def test_fold_ignores_accents_and_case():
    assert ocr.fold("LA MÊME ÉNERGIE !") == ocr.fold("la meme energie")
