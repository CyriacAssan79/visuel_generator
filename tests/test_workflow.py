import io

import pytest
from PIL import Image

from komian import config, db, ocr
from komian.brands import load_profile
from komian.checks import check_spelling
from komian.compose import split_in_two
from komian.models import Brief
from komian.storage import ImportRejected, import_image
from komian.workflow import (ApprovalRefused, ExportBlocked, PlanBlocked, decide, export_approved, generate,
                             generate_variants, prepare_plan)


@pytest.fixture(autouse=True)
def no_ocr(monkeypatch):
    """Tests rapides et déterministes : OCR simulé absent (voir test_ocr.py pour l'OCR réel)."""
    def unavailable():
        raise ocr.OcrUnavailable("OCR désactivé pour les tests.")
    monkeypatch.setattr(ocr, "_reader", unavailable)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    for key in ("sources", "tmp", "pending", "approved"):
        monkeypatch.setitem(config.DIRS, key, tmp_path / key)
        (tmp_path / key).mkdir()
    with db.connect(tmp_path / "test.sqlite3") as c:
        yield c


def make_brief(**overrides) -> Brief:
    data = dict(brand_id="mr_bricolage", series="Lundi motivation", objective="motiver", channel="Instagram",
                format_id="post_carre", headline="L'envie vient souvent après l'action.",
                exact_visual_text="LA MOTIVATION SUIT L'ACTION, PAS L'INVERSE",
                visual_direction="Formes géométriques simples rouge/blanc, logo en bas à droite.")
    data.update(overrides)
    return Brief(**data)


def statuses(conn, render_id):
    return {c["name"]: c["status"] for c in db.get_checks(conn, render_id)}


def test_split_keeps_every_character():
    text = "UN DERNIER LUNDI, LA MÊME ÉNERGIE"
    a, b = split_in_two(text)
    assert (a, b) == ("UN DERNIER LUNDI,", "LA MÊME ÉNERGIE")
    assert f"{a} {b}" == text


def test_geometric_render_passes_text_and_color_checks(conn):
    render_id = generate(conn, db.create_brief(conn, make_brief()), "citation_centree", "geometrique")
    s = statuses(conn, render_id)
    assert s["Textes exacts"] == "conforme"
    assert len(s) <= 14, s  # rapport compact : un contrôle par sujet
    assert s["Couleurs des éléments ajoutés"] == "conforme"
    assert s["Fond en aplats de marque"] == "conforme"
    assert s["Lisibilité (OCR)"] == "non_concluant"  # jamais présenté comme réussi


def test_series_variety_avoids_recent_variants(conn):
    brief_id = db.create_brief(conn, make_brief())
    variants = set()
    for _ in range(3):
        rid = generate(conn, brief_id, "citation_centree", "geometrique")
        variants.add(__import__("json").loads(db.get_render(conn, rid)["params"])["variant"])
    assert len(variants) == 3


def test_requested_icons_are_drawn_and_checked(conn):
    brief = make_brief(icons=["calendrier", "coche"], visual_direction="Icône calendrier, logo en bas à droite.")
    render_id = generate(conn, db.create_brief(conn, brief), "bandeau_titre_haut", "geometrique")
    s = statuses(conn, render_id)
    assert s["Icône « calendrier »"] == s["Icône « coche »"] == "conforme"
    assert s["Couleurs des éléments ajoutés"] == "conforme"


def test_icon_mentioned_but_not_selected_is_flagged():
    plan = prepare_plan(load_profile("mr_bricolage"), make_brief(visual_direction="avec une icône calendrier"),
                        "citation_centree", "geometrique")
    assert any("icône" in w for w in plan.warnings)


def photo_params(tmp_path):
    from komian.storage import import_image as imp
    buf = io.BytesIO()
    img = Image.new("RGB", (1200, 1200), (200, 200, 200))
    img.paste((40, 40, 40), (0, 0, 600, 1200))  # moitié gauche chargée -> le message doit l'éviter
    for x in range(0, 600, 40):
        img.paste((230, 230, 230), (x, 0, x + 20, 1200))
    img.save(buf, "PNG")
    return {"photo_path": str(imp(buf.getvalue(), "fond.png", "mr_bricolage"))}


def test_variants_use_distinct_layouts_on_calmest_zones(conn, tmp_path):
    brief_id = db.create_brief(conn, make_brief(visual_direction="Photo d'atelier, logo en bas à droite."))
    batch_id, ids = generate_variants(conn, brief_id, "bandeau_blocs", "photo", photo_params(tmp_path))
    renders = db.batch_renders(conn, batch_id)
    assert len(ids) == 3 and len({r["layout"] for r in renders}) == 3
    assert renders[0]["layout"].endswith("droite")  # zone calme = moitié droite du fond
    for rid in ids:
        s = statuses(conn, rid)
        assert "anomalie" not in s.values(), s


def test_layouts_covering_a_face_are_not_proposed(conn, tmp_path, monkeypatch):
    from komian import saliency
    face = (60, 120, 360, 420, 0.95)  # visage simulé en haut à gauche du fond
    monkeypatch.setattr(saliency, "detect_faces", lambda image: [face])
    brief_id = db.create_brief(conn, make_brief(visual_direction="Photo d'atelier, logo en bas à droite."))
    batch_id, ids = generate_variants(conn, brief_id, "bandeau_blocs", "photo", photo_params(tmp_path))
    renders = db.batch_renders(conn, batch_id)
    assert len(renders) == 3 and "haut_gauche" not in {r["layout"] for r in renders}
    assert all(statuses(conn, r["id"])["Visages dégagés"] == "conforme" for r in renders)


def test_face_covered_by_message_is_an_anomaly(conn, tmp_path, monkeypatch):
    from komian import saliency
    monkeypatch.setattr(saliency, "detect_faces", lambda image: [(60, 120, 360, 420, 0.95)])
    brief_id = db.create_brief(conn, make_brief(visual_direction="Photo d'atelier, logo en bas à droite."))
    rid = generate(conn, brief_id, "bandeau_blocs", "photo", photo_params(tmp_path), layout="haut_gauche")
    assert statuses(conn, rid)["Visages dégagés"] == "anomalie"


def test_text_group_stays_above_band():
    from komian.compose import ZONE_BOTTOM, TEMPLATES, compose, message_bbox
    profile = load_profile("mr_bricolage")
    for layout in TEMPLATES["bandeau_blocs"]["layouts"]:
        comp = compose(profile, make_brief(icons=["calendrier"]), (1440, 1440), "bandeau_blocs",
                       lambda s: Image.new("RGB", s, "gray"), layout)
        x0, y0, x1, y1 = message_bbox(comp)
        assert 0 <= x0 and x1 <= 1440 and y1 <= 1440 * ZONE_BOTTOM, (layout, message_bbox(comp))


def test_choosing_a_variant_rejects_the_others(conn, tmp_path):
    brief_id = db.create_brief(conn, make_brief())
    batch_id, ids = generate_variants(conn, brief_id, "citation_centree", "geometrique")
    decide(conn, ids[1], "approved", "Awa", acknowledge_inconclusive=True)
    by_id = {r["id"]: r["status"] for r in db.batch_renders(conn, batch_id)}
    assert by_id[ids[1]] == "approved"
    assert by_id[ids[0]] == by_id[ids[2]] == "rejected"
    assert "non retenue" in db.latest_approval(conn, ids[0])["comment"]
    with pytest.raises(ExportBlocked):
        export_approved(conn, ids[0])
    assert export_approved(conn, ids[1]).exists()


def test_message_photo_styles_render_without_anomaly():
    from komian.checks import check_series_tag
    from komian.compose import MESSAGE_PHOTO_LAYOUTS, compose
    profile = load_profile("mr_bricolage")
    brief = make_brief(headline_on_visual=False)
    for layout in ("panneau:centre_gauche", "direct:bas_centre", "blocs:centre_droite"):
        assert layout in MESSAGE_PHOTO_LAYOUTS
        comp = compose(profile, brief, (1440, 1440), "message_photo", lambda s: Image.new("RGB", s, "gray"), layout)
        roles = {l.get("role") for l in comp.layers}
        assert any(r and r.startswith("texte_exact") for r in roles) and "accroche" not in roles
        if not layout.startswith("blocs"):
            assert {"serie_1", "serie_2"} <= roles
            assert check_series_tag(comp, brief, profile).status == "conforme"
        if layout.startswith("direct"):
            assert next(l for l in comp.layers if l.get("role") == "texte_exact")["shadow"]


def test_message_photo_variants_differ_in_style(conn, tmp_path):
    brief_id = db.create_brief(conn, make_brief(headline_on_visual=False,
                                                visual_direction="Photo d'atelier, logo en bas à droite."))
    batch_id, ids = generate_variants(conn, brief_id, "message_photo", "photo", photo_params(tmp_path))
    layouts = [r["layout"] for r in db.batch_renders(conn, batch_id)]
    assert len(set(layouts)) == 3 and len({l.split(":")[0] for l in layouts}) >= 2, layouts
    for rid in ids:
        s = statuses(conn, rid)
        assert not any(name.startswith("Contraste —") for name in s)
        assert s["Textes exacts"] == "conforme" and s["Couleurs des éléments ajoutés"] == "conforme", s


def test_prune_removes_renders_whose_file_was_deleted(conn):
    brief_id = db.create_brief(conn, make_brief())
    _, ids = generate_variants(conn, brief_id, "citation_centree", "geometrique")
    decide(conn, ids[0], "approved", "Awa", acknowledge_inconclusive=True)
    export_approved(conn, ids[0])
    for rid in ids:  # ménage manuel du dossier : tous les fichiers en attente disparaissent
        config.from_stored(db.get_render(conn, rid)["file_path"]).unlink()
    assert len(db.missing_render_files(conn)) == 3
    assert db.prune_missing_renders(conn) == (2, 1)  # le rendu exporté reste tracé
    assert [r["id"] for r in db.list_renders(conn)] == [ids[0]]
    assert db.get_checks(conn, ids[1]) == []


def test_delete_render_removes_file_and_records(conn):
    from komian.workflow import DeleteRefused, delete_render
    brief_id = db.create_brief(conn, make_brief())
    _, ids = generate_variants(conn, brief_id, "citation_centree", "geometrique")
    path = config.from_stored(db.get_render(conn, ids[1])["file_path"])
    assert delete_render(conn, ids[1]) == [ids[1]]
    assert not path.exists()
    assert db.get_checks(conn, ids[1]) == []
    assert ids[1] not in [r["id"] for r in db.list_renders(conn)]
    decide(conn, ids[0], "approved", "Awa", acknowledge_inconclusive=True)
    export_approved(conn, ids[0])
    with pytest.raises(DeleteRefused):  # un visuel livré reste tracé
        delete_render(conn, ids[0])
    assert config.from_stored(db.get_render(conn, ids[0])["file_path"]).exists()
    copy = config.from_stored(conn.execute("SELECT file_path FROM exports WHERE render_id = ?",
                                           (ids[0],)).fetchone()["file_path"])
    assert delete_render(conn, ids[0], include_exported=True) == [ids[0]]  # sur confirmation explicite
    assert not copy.exists() and not db.is_exported(conn, ids[0])


def test_delete_render_takes_quality_versions_and_keeps_shared_scene(conn, tmp_path, monkeypatch):
    import json
    from komian.workflow import delete_render
    monkeypatch.setitem(config.DIRS, "scenes", tmp_path / "scenes")
    brief_id = db.create_brief(conn, make_brief())
    _, ids = generate_variants(conn, brief_id, "citation_centree", "geometrique")
    scene = tmp_path / "scenes" / "s.png"
    scene.parent.mkdir()
    Image.new("RGB", (8, 8)).save(scene)
    final = tmp_path / "pending" / "final.png"
    Image.new("RGB", (8, 8)).save(final)
    for rid in ids:  # les variantes d'un lot partagent la scène créée par l'IA
        conn.execute("UPDATE renders SET params = json_set(params, '$.scene_path', ?) WHERE id = ?",
                     (str(scene), rid))
    row = db.get_render(conn, ids[0])
    db.insert_render(conn, "final1", row["brief_id"], row["template_id"], "ia_locale",
                     {**json.loads(row["params"]), "quality_of": ids[0]}, final, "x", "pending")
    assert sorted(delete_render(conn, "final1")) == sorted([ids[0], "final1"])  # aperçu et finale ensemble
    assert not final.exists()
    assert scene.exists()  # encore utilisée par les autres variantes
    delete_render(conn, ids[1])
    delete_render(conn, ids[2])
    assert not scene.exists()


def test_gpu_falls_back_to_cpu_when_unavailable(monkeypatch):
    from komian import models_manager
    monkeypatch.setattr(models_manager, "openvino_devices", lambda: ("CPU",))
    assert models_manager.resolve_device("GPU") == "CPU"
    monkeypatch.setattr(models_manager, "openvino_devices", lambda: ("CPU", "GPU"))
    assert models_manager.resolve_device("gpu") == "GPU"


def test_stored_paths_are_portable():
    assert config.to_stored(config.ROOT / "data" / "renders" / "x.png") == "data/renders/x.png"
    legacy = r"C:\Users\KSOMS\Favorites\generation_de_visuel\data\renders\pending\x.png"
    assert config.from_stored(legacy) == config.ROOT / "data/renders/pending/x.png"
    wsl = "/mnt/c/Users/KSOMS/Favorites/generation_de_visuel/data/renders/pending/x.png"
    assert config.from_stored(wsl) == config.ROOT / "data/renders/pending/x.png"


def test_scene_prompt_suggested_from_direction():
    from komian.backgrounds import suggest_prompt
    assert "magasin de bricolage" in suggest_prompt("Photo désaturée d'un intérieur ou d'un rayon")
    assert "jardin" in suggest_prompt("Ambiance jardinage au printemps")
    assert "atelier" in suggest_prompt("Fond rouge, typographie blanche")


def test_glossary_terms_are_protected_from_translation():
    from komian import translate
    text, terms = translate._protect("femme en salopette, plan taille, devant un établi")
    assert terms == ["medium shot", "workbench", "overalls"] or set(terms) == {"medium shot", "workbench", "overalls"}
    assert "salopette" not in text and "TERM" in text
    assert translate._restore("woman in TERM2s, TERM0", ["medium shot", "workbench", "overalls"]) \
        == "woman in overalls, medium shot"


def test_english_prompt_is_not_translated():
    from komian.translate import translate_prompt
    prompt = "smiling Black man wearing a plaid shirt in a workshop, realistic photo"
    assert translate_prompt(prompt) == (prompt, False)


def test_forbidden_spelling_is_an_anomaly():
    profile = load_profile("mr_bricolage")
    assert check_spelling(make_brief(exact_visual_text="MR.BRICOLAGE VOUS ACCUEILLE"), profile).status == "anomalie"
    assert check_spelling(make_brief(), profile).status == "conforme"


def test_overlay_request_is_flagged_unless_brand_allows_it():
    brief = make_brief(visual_direction="Photo désaturée, overlay rouge semi-transparent")
    allowed = load_profile("mr_bricolage")  # overlays validés par la marque le 2026-10-19
    assert allowed.overlays_allowed
    plan = prepare_plan(allowed, brief, "bandeau_titre_haut", "photo")
    assert not any("100 %" in w for w in plan.warnings)
    strict = allowed.model_copy(update={"overlays_allowed": False})
    plan = prepare_plan(strict, brief, "bandeau_titre_haut", "photo")
    assert any("100 %" in w for w in plan.warnings)


def test_validated_brand_has_no_open_points():
    profile = load_profile("mr_bricolage")
    assert profile.unknowns == []
    assert profile.primary_colors["rouge"].hex == "#EB0029"
    assert all(logo.status == "confirmé" for logo in profile.logos)
    assert "orange" in profile.allowed_system_colors  # couleurs secondaires définitives


def test_unknown_format_blocks_generation(conn):
    brief_id = db.create_brief(conn, make_brief(format_id="a0"))
    with pytest.raises(PlanBlocked):
        generate(conn, brief_id, "citation_centree", "geometrique")


def test_ai_source_failure_is_recorded(conn):
    brief_id = db.create_brief(conn, make_brief())
    with pytest.raises(Exception):
        generate(conn, brief_id, "citation_centree", "ia_locale")
    errors = [r for r in db.list_renders(conn) if r["status"] == "error"]
    assert errors and "IA" in errors[0]["error"]


def test_export_blocked_without_approval(conn):
    render_id = generate(conn, db.create_brief(conn, make_brief()), "citation_centree", "geometrique")
    with pytest.raises(ExportBlocked):
        export_approved(conn, render_id)


def test_approval_requires_acknowledging_inconclusive_checks(conn):
    render_id = generate(conn, db.create_brief(conn, make_brief()), "citation_centree", "geometrique")
    with pytest.raises(ApprovalRefused):
        decide(conn, render_id, "approved", "Awa")
    decide(conn, render_id, "approved", "Awa", acknowledge_inconclusive=True)
    exported = export_approved(conn, render_id)
    assert exported.exists() and exported.parent == config.DIRS["approved"]


def test_modified_file_cannot_be_exported(conn):
    render_id = generate(conn, db.create_brief(conn, make_brief()), "citation_centree", "geometrique")
    decide(conn, render_id, "approved", "Awa", acknowledge_inconclusive=True)
    path = config.from_stored(db.get_render(conn, render_id)["file_path"])
    Image.new("RGB", (1440, 1440), "white").save(path)
    with pytest.raises(ExportBlocked):
        export_approved(conn, render_id)


def test_rejection_after_approval_blocks_export(conn):
    render_id = generate(conn, db.create_brief(conn, make_brief()), "citation_centree", "geometrique")
    decide(conn, render_id, "approved", "Awa", acknowledge_inconclusive=True)
    decide(conn, render_id, "rejected", "Koffi", "Couleur à revoir")
    with pytest.raises(ExportBlocked):
        export_approved(conn, render_id)


def test_brief_revision_requires_justification(conn):
    db.create_brief(conn, make_brief())
    key = db.list_briefs(conn, "mr_bricolage")[0]["brief_key"]
    with pytest.raises(ValueError):
        db.revise_brief(conn, key, make_brief(exact_visual_text="LA MOTIVATION SUIT L'ACTION."), "", "Awa")
    db.revise_brief(conn, key, make_brief(exact_visual_text="LA MOTIVATION SUIT L'ACTION."), "Point ajouté", "Awa")
    assert [v["version"] for v in db.brief_versions(conn, key)] == [1, 2]


def test_photo_import_rejects_fake_images(conn):
    with pytest.raises(ImportRejected):
        import_image(b"<script>alert(1)</script>", "photo.jpg", "mr_bricolage")
    with pytest.raises(ImportRejected):
        import_image(b"x", "photo.exe", "mr_bricolage")
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), "gray").save(buf, "JPEG")
    assert import_image(buf.getvalue(), "photo.jpg", "mr_bricolage").exists()


def test_path_traversal_refused():
    with pytest.raises(ValueError):
        config.safe_path(config.DIRS["brands"], "..", "..", "secret.txt")


# --- IA : aperçu rapide puis version qualité à l'approbation (modèles simulés) ---------------------------
GOOD_FACE = {"ok": True, "score": 0.8, "width": 100, "sharpness": 300, "confidence": 0.93, "problems": []}


@pytest.fixture
def fake_ai(conn, tmp_path, monkeypatch):
    """Création et passage en qualité simulés ; `final_action` règle le résultat du contrôle final."""
    from komian import backgrounds, quality_loop
    monkeypatch.setitem(config.DIRS, "scenes", tmp_path / "scenes")
    monkeypatch.setattr(backgrounds, "translate_prompt", lambda text: (text, False))
    state = {"final_action": True, "quality_calls": 0}

    def create_scene(prompt_en, size, seed):
        report = {"prompt": prompt_en, "object": "power drill", "question": "Is the person drilling?",
                  "action_verified": True, "face": GOOD_FACE, "clothed": True, "candidates": 1, "object_added": False,
                  "seed": seed, "duration_s": 1.0}
        return Image.new("RGB", size, (120, 110, 100)), report

    def quality_scene(scene, report, size, seed):
        state["quality_calls"] += 1
        return Image.new("RGB", size, (125, 115, 105)), {"face": GOOD_FACE, "clothed": True, "action_verified": state["final_action"]}

    monkeypatch.setattr(backgrounds, "create_scene", create_scene)
    monkeypatch.setattr(quality_loop, "quality_scene", quality_scene)
    return state


def ai_preview(conn):
    brief_id = db.create_brief(conn, make_brief(visual_direction="Homme qui perce un mur, logo en bas à droite."))
    return generate(conn, brief_id, "citation_centree", "ia_locale",
                    {"prompt": "Black man drilling a wall with a power drill"})


def test_approving_an_ai_preview_approves_its_quality_version(conn, fake_ai):
    preview_id = ai_preview(conn)
    assert statuses(conn, preview_id)["Action demandée"] == "conforme"
    approval_id = decide(conn, preview_id, "approved", "Awa", acknowledge_inconclusive=True)
    final_id = db.get_approval(conn, approval_id)["render_id"]
    assert final_id != preview_id and fake_ai["quality_calls"] == 1
    final = db.get_render(conn, final_id)
    assert final["status"] == "approved" and final["layout"] == db.get_render(conn, preview_id)["layout"]
    assert "aperçu rapide" in db.latest_approval(conn, final_id)["comment"]
    assert db.get_render(conn, preview_id)["status"] == "rejected"
    assert export_approved(conn, final_id).exists()
    with pytest.raises(ExportBlocked):  # l'aperçu, remplacé, ne peut plus être exporté
        export_approved(conn, preview_id)


def test_quality_version_losing_the_action_is_not_approved(conn, fake_ai):
    from komian.workflow import QualityNotApproved
    fake_ai["final_action"] = False
    preview_id = ai_preview(conn)
    with pytest.raises(QualityNotApproved) as refused:
        decide(conn, preview_id, "approved", "Awa", acknowledge_inconclusive=True)
    final = db.get_render(conn, refused.value.render_id)
    assert final["status"] == "pending" and "Action demandée" in str(refused.value)
    assert statuses(conn, final["id"])["Action demandée"] == "non_concluant"
    assert db.get_render(conn, preview_id)["status"] == "pending"


def test_cancelling_a_quality_approval_reopens_the_preview(conn, fake_ai):
    from komian.workflow import cancel_quality_approval
    preview_id = ai_preview(conn)
    final_id = db.get_approval(conn, decide(conn, preview_id, "approved", "Awa",
                                            acknowledge_inconclusive=True))["render_id"]
    assert cancel_quality_approval(conn, final_id, "Awa") == preview_id
    assert db.get_render(conn, final_id)["status"] == "rejected"
    assert db.get_render(conn, preview_id)["status"] == "pending"
    with pytest.raises(ExportBlocked):
        export_approved(conn, final_id)
