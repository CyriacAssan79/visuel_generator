"""Génération en ligne : quota journalier, consigne enrichie, aperçu de mise en page (aucun appel réseau)."""
import pytest
from PIL import Image

from komian import config, db, ocr, online
from komian.brands import load_profile
from komian.models import Brief
from komian.workflow import generate, needs_quality_pass, preview, zone_hint


@pytest.fixture(autouse=True)
def no_ocr(monkeypatch):
    def unavailable():
        raise ocr.OcrUnavailable("OCR désactivé pour les tests.")
    monkeypatch.setattr(ocr, "_reader", unavailable)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    for key in ("sources", "tmp", "pending", "approved", "scenes"):
        monkeypatch.setitem(config.DIRS, key, tmp_path / key)
        (tmp_path / key).mkdir()
    with db.connect(tmp_path / "test.sqlite3") as c:
        yield c


@pytest.fixture
def fake_api(monkeypatch):
    """Remplace l'appel Cloudflare : image grise, consigne et taille mémorisées."""
    calls = []

    def generate_image(prompt, size, seed, model=None, reference=None):
        calls.append({"prompt": prompt, "size": size, "model": model})
        return Image.new("RGB", size, (90, 90, 90))
    monkeypatch.setattr(online, "generate_image", generate_image)
    monkeypatch.setattr(online, "credentials", lambda: ("compte", "jeton"))
    monkeypatch.setattr("komian.backgrounds.translate_prompt", lambda text: (text, False))
    return calls


def bernabe_brief(**kw):
    data = dict(brand_id="bernabe", series="Bon début de semaine", objective="motiver", channel="Instagram",
                format_id="post_carre", headline="Bonne semaine à tous !",
                exact_visual_text="Votre projet avance. Votre équipement doit suivre.",
                visual_direction="chantier", headline_on_visual=True)
    return Brief(**{**data, **kw})


def test_quota_counts_and_blocks(conn, monkeypatch):
    monkeypatch.setattr(online, "config", lambda: {**online.DEFAULTS, "daily_limit": 2})
    assert online.remaining(conn) == 2
    online.record_use(conn, "creation", "m")
    online.record_use(conn, "creation", "m")
    assert online.remaining(conn) == 0
    with pytest.raises(online.QuotaExceeded):
        online.check_quota(conn)
    conn.execute("UPDATE online_usage SET day = '2000-01-01'")  # hier : le quota est renouvelé
    assert online.remaining(conn) == 2


def test_prompt_adds_market_context_and_no_text():
    prompt = online.build_prompt("worker on a construction site", load_profile("bernabe"), "keep the top free")
    assert "Abidjan" in prompt and "Black African" in prompt
    assert "keep the top free" in prompt and "no text" in prompt


def test_generation_size_is_about_one_megapixel():
    w, h = online.generation_size((1440, 1440))
    assert (w, h) == (1024, 1024)
    w, h = online.generation_size((1080, 1350))
    assert w % 16 == 0 and h % 16 == 0 and 0.9e6 < w * h < 1.1e6 and abs(w / h - 0.8) < 0.02


def test_preview_composes_without_generation():
    comp = preview(load_profile("bernabe"), bernabe_brief(), "bernabe_bandeau", "panneau:haut_centre", 0.25)
    assert comp.image.size == (360, 360)
    assert any(l["kind"] == "logo" for l in comp.layers)


def test_zone_hint_follows_layout():
    profile, brief = load_profile("bernabe"), bernabe_brief()
    top = zone_hint(profile, brief, "bernabe_bandeau", "panneau:haut_centre")
    assert "top center" in top and "banner" in top
    short = bernabe_brief(exact_visual_text="Bon courage !", headline_on_visual=False, show_series_tag=False)
    left = zone_hint(profile, short, "bernabe_bandeau", "direct:bas_gauche")
    assert "bottom left" in left and "right side" in left
    assert "blurred" not in zone_hint(profile, brief, "bernabe_bandeau", None)  # plusieurs propositions : bandeau seul


def test_online_creation_uses_one_credit_and_no_quality_pass(conn, fake_api):
    brief_id = db.create_brief(conn, bernabe_brief())
    before = online.remaining(conn)
    rid = generate(conn, brief_id, "bernabe_bandeau", "ia_en_ligne",
                   {"prompt": "ouvrier sur un chantier"}, "panneau:haut_centre")
    assert online.remaining(conn) == before - 1
    assert len(fake_api) == 1 and fake_api[0]["size"] == (1024, 1024)
    assert "top center" in fake_api[0]["prompt"] and "Abidjan" in fake_api[0]["prompt"]
    render = db.get_render(conn, rid)
    import json
    assert not needs_quality_pass(render, json.loads(render["params"]))  # l'image en ligne est la finale
    assert "Image générée par IA" in [c["name"] for c in db.get_checks(conn, rid)]


def test_patch_scene_keeps_outside_of_zone_identical():
    import numpy as np
    from komian.workflow import patch_scene
    scene = Image.new("RGB", (1024, 1024), (40, 120, 200))
    sent = []

    def edit(image, size):
        sent.append(image.size)
        return Image.new("RGB", size, (250, 0, 0))
    new, info = patch_scene(scene, [(0, 0)], edit)
    assert max(sent[0]) < 512  # Cloudflare : entrée < 512 × 512
    a = np.asarray(new)
    x1, y1 = info["crop_box"][2], info["crop_box"][3]
    assert (a[y1 + 5:, :] == (40, 120, 200)).all() and (a[:, x1 + 5:] == (40, 120, 200)).all()
    assert tuple(a[100, 100]) == (250, 0, 0)  # zone cochée remplacée


def test_correction_once_one_credit_then_final(conn, fake_api):
    import json
    from komian.workflow import CorrectionRefused, correct_render
    brief_id = db.create_brief(conn, bernabe_brief())
    rid = generate(conn, brief_id, "bernabe_bandeau", "ia_en_ligne", {"prompt": "chantier"}, "panneau:haut_centre")
    before = online.remaining(conn)
    fixed = correct_render(conn, rid, "ajouter un casque blanc", [(0, 1), (1, 1)],
                           edit_fn=lambda image, size: Image.new("RGB", size, (200, 200, 200)))
    assert online.remaining(conn) == before - 1
    params = json.loads(db.get_render(conn, fixed)["params"])
    assert params["correction_of"] == rid and params["correction"]["cells"] == [[0, 1], [1, 1]]
    assert db.get_render(conn, fixed)["layout"] == "panneau:haut_centre"
    with pytest.raises(CorrectionRefused):  # une seule correction par visuel
        correct_render(conn, fixed, "encore", [(1, 1)], edit_fn=lambda i, s: Image.new("RGB", s))
    with pytest.raises(CorrectionRefused):
        correct_render(conn, rid, "encore", [(1, 1)], edit_fn=lambda i, s: Image.new("RGB", s))


def test_online_creation_refused_when_quota_reached(conn, fake_api, monkeypatch):
    monkeypatch.setattr(online, "config", lambda: {**online.DEFAULTS, "daily_limit": 0})
    brief_id = db.create_brief(conn, bernabe_brief())
    with pytest.raises(online.QuotaExceeded):
        generate(conn, brief_id, "bernabe_bandeau", "ia_en_ligne", {"prompt": "chantier"}, "panneau:haut_centre")
    assert fake_api == []
