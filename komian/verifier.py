"""Questions posées au modèle vision-langage (Qwen3-VL) : l'action est-elle faite ? où est la main ?

Banc d'essai du 2026-10-19 (32 images jugées à la main) : 94 % d'accord, aucun faux « oui » sur 19 échecs
et 32 questions pièges, ~3 s par question. Les modèles plus petits essayés (InternVL2 1B et 2B) répondaient
« oui » trop facilement.
"""
import re

import numpy as np
from PIL import Image

YES_NO = "{question} Look carefully at the hands. Answer only yes or no."
LOCATE_HAND = ('Locate the hand of the person that should hold the {obj}. '
               'Output only JSON: {{"bbox_2d": [x1, y1, x2, y2]}}.')


def _ask(vlm, text: str, image: Image.Image, max_tokens: int) -> str:
    import openvino as ov
    import openvino_genai as g
    config = g.GenerationConfig()
    config.max_new_tokens = max_tokens
    return vlm.generate(text, image=ov.Tensor(np.asarray(image.convert("RGB"))[None]),
                        generation_config=config).texts[0].strip()


def action_done(vlm, question: str, image: Image.Image) -> bool:
    """Seul un « yes » explicite compte : en cas de doute, l'action est considérée comme absente."""
    return _ask(vlm, YES_NO.format(question=question), image, 5).lower().startswith("yes")


BARE = "Is the person shirtless or showing a bare chest? Answer only yes or no."


def is_bare(vlm, image: Image.Image) -> bool:
    """Personne dévêtue ? (banc d'essai : 8 réponses justes sur 8, ~3 s). En cas de doute : non."""
    return _ask(vlm, BARE, image, 5).lower().startswith("yes")


def parse_box(text: str, size) -> list[float] | None:
    """Boîte « [x1, y1, x2, y2] » de Qwen3-VL (coordonnées relatives sur 0–1000) en pixels de l'image."""
    bracket = re.search(r"\[([^\]]*)\]", text)
    nums = [int(n) for n in re.findall(r"\d+", bracket.group(1))][:4] if bracket else []
    if len(nums) != 4:
        return None
    w, h = size
    x0, y0, x1, y1 = nums[0] * w / 1000, nums[1] * h / 1000, nums[2] * w / 1000, nums[3] * h / 1000
    return [x0, y0, x1, y1] if x1 > x0 and y1 > y0 else None


def locate_hand(vlm, obj: str, image: Image.Image) -> list[float] | None:
    return parse_box(_ask(vlm, LOCATE_HAND.format(obj=obj), image, 40), image.size)
