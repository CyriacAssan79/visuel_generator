"""Traduction réelle (charge le modèle MarianMT, environ 300 Mo). Ignoré si transformers est absent."""
import pytest

pytest.importorskip("transformers")
pytest.importorskip("sentencepiece")

from komian.translate import translate_prompt  # noqa: E402


def test_french_scene_is_translated_with_trade_vocabulary():
    english, translated = translate_prompt(
        "Femme souriante en salopette qui peint un mur avec un rouleau, plan taille, regard vers l'objectif, "
        "établi en bois, photo réaliste")
    assert translated
    for term in ("overalls", "paint roller", "medium shot", "looking at the camera", "workbench"):
        assert term in english, english
    assert "TERM" not in english
    assert "gentle natural smile" in english and "candid photo" in english


def test_negative_prompt_excludes_synthetic_look():
    from komian.backgrounds import NEGATIVE_PROMPT
    for term in ("cartoon", "exaggerated smile", "plastic skin"):
        assert term in NEGATIVE_PROMPT
