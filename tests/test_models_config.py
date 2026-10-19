"""Configuration des modèles d'images (sans charger de modèle)."""
import pytest

from komian.backgrounds import NEGATIVE_PROMPT, SourceUnavailable, ai_configured, generated_size, model_spec
from komian.models_manager import model_dir


def test_loop_roles_are_configured():
    assert ai_configured()
    assert model_spec("quality")[1]["repo"].startswith("SG161222/Realistic_Vision")
    assert "Qwen3-VL" in model_spec("verifier")[1]["repo"]


def test_negative_prompt_excludes_nudity():
    for term in ("nsfw", "nude", "shirtless"):
        assert term in NEGATIVE_PROMPT


def test_unconverted_model_names_conversion_script(tmp_path):
    spec = {"path": str(tmp_path / "absent"), "convert_script": "scripts/convert_realistic_vision.sh"}
    with pytest.raises(SourceUnavailable, match="convert_realistic_vision"):
        model_dir(spec)


def test_generated_size_keeps_area_for_every_format():
    assert generated_size((1440, 1440)) == (512, 512)
    assert generated_size((1080, 1350)) == (448, 576)   # avant : 384 × 512
    assert generated_size((1080, 1920)) == (384, 704)   # avant : 256 × 512
