"""Sources d'image de fond interchangeables : photo importée, formes géométriques, IA locale."""
import random
import uuid

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from .config import DIRS, from_stored, to_stored
from .models import BrandProfile
from .models_manager import SourceUnavailable, model_spec, openvino_devices, resolve_device  # noqa: F401
from .quality_loop import LCM_PHOTO_STYLE, NEGATIVE_PROMPT, create_scene, loop_settings  # noqa: F401
from .translate import TRANSLATION_MODEL, translate_prompt

SUPERSAMPLE = 3


class PhotoSource:
    id = "photo"
    label = "Photo importée (banque d'images libre de droits)"

    def make(self, size, profile: BrandProfile, params: dict) -> Image.Image:
        path = from_stored(params["photo_path"]).resolve()
        if not path.is_relative_to(DIRS["sources"].resolve()):
            raise ValueError("La photo doit provenir du répertoire d'import contrôlé.")
        photo = ImageOps.fit(Image.open(path).convert("RGB"), size, Image.Resampling.LANCZOS,
                             centering=(0.5, params.get("focus_y", 0.4)))
        saturation = params.get("saturation", 1.0)
        if saturation != 1.0:
            photo = ImageEnhance.Color(photo).enhance(saturation)
        return photo


class GeometricSource:
    """Formes simples en aplats de couleurs de marque, sans dégradé ni tramage."""
    id = "geometrique"
    label = "Formes géométriques (aplats de couleurs de marque)"
    variants = ("cercles", "diagonales", "blocs")

    def make(self, size, profile: BrandProfile, params: dict) -> Image.Image:
        variant = params["variant"]
        rng = random.Random(params["seed"])
        red = profile.primary_colors["rouge"].rgb
        white = (255, 255, 255)
        w, h = size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE
        base = red if variant == "blocs" else white
        ink = white if variant == "blocs" else red
        img = Image.new("RGB", (w, h), base)
        draw = ImageDraw.Draw(img)
        getattr(self, f"_{variant}")(draw, w, h, rng, ink, base)
        # Réduction LANCZOS = bords lissés ; les aplats restent à 100 %.
        return img.resize(size, Image.Resampling.LANCZOS)

    @staticmethod
    def _cercles(draw, w, h, rng, ink, base):
        for _ in range(rng.randint(4, 6)):
            r = rng.uniform(0.12, 0.32) * w
            cx = rng.choice([rng.uniform(-0.1, 0.25), rng.uniform(0.75, 1.1)]) * w
            cy = rng.uniform(-0.1, 1.0) * h
            if rng.random() < 0.4:
                ring = r * 0.12
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ink)
                draw.ellipse((cx - r + ring, cy - r + ring, cx + r - ring, cy + r - ring), fill=base)
            else:
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ink)

    @staticmethod
    def _diagonales(draw, w, h, rng, ink, base):
        band = rng.uniform(0.06, 0.1) * w
        gap = band * rng.uniform(1.6, 2.4)
        start = -h
        for i in range(int((w + 2 * h) / (band + gap))):
            x = start + i * (band + gap)
            if rng.random() < 0.65:
                draw.polygon([(x, h), (x + band, h), (x + band + h, 0), (x + h, 0)], fill=ink)
        corner = rng.uniform(0.35, 0.5) * w
        draw.polygon([(w, 0), (w - corner, 0), (w, corner)], fill=ink)

    @staticmethod
    def _blocs(draw, w, h, rng, ink, base):
        cols, rows = 4, 4
        cw, ch = w / cols, h / rows
        for c in range(cols):
            for r in range(rows):
                if rng.random() < 0.45:
                    x0, y0 = c * cw, r * ch
                    shape = rng.choice(["quart", "demi", "carre"])
                    if shape == "carre":
                        m = cw * 0.18
                        draw.rectangle((x0 + m, y0 + m, x0 + cw - m, y0 + ch - m), fill=ink)
                    elif shape == "quart":
                        corner = rng.choice([(x0, y0), (x0 + cw, y0), (x0, y0 + ch), (x0 + cw, y0 + ch)])
                        draw.ellipse((corner[0] - cw, corner[1] - ch, corner[0] + cw, corner[1] + ch), fill=ink)
                    else:
                        draw.pieslice((x0, y0, x0 + cw, y0 + ch * 2), 180, 360, fill=ink)



# Mots-clés de la direction artistique (français) -> description de scène pour le modèle (anglais).
# Suggestions en français : la description est traduite en anglais au moment de la génération.
SCENE_HINTS = [
    (("rayon", "magasin"), "rayon d'un magasin de bricolage avec des outils et des pots de peinture"),
    (("jardin", "jardinage", "plante"), "jardin luxuriant avec des plantes et des outils de jardinage"),
    (("salle de bain", "sanitaire"), "salle de bain moderne et lumineuse"),
    (("cuisine",), "cuisine moderne et lumineuse"),
    (("intérieur", "maison", "salon"), "salon moderne et chaleureux"),
    (("peinture",), "mur fraîchement peint avec des pots de peinture et des rouleaux"),
    (("chantier", "btp", "construction", "ouvrier"),
     "chantier de construction, immeuble en béton et échafaudages, ouvrier en gilet orange et casque blanc"),
]
DEFAULT_SCENE = "atelier de bricolage, mur perforé avec des outils, établi en bois"
PROMPT_STYLE = "lumière naturelle chaude, photo réaliste, arrière-plan flou"


def suggest_prompt(visual_direction: str, default_scene: str | None = None) -> str:
    """Scène proposée à partir de la direction artistique ; sinon la scène par défaut de la marque."""
    direction = visual_direction.lower()
    scene = next((s for words, s in SCENE_HINTS if any(w in direction for w in words)),
                 default_scene or DEFAULT_SCENE)
    return f"{scene}, {PROMPT_STYLE}"


def generated_size(size, area: int = 512 * 512) -> tuple[int, int]:
    """Taille de génération : même surface quel que soit le format (coût constant), au ratio du gabarit,
    en multiples de 64. Carré 512 × 512, portrait 448 × 576, story 384 × 704."""
    ratio = size[0] / size[1]
    return tuple(max(64, round(v / 64) * 64) for v in ((area * ratio) ** 0.5, (area / ratio) ** 0.5))


def scene_to_background(scene: Image.Image, size, params: dict) -> Image.Image:
    """Scène générée -> fond au format final (recadrage, agrandissement, saturation demandée)."""
    image = ImageOps.fit(scene.convert("RGB"), size, Image.Resampling.LANCZOS)
    saturation = params.get("saturation", 1.0)
    return ImageEnhance.Color(image).enhance(saturation) if saturation != 1.0 else image


def ai_configured() -> bool:
    """La source IA est-elle configurée (data/models.yaml) ? Ne charge aucun modèle."""
    try:
        return all(model_spec(role) for role in ("fast", "quality", "verifier"))
    except (SourceUnavailable, OSError):
        return False


def save_scene(scene: Image.Image) -> str:
    """Scène enregistrée (taille générée) : point de départ du passage en qualité à l'approbation."""
    DIRS["scenes"].mkdir(parents=True, exist_ok=True)
    path = DIRS["scenes"] / f"{uuid.uuid4().hex[:12]}.png"
    scene.save(path)
    return to_stored(path)


class DiffusionSource:
    """Scène seule (jamais de texte ni de logo), produite par la boucle de contrôle qualité."""
    id = "ia_locale"
    label = "IA locale (boucle de contrôle qualité)"

    def make(self, size, profile: BrandProfile, params: dict) -> Image.Image:
        if not params.get("prompt", "").strip():
            raise ValueError("Description de la scène (prompt) obligatoire pour la source IA.")
        fast_key, fast = model_spec("fast")
        verifier_key, verifier = model_spec("verifier")
        gw, gh = generated_size(size, loop_settings().get("area", 512 * 512))
        params.setdefault("seed", random.randrange(10**9))
        params.update({"model": fast_key, "repo": fast["repo"], "licence": fast.get("licence"),
                       "verifier": verifier_key, "verifier_licence": verifier.get("licence"),
                       "device": resolve_device(fast.get("device", "CPU")), "steps": fast["steps"],
                       "generated_size": [gw, gh]})
        # Description saisie en français ou en anglais : traduite ici, jamais affichée, enregistrée avec le rendu
        prompt_en, translated = translate_prompt(params["prompt"])
        params["prompt_en"] = prompt_en
        params["translation"] = TRANSLATION_MODEL if translated else None
        scene, report = create_scene(prompt_en, (gw, gh), params["seed"])
        params["loop"] = report
        params["scene_path"] = save_scene(scene)
        return scene_to_background(scene, size, params)


SOURCES = {s.id: s for s in (PhotoSource(), GeometricSource(), DiffusionSource())}
