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


def test_partial_photo_zones_reuse_usual_shapes():
    """Zones photo partielles (affiche Bernabé, titre en haut) : pas de nouvelle forme à compiler."""
    assert generated_size((1440, 835)) == (704, 384)
    assert generated_size((1440, 1195)) == (576, 448)
    assert generated_size((1080, 1594)) == (448, 576)


def test_gpu_memory_error_releases_models_and_retries_once():
    from komian.models_manager import ModelManager
    manager, calls = ModelManager(), []

    def ensure(state, size):
        calls.append(state)
        if len(calls) == 1:
            raise RuntimeError("[GPU] Exceeded max size of memory allocation: Required 14745600 bytes")
    manager._ensure_verifier = lambda: "verificateur"
    manager._ensure = ensure
    with manager.use("creation", (512, 512)) as pipes:
        assert pipes["verifier"] == "verificateur"
    assert calls == ["creation", "creation"]

    manager._ensure = lambda state, size: (_ for _ in ()).throw(
        RuntimeError("[GPU] ProgramBuilder build failed!"))
    with pytest.raises(SourceUnavailable, match="Mémoire de la puce graphique saturée"):
        with manager.use("creation", (512, 512)):
            pass
