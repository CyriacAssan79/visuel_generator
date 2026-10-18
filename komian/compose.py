"""Composition des gabarits : textes exacts, aplats de marque, logo officiel.

Chaque élément ajouté est consigné dans `layers` pour que les contrôles puissent
vérifier l'image produite plutôt que de simples intentions.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

from .brands import asset_path, file_sha256
from .models import BrandProfile, Brief

WHITE = (255, 255, 255)


@dataclass
class Composition:
    image: Image.Image
    template_id: str
    layers: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    layout: str | None = None


def split_in_two(text: str) -> tuple[str, str]:
    """Coupe le texte exact en deux blocs sans modifier aucun caractère."""
    if "," in text:
        i = text.index(",") + 1
        return text[:i].strip(), text[i:].strip()
    words = text.split()
    half = (len(words) + 1) // 2
    return " ".join(words[:half]), " ".join(words[half:])


class Composer:
    def __init__(self, profile: BrandProfile, brief: Brief, size: tuple[int, int]):
        self.profile = profile
        self.brief = brief
        self.W, self.H = size
        self.layers: list[dict] = []
        self.layout: str = ""
        self.warnings: list[str] = []
        self._fonts: dict = {}

    # --- outils ------------------------------------------------------------

    def font(self, style: str, size: int) -> ImageFont.FreeTypeFont:
        key = (style, size)
        if key not in self._fonts:
            path = asset_path(self.profile, self.profile.fonts[style])
            self._fonts[key] = ImageFont.truetype(str(path), size)
        return self._fonts[key]

    def color(self, name: str) -> tuple[int, int, int]:
        return self.profile.allowed_system_colors[name]

    @staticmethod
    def wrap(text: str, font, max_w: float) -> list[str] | None:
        lines: list[str] = []
        for paragraph in text.split("\n"):
            current = ""
            for word in paragraph.split():
                if font.getlength(word) > max_w:
                    return None
                trial = f"{current} {word}".strip()
                if font.getlength(trial) <= max_w:
                    current = trial
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        return lines

    def fit(self, text, style, w, h, max_size, min_size, gap=0.12):
        for size in range(max_size, min_size - 1, -2):
            lines = self.wrap(text, self.font(style, size), w)
            if lines and self._block_height(size, len(lines), gap) <= h:
                return size, lines
        return None, None

    @staticmethod
    def _block_height(size, n, gap):
        return round(size * (1 + gap)) * n - round(size * gap)

    @staticmethod
    def background_stats(canvas: Image.Image, box) -> tuple[list[float], float]:
        x0, y0, x1, y1 = (int(v) for v in box)
        region = canvas.crop((max(x0, 0), max(y0, 0), min(x1, canvas.width), min(y1, canvas.height)))
        stat = ImageStat.Stat(region.convert("RGB"))
        lum_std = ImageStat.Stat(region.convert("L")).stddev[0]
        return [round(v, 1) for v in stat.mean], round(lum_std, 1)

    # --- éléments ------------------------------------------------------------

    def text(self, canvas, text, role, style, color_name, box, max_size, min_size,
             align="center", valign="center", gap=0.12, shadow=False):
        x, y, w, h = box
        size, lines = self.fit(text, style, w, h, max_size, min_size, gap)
        fitted = size is not None
        if not fitted:  # jamais tronqué : on affiche à la taille minimale et on le signale
            size = min_size
            lines = self.wrap(text, self.font(style, size), w) or text.split()
        font = self.font(style, size)
        line_h = round(size * (1 + gap))
        total = self._block_height(size, len(lines), gap)
        top = y + (h - total) / 2 if valign == "center" else y
        bg_mean, bg_std = self.background_stats(canvas, (x, y, x + w, y + h))

        draw = ImageDraw.Draw(canvas)
        color = self.color(color_name)
        positions = []
        for i, line in enumerate(lines):
            lw = font.getlength(line)
            lx = {"center": x + (w - lw) / 2, "left": x, "right": x + w - lw}[align]
            positions.append((lx, top + i * line_h, line))
        if shadow:  # ombre portée douce (noir, flou) pour détacher un texte posé sur une photo
            mask = Image.new("L", canvas.size, 0)
            mdraw = ImageDraw.Draw(mask)
            offset = max(2, round(size * 0.04))
            for lx, ly, line in positions:
                mdraw.text((lx + offset, ly + offset), line, font=font, fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(max(2, size * 0.12))).point(lambda v: round(v * 0.75))
            canvas.paste((0, 0, 0), (0, 0), mask)
        boxes = []
        for lx, ly, line in positions:
            draw.text((lx, ly), line, font=font, fill=color)
            boxes.append(draw.textbbox((lx, ly), line, font=font))
        bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))
        self.layers.append({
            "kind": "text", "role": role, "text": text, "lines": lines, "style": style,
            "font_file": self.profile.fonts[style], "size": size, "color_name": color_name,
            "color": color, "box": [x, y, w, h], "bbox": bbox, "fitted": fitted,
            "background_mean": bg_mean, "background_std": bg_std, "shadow": shadow,
        })
        return bbox

    def rect(self, canvas, box, color_name, role):
        x0, y0, x1, y1 = (round(v) for v in box)
        ImageDraw.Draw(canvas).rectangle((x0, y0, x1, y1), fill=self.color(color_name))
        self.layers.append({"kind": "shape", "role": role, "color_name": color_name, "bbox": (x0, y0, x1, y1),
                            "color": self.color(color_name), "sample_points": [(x0 + 3, y0 + 3), (x1 - 3, y1 - 3)]})

    def fading_panel(self, canvas, box, role, solid=0.68):
        """Panneau blanc opaque sur `solid` de sa largeur, puis fondu vers la transparence (références)."""
        x0, y0, x1, y1 = (round(v) for v in box)
        w, h = x1 - x0, y1 - y0
        ramp = np.clip((w - np.arange(w)) / max(1, w * (1 - solid)), 0, 1)
        mask = Image.fromarray(np.tile((ramp * 255).astype(np.uint8), (h, 1)))
        canvas.paste(Image.new("RGB", (w, h), WHITE), (x0, y0), mask)
        self.layers.append({"kind": "shape", "role": role, "color_name": "blanc", "color": WHITE,
                            "bbox": (x0, y0, x1, y1),
                            "sample_points": [(x0 + 3, y0 + 3), (x0 + round(w * solid * 0.9), y1 - 3)]})

    def badges(self, canvas, center, diameter):
        """Pastilles d'icônes demandées par le brief, alignées de droite à gauche depuis `center`."""
        for i, kind in enumerate(self.brief.icons):
            cx = center[0] - i * diameter * 1.15
            self.badge(canvas, kind, (cx, center[1]), diameter)

    def badge(self, canvas, kind, center, diameter):
        """Pastille rouge + pictogramme blanc, dessinés en aplats (sur-échantillonnés puis réduits)."""
        s = 4
        d = round(diameter) * s
        red, white = self.color("rouge"), WHITE
        tile = Image.new("RGBA", (d, d), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tile)
        u = d / 100  # unité relative
        draw.ellipse((0, 0, d - 1, d - 1), fill=white)  # liseré : détache la pastille d'un fond rouge
        draw.ellipse((4 * u, 4 * u, d - 1 - 4 * u, d - 1 - 4 * u), fill=red)
        if kind == "calendrier":
            draw.rounded_rectangle((27 * u, 31 * u, 73 * u, 74 * u), radius=5 * u, fill=white)
            draw.rectangle((27 * u, 43 * u, 73 * u, 46 * u), fill=red)
            for col in range(3):
                for row in range(2):
                    x, y = 33 * u + col * 13 * u, 51 * u + row * 11 * u
                    draw.rectangle((x, y, x + 8 * u, y + 7 * u), fill=red)
            for x in (37, 59):
                draw.rounded_rectangle((x * u, 24 * u, (x + 4) * u, 36 * u), radius=2 * u, fill=white)
        elif kind == "coche":
            draw.line([(28 * u, 52 * u), (44 * u, 68 * u), (73 * u, 35 * u)], fill=white, width=round(11 * u),
                      joint="curve")
        tile = tile.resize((round(diameter), round(diameter)), Image.Resampling.LANCZOS)
        x, y = round(center[0] - diameter / 2), round(center[1] - diameter / 2)
        canvas.paste(tile, (x, y), tile)
        self.layers.append({"kind": "shape", "role": f"icone_{kind}", "color_name": "rouge", "color": red,
                            "bbox": (x, y, x + round(diameter), y + round(diameter)),
                            "sample_points": [(round(center[0] - diameter * 0.4), round(center[1]))]})

    def band(self, canvas, top_ratio=0.765, depth_ratio=0.095):
        """Bandeau rouge à bord supérieur incurvé (gabarit des visuels de référence)."""
        s = 4
        W, H = self.W * s, self.H * s
        top, depth, cx = top_ratio * H, depth_ratio * H, W / 2
        pts = [(x, top + depth * (1 - ((x - cx) / cx) ** 2)) for x in range(0, W + 1, 4 * s)]
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).polygon(pts + [(W, H), (0, H)], fill=255)
        mask = mask.resize((self.W, self.H), Image.Resampling.LANCZOS)
        red = self.color("rouge")
        canvas.paste(Image.new("RGB", canvas.size, red), (0, 0), mask)
        self.layers.append({"kind": "shape", "role": "bandeau", "color_name": "rouge", "color": red,
                            "sample_points": [(self.W // 2, self.H - 6), (6, int(self.H * (top_ratio + 0.03)))]})

    def logo(self, canvas, logo_id, width, right, top):
        asset = self.profile.logo(logo_id)
        path = asset_path(self.profile, asset.file)
        img = Image.open(path).convert("RGBA")
        img = img.resize((width, round(img.height * width / img.width)), Image.Resampling.LANCZOS)
        x = right - width
        bg_mean, bg_std = self.background_stats(canvas, (x, top, x + img.width, top + img.height))
        canvas.paste(img, (x, top), img)
        vb = img.getchannel("A").getbbox()
        bbox = (x + vb[0], top + vb[1], x + vb[2], top + vb[3])
        self.layers.append({"kind": "logo", "logo_id": logo_id, "file": asset.file,
                            "sha256": file_sha256(path), "status": asset.status, "bbox": bbox,
                            "background_mean": bg_mean, "background_std": bg_std})
        if asset.status != "confirmé":
            self.warnings.append(f"Logo « {logo_id} » au statut « {asset.status} ».")
        return bbox

    def footer(self, canvas):
        """Mentions locales à gauche, logo blanc et mention « Maison et Jardin » à droite."""
        W, H = self.W, self.H
        lm = self.profile.local_market
        if lm:
            for i, value in enumerate([lm.handle, lm.address]):
                if value:
                    self.text(canvas, value, "mention_locale", "medium", "blanc",
                              (round(W * 0.055), round(H * (0.868 + i * 0.05)), round(W * 0.45), round(H * 0.045)),
                              max_size=round(H * 0.029), min_size=round(H * 0.016), align="left")
        logo_box = self.logo(canvas, "blanc_derive", round(W * 0.31), round(W * 0.955), round(H * 0.85))
        if lm and lm.tagline:
            self.text(canvas, lm.tagline, "mention_logo_locale", "regular", "blanc",
                      (logo_box[0], logo_box[3] + round(H * 0.004), logo_box[2] - logo_box[0], round(H * 0.04)),
                      max_size=round(H * 0.03), min_size=round(H * 0.016), align="right", valign="top")
            self.warnings.append("Mention « Maison et Jardin » recomposée en Ubuntu : logo local officiel à confirmer.")



# --- Gabarits ------------------------------------------------------------------
# Zone photo utilisable au-dessus du bandeau (le bandeau commence à 0,765 H sur les bords).
ZONE_TOP, ZONE_BOTTOM = 0.06, 0.74

LAYOUTS = {
    "haut_gauche": "En haut à gauche",
    "haut_centre": "En haut, centré",
    "centre_gauche": "Au centre, à gauche",
    "centre_droite": "Au centre, à droite",
    "haut_droite": "En haut à droite",
    "bas_gauche": "En bas à gauche",
    "bas_centre": "En bas, centré",
    "bas_droite": "En bas à droite",
    "centre": "Au centre",
    "gauche": "À gauche",
    "droite": "À droite",
}


def place_group(layout: str, W: int, H: int, w: float, h: float) -> tuple[float, float]:
    """Origine d'un groupe de taille w×h selon la disposition, dans la zone photo."""
    margin = W * 0.05
    horizontal = layout.split("_")[-1]
    x = {"gauche": margin, "droite": W - margin - w}.get(horizontal, (W - w) / 2)
    vertical = layout.split("_")[0]
    top, bottom = H * ZONE_TOP + H * 0.025, H * ZONE_BOTTOM - H * 0.01
    y = {"haut": top, "bas": bottom - h}.get(vertical, (top + bottom - h) / 2)
    return x, y


def _place_badges(c: "Composer", canvas, x0, y0, width, height, d):
    """Pastilles à droite du groupe, sinon à gauche, sinon sous le groupe."""
    n = len(c.brief.icons)
    if not n:
        return
    span = d * (1 + 1.15 * (n - 1))
    cy = y0 + height / 2
    if x0 + width + d * 0.25 + span <= c.W - c.W * 0.02:
        c.badges(canvas, (x0 + width + d * 0.75 + (n - 1) * d * 1.15, cy), d)
    elif x0 - d * 0.25 - span >= c.W * 0.02:
        c.badges(canvas, (x0 - d * 0.75, cy), d)
    else:
        c.badges(canvas, (x0 + width - d / 2, y0 + height + d * 0.7), d)


def _bandeau_titre_haut(c: "Composer", background) -> Image.Image:
    """Référence « La motivation suit l'action » : titres rouges en haut, photo, bandeau."""
    W, H = c.W, c.H
    top = round(H * 0.17)
    canvas = Image.new("RGB", (W, H), WHITE)
    bg = background((W, H - top))
    fade = Image.linear_gradient("L").resize((W, round(H * 0.06)))  # fondu de la photo vers le blanc
    canvas.paste(bg, (0, top))
    c.layers.append({"kind": "background", "role": "fond", "box": [0, top, W, H - top]})
    canvas.paste(Image.new("RGB", fade.size, WHITE), (0, top), Image.eval(fade, lambda v: 255 - v))
    align = "left" if c.layout == "haut_gauche" else "center"
    c.text(canvas, c.brief.headline, "accroche", "regular", "rouge",
           (round(W * 0.05), round(H * 0.022), round(W * 0.9), round(H * 0.055)),
           max_size=round(H * 0.036), min_size=round(H * 0.02), align=align)
    c.text(canvas, c.brief.exact_visual_text, "texte_exact", "bold", "rouge",
           (round(W * 0.05 if align == "left" else W * 0.03), round(H * 0.075), round(W * 0.94), round(H * 0.085)),
           max_size=round(H * 0.04), min_size=round(H * 0.022), align=align)
    c.badges(canvas, (W * 0.92, top + H * 0.075), round(W * 0.085))
    c.band(canvas)
    c.footer(canvas)
    return canvas


def _bandeau_blocs(c: "Composer", background) -> Image.Image:
    """Référence « Dernier lundi » : photo pleine, blocs rouge et vert positionnables."""
    W, H = c.W, c.H
    canvas = background((W, H)).copy()
    c.layers.append({"kind": "background", "role": "fond", "box": [0, 0, W, H]})
    part1, part2 = split_in_two(c.brief.exact_visual_text)
    pad = round(W * 0.025)
    max_w = round(W * 0.56)
    s1, l1 = c.fit(part1, "bold", max_w, H * 0.12, round(H * 0.05), round(H * 0.026))
    s2, l2 = c.fit(part2, "bold_italic", max_w, H * 0.12, round(H * 0.056), round(H * 0.026))
    show_head = c.brief.headline_on_visual
    s3, l3 = c.fit(c.brief.headline, "medium", max_w, H * 0.08, round(H * 0.024), round(H * 0.016))
    if not show_head:
        s3, l3 = 0, []
    if None in (s1, s2, s3):
        c.warnings.append("Texte trop long pour le gabarit à blocs.")
        s1, s2, s3 = s1 or round(H * 0.026), s2 or round(H * 0.026), s3 or round(H * 0.016)
        l1, l2, l3 = [part1], [part2], [c.brief.headline]
    width = max(max(c.font("bold", s1).getlength(t) for t in l1),
                max(c.font("bold_italic", s2).getlength(t) for t in l2),
                max((c.font("medium", s3).getlength(t) for t in l3), default=0)) + 2 * pad + 4  # marge anti-arrondi
    h1 = c._block_height(s1, len(l1), 0.12) + 2 * pad * 0.7
    h2 = c._block_height(s2, len(l2), 0.12) + (c._block_height(s3, len(l3), 0.12) + 0.6 * pad if show_head else 0)         + 2 * pad * 0.7
    x0, y0 = (round(v) for v in place_group(c.layout, W, H, width, h1 + h2))
    c.rect(canvas, (x0, y0, x0 + width, y0 + h1), "rouge", "bloc_titre_1")
    c.rect(canvas, (x0, y0 + h1, x0 + width, y0 + h1 + h2), "vert", "bloc_titre_2")
    inner = (round(x0 + pad), math.ceil(width - 2 * pad))
    c.text(canvas, part1, "texte_exact_1", "bold", "blanc",
           (inner[0], round(y0 + pad * 0.7), inner[1], round(h1 - 1.4 * pad)), max_size=s1, min_size=s1)
    y2 = y0 + h1 + pad * 0.7
    hp2 = c._block_height(s2, len(l2), 0.12)
    c.text(canvas, part2, "texte_exact_2", "bold_italic", "blanc",
           (inner[0], round(y2), inner[1], hp2), max_size=s2, min_size=s2)
    if show_head:
        c.text(canvas, c.brief.headline, "accroche", "medium", "blanc",
               (inner[0], round(y2 + hp2 + pad * 0.6), inner[1], c._block_height(s3, len(l3), 0.12)),
               max_size=s3, min_size=s3)
    _place_badges(c, canvas, x0, y0, width, h1 + h2, round(W * 0.085))
    c.band(canvas)
    c.footer(canvas)
    return canvas


def _citation_centree(c: "Composer", background) -> Image.Image:
    """Brief « formes géométriques » : citation sur carte blanche (centrée, à gauche ou à droite), bandeau."""
    W, H = c.W, c.H
    canvas = background((W, H)).copy()
    c.layers.append({"kind": "background", "role": "fond", "box": [0, 0, W, H]})
    card_w = W * (0.82 if c.layout == "centre" else 0.62)
    x0 = {"gauche": W * 0.07, "droite": W * 0.93 - card_w}.get(c.layout, (W - card_w) / 2)
    x1, y0, y1 = x0 + card_w, H * 0.15, H * 0.64
    frame = round(W * 0.012)
    c.rect(canvas, (x0 - frame, y0 - frame, x1 + frame, y1 + frame), "rouge", "cadre_citation")
    c.rect(canvas, (x0, y0, x1, y1), "blanc", "carte_citation")
    pad = W * (0.06 if c.layout == "centre" else 0.045)
    c.text(canvas, c.brief.headline, "accroche", "regular", "gris_sombre",
           (round(x0 + pad), round(y0 + pad * 0.8), round(x1 - x0 - 2 * pad), round(H * 0.07)),
           max_size=round(H * 0.034), min_size=round(H * 0.02))
    c.text(canvas, c.brief.exact_visual_text, "texte_exact", "bold", "rouge",
           (round(x0 + pad), round(y0 + pad * 0.8 + H * 0.085), round(x1 - x0 - 2 * pad),
            round(y1 - y0 - pad * 1.6 - H * 0.085)),
           max_size=round(H * 0.075), min_size=round(H * 0.03))
    corner = x0 if c.layout == "droite" else x1  # pastilles côté intérieur du visuel
    c.badges(canvas, (corner + (W * 0.1 * 1.15 * (len(c.brief.icons) - 1) if c.layout == "droite" else 0), y0),
             round(W * 0.1))
    c.band(canvas)
    c.footer(canvas)
    return canvas


def _series_tag(c: "Composer", canvas, x0, y0, draw=True) -> tuple[float, float]:
    """Étiquette de série des visuels livrés : bloc rouge (« Lundi ») puis bloc vert plus large (« MOTIVATION »)."""
    tag = c.profile.series_tag(c.brief.series) if c.brief.show_series_tag else None
    if not tag:
        return 0, 0
    W, H = c.W, c.H
    s1, s2 = round(H * 0.05), round(H * 0.036)
    pad = round(W * 0.018)
    w1 = c.font("bold", s1).getlength(tag[0]) + 2 * pad + 4
    w2 = max(c.font("bold_italic", s2).getlength(tag[1]) + 2 * pad + 4, w1 + W * 0.03)
    h1, h2 = round(s1 * 1.3), round(s2 * 1.45)
    if draw:
        c.rect(canvas, (x0, y0, x0 + w1, y0 + h1), "rouge", "bandeau_serie_1")
        c.text(canvas, tag[0], "serie_1", "bold", "blanc", (round(x0 + pad), round(y0), math.ceil(w1 - 2 * pad), h1),
               max_size=s1, min_size=s1, align="left")
        c.rect(canvas, (x0, y0 + h1, x0 + w2, y0 + h1 + h2), "vert", "bandeau_serie_2")
        c.text(canvas, tag[1], "serie_2", "bold_italic", "blanc",
               (round(x0 + pad), round(y0 + h1), math.ceil(w2 - 2 * pad), h2), max_size=s2, min_size=s2, align="left")
    return w2, h1 + h2


def _fit_or_min(c: "Composer", text, style, w, h, max_size, min_size, gap):
    size, lines = c.fit(text, style, w, h, max_size, min_size, gap)
    if size is None:
        c.warnings.append(f"« {text[:40]} » trop long pour la zone prévue.")
        size, lines = min_size, c.wrap(text, c.font(style, min_size), w) or [text]
    width = max(c.font(style, size).getlength(line) for line in lines)
    return size, lines, width, c._block_height(size, len(lines), gap)


def _message_photo(c: "Composer", background) -> Image.Image:
    """Visuels « Lundi motivation » livrés : étiquette de série + message, placé là où la photo le permet.

    Styles : « panneau » (panneau blanc à fondu, texte noir), « direct » (texte blanc ombré sur la photo,
    étiquette seule en haut), « blocs » (citation dans les blocs rouge et vert, sans étiquette).
    """
    style, pos = c.layout.split(":")
    if style == "blocs":
        c.layout = pos
        canvas = _bandeau_blocs(c, background)
        c.layout = f"blocs:{pos}"
        return canvas
    W, H = c.W, c.H
    canvas = background((W, H)).copy()
    c.layers.append({"kind": "background", "role": "fond", "box": [0, 0, W, H]})
    tag_w, tag_h = _series_tag(c, canvas, 0, 0, draw=False)
    exact, headline = c.brief.exact_visual_text, c.brief.headline
    show_head = c.brief.headline_on_visual
    d = round(W * 0.085)

    if style == "panneau":
        pad = round(W * 0.025)
        # Comme les visuels livrés : texte plus petit que l'étiquette, sur deux lignes de préférence
        sq, lq, qw, qh = _fit_or_min(c, exact, "bold", round(W * 0.56), H * 0.11, round(H * 0.031), round(H * 0.02), 0.18)
        hw = hh = 0
        if show_head:
            sh, lh, hw, hh = _fit_or_min(c, headline, "regular", round(W * 0.56), H * 0.08, round(H * 0.022),
                                         round(H * 0.016), 0.15)
        content_w = math.ceil(max(qw, hw)) + 4
        tail = W * 0.1  # queue du fondu vers la transparence
        panel_w = content_w + 2 * pad + tail
        panel_h = qh + (hh + round(H * 0.012) if show_head else 0) + 2 * pad
        x0, y0 = (round(v) for v in place_group(pos, W, H, max(tag_w, panel_w), tag_h + panel_h))
        _series_tag(c, canvas, x0, y0)
        py = y0 + tag_h
        c.fading_panel(canvas, (x0, py, x0 + panel_w, py + panel_h), "panneau_citation",
                       solid=(content_w + 2 * pad) / panel_w)
        c.text(canvas, exact, "texte_exact", "bold", "noir", (x0 + pad, py + pad, content_w, qh),
               max_size=sq, min_size=sq, align="left", gap=0.18)
        if show_head:
            c.text(canvas, headline, "accroche", "regular", "noir",
                   (x0 + pad, py + pad + qh + round(H * 0.012), content_w, hh),
                   max_size=sh, min_size=sh, align="left", gap=0.15)
        if tag_h:
            _place_badges(c, canvas, x0, y0, tag_w, tag_h, d)
        else:
            _place_badges(c, canvas, x0, py, panel_w, panel_h, d)

    else:  # direct
        sq, lq, qw, qh = _fit_or_min(c, exact, "bold", round(W * 0.56), H * 0.22, round(H * 0.042), round(H * 0.024),
                                     0.15)
        hw = hh = 0
        if show_head:
            sh, lh, hw, hh = _fit_or_min(c, headline, "medium", round(W * 0.56), H * 0.08, round(H * 0.026),
                                         round(H * 0.016), 0.15)
        group_w = math.ceil(max(qw, hw)) + 4
        group_h = qh + (hh + round(H * 0.015) if show_head else 0)
        x0, y0 = (round(v) for v in place_group(pos, W, H, group_w, group_h))
        align = {"gauche": "left", "droite": "right"}.get(pos.split("_")[-1], "center")
        c.text(canvas, exact, "texte_exact", "bold", "blanc", (x0, y0, group_w, qh),
               max_size=sq, min_size=sq, align=align, gap=0.15, shadow=True)
        if show_head:
            c.text(canvas, headline, "accroche", "medium", "blanc", (x0, y0 + qh + round(H * 0.015), group_w, hh),
                   max_size=sh, min_size=sh, align=align, gap=0.15, shadow=True)
        margin = W * 0.05
        tx = W - margin - tag_w if pos.endswith("droite") else margin
        ty = round(H * 0.085)
        _series_tag(c, canvas, round(tx), ty)
        if tag_h:
            _place_badges(c, canvas, round(tx), ty, tag_w, tag_h, d)
        else:
            _place_badges(c, canvas, x0, y0, group_w, group_h, d)

    c.band(canvas)
    c.footer(canvas)
    return canvas


STYLE_LABELS = {"panneau": "Panneau blanc", "direct": "Texte sur photo", "blocs": "Blocs rouge/vert"}


def layout_label(layout: str | None) -> str:
    if not layout:
        return ""
    if ":" in layout:
        style, pos = layout.split(":")
        return f"{STYLE_LABELS.get(style, style)} — {LAYOUTS.get(pos, pos).lower()}"
    return LAYOUTS.get(layout, layout)


MESSAGE_PHOTO_LAYOUTS = (
    [f"panneau:{p}" for p in ("centre_gauche", "centre_droite", "haut_gauche", "haut_droite", "bas_gauche",
                              "bas_droite")]
    + [f"direct:{p}" for p in ("bas_centre", "bas_gauche", "bas_droite", "centre_gauche", "centre_droite")]
    + [f"blocs:{p}" for p in ("haut_gauche", "centre_gauche", "centre_droite", "bas_gauche", "bas_droite")]
)


TEMPLATES = {
    "message_photo": {"label": "Lundi motivation : message sur photo (panneau, texte direct ou blocs)",
                      "render": _message_photo, "logo_position": "bas à droite",
                      "layouts": MESSAGE_PHOTO_LAYOUTS},
    "bandeau_titre_haut": {"label": "Titre en haut + photo + bandeau rouge", "render": _bandeau_titre_haut,
                           "logo_position": "bas à droite", "layouts": ["haut_centre", "haut_gauche"]},
    "bandeau_blocs": {"label": "Photo pleine + blocs rouge/vert + bandeau rouge", "render": _bandeau_blocs,
                      "logo_position": "bas à droite",
                      "layouts": ["haut_gauche", "centre_gauche", "centre_droite", "haut_centre", "bas_gauche",
                                  "haut_droite", "bas_centre", "bas_droite"]},
    "citation_centree": {"label": "Citation sur carte + bandeau rouge", "render": _citation_centree,
                         "logo_position": "bas à droite", "layouts": ["centre", "gauche", "droite"]},
}

# Rôles des couches qui forment le « groupe de message » (pour mesurer le fond qu'elles recouvrent).
MESSAGE_ROLES = ("texte_exact", "accroche", "bloc_titre", "carte_citation", "cadre_citation", "serie",
                 "bandeau_serie", "panneau", "icone")


def message_mask(comp: "Composition", size, scale: int = 4) -> np.ndarray:
    """Masque (réduit d'un facteur `scale`) des pixels couverts par le message, élément par élément."""
    W, H = size
    mask = np.zeros((H // scale, W // scale), dtype=bool)
    for l in comp.layers:
        if l.get("role", "").startswith(MESSAGE_ROLES) and "bbox" in l:
            x0, y0, x1, y1 = (int(v) // scale for v in l["bbox"])
            mask[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)] = True
    return mask


def message_bbox(comp: "Composition") -> tuple[int, int, int, int]:
    boxes = []
    for l in comp.layers:
        if l.get("role", "").startswith(MESSAGE_ROLES):
            if "bbox" in l:
                boxes.append(l["bbox"])
            elif l["kind"] == "shape" and "sample_points" in l:
                (ax, ay), (bx, by) = l["sample_points"][0], l["sample_points"][-1]
                boxes.append((ax - 3, ay - 3, bx + 3, by + 3))
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def compose(profile: BrandProfile, brief: Brief, size, template_id: str, background,
            layout: str | None = None) -> Composition:
    """`background(size) -> Image` fournit l'image de fond (photo, formes ou IA)."""
    layouts = TEMPLATES[template_id]["layouts"]
    layout = layout or layouts[0]
    if layout not in layouts:
        raise ValueError(f"Disposition « {layout} » non disponible pour le gabarit {template_id}")
    composer = Composer(profile, brief, size)
    composer.layout = layout
    image = TEMPLATES[template_id]["render"](composer, background)
    return Composition(image.convert("RGB"), template_id, composer.layers, composer.warnings, layout)
