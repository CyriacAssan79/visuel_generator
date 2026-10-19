"""Boucle de contrôle qualité de la scène générée par l'IA (docs/generation-images.md).

Création (≤ budget, en silence) :
  1. gabarit d'action : l'objet est reconnu dans la description, le geste est mis en avant, la question de
     contrôle est préparée ;
  2. jusqu'à `max_candidates` images rapides, chacune contrôlée : visage (géométrie, taille, netteté), puis action ;
  3. si aucune ne fait l'action : localisation de la main et ajout de l'objet (retouche rapide de la zone) ;
  4. la meilleure image est retenue, avec un rapport enregistré (affiché dans les contrôles du visuel).
Approbation : passage en qualité de la scène retenue, puis nouveau contrôle du visage et de l'action.

La logique ne dépend pas des modèles : elle passe par un « backend » (OpenVINO en production, simulé en test).
"""
import re
import time
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

from .saliency import face_quality

# Éléments exclus : texte et logo (ajoutés ensuite), nudité (sans tenue précisée, Realistic Vision produit
# volontiers des personnes torse nu), aspect « personnage de synthèse », défauts d'anatomie (liste de l'auteur
# de Realistic Vision). Limite : l'encodeur de texte lit 75 jetons. Liste mesurée à 70 jetons, par priorité.
NEGATIVE_PROMPT = ("text, letters, logo, watermark, signage, nsfw, nude, shirtless, cartoon, cgi, 3d render, doll, "
                   "plastic skin, exaggerated smile, too many teeth, deformed face, asymmetric eyes, deformed iris, "
                   "mutated hands, extra fingers, fused fingers, bad anatomy, extra limbs, blurry, low quality")
# Le modèle rapide (LCM) ignore la liste d'exclusion : le style photographique est ajouté à la description.
LCM_PHOTO_STYLE = "candid photo, 35mm photograph, natural skin texture, natural expression"

# Objet reconnu dans la description anglaise -> geste mis en avant, question de contrôle, objet tenu en main ?
# Les formulations du geste viennent du banc d'essai (2026-10-19) : « tenu dans la main », vue de profil ou de 3/4.
ACTIONS = [
    (r"power drill|\bdrill", "power drill",
     "holding a cordless power drill in the hand pressed against the wall, drilling a hole",
     "drilling into the wall with a power drill held in their hand", True),
    (r"screwdriver", "screwdriver", "holding a screwdriver in the hand, driving a screw",
     "using a screwdriver held in their hand", True),
    (r"watering can", "watering can",
     "pouring water from a watering can held in the hand onto the plants, water stream visible",
     "watering plants with a watering can held in their hand", True),
    (r"garden hose|\bhose\b", "garden hose", "holding a garden hose in the hand, spraying water onto the plants",
     "watering plants with a garden hose held in their hand", True),
    (r"cardboard box|\bboxe?s?\b|\bcartons?\b", "cardboard box",
     "carrying a large plain cardboard box in both arms against the chest", "carrying a cardboard box in their arms",
     True),
    (r"paint roller", "paint roller", "rolling paint onto the wall with a paint roller held in both hands",
     "painting the wall with a paint roller held in their hand", True),
    (r"paintbrush|paint brush|\bbrush\b", "paintbrush", "painting the wall with a paintbrush held in the hand",
     "painting with a paintbrush held in their hand", True),
    (r"hammer", "hammer", "holding a hammer in the hand, hammering a nail into a wooden plank",
     "using a hammer held in their hand", True),
    (r"jigsaw|\bsaw\b", "saw", "cutting a wooden plank with a saw held in the hand",
     "cutting wood with a saw held in their hand", True),
    (r"tape measure", "tape measure", "measuring a wooden plank with a tape measure held in both hands",
     "measuring with a tape measure held in their hands", True),
    (r"shovel|spade", "shovel", "digging the soil with a shovel held in both hands",
     "digging with a shovel held in their hands", True),
    (r"lawn ?mower", "lawn mower", "pushing a lawn mower with both hands on the handle", "pushing a lawn mower",
     False),
    (r"wheelbarrow", "wheelbarrow", "pushing a wheelbarrow with both hands", "pushing a wheelbarrow", False),
    (r"ladder", "ladder", "standing on a ladder", "standing on a ladder", False),
]
VIEW = "three-quarter view"

# Durées estimées (s, puce graphique Iris Xe) pour ne pas lancer une étape qui dépasserait le budget
EST_CANDIDATE, EST_CHECK, EST_LOCATE, EST_ADD = 8, 3, 7, 9


@dataclass
class ActionPlan:
    prompt: str                 # description envoyée au modèle rapide
    object: str | None = None   # objet tenu, si reconnu
    question: str | None = None
    holdable: bool = False      # l'objet peut-il être ajouté dans la main par retouche ?


def photo_style(prompt_en: str) -> str:
    """« A realistic image of… » pousse le modèle vers un rendu 3D, « carton » : remplacé par un style photo."""
    return re.sub(r"\b(?:an? )?(?:hyper-?|ultra-?)?realistic (?:image|picture|photo|photograph|render)(?: of)?\b",
                  "candid photo of", prompt_en, flags=re.IGNORECASE)


PERSON = r"\b(?:man|men|woman|women|person|people|boy|girl|guy|lady|couple|child|kid|worker|portrait)\b"
CLOTHING = (r"\b(?:wearing|dressed|clothes|clothing|clothed|outfit|uniform|shirt|t-shirt|tshirt|polo|dress|overalls|"
            r"apron|jacket|coat|sweater|hoodie|blouse|tunic|boubou|jeans|trousers|pants|suit)\b")
DRESSED = "wearing a casual shirt, fully clothed"


def dress(prompt_en: str) -> str:
    """Sans tenue précisée, le modèle rapide dénude volontiers (3 images sur 4 au banc d'essai) : tenue imposée."""
    if re.search(PERSON, prompt_en, re.IGNORECASE) and not re.search(CLOTHING, prompt_en, re.IGNORECASE):
        return f"{prompt_en}, {DRESSED}"
    return prompt_en


def plan_action(prompt_en: str) -> ActionPlan:
    """Gabarit fixe (sans modèle de langage : la réécriture par IA s'est révélée lente et peu fiable)."""
    prompt_en = dress(photo_style(prompt_en))
    text = prompt_en.lower()
    for pattern, obj, gesture, check, holdable in ACTIONS:
        if re.search(pattern, text):
            # « regarde l'objectif » contredit le geste : la personne regarde ce qu'elle fait
            base = re.sub(r",?\s*looking (at|into) the camera", "", prompt_en).strip(" ,")
            return ActionPlan(f"{gesture}, {VIEW}, {base}", obj, f"Is the person {check}?", holdable)
    return ActionPlan(prompt_en)


def hand_mask(box, size) -> Image.Image:
    """Zone carrée autour de la main, deux fois plus large qu'elle (place pour l'objet), bords adoucis."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    half = max(box[2] - box[0], box[3] - box[1])
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle([cx - half, cy - half, cx + half, cy + half], fill=255)
    return mask.filter(ImageFilter.GaussianBlur(8))


def _face_ok(face) -> bool:
    return face is None or face["ok"]  # pas de visage = scène sans personne : rien à refuser


def create(prompt_en: str, seed: int, backend, *, budget_s=90, max_candidates=3, object_attempts=2,
           face_fn=face_quality, clock=time.perf_counter) -> tuple[Image.Image, dict]:
    """Scène retenue et rapport de la boucle (enregistré avec le visuel).

    Ordre des contrôles d'une candidate : visage, tenue (personne dévêtue = éliminée), puis action.
    """
    t0 = clock()
    left = lambda: budget_s - (clock() - t0)  # noqa: E731
    plan = plan_action(prompt_en)
    candidates, chosen = [], None
    for i in range(max_candidates):
        if i and left() < EST_CANDIDATE + EST_CHECK * (2 if plan.question else 1):
            break
        image = backend.generate(f"{plan.prompt}, {LCM_PHOTO_STYLE}", seed + i)
        face = face_fn(image)
        bare = backend.is_bare(image) if face is not None else None  # dès qu'une personne est visible
        action = (backend.action_done(plan.question, image)
                  if plan.question and _face_ok(face) and not bare else None)
        candidates.append({"image": image, "face": face, "bare": bare, "action": action, "seed": seed + i})
        if _face_ok(face) and not bare and action is not False:
            chosen = candidates[-1]
            break

    object_added = False
    if chosen is None:
        chosen = max(candidates, key=lambda c: (not c["bare"], _face_ok(c["face"]),
                                                 (c["face"] or {}).get("score", 0)))
        if plan.holdable and not chosen["bare"] and left() >= EST_LOCATE + EST_ADD + EST_CHECK:
            box = backend.locate_hand(plan.object, chosen["image"])
            for k in range(object_attempts if box else 0):
                if left() < EST_ADD + EST_CHECK:
                    break
                fixed = backend.add_object(chosen["image"], hand_mask(box, chosen["image"].size),
                                           f"a hand firmly holding a {plan.object}, {plan.prompt}, {LCM_PHOTO_STYLE}",
                                           seed + 100 + k)
                if backend.action_done(plan.question, fixed):
                    chosen = {**chosen, "image": fixed, "face": face_fn(fixed), "action": True}
                    object_added = True
                    break

    report = {
        "prompt": plan.prompt, "object": plan.object, "question": plan.question,
        "action_verified": chosen["action"] if plan.question else None,
        "face": chosen["face"], "clothed": None if chosen["bare"] is None else not chosen["bare"],
        "candidates": len(candidates), "object_added": object_added,
        "seed": chosen["seed"], "duration_s": round(clock() - t0, 1),
    }
    return chosen["image"], report


def finalize(scene: Image.Image, report: dict, seed: int, backend, *, strength=0.4,
             face_fn=face_quality) -> tuple[Image.Image, dict]:
    """Passage en qualité (image vers image), puis nouveaux contrôles : tenue, visage, geste."""
    final = backend.refine(scene, report["prompt"], seed, strength)
    face = face_fn(final)
    bare = backend.is_bare(final) if face is not None else None
    action = backend.action_done(report["question"], final) if report.get("question") else None
    return final, {"face": face, "clothed": None if bare is None else not bare, "action_verified": action,
                   "strength": strength}


# --- Production : modèles OpenVINO ----------------------------------------------------------------------
class OpenVINOBackend:
    def __init__(self, pipes: dict, size):
        from .models_manager import model_spec
        self.pipes, self.size = pipes, tuple(size)
        self.fast = model_spec("fast")[1]
        self.quality = model_spec("quality")[1]

    @staticmethod
    def _tensor(image):
        import numpy as np
        import openvino as ov
        return ov.Tensor(np.asarray(image.convert("RGB"))[None])

    def _common(self, spec, seed):
        return {"width": self.size[0], "height": self.size[1], "num_inference_steps": spec["steps"],
                "guidance_scale": spec.get("guidance_scale", 7.5), "rng_seed": seed}

    def generate(self, prompt, seed):
        return Image.fromarray(self.pipes["text2image"].generate(prompt, **self._common(self.fast, seed)).data[0])

    def add_object(self, image, mask, prompt, seed):
        out = self.pipes["inpaint"].generate(prompt, self._tensor(image), self._tensor(mask.convert("RGB")),
                                             strength=0.9, **self._common(self.fast, seed))
        return Image.fromarray(out.data[0])

    def refine(self, image, prompt, seed, strength):
        out = self.pipes["image2image"].generate(prompt, self._tensor(image), negative_prompt=NEGATIVE_PROMPT,
                                                 strength=strength, **self._common(self.quality, seed))
        return Image.fromarray(out.data[0])

    def action_done(self, question, image):
        from .verifier import action_done
        return action_done(self.pipes["verifier"], question, image)

    def is_bare(self, image):
        from .verifier import is_bare
        return is_bare(self.pipes["verifier"], image)

    def locate_hand(self, obj, image):
        from .verifier import locate_hand
        return locate_hand(self.pipes["verifier"], obj, image)


def loop_settings() -> dict:
    from .models_manager import settings
    return settings().get("loop", {})


def create_scene(prompt_en: str, size, seed: int) -> tuple[Image.Image, dict]:
    """Création contrôlée ; Realistic Vision est ensuite préchargé pendant que l'utilisateur regarde le visuel."""
    from .models_manager import MANAGER
    cfg = loop_settings()
    with MANAGER.use("creation", size) as pipes:
        scene, report = create(prompt_en, seed, OpenVINOBackend(pipes, size), budget_s=cfg.get("budget_s", 90),
                               max_candidates=cfg.get("max_candidates", 3),
                               object_attempts=cfg.get("object_attempts", 2))
    MANAGER.preload("quality", size)
    return scene, report


def quality_scene(scene: Image.Image, report: dict, size, seed: int) -> tuple[Image.Image, dict]:
    """Passage en qualité à l'approbation ; le modèle rapide est ensuite rechargé pour la création suivante."""
    from .models_manager import MANAGER
    cfg = loop_settings()
    with MANAGER.use("quality", size) as pipes:
        final, final_report = finalize(scene, report, seed, OpenVINOBackend(pipes, size),
                                       strength=cfg.get("quality_strength", 0.4))
    MANAGER.preload("creation", size)
    return final, final_report
