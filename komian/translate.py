"""Traduction locale français → anglais des descriptions de scène (MarianMT, Helsinki-NLP opus-mt-fr-en).

Les modèles d'images comprennent l'anglais : la description saisie en français est traduite dans le
processus de génération, sans être affichée. Un glossaire métier (photo, bricolage) est appliqué avant
la traduction, car le modèle généraliste confond des termes clés (« plan taille », « rayon », « établi »).
Les termes du glossaire sont protégés par des marqueurs pendant la traduction, puis réinsérés tels quels.
"""
import re
import unicodedata
from functools import lru_cache

TRANSLATION_MODEL = "Helsinki-NLP/opus-mt-fr-en"

# Terme français (expression régulière) -> terme anglais attendu par le modèle d'images. L'ordre compte :
# les expressions longues passent avant les mots isolés (« rayon de soleil » avant « rayon »).
GLOSSARY = [
    (r"rayons? de soleil", "sunbeams"),
    (r"plan (?:taille|moyen|poitrine)", "medium shot"),
    (r"plan rapproché|gros plan", "close-up shot"),
    (r"plan large|plan d'ensemble", "wide shot"),
    (r"plan américain", "medium full shot"),
    (r"plan (?:en )?pied", "full body shot"),
    (r"(?:le )?regard (?:vers|face à) l'objectif|regardant l'objectif|regarde l'objectif", "looking at the camera"),
    (r"mise au point nette", "sharp focus"),
    # Expressions et rendu : « smiling » produit des sourires forcés, « realistic photo » un rendu de synthèse.
    (r"(?:au |avec un )?(?:large |grand )?sourire naturel", "gentle natural smile"),
    (r"souriante?s?", "with a gentle natural smile"),
    # « réaliste » oriente le modèle vers un rendu 3D ou de synthèse : remplacé par un style photographique
    (r"(?:une )?(?:photo|image)s? r[ée]alistes?|photo-r[ée]aliste|photor[ée]aliste", "candid photo, 35mm photograph"),
    (r"visage détaillé", "natural skin texture"),
    (r"arrière-plan flou", "blurred background"),
    (r"(?:mur|panneau) perforé", "pegboard"),
    (r"établis?", "workbench"),
    (r"rayons? d'un magasin de bricolage|rayons? de magasin de bricolage", "home improvement store aisle"),
    (r"rayons?(?: d'un magasin| de magasin)?", "shop aisle"),
    (r"magasin de bricolage", "home improvement store"),
    (r"salopettes?", "overalls"),
    (r"pots? de peinture", "paint cans"),
    (r"rouleau(?:x)?(?: de peinture)?", "paint roller"),
    (r"scie sauteuse", "jigsaw"),
    (r"perceuse(?: visseuse)?", "power drill"),
    (r"visseuse", "cordless screwdriver"),
    (r"mètre ruban", "tape measure"),
    (r"niveau à bulle", "spirit level"),
    (r"(?:caisse|boîte) à outils", "toolbox"),
    (r"clé à molette", "adjustable wrench"),
    (r"tournevis", "screwdriver"),
    (r"lunettes de protection", "safety glasses"),
    (r"arrosoir", "watering can"),
    # Objets reconnus par la boucle de contrôle de l'action (komian/quality_loop.py, ACTIONS)
    (r"tuyaux? d'arrosage", "garden hose"),
    (r"cartons?", "cardboard box"),
    (r"pinceaux?", "paintbrush"),
    (r"marteaux?", "hammer"),
    (r"scies?", "saw"),
    (r"pelles?", "shovel"),
    (r"tondeuses?(?: à gazon)?", "lawn mower"),
    (r"brouettes?", "wheelbarrow"),
    (r"échelles?", "ladder"),
    (r"désaturée?s?", "desaturated"),
]
_GLOSSARY = [(re.compile(rf"\b{pattern}\b", re.IGNORECASE), english) for pattern, english in GLOSSARY]
_PLACEHOLDER = re.compile(r"TERM(\d+)[a-z]*")  # le traducteur peut ajouter un suffixe (« TERM2s » au pluriel)

FRENCH_WORDS = {"le", "la", "les", "un", "une", "des", "du", "de", "d", "avec", "dans", "sur", "et", "en", "au",
                "aux", "qui", "est", "son", "sa", "ses", "pour", "par", "très", "chez"}
# Mots anglais caractéristiques d'une description de scène : leur présence (sans mot français) suffit.
ENGLISH_WORDS = {"the", "a", "an", "with", "in", "on", "and", "of", "at", "wearing", "holding", "using", "light",
                 "lighting", "realistic", "smiling", "shot", "background", "interior", "focus", "sharp",
                 "camera", "detailed", "face", "warm", "natural", "looking", "woman", "man", "young", "old",
                 "wooden", "bright", "sunny", "garden", "workshop", "room", "living", "kitchen", "bathroom"}


def _has_accents(text: str) -> bool:
    return any(unicodedata.decomposition(c) for c in text if c.isalpha() and not c.isascii())


def _counts(text: str) -> tuple[int, int]:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return sum(w in FRENCH_WORDS for w in words), sum(w in ENGLISH_WORDS for w in words)


def is_french(text: str) -> bool:
    """La description doit-elle être traduite ? (accents, ou mots-outils français plus nombreux)."""
    if _has_accents(text):
        return True
    fr, en = _counts(text)
    return fr > en


def _is_english_segment(text: str) -> bool:
    """Segment à laisser tel quel : mots anglais caractéristiques, aucun mot français ni accent."""
    fr, en = _counts(text)
    return not _has_accents(text) and fr == 0 and en > 0


def _protect(text: str) -> tuple[str, list[str]]:
    """Remplace les termes du glossaire par TERM0, TERM1… (que le traducteur recopie sans les modifier)."""
    terms: list[str] = []

    def keep(english):
        def repl(_match):
            terms.append(english)
            return f"TERM{len(terms) - 1}"
        return repl

    for pattern, english in _GLOSSARY:
        text = pattern.sub(keep(english), text)
    return text, terms


def _restore(text: str, terms: list[str]) -> str:
    return _PLACEHOLDER.sub(lambda m: terms[int(m.group(1))] if int(m.group(1)) < len(terms) else "", text)


@lru_cache(maxsize=1)
def _model():
    from transformers import MarianMTModel, MarianTokenizer
    tokenizer = MarianTokenizer.from_pretrained(TRANSLATION_MODEL)
    model = MarianMTModel.from_pretrained(TRANSLATION_MODEL, use_safetensors=True).eval()
    return tokenizer, model


def _translate_segments(segments: list[str]) -> list[str]:
    import torch
    tokenizer, model = _model()
    with torch.no_grad():
        batch = tokenizer(segments, return_tensors="pt", padding=True, truncation=True)
        out = model.generate(**batch, max_new_tokens=128, num_beams=4)
    return [tokenizer.decode(o, skip_special_tokens=True).strip().rstrip(".") for o in out]


def translate_prompt(text: str) -> tuple[str, bool]:
    """Description prête pour le modèle d'images (anglais) et indicateur « a été traduite ».

    Le texte est découpé aux virgules et points-virgules : chaque élément est traduit séparément,
    pour qu'aucun détail d'une longue énumération ne soit perdu. Les éléments déjà en anglais, ou
    composés uniquement de termes du glossaire, ne passent pas par le traducteur.
    """
    text = " ".join(text.split())
    if not text or not is_french(text):
        return text, False
    protected, terms = _protect(text)
    segments = [s.strip() for s in re.split(r"[,;\n]", protected) if s.strip()]
    to_translate = [i for i, s in enumerate(segments)
                    if re.search(r"[^\W\d_]", _PLACEHOLDER.sub("", s)) and not _is_english_segment(s)]
    if to_translate:
        for i, english in zip(to_translate, _translate_segments([segments[i] for i in to_translate])):
            segments[i] = english
    return ", ".join(_restore(s, terms) for s in segments), True
