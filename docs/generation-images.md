# Génération d'images

## Vue d'ensemble

La création d'une scène par l'IA enchaîne trois modèles, tous locaux :

| Rôle | Modèle | Quand | Temps* |
|---|---|---|---|
| **Création rapide** | Realistic Vision V5.1 avec LCM-LoRA fusionné, OpenVINO int8, converti sur la machine ([LCM-LoRA](https://huggingface.co/latent-consistency/lcm-lora-sdv1-5)) | À la création : candidates et ajout d'un objet dans la main | ~6 s par image |
| **Vérificateur** | Qwen3-VL 4B, OpenVINO int4 ([fiche](https://huggingface.co/OpenVINO/Qwen3-VL-4B-Instruct-int4-ov)) | À la création et à l'approbation : le geste demandé est-il fait ? où est la main ? | ~3 s par question |
| **Version finale** | Realistic Vision V5.1, OpenVINO int8, converti sur la machine ([fiche](https://huggingface.co/SG161222/Realistic_Vision_V5.1_noVAE)) | À l'approbation : passage en haute qualité | ~20 à 45 s |

\* Sur la puce graphique Iris Xe, une fois les modèles chargés. La première création après un démarrage charge les modèles : 2 à 3 minutes de plus.

L'utilisateur ne choisit plus de mode : il décrit la scène, l'IA la crée et la contrôle **en silence**, puis la version finale en haute qualité est produite **au moment de l'approbation**.

### Pourquoi un aperçu en Realistic Vision rapide

Jusqu'au 19 octobre 2026, l'aperçu venait de **LCM Dreamshaper**, un modèle au rendu à mi-chemin entre la photo et l'illustration. En 6 étapes, il lissait la peau et les matières : l'aperçu paraissait « peint », « carton ». Or c'est l'aperçu que l'utilisateur juge.

L'aperçu vient désormais de **Realistic Vision lui-même**, rendu rapide par l'extension **LCM-LoRA** (OpenRAIL++), qui permet de générer en 4 à 8 étapes. L'extension est **fusionnée dans les poids** une fois pour toutes, à la conversion (`scripts/convert_realistic_vision_lcm.sh`). OpenVINO GenAI 2026.4 échoue à l'appliquer à la volée, mais un modèle fusionné est un modèle ordinaire.

| Comparatif (mêmes scènes, mêmes graines) | Rendu | Temps par image |
|---|---|---|
| LCM Dreamshaper, 6 étapes (ancien) | Peint, peau lisse | 10 à 15 s* |
| **Realistic Vision rapide, 6 étapes, sans guidage (retenu)** | **Photographique, peau et lumière naturelles** | **6 s** |
| Realistic Vision rapide, 8 étapes, guidage 1,5 | Photographique, un peu plus contrasté | 13 s |

\* Mesure du 19 octobre ; 6 à 8 s lors des essais précédents.

Comme l'aperçu et la version finale partent du même modèle, le passage en qualité modifie moins l'image.

**Contrepartie : la nudité.** Sans guidage, la liste d'exclusion n'agit pas, et même avec un guidage de 1,5, un prompt sans tenue précisée (« portrait d'un homme âgé dans un atelier ») a donné **3 hommes torse nu sur 4**. Deux garde-fous ont été ajoutés à la boucle :
1. **Tenue imposée** : si la description parle d'une personne sans mentionner de vêtement, « wearing a casual shirt, fully clothed » est ajouté (4 images habillées sur 4 au même essai) ;
2. **Contrôle de tenue** par le vérificateur, sur chaque candidate et sur la version finale : « La personne est-elle torse nu ? » (8 réponses justes sur 8 au banc d'essai). Une candidate dévêtue est éliminée. Une version finale dévêtue est bloquée par une **anomalie**, ce qui empêche l'approbation.

## Comment une scène est produite

1. La description saisie, en français ou en anglais, est traduite en anglais si nécessaire (voir [Traduction](traduction.md)).
2. La **boucle de contrôle qualité** (ci-dessous) produit la scène retenue, à la taille de génération du format : 512 × 512 (carré), 448 × 576 (portrait) ou 384 × 704 (story). La surface est la même pour tous les formats, donc le coût aussi.
3. La scène est recadrée et agrandie au format final (1440 × 1440 pour un post carré). Elle est aussi enregistrée à sa taille de génération, pour le passage en qualité.
4. Le compositeur ajoute l'étiquette de série, le texte exact, le logo et le bandeau. Avec l'option « trois mises en page », la scène n'est créée **qu'une fois** : les trois variantes partagent le même fond.
5. Les contrôles s'exécutent sur l'image finale (voir [Contrôles](controles.md)), dont deux nouveaux : **Action demandée** et **Visage**.
6. À l'**approbation**, la version finale est créée en haute qualité (voir plus bas).

## Boucle de contrôle qualité

### Pourquoi

Les modèles d'images ratent souvent les visages et, plus encore, **les gestes avec un objet** : une personne censée percer un mur tient un objet indéfini, ou rien du tout. Plutôt que de laisser l'utilisateur relancer jusqu'à obtenir une image correcte, l'IA contrôle elle-même son résultat et corrige ce qui peut l'être, dans un budget de **1 min 30**.

### Déroulé, à la création

1. **Préparation de la description** : « image réaliste » est remplacé par un style photographique (ce terme pousse les modèles vers un rendu 3D), et une tenue est imposée si aucune n'est précisée.
2. **Gabarit d'action** : l'objet tenu est reconnu dans la description (perceuse, tournevis, arrosoir, tuyau d'arrosage, carton, rouleau, pinceau, marteau, scie, mètre ruban, pelle ; tondeuse, brouette et échelle sans ajout possible). Le geste est placé en tête de la description (« holding a cordless power drill in the hand pressed against the wall… », vue de trois quarts), et « regarde l'objectif » est retiré, car il contredit le geste. Une question de contrôle est préparée. Sans objet reconnu, seul le visage est contrôlé.
3. **Jusqu'à 3 candidates** en mode rapide. Pour chacune :
   - **contrôle du visage** (détecteur YuNet, déjà utilisé pour les contrôles) : position des yeux, du nez et des coins de la bouche, taille du visage (au moins 48 px), netteté, confiance du détecteur. Un visage raté élimine la candidate sans autre question ;
   - **contrôle de la tenue** par le vérificateur : une personne torse nu élimine la candidate ;
   - **contrôle de l'action** par le vérificateur : « La personne perce-t-elle le mur avec une perceuse tenue en main ? ». Seul un « oui » explicite compte.

   La boucle s'arrête à la première candidate qui passe les trois contrôles.
4. **Si aucune ne fait l'action** : le vérificateur **localise la main** de la meilleure candidate, puis l'objet est **ajouté dans la main** par retouche de cette zone seulement (2 essais, ~8 s chacun), et l'action est revérifiée.
5. La meilleure scène est retenue, avec un **rapport** enregistré dans le visuel : nombre de candidates, objet ajouté ou non, action vérifiée ou non, tenue, état du visage.
6. Pendant que l'utilisateur regarde son visuel, Realistic Vision (version complète) est **préchargé en arrière-plan** pour l'approbation.

Si le budget est atteint sans succès, la meilleure image est livrée quand même. Le contrôle **Action demandée** indique alors : « L'action demandée n'apparaît pas : relancez ou utilisez une photo ». Rien n'est caché au valideur.

### Déroulé, à l'approbation

1. Les règles habituelles s'appliquent **sur l'aperçu** : aucune anomalie, et les points non concluants doivent avoir été vérifiés à l'œil.
2. La scène retenue passe en **haute qualité** : Realistic Vision redessine 40 % de l'image, ce qui conserve la composition et le geste et rend les visages plus naturels.
3. La **même mise en page** est recomposée, puis **tous les contrôles** sont relancés, dont le visage et l'action.
4. Si la version finale reste conforme, l'**approbation est enregistrée sur ce fichier final**, avec la mention « Approuvé sur l'aperçu rapide ; version qualité générée automatiquement ». L'aperçu est classé comme remplacé, et seul le fichier final peut être exporté.
5. Si la version finale présente une anomalie ou un **nouveau** point à vérifier (par exemple l'action perdue au passage), elle n'est **pas** approuvée : elle reste en attente, avec la raison affichée.
6. Le valideur voit aussitôt la version finale et peut **annuler l'approbation** : elle est alors rejetée, et l'aperçu revient en attente. Une nouvelle approbation recrée une version finale avec une autre graine.

### Mesures (banc d'essai du 19 octobre 2026)

| Scène | Déroulé | Création | Action vérifiée à la fin |
|---|---|---|---|
| Porter un carton | 1re candidate retenue | 9 s | ✅ |
| Arroser des plantes | 2e candidate retenue | 17 s | ✅ |
| Percer un mur | 3 candidates sans perceuse au mur, puis perceuse ajoutée dans la main | ~70 s | ✅ |
| Peindre au rouleau | 3 candidates et 2 ajouts d'objet rejetés (éponge ou pinceau au lieu du rouleau) | 50 s | ❌ (correctement signalé) |

Approbation : 20 à 45 s pour le passage en qualité si Realistic Vision a fini de se précharger. Sinon, l'échange de modèles ajoute 40 à 100 s.

Vérificateur : 94 % d'accord avec un jugement humain sur 32 images, **aucun faux « oui »** sur 19 échecs et 32 questions pièges. Les modèles plus petits essayés (InternVL2 1B et 2B) répondaient « oui » trop facilement (59 % et 75 % d'accord).

### Limites

- **Le rouleau de peinture** est un objet que ce modèle ne sait pas dessiner : l'action reste signalée ⚠️. Utilisez une vraie photo.
- **La mémoire** : sous WSL, la puce graphique puise dans la mémoire donnée à WSL (~8 Go). Les trois modèles ne tiennent pas ensemble : le modèle rapide et le modèle qualité alternent, d'où le préchargement. Si l'on enchaîne une approbation puis une nouvelle création, la création attend le retour du modèle rapide (40 à 100 s).
- **Le faux texte** sur les objets (cartons) n'est pas détecté par la boucle : il reste à vérifier à l'œil, comme l'indique le contrôle « Image générée par IA ».

## Pourquoi Realistic Vision pour la version finale

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

- **Les actions précises avec un outil** : sur toutes les générations du test, la peintre ne tient jamais son rouleau. Ce défaut est commun aux deux modèles. C'est ce qui a motivé la [boucle de contrôle qualité](#boucle-de-contrôle-qualité).
- **Les petits visages** : l'image est générée en 512 px puis agrandie jusqu'à 1440 px. Un visage petit dans l'image reste donc peu détaillé, quel que soit le modèle.
- **Les petits défauts de l'aperçu** : l'aperçu est produit en 6 étapes. La version complète, en 25 étapes, n'intervient qu'à l'approbation.

### Installation sur une nouvelle machine

Aucune version OpenVINO officielle de Realistic Vision n'existe. Il en existe des conversions publiées par des tiers, que nous n'avons pas retenues, faute de provenance vérifiable. Le modèle est donc converti **une seule fois** sur la machine, à partir des poids officiels :

```bash
bash scripts/convert_realistic_vision.sh
```

Le script télécharge les poids officiels (environ 4 Go), installe la conversion dans un environnement conda temporaire (`rv_convert`, supprimé à la fin), puis écrit le modèle int8 dans `~/.cache/komian/models/realistic-vision-v5.1-int8-ov`. Comptez une dizaine de minutes. Un environnement séparé est nécessaire, car l'outil de conversion (`optimum-intel`) est incompatible avec `diffusers`.

Tant que la conversion n'a pas été faite, l'approbation d'un visuel créé par l'IA affiche une erreur explicite qui indique le script à lancer, et l'aperçu reste en attente.

## Accélération OpenVINO

Le projet utilise **OpenVINO GenAI** (Intel) pour exécuter les modèles sur la puce graphique Iris Xe plutôt que sur le processeur.

| Configuration mesurée | Temps par image (512 px) |
|---|---|
| Stable Diffusion 1.5, PyTorch, processeur *(retiré)* | 339 s |
| Stable Diffusion 1.5, OpenVINO fp16, puce graphique *(retiré)* | 53 s |
| Stable Diffusion 1.5, OpenVINO int8, puce graphique *(retiré)* | 43 s |
| Realistic Vision V5.1, OpenVINO int8, puce graphique, 25 étapes, image complète | 45 à 60 s |
| **Realistic Vision V5.1, passage en qualité (40 % de l'image redessinée)** | **20 à 45 s** |
| **Realistic Vision rapide (LCM-LoRA fusionné), 6 étapes, aperçu** | **6 s** |
| **Realistic Vision rapide, retouche de la zone de la main** | **~8 s** |
| LCM Dreamshaper v7, OpenVINO int8, puce graphique *(ancien aperçu)* | 6 à 15 s |
| **Qwen3-VL 4B, OpenVINO int4, puce graphique, une question** | **~3 s** |
| LCM Dreamshaper v7, OpenVINO int8, processeur (WSL sans pilote) | 59 s |

Sous WSL, l'accès à la puce graphique exige le pilote de calcul Intel : `sudo apt install -y intel-opencl-icd libze-intel-gpu1 libze1 clinfo`. Sans lui, l'application bascule automatiquement sur le processeur et affiche un avertissement.

La bibliothèque `optimum-intel` n'est pas installée dans l'environnement du projet, car elle impose une version de `huggingface-hub` incompatible avec `diffusers`. Elle ne sert qu'à la conversion, dans un environnement temporaire.

## Écrire une bonne description de scène

Ce que le modèle réussit bien :

- les **personnes en plan moyen** (à mi-corps), qui regardent l'objectif ;
- les **ambiances** : atelier, salon, jardin, rayon de magasin ;
- les **objets simples** : plante, arrosoir, tablier.

Ce qu'il réussit mal :

- **une action précise avec un outil** : l'outil est souvent faux ou absent. La boucle de contrôle le vérifie et l'ajoute dans la main si besoin. Ça fonctionne pour la perceuse ou l'arrosoir, mais pas pour le rouleau de peinture, que le modèle ne sait pas dessiner ;
- **les mains** qui manipulent un outil (les mains jointes ou tenant un objet simple passent mieux) ;
- **les produits précis ou de marque** ;
- **les visages petits dans l'image** (plan large).

Pour ces cas, préférez une vraie photo importée.

Structure conseillée : *qui* (âge, genre, origine, **tenue**) → *quoi* (une seule action simple) → *où* (décor) → *cadrage* → *lumière et style*. Précisez toujours la tenue (« en chemise rouge », « en t-shirt blanc ») : c'est le moyen le plus sûr d'obtenir une personne habillée comme prévu.

**Nommez l'outil tenu** (« avec une perceuse », « avec un arrosoir ») : c'est lui que la boucle reconnaît pour vérifier le geste et, si besoin, ajouter l'objet dans la main.

> Femme noire d'une vingtaine d'années, souriante, en t-shirt blanc et salopette en jean, qui peint le mur d'un salon avec un rouleau, appartement lumineux, plan taille, regard vers l'objectif, lumière naturelle chaude, photo réaliste

Restez concis : le modèle ne lit qu'environ 75 mots-clés (jetons). Au-delà, la fin de la description est ignorée.

N'écrivez **jamais** de texte, de slogan ou de nom de marque dans la description : ils sont ajoutés ensuite.

Pour obtenir une autre personne ou une autre composition avec la même description, **relancez la création** : chaque création part d'une nouvelle graine, enregistrée avec le visuel.

## Corrections automatiques du rendu

Pour éviter l'aspect « personnage de synthèse » (sourire forcé, trop de dents, peau plastique), constaté lors des essais :

- la traduction remplace *smiling* par *with a gentle natural smile*, et *realistic photo* par *candid photo, 35mm photograph* ;
- une liste d'éléments à exclure est transmise au modèle. Elle est utilisée au passage en qualité, et définie par `NEGATIVE_PROMPT` dans `komian/quality_loop.py`, par ordre de priorité :
  1. texte, logo et enseignes (ajoutés ensuite par le compositeur) ;
  2. nudité (`nsfw, nude, shirtless`) ;
  3. aspect de synthèse : cartoon, rendu 3D, poupée, peau plastique, sourire exagéré, trop de dents ;
  4. défauts d'anatomie, repris de la liste recommandée par l'auteur de Realistic Vision : visage et iris déformés, yeux asymétriques, mains mutées, doigts en trop ou fondus, membres en trop ;
  5. flou et basse qualité.
- cette liste tient en **70 jetons**. L'encodeur de texte n'en lit que 75 et ignore la suite. Toute modification doit respecter cette limite, en gardant les éléments importants en tête de liste ;
- le modèle rapide (LCM) ignore cette liste : des termes de style photographique sont ajoutés directement à sa description (`LCM_PHOTO_STYLE`).

Une retouche automatique des visages (régénération du visage en haute résolution) a été testée avec SD 1.5, puis écartée : le visage obtenu était d'aspect « peint », et la scène différait de celle demandée.

## Changer ou ajouter un modèle

Les modèles et les réglages de la boucle sont déclarés dans `data/models.yaml` :

```yaml
loop:
  fast: lcm_ov_gpu            # création rapide (candidates, ajout d'objet)
  quality: rv51_ov_int8_gpu   # version finale, à l'approbation
  verifier: qwen3vl_4b_gpu    # contrôle de l'action, localisation de la main
  budget_s: 90                # temps maximal de la boucle à la création
  max_candidates: 3
  object_attempts: 2
  quality_strength: 0.4       # part de l'image redessinée au passage en qualité
  area: 262144                # surface générée : 512 × 512, répartie selon le format
models:
  rv51_ov_int8_gpu:
    label: "Realistic Vision V5.1"
    repo: "SG161222/Realistic_Vision_V5.1_noVAE"                  # dépôt source (traçabilité)
    path: "~/.cache/komian/models/realistic-vision-v5.1-int8-ov"  # modèle converti sur la machine
    convert_script: "scripts/convert_realistic_vision.sh"
    device: GPU           # ou CPU
    scheduler: EULER_ANCESTRAL_DISCRETE   # facultatif : planificateur imposé
    licence: "CreativeML OpenRAIL-M"
    steps: 25
    guidance_scale: 5.0
```

Sans `path`, le modèle est téléchargé depuis Hugging Face (`repo`) au premier usage, comme Qwen3-VL.

Pour remplacer un modèle :

1. Le mesurer sur la machine, sur une scène avec personne : `python benchmarks/bench_models.py <clé> --device GPU --scene personne`. Le résultat est enregistré dans `benchmarks/results/`.
2. Vérifier sa licence.
3. Le déclarer dans `models.yaml`, puis l'affecter au rôle voulu dans `loop`.
4. Pour un vérificateur, refaire l'essai de fiabilité : il ne doit pas répondre « oui » à une image où l'action est absente.
5. Vérifier que la mémoire suffit : le vérificateur doit tenir à côté de chacun des deux modèles d'images.

Les modèles **SDXL** et **FLUX.1 schnell**, prévus par l'architecture, n'ont pas été retenus sur cette machine : SDXL demande plus de 10 Go de mémoire, et FLUX.1 schnell environ 24 Go, au-delà des 16 Go disponibles.
