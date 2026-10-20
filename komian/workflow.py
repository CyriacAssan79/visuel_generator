"""Orchestrateur : plan de génération, rendu, contrôles, validation, export."""
import json
import random
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import db
from .backgrounds import SOURCES, GeometricSource, model_spec, save_scene, scene_to_background
from .brands import file_sha256, load_profile, missing_assets
from .checks import ANOMALIE, NON_CONCLUANT, run_checks
from .compose import TEMPLATES, compose, layout_label, message_mask
from .config import DIRS, FORMATS, from_stored, safe_path
from .models import BrandProfile, Brief
from .saliency import FaceDetectionUnavailable, faces_on_canvas, saliency_map


class PlanBlocked(RuntimeError):
    pass


class ApprovalRefused(RuntimeError):
    pass


class QualityNotApproved(ApprovalRefused):
    """La version qualité a été créée, mais ses contrôles empêchent de l'approuver automatiquement."""

    def __init__(self, render_id: str, message: str):
        super().__init__(message)
        self.render_id = render_id


class ExportBlocked(RuntimeError):
    pass


@dataclass
class Plan:
    strict: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)


# Repérage simple par mots-clés : signale, ne tranche pas.
OVERLAY_WORDS = ("semi-transparent", "transparen", "overlay", "dégradé", "degrade", "tramé", "trame")
ICON_WORDS = ("icône", "icone", "pictogramme", "calendrier", "coche")
UNSUPPORTED_WORDS = ("illustration", "dessin", "mascotte")
PHOTO_WORDS = ("photo", "image d'", "intérieur", "rayon")
SHAPES_WORDS = ("forme", "géométri", "geometri")


def prepare_plan(profile: BrandProfile, brief: Brief, template_id: str, source_id: str) -> Plan:
    plan = Plan()
    if brief.format_id not in FORMATS:
        plan.blocking.append(f"Format inconnu : {brief.format_id}")
    if template_id not in TEMPLATES:
        plan.blocking.append(f"Gabarit inconnu : {template_id}")
    elif template_id not in profile.templates:
        plan.blocking.append(f"Le gabarit « {TEMPLATES[template_id]['label']} » n'est pas prévu pour "
                             f"{profile.brand_name}.")
    if source_id not in SOURCES:
        plan.blocking.append(f"Source d'image inconnue : {source_id}")
    for missing in missing_assets(profile):
        plan.blocking.append(f"Ressource de marque manquante : {missing}")

    plan.strict = [
        f"Texte exact : « {brief.exact_visual_text} »",
        f"Accroche : « {brief.headline} »",
        f"Logo officiel, {brief.logo_position}",
        f"Police {profile.font_name}",
        profile.primary_color_rule,
        f"Orthographe : {profile.official_spelling}",
    ]
    plan.preferences = [brief.visual_direction]

    direction = brief.visual_direction.lower()
    if not profile.overlays_allowed and any(w in direction for w in OVERLAY_WORDS):
        plan.warnings.append("La direction demande une transparence ou un dégradé ; la charte impose les couleurs "
                             "principales à 100 % : à confirmer par le responsable de marque.")
    if any(w in direction for w in ICON_WORDS) and not brief.icons:
        plan.warnings.append("La direction mentionne une icône mais aucune n'est sélectionnée dans le brief.")
    asked = [w for w in UNSUPPORTED_WORDS if w in direction]
    if asked:
        plan.warnings.append(f"Élément demandé non pris en charge par les gabarits ({', '.join(asked)}) : "
                             "à ajouter manuellement ou à développer.")
    if source_id == "geometrique" and any(w in direction for w in PHOTO_WORDS):
        plan.warnings.append("La direction évoque une photo alors que la source choisie est « formes géométriques ».")
    if source_id == "photo" and any(w in direction for w in SHAPES_WORDS):
        plan.warnings.append("La direction évoque des formes géométriques alors que la source choisie est une photo.")
    if (template_id in TEMPLATES and not TEMPLATES[template_id].get("logo_fixed")
            and TEMPLATES[template_id]["logo_position"] != brief.logo_position):
        plan.warnings.append(f"Le gabarit place le logo {TEMPLATES[template_id]['logo_position']}, "
                             f"le brief demande {brief.logo_position}.")
    return plan


def pick_variant(conn, brief: Brief, rng: random.Random) -> str:
    """Évite les variantes utilisées par les derniers visuels de la même série."""
    variants = list(GeometricSource.variants)
    if brief.series:
        used = {p.get("variant") for p in db.recent_series_params(conn, brief.brand_id, brief.series)}
        variants = [v for v in variants if v not in used] or variants
    return rng.choice(variants)


def _prepare(conn, brief_id, template_id, source_id, params):
    row, brief = db.get_brief(conn, brief_id)
    profile = load_profile(brief.brand_id)
    plan = prepare_plan(profile, brief, template_id, source_id)
    if plan.blocking:
        raise PlanBlocked(" ; ".join(plan.blocking))
    params = dict(params or {})
    if source_id == "geometrique":
        rng = random.Random()
        params.setdefault("variant", pick_variant(conn, brief, rng))
        params.setdefault("seed", rng.randrange(10**9))
    source = SOURCES[source_id]
    cache: dict = {}

    def background(size):
        """Le fond est produit une seule fois par taille, puis partagé par toutes les dispositions."""
        if size not in cache:
            cache[size] = source.make(size, profile, params)
        return cache[size]

    return row, brief, profile, plan, params, background, cache


def _fail(conn, brief_id, template_id, source_id, params, started, exc, batch_id=None):
    db.insert_render(conn, uuid.uuid4().hex[:12], brief_id, template_id, source_id, params, None, None, "error",
                     error=f"{type(exc).__name__}: {exc}", duration_s=round(time.perf_counter() - started, 2),
                     batch_id=batch_id)
    conn.commit()


def _save(conn, row, brief, profile, plan, template_id, source_id, params, comp, background_img, started,
          batch_id=None, extra=None) -> str:
    render_id = uuid.uuid4().hex[:12]
    filename = f"{profile.brand_id}_{row['brief_key']}_v{row['version']}_{render_id}.png"
    tmp = safe_path(DIRS["tmp"], filename)
    comp.image.save(tmp, "PNG")
    results = run_checks(tmp, comp, brief, profile, plan.warnings, source_id, params, background_img)
    pending = safe_path(DIRS["pending"], filename)
    shutil.move(tmp, pending)
    record = {**params, **(extra or {}), "layout": comp.layout, "plan_warnings": plan.warnings,
              "layers": comp.layers}
    db.insert_render(conn, render_id, row["id"], template_id, source_id, record, pending, file_sha256(pending),
                     "pending", duration_s=round(time.perf_counter() - started, 2), batch_id=batch_id,
                     layout=comp.layout)
    db.insert_checks(conn, render_id, results)
    return render_id


def generate(conn, brief_id: int, template_id: str, source_id: str, params: dict | None = None,
             layout: str | None = None) -> str:
    """Un rendu, dans une disposition donnée (la première du gabarit par défaut)."""
    started = time.perf_counter()
    row, brief, profile, plan, params, background, cache = _prepare(conn, brief_id, template_id, source_id, params)
    try:
        comp = compose(profile, brief, FORMATS[brief.format_id], template_id, background, layout)
    except Exception as exc:
        _fail(conn, brief_id, template_id, source_id, params, started, exc)
        raise
    return _save(conn, row, brief, profile, plan, template_id, source_id, params, comp,
                 next(iter(cache.values()), None), started)


FACE_COVER_TOLERANCE = 0.05


MASK_SCALE = 4


def mask_face_cover(face, mask) -> float:
    """Part de la surface d'un visage recouverte par le message (masque réduit)."""
    x0, y0, x1, y1 = (int(v) // MASK_SCALE for v in face[:4])
    region = mask[max(y0, 0):y1, max(x0, 0):x1]
    return float(region.mean()) if region.size else 0.0


DIRECT_TEXT_MAX_LUMINANCE = 130  # au-delà, un texte blanc posé sur la photo devient peu lisible


def placement_score(background: Image.Image, canvas_size, mask, sal, faces=(), style: str = "") -> dict:
    """Plus le score est bas, mieux c'est : aucun visage masqué, peu de sujet masqué, fond calme
    (et assez sombre pour un texte blanc posé directement sur la photo)."""
    W, H = canvas_size
    small_sal = sal[::MASK_SCALE, ::MASK_SCALE][:mask.shape[0], :mask.shape[1]]
    covered = float((small_sal * mask).sum() / max(small_sal.sum(), 1e-9))
    lum = np.asarray(background.convert("L").resize((mask.shape[1], mask.shape[0])), dtype=float)
    calm = round(float(lum[mask].std()) if mask.any() else 0.0, 1)
    face_cover = max((mask_face_cover(f, mask) for f in faces), default=0.0)
    penalty = 1000 * face_cover if face_cover > FACE_COVER_TOLERANCE else 0
    brightness = round(float(lum[mask].mean()) if mask.any() else 0.0, 1)
    if style in ("direct", "degrade"):  # texte blanc (et rouge) posé sur la photo
        penalty += max(0.0, brightness - DIRECT_TEXT_MAX_LUMINANCE) * 0.6 + calm * 0.4
    return {"score": round(penalty + covered * 100 + calm * 0.3, 1), "subject_covered": round(covered, 3),
            "zone_busyness": calm, "zone_brightness": brightness, "face_covered": round(face_cover, 2)}


def _style_and_position(template_id: str, layout: str) -> tuple[str, str]:
    if ":" in layout:
        style, pos = layout.split(":")
        return style, pos
    return template_id, layout


STYLE_REPEAT_PENALTY = 25     # un style déjà proposé doit être nettement meilleur pour revenir
POSITION_REPEAT_PENALTY = 10


def pick_diverse(candidates: list, count: int) -> list:
    """Choisit `count` candidats : meilleur score, avec un malus pour un style ou une position déjà proposés."""
    pool, picked, styles, positions = list(candidates), [], set(), set()
    while pool and len(picked) < count:
        best = min(pool, key=lambda c: c[0]["score"] + STYLE_REPEAT_PENALTY * (c[2][0] in styles)
                   + POSITION_REPEAT_PENALTY * (c[2][1] in positions))
        pool.remove(best)
        picked.append(best)
        styles.add(best[2][0])
        positions.add(best[2][1])
    return picked


def generate_variants(conn, brief_id: int, template_id: str, source_id: str, params: dict | None = None,
                      count: int = 3) -> tuple[str, list[str]]:
    """Un seul fond, plusieurs dispositions : on garde `count` variantes qui dégagent les visages,
    masquent le moins le sujet, et diffèrent par le style et la position."""
    started = time.perf_counter()
    batch_id = uuid.uuid4().hex[:12]
    row, brief, profile, plan, params, background, cache = _prepare(conn, brief_id, template_id, source_id, params)
    size = FORMATS[brief.format_id]
    candidates = []
    try:
        sal = faces = None
        for layout in TEMPLATES[template_id]["layouts"]:
            comp = compose(profile, brief, size, template_id, background, layout)
            bg = next(iter(cache.values()))
            if sal is None:
                sal = saliency_map(bg, size)
                try:
                    faces = faces_on_canvas(bg, comp.layers) if source_id != "geometrique" else []
                except FaceDetectionUnavailable:
                    faces = []  # le contrôle « Visages dégagés » le signalera comme non concluant
            style_pos = _style_and_position(template_id, layout)
            score = placement_score(bg, size, message_mask(comp, size, MASK_SCALE), sal, faces, style_pos[0])
            candidates.append((score, comp, style_pos))
    except Exception as exc:
        _fail(conn, brief_id, template_id, source_id, params, started, exc, batch_id)
        raise
    candidates.sort(key=lambda c: c[0]["score"])
    clean = [c for c in candidates if c[0]["face_covered"] <= FACE_COVER_TOLERANCE]
    chosen = pick_diverse(clean or candidates, count)  # sans disposition propre : les moins mauvaises, signalées
    bg = next(iter(cache.values()))
    return batch_id, [
        _save(conn, row, brief, profile, plan, template_id, source_id, params, comp, bg, started, batch_id,
              {**score, "rank": rank})
        for rank, (score, comp, _) in enumerate(chosen, start=1)
    ]


def decide(conn, render_id: str, decision: str, reviewer: str, comment: str = "",
           acknowledge_inconclusive: bool = False) -> int:
    render = db.get_render(conn, render_id)
    if render["status"] == "error":
        raise ApprovalRefused("Ce rendu a échoué : rien à valider.")
    if not reviewer.strip():
        raise ApprovalRefused("Le nom du responsable de la validation est obligatoire.")
    path = from_stored(render["file_path"])
    if file_sha256(path) != render["sha256"]:
        raise ApprovalRefused("Le fichier a été modifié après le rendu : générer une nouvelle version.")
    if decision == "approved":
        checks = db.get_checks(conn, render_id)
        anomalies = [c["name"] for c in checks if c["status"] == ANOMALIE]
        if anomalies:
            raise ApprovalRefused("Approbation impossible, anomalies : " + ", ".join(anomalies))
        if any(c["status"] == NON_CONCLUANT for c in checks) and not acknowledge_inconclusive:
            raise ApprovalRefused("Des contrôles sont non concluants : confirmer qu'ils ont été vérifiés à l'œil.")
    elif decision != "rejected":
        raise ValueError(f"Décision inconnue : {decision}")
    params = json.loads(render["params"])
    if decision == "approved" and needs_quality_pass(render, params):
        return _approve_with_quality(conn, render, params, reviewer.strip(), comment.strip())
    approval_id = db.insert_approval(conn, render_id, render["sha256"], decision, reviewer.strip(), comment.strip())
    if decision == "approved":
        _reject_siblings(conn, render, reviewer.strip())
    return approval_id


VARIANT_NOT_KEPT = "Variante non retenue"
SUPERSEDED = "Remplacé par la version qualité."
QUALITY_NOTE = "Approuvé sur l'aperçu rapide ; version qualité générée automatiquement."
CANCELLED = "Approbation annulée après examen de la version qualité."


def _reject_siblings(conn, render, reviewer: str) -> None:
    """Le choix d'une variante écarte les autres variantes du même lot encore en attente."""
    if not render["batch_id"]:
        return
    label = layout_label(render["layout"])
    for sibling in db.batch_renders(conn, render["batch_id"]):
        if sibling["id"] != render["id"] and sibling["status"] == "pending":
            db.insert_approval(conn, sibling["id"], sibling["sha256"], "rejected", reviewer,
                               f"{VARIANT_NOT_KEPT} : « {label} » choisie.")


def needs_quality_pass(render, params: dict) -> bool:
    """Aperçu créé par l'IA en mode rapide : l'approuver déclenche le passage en qualité."""
    return (render["background_source"] == "ia_locale" and bool(params.get("scene_path"))
            and not params.get("quality_of"))


def _approve_with_quality(conn, render, params: dict, reviewer: str, comment: str) -> int:
    """Passage en qualité de la scène, même mise en page recomposée, contrôles relancés.

    L'approbation est enregistrée sur le fichier final (celui qui sera exporté), avec la mention qu'elle a été
    donnée sur l'aperçu. Elle est refusée si la version qualité présente une anomalie ou un nouveau point à
    vérifier (par exemple l'action perdue) : la version qualité reste alors en attente d'examen.
    """
    from .quality_loop import quality_scene
    started = time.perf_counter()
    row, brief = db.get_brief(conn, render["brief_id"])
    profile = load_profile(brief.brand_id)
    plan = prepare_plan(profile, brief, render["template_id"], "ia_locale")
    size = FORMATS[brief.format_id]
    scene = Image.open(from_stored(params["scene_path"])).convert("RGB")
    attempt = sum(json.loads(r["params"]).get("quality_of") == render["id"] for r in db.list_renders(conn))
    final_scene, final_report = quality_scene(scene, params["loop"], scene.size,
                                              params["loop"].get("seed", params["seed"]) + attempt)
    cache: dict = {}

    def background(s):
        if s not in cache:
            cache[s] = scene_to_background(final_scene, s, params)
        return cache[s]

    comp = compose(profile, brief, size, render["template_id"], background, render["layout"])
    base = {k: v for k, v in params.items() if k not in ("layers", "layout", "plan_warnings")}
    final_params = {**base, "quality_of": render["id"], "scene_quality_path": save_scene(final_scene),
                    "quality_model": model_spec("quality")[0], "loop": {**params["loop"], "final": final_report}}
    final_id = _save(conn, row, brief, profile, plan, render["template_id"], "ia_locale", final_params, comp,
                     next(iter(cache.values())), started, render["batch_id"])

    acknowledged = {c["name"] for c in db.get_checks(conn, render["id"]) if c["status"] == NON_CONCLUANT}
    final_checks = db.get_checks(conn, final_id)
    blocking = [c["name"] for c in final_checks if c["status"] == ANOMALIE]
    blocking += [c["name"] for c in final_checks if c["status"] == NON_CONCLUANT and c["name"] not in acknowledged]
    if blocking:
        conn.commit()  # la version qualité est conservée, en attente d'examen
        raise QualityNotApproved(final_id, "Version qualité créée, mais non approuvée automatiquement : "
                                           f"{', '.join(blocking)}. Examinez-la avant de décider.")
    final = db.get_render(conn, final_id)
    approval_id = db.insert_approval(conn, final_id, final["sha256"], "approved", reviewer,
                                     f"{comment} — {QUALITY_NOTE}" if comment else QUALITY_NOTE)
    db.insert_approval(conn, render["id"], render["sha256"], "rejected", reviewer, SUPERSEDED)
    _reject_siblings(conn, final, reviewer)
    return approval_id


def cancel_quality_approval(conn, render_id: str, reviewer: str) -> str | None:
    """Annule l'approbation d'une version qualité : elle est rejetée, l'aperçu et ses variantes sont rouverts.

    Renvoie l'identifiant de l'aperçu rouvert (None s'il ne s'agit pas d'une version qualité).
    """
    render = db.get_render(conn, render_id)
    preview_id = json.loads(render["params"]).get("quality_of")
    decide(conn, render_id, "rejected", reviewer, CANCELLED)
    if preview_id:
        batch = db.batch_renders(conn, render["batch_id"]) if render["batch_id"] else [db.get_render(conn, preview_id)]
        for r in batch:
            last = db.latest_approval(conn, r["id"])
            if r["status"] == "rejected" and last and (last["comment"] == SUPERSEDED
                                                       or last["comment"].startswith(VARIANT_NOT_KEPT)):
                db.reopen_render(conn, r["id"])
    return preview_id


class DeleteRefused(RuntimeError):
    pass


def linked_versions(conn, render_id: str) -> list:
    """Le visuel et ses versions liées : l'aperçu et sa (ses) version(s) finale(s) en haute qualité."""
    render = db.get_render(conn, render_id)
    preview_id = json.loads(render["params"]).get("quality_of") or render_id
    rows = [r for r in db.list_renders(conn)
            if r["id"] == preview_id or json.loads(r["params"]).get("quality_of") == preview_id]
    return rows or [render]


def delete_render(conn, render_id: str) -> list[str]:
    """Supprime un visuel de la galerie : fichier, contrôles, décisions, et ses versions liées (aperçu / finale).

    Un visuel exporté n'est jamais supprimé : la trace de ce qui a été livré doit rester. Les scènes créées par
    l'IA ne sont effacées que si plus aucun visuel ne les utilise (les variantes d'un lot partagent la même).
    Renvoie les identifiants supprimés.
    """
    rows = linked_versions(conn, render_id)
    if any(db.is_exported(conn, r["id"]) for r in rows):
        raise DeleteRefused("Ce visuel a déjà été téléchargé en version finale : il reste dans l'historique.")
    scenes = set()
    for r in rows:
        params = json.loads(r["params"])
        scenes.update(params[k] for k in ("scene_path", "scene_quality_path") if params.get(k))
        db.delete_render_rows(conn, r["id"])
        if r["file_path"]:
            from_stored(r["file_path"]).unlink(missing_ok=True)
    still_used = set()
    for r in conn.execute("SELECT params FROM renders"):
        params = json.loads(r["params"])
        still_used.update(params.get(k) for k in ("scene_path", "scene_quality_path"))
    for scene in scenes - still_used:
        from_stored(scene).unlink(missing_ok=True)
    return [r["id"] for r in rows]


def export_approved(conn, render_id: str) -> Path:
    render = db.get_render(conn, render_id)
    approval = db.latest_approval(conn, render_id)
    if approval is None or approval["decision"] != "approved":
        raise ExportBlocked("Export bloqué : aucune approbation humaine valide pour ce rendu.")
    source = from_stored(render["file_path"])
    if approval["sha256"] != render["sha256"] or file_sha256(source) != approval["sha256"]:
        raise ExportBlocked("Export bloqué : le fichier ne correspond plus à la version approuvée.")
    target = safe_path(DIRS["approved"], source.name)
    shutil.copy2(source, target)
    if file_sha256(target) != approval["sha256"]:
        target.unlink()
        raise ExportBlocked("Export interrompu : copie corrompue.")
    db.insert_export(conn, render_id, approval["id"], target)
    return target
