# IA utilisées pour les contrôles et la mise en page

Ces outils n'interviennent pas dans la création de l'image. Ils servent à **vérifier** le visuel et à **placer** le message au bon endroit.

## Relecture du texte : EasyOCR

| | |
|---|---|
| Bibliothèque | [EasyOCR](https://github.com/JaidedAI/EasyOCR) 1.7, modèles de reconnaissance latins (`fr`) |
| Licence | Apache 2.0 |
| Taille | environ 95 Mo (`~/.EasyOCR`) |
| Exécution | processeur |
| Code | `komian/ocr.py`, contrôle « Lisibilité (OCR) » dans `komian/checks.py` |

L'OCR relit le texte exact et l'accroche **tels qu'ils apparaissent dans l'image finale**, puis compare sa lecture au brief, sans tenir compte des accents ni de la casse. Au-delà de 85 % de similarité (`READABLE_SIMILARITY`), le texte est jugé lisible.

- L'**exactitude** du texte (casse, accents, ponctuation) est vérifiée par un autre contrôle, « Textes exacts », à partir de ce que le compositeur a réellement dessiné. L'OCR vérifie la **lisibilité**.
- Une lecture insuffisante donne un résultat **non concluant**, jamais une anomalie : un OCR peut échouer sur un texte pourtant lisible pour un humain.

## Détection des visages : YuNet

| | |
|---|---|
| Modèle | [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet), version 2023mar, via OpenCV (`cv2.FaceDetectorYN`) |
| Licence | MIT |
| Taille | 232 Ko (`data/models/face_detection_yunet_2023mar.onnx`) |
| Exécution | processeur, quelques dizaines de millisecondes |
| Code | `komian/saliency.py` |

YuNet sert à deux choses :

1. **Placement des variantes.** Une disposition dont le message recouvre plus de 5 % d'un visage (`FACE_COVER_TOLERANCE`) est écartée des propositions.
2. **Contrôle « Visages dégagés ».** Si le message recouvre un visage détecté, c'est une anomalie, et l'approbation est refusée.

Limites : seuil de confiance de 60 % (`FACE_MIN_CONFIDENCE`). Un visage de profil, partiellement caché ou très petit peut échapper au détecteur. Le contrôle le rappelle, et la vérification à l'œil reste nécessaire.

OpenCV 5 ne fournit plus les anciens détecteurs Haar : YuNet est le détecteur recommandé.

## Repérage du sujet : spectral residual

Ce n'est pas un modèle entraîné, mais un algorithme classique de **carte de saillance** (Hou et Zhang, 2007). Il estime, à partir du spectre de fréquences de l'image, les zones qui attirent l'œil.

- Code : `komian/saliency.py`.
- Usage : classer les dispositions du message. Une disposition qui couvre peu de zones saillantes, sur un fond calme, est préférée.
- Limite : il peut retenir un décor contrasté (cadre en bois, feuillage) plutôt qu'un visage. C'est pourquoi la détection de visages, plus fiable pour les personnes, prime sur lui.

## Ce qui reste un contrôle humain

Aucun de ces outils ne remplace la relecture du visuel. Restent toujours à vérifier à l'œil, et sont signalés comme tels dans le rapport de contrôle :

- les mains, les objets et l'absence de texte parasite dans une scène générée par IA ;
- les éléments interdits déclarés dans le brief ;
- les points de la charte non tranchés (règles d'usage du logo, logo blanc dérivé, mention « Maison et Jardin »).
