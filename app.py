"""Interface studio KÔMIAN — lancer avec : streamlit run app.py"""
import json
from pathlib import Path

import streamlit as st

from komian import db
from komian.backgrounds import (SOURCES, GeometricSource, active_model, model_choices, resolve_device,
                                suggest_prompt)
from komian.brands import list_brands, load_profile
from komian.compose import TEMPLATES, layout_label
from komian.config import FORMATS, from_stored, to_stored
from komian.models import Brief
from komian.storage import ImportRejected, import_image
from komian.workflow import (ApprovalRefused, ExportBlocked, PlanBlocked, decide, export_approved, generate,
                             generate_variants,
                             prepare_plan)

STATUS_ICON = {"conforme": "✅ Conforme", "anomalie": "❌ Anomalie", "non_concluant": "❔ Non concluant"}
OBJECTIVES = ["motiver", "promouvoir", "informer", "recruter", "sensibiliser", "autre"]

st.set_page_config(page_title="KÔMIAN — Studio", page_icon="🎨", layout="wide")
st.session_state.setdefault("brief_id", None)
st.session_state.setdefault("render_id", None)

# --- Marque ------------------------------------------------------------------
with st.sidebar:
    st.title("KÔMIAN Studio")
    brand_id = st.selectbox("Marque", list_brands())
    profile = load_profile(brand_id)
    st.caption(f"Source : {profile.source_document} — version {profile.source_version_status}")
    st.markdown(" ".join(f"<span style='background:{c.hex};color:white;padding:2px 8px;border-radius:4px'>"
                         f"{c.name}</span>" for c in profile.primary_colors.values()), unsafe_allow_html=True)
    st.caption(profile.primary_color_rule)
    with st.expander(f"⚠️ {len(profile.unknowns)} points à confirmer"):
        for u in profile.unknowns:
            st.markdown(f"- {u}")
    with db.connect() as conn:
        n_missing = len(db.missing_render_files(conn))
    if n_missing:
        st.warning(f"{n_missing} rendu(s) enregistré(s) dont le fichier a été supprimé du dossier.")
        if st.button("Mettre à jour la base"):
            with db.connect() as conn:
                removed, kept = db.prune_missing_renders(conn)
            st.toast(f"{removed} rendu(s) retiré(s) de la base"
                     + (f", {kept} exporté(s) conservé(s) pour la traçabilité." if kept else "."))
            st.rerun()


def show_image(container, stored_path):
    """Affiche un rendu, ou un avertissement si son fichier a disparu (au lieu de faire planter la page)."""
    path = from_stored(stored_path)
    if path and path.exists():
        container.image(str(path), width="stretch")
    else:
        container.warning("Fichier introuvable : supprimé du dossier ? Utiliser « Mettre à jour la base ».")

tab_brief, tab_gen, tab_check, tab_hist = st.tabs(
    ["1. Brief", "2. Génération", "3. Contrôle et validation", "4. Historique"])

# --- 1. Brief ----------------------------------------------------------------
with tab_brief:
    with db.connect() as conn:
        briefs = db.list_briefs(conn, brand_id)
    options = {"➕ Nouveau brief": None}
    for b in briefs:
        data = json.loads(b["data"])
        options[f"{data['exact_visual_text'][:50]} — v{b['version']} ({b['brief_key']})"] = b["id"]
    choice = st.selectbox("Brief", list(options))
    current_id = options[choice]
    current = None
    if current_id:
        with db.connect() as conn:
            current_row, current = db.get_brief(conn, current_id)
        st.session_state.brief_id = current_id

    with st.form("brief"):
        c1, c2, c3 = st.columns(3)
        series = c1.text_input("Série", current.series if current else "Lundi motivation")
        objective = c2.selectbox("Objectif", OBJECTIVES, OBJECTIVES.index(current.objective) if current else 0)
        format_id = c3.selectbox("Format", list(FORMATS),
                                 list(FORMATS).index(current.format_id) if current else 0,
                                 format_func=lambda f: f"{f} ({FORMATS[f][0]}×{FORMATS[f][1]})")
        channel = c1.text_input("Canal", current.channel if current else "Instagram / Facebook")
        audience = c2.text_input("Public cible (facultatif)", (current.target_audience or "") if current else "")
        positions = ["bas à droite", "bas à gauche", "haut à droite", "haut à gauche"]
        logo_pos = c3.selectbox("Position du logo", positions,
                                positions.index(current.logo_position) if current else 0)
        headline = st.text_input("Accroche", current.headline if current else "")
        exact = st.text_input("Texte exact à afficher (conservé caractère pour caractère)",
                              current.exact_visual_text if current else "")
        direction = st.text_area("Direction artistique", current.visual_direction if current else "")
        icons = st.multiselect("Icônes", ["calendrier", "coche"], current.icons if current else [])
        c1, c2 = st.columns(2)
        show_tag = c1.checkbox("Afficher l'étiquette de série (ex. « Lundi / MOTIVATION »)",
                               current.show_series_tag if current else True)
        head_on = c2.checkbox("Afficher l'accroche sur le visuel (sinon : texte de la publication)",
                              current.headline_on_visual if current else False)
        constraints = st.text_area("Interdictions / zones à préserver (une par ligne)",
                                   "\n".join(current.constraints) if current else "")
        author = st.text_input("Auteur")
        note = st.text_input("Justification de la modification (obligatoire pour une nouvelle version)",
                             disabled=current is None)
        submitted = st.form_submit_button("Enregistrer une nouvelle version" if current else "Créer le brief")

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
            st.success("Brief enregistré.")
            st.rerun()
        except Exception as exc:
            st.error(f"Brief refusé : {exc}")

    if current:
        with db.connect() as conn:
            versions = db.brief_versions(conn, current_row["brief_key"])
        if len(versions) > 1:
            st.subheader("Historique des versions")
            for v in versions:
                d = json.loads(v["data"])
                st.markdown(f"**v{v['version']}** — {v['created_at']} — {v['author'] or '?'} — "
                            f"_{v['change_note']}_  \n« {d['exact_visual_text']} »")

# --- 2. Génération -----------------------------------------------------------
with tab_gen:
    if not st.session_state.brief_id:
        st.info("Sélectionner ou créer un brief dans l'onglet 1.")
    else:
        with db.connect() as conn:
            row, brief = db.get_brief(conn, st.session_state.brief_id)
        st.markdown(f"**Brief v{row['version']}** — « {brief.exact_visual_text} »")
        c1, c2 = st.columns(2)
        template_id = c1.selectbox("Gabarit", list(TEMPLATES), format_func=lambda t: TEMPLATES[t]["label"])
        source_ids = list(SOURCES)
        source_id = c2.radio("Source de l'image de fond", source_ids, format_func=lambda s: SOURCES[s].label,
                             index=source_ids.index("ia_locale" if active_model() else "geometrique"))

        plan = prepare_plan(profile, brief, template_id, source_id)
        with st.expander("Plan de génération", expanded=bool(plan.warnings or plan.blocking)):
            st.markdown("**Contraintes strictes**\n" + "\n".join(f"- {s}" for s in plan.strict))
            st.markdown("**Préférences créatives**\n" + "\n".join(f"- {p}" for p in plan.preferences))
            for b in plan.blocking:
                st.error(b)
            for w in plan.warnings:
                st.warning(w)

        params: dict = {}
        upload = None
        if source_id == "photo":
            upload = st.file_uploader("Photo (JPG, PNG, WEBP)", type=["jpg", "jpeg", "png", "webp"])
            c1, c2 = st.columns(2)
            params["saturation"] = c1.slider("Saturation (0 = noir et blanc)", 0.0, 1.0, 1.0, 0.05)
            params["focus_y"] = c2.slider("Cadrage vertical", 0.0, 1.0, 0.4, 0.05)
            rights = st.text_input("Droits vérifiés par (laisser vide si non vérifiés)")
            if rights.strip():
                params["rights_confirmed_by"] = rights.strip()
        elif source_id == "geometrique":
            variant = st.selectbox("Variante", ["auto"] + list(GeometricSource.variants),
                                   format_func=lambda v: "Automatique (différente des dernières de la série)"
                                   if v == "auto" else v)
            if variant != "auto":
                params["variant"] = variant
        else:
            choices = model_choices()
            if not choices:
                st.warning("Aucun modèle IA retenu après benchmark : cette source est inactive.")
            else:
                default_key = active_model()[0]
                keys = [k for k, _ in choices]
                params["model_choice"] = st.radio(
                    "Mode de génération", keys, horizontal=True,
                    index=keys.index(default_key) if default_key in keys else 0,
                    format_func=lambda k: dict(choices)[k].get("label", k))
                spec = dict(choices)[params["model_choice"]]
                device = spec.get("device", "CPU")
                if spec.get("engine") == "openvino" and resolve_device(device) != device.upper():
                    st.warning("La puce graphique Intel n'est pas accessible (pilote absent sous WSL ?) : "
                               "la génération passe sur le processeur, environ 10 fois plus lente.")
                    device = "CPU"
                where = {"GPU": "puce graphique Intel", "CPU": "processeur"}.get(device, "processeur")
                engine = "OpenVINO" if spec.get("engine") == "openvino" else "PyTorch"
                st.caption(f"{engine} sur {where}, {spec['steps']} étapes, environ {spec['expected_s']} s par scène "
                           f"(licence {spec['licence']}). Le premier usage après démarrage charge le modèle "
                           "(environ 1 à 3 minutes).")
            params["prompt"] = st.text_area(
                "Description de la scène, en français ou en anglais (sans texte ni logo : ils sont ajoutés ensuite)",
                suggest_prompt(brief.visual_direction), key=f"prompt_{row['id']}")
            params["saturation"] = st.slider("Saturation (0 = noir et blanc)", 0.0, 1.0, 1.0, 0.05)

        n_layouts = len(TEMPLATES[template_id]["layouts"])
        variants = st.checkbox(f"Proposer {min(3, n_layouts)} mises en page différentes (même fond)", value=True,
                               disabled=n_layouts < 2)
        if st.button("Générer", type="primary", disabled=bool(plan.blocking)):
            try:
                if source_id == "photo":
                    if upload is None:
                        raise ImportRejected("Aucune photo importée.")
                    params["photo_path"] = to_stored(import_image(upload.getvalue(), upload.name, brand_id))
                with st.spinner("Composition en cours…"), db.connect() as conn:
                    if variants and n_layouts > 1:
                        _, ids = generate_variants(conn, st.session_state.brief_id, template_id, source_id, params)
                        st.session_state.render_id = ids[0]
                    else:
                        st.session_state.render_id = generate(conn, st.session_state.brief_id, template_id,
                                                              source_id, params)
                st.success("Rendu prêt : voir l'onglet 3.")
            except (ImportRejected, PlanBlocked) as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"Échec du rendu ({type(exc).__name__}) : {exc}")

# --- 3. Contrôle et validation ------------------------------------------------
with tab_check:
    with db.connect() as conn:
        renders = [r for r in db.list_renders(conn, brand_id) if r["status"] != "error"]
    if not renders:
        st.info("Aucun rendu pour cette marque.")
    else:
        # Regroupe les variantes d'un même lot ; un rendu isolé forme son propre groupe.
        groups: dict[str, list] = {}
        for r in renders:
            groups.setdefault(r["batch_id"] or r["id"], []).append(r)
        keys = list(groups)
        current_key = next((k for k, g in groups.items() if any(r["id"] == st.session_state.render_id for r in g)),
                           keys[0])
        group_key = st.selectbox("Génération", keys, index=keys.index(current_key), format_func=lambda k: (
            f"{groups[k][0]['created_at']} — {groups[k][0]['template_id']} / {groups[k][0]['background_source']}"
            f" — brief v{groups[k][0]['brief_version']} — {len(groups[k])} variante(s)"))
        group = sorted(groups[group_key], key=lambda r: json.loads(r["params"]).get("rank", 0))

        if len(group) > 1:
            st.markdown("**Choisir une variante**")
            cols = st.columns(len(group))
            for col, r in zip(cols, group):
                with db.connect() as conn:
                    statuses = [c["status"] for c in db.get_checks(conn, r["id"])]
                show_image(col, r["file_path"])
                col.caption(f"**{layout_label(r['layout'])}** — {r['status']}  \n"
                            f"❌ {statuses.count('anomalie')} · ❔ {statuses.count('non_concluant')}")
            ids = [r["id"] for r in group]
            default = ids.index(st.session_state.render_id) if st.session_state.render_id in ids else 0
            render_id = st.radio("Variante à examiner", ids, index=default, horizontal=True,
                                 format_func=lambda i: layout_label(next(r["layout"] for r in group if r["id"] == i)))
        else:
            render_id = group[0]["id"]
        st.session_state.render_id = render_id
        with db.connect() as conn:
            render = db.get_render(conn, render_id)
            checks = db.get_checks(conn, render_id)
            approval = db.latest_approval(conn, render_id)

        left, right = st.columns([1, 1])
        show_image(left, render["file_path"])
        # Seul ce qui demande une action est affiché ; les contrôles conformes restent repliés
        to_review = [c for c in checks if c["status"] != "conforme"]
        passed = [c for c in checks if c["status"] == "conforme"]
        anomalies = sum(c["status"] == "anomalie" for c in checks)
        if anomalies:
            right.error(f"{anomalies} anomalie(s) : à corriger avant approbation.")
        elif to_review:
            right.info(f"Aucune anomalie. {len(to_review)} point(s) à vérifier à l'œil avant d'approuver.")
        else:
            right.success("Tous les contrôles sont conformes.")
        for c in to_review:
            right.markdown(f"{STATUS_ICON[c['status']].split()[0]} **{c['name']}** — {c['detail']}")
        with right.expander(f"✅ {len(passed)} contrôle(s) conforme(s)"):
            for c in passed:
                st.markdown(f"**{c['name']}** — {c['detail']}")

        st.divider()
        if approval:
            st.markdown(f"Dernière décision : **{approval['decision']}** par {approval['reviewer']} "
                        f"le {approval['created_at']} — {approval['comment'] or ''}")
        with st.form("decision"):
            reviewer = st.text_input("Responsable de la validation")
            comment = st.text_area("Commentaire")
            ack = st.checkbox("J'ai vérifié à l'œil les contrôles non concluants")
            c1, c2 = st.columns(2)
            approve = c1.form_submit_button("✅ Approuver", type="primary")
            reject = c2.form_submit_button("Rejeter")
        if approve or reject:
            try:
                with db.connect() as conn:
                    decide(conn, render_id, "approved" if approve else "rejected", reviewer, comment, ack)
                st.rerun()
            except ApprovalRefused as exc:
                st.error(str(exc))

        if st.button("Exporter la version approuvée"):
            try:
                with db.connect() as conn:
                    target = export_approved(conn, render_id)
                st.success(f"Exporté : {target.name}")
                st.download_button("Télécharger", Path(target).read_bytes(), file_name=target.name,
                                   mime="image/png")
            except ExportBlocked as exc:
                st.error(str(exc))

# --- 4. Historique -----------------------------------------------------------
with tab_hist:
    with db.connect() as conn:
        rows = db.list_renders(conn, brand_id)
    st.dataframe([{"date": r["created_at"], "rendu": r["id"], "brief": f"{r['brief_key']} v{r['brief_version']}",
                   "gabarit": r["template_id"], "disposition": layout_label(r["layout"]),
                   "lot": r["batch_id"] or "", "source": r["background_source"], "statut": r["status"],
                   "durée (s)": r["duration_s"], "erreur": r["error"] or ""} for r in rows],
                 width="stretch")
