"""Sources d'image de fond interchangeables : photo importée, formes géométriques, IA locale."""
import gc
import random
from functools import lru_cache
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from .config import DIRS, OV_CACHE, from_stored
from .translate import TRANSLATION_MODEL, translate_prompt
from .models import BrandProfile

SUPERSAMPLE = 3


class SourceUnavailable(RuntimeError):
    """La source ne peut pas produire d'image sur cette machine (erreur visible, jamais masquée)."""


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


# Éléments exclus : texte et logo (ajoutés ensuite), aspect « personnage de synthèse » (sourire forcé, peau
# plastique), défauts d'anatomie (liste recommandée par l'auteur de Realistic Vision) et nudité : sans tenue
# précisée, Realistic Vision produit volontiers des personnes torse nu, inacceptable pour une marque.
# Limite : l'encodeur de texte lit 75 jetons, la suite est ignorée. Liste mesurée à 70 jetons, par priorité.
NEGATIVE_PROMPT = ("text, letters, logo, watermark, signage, nsfw, nude, shirtless, cartoon, cgi, 3d render, doll, "
                   "plastic skin, exaggerated smile, too many teeth, deformed face, asymmetric eyes, deformed iris, "
                   "mutated hands, extra fingers, fused fingers, bad anatomy, extra limbs, blurry, low quality")
# Les modèles LCM ignorent la liste d'exclusion : le style photographique est alors ajouté à la description.
LCM_PHOTO_STYLE = "candid photo, 35mm photograph, natural skin texture, natural expression"

# Mots-clés de la direction artistique (français) -> description de scène pour le modèle (anglais).
# Suggestions en français : la description est traduite en anglais au moment de la génération.
SCENE_HINTS = [
    (("rayon", "magasin"), "rayon d'un magasin de bricolage avec des outils et des pots de peinture"),
    (("jardin", "jardinage", "plante"), "jardin luxuriant avec des plantes et des outils de jardinage"),
    (("salle de bain", "sanitaire"), "salle de bain moderne et lumineuse"),
    (("cuisine",), "cuisine moderne et lumineuse"),
    (("intérieur", "maison", "salon"), "salon moderne et chaleureux"),
    (("peinture",), "mur fraîchement peint avec des pots de peinture et des rouleaux"),
]
DEFAULT_SCENE = "atelier de bricolage, mur perforé avec des outils, établi en bois"
PROMPT_STYLE = "lumière naturelle chaude, photo réaliste, arrière-plan flou"


def suggest_prompt(visual_direction: str) -> str:
    direction = visual_direction.lower()
    scene = next((s for words, s in SCENE_HINTS if any(w in direction for w in words)), DEFAULT_SCENE)
    return f"{scene}, {PROMPT_STYLE}"


def _model_settings() -> dict:
    with (DIRS["brands"].parent / "models.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def active_model(key: str | None = None) -> tuple[str, dict] | None:
    """Modèle demandé, sinon le modèle actif par défaut (None si aucun n'est retenu)."""
    settings = _model_settings()
    key = key or settings.get("active")
    if not key:
        return None
    if key not in settings["models"]:
        raise SourceUnavailable(f"Modèle IA inconnu : {key}")
    return key, settings["models"][key]


def model_choices() -> list[tuple[str, dict]]:
    """Modèles proposés dans l'application, dans l'ordre du fichier de configuration."""
    settings = _model_settings()
    return [(k, settings["models"][k]) for k in settings.get("choices", [])]




@lru_cache(maxsize=1)
def _diffusers_pipeline(repo: str, pipeline: str):
    import diffusers
    import torch
    pipe = getattr(diffusers, pipeline).from_pretrained(
        repo, dtype=torch.float32, variant="fp16", safety_checker=None, requires_safety_checker=False)
    pipe.set_progress_bar_config(disable=True)
    return pipe


_LOADED: dict = {}  # un seul modèle chargé à la fois : la mémoire de la puce graphique est partagée et limitée


def _release_loaded() -> None:
    _LOADED.clear()
    _diffusers_pipeline.cache_clear()
    gc.collect()


def _openvino_model_dir(spec: dict) -> Path:
    """Dossier du modèle : converti sur la machine (`path`), sinon téléchargé depuis Hugging Face (`repo`)."""
    if spec.get("path"):
        path = Path(spec["path"]).expanduser()
        if not (path / "model_index.json").is_file():
            raise SourceUnavailable(f"Modèle non converti sur cette machine ({path}) : lancer "
                                    f"{spec.get('convert_script', 'le script de conversion')} sous WSL.")
        return path
    from huggingface_hub import snapshot_download
    return Path(snapshot_download(spec["repo"]))


def _openvino_pipeline(spec: dict, device: str, width: int, height: int, guidance: float):
    """Pipeline OpenVINO compilé pour une taille fixe (formes statiques = plus rapide), gardé en mémoire.

    Le modèle précédent est libéré AVANT de charger le suivant : les deux ensemble dépassent la mémoire
    de la puce graphique intégrée.
    """
    scheduler = spec.get("scheduler")
    key = (spec.get("path") or spec["repo"], scheduler, device, width, height, guidance)
    if key in _LOADED:
        return _LOADED[key]
    _release_loaded()
    import openvino_genai as ov_genai
    model_dir = _openvino_model_dir(spec)
    pipe = ov_genai.Text2ImagePipeline(str(model_dir))
    if scheduler:  # planificateur recommandé par l'auteur du modèle, à la place de celui du dossier
        pipe.set_scheduler(ov_genai.Scheduler.from_config(str(model_dir / "scheduler" / "scheduler_config.json"),
                                                          getattr(ov_genai.Scheduler.Type, scheduler)))
    pipe.reshape(1, height, width, guidance)
    OV_CACHE.mkdir(parents=True, exist_ok=True)
    pipe.compile(device, CACHE_DIR=str(OV_CACHE))
    _LOADED[key] = pipe
    return pipe


@lru_cache(maxsize=1)
def openvino_devices() -> tuple[str, ...]:
    import openvino
    return tuple(openvino.Core().available_devices)


def resolve_device(requested: str) -> str:
    """Support demandé s'il est disponible ; sinon repli sur le processeur (ex. WSL sans pilote Intel)."""
    requested = requested.upper()
    return requested if requested in openvino_devices() else "CPU"


def generate_scene(spec: dict, prompt: str, width: int, height: int, seed: int) -> Image.Image:
    """Génère la scène avec le moteur déclaré pour le modèle (« diffusers » ou « openvino »)."""
    engine = spec.get("engine", "diffusers")
    if engine == "openvino":
        try:
            import openvino_genai  # noqa: F401
        except ImportError as exc:
            raise SourceUnavailable("OpenVINO GenAI n'est pas installé.") from exc
        guidance = spec.get("guidance_scale", 7.5)
        pipe = _openvino_pipeline(spec, resolve_device(spec.get("device", "CPU")), width, height, guidance)
        call = {"width": width, "height": height, "num_inference_steps": spec["steps"], "rng_seed": seed,
                "guidance_scale": guidance}
        if not spec.get("lcm"):  # les modèles LCM n'utilisent pas de prompt négatif
            call["negative_prompt"] = NEGATIVE_PROMPT
        else:
            prompt = f"{prompt}, {LCM_PHOTO_STYLE}"
        return Image.fromarray(pipe.generate(prompt, **call).data[0])
    try:
        import torch
    except ImportError as exc:
        raise SourceUnavailable("Aucun moteur IA local installé (torch/diffusers absents).") from exc
    if _LOADED:
        _release_loaded()
    return _diffusers_pipeline(spec["repo"], spec["pipeline"])(
        prompt=prompt, negative_prompt=NEGATIVE_PROMPT, num_inference_steps=spec["steps"], width=width,
        height=height, generator=torch.Generator("cpu").manual_seed(seed)).images[0]


class DiffusionSource:
    """Génération locale de la scène seule (jamais de texte ni de logo), modèle retenu après benchmark."""
    id = "ia_locale"
    label = "IA locale (modèle retenu après benchmark)"

    def make(self, size, profile: BrandProfile, params: dict) -> Image.Image:
        model = active_model(params.get("model_choice"))
        if model is None:
            raise SourceUnavailable("Moteur IA non configuré : aucun modèle retenu après benchmark "
                                    "(data/models.yaml, champ « active »).")
        key, spec = model
        if not params.get("prompt", "").strip():
            raise ValueError("Description de la scène (prompt) obligatoire pour la source IA.")
        base = spec["base_size"]
        # Ratio du gabarit, dimensions multiples de 64 autour de la taille native du modèle
        scale = base / max(size)
        gw, gh = (max(64, round(v * scale / 64) * 64) for v in size)
        params.setdefault("seed", random.randrange(10**9))
        engine = spec.get("engine", "diffusers")
        device = resolve_device(spec.get("device", "CPU")) if engine == "openvino" else "CPU"
        params.update({"model": key, "repo": spec["repo"], "licence": spec.get("licence"), "engine": engine,
                       "device": device,
                       "device_requested": spec.get("device", "CPU"), "steps": spec["steps"],
                       "guidance_scale": spec.get("guidance_scale"), "scheduler": spec.get("scheduler"),
                       "generated_size": [gw, gh],
                       "negative_prompt": None if spec.get("lcm") else NEGATIVE_PROMPT})
        # Description saisie en français ou en anglais : traduite ici, jamais affichée, enregistrée avec le rendu
        prompt_en, translated = translate_prompt(params["prompt"])
        params["prompt_en"] = prompt_en
        params["translation"] = TRANSLATION_MODEL if translated else None
        image = generate_scene(spec, prompt_en, gw, gh, params["seed"])
        image = ImageOps.fit(image, size, Image.Resampling.LANCZOS)
        saturation = params.get("saturation", 1.0)
        return ImageEnhance.Color(image).enhance(saturation) if saturation != 1.0 else image


SOURCES = {s.id: s for s in (PhotoSource(), GeometricSource(), DiffusionSource())}
