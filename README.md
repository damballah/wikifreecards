# WikiFreeCards

**Collectionne les articles de Wikipédia comme des cartes.** Ouvre des paquets, découvre des articles tirés au hasard, classés du plus rare au plus commun selon leur nombre de vues, puis range-les dans ta collection locale.

![Licence MIT](https://img.shields.io/badge/licence-MIT-blue.svg)
![Python Version](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)
![Fonctionne en local](https://img.shields.io/badge/donn%C3%A9es-100%25%20locales-green.svg)

WikiFreeCards est un logiciel **local** : il tourne sur ton ordinateur, enregistre tout dans un seul fichier (SQLite) et s'utilise depuis ton navigateur. Pas de compte, pas de serveur à louer, pas de publicité.

<!-- Ajoute ici une ou deux captures d'écran, par exemple :
![La collection](docs/images/collection.png)
-->

## Ce que tu peux faire

**Collectionner**
- Ouvrir des **paquets** de cartes tirées au hasard dans Wikipédia, avec animations et sons.
- Un **rang de rareté** par carte (L, UR, SR, R, PC, C) calculé d'après le nombre de vues de l'article.
- Des **recherches** dans Wikipédia pour rapatrier les articles qui t'intéressent.
- Des **catégories**, des favoris, des filtres, une corbeille, des **doublons** repérés automatiquement (même texte, même rang, même image).
- Des cartes **full-art** et un **GOD PACK** extrêmement rare.

**Personnaliser**
- Un **éditeur d'illustration** : choisir parmi toutes les images de l'article, puis déplacer, agrandir ou réduire l'image dans le cadre de la carte.
- Un **créateur de cartes** pour fabriquer tes propres cartes (image, texte, rang).
- Une page **profil** avec des **vitrines** pour exposer tes plus belles cartes.
- Une page **Configuration** très complète : thèmes, apparence des rangs, sons et musique, disposition, affichage mobile…

**Conserver et partager**
- **Export** des cartes en PNG, PDF ou Word, avec QR code vers l'article.
- **Sauvegardes** automatiques de ta collection.
- Le **Hall des collections** : partage ta collection avec d'autres collectionneurs, via Tor (voir plus bas).

La liste complète des fonctionnalités est dans [`FONCTIONNALITES.md`](FONCTIONNALITES.md).

## Installation

Il te faut **Python 3.12 ou plus récent** (testé avec 3.12). Edge ou Chrome sont recommandés.

```bash
git clone https://github.com/damballah/wikifreecards.git
cd wikifreecards
pip install -r requirements.txt
python main.py
```

Le programme lance le site en local et ouvre la page dans ton navigateur. **Tout se fait ensuite depuis la page.** `Ctrl+C` dans le terminal arrête le serveur.

Bibliothèques : `requests` et `cryptography` (obligatoires). `Pillow` est facultatif : il sert à réduire et redresser l'image d'un paquet personnalisé.

## Le Hall des collections (partage via Tor)

Le partage est **désactivé par défaut**. Une fois activé, ton nœud est joignable par une adresse `.onion` calculée à partir de ta clé d'identité (Ed25519). Les connexions passent par le réseau **Tor** :

- ton **adresse IP n'est jamais visible**, et tu n'ouvres aucun port sur ta box ;
- entre le visiteur et ton nœud, Tor établit un **chiffrement de bout en bout** : personne au milieu ne lit le contenu ;
- chaque réponse de ton nœud est **signée en Ed25519** (avec un nonce propre à la requête) : on sait qu'elle vient de toi, qu'elle n'a pas été modifiée et qu'elle n'est pas rejouée ;
- tout est en **lecture seule** : les visiteurs peuvent parcourir tes cartes et en rapatrier une copie, mais ne peuvent rien modifier chez toi ;
- **tu choisis ce qui est visible** : profil, collection, ou rien.

Il faut que le programme **Tor** soit installé sur ta machine (le logiciel peut le lancer pour toi, il ne l'installe jamais). Ton nœud n'est joignable que lorsque ton ordinateur est allumé.

> Les visiteurs voient ton pseudo et le nom de ta collection : évite d'y mettre des informations personnelles. Ta clé secrète est dans `data/identite_p2p.key` ; elle n'est pas dans les sauvegardes. La perdre fait changer ton adresse.

## Personnaliser

| Pour… | Fais ceci |
|---|---|
| Changer le logo | Remplace le fichier `logo/logo.*` par une image du même nom |
| Changer l'icône de l'onglet | Dépose `ico/favicon.ico` (16×16 ou 32×32) ou `ico/favicon.png` (32×32) |
| Modifier un réglage | Page **Configuration** du site (ou `wikicartes/config.py` pour les valeurs de départ) |

## Organisation du projet

```
main.py            lancement du programme
wikicartes/        le code Python (serveur local, base de données, partage, rendu…)
static/            scripts et feuilles de style du site
templates/         modèles de pages HTML
logo/  ico/        logo du site et icône d'onglet
zuul/  gozer/      calques des cartes full-art
data/              créé au premier lancement : ta collection (collection.db) et tes sauvegardes
```

## Données et respect de Wikipédia

Le contenu des cartes provient de **Wikipédia**, sous licence libre **CC BY-SA**. Le programme interroge l'API publique de Wikipédia avec une pause d'une seconde par défaut entre deux requêtes (réglable dans la Configuration) et s'identifie par le contact indiqué dans la Configuration (par défaut, ce dépôt). Sois courtois : garde une pause raisonnable.

## Licence

WikiFreeCards est un logiciel libre sous **licence MIT** : tu peux l'utiliser, le modifier et le partager, à condition de conserver la mention d'auteur d'origine. Voir [`LICENSE`](LICENSE).

Copyright (c) 2026 [Damballah Oueddo](https://github.com/damballah)
