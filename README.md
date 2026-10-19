# KÔMIAN : moteur de génération visuelle (MVP)

Application interne Streamlit pour le studio KÔMIAN. Elle produit des visuels publicitaires à partir d'une charte de marque et d'un brief, en exécute les contrôles de conformité, puis exige une validation humaine avant l'export.

La marque pilote est Mr.Bricolage Côte d'Ivoire, avec la série « Lundi motivation ».

Toute l'IA tourne en local, sans service en ligne ni coût à l'usage. Les modèles utilisés, leurs licences et leurs limites sont décrits dans **[docs/](docs/index.md)**.

## Lancer (WSL, Ubuntu)

Le projet tourne dans l'environnement conda `generation_visuel` de WSL, isolé des autres projets.

```bash
conda activate generation_visuel
cd /mnt/c/Users/KSOMS/Favorites/generation_de_visuel
streamlit run app.py          # puis http://localhost:8501 depuis Windows
python -m pytest              # tests automatiques
```

## Installer sur une nouvelle machine

```bash
conda create -n generation_visuel python=3.11
conda activate generation_visuel
pip install -r requirements.txt
# Accès à la puce graphique Intel depuis WSL (accélération OpenVINO) :
sudo apt install -y intel-opencl-icd libze-intel-gpu1 libze1 clinfo
# Mode qualité (Realistic Vision) : conversion unique, environ 10 minutes
bash scripts/convert_realistic_vision.sh
```

Les autres modèles d'IA se téléchargent au premier usage (environ 3 Go au total) dans `~/.cache/huggingface` et `~/.EasyOCR`. Le cache de compilation OpenVINO est dans `~/.cache/komian/ov_cache`.

La base enregistre des chemins relatifs au projet : elle fonctionne sous WSL comme sous Windows.

## Parcours

L'interface ne montre que ce qui sert à créer et valider un visuel. Les détails techniques (modèle, moteur, graine, identifiants) restent enregistrés en base, mais ne sont pas affichés. En cas d'échec, l'utilisateur voit un message simple et les détails sont repliés sous « Détails pour l'administrateur ».

1. **✏️ Brief** : le message (texte exact, accroche), le contexte (série, objectif, format, réseaux) et la mise en forme (direction artistique, logo, icônes, éléments à éviter). Le brief est versionné : toute modification exige d'indiquer ce qui change.
2. **🎨 Création** : choix de la mise en page et de l'image de fond.
   - **📷 Ma photo** : photo libre de droits importée.
   - **🔷 Formes aux couleurs de la marque** : aplats aux couleurs de la charte.
   - **✨ Image créée par l'IA** : mode ⚡ Rapide (environ 6 s, LCM Dreamshaper) pour essayer des idées, ou ✨ Qualité (environ 50 s, Realistic Vision : visages et mains plus fiables) pour la version finale. La scène peut être décrite en français.

   Par défaut, trois mises en page sont proposées sur le même fond. Elles dégagent les visages et varient le style et la position du message. Les contradictions entre le brief et la charte sont signalées avant la création.
3. **✅ Validation** : choix de la mise en page, puis rapport limité aux points à corriger et à vérifier à l'œil ; les contrôles réussis sont repliés. L'approbation est impossible s'il reste un point à corriger. Elle est liée à l'empreinte SHA-256 du fichier exact, et le choix d'une mise en page écarte automatiquement les autres. Une fois le visuel approuvé, **« Préparer le fichier final »** l'exporte et propose son téléchargement.
4. **🗂️ Galerie** : tous les visuels de la marque, filtrables par statut (en attente, approuvés, rejetés). « Ouvrir » affiche le visuel dans l'onglet Validation.

Chaque visuel enregistre son brief, sa mise en page et, pour l'IA, le modèle, sa licence, la graine et les descriptions saisie et traduite.

Si des images sont supprimées à la main du dossier, le bouton **« Retirer de la galerie »** de la barre latérale nettoie la galerie. Les visuels exportés restent dans l'historique.

## Organisation

| Chemin | Rôle |
|---|---|
| `app.py` | Interface Streamlit |
| `komian/compose.py` | Gabarits : textes exacts, étiquette de série, panneaux, bandeau, logo, icônes |
| `komian/backgrounds.py` | Sources de fond : photo, formes géométriques, IA locale (OpenVINO / PyTorch), liste d'exclusion |
| `komian/translate.py` | Traduction français → anglais des descriptions de scène, avec glossaire métier |
| `komian/checks.py` | Contrôles mesurés sur l'image produite |
| `komian/ocr.py`, `komian/saliency.py` | Relecture OCR, détection de visages, repérage du sujet |
| `komian/workflow.py` | Plan, rendu, variantes, validation, export |
| `komian/db.py`, `komian/models.py` | Base SQLite et modèles de données (Pydantic) |
| `data/brands/<marque>/profile.yaml` | Profil de marque, décisions validées et points éventuellement « à confirmer » |
| `data/models.yaml` | Modèles d'images proposés et mode par défaut |
| `data/renders/pending/`, `data/exports/approved/` | Rendus en attente et exports approuvés |
| `benchmarks/` | Script et résultats des mesures de performance des modèles |
| `scripts/convert_realistic_vision.sh` | Conversion unique de Realistic Vision au format OpenVINO int8 |
| `docs/` | Documentation des IA utilisées ([index](docs/index.md)) |
| `tests/` | Tests automatiques (pytest) |

## Documentation

- [Vue d'ensemble des IA et licences](docs/index.md)
- [Génération d'images](docs/generation-images.md) : modes, pourquoi Realistic Vision, performances, écrire une description de scène, ajouter un modèle
- [Traduction](docs/traduction.md) : traducteur local et glossaire métier
- [Contrôles](docs/controles.md) : OCR, détection de visages, repérage du sujet

## Points ouverts

- **Licences des modèles d'images**, et obligation éventuelle d'indiquer qu'une image a été générée par IA : à faire valider par le juridique avant usage commercial (voir [docs/index.md](docs/index.md)).
## Décisions de charte (Mr.Bricolage)

Les points ouverts de la charte ont été validés le 19 octobre 2026. Le fonctionnement existant est accepté tel quel :

- le guide de 2017 s'applique au marché ivoirien ;
- la mention « Maison et Jardin » recomposée en Ubuntu et le logo blanc dérivé automatiquement sont acceptés ;
- la taille, la position et les fonds du logo des gabarits actuels sont acceptés ;
- les six couleurs secondaires sont définitives ;
- le rouge de référence reste **#EB0029**, malgré les écarts mesurés sur le fichier du logo et les visuels déjà livrés ;
- les aplats semi-transparents sur photo sont autorisés.

Le détail figure en tête de `data/brands/mr_bricolage/profile.yaml`.
