# Génération d'images

## Les deux modes proposés

| Mode | Modèle | Étapes | Temps par scène* | Rendu |
|---|---|---|---|---|
| **Rapide** (par défaut) | LCM Dreamshaper v7, OpenVINO int8 ([fiche](https://huggingface.co/OpenVINO/LCM_Dreamshaper_v7-int8-ov)) | 6 | environ 6 à 8 s | Plus doux, peau un peu lisse. Idéal pour essayer plusieurs scènes. |
| **Qualité** | Stable Diffusion 1.5, OpenVINO int8 ([fiche](https://huggingface.co/OpenVINO/stable-diffusion-v1-5-int8-ov)) | 20 | environ 45 à 50 s | Photographique. Pour la version finale. |

\* Sur la puce graphique Iris Xe, une fois le modèle chargé. Après un démarrage de l'application ou un changement de mode, la première génération recharge le modèle : environ 1 minute en mode rapide, 3 minutes en mode qualité.

Le mode se choisit dans l'onglet **Génération**, quand la source « IA locale » est sélectionnée. Un seul modèle est chargé à la fois : la mémoire de la puce graphique, partagée avec le système, ne permet pas d'en garder deux.

## Comment une scène est produite

1. La description saisie, en français ou en anglais, est traduite en anglais si nécessaire (voir [Traduction](traduction.md)).
2. Le modèle génère une image de 512 × 512 px (ou au format du gabarit, en multiples de 64).
3. L'image est recadrée et agrandie au format final (1440 × 1440 pour un post carré).
4. Le compositeur ajoute l'étiquette de série, le texte exact, le logo et le bandeau.
5. Les contrôles s'exécutent sur l'image finale (voir [Contrôles](controles.md)).

Avec l'option « trois mises en page », la scène n'est générée **qu'une fois** : les trois variantes partagent le même fond.

## Accélération OpenVINO

Le projet utilise **OpenVINO GenAI** (Intel) pour exécuter les modèles sur la puce graphique Iris Xe plutôt que sur le processeur.

| Configuration mesurée | Temps par image (512 px) |
|---|---|
| Stable Diffusion 1.5, PyTorch, processeur | 339 s |
| Stable Diffusion 1.5, OpenVINO fp16, puce graphique | 53 s |
| Stable Diffusion 1.5, OpenVINO int8, puce graphique | 43 s |
| **LCM Dreamshaper v7, OpenVINO int8, puce graphique** | **6 s** |
| LCM Dreamshaper v7, OpenVINO int8, processeur (WSL sans pilote) | 59 s |

Sous WSL, l'accès à la puce graphique exige le pilote de calcul Intel : `sudo apt install -y intel-opencl-icd libze-intel-gpu1 libze1 clinfo`. Sans lui, l'application bascule automatiquement sur le processeur et affiche un avertissement.

La bibliothèque `optimum-intel` a été écartée : elle impose une version de `huggingface-hub` incompatible avec `diffusers`.

## Écrire une bonne description de scène

Ce que le modèle réussit bien :

- les **personnes en plan moyen** (à mi-corps), qui regardent l'objectif ;
- les **ambiances** : atelier, salon, jardin, rayon de magasin ;
- les **objets simples** : rouleau, plante, arrosoir.

Ce qu'il réussit mal :

- **une action précise avec un outil**, par exemple « coupe une planche à la scie sauteuse » : l'outil est souvent faux ou absent ;
- **les mains** qui tiennent un objet ;
- **les produits précis ou de marque** ;
- **les visages petits dans l'image** (plan large).

Pour ces cas, préférez une vraie photo importée.

Structure conseillée : *qui* (âge, genre, origine, tenue) → *quoi* (une seule action simple) → *où* (décor) → *cadrage* → *lumière et style*.

> Femme noire d'une vingtaine d'années, souriante, en t-shirt blanc et salopette en jean, qui peint le mur d'un salon avec un rouleau, appartement lumineux, plan taille, regard vers l'objectif, lumière naturelle chaude, photo réaliste

N'écrivez **jamais** de texte, de slogan ou de nom de marque dans la description : ils sont ajoutés ensuite.

Pour obtenir une autre personne ou une autre composition avec la même description, **changez la graine**.

## Corrections automatiques du rendu

Pour éviter l'aspect « personnage de synthèse » (sourire forcé, trop de dents, peau plastique), constaté lors des essais :

- la traduction remplace *smiling* par *with a gentle natural smile*, et *realistic photo* par *candid photo, 35mm photograph* ;
- une liste d'éléments à exclure est transmise au modèle : texte, logo, mains déformées, aspect cartoon, rendu 3D, peau plastique, sourire exagéré, dents ou visage déformés. Elle est définie par `NEGATIVE_PROMPT` dans `komian/backgrounds.py` ;
- le modèle LCM ignore cette liste : des termes de style photographique sont alors ajoutés directement à sa description (`LCM_PHOTO_STYLE`).

Une retouche automatique des visages (régénération du visage en haute résolution) a été testée, puis écartée : le visage obtenu était d'aspect « peint », et la scène différait de celle demandée.

## Changer ou ajouter un modèle

Les modèles proposés sont déclarés dans `data/models.yaml` :

```yaml
active: lcm_ov_gpu                         # mode sélectionné par défaut
choices: [lcm_ov_gpu, sd15_ov_int8_gpu]    # modes proposés dans l'application
models:
  lcm_ov_gpu:
    label: "Rapide : LCM Dreamshaper v7 (≈ 6 s, image plus douce)"
    repo: "OpenVINO/LCM_Dreamshaper_v7-int8-ov"
    engine: openvino      # ou « diffusers » (PyTorch, processeur)
    device: GPU           # ou CPU
    lcm: true             # pas de liste d'exclusion pour ce type de modèle
    licence: "MIT"
    steps: 6
    guidance_scale: 8.0
    base_size: 512
    expected_s: 6
```

Pour ajouter un modèle :

1. Le mesurer sur la machine : `python benchmarks/bench_models.py <clé> --device GPU`. Le résultat est enregistré dans `benchmarks/results/`.
2. Vérifier sa licence.
3. Le déclarer dans `models.yaml`, puis l'ajouter à `choices`.

Les modèles **SDXL** et **FLUX.1 schnell**, prévus par l'architecture, n'ont pas été retenus sur cette machine : SDXL demande plus de 10 Go de mémoire, et FLUX.1 schnell environ 24 Go, au-delà des 16 Go disponibles.
