"""Contrôles de conformité. Trois états : conforme, anomalie, non_concluant.

Un contrôle qui ne peut pas s'exécuter de façon fiable est « non_concluant »,
jamais « conforme ».
"""
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .compose import Composition
from .config import FORMATS
from .models import BrandProfile, Brief

CONFORME, ANOMALIE, NON_CONCLUANT = "conforme", "anomalie", "non_concluant"
TEXT_BG_MAX_STD = 35        # au-delà, le fond sous le texte est trop hétérogène pour mesurer un contraste
MIN_TEXT_RATIO = 0.015      # taille minimale de texte, en fraction de la hauteur
FLAT_COLOR_MIN_SHARE = 0.95  # part minimale de pixels exactement aux couleurs de marque


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str
    limit: str | None = None


def normalize(text: str) -> str:
    return " ".join(text.split())


def luminance(rgb) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _texts(comp: Composition, prefix: str) -> list[dict]:
    return [l for l in comp.layers if l["kind"] == "text" and l["role"].startswith(prefix)]


def check_dimensions(path: Path, brief: Brief) -> CheckResult:
    expected = FORMATS[brief.format_id]
    with Image.open(path) as img:
        ok = img.size == expected and img.format == "PNG" and img.mode == "RGB"
        detail = f"Fichier {img.format} {img.mode} {img.size[0]}×{img.size[1]} ; attendu PNG RGB {expected[0]}×{expected[1]}"
    return CheckResult("Dimensions et format", CONFORME if ok else ANOMALIE, detail)


ROLE_LABELS = {"texte_exact": "texte", "accroche": "accroche", "mention_locale": "mentions locales",
               "mention_logo_locale": "mention du logo", "serie": "étiquette de série"}


def _role_label(role: str) -> str:
    return next((label for prefix, label in ROLE_LABELS.items() if role.startswith(prefix)), role)


def _worst(statuses) -> str:
    statuses = set(statuses)
    return ANOMALIE if ANOMALIE in statuses else NON_CONCLUANT if NON_CONCLUANT in statuses else CONFORME


def check_exact_text(comp: Composition, brief: Brief) -> CheckResult:
    """Texte exact (et accroche si affichée) : casse, accents et ponctuation identiques au brief."""
    fields = [("texte", "texte_exact", brief.exact_visual_text)]
    if brief.headline_on_visual:
        fields.append(("accroche", "accroche", brief.headline))
    problems = []
    for label, prefix, expected in fields:
        layers = _texts(comp, prefix)
        drawn = normalize(" ".join(" ".join(l["lines"]) for l in layers))
        if not layers:
            problems.append(f"{label} absent du visuel")
        elif drawn != normalize(expected):
            problems.append(f"{label} : « {drawn} » au lieu de « {normalize(expected)} »")
    if problems:
        return CheckResult("Textes exacts", ANOMALIE, " ; ".join(problems))
    return CheckResult("Textes exacts", CONFORME, "Identiques au brief (casse, accents, ponctuation).")


def check_series_tag(comp: Composition, brief: Brief, profile: BrandProfile) -> CheckResult | None:
    tag = profile.series_tag(brief.series) if brief.show_series_tag else None
    drawn = [l["text"] for l in _texts(comp, "serie")]
    if not tag:
        return None
    if not drawn:  # gabarit ou style sans étiquette (ex. blocs) : rien à contrôler
        return None
    if drawn == tag:
        return CheckResult("Étiquette de série", CONFORME, f"« {' / '.join(drawn)} » conforme au profil de marque.")
    return CheckResult("Étiquette de série", ANOMALIE, f"Composé : {drawn} ; attendu : {tag}")


def check_text_fit(comp: Composition, size) -> CheckResult:
    W, H = size
    problems = []
    for l in _texts(comp, ""):
        x0, y0, x1, y1 = l["bbox"]
        if not l["fitted"]:
            problems.append(f"« {l['text'][:30]} » ne tient pas dans sa zone")
        if l["size"] < H * MIN_TEXT_RATIO:
            problems.append(f"« {l['text'][:30]} » trop petit ({l['size']} px)")
        if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
            problems.append(f"« {l['text'][:30]} » déborde du visuel")
    if problems:
        return CheckResult("Texte complet et lisible", ANOMALIE, " ; ".join(problems))
    return CheckResult("Texte complet et lisible", CONFORME,
                       f"Tous les textes tiennent dans leur zone, taille ≥ {round(H * MIN_TEXT_RATIO)} px.")


def check_contrast(comp: Composition) -> CheckResult:
    """Contraste de tous les textes, en une ligne : seul le cas le plus défavorable est détaillé."""
    statuses, problems, ratios = [], [], []
    for l in _texts(comp, ""):
        label = _role_label(l["role"])
        if l["background_std"] > TEXT_BG_MAX_STD:
            statuses.append(NON_CONCLUANT)
            problems.append(f"{label} sur fond photo hétérogène, à vérifier à l'œil")
            continue
        ratio = contrast_ratio(l["color"], l["background_mean"])
        minimum = 3.0 if l["size"] >= 24 else 4.5
        ratios.append(ratio)
        if ratio < minimum:
            statuses.append(ANOMALIE)
            problems.append(f"{label} : {ratio:.1f}:1 (minimum {minimum}:1)")
        else:
            statuses.append(CONFORME)
    status = _worst(statuses)
    if status == CONFORME:
        return CheckResult("Contraste des textes", CONFORME, f"Ratio minimal {min(ratios):.1f}:1 (norme WCAG).")
    return CheckResult("Contraste des textes", status, " ; ".join(problems))


def check_ocr(comp: Composition, image: Image.Image) -> CheckResult:
    """Relecture OCR du texte et de l'accroche : le texte doit être lisible tel qu'affiché."""
    from . import ocr
    statuses, problems = [], []
    for l in _texts(comp, "texte_exact") + _texts(comp, "accroche"):
        label = _role_label(l["role"])
        try:
            read = ocr.read_region(image, l["bbox"])
        except ocr.OcrUnavailable as exc:
            return CheckResult("Lisibilité (OCR)", NON_CONCLUANT, str(exc), "Relecture humaine obligatoire.")
        except Exception as exc:
            statuses.append(NON_CONCLUANT)
            problems.append(f"{label} : OCR en échec ({type(exc).__name__})")
            continue
        if ocr.similarity(l["text"], read) >= ocr.READABLE_SIMILARITY:
            statuses.append(CONFORME)
        else:
            statuses.append(NON_CONCLUANT)
            problems.append(f"{label} mal relu (« {read} »), à vérifier à l'œil")
    if _worst(statuses) == CONFORME:
        return CheckResult("Lisibilité (OCR)", CONFORME, "Textes relus correctement par l'OCR.")
    return CheckResult("Lisibilité (OCR)", NON_CONCLUANT, " ; ".join(problems))


def check_faces(comp: Composition, background: Image.Image, size) -> CheckResult:
    from .compose import message_mask
    from .saliency import FaceDetectionUnavailable, faces_on_canvas
    from .workflow import MASK_SCALE, mask_face_cover
    name = "Visages dégagés"
    try:
        faces = faces_on_canvas(background, comp.layers)
    except FaceDetectionUnavailable as exc:
        return CheckResult(name, NON_CONCLUANT, str(exc), "Vérifier à l'œil que le message ne masque aucun visage.")
    mask = message_mask(comp, size, MASK_SCALE)
    covered = [(f, mask_face_cover(f, mask)) for f in faces]
    covered = [(f, o) for f, o in covered if o > 0.05]
    if covered:
        return CheckResult(name, ANOMALIE, "Le message recouvre " + ", ".join(
            f"un visage à {o:.0%} (confiance {f[4]:.0%})" for f, o in covered) + ".")
    if faces:
        return CheckResult(name, CONFORME, f"{len(faces)} visage(s) détecté(s), aucun masqué par le message.",
                           "Détection automatique : un visage de profil ou partiel peut échapper au détecteur.")
    return CheckResult(name, CONFORME, "Aucun visage détecté dans l'image.",
                       "Détection automatique : un visage de profil ou partiel peut échapper au détecteur.")


def check_logo(comp: Composition, image: Image.Image, brief: Brief, profile: BrandProfile) -> CheckResult:
    """Logo officiel présent, visible et placé comme demandé."""
    from .brands import asset_path, file_sha256
    logos = [l for l in comp.layers if l["kind"] == "logo"]
    if not logos:
        return CheckResult("Logo", ANOMALIE, "Aucun logo composé.")
    l = logos[0]
    problems = []
    region = image.crop(l["bbox"]).convert("L")
    bright = sum(1 for v in region.get_flattened_data() if v > 230) / max(1, region.width * region.height)
    if file_sha256(asset_path(profile, l["file"])) != l["sha256"] or bright <= 0.15:
        problems.append("ressource modifiée ou logo non visible")
    W, H = image.size
    x0, y0, x1, y1 = l["bbox"]
    actual = f"{'bas' if (y0 + y1) / 2 > H / 2 else 'haut'} à {'droite' if (x0 + x1) / 2 > W / 2 else 'gauche'}"
    if actual != brief.logo_position:
        problems.append(f"placé {actual} au lieu de {brief.logo_position}")
    if min(x0, y0, W - x1, H - y1) / W < 0.02:
        problems.append("trop près du bord")
    if problems:
        return CheckResult("Logo", ANOMALIE, " ; ".join(problems))
    return CheckResult("Logo", CONFORME, f"Présent et placé {actual}.")


def charter_points(profile: BrandProfile, comp: Composition) -> list[str]:
    """Points de charte non tranchés, identiques d'un rendu à l'autre : regroupés sur une seule ligne.

    Les règles d'usage du logo (taille minimale, zone de protection, fonds) ne sont signalées que tant qu'elles
    figurent parmi les points à confirmer du profil.
    """
    points = [u for u in profile.unknowns if "logo" in u.lower()]
    points += [w for w in comp.warnings if "logo" in w.lower()]
    return points


def check_colors(comp: Composition, image: Image.Image, profile: BrandProfile) -> CheckResult:
    allowed = profile.allowed_system_colors
    problems = []
    for l in comp.layers:
        if l["kind"] == "shape":
            for p in l["sample_points"]:
                got = image.getpixel(tuple(p))
                if max(abs(a - b) for a, b in zip(got, l["color"])) > 2:
                    problems.append(f"{l['role']} : {got} au lieu de {tuple(l['color'])}")
        if l["kind"] in ("shape", "text") and tuple(l["color"]) not in allowed.values():
            problems.append(f"{l['role']} : couleur hors charte {tuple(l['color'])}")
    if problems:
        return CheckResult("Couleurs des éléments ajoutés", ANOMALIE, " ; ".join(problems))
    return CheckResult("Couleurs des éléments ajoutés", CONFORME,
                       "Aplats et textes aux valeurs exactes de la charte, vérifiés sur l'image.",
                       "Ne couvre pas les couleurs de la photographie.")


def check_flat_background(background: Image.Image, profile: BrandProfile) -> CheckResult:
    allowed = set(profile.allowed_system_colors.values())
    pixels = background.convert("RGB").get_flattened_data()
    share = sum(1 for p in pixels if p in allowed) / len(pixels)
    status = CONFORME if share >= FLAT_COLOR_MIN_SHARE else ANOMALIE
    return CheckResult("Fond en aplats de marque", status,
                       f"{share:.1%} des pixels du fond exactement aux couleurs de la charte (seuil {FLAT_COLOR_MIN_SHARE:.0%}).",
                       "Le reste correspond au lissage des bords des formes.")


def check_spelling(brief: Brief, profile: BrandProfile) -> CheckResult:
    found = []
    for text in (brief.headline, brief.exact_visual_text):
        for bad in profile.forbidden_spellings:
            if re.search(rf"(?<!\w){re.escape(bad)}(?!\w)", text):
                found.append(bad)
        for abbr in profile.internal_only_abbreviations:
            if re.search(rf"(?<!\w){re.escape(abbr)}(?![\w.])", text):
                found.append(f"{abbr} (usage interne uniquement)")
    if found:
        return CheckResult("Orthographe de la marque", ANOMALIE, "Variantes interdites : " + ", ".join(found))
    return CheckResult("Orthographe de la marque", CONFORME,
                       f"Aucune variante interdite de « {profile.official_spelling} » dans les textes de campagne.",
                       "Les mentions locales (identifiant réseau social, adresse) ne sont pas concernées.")


# Critère de face_geometry non respecté -> défaut affiché
FACE_PROBLEMS = {"yeux à niveau": "yeux pas à niveau", "nez entre les yeux": "nez décalé",
                 "yeux, nez et bouche dans l'ordre": "traits mal placés", "écart des yeux": "écart des yeux anormal",
                 "visage trop petit": "visage trop petit dans l'image", "visage peu net ou déformé": "visage peu net"}


def loop_checks(loop: dict | None) -> list[CheckResult]:
    """Contrôles issus de la boucle de l'IA : sur la version qualité si elle existe, sinon sur l'aperçu."""
    if not loop:
        return []
    current = {**loop, **loop.get("final", {})}
    results = []
    if loop.get("question"):
        obj = loop.get("object")
        if current.get("action_verified"):
            detail = f"Geste avec l'objet « {obj} » vérifié automatiquement"
            if loop.get("object_added"):
                detail += " (objet ajouté dans la main par l'IA)"
            results.append(CheckResult("Action demandée", CONFORME, detail + ".",
                                       "Contrôle automatique par un modèle vision-langage."))
        else:
            results.append(CheckResult("Action demandée", NON_CONCLUANT,
                                       "L'action demandée n'apparaît pas : relancez ou utilisez une photo.",
                                       f"Objet attendu : {obj} ; contrôle automatique, à confirmer à l'œil."))
    if current.get("clothed") is False:
        results.append(CheckResult("Tenue", ANOMALIE, "Personne dévêtue (torse nu) : à ne pas publier. "
                                   "Relancez la création en précisant la tenue.",
                                   "Contrôle automatique par un modèle vision-langage."))
    elif current.get("clothed"):
        results.append(CheckResult("Tenue", CONFORME, "Personne habillée.",
                                   "Contrôle automatique par un modèle vision-langage."))
    face = current.get("face")
    if face:
        if face["ok"]:
            results.append(CheckResult("Visage", CONFORME, "Visage net et bien formé (yeux, nez, bouche).",
                                       f"{face['width']} px dans l'image générée, netteté {face['sharpness']}."))
        else:
            problems = [FACE_PROBLEMS.get(p, p) for p in face["problems"]]
            results.append(CheckResult("Visage", NON_CONCLUANT, "Visage à vérifier : " + ", ".join(problems) + ".",
                                       "Contrôle automatique des 5 points du visage (yeux, nez, coins de la bouche)."))
    return results


def run_checks(path: Path, comp: Composition, brief: Brief, profile: BrandProfile, plan_warnings: list[str],
               source_id: str, params: dict, background: Image.Image | None) -> list[CheckResult]:
    with Image.open(path) as img:
        image = img.convert("RGB")
    results = [check_dimensions(path, brief), check_exact_text(comp, brief), check_text_fit(comp, image.size)]
    tag_check = check_series_tag(comp, brief, profile)
    if tag_check:
        results.append(tag_check)
    results += [check_contrast(comp), check_logo(comp, image, brief, profile), check_colors(comp, image, profile)]
    if source_id == "geometrique" and background is not None:
        results.append(check_flat_background(background, profile))
    if source_id in ("photo", "ia_locale") and background is not None:
        results.append(check_faces(comp, background, image.size))
    for icon in brief.icons:
        drawn = any(l["role"] == f"icone_{icon}" for l in comp.layers)
        results.append(CheckResult(f"Icône « {icon} »", CONFORME if drawn else ANOMALIE,
                                   "Pictogramme composé en aplats de marque." if drawn else "Icône demandée absente."))
    results.append(check_spelling(brief, profile))
    results.append(check_ocr(comp, image))
    if source_id == "photo":
        if params.get("rights_confirmed_by"):
            results.append(CheckResult("Droits de la photo", CONFORME,
                                       f"Déclarés libres de droits par {params['rights_confirmed_by']}.",
                                       "Déclaration, non vérifiée par le système."))
        else:
            results.append(CheckResult("Droits de la photo", NON_CONCLUANT, "Droits d'utilisation non déclarés."))
    if source_id == "ia_locale":
        gw, gh = params.get("generated_size", (0, 0))
        results.append(CheckResult("Image générée par IA", NON_CONCLUANT,
                                   "Vérifier à l'œil la netteté, les mains et l'absence de texte parasite.",
                                   f"Modèle {params.get('model')} ({params.get('device')}), {gw}×{gh} px agrandi, "
                                   f"graine {params.get('seed')}."))
        results += loop_checks(params.get("loop"))
    if brief.constraints:
        results.append(CheckResult("Éléments interdits", NON_CONCLUANT,
                                   "À vérifier à l'œil : " + " ; ".join(brief.constraints)))
    charter = charter_points(profile, comp)
    brief_points = plan_warnings + [w for w in comp.warnings if w not in charter]
    if brief_points:
        results.append(CheckResult("Points à confirmer pour ce brief", NON_CONCLUANT, " ; ".join(brief_points)))
    if charter:
        results.append(CheckResult("Charte : points non tranchés", NON_CONCLUANT,
                                   f"{len(charter)} point(s) identiques pour tous les rendus : " + " ; ".join(charter),
                                   "À faire valider une fois par le responsable de marque."))
    return results
