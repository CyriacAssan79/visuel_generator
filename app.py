"""Interface studio KÔMIAN — lancer avec : streamlit run app.py

L'interface ne montre que ce qui sert à créer et valider un visuel. Les détails techniques (modèles, moteurs,
identifiants, base de données) restent enregistrés pour la traçabilité, mais ne sont pas affichés.
Le studio porte la charte KÔMIAN (komian/ui.py) ; les visuels créés suivent la charte du client sélectionné.
"""
import json
from datetime import datetime
from pathlib import Path

import streamlit as st
from PIL import Image

from komian import db, online, ui
from komian.backgrounds import (SOURCES, GeometricSource, SourceUnavailable, ai_configured, model_spec,
                                resolve_device, suggest_prompt)
from komian.brands import asset_path, list_brands, load_profile
from komian.compose import TEMPLATES, layout_label
from komian.config import FORMATS, from_stored, to_stored
from komian.models import Brief
from komian.storage import ImportRejected, import_image
from komian.workflow import (ApprovalRefused, DeleteRefused, ExportBlocked, PlanBlocked, QualityNotApproved,
                             cancel_quality_approval, decide, delete_render, export_approved, generate,
                             generate_variants, linked_versions, needs_quality_pass, prepare_plan,
                             preview, CorrectionRefused, cell_label, correct_render, correction_state,
                             faces_in_scene)

# --- Libellés affichés -----------------------------------------------------------
OBJECTIVES = ["motiver", "promouvoir", "informer", "recruter", "sensibiliser", "autre"]
FORMAT_LABELS = {"post_carre": "Post carré", "post_portrait": "Post portrait", "story": "Story"}
SOURCE_LABELS = {"photo": "Ma photo", "geometrique": "Formes aux couleurs de la marque",
                 "ia_en_ligne": "IA en ligne", "ia_locale": "IA locale"}
SOURCE_HELP = {"photo": "Importez une photo libre de droits.",
               "geometrique": "Un fond graphique simple, en aplats de couleurs de la charte.",
               "ia_en_ligne": "Décrivez la scène : l'IA en ligne crée la photo en quelques secondes, le texte et "
                              "le logo sont ajoutés ensuite. Une création utilise un crédit du jour.",
               "ia_locale": "Décrivez la scène : l'IA de ce poste crée la photo (environ 1 min 30), le texte et le "
                            "logo sont ajoutés ensuite."}
GEOMETRIC_VARIANTS = {"cercles": "Cercles", "diagonales": "Diagonales", "blocs": "Blocs"}
CHECK_LABELS = {
    "Lisibilité (OCR)": "Relecture automatique du texte",
    "Contraste des textes": "Contraste du texte",
    "Couleurs des éléments ajoutés": "Couleurs de la charte",
    "Fond en aplats de marque": "Fond aux couleurs de la marque",
    "Image générée par IA": "Image créée par l'IA",
    "Points à confirmer pour ce brief": "Points d'attention",
    "Charte : points non tranchés": "Charte : points à confirmer",
}
LOGO_POSITIONS = ["bas à droite", "bas à gauche", "haut à droite", "haut à gauche"]
STEPS = ["Client", "Brief", "Création"]

st.set_page_config(page_title="KÔMIAN Studio", page_icon=str(ui.FAVICON), layout="wide")
ui.inject_theme()
st.logo(str(ui.LOGO_WHITE), icon_image=str(ui.SYMBOL_WHITE), size="medium")
st.session_state.setdefault("brief_id", None)
st.session_state.setdefault("render_id", None)
st.session_state.setdefault("last_batch", [])
st.session_state.setdefault("step", 0)
if st.session_state.get("flash"):  # message à afficher après un rechargement de la page
    st.toast(st.session_state.pop("flash"))


def fmt_date(value: str) -> str:
    """Date lisible, à l'heure locale (« 18/10 à 14:32 »)."""
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d/%m à %H:%M")
    except (TypeError, ValueError):
        return value or ""


def format_label(format_id: str) -> str:
    w, h = FORMATS.get(format_id, (0, 0))
    return f"{FORMAT_LABELS.get(format_id, format_id)} ({w} × {h})"


def brief_text(row) -> str:
    """Texte du brief d'un visuel ; vide si la donnée manque (une ligne SQLite lève IndexError, pas KeyError)."""
    if "brief_data" not in row.keys():
        return ""
    try:
        return json.loads(row["brief_data"])["exact_visual_text"]
    except (KeyError, TypeError, ValueError):
        return ""


def short(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def show_image(container, stored_path) -> bool:
    """Affiche un visuel ; s'il a été supprimé du dossier, le signale sans faire planter la page."""
    path = from_stored(stored_path)
    if path and path.exists():
        container.image(str(path), width="stretch")
        return True
    container.warning("Image introuvable : elle a été supprimée du dossier.")
    return False


def superseded_ids(rows) -> set[str]:
    """Aperçus remplacés par une version qualité encore valable (ils ne sont plus proposés à la validation)."""
    ids = set()
    for r in rows:
        params = json.loads(r["params"])
        for source in (params.get("quality_of"), params.get("correction_of")):  # version qualité ou corrigée
            if source and r["status"] != "rejected":
                ids.add(source)
    return ids


def reviewable(rows) -> list:
    """Visuels à examiner : un aperçu remplacé par sa version finale, ou une version finale annulée, n'y est plus."""
    hidden = superseded_ids(rows) | {r["id"] for r in rows if r["status"] == "rejected"
                                     and json.loads(r["params"]).get("quality_of")}
    return [r for r in rows if r["id"] not in hidden]


# --- Client actif : choisi depuis sa fiche (page Clients), le premier par défaut ------
if st.session_state.get("client") not in list_brands():
    st.session_state.client = list_brands()[0]
brand_id = st.session_state.client
profile = load_profile(brand_id)

online_limit = int(online.config()["daily_limit"])
with db.connect() as conn:
    online_left = online.remaining(conn) if online.configured() else 0
    n_pending = sum(r["status"] == "pending" for r in reviewable(
        [r for r in db.list_renders(conn, brand_id) if r["status"] != "error"]))


# --- Créer un visuel : 1. Brief ----------------------------------------------------
def brief_form():
    with db.connect() as conn:
        briefs = db.list_briefs(conn, brand_id)
    options = {"Nouveau brief": None}
    for b in briefs:
        data = json.loads(b["data"])
        version = f" · version {b['version']}" if b["version"] > 1 else ""
        options[f"« {short(data['exact_visual_text'])} »{version}"] = b["id"]
    ids = list(options.values())
    default = ids.index(st.session_state.brief_id) if st.session_state.brief_id in ids else 0
    choice = st.selectbox("Brief", list(options), index=default)
    current_id = options[choice]
    current = None
    if current_id:
        with db.connect() as conn:
            current_row, current = db.get_brief(conn, current_id)
        st.session_state.brief_id = current_id

    with st.form("brief"):
        st.subheader("Le message")
        exact = st.text_input("Texte du visuel", current.exact_visual_text if current else "",
                              help="Reproduit exactement, caractère pour caractère (accents, majuscules, ponctuation).")
        headline = st.text_input("Accroche", current.headline if current else "")
        head_on = st.checkbox("Afficher l'accroche sur le visuel (sinon, elle sert de texte à la publication)",
                              current.headline_on_visual if current else False)

        st.subheader("Le contexte")
        c1, c2, c3 = st.columns(3)
        series = c1.text_input("Série", current.series if current else next(iter(profile.series_tags), ""),
                               help="Une série connue de la charte affiche son étiquette (ex. "
                                    + " ; ".join(f"« {s} »" for s in profile.series_tags) + ")."
                               if profile.series_tags else None)
        objective = c2.selectbox("Objectif", OBJECTIVES, OBJECTIVES.index(current.objective) if current else 0,
                                 format_func=str.capitalize)
        format_id = c3.selectbox("Format", list(FORMATS),
                                 list(FORMATS).index(current.format_id) if current else 0, format_func=format_label)
        c1, c2 = st.columns(2)
        channel = c1.text_input("Réseaux", current.channel if current else "Instagram / Facebook")
        audience = c2.text_input("Public visé (facultatif)", (current.target_audience or "") if current else "")

        st.subheader("La mise en forme")
        direction = st.text_area("Direction artistique", current.visual_direction if current else "",
                                 placeholder="Ex. : femme souriante qui peint un mur, ambiance chaleureuse et lumineuse")
        c1, c2, c3 = st.columns(3)
        logo_pos = c1.selectbox("Position du logo", LOGO_POSITIONS,
                                LOGO_POSITIONS.index(current.logo_position) if current else 0,
                                format_func=str.capitalize)
        icons = c2.multiselect("Icônes", ["calendrier", "coche"], current.icons if current else [],
                               format_func=str.capitalize)
        show_tag = c3.checkbox("Afficher l'étiquette de série (ex. « Lundi / MOTIVATION »)",
                               current.show_series_tag if current else True)
        constraints = st.text_area("À éviter (un élément par ligne)",
                                   "\n".join(current.constraints) if current else "",
                                   placeholder="Ex. : pas de cigarette\nne pas masquer le visage")

        st.divider()
        c1, c2 = st.columns(2)
        author = c1.text_input("Votre nom")
        note = c2.text_input("Qu'est-ce qui change ?", disabled=current is None,
                             help="Obligatoire pour modifier un brief existant : une nouvelle version est créée.")
        submitted = st.form_submit_button("Enregistrer et continuer" if current else "Créer le brief",
                                          type="primary", icon=":material/arrow_forward:")

    if submitted:
        try:
            brief = Brief(brand_id=brand_id, series=series or None, objective=objective, channel=channel,
                          format_id=format_id, target_audience=audience or None, headline=headline,
                          exact_visual_text=exact, visual_direction=direction, logo_position=logo_pos, icons=icons,
                          show_series_tag=show_tag, headline_on_visual=head_on,
                          constraints=[c for c in constraints.splitlines() if c.strip()])
            with db.connect() as conn:
                if current:
                    new_id = db.revise_brief(conn, current_row["brief_key"], brief, note, author)
                else:
                    new_id = db.create_brief(conn, brief, author or None)
            st.session_state.brief_id = new_id
            st.session_state.step = 2
            st.session_state.flash = "Brief enregistré. Créez maintenant le visuel."
            st.rerun()
        except Exception as exc:
            st.error(f"Le brief n'a pas pu être enregistré : {exc}")

    if current:
        if st.button("Continuer sans modifier le brief", icon=":material/arrow_forward:"):
            st.session_state.step = 2
            st.rerun()
        with db.connect() as conn:
            versions = db.brief_versions(conn, current_row["brief_key"])
        if len(versions) > 1:
            with st.expander(f"Historique des modifications ({len(versions)} versions)", icon=":material/history:"):
                for v in versions:
                    d = json.loads(v["data"])
                    st.markdown(f"**Version {v['version']}** · {fmt_date(v['created_at'])} · "
                                f"{v['author'] or 'auteur inconnu'}  \n"
                                f"{v['change_note'] or 'Création'} — « {d['exact_visual_text']} »")


# --- Créer un visuel : 2. Création -------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=200)
def preview_png(brand: str, brief_json: str, template_id: str, layout: str, scale: float) -> bytes:
    """Vignette de mise en page sur fond neutre (mise en cache : instantanée au deuxième affichage)."""
    import io
    comp = preview(load_profile(brand), Brief.model_validate_json(brief_json), template_id, layout, scale)
    buf = io.BytesIO()
    comp.image.save(buf, "PNG")
    return buf.getvalue()


def layout_preview(brief, template_id: str, layouts: list, choice: str) -> None:
    """Aperçu de la mise en page avant génération : la disposition choisie, ou toutes en vignettes."""
    with st.container(key="card_preview"):
        ui.label("Aperçu de la mise en page · avant génération")
        data = brief.model_dump_json()
        if choice != "auto" or len(layouts) == 1:
            st.image(preview_png(brand_id, data, template_id, layouts[0] if choice == "auto" else choice, 0.45),
                     width="stretch")
            st.caption("Fond gris provisoire : l'image créée prendra sa place.")
            return
        st.caption("Dispositions possibles : le studio retiendra les 3 qui dégagent le mieux le sujet de l'image. "
                   "Choisissez-en une à gauche pour la fixer.")
        per_row = 4
        for start in range(0, len(layouts), per_row):
            cols = st.columns(per_row)
            for col, lay in zip(cols, layouts[start:start + per_row]):
                col.image(preview_png(brand_id, data, template_id, lay, 0.22), width="stretch")
                col.caption(layout_label(lay))


def step_creation():
    if not st.session_state.brief_id:
        st.info("Commencez par créer ou choisir un brief à l'étape 2.")
        return
    with db.connect() as conn:
        row, brief = db.get_brief(conn, st.session_state.brief_id)

    left, right = st.columns([1, 1], gap="large")
    with left.container(key="card_create"):
        ui.label("Brief")
        st.markdown(f"#### « {brief.exact_visual_text} »")
        st.caption(f"{format_label(brief.format_id)} · {brief.series or 'hors série'}")

        st.subheader("Mise en page")
        template_id = st.selectbox("Modèle de mise en page", [t for t in profile.templates if t in TEMPLATES],
                                   format_func=lambda t: TEMPLATES[t]["label"], label_visibility="collapsed")

        layouts = TEMPLATES[template_id]["layouts"]
        layout_choice = "auto"
        if len(layouts) > 1:
            layout_choice = st.selectbox(
                "Disposition", ["auto"] + list(layouts), key=f"layout_{template_id}",
                format_func=lambda l: "Le studio choisit (3 propositions)" if l == "auto" else layout_label(l),
                help="L'aperçu à droite montre la mise en page avant de créer l'image. Avec une disposition "
                     "choisie, l'IA laisse libre la zone du texte.")

        st.subheader("Image de fond")
        source_ids = list(SOURCES)
        default_source = ("ia_en_ligne" if online_left > 0 else "ia_locale" if ai_configured() else "geometrique")
        source_id = st.radio("Image de fond", source_ids, horizontal=True, label_visibility="collapsed",
                             format_func=lambda s: SOURCE_LABELS.get(s, s), index=source_ids.index(default_source))
        st.caption(SOURCE_HELP.get(source_id, ""))

        plan = prepare_plan(profile, brief, template_id, source_id)
        for b in plan.blocking:
            st.error(b)
        for w in plan.warnings:
            st.warning(w)

        params: dict = {}
        upload = None
        wait = ""
        if source_id == "photo":
            upload = st.file_uploader("Photo (JPG, PNG ou WEBP)", type=["jpg", "jpeg", "png", "webp"])
            c1, c2 = st.columns(2)
            params["saturation"] = c1.slider("Intensité des couleurs", 0.0, 1.0, 1.0, 0.05,
                                             help="0 = noir et blanc")
            params["focus_y"] = c2.slider("Cadrage vertical", 0.0, 1.0, 0.4, 0.05,
                                          help="0 = haut de la photo, 1 = bas")
            rights = st.text_input("Droits d'utilisation vérifiés par",
                                   help="Laissez vide si personne ne les a vérifiés : ce sera signalé au contrôle.")
            if rights.strip():
                params["rights_confirmed_by"] = rights.strip()
        elif source_id == "geometrique":
            variant = st.radio("Style", ["auto"] + list(GeometricSource.variants), horizontal=True,
                               format_func=lambda v: "Surprise" if v == "auto" else GEOMETRIC_VARIANTS.get(v, v),
                               help="« Surprise » choisit un style différent des derniers visuels de la série.")
            if variant != "auto":
                params["variant"] = variant
        else:
            if source_id == "ia_en_ligne":
                if not online.configured():
                    st.warning("La génération en ligne n'est pas configurée (identifiants Cloudflare absents).")
                elif online_left <= 0:
                    st.warning(f"Quota du jour atteint ({online_limit} images). Il se renouvelle à minuit : "
                               "utilisez l'IA locale, une photo ou les formes de la marque.")
                else:
                    st.caption(f"1 crédit pour cette création · **{online_left} / {online_limit}** restants "
                               "aujourd'hui. L'image validée est la version finale.")
                    wait = " (quelques secondes)"
            elif not ai_configured():
                st.warning("La création d'image par IA n'est pas disponible sur ce poste.")
            else:
                st.caption("L'IA crée la scène, vérifie le visage et le geste demandé, puis corrige si besoin. "
                           "La version finale, en haute qualité, est produite au moment de l'approbation.")
                wait = " (jusqu'à 1 min 30 ; la première création après un démarrage prend 2 à 3 minutes de plus)"
                device = model_spec("fast")[1].get("device", "CPU")
                if resolve_device(device) != device.upper():
                    st.warning("Ce poste fonctionne en mode ralenti : la création prendra environ 10 fois plus "
                               "de temps que prévu.")
            params["prompt"] = st.text_area(
                "Décrivez la scène", suggest_prompt(brief.visual_direction, profile.default_scene), key=f"prompt_{row['id']}", height=110,
                help="En français ou en anglais. Indiquez qui (âge, tenue), quoi (une action simple), où, le cadrage "
                     "et la lumière. N'écrivez ni texte ni logo : ils sont ajoutés ensuite.")
            if source_id == "ia_en_ligne":
                st.caption("Le studio précise automatiquement le contexte local, la zone à laisser libre pour le "
                           "texte et le style photo.")
            with st.expander("Conseils pour une belle image", icon=":material/lightbulb:"):
                st.markdown(
                    "- **Une personne en plan taille** qui regarde l'objectif donne les meilleurs résultats.\n"
                    "- **Précisez la tenue** (« en t-shirt blanc », « en chemise rouge »).\n"
                    "- **Évitez les gestes précis avec un outil** et les petits visages en plan large : "
                    "préférez alors une vraie photo.\n"
                    "- **Nommez l'outil tenu** (perceuse, arrosoir, carton, pinceau…) : l'IA vérifie qu'il est bien "
                    "dans la main et l'ajoute si besoin. Le rouleau de peinture reste hors de sa portée.\n"
                    "- Le résultat ne convient pas ? **Relancez** : chaque création propose une nouvelle image.")
            params["saturation"] = st.slider("Intensité des couleurs", 0.0, 1.0, 1.0, 0.05, help="0 = noir et blanc")

        n_layouts = len(layouts)
        variants = layout_choice == "auto" and n_layouts > 1
        blocked = bool(plan.blocking) or (source_id == "ia_en_ligne" and (online_left <= 0 or not online.configured()))
        create = st.button("Créer le visuel" + (" (1 crédit)" if source_id == "ia_en_ligne" else ""),
                           type="primary", disabled=blocked, icon=":material/auto_awesome:", width="stretch")

    with right:
        if create:
            try:
                if source_id == "photo":
                    if upload is None:
                        raise ImportRejected("Importez d'abord une photo.")
                    params["photo_path"] = to_stored(import_image(upload.getvalue(), upload.name, brand_id))
                with st.spinner(f"Création du visuel en cours{wait}…"), db.connect() as conn:
                    if variants:
                        _, ids = generate_variants(conn, st.session_state.brief_id, template_id, source_id, params)
                    else:
                        ids = [generate(conn, st.session_state.brief_id, template_id, source_id, params,
                                        None if layout_choice == "auto" else layout_choice)]
                st.session_state.render_id = ids[0]
                st.session_state.last_batch = ids
                st.rerun()  # compteurs de la barre latérale (crédits, visuels à valider) à jour
            except ImportRejected as exc:
                st.error(f"Photo refusée : {exc}")
            except PlanBlocked as exc:
                st.error(str(exc))
            except SourceUnavailable as exc:
                if source_id == "ia_en_ligne":
                    st.error(str(exc))
                else:
                    st.error("La création d'image par IA n'est pas disponible sur ce poste pour le moment. "
                             "Choisissez une autre image de fond, ou contactez l'administrateur.")
                    with st.expander("Détails pour l'administrateur"):
                        st.code(str(exc), language=None)
            except Exception as exc:
                st.error("La création a échoué. Réessayez ; si le problème persiste, contactez l'administrateur.")
                with st.expander("Détails pour l'administrateur"):
                    st.code(f"{type(exc).__name__} : {exc}", language=None)

        layout_preview(brief, template_id, layouts, layout_choice)
        made = []
        if st.session_state.last_batch:
            with db.connect() as conn:
                made = [db.get_render(conn, i) for i in st.session_state.last_batch]
            made = [r for r in made if r["status"] != "error"]
        with st.container(key="stage_create"):
            if made:
                cols = st.columns(len(made))
                for col, r in zip(cols, made):
                    show_image(col, r["file_path"])
                    col.caption(layout_label(r["layout"]))
            else:
                ui.label("Visuel")
                st.caption("Le visuel créé apparaîtra ici, aux couleurs de la charte du client.")
        if made:
            st.success("Visuel prêt ! Choisissez et validez-le à l'étape de validation.")
            if st.button("Passer à la validation", type="primary", icon=":material/arrow_forward:"):
                st.switch_page(PAGES["validation"])


def select_client(b: str) -> None:
    """Change le client actif ; le brief et les créations en cours appartenaient à l'ancien client."""
    if b != st.session_state.client:
        st.session_state.client = b
        st.session_state.brief_id = None
        st.session_state.render_id = None
        st.session_state.last_batch = []


# --- Créer un visuel : 1. Client -----------------------------------------------------
def step_client():
    with st.container(key="card_pick"):
        c1, c2 = st.columns([2, 1], vertical_alignment="center")
        c1.subheader("Client")
        query = c2.text_input("Rechercher un client", placeholder="Rechercher un client",
                              label_visibility="collapsed")
        brands = [b for b in list_brands() if query.casefold() in load_profile(b).brand_name.casefold()]
        if not brands:
            st.caption("Aucun client ne correspond à cette recherche.")
        styles = []
        per_row = 4
        for start in range(0, len(brands), per_row):
            cols = st.columns(per_row)
            for col, b in zip(cols, brands[start:start + per_row]):
                p = load_profile(b)
                logo = next((asset_path(p, lg.file) for lg in p.logos if not lg.on_dark_background), None)
                state = "on" if b == brand_id else "off"
                if logo and logo.is_file():
                    styles.append(f".st-key-pick_{state}_{b} button::before {{ background-image: url({ui.data_uri(logo)}); }}")
                if col.button(p.brand_name, key=f"pick_{state}_{b}", width="stretch"):
                    select_client(b)
                    st.rerun()
        st.html(f"<style>{''.join(styles)}</style>")
    st.caption("Les visuels créés suivent automatiquement la charte du client choisi : logo, couleurs, typographie.")
    _, c2 = st.columns([3, 1])
    if c2.button("Continuer", type="primary", icon=":material/arrow_forward:", width="stretch"):
        st.session_state.step = 1
        st.rerun()


def charte_panel(p) -> None:
    """Rappel de la charte appliquée automatiquement, à côté du brief (comme dans KÔMIAN Studio)."""
    logo = next((asset_path(p, lg.file) for lg in p.logos if not lg.on_dark_background), None)
    colors = [c.hex for c in p.primary_colors.values()]
    fonts = p.font_name
    logo_html = (f"<div style='margin-top:8px;background:var(--g100);padding:8px 10px;display:inline-block'>"
                 f"<img src='{ui.data_uri(logo)}' alt='Logo' style='height:22px'></div>"
                 if logo and logo.is_file() else "")
    dots = "".join(f"<span style='background:{c}' title='{c}'></span>" for c in colors)
    with st.container(key="card_charte"):
        html = ui.card_head("Charte appliquée automatiquement", p.brand_name)
        html += ("<div class='k-setting'><div class='txt'><b>Logo officiel</b><span>Posé par la plateforme, "
                 f"jamais redessiné par l'IA.</span>{logo_html}</div></div>")
        html += ("<div class='k-setting'><div class='txt'><b>Couleurs de la charte</b>"
                 f"<div class='k-sw-sm' style='margin-top:6px'>{dots}</div></div></div>")
        html += ui.setting("Typographie", fonts)
        html += ui.setting("Orthographe officielle", p.official_spelling)
        if p.local_market:
            html += ui.setting("Signature locale", " · ".join(
                x for x in [p.local_market.tagline, p.local_market.handle, p.local_market.address] if x))
        if p.contact:
            html += ui.setting("Coordonnées", " · ".join(
                x for x in [p.contact.whatsapp and f"WhatsApp {p.contact.whatsapp}", p.contact.phone,
                            p.contact.website] if x))
        st.markdown(html, unsafe_allow_html=True)


def step_brief():
    main, side = st.columns([1.7, 1], gap="medium")
    with side:
        charte_panel(profile)
        if st.button("Changer de client", icon=":material/arrow_back:", width="stretch"):
            st.session_state.step = 0
            st.rerun()
    with main:
        brief_form()


def page_create():
    ui.page_head("Production", "Créer un visuel",
                 "Choisissez le client, remplissez le brief : la plateforme applique la charte du client "
                 "et pose le logo et la typographie.")
    clicked = ui.stepper(STEPS, st.session_state.step)
    if clicked is not None and clicked != st.session_state.step:
        if clicked == 2 and not st.session_state.brief_id:
            st.toast("Enregistrez d'abord le brief.")
        else:
            st.session_state.step = clicked
            st.rerun()
    [step_client, step_brief, step_creation][st.session_state.step]()


# --- Validation ------------------------------------------------------------------
def grid_overlay(scene_path) -> Image.Image | None:
    """Scène de l'image (sans texte ni logo) avec la grille 3 × 3 numérotée, pour choisir la zone à corriger."""
    from PIL import ImageDraw
    path = from_stored(scene_path)
    if not path or not path.exists():
        return None
    img = Image.open(path).convert("RGB")
    img.thumbnail((720, 720))
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for i in (1, 2):
        draw.line([(w * i / 3, 0), (w * i / 3, h)], fill="white", width=3)
        draw.line([(0, h * i / 3), (w, h * i / 3)], fill="white", width=3)
    for r in range(3):
        for c in range(3):
            x, y = c * w / 3 + 10, r * h / 3 + 8
            draw.rectangle((x - 4, y - 2, x + 26, y + 26), fill=(0, 0, 0))
            draw.text((x + 4, y + 2), str(r * 3 + c + 1), fill="white", font_size=22)
    return img


def correction_panel(render, params: dict, checks) -> None:
    """Correction ciblée : décrire le défaut, cocher la zone, 1 crédit, une seule fois (version finale)."""
    if render["background_source"] != "ia_en_ligne":
        return
    with db.connect() as conn:
        refusal = correction_state(conn, render)
    if refusal:
        if not params.get("correction_of") and render["status"] == "pending":
            st.caption(refusal)
        return
    with st.expander(f"Corriger l'image (1 crédit · {online_left} / {online_limit} restants)",
                     icon=":material/healing:"):
        st.caption("Décrivez ce qui ne va pas et cochez la zone : seule cette partie de l'image est retouchée, le "
                   "reste ne bouge pas. Une seule correction par visuel ; le résultat est la version finale.")
        grid = grid_overlay(params.get("scene_path"))
        if grid is not None:
            st.image(grid, width="stretch")
        defects = [f"{CHECK_LABELS.get(c['name'], c['name'])} : {c['detail']}" for c in checks
                   if c["status"] != "conforme" and c["name"] in ("Visage", "Action demandée", "Tenue")]
        instruction = st.text_area("Ce qui ne va pas", "\n".join(defects), key=f"fix_text_{render['id']}",
                                   height=90, placeholder="Ex. : la main gauche a six doigts ; ajouter un casque "
                                                          "blanc sur la tête ; enlever le seau à droite")
        if f"fix_cells_{render['id']}" not in st.session_state:
            scene = from_stored(params.get("scene_path"))
            faces = faces_in_scene(Image.open(scene).convert("RGB")) if scene and scene.exists() else []
            wants_face = any(w in instruction.lower() for w in ("visage", "tête", "tete", "yeux", "bouche"))
            st.session_state[f"fix_cells_{render['id']}"] = [r * 3 + c + 1 for r, c in faces] if wants_face else []
        numbers = st.pills("Zone à corriger", list(range(1, 10)), selection_mode="multi",
                           key=f"fix_cells_{render['id']}",
                           format_func=lambda n: f"{n} · {cell_label(((n - 1) // 3, (n - 1) % 3))}")
        can_fix = online_left > 0 and bool(instruction.strip()) and bool(numbers)
        if st.button("Corriger (1 crédit)", type="primary", icon=":material/healing:", disabled=not can_fix,
                     key=f"fix_go_{render['id']}", width="stretch"):
            try:
                with st.spinner("Correction de la zone en cours…"), db.connect() as conn:
                    new_id = correct_render(conn, render["id"], instruction,
                                            [((n - 1) // 3, (n - 1) % 3) for n in numbers])
            except (CorrectionRefused, SourceUnavailable) as exc:
                st.error(str(exc))
                return
            st.session_state.render_id = new_id
            st.session_state.flash = "Image corrigée : vérifiez la nouvelle version, puis approuvez-la."
            st.rerun()
        if online_left <= 0:
            st.caption("Quota du jour atteint : la correction sera possible demain.")



def client_filter() -> None:
    """Choix du client sur les pages Validation et Galerie (affiché dès qu'il y a plusieurs clients)."""
    brands = list_brands()
    if len(brands) < 2:
        return
    picked = st.selectbox("Client", brands, index=brands.index(brand_id), key="client_filter",
                          format_func=lambda b: load_profile(b).brand_name)
    if picked != brand_id:
        select_client(picked)
        st.rerun()


def page_validation():
    ui.page_head("Production", "Validation",
                 f"Contrôlez les visuels de {profile.brand_name}, puis approuvez-les ou rejetez-les. "
                 "Le fichier final se télécharge une fois le visuel approuvé.")
    client_filter()
    with db.connect() as conn:
        renders = reviewable([r for r in db.list_renders(conn, brand_id) if r["status"] != "error"])
    if not renders:
        st.info("Aucun visuel à valider pour le moment. Créez-en un depuis « Créer un visuel ».")
        return
    # Les mises en page proposées ensemble forment un seul groupe.
    groups: dict[str, list] = {}
    for r in renders:
        groups.setdefault(r["batch_id"] or r["id"], []).append(r)
    keys = list(groups)
    current_key = next((k for k, g in groups.items() if any(r["id"] == st.session_state.render_id for r in g)),
                       keys[0])

    def group_label(k):
        first = groups[k][0]
        n = len(groups[k])
        return (f"{fmt_date(first['created_at'])} — « {short(brief_text(first), 45)} » — "
                f"{TEMPLATES.get(first['template_id'], {}).get('label', 'mise en page')}"
                + (f" ({n} propositions)" if n > 1 else ""))

    group_key = st.selectbox("Visuel", keys, index=keys.index(current_key), format_func=group_label)
    group = sorted(groups[group_key], key=lambda r: json.loads(r["params"]).get("rank", 0))

    if len(group) > 1:
        with st.container(key="card_layouts"):
            st.subheader("Choisissez la mise en page à valider")
            cols = st.columns(len(group))
            for col, r in zip(cols, group):
                with db.connect() as conn:
                    statuses = [c["status"] for c in db.get_checks(conn, r["id"])]
                show_image(col, r["file_path"])
                n_fix = statuses.count("anomalie")
                final = " · version finale" if json.loads(r["params"]).get("quality_of") else ""
                col.caption(f"**{layout_label(r['layout'])}{final}**  \n"
                            + (f":red[{n_fix} à corriger]" if n_fix else ":green[Prête à valider]"))
            ids = [r["id"] for r in group]
            default = ids.index(st.session_state.render_id) if st.session_state.render_id in ids else 0
            render_id = st.radio("Mise en page retenue", ids, index=default, horizontal=True,
                                 format_func=lambda i: layout_label(next(r["layout"] for r in group if r["id"] == i)))
    else:
        render_id = group[0]["id"]
    st.session_state.render_id = render_id
    with db.connect() as conn:
        render = db.get_render(conn, render_id)
        checks = db.get_checks(conn, render_id)
        approval = db.latest_approval(conn, render_id)

    left, right = st.columns([1.3, 1], gap="large")
    with left.container(key="stage_review"):
        show_image(st, render["file_path"])
    render_params = json.loads(render["params"])
    is_preview = needs_quality_pass(render, render_params)
    with right:
        with st.container(key="card_checks"):
            ui.status_badge(st, render["status"])
            if render_params.get("quality_of"):
                st.caption("Version finale en haute qualité, créée à l'approbation de l'aperçu.")
            if render_params.get("correction_of"):
                fix = render_params.get("correction", {})
                st.caption(f"Version corrigée (zone : {', '.join(cell_label(c) for c in fix.get('cells', []))}) — "
                           f"« {fix.get('instruction', '')} ». C'est la version finale.")
            if st.session_state.get("check_notice"):
                st.warning(st.session_state.pop("check_notice"))
            if approval:
                verb = "Approuvé" if approval["decision"] == "approved" else "Rejeté"
                st.caption(f"{verb} par {approval['reviewer']} le {fmt_date(approval['created_at'])}"
                           + (f" — « {approval['comment']} »" if approval["comment"] else ""))

            to_fix = [c for c in checks if c["status"] == "anomalie"]
            to_look = [c for c in checks if c["status"] == "non_concluant"]
            passed = [c for c in checks if c["status"] == "conforme"]
            ui.label("Contrôles automatiques")
            if to_fix:
                st.error(f"**{len(to_fix)} point(s) à corriger** avant de pouvoir approuver")
                for c in to_fix:
                    st.markdown(f":red[:material/close:] **{CHECK_LABELS.get(c['name'], c['name'])}** — {c['detail']}")
            if to_look:
                st.info(f"**{len(to_look)} point(s) à vérifier à l'œil**")
                for c in to_look:
                    st.markdown(f":violet[:material/visibility:] **{CHECK_LABELS.get(c['name'], c['name'])}** — "
                                f"{c['detail']}")
            if not to_fix and not to_look:
                st.success("Tous les contrôles sont réussis.")
            with st.expander(f"{len(passed)} contrôle(s) réussi(s)", icon=":material/check:"):
                st.markdown("\n".join(f"- {CHECK_LABELS.get(c['name'], c['name'])}" for c in passed))

        correction_panel(render, render_params, checks)

        with st.form("decision"):
            st.subheader("Votre décision")
            if is_preview:
                st.caption("Ceci est un aperçu. À l'approbation, la version finale est créée en haute qualité "
                           "(30 s à 2 min), contrôlée à nouveau, puis approuvée si elle reste conforme.")
            reviewer = st.text_input("Votre nom")
            comment = st.text_area("Commentaire (facultatif)", height=80)
            ack = st.checkbox("J'ai vérifié à l'œil les points signalés", disabled=not to_look)
            c1, c2 = st.columns(2)
            approve = c1.form_submit_button("Approuver", type="primary", disabled=bool(to_fix),
                                            icon=":material/check:", width="stretch")
            reject = c2.form_submit_button("Rejeter", icon=":material/close:", width="stretch")
        if approve or reject:
            try:
                waiting = ("Création de la version finale en haute qualité…" if approve and is_preview
                           else "Enregistrement…")
                with st.spinner(waiting), db.connect() as conn:
                    approval_id = decide(conn, render_id, "approved" if approve else "rejected", reviewer,
                                         comment, ack or not to_look)
                    st.session_state.render_id = db.get_approval(conn, approval_id)["render_id"]
                if approve and is_preview:
                    st.session_state.flash = ("Version finale approuvée. Vérifiez-la : vous pouvez encore "
                                              "annuler l'approbation.")
                else:
                    st.session_state.flash = "Visuel approuvé." if approve else "Visuel rejeté."
                st.rerun()
            except QualityNotApproved as exc:
                st.session_state.render_id = exc.render_id
                st.session_state.check_notice = str(exc)
                st.rerun()
            except ApprovalRefused as exc:
                st.error(str(exc))
            except SourceUnavailable as exc:
                st.error("La version finale n'a pas pu être créée sur ce poste : l'aperçu reste en attente.")
                with st.expander("Détails pour l'administrateur"):
                    st.code(str(exc), language=None)

        if render["status"] == "approved" and render_params.get("quality_of"):
            with st.expander("Annuler l'approbation", icon=":material/undo:"):
                with st.form("cancel"):
                    st.caption("La version finale sera rejetée et l'aperçu reviendra en attente de validation.")
                    canceller = st.text_input("Votre nom", key="cancel_name")
                    if st.form_submit_button("Annuler l'approbation"):
                        try:
                            with db.connect() as conn:
                                preview = cancel_quality_approval(conn, render_id, canceller)
                            st.session_state.render_id = preview or render_id
                            st.session_state.flash = "Approbation annulée : l'aperçu est de nouveau en attente."
                            st.rerun()
                        except ApprovalRefused as exc:
                            st.error(str(exc))

        if render["status"] == "approved":
            if st.button("Préparer le fichier final", icon=":material/inventory_2:", width="stretch"):
                try:
                    with db.connect() as conn:
                        target = export_approved(conn, render_id)
                    st.download_button("Télécharger le visuel", Path(target).read_bytes(),
                                       file_name=target.name, mime="image/png", type="primary",
                                       icon=":material/download:", width="stretch")
                except ExportBlocked as exc:
                    st.error(str(exc))
        else:
            st.caption("Le téléchargement du fichier final sera possible une fois le visuel approuvé.")


# --- Galerie ---------------------------------------------------------------------
def delete_button(container, r, exported: bool) -> None:
    """Suppression d'un visuel, après confirmation. Un visuel déjà téléchargé demande une confirmation explicite."""
    with container.popover("Supprimer", width="stretch"):
        st.markdown("**Supprimer ce visuel ?**")
        final = json.loads(r["params"]).get("quality_of")
        st.caption("Le fichier, ses contrôles et ses décisions sont effacés définitivement"
                   + (", ainsi que l'aperçu dont il est issu." if final else ".")
                   + (" Il est approuvé." if r["status"] == "approved" else ""))
        if not exported:  # l'aperçu suit sa version finale si celle-ci a été téléchargée
            with db.connect() as conn:
                exported = any(db.is_exported(conn, v["id"]) for v in linked_versions(conn, r["id"]))
        if exported:
            st.warning("Ce visuel a déjà été téléchargé en version finale. Sa trace dans l'historique et sa copie "
                       "exportée seront aussi effacées (les fichiers déjà téléchargés sur votre ordinateur restent).")
            if not st.checkbox("Je confirme la suppression de l'historique", key=f"del_exp_{r['id']}"):
                return
        if st.button("Supprimer définitivement", key=f"del_ok_{r['id']}", type="primary", width="stretch"):
            try:
                with db.connect() as conn:
                    removed = delete_render(conn, r["id"], include_exported=exported)
            except DeleteRefused as exc:
                st.error(str(exc))
                return
            st.session_state.last_batch = [i for i in st.session_state.last_batch if i not in removed]
            if st.session_state.render_id in removed:
                st.session_state.render_id = None
            st.session_state.flash = "Visuel supprimé."
            st.rerun()


def page_gallery():
    ui.page_head("Production", "Galerie", f"Tous les visuels créés pour {profile.brand_name}.")
    client_filter()
    with db.connect() as conn:
        n_missing = len(db.missing_render_files(conn))
    if n_missing:
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.warning(f"{n_missing} visuel(s) de la galerie ont été supprimés du dossier.")
        if c2.button("Retirer de la galerie", width="stretch"):
            with db.connect() as conn:
                removed, kept = db.prune_missing_renders(conn)
            st.toast(f"{removed} visuel(s) retiré(s) de la galerie"
                     + (f" ; {kept} visuel(s) exporté(s) conservé(s) dans l'historique." if kept else "."))
            st.rerun()

    with db.connect() as conn:
        rows = [r for r in db.list_renders(conn, brand_id) if r["status"] != "error"]
        exported = db.exported_render_ids(conn)
    replaced = superseded_ids(rows)
    rows = [r for r in rows if r["id"] not in replaced]  # seule la version finale reste visible
    if not rows:
        st.info("La galerie est vide : vos visuels apparaîtront ici.")
        return
    filters = {"Tous": None, "En attente": "pending", "Approuvés": "approved", "Rejetés": "rejected"}
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    picked = c1.segmented_control("Afficher", list(filters), default="Tous", label_visibility="collapsed")
    wanted = filters.get(picked or "Tous")
    matching = [r for r in rows if wanted is None or r["status"] == wanted]
    limit = st.session_state.setdefault("gallery_limit", 24)
    shown = matching[:limit]
    c2.markdown(f"<div style='text-align:right'><span class='k-label'>{len(matching)} visuel(s)</span></div>",
                unsafe_allow_html=True)
    per_row = 4
    for start in range(0, len(shown), per_row):
        cols = st.columns(per_row)
        for col, r in zip(cols, shown[start:start + per_row]):
            with col.container(border=True, key=f"tile_{r['id']}"):
                show_image(st, r["file_path"])
                ui.status_badge(st, r["status"])
                st.caption(f"« {short(brief_text(r), 50)} »  \n{fmt_date(r['created_at'])}")
                b1, b2 = st.columns(2)
                if b1.button("Ouvrir", key=f"open_{r['id']}", width="stretch"):
                    st.session_state.render_id = r["id"]
                    st.switch_page(PAGES["validation"])
                delete_button(b2, r, r["id"] in exported)
    if len(matching) > limit:
        if st.button(f"Afficher plus ({len(matching) - limit} restant(s))"):
            st.session_state.gallery_limit = limit + 24
            st.rerun()


# --- Clients ---------------------------------------------------------------------
FONT_WEIGHTS = {"light": (300, "normal"), "regular": (400, "normal"), "medium": (500, "normal"),
                "bold": (700, "normal"), "italic": (400, "italic"), "bold_italic": (700, "italic")}


def white_logo(p):
    """Logo pour fond sombre (bandeau à la couleur du client), sinon le premier logo."""
    lg = next((lg for lg in p.logos if lg.on_dark_background), p.logos[0] if p.logos else None)
    return asset_path(p, lg.file) if lg else None


def charte_tag(p) -> str:
    return ui.tag("charte validée", "ok") if not p.unknowns else ""


def visible_renders(conn, b) -> list:
    rows = [r for r in db.list_renders(conn, b) if r["status"] != "error"]
    replaced = superseded_ids(rows)
    return [r for r in rows if r["id"] not in replaced]


def page_clients():
    fiche = st.query_params.get("fiche")
    if fiche in list_brands():
        client_sheet(fiche)
        return
    ui.page_head("Référentiel", "Clients & chartes",
                 "Chaque fiche porte la charte appliquée automatiquement aux visuels du client : "
                 "logos, palette, typographies et règles d'usage.")
    brands = list_brands()
    with db.connect() as conn:
        counts = {b: len(visible_renders(conn, b)) for b in brands}
    st.markdown(f"<div class='k-row' style='margin:8px 0 14px'><h2>Clients</h2>"
                f"<span class='k-label'>{len(brands)} client(s)</span></div>", unsafe_allow_html=True)
    per_row = 4
    for start in range(0, len(brands), per_row):
        cols = st.columns(per_row)
        for col, b in zip(cols, brands[start:start + per_row]):
            p = load_profile(b)
            colors = [c.hex for c in p.primary_colors.values()]
            sub = " · ".join(x for x in [p.local_market.market if p.local_market else "",
                                         f"{counts[b]} visuel(s)"] if x)
            with col.container(key=f"card_client_{b}"):
                st.markdown(ui.client_tile(p.brand_name, colors[0] if colors else "#111", white_logo(p), sub,
                                           colors, charte_tag(p) + (ui.tag("client actif") if b == brand_id
                                                                    else "")), unsafe_allow_html=True)
                if st.button("Ouvrir la fiche", key=f"fiche_{b}", width="stretch"):
                    st.query_params["fiche"] = b
                    st.rerun()


def client_sheet(b: str):
    p = load_profile(b)
    if st.button("Clients", key="back", type="tertiary", icon=":material/arrow_back:"):
        del st.query_params["fiche"]
        st.rerun()
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    with c1:
        market = f" · marché {p.local_market.market}" if p.local_market else ""
        ui.page_head("Fiche client", p.brand_name, f"Charte : {p.source_document}{market}")
    if c2.button("Créer un visuel", type="primary", icon=":material/auto_awesome:", width="stretch"):
        select_client(b)
        st.session_state.step = 1
        st.switch_page(PAGES["create"])

    primary = [c.hex for c in p.primary_colors.values()]
    left, right = st.columns([1.5, 1], gap="medium")
    with left:
        with st.container(key="card_logos"):
            tiles = "".join(ui.asset(asset_path(p, lg.file), lg.id.replace("_", " ").capitalize(),
                                     lg.description, bg=primary[0] if lg.on_dark_background and primary
                                     else "var(--g100)") for lg in p.logos)
            st.markdown(ui.card_head("Logos", f"{len(p.logos)} variante(s)")
                        + f"<div class='k-grid' style='grid-template-columns:repeat(auto-fill,minmax(200px,1fr))'>"
                        f"{tiles}</div>", unsafe_allow_html=True)

        with st.container(key="card_palette"):
            def swatches(colors):
                return "".join(ui.swatch(c.name.replace("_", " ").capitalize(), c.hex,
                                         " · ".join(x for x in [f"Pantone {c.pantone}" if c.pantone else "",
                                                                f"CMJN {'/'.join(map(str, c.cmyk))}" if c.cmyk
                                                                else ""] if x)) for c in colors)
            html = ui.card_head("Palette", "couleurs de la charte")
            html += f"<span class='k-label' style='margin:8px 0'>Principales</span>" \
                    f"<div class='k-grid'>{swatches(p.primary_colors.values())}</div>"
            if p.secondary_colors:
                html += f"<span class='k-label' style='margin:18px 0 8px'>Secondaires</span>" \
                        f"<div class='k-grid'>{swatches(p.secondary_colors)}</div>"
            if p.neutral_colors:
                html += f"<span class='k-label' style='margin:18px 0 8px'>Texte et neutres</span>" \
                        f"<div class='k-grid'>{swatches(p.neutral_colors.values())}</div>"
            st.markdown(html, unsafe_allow_html=True)
            st.caption(p.primary_color_rule)

        refs = sorted(asset_path(p, "references").glob("*.*")) if asset_path(p, "references").is_dir() else []
        refs = [r for r in refs if r.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
        if refs:
            with st.container(key="card_refs"):
                st.markdown(ui.card_head("Visuels de référence", f"{len(refs)} fichier(s)"), unsafe_allow_html=True)
                st.caption("Visuels déjà livrés au client, qui servent de modèle aux mises en page.")
                cols = st.columns(4)
                for col, r in zip(cols * (len(refs) // 4 + 1), refs):
                    col.image(str(r), width="stretch")

        with db.connect() as conn:
            recent = visible_renders(conn, b)[:8]
        if recent:
            with st.container(key="card_recent"):
                st.markdown(ui.card_head("Derniers visuels", f"{len(recent)} récent(s)"), unsafe_allow_html=True)
                cols = st.columns(4)
                for i, r in enumerate(recent):
                    with cols[i % 4]:
                        show_image(st, r["file_path"])
                        ui.status_badge(st, r["status"])

    with right:
        with st.container(key="card_fonts"):
            family = f"brand-{b}"
            faces = "".join(ui.font_face(family, asset_path(p, f), *FONT_WEIGHTS.get(k, (400, "normal")))
                            for k, f in p.fonts.items() if k in ("regular", "bold"))
            names = [p.font_name]
            sample = p.series_tags and next(iter(p.series_tags)) or p.brand_name
            st.html(f"<style>{faces}</style>")
            st.markdown(ui.card_head("Typographies", ", ".join(names))
                        + f"<div class='k-font-sample' style=\"font-family:'{family}';font-weight:700\">"
                        f"{sample}</div>"
                        f"<div style=\"font-family:'{family}';font-size:15px;color:var(--g700)\">"
                        "Aa Bb Cc Dd Ee — 0123456789 — àâçéèêëîôûù</div>"
                        f"<div class='k-tags' style='margin-top:12px'>"
                        + "".join(ui.tag(k.replace("_", " ")) for k in p.fonts) + "</div>",
                        unsafe_allow_html=True)

        with st.container(key="card_rules"):
            rules = ui.card_head("Règles d'usage")
            rules += ui.setting("Orthographe officielle", p.official_spelling)
            if p.forbidden_spellings:
                rules += ui.setting("Orthographes interdites", ", ".join(p.forbidden_spellings))
            if p.internal_only_abbreviations:
                rules += ui.setting("Abréviations internes", "À ne jamais publier : "
                                    + ", ".join(p.internal_only_abbreviations))
            rules += ui.setting("Aplats semi-transparents sur photo",
                                "Autorisés par la marque" if p.overlays_allowed else "Non autorisés")
            rules += ui.setting("Logo", "Posé par la plateforme depuis les fichiers officiels, jamais créé par l'IA.")
            st.markdown(rules, unsafe_allow_html=True)

        if p.local_market:
            m = p.local_market
            with st.container(key="card_market"):
                html = ui.card_head(f"Signature locale · {m.market}")
                ct = p.contact
                for title, value in [("Mention", m.tagline), ("Site / réseaux", m.handle), ("Adresse", m.address),
                                     ("WhatsApp", ct and ct.whatsapp), ("Téléphone", ct and ct.phone),
                                     ("Site web", ct and ct.website), ("Signature", ct and ct.slogan)]:
                    if value:
                        html += ui.setting(title, value)
                st.markdown(html, unsafe_allow_html=True)

        if p.series_tags or p.iconography_themes:
            with st.container(key="card_series"):
                html = ui.card_head("Séries et univers")
                for name, lines in p.series_tags.items():
                    html += ui.setting(name, "Étiquette : " + " / ".join(lines))
                if p.iconography_themes:
                    html += ("<div class='k-setting'><div class='txt'><b>Thèmes iconographiques</b>"
                             f"<div class='k-tags' style='margin-top:6px'>"
                             + "".join(ui.tag(t) for t in p.iconography_themes) + "</div></div></div>")
                st.markdown(html, unsafe_allow_html=True)


# --- Navigation ------------------------------------------------------------------
PAGES = {
    "create": st.Page(page_create, title="Créer un visuel", icon=":material/auto_awesome:", url_path="creer",
                      default=True),
    "validation": st.Page(page_validation, title=f"À valider ({n_pending})" if n_pending else "À valider",
                          icon=":material/check:", url_path="valider"),
    "gallery": st.Page(page_gallery, title="Galerie", icon=":material/grid_view:", url_path="galerie"),
    "clients": st.Page(page_clients, title="Clients", icon=":material/domain:", url_path="clients"),
}
page = st.navigation({"Production": [PAGES["create"], PAGES["validation"], PAGES["gallery"]],
                      "Référentiel": [PAGES["clients"]]})

with st.sidebar:
    st.markdown(ui.engine_status(ai_configured(), (online_left, online_limit) if online.configured() else None),
                unsafe_allow_html=True)

with st.container(key="topbar"):
    c1, c2 = st.columns([3, 1])
    c1.markdown(ui.topbar_crumbs(page.title.split(" (")[0]), unsafe_allow_html=True)
    if page.title != PAGES["create"].title:
        c2.page_link(PAGES["create"], label="Créer un visuel", icon=":material/auto_awesome:")

page.run()
