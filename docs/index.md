# Documentation des IA utilisées

Le moteur KÔMIAN s'appuie sur six modèles d'IA. Tous tournent **en local**, dans l'environnement WSL du projet : aucun service en ligne, aucune donnée envoyée à l'extérieur, aucun coût à l'usage. Les modèles sont téléchargés une seule fois, puis restent en cache sur la machine.

| Modèle | Rôle | Licence | Taille | Document |
|---|---|---|---|---|
| LCM Dreamshaper v7 (OpenVINO, int8) | Génération de la scène, **mode rapide** | MIT, modèle dérivé d'un modèle sous CreativeML OpenRAIL-M (voir ci-dessous) | 2,1 Go | [Génération d'images](generation-images.md) |
| Stable Diffusion 1.5 (OpenVINO, int8) | Génération de la scène, **mode qualité** | CreativeML OpenRAIL-M | 2,1 Go | [Génération d'images](generation-images.md) |
| Helsinki-NLP opus-mt-fr-en (MarianMT) | Traduction français → anglais des descriptions de scène | Apache 2.0 | 0,3 Go | [Traduction](traduction.md) |
| EasyOCR (modèles latins) | Relecture du texte affiché sur le visuel | Apache 2.0 | 0,1 Go | [Contrôles](controles.md) |
| YuNet (OpenCV Zoo) | Détection des visages | MIT | 0,2 Mo | [Contrôles](controles.md) |
| Spectral residual | Repérage du sujet de l'image pour placer le texte | Algorithme, sans modèle | — | [Contrôles](controles.md) |

## Principe : l'IA ne produit jamais le texte ni le logo

Le modèle d'images génère **uniquement la scène**. Les textes exacts, le logo officiel, l'étiquette de série et le bandeau sont ensuite ajoutés par le compositeur, au pixel près. Les modèles d'images écrivent mal (lettres déformées, accents faux), et une charte ne tolère aucune approximation sur le texte ou le logo.

## Points d'attention sur les licences

- **Stable Diffusion 1.5** et **Dreamshaper 7** sont publiés sous **CreativeML OpenRAIL-M**. L'usage commercial des images est autorisé, mais la licence interdit certains usages : contenus illégaux, trompeurs ou diffamatoires, désinformation, exploitation de personnes vulnérables, etc. Ces restrictions s'appliquent aux images produites.
- **LCM Dreamshaper v7** est publié sous **MIT**, mais il est obtenu par distillation de Dreamshaper 7 (OpenRAIL-M). Par prudence, appliquez-lui les mêmes restrictions d'usage que Stable Diffusion 1.5.
- **À faire valider par le responsable juridique avant tout usage commercial** : ces licences, ainsi que l'éventuelle obligation de signaler qu'une image a été générée par IA, selon les règles des plateformes et du marché visé.

Chaque rendu enregistre en base le modèle, la licence, la graine et les descriptions utilisés : on peut toujours retrouver comment une image a été produite.

## Où se trouvent les modèles

| Élément | Emplacement (WSL) |
|---|---|
| Modèles Hugging Face (génération, traduction) | `~/.cache/huggingface/hub` |
| Cache de compilation OpenVINO | `~/.cache/komian/ov_cache` |
| Modèles EasyOCR | `~/.EasyOCR` |
| Modèle YuNet | `data/models/face_detection_yunet_2023mar.onnx` (dans le projet) |
| Choix des modèles d'images | `data/models.yaml` |

## Mesures de performance

Les temps cités dans ces documents ont été mesurés sur la machine du studio : Intel Core i7-1255U, puce graphique intégrée Iris Xe, 16 Go de mémoire, sans carte graphique dédiée. Les résultats bruts du benchmark sont dans [`benchmarks/results/`](../benchmarks/results/), et le script dans [`benchmarks/bench_models.py`](../benchmarks/bench_models.py).
