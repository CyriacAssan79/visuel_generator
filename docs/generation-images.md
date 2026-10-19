# Génération d'images

## Les deux modes proposés

| Mode | Modèle | Étapes | Temps par scène* | Rendu |
|---|---|---|---|---|
| **Rapide** (par défaut) | LCM Dreamshaper v7, OpenVINO int8 ([fiche](https://huggingface.co/OpenVINO/LCM_Dreamshaper_v7-int8-ov)) | 6 | environ 6 à 8 s | Plus doux, peau un peu lisse. Idéal pour essayer plusieurs scènes. |
| **Qualité** | Realistic Vision V5.1, OpenVINO int8, converti sur la machine ([fiche](https://huggingface.co/SG161222/Realistic_Vision_V5.1_noVAE)) | 25 | environ 45 à 60 s | Photographique. Visages et mains nettement plus fiables. Pour la version finale. |

\* Sur la puce graphique Iris Xe, une fois le modèle chargé. Le temps varie d'une génération à l'autre, car la puce partage sa mémoire et sa chaleur avec le processeur. Après un démarrage de l'application ou un changement de mode, la première génération recharge le modèle : environ 1 minute en mode rapide, 2 à 3 minutes en mode qualité.

Le mode se choisit dans l'onglet **Génération**, quand la source « IA locale » est sélectionnée. Un seul modèle est chargé à la fois : la mémoire de la puce graphique, partagée avec le système, ne permet pas d'en garder deux.

## Comment une scène est produite

1. La description saisie, en français ou en anglais, est traduite en anglais si nécessaire (voir [Traduction](traduction.md)).
2. Le modèle génère une image de 512 × 512 px (ou au format du gabarit, en multiples de 64).
3. L'image est recadrée et agrandie au format final (1440 × 1440 pour un post carré).
4. Le compositeur ajoute l'étiquette de série, le texte exact, le logo et le bandeau.
5. Les contrôles s'exécutent sur l'image finale (voir [Contrôles](controles.md)).

Avec l'option « trois mises en page », la scène n'est générée **qu'une fois** : les trois variantes partagent le même fond.

## Pourquoi Realistic Vision en mode qualité

### Le problème

Jusqu'au 18 octobre 2026, le mode qualité utilisait **Stable Diffusion 1.5**. Sur les visuels avec des personnes, le gabarit habituel de Mr.Bricolage, les visages étaient souvent ratés (bouche tordue, regard flou, yeux asymétriques), tout comme les mains (doigts fondus, objets tenus de travers). SD 1.5 est un modèle généraliste de 2022, entraîné sur des images de toute nature et de qualité inégale. L'anatomie humaine est l'un de ses points faibles connus.

### Ce qu'est Realistic Vision

Realistic Vision V5.1 n'est pas un nouveau type de modèle : c'est **Stable Diffusion 1.5 réentraîné sur des photographies**, par son auteur SG161222. L'architecture est identique, seuls les poids changent. Il en découle trois conséquences :

- **Même coût sur la machine** : environ 1,1 Go sur disque une fois converti, pic de mémoire de 1,2 à 1,5 Go, temps comparable à SD 1.5.
- **Rendu photographique** : peau, regard, expressions, lumière.
- **Anatomie plus fiable** : visages et mains. L'amélioration est nette, mais les défauts ne disparaissent pas entièrement.

### Le test qui a motivé le choix

Les deux modèles ont été comparés le 18 octobre 2026 sur la puce graphique Iris Xe, avec les mêmes descriptions et les mêmes graines. Il y avait quatre scènes avec des personnes (peintre en salopette, vendeur en rayon, couple au jardin, homme âgé à l'atelier) et deux graines chacune.

| Critère | Stable Diffusion 1.5 | Realistic Vision V5.1 |
|---|---|---|
| Visages | Bouche ou yeux déformés sur plusieurs images, regard flou | Yeux symétriques, sourire naturel, grain de peau réel |
| Mains | Informes dès qu'elles tiennent un objet | Crédibles quand elles sont jointes ou tiennent un objet simple ; encore imparfaites parfois |
| Objets et décor | Arrosoir méconnaissable, atelier générique | Arrosoir reconnaissable, mur perforé avec outils |
| Temps par scène (512 px) | 43 s (20 étapes) | 45 à 60 s (25 étapes) |

Realistic Vision l'emporte sur tous les critères de qualité, pour un temps à peine supérieur. SD 1.5 a donc été **retiré** de l'application et de la machine. Ses mesures restent consultables dans `benchmarks/results/`.

### Réglages retenus

| Réglage | Valeur | Raison |
|---|---|---|
| Version | **V5.1** | Version stable et la plus utilisée. La V6.0 est encore en bêta selon son auteur, et elle vise des résolutions de 896 px, environ trois fois plus lentes sur cette machine. |
| VAE (décodeur d'image) | `stabilityai/sd-vae-ft-mse` (MIT) | Recommandé par l'auteur : sans lui, couleurs délavées et artefacts. |
| Planificateur | Euler Ancestral | Recommandé par l'auteur et pris en charge par OpenVINO. Le planificateur d'origine du dépôt (DEIS) est refusé par OpenVINO. |
| Étapes | 25 | Minimum conseillé par l'auteur. 20 étapes donnent un rendu équivalent, pour un gain de temps faible (~2 s). |
| Guidage | 5 | Fourchette conseillée : 3,5 à 7. À 7, le rendu est un peu plus contrasté, sans gain sur les visages. |
| Liste d'exclusion | Voir plus bas | Inclut la **nudité** : sans tenue précisée, le modèle a produit des personnes torse nu. |

### Ce qu'il ne règle pas

- **Les actions précises avec un outil** : sur toutes les générations du test, la peintre ne tient jamais son rouleau. Ce défaut est commun aux deux modèles.
- **Les petits visages** : l'image est générée en 512 px puis agrandie jusqu'à 1440 px. Un visage petit dans l'image reste donc peu détaillé, quel que soit le modèle.
- **Le mode rapide** (LCM Dreamshaper) ne change pas : c'est un autre modèle.

### Installation sur une nouvelle machine

Aucune version OpenVINO officielle de Realistic Vision n'existe. Il en existe des conversions publiées par des tiers, que nous n'avons pas retenues, faute de provenance vérifiable. Le modèle est donc converti **une seule fois** sur la machine, à partir des poids officiels :

```bash
bash scripts/convert_realistic_vision.sh
```

Le script télécharge les poids officiels (environ 4 Go), installe la conversion dans un environnement conda temporaire (`rv_convert`, supprimé à la fin), puis écrit le modèle int8 dans `~/.cache/komian/models/realistic-vision-v5.1-int8-ov`. Comptez une dizaine de minutes. Un environnement séparé est nécessaire, car l'outil de conversion (`optimum-intel`) est incompatible avec `diffusers`.

Tant que la conversion n'a pas été faite, le mode qualité affiche une erreur explicite qui indique le script à lancer.

## Accélération OpenVINO

Le projet utilise **OpenVINO GenAI** (Intel) pour exécuter les modèles sur la puce graphique Iris Xe plutôt que sur le processeur.

| Configuration mesurée | Temps par image (512 px) |
|---|---|
| Stable Diffusion 1.5, PyTorch, processeur *(retiré)* | 339 s |
| Stable Diffusion 1.5, OpenVINO fp16, puce graphique *(retiré)* | 53 s |
| Stable Diffusion 1.5, OpenVINO int8, puce graphique *(retiré)* | 43 s |
| **Realistic Vision V5.1, OpenVINO int8, puce graphique, 25 étapes** | **45 à 60 s** |
| **LCM Dreamshaper v7, OpenVINO int8, puce graphique** | **6 s** |
| LCM Dreamshaper v7, OpenVINO int8, processeur (WSL sans pilote) | 59 s |

Sous WSL, l'accès à la puce graphique exige le pilote de calcul Intel : `sudo apt install -y intel-opencl-icd libze-intel-gpu1 libze1 clinfo`. Sans lui, l'application bascule automatiquement sur le processeur et affiche un avertissement.

La bibliothèque `optimum-intel` n'est pas installée dans l'environnement du projet, car elle impose une version de `huggingface-hub` incompatible avec `diffusers`. Elle ne sert qu'à la conversion, dans un environnement temporaire.

## Écrire une bonne description de scène

Ce que le modèle réussit bien :

- les **personnes en plan moyen** (à mi-corps), qui regardent l'objectif ;
- les **ambiances** : atelier, salon, jardin, rayon de magasin ;
- les **objets simples** : plante, arrosoir, tablier.

Ce qu'il réussit mal :

- **une action précise avec un outil**, par exemple « peint le mur avec un rouleau » ou « coupe une planche à la scie sauteuse » : l'outil est souvent faux ou absent ;
- **les mains** qui manipulent un outil (les mains jointes ou tenant un objet simple passent mieux) ;
- **les produits précis ou de marque** ;
- **les visages petits dans l'image** (plan large).

Pour ces cas, préférez une vraie photo importée.

Structure conseillée : *qui* (âge, genre, origine, **tenue**) → *quoi* (une seule action simple) → *où* (décor) → *cadrage* → *lumière et style*. Précisez toujours la tenue (« en chemise rouge », « en t-shirt blanc ») : c'est le moyen le plus sûr d'obtenir une personne habillée comme prévu.

> Femme noire d'une vingtaine d'années, souriante, en t-shirt blanc et salopette en jean, qui peint le mur d'un salon avec un rouleau, appartement lumineux, plan taille, regard vers l'objectif, lumière naturelle chaude, photo réaliste

Restez concis : le modèle ne lit qu'environ 75 mots-clés (jetons). Au-delà, la fin de la description est ignorée.

N'écrivez **jamais** de texte, de slogan ou de nom de marque dans la description : ils sont ajoutés ensuite.

Pour obtenir une autre personne ou une autre composition avec la même description, **changez la graine**.

## Corrections automatiques du rendu

Pour éviter l'aspect « personnage de synthèse » (sourire forcé, trop de dents, peau plastique), constaté lors des essais :

- la traduction remplace *smiling* par *with a gentle natural smile*, et *realistic photo* par *candid photo, 35mm photograph* ;
- une liste d'éléments à exclure est transmise au modèle. Elle est définie par `NEGATIVE_PROMPT` dans `komian/backgrounds.py`, par ordre de priorité :
  1. texte, logo et enseignes (ajoutés ensuite par le compositeur) ;
  2. nudité (`nsfw, nude, shirtless`) ;
  3. aspect de synthèse : cartoon, rendu 3D, poupée, peau plastique, sourire exagéré, trop de dents ;
  4. défauts d'anatomie, repris de la liste recommandée par l'auteur de Realistic Vision : visage et iris déformés, yeux asymétriques, mains mutées, doigts en trop ou fondus, membres en trop ;
  5. flou et basse qualité.
- cette liste tient en **70 jetons**. L'encodeur de texte n'en lit que 75 et ignore la suite. Toute modification doit respecter cette limite, en gardant les éléments importants en tête de liste ;
- le modèle LCM ignore cette liste : des termes de style photographique sont alors ajoutés directement à sa description (`LCM_PHOTO_STYLE`).

Une retouche automatique des visages (régénération du visage en haute résolution) a été testée avec SD 1.5, puis écartée : le visage obtenu était d'aspect « peint », et la scène différait de celle demandée.

## Changer ou ajouter un modèle

Les modèles proposés sont déclarés dans `data/models.yaml` :

```yaml
active: lcm_ov_gpu                         # mode sélectionné par défaut
choices: [lcm_ov_gpu, rv51_ov_int8_gpu]    # modes proposés dans l'application
models:
  rv51_ov_int8_gpu:
    label: "Qualité : Realistic Vision V5.1 (≈ 50 s, visages et mains plus fiables)"
    repo: "SG161222/Realistic_Vision_V5.1_noVAE"                  # dépôt source (traçabilité)
    path: "~/.cache/komian/models/realistic-vision-v5.1-int8-ov"  # modèle converti sur la machine
    convert_script: "scripts/convert_realistic_vision.sh"
    engine: openvino      # ou « diffusers » (PyTorch, processeur)
    device: GPU           # ou CPU
    scheduler: EULER_ANCESTRAL_DISCRETE   # facultatif : planificateur imposé
    licence: "CreativeML OpenRAIL-M"
    steps: 25
    guidance_scale: 5.0
    base_size: 512
    expected_s: 50
```

Sans `path`, le modèle est téléchargé depuis Hugging Face (`repo`) au premier usage, comme LCM Dreamshaper. Pour un modèle de type LCM, ajoutez `lcm: true` : la liste d'exclusion n'est alors pas utilisée.

Pour ajouter un modèle :

1. Le mesurer sur la machine, sur une scène avec personne : `python benchmarks/bench_models.py <clé> --device GPU --scene personne`. Le résultat est enregistré dans `benchmarks/results/`.
2. Vérifier sa licence.
3. Le déclarer dans `models.yaml`, puis l'ajouter à `choices`.

Les modèles **SDXL** et **FLUX.1 schnell**, prévus par l'architecture, n'ont pas été retenus sur cette machine : SDXL demande plus de 10 Go de mémoire, et FLUX.1 schnell environ 24 Go, au-delà des 16 Go disponibles.
