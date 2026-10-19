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

1. **Brief** : objectif, format, accroche, texte exact, direction artistique, icônes, étiquette de série. Le brief est versionné : toute modification exige une justification.
2. **Génération** : choix d'un gabarit et d'une source de fond.
   - **Photo importée** : banque d'images libre de droits.
   - **Formes géométriques** : aplats aux couleurs de la charte.
   - **IA locale** : mode rapide (environ 8 s, LCM Dreamshaper) ou qualité (environ 50 s, Realistic Vision : visages et mains plus fiables). La description de la scène peut être saisie en français : elle est traduite automatiquement.

   Par défaut, trois mises en page sont proposées sur le même fond. Elles dégagent les visages et varient le style et la position du message. Avant le rendu, le plan de génération signale les contradictions entre le brief et la charte.
3. **Contrôle et validation** : le rapport n'affiche que les anomalies et les points à vérifier à l'œil ; les contrôles conformes sont repliés. L'approbation est refusée s'il reste une anomalie. Elle est liée à l'empreinte SHA-256 du fichier exact, et le choix d'une variante écarte automatiquement les autres.
4. **Export** : bloqué sans approbation valide pour le fichier exact.

Chaque rendu enregistre son brief, son gabarit, sa disposition et, pour l'IA, le modèle, sa licence, la graine et les descriptions saisie et traduite.

Si des fichiers de rendu sont supprimés à la main, le bouton **« Mettre à jour la base »** de la barre latérale retire les rendus orphelins. Les rendus exportés sont conservés.

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
| `data/brands/<marque>/profile.yaml` | Profil de marque, avec les points « à confirmer » |
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
- **Charte Mr.Bricolage** : version applicable au marché ivoirien, fichiers officiels du logo blanc et du logo « Maison et Jardin », règles d'usage du logo (taille minimale, zone de protection), couleurs secondaires définitives. Ces points sont listés dans `data/brands/mr_bricolage/profile.yaml`.
