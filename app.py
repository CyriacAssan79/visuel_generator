"""Interface studio KÔMIAN — lancer avec : streamlit run app.py

L'interface ne montre que ce qui sert à créer et valider un visuel. Les détails techniques (modèles, moteurs,
identifiants, base de données) restent enregistrés pour la traçabilité, mais ne sont pas affichés.
"""
import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from komian import db
from komian.backgrounds import (SOURCES, GeometricSource, SourceUnavailable, active_model, model_choices,
                                resolve_device, suggest_prompt)
from komian.brands import list_brands, load_profile
from komian.compose import TEMPLATES, layout_label
from komian.config import FORMATS, from_stored, to_stored
from komian.models import Brief
from komian.storage import ImportRejected, import_image
from komian.workflow import (ApprovalRefused, ExportBlocked, PlanBlocked, decide, export_approved, generate,
                             generate_variants, prepare_plan)

# --- Libellés affichés -----------------------------------------------------------
OBJECTIVES = ["motiver", "promouvoir", "informer", "recruter", "sensibiliser", "autre"]
FORMAT_LABELS = {"post_carre": "Post carré", "post_portrait": "Post portrait", "story": "Story"}
SOURCE_LABELS = {"photo": "📷 Ma photo", "geometrique": "🔷 Formes aux couleurs de la marque",
                 "ia_locale": "✨ Image créée par l'IA"}
SOURCE_HELP = {"photo": "Importez une photo libre de droits.",
               "geometrique": "Un fond graphique simple, en aplats de couleurs de la charte.",
               "ia_locale": "Décrivez la scène : l'IA crée la photo, le texte et le logo sont ajoutés ensuite."}
STATUS = {"pending": ("En attente de validation", "orange"), "approved": ("Approuvé", "green"),
          "rejected": ("Rejeté", "red")}
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

st.set_page_config(page_title="KÔMIAN Studio", page_icon="🎨", layout="wide")
st.session_state.setdefault("brief_id", None)
st.session_state.setdefault("render_id", None)
st.session_state.setdefault("last_batch", [])
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


def status_badge(container, status: str) -> None:
    label, color = STATUS.get(status, (status, "gray"))
    container.badge(label, color=color)


def show_image(container, stored_path) -> bool:
    """Affiche un visuel ; s'il a été supprimé du dossier, le signale sans faire planter la page."""
    path = from_stored(stored_path)
    if path and path.exists():
        container.image(str(path), width="stretch")
        return True
    container.warning("Image introuvable : elle a été supprimée du dossier.")
    return False


def mode_label(spec: dict) -> str:
    """« ⚡ Rapide · ≈ 6 s — pour essayer des idées » à partir de la configuration du modèle."""
    name = spec.get("label", "").split(":")[0].strip() or "IA"
    if spec.get("lcm"):
        return f"⚡ {name} · ≈ {spec['expected_s']} s — pour essayer des idées"
    return f"✨ {name} · ≈ {spec['expected_s']} s — pour la version finale"


# --- Barre latérale : marque -----------------------------------------------------
with st.sidebar:
    st.title("🎨 KÔMIAN Studio")
    brand_id = st.selectbox("Marque", list_brands(), format_func=lambda b: load_profile(b).brand_name)
    profile = load_profile(brand_id)
    colors = list(profile.primary_colors.values())
    st.markdown(" ".join(f"<span style='background:{c.hex};color:white;padding:3px 10px;border-radius:12px;"
                         f"font-size:0.85em'>{c.name.replace('_', ' ')}</span>" for c in colors),
                unsafe_allow_html=True)
    if profile.unknowns:
        with st.expander(f"⚠️ {len(profile.unknowns)} point(s) de charte à confirmer"):
            for u in profile.unknowns:
                st.markdown(f"- {u}")
    else:
        st.caption("✅ Charte validée")

    with db.connect() as conn:
        n_missing = len(db.missing_render_files(conn))
    if n_missing:
        st.divider()
        st.caption(f"{n_missing} visuel(s) de la galerie ont été supprimés du dossier.")
        if st.button("Retirer de la galerie"):
            with db.connect() as conn:
                removed, kept = db.prune_missing_renders(conn)
            st.toast(f"{removed} visuel(s) retiré(s) de la galerie"
                     + (f" ; {kept} visuel(s) exporté(s) conservé(s) dans l'historique." if kept else "."))
            st.rerun()

tab_brief, tab_gen, tab_check, tab_gallery = st.tabs(
    ["✏️ 1. Brief", "🎨 2. Création", "✅ 3. Validation", "🗂️ Galerie"])

# --- 1. Brief --------------------------------------------------------------------
with tab_brief:
    with db.connect() as conn:
        briefs = db.list_briefs(conn, brand_id)
    options = {"➕ Nouveau brief": None}
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
        series = c1.text_input("Série", current.series if current else "Lundi motivation")
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
        submitted = st.form_submit_button("Enregistrer les modifications" if current else "Créer le brief",
                                          type="primary")

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
            st.session_state.flash = "Brief enregistré. Étape suivante : 🎨 2. Création."
            st.rerun()
        except Exception as exc:
            st.error(f"Le brief n'a pas pu être enregistré : {exc}")

    if current:
        with db.connect() as conn:
            versions = db.brief_versions(conn, current_row["brief_key"])
        if len(versions) > 1:
            with st.expander(f"Historique des modifications ({len(versions)} versions)"):
                for v in versions:
                    d = json.loads(v["data"])
                    st.markdown(f"**Version {v['version']}** · {fmt_date(v['created_at'])} · "
                                f"{v['author'] or 'auteur inconnu'}  \n"
                                f"{v['change_note'] or 'Création'} — « {d['exact_visual_text']} »")

# --- 2. Création -----------------------------------------------------------------
with tab_gen:
    if not st.session_state.brief_id:
        st.info("Commencez par créer ou choisir un brief dans l'onglet ✏️ 1. Brief.")
    else:
        with db.connect() as conn:
            row, brief = db.get_brief(conn, st.session_state.brief_id)
        st.markdown(f"#### « {brief.exact_visual_text} »")
        st.caption(f"{format_label(brief.format_id)} · {brief.series or 'hors série'}")

        st.subheader("Mise en page")
        template_id = st.selectbox("Modèle de mise en page", list(TEMPLATES),
                                   format_func=lambda t: TEMPLATES[t]["label"], label_visibility="collapsed")

        st.subheader("Image de fond")
        source_ids = list(SOURCES)
        source_id = st.radio("Image de fond", source_ids, horizontal=True, label_visibility="collapsed",
                             format_func=lambda s: SOURCE_LABELS.get(s, s),
                             index=source_ids.index("ia_locale" if active_model() else "geometrique"))
        st.caption(SOURCE_HELP.get(source_id, ""))

        plan = prepare_plan(profile, brief, template_id, source_id)
        for b in plan.blocking:
            st.error(b)
        for w in plan.warnings:
            st.warning(w)

        params: dict = {}
        upload = None
        expected_s = None
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
                               format_func=lambda v: "🎲 Surprise" if v == "auto" else GEOMETRIC_VARIANTS.get(v, v),
                               help="« Surprise » choisit un style différent des derniers visuels de la série.")
            if variant != "auto":
                params["variant"] = variant
        else:
            choices = model_choices()
            if not choices:
                st.warning("La création d'image par IA n'est pas disponible sur ce poste.")
            else:
                default_key = active_model()[0]
                keys = [k for k, _ in choices]
                params["model_choice"] = st.radio(
                    "Qualité", keys, horizontal=True, index=keys.index(default_key) if default_key in keys else 0,
                    format_func=lambda k: mode_label(dict(choices)[k]))
                spec = dict(choices)[params["model_choice"]]
                expected_s = spec["expected_s"]
                device = spec.get("device", "CPU")
                if spec.get("engine") == "openvino" and resolve_device(device) != device.upper():
                    st.warning("Ce poste fonctionne en mode ralenti : la création prendra environ 10 fois plus "
                               "de temps que prévu.")
            params["prompt"] = st.text_area(
                "Décrivez la scène", suggest_prompt(brief.visual_direction), key=f"prompt_{row['id']}", height=110,
                help="En français ou en anglais. Indiquez qui (âge, tenue), quoi (une action simple), où, le cadrage "
                     "et la lumière. N'écrivez ni texte ni logo : ils sont ajoutés ensuite.")
            with st.expander("💡 Conseils pour une belle image"):
                st.markdown(
                    "- **Une personne en plan taille** qui regarde l'objectif donne les meilleurs résultats.\n"
                    "- **Précisez la tenue** (« en t-shirt blanc », « en chemise rouge »).\n"
                    "- **Évitez les gestes précis avec un outil** et les petits visages en plan large : "
                    "préférez alors une vraie photo.\n"
                    "- Le résultat ne convient pas ? **Relancez** : chaque création propose une nouvelle image.\n"
                    "- Le mode ⚡ Rapide sert à essayer des idées ; passez en ✨ Qualité pour la version finale.")
            params["saturation"] = st.slider("Intensité des couleurs", 0.0, 1.0, 1.0, 0.05, help="0 = noir et blanc")

        n_layouts = len(TEMPLATES[template_id]["layouts"])
        variants = st.toggle(f"Proposer {min(3, n_layouts)} mises en page au choix", value=n_layouts > 1,
                             disabled=n_layouts < 2)
        if st.button("✨ Créer le visuel", type="primary", disabled=bool(plan.blocking)):
            wait = (f" (environ {expected_s} s ; la première création après un démarrage prend 1 à 3 minutes de "
                    "plus)") if expected_s else ""
            try:
                if source_id == "photo":
                    if upload is None:
                        raise ImportRejected("Importez d'abord une photo.")
                    params["photo_path"] = to_stored(import_image(upload.getvalue(), upload.name, brand_id))
                with st.spinner(f"Création du visuel en cours{wait}…"), db.connect() as conn:
                    if variants and n_layouts > 1:
                        _, ids = generate_variants(conn, st.session_state.brief_id, template_id, source_id, params)
                    else:
                        ids = [generate(conn, st.session_state.brief_id, template_id, source_id, params)]
                st.session_state.render_id = ids[0]
                st.session_state.last_batch = ids
            except ImportRejected as exc:
                st.error(f"Photo refusée : {exc}")
            except PlanBlocked as exc:
                st.error(str(exc))
            except SourceUnavailable as exc:
                st.error("La création d'image par IA n'est pas disponible sur ce poste pour le moment. "
                         "Choisissez une autre image de fond, ou contactez l'administrateur.")
                with st.expander("Détails pour l'administrateur"):
                    st.code(str(exc), language=None)
            except Exception as exc:
                st.error("La création a échoué. Réessayez ; si le problème persiste, contactez l'administrateur.")
                with st.expander("Détails pour l'administrateur"):
                    st.code(f"{type(exc).__name__} : {exc}", language=None)

        if st.session_state.last_batch:
            with db.connect() as conn:
                made = [db.get_render(conn, i) for i in st.session_state.last_batch]
            made = [r for r in made if r["status"] != "error"]
            if made:
                st.success("Visuel prêt ! Choisissez et validez-le dans l'onglet ✅ 3. Validation.")
                cols = st.columns(len(made))
                for col, r in zip(cols, made):
                    show_image(col, r["file_path"])
                    col.caption(layout_label(r["layout"]))

# --- 3. Validation ---------------------------------------------------------------
with tab_check:
    with db.connect() as conn:
        renders = [r for r in db.list_renders(conn, brand_id) if r["status"] != "error"]
    if not renders:
        st.info("Aucun visuel à valider pour le moment. Créez-en un dans l'onglet 🎨 2. Création.")
    else:
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
            st.markdown("**Choisissez la mise en page à valider**")
            cols = st.columns(len(group))
            for col, r in zip(cols, group):
                with db.connect() as conn:
                    statuses = [c["status"] for c in db.get_checks(conn, r["id"])]
                show_image(col, r["file_path"])
                n_fix = statuses.count("anomalie")
                col.caption(f"**{layout_label(r['layout'])}**  \n"
                            + (f"❌ {n_fix} à corriger" if n_fix else "✅ Prête à valider"))
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

        st.divider()
        left, right = st.columns([1, 1])
        show_image(left, render["file_path"])
        with right:
            status_badge(st, render["status"])
            if approval:
                verb = "Approuvé" if approval["decision"] == "approved" else "Rejeté"
                st.caption(f"{verb} par {approval['reviewer']} le {fmt_date(approval['created_at'])}"
                           + (f" — « {approval['comment']} »" if approval["comment"] else ""))

            to_fix = [c for c in checks if c["status"] == "anomalie"]
            to_look = [c for c in checks if c["status"] == "non_concluant"]
            passed = [c for c in checks if c["status"] == "conforme"]
            if to_fix:
                st.error(f"**{len(to_fix)} point(s) à corriger** avant de pouvoir approuver")
                for c in to_fix:
                    st.markdown(f"❌ **{CHECK_LABELS.get(c['name'], c['name'])}** — {c['detail']}")
            if to_look:
                st.info(f"**{len(to_look)} point(s) à vérifier à l'œil**")
                for c in to_look:
                    st.markdown(f"👁️ **{CHECK_LABELS.get(c['name'], c['name'])}** — {c['detail']}")
            if not to_fix and not to_look:
                st.success("Tous les contrôles sont réussis.")
            with st.expander(f"✅ {len(passed)} contrôle(s) réussi(s)"):
                st.markdown("\n".join(f"- {CHECK_LABELS.get(c['name'], c['name'])}" for c in passed))

            with st.form("decision"):
                st.markdown("**Votre décision**")
                reviewer = st.text_input("Votre nom")
                comment = st.text_area("Commentaire (facultatif)", height=80)
                ack = st.checkbox("J'ai vérifié à l'œil les points signalés", disabled=not to_look)
                c1, c2 = st.columns(2)
                approve = c1.form_submit_button("✅ Approuver", type="primary", disabled=bool(to_fix),
                                                width="stretch")
                reject = c2.form_submit_button("Rejeter", width="stretch")
            if approve or reject:
                try:
                    with db.connect() as conn:
                        decide(conn, render_id, "approved" if approve else "rejected", reviewer, comment,
                               ack or not to_look)
                    st.session_state.flash = "Visuel approuvé." if approve else "Visuel rejeté."
                    st.rerun()
                except ApprovalRefused as exc:
                    st.error(str(exc))

            if render["status"] == "approved":
                if st.button("📦 Préparer le fichier final", width="stretch"):
                    try:
                        with db.connect() as conn:
                            target = export_approved(conn, render_id)
                        st.download_button("⬇️ Télécharger le visuel", Path(target).read_bytes(),
                                           file_name=target.name, mime="image/png", type="primary",
                                           width="stretch")
                    except ExportBlocked as exc:
                        st.error(str(exc))
            else:
                st.caption("Le téléchargement du fichier final sera possible une fois le visuel approuvé.")

# --- Galerie ---------------------------------------------------------------------
with tab_gallery:
    with db.connect() as conn:
        rows = [r for r in db.list_renders(conn, brand_id) if r["status"] != "error"]
    if not rows:
        st.info("La galerie est vide : vos visuels apparaîtront ici.")
    else:
        filters = {"Tous": None, "En attente": "pending", "Approuvés": "approved", "Rejetés": "rejected"}
        picked = st.segmented_control("Afficher", list(filters), default="Tous", label_visibility="collapsed")
        wanted = filters.get(picked or "Tous")
        matching = [r for r in rows if wanted is None or r["status"] == wanted]
        limit = st.session_state.setdefault("gallery_limit", 24)
        shown = matching[:limit]
        st.caption(f"{len(matching)} visuel(s)")
        per_row = 4
        for start in range(0, len(shown), per_row):
            cols = st.columns(per_row)
            for col, r in zip(cols, shown[start:start + per_row]):
                with col.container(border=True):
                    show_image(st, r["file_path"])
                    status_badge(st, r["status"])
                    st.caption(f"« {short(brief_text(r), 50)} »  \n{fmt_date(r['created_at'])}")
                    if st.button("Ouvrir", key=f"open_{r['id']}", width="stretch"):
                        st.session_state.render_id = r["id"]
                        st.session_state.flash = "Visuel sélectionné : il est affiché dans l'onglet ✅ 3. Validation."
                        st.rerun()
        if len(matching) > limit:
            if st.button(f"Afficher plus ({len(matching) - limit} restant(s))"):
                st.session_state.gallery_limit = limit + 24
                st.rerun()
