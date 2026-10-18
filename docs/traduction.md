# Traduction des descriptions de scène

Les modèles d'images comprennent l'anglais. Pour que le studio puisse décrire les scènes en français, la description est traduite **dans le processus de génération** : la traduction n'est jamais affichée, mais elle est enregistrée avec le rendu.

## Modèle

| | |
|---|---|
| Modèle | [Helsinki-NLP opus-mt-fr-en](https://huggingface.co/Helsinki-NLP/opus-mt-fr-en) (MarianMT) |
| Licence | Apache 2.0 |
| Taille | environ 300 Mo |
| Exécution | processeur, via `transformers` (dépendances `sentencepiece` et `sacremoses`) |
| Temps | environ 10 s pour la première traduction après démarrage (chargement), puis moins d'une seconde |
| Code | `komian/translate.py` |

## Fonctionnement

1. **Détection de la langue.** Une description sans accent ni mot-outil français (*le, la, avec, dans*…) est considérée comme déjà en anglais et transmise telle quelle.
2. **Glossaire métier.** Les termes de photo et de bricolage sont remplacés par leur équivalent anglais, puis **protégés par des marqueurs** pendant la traduction pour que le traducteur ne les modifie pas.
3. **Découpage.** La description est découpée aux virgules et points-virgules, et chaque élément est traduit séparément pour qu'aucun détail d'une longue énumération ne se perde.
4. **Enregistrement.** Le texte saisi (`prompt`), le texte transmis (`prompt_en`) et le modèle de traduction sont enregistrés dans les paramètres du rendu.

## Pourquoi un glossaire

Sans glossaire, le traducteur généraliste faisait des contresens sur des termes décisifs pour l'image :

| Français | Traduction brute | Avec glossaire |
|---|---|---|
| plan taille | *waistline* (tour de taille) | *medium shot* |
| rayon (de magasin) | *ray* (rayon lumineux) | *shop aisle* |
| établi en bois | *made of wood* (« établi » perdu) | *wooden workbench* |
| souriante | *smiling* (sourire forcé à l'image) | *with a gentle natural smile* |
| photo réaliste | *realistic photo* (rendu de synthèse) | *candid photo, 35mm photograph* |

Le glossaire couvre une trentaine de termes : cadrages (plan taille, plan rapproché, plan large…), regard vers l'objectif, outils (perceuse, scie sauteuse, niveau à bulle, mètre ruban…), décor (mur perforé, établi, rayon), expressions et style photo.

## Ajouter un terme au glossaire

Ajoutez une ligne à la liste `GLOSSARY` de `komian/translate.py`. Une expression longue doit passer avant les mots isolés qu'elle contient :

```python
(r"ponceuse(?: orbitale)?", "orbital sander"),
```

Ajoutez ensuite le cas au test `tests/test_translate.py`.

## Limites

- **Les tournures complexes peuvent être traduites mot à mot** (*overalls in jeans* pour « salopette en jean ») : sans conséquence pour le modèle d'images.
- **Un mot anglais isolé dans une phrase française** peut être modifié par le traducteur. Écrivez de préférence toute la description dans une seule langue.
- **La détection de langue est simple.** Une description très courte et sans mot-outil (« ambiance chaleureuse ») est bien traduite, mais un cas ambigu peut passer sans traduction. Le texte réellement transmis est visible dans les paramètres du rendu.
