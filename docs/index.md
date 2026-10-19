# Documentation des IA utilisées

Le moteur KÔMIAN s'appuie sur sept modèles d'IA. Tous tournent **en local**, dans l'environnement WSL du projet : aucun service en ligne, aucune donnée envoyée à l'extérieur, aucun coût à l'usage. Les modèles sont téléchargés une seule fois, puis restent en cache sur la machine.

| Modèle | Rôle | Licence | Taille | Document |
|---|---|---|---|---|
| Realistic Vision V5.1 rapide (LCM-LoRA fusionné, OpenVINO int8, converti sur la machine) | **Création rapide** de la scène (aperçu photoréaliste) : candidates, ajout d'un objet dans la main | CreativeML OpenRAIL-M ; LCM-LoRA sous OpenRAIL++ | 1,1 Go | [Génération d'images](generation-images.md#pourquoi-un-aperçu-en-realistic-vision-rapide) |
| Qwen3-VL 4B (OpenVINO, int4) | **Vérificateur** : le geste demandé est-il fait ? la personne est-elle habillée ? où est la main ? | Apache 2.0 | 2,9 Go | [Génération d'images](generation-images.md#boucle-de-contrôle-qualité) |
| Realistic Vision V5.1 (OpenVINO, int8, converti sur la machine) | **Version finale**, à l'approbation : rendu photographique, visages plus naturels | CreativeML OpenRAIL-M ; VAE sd-vae-ft-mse sous MIT | 1,1 Go | [Génération d'images](generation-images.md#pourquoi-realistic-vision-pour-la-version-finale) |
| Helsinki-NLP opus-mt-fr-en (MarianMT) | Traduction français → anglais des descriptions de scène | Apache 2.0 | 0,3 Go | [Traduction](traduction.md) |
| EasyOCR (modèles latins) | Relecture du texte affiché sur le visuel | Apache 2.0 | 0,1 Go | [Contrôles](controles.md) |
| YuNet (OpenCV Zoo) | Détection des visages ; qualité du visage dans la boucle de l'IA (yeux, nez, bouche) | MIT | 0,2 Mo | [Contrôles](controles.md) |
| Spectral residual | Repérage du sujet de l'image pour placer le texte | Algorithme, sans modèle | — | [Contrôles](controles.md) |

## Principe : l'IA ne produit jamais le texte ni le logo

Le modèle d'images génère **uniquement la scène**. Les textes exacts, le logo officiel, l'étiquette de série et le bandeau sont ensuite ajoutés par le compositeur, au pixel près. Les modèles d'images écrivent mal (lettres déformées, accents faux), et une charte ne tolère aucune approximation sur le texte ou le logo.

## Points d'attention sur les licences

- **Realistic Vision V5.1** est publié sous **CreativeML OpenRAIL-M**, la licence de Stable Diffusion 1.5 dont ils dérivent. L'usage commercial des images est autorisé, mais la licence interdit certains usages : contenus illégaux, trompeurs ou diffamatoires, désinformation, exploitation de personnes vulnérables, etc. Ces restrictions s'appliquent aux images produites.
- Le VAE **sd-vae-ft-mse** de Stability AI, associé à Realistic Vision, est publié sous **MIT**.
- **LCM-LoRA** (extension fusionnée dans l'aperçu rapide) est publié sous **OpenRAIL++**, de la même famille : mêmes restrictions d'usage.
- **LCM Dreamshaper v7**, l'ancien modèle d'aperçu (MIT, dérivé d'un modèle OpenRAIL-M), n'est plus utilisé depuis le 19 octobre 2026.
- **Realistic Vision** peut produire de la nudité quand la tenue n'est pas précisée. La boucle impose une tenue et la contrôle (une personne dévêtue bloque l'approbation), mais le contrôle humain avant validation reste indispensable.
- **Qwen3-VL** est publié sous **Apache 2.0** : usage commercial autorisé, sans restriction d'usage particulière.
- **Stable Diffusion 1.5**, utilisé jusqu'au 18 octobre 2026, a été retiré (voir [Génération d'images](generation-images.md#pourquoi-realistic-vision-pour-la-version-finale)).
- **À faire valider par le responsable juridique avant tout usage commercial** : ces licences, ainsi que l'éventuelle obligation de signaler qu'une image a été générée par IA, selon les règles des plateformes et du marché visé.

Chaque rendu enregistre en base le modèle, la licence, la graine et les descriptions utilisés : on peut toujours retrouver comment une image a été produite.

## Où se trouvent les modèles

| Élément | Emplacement (WSL) |
|---|---|
| Modèles Hugging Face (génération, vérificateur, traduction), et poids sources de Realistic Vision | `~/.cache/huggingface/hub` |
| Scènes générées, à leur taille de génération (départ du passage en qualité) | `data/renders/scenes/` (dans le projet, non versionné) |
| Realistic Vision converti (créé par `scripts/convert_realistic_vision.sh`) | `~/.cache/komian/models/realistic-vision-v5.1-int8-ov` |
| Cache de compilation OpenVINO | `~/.cache/komian/ov_cache` |
| Modèles EasyOCR | `~/.EasyOCR` |
| Modèle YuNet | `data/models/face_detection_yunet_2023mar.onnx` (dans le projet) |
| Choix des modèles d'images | `data/models.yaml` |

## Mesures de performance

Les temps cités dans ces documents ont été mesurés sur la machine du studio : Intel Core i7-1255U, puce graphique intégrée Iris Xe, 16 Go de mémoire, sans carte graphique dédiée. Les résultats bruts du benchmark sont dans [`benchmarks/results/`](../benchmarks/results/), et le script dans [`benchmarks/bench_models.py`](../benchmarks/bench_models.py).
