# WikiFreeCards

**Un jeu de cartes à collectionner dont chaque carte est un article de Wikipédia.**
Ouvre des paquets, découvre des articles tirés au hasard, classés par rareté selon leur audience, et range-les dans ta collection.

![Licence MIT](https://img.shields.io/badge/licence-MIT-blue.svg)
![Python 3.12](https://img.shields.io/badge/python-3.12-yellow.svg)
![Données locales](https://img.shields.io/badge/donn%C3%A9es-100%25%20locales-green.svg)

WikiFreeCards est un logiciel **local** : il tourne sur ton ordinateur, garde tout dans un fichier SQLite et s'utilise depuis ton navigateur.
Pas de compte, pas de serveur à louer, pas de publicité, pas de télémétrie.

<!-- Ajoute ici une ou deux captures d'écran :
![La collection](docs/images/collection.png)
-->

## Le principe

Chaque carte reprend le titre, l'image, le résumé et les statistiques d'un article. Sa **rareté** vient du nombre moyen de vues par jour sur les 60 derniers jours :

| Rang | Vues par jour | | Rang | Vues par jour |
|---|---|---|---|---|
| **L** · Légendaire | 10 000 et plus | | **R** · Rare | 50 et plus |
| **UR** · Ultra rare | 2 000 et plus | | **PC** · Peu commun | 10 et plus |
| **SR** · Super rare | 500 et plus | | **C** · Commun | moins de 10 |

Les paliers se règlent dans la Configuration. Le rang d'une carte peut être recalculé à tout moment d'après ses nouvelles vues.

## Fonctionnalités

**Obtenir des cartes**
- **Paquets** : tirage au hasard, ouverture animée, cartes full-art et GOD PACK ultra rares.
- **Recherche** dans Wikipédia pour rapatrier un article précis.
- **Importation en lot** depuis un fichier `.txt` (un titre par ligne) : progression en direct, interruption et reprise possibles.

**Gérer sa collection**
- Catégories automatiques par mots-clés (dans le titre, le sous-titre ou l'introduction), favoris, filtres, tri, détection des doublons, corbeille.
- **Mise à jour à la demande** : un clic sur la bande du bas d'une carte relit ses statistiques sur Wikipédia (vues, langues, modifications, liens) et recalcule son rang, qui peut monter ou descendre.

**Personnaliser**
- Choix et **cadrage de l'illustration** parmi toutes les images de l'article, créateur de cartes, thèmes, sons, mise en page mobile.
- **Page de profil** : vitrines de tes plus belles cartes et **photo de profil ronde** (image d'une carte ou fichier de ton ordinateur, avec positionnement).

**Partager et conserver**
- **Hall des collections** : partage en lecture seule avec d'autres collectionneurs, via Tor, photo de profil comprise.
- **Export** en PNG, PDF ou Word, **sauvegardes** de la collection, **journal d'activité** optionnel (`journal.log`).

La liste détaillée est dans [`FONCTIONNALITES.md`](FONCTIONNALITES.md).

### Importation en lot

Dans **Configuration > Système**, le bouton d'importation analyse d'abord ton fichier sans rien demander à Wikipédia (titres, doublons, articles déjà possédés, durée estimée), puis crée les cartes en lots de 20 titres, une requête à la fois, avec une pause réglable. Pendant l'opération, une fenêtre affiche le nombre de cartes restantes, une barre de progression et le temps restant. Limites : 50 000 titres distincts et 5 Mo par fichier.

## Installation

Prérequis : **Python 3.12**, la version avec laquelle le programme est développé et testé. Edge ou Chrome sont recommandés.

```bash
git clone https://github.com/damballah/wikifreecards.git
cd wikifreecards
pip install -r requirements.txt
python main.py
```

Le programme démarre un serveur local, ouvre la page dans ton navigateur, et tout se règle ensuite depuis la page **Configuration**. `Ctrl+C` dans le terminal l'arrête.

Dépendances : `requests` et `cryptography`. `Pillow` est facultatif (réduction des images de paquets personnalisés). **Tor** n'est nécessaire que pour le Hall des collections.

## Respect de Wikipédia

Les cartes viennent de l'API publique de Wikipédia, utilisée avec courtoisie : une requête à la fois, une pause entre deux requêtes, le paramètre `maxlag`, et le respect des demandes de ralentir. L'importation en lot regroupe 20 titres par requête et se met en pause d'elle-même si Wikipédia insiste.
Le contenu des articles est sous licence libre **CC BY-SA**.

## Le Hall des collections (Tor)

Le partage est **désactivé par défaut**. Une fois activé, ton nœud est joignable par une adresse `.onion` dérivée de ta clé d'identité (Ed25519) :

- ton adresse IP n'est jamais visible et aucun port n'est à ouvrir ;
- Tor chiffre les échanges de bout en bout, et chaque réponse est signée par ta clé ;
- tout est en lecture seule, et tu choisis ce qui est visible (profil, collection) ;
- les visiteurs voient ta photo de profil sous forme d'un carré recadré, jamais l'image d'origine ;
- le Tor lancé par le programme est fermé avec lui.

Ton pseudo et le nom de ta collection restent visibles de ceux qui te trouvent : évite d'y mettre des informations personnelles. Ta clé est stockée dans `data/` et n'est pas comprise dans les sauvegardes.

## Organisation du projet

```
main.py          lancement
wikicartes/      le code Python (serveur local, base, partage, rendu)
static/          scripts et styles
templates/       modèles de pages
profil/          la photo de profil
logo/  ico/      logo du site et icône d'onglet
zuul/  gozer/    calques des cartes full-art
data/            créé au premier lancement : collection et sauvegardes
paquets/         différents designs de paquets
sons/            sons d'évèements et musique fourni de base (Libres de droits)
tor/             tor expert bundle fourni dans sa version 16.0‏ (tor 0.4.9.15)
```

## Licence

Logiciel libre sous licence **MIT**, voir [`LICENSE`](LICENSE).

Copyright (c) 2026 [Damballah Oueddo](https://github.com/damballah)
