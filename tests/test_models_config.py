"""Configuration des modèles d'images (sans charger de modèle)."""
import pytest

from komian.backgrounds import NEGATIVE_PROMPT, SourceUnavailable, _openvino_model_dir, model_choices


def test_quality_mode_is_realistic_vision():
    choices = dict(model_choices())
    assert "rv51_ov_int8_gpu" in choices
    assert not any("stable-diffusion-v1-5" in spec["repo"] for spec in choices.values())


def test_negative_prompt_excludes_nudity():
    for term in ("nsfw", "nude", "shirtless"):
        assert term in NEGATIVE_PROMPT


def test_unconverted_model_names_conversion_script(tmp_path):
    spec = {"path": str(tmp_path / "absent"), "convert_script": "scripts/convert_realistic_vision.sh"}
    with pytest.raises(SourceUnavailable, match="convert_realistic_vision"):
        _openvino_model_dir(spec)
