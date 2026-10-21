"""Gabarits Bernabé (charte « Manuel d'identité visuelle » et publications réseaux sociaux).

- « bandeau » : comme les publications existantes — photo pleine, bandeau bleu droit en bas, cartouche du logo
  vertical (filet blanc, « CÔTE D'IVOIRE ») à cheval sur la photo et le bandeau, WhatsApp à gauche ;
  titre en capitales, dernière partie en rouge (panneau blanc, texte direct ou dégradé bleu).
- « affiche » : affiche verticale petit format de la charte (p. 48-49) — photo en haut, filet rouge avec
  triangle, zone de texte bleue, logo horizontal blanc et coordonnées centrés en bas.

Importé à la fin de compose.py : les outils de composition y sont déjà définis.
"""
import math

from PIL import Image, ImageDraw

from .compose import WHITE

BAND_TOP = 0.865          # haut du bandeau bleu (publications : ~0,865 H)
ZONE_TOP, ZONE_BOTTOM = 0.07, 0.80  # zone du message, au-dessus du cartouche du logo
TITLE_STYLE = "heavy"


def _upper(c) -> str | None:
    return "upper" if c.profile.uppercase_titles else None


def split_balanced(text: str) -> tuple[str, str]:
    """Coupe le texte exact en deux parties de longueurs proches, sans modifier aucun caractère :
    après une fin de phrase si possible, sinon entre deux mots."""
    words = text.split()
    if len(words) < 2:
        return text, ""
    cuts = [i for i in range(1, len(words)) if words[i - 1][-1] in ".!?:;,"] or range(1, len(words))
    best = min(cuts, key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return " ".join(words[:best]), " ".join(words[best:])


def _title_parts(c) -> list[tuple[str, str, str]]:
    """(rôle, texte, couleur « principale » ou « accent ») : l'accroche affichée passe en rouge, sinon
    la seconde moitié du texte exact (comme « … EST-ELLE / VRAIMENT ADAPTÉE … » sur les publications)."""
    exact = c.brief.exact_visual_text
    if c.brief.headline_on_visual:
        return [("texte_exact", exact, "main"), ("accroche", c.brief.headline, "accent")]
    first, second = split_balanced(exact)
    if not second:
        return [("texte_exact", exact, "main")]
    return [("texte_exact_1", first, "main"), ("texte_exact_2", second, "accent")]


def _fit_parts(c, parts, width, max_size, min_size, max_h, gap=0.1):
    """Taille commune à toutes les parties du titre (comme sur les publications)."""
    case = _upper(c)
    texts = [t.upper() if case else t for _, t, _ in parts]
    for size in range(max_size, min_size - 1, -2):
        wrapped = [c.wrap(t, c.font(TITLE_STYLE, size), width) for t in texts]
        if all(wrapped):
            heights = [c._block_height(size, len(w), gap) for w in wrapped]
            if sum(heights) + size * gap * (len(parts) - 1) <= max_h:
                widths = [max(c.font(TITLE_STYLE, size).getlength(line) for line in w) for w in wrapped]
                return size, heights, math.ceil(max(widths)) + 4
    c.warnings.append("Titre trop long pour le gabarit : composé à la taille minimale.")
    wrapped = [c.wrap(t, c.font(TITLE_STYLE, min_size), width) or [t] for t in texts]
    return min_size, [c._block_height(min_size, len(w), gap) for w in wrapped], width


def _draw_title(c, canvas, parts, x, y, w, size, heights, colors, align, shadow=False, gap=0.1):
    for (role, text, kind), h in zip(parts, heights):
        c.text(canvas, text, role, TITLE_STYLE, colors[kind], (round(x), round(y), w, h), max_size=size,
               min_size=size, align=align, gap=gap, shadow=shadow, case=_upper(c))
        y += h + size * gap
    return y


def _place(layout: str, W, H, w, h) -> tuple[float, float]:
    margin = W * 0.08
    horizontal, vertical = layout.split("_")[-1], layout.split("_")[0]
    x = {"gauche": margin, "droite": W - margin - w}.get(horizontal, (W - w) / 2)
    top, bottom = H * ZONE_TOP, H * ZONE_BOTTOM
    y = {"haut": top, "bas": bottom - h}.get(vertical, (top + bottom - h) / 2)
    return x, y


def _series_block(c, canvas, x, y, color, draw=True) -> tuple[int, int]:
    """Étiquette de série : un bloc plein (rouge ou bleu), texte blanc en capitales."""
    tag = c.profile.series_tag(c.brief.series) if c.brief.show_series_tag else None
    if not tag:
        return 0, 0
    W, H = c.W, c.H
    size = round(H * 0.03)
    pad_x, pad_y = round(W * 0.03), round(size * 0.45)
    w = math.ceil(c.font("regular", size).getlength(tag[0])) + 2 * pad_x + 4
    h = round(size * 1.25) + 2 * pad_y
    if draw:
        c.rect(canvas, (x, y, x + w, y + h), color, "bandeau_serie")
        c.text(canvas, tag[0], "serie", "regular", "blanc", (x + pad_x, y, w - 2 * pad_x, h), max_size=size,
               min_size=size)
    return w, h


def _blue_gradient(c, canvas, height_ratio=0.5, strength=0.82):
    """Dégradé bleu en haut de la photo (publication « Bon week-end »), de l'opacité `strength` à 0."""
    W, H = c.W, c.H
    h = round(H * height_ratio)
    ramp = Image.linear_gradient("L").resize((W, h)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    mask = ramp.point(lambda v: round(v * strength))
    canvas.paste(Image.new("RGB", (W, h), c.color("bleu")), (0, 0), mask)
    c.layers.append({"kind": "overlay", "role": "degrade", "color_name": "bleu", "box": [0, 0, W, h]})


def whatsapp_icon(c, canvas, center, d):
    """Pastille blanche avec bulle et combiné stylisés en bleu (sur-échantillonnée puis réduite)."""
    s = 4
    D = round(d) * s
    tile = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    blue = c.color("bleu")
    u = D / 100
    draw.ellipse((0, 0, D - 1, D - 1), fill=WHITE)
    draw.ellipse((17 * u, 15 * u, 83 * u, 81 * u), outline=blue, width=round(7 * u))  # bulle
    draw.polygon([(20 * u, 66 * u), (14 * u, 86 * u), (34 * u, 79 * u)], fill=blue)     # queue de la bulle
    draw.arc((33 * u, 31 * u, 67 * u, 65 * u), 100, 260, fill=blue, width=round(9 * u))  # combiné
    draw.rounded_rectangle((33 * u, 28 * u, 43 * u, 40 * u), radius=3 * u, fill=blue)
    draw.rounded_rectangle((52 * u, 57 * u, 64 * u, 67 * u), radius=3 * u, fill=blue)
    tile = tile.resize((round(d), round(d)), Image.Resampling.LANCZOS)
    x, y = round(center[0] - d / 2), round(center[1] - d / 2)
    canvas.paste(tile, (x, y), tile)
    c.layers.append({"kind": "shape", "role": "picto_whatsapp", "color_name": "blanc", "color": WHITE,
                     "bbox": (x, y, x + round(d), y + round(d)), "sample_points": []})


def _contact_line(c, canvas, x, cy, size, align="left", with_site=False):
    """Icône WhatsApp + numéro (et site), sur fond bleu."""
    contact = c.profile.contact
    if not contact or not contact.whatsapp:
        return
    d = round(size * 1.45)
    text = contact.whatsapp + (f"   {contact.website}" if with_site and contact.website else "")
    tw = math.ceil(c.font("medium", size).getlength(text)) + 4
    total = d + round(size * 0.5) + tw
    x0 = x - total / 2 if align == "center" else x
    whatsapp_icon(c, canvas, (x0 + d / 2, cy), d)
    c.text(canvas, text, "mention_locale", "medium", "blanc",
           (round(x0 + d + size * 0.5), round(cy - size * 0.75), tw, round(size * 1.5)), max_size=size,
           min_size=size, align="left")


def _band_footer(c, canvas):
    """Bandeau bleu droit, cartouche du logo à droite, « Depuis 1953 », WhatsApp à gauche."""
    W, H = c.W, c.H
    top = round(H * BAND_TOP)
    c.rect(canvas, (0, top, W, H), "bleu", "bandeau")
    box = c.logo(canvas, "cartouche_blanc", round(W * 0.11), round(W * 0.905), round(H * 0.815))
    lm = c.profile.local_market
    if lm and lm.tagline:
        size = round(H * 0.017)
        tw = math.ceil(c.font("regular", size).getlength(lm.tagline)) + 4
        cx, ty = (box[0] + box[2]) / 2, box[3] + round(H * 0.006)
        c.text(canvas, lm.tagline, "mention_logo_locale", "regular", "blanc",
               (round(cx - tw / 2), ty, tw, round(size * 1.3)), max_size=size, min_size=size)
        line_w, line_h, gap = round(W * 0.018), max(2, round(H * 0.0015)), round(W * 0.008)
        ly = round(ty + size * 0.7)
        c.rect(canvas, (cx - tw / 2 - gap - line_w, ly, cx - tw / 2 - gap, ly + line_h), "blanc", "filet_mention")
        c.rect(canvas, (cx + tw / 2 + gap, ly, cx + tw / 2 + gap + line_w, ly + line_h), "blanc", "filet_mention")
        if lm.status != "confirmé":
            c.warnings.append(f"Mention « {lm.tagline} » sous le logo : relevée sur les publications, "
                              "absente de la charte.")
    _contact_line(c, canvas, round(W * 0.09), round((top + H) / 2 + H * 0.003), round(H * 0.024))


def _bandeau(c, background) -> Image.Image:
    """Publications Bernabé : photo pleine, titre (panneau blanc, texte direct ou dégradé), bandeau bleu."""
    style, pos = c.layout.split(":")
    W, H = c.W, c.H
    canvas = background((W, H)).copy()
    c.layers.append({"kind": "background", "role": "fond", "box": [0, 0, W, H]})
    parts = _title_parts(c)
    align = {"gauche": "left", "droite": "right"}.get(pos.split("_")[-1], "center")

    if style == "panneau":  # titre bleu puis rouge sur panneau blanc (publication « boîte à outils »)
        pad_x, pad_y = round(W * 0.035), round(H * 0.02)
        size, heights, tw = _fit_parts(c, parts, round(W * 0.8), round(H * 0.05), round(H * 0.026), H * 0.2)
        panel_w, panel_h = tw + 2 * pad_x, sum(heights) + size * 0.1 * (len(parts) - 1) + 2 * pad_y
        x0, y0 = _place(pos, W, H, panel_w, panel_h)
        c.rect(canvas, (x0, y0, x0 + panel_w, y0 + panel_h), "blanc", "panneau_titre")
        _draw_title(c, canvas, parts, x0 + pad_x, y0 + pad_y, tw, size, heights,
                    {"main": "bleu", "accent": "rouge"}, align)
    else:  # direct ou dégradé : titre blanc puis rouge, ombré, étiquette de série au-dessus
        if style == "degrade":
            _blue_gradient(c, canvas)
        size, heights, tw = _fit_parts(c, parts, round(W * (0.86 if align == "center" else 0.8)), round(H * 0.058),
                                       round(H * 0.028), H * 0.26)
        tag_w, tag_h = _series_block(c, canvas, 0, 0, "rouge", draw=False)
        gap = round(H * 0.035) if tag_h else 0
        group_w, group_h = max(tw, tag_w), tag_h + gap + sum(heights) + size * 0.1 * (len(parts) - 1)
        x0, y0 = _place(pos, W, H, group_w, group_h)
        if tag_h:
            tx = {"left": x0, "right": x0 + group_w - tag_w}.get(align, (W - tag_w) / 2)
            _series_block(c, canvas, round(tx), round(y0), "rouge" if pos.startswith("haut") else "bleu")
        tx = {"left": x0, "right": x0 + group_w - tw}.get(align, (W - tw) / 2)
        _draw_title(c, canvas, parts, tx, y0 + tag_h + gap, tw, size, heights, {"main": "blanc", "accent": "rouge"},
                    align, shadow=True)
    _band_footer(c, canvas)
    return canvas


def _affiche(c, background) -> Image.Image:
    """Affiche verticale petit format (charte p. 48-49), adaptée au format du brief."""
    W, H = c.W, c.H
    photo_h = round(H * 0.58)
    canvas = Image.new("RGB", (W, H), c.color("bleu"))
    canvas.paste(background((W, photo_h)), (0, 0))
    c.layers.append({"kind": "background", "role": "fond", "box": [0, 0, W, photo_h]})
    c.layers.append({"kind": "shape", "role": "zone_texte", "color_name": "bleu", "color": c.color("bleu"),
                     "bbox": (0, photo_h, W, H), "sample_points": [(6, H - 6), (W - 6, photo_h + 40)]})
    # Filet rouge et triangle pointant vers la zone de texte (signe de la charte)
    line_h = max(4, round(H * 0.006))
    c.rect(canvas, (0, photo_h - line_h // 2, W, photo_h + line_h // 2), "rouge", "filet_rouge")
    s, tri_w, tri_h = 4, W * 0.045, W * 0.024
    mask = Image.new("L", (W * s, H * s), 0)
    cx, top = W / 2, photo_h + line_h // 2 - 1
    ImageDraw.Draw(mask).polygon([((cx - tri_w / 2) * s, top * s), ((cx + tri_w / 2) * s, top * s),
                                  (cx * s, (top + tri_h) * s)], fill=255)
    canvas.paste(Image.new("RGB", canvas.size, c.color("rouge")), (0, 0), mask.resize((W, H), Image.Resampling.LANCZOS))
    c.layers.append({"kind": "shape", "role": "triangle_filet", "color_name": "rouge", "color": c.color("rouge"),
                     "bbox": (round(cx - tri_w / 2), top, round(cx + tri_w / 2), round(top + tri_h)),
                     "sample_points": [(round(cx), round(top + tri_h * 0.3))]})

    # Titre blanc (texte exact) ; accroche en bleu sur un bandeau blanc, comme « S3 HIRO NITRILLE »
    exact = c.brief.exact_visual_text
    size, heights, tw = _fit_parts(c, [("texte_exact", exact, "main")], round(W * 0.84), round(H * 0.062),
                                   round(H * 0.03), H * 0.15)
    y = photo_h + round(H * 0.055)
    _draw_title(c, canvas, [("texte_exact", exact, "main")], (W - tw) / 2, y, tw, size, heights,
                {"main": "blanc"}, "center")
    y += heights[0] + round(H * 0.02)
    if c.brief.headline_on_visual:
        hs = round(H * 0.03)
        head = c.brief.headline.upper() if _upper(c) else c.brief.headline
        hw = min(round(W * 0.84), math.ceil(c.font("heavy", hs).getlength(head)) + round(W * 0.08))
        hh = round(hs * 1.7)
        c.rect(canvas, ((W - hw) / 2, y, (W + hw) / 2, y + hh), "blanc", "panneau_accroche")
        c.text(canvas, c.brief.headline, "accroche", "heavy", "bleu", (round((W - hw) / 2 + W * 0.02), round(y),
               hw - round(W * 0.04), hh), max_size=hs, min_size=round(H * 0.018), case=_upper(c))
    logo_w = round(W * 0.4)
    c.logo(canvas, "horizontal_blanc", logo_w, round((W + logo_w) / 2), round(H * 0.855))
    _contact_line(c, canvas, W / 2, round(H * 0.955), round(H * 0.021), align="center", with_site=True)
    return canvas


BANDEAU_LAYOUTS = ["panneau:haut_centre", "panneau:bas_centre", "degrade:haut_centre", "direct:bas_gauche",
                   "direct:haut_gauche", "direct:centre_gauche", "direct:bas_centre"]

BERNABE_TEMPLATES = {
    "bernabe_bandeau": {"label": "Publication : photo + titre + bandeau bleu (comme les posts publiés)",
                        "render": _bandeau, "logo_position": "bas à droite", "layouts": BANDEAU_LAYOUTS},
    "bernabe_affiche": {"label": "Affiche de la charte : photo, filet rouge, zone de texte bleue",
                        "render": _affiche, "logo_position": "bas au centre", "logo_fixed": True,
                        "layouts": ["centre"]},
}
