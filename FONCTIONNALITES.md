# WikiCartes — liste complète des fonctionnalités

WikiCartes est un jeu de cartes à collectionner fabriqué avec des articles de **Wikipédia**. Il tourne **en local** sur ton ordinateur
(`python main.py`) : un petit serveur local, ta page dans le navigateur, une base de données SQLite. Rien n'est hébergé ailleurs, et
tout ce qui touche à ta collection reste chez toi, sauf ce que tu décides de partager (Hall des collections).

Ce document recense **tout ce que le programme sait faire**. Pour le détail des réglages et le mode d'emploi, voir `README.md`.

---

## 1. Obtenir des cartes

- **Ouvrir un paquet** : un clic sur le paquet tire des articles Wikipédia (5, 10 ou 20 cartes par paquet, au choix) et les ajoute en tête
  de ta collection. Les cartes du paquet s'affichent **des plus
  communes aux plus rares** (la plus rare en dernier).
- **Un rang selon la popularité** : chaque article reçoit un rang d'après son **nombre de vues par jour** (moyenne sur 7 jours par
  défaut) : **L**égendaire, **UR** ultra rare, **SR** super rare, **R** rare, **PC** peu commun, **C** commun. Seuils, probabilités de
  tirage, noms et lettres (1 à 3) de chaque rang sont réglables.
- **Tirage** : articles les plus vus du moment (top Wikipédia), articles aléatoires, ou un mélange selon les probabilités des rangs ;
  langue de Wikipédia réglable, période de calcul des vues réglable.
- **Décompte d'ouverture** : pour ménager Wikipédia, les requêtes sont espacées ; un décompte en secondes (avec barre de progression)
  s'affiche et colle aux réglages ; le paquet s'ouvre quand le tirage est terminé.
- **Réserve de cartes (pré-chargement)** : le programme peut préparer des paquets à l'avance, en arrière-plan, poliment (une requête
  à la fois, pauses longues, plafond par heure, arrêt si Wikipédia ralentit, priorité à tes ouvertures de paquet et à tes recherches).
  État, jauge et boutons « Remplir maintenant » / « Vider la réserve » dans la Configuration.
- **Stock de paquets prêts et décompte** (réglable) : la taille du paquet fixe le stock : **5 cartes = 10 paquets prêts, 10 cartes = 3 paquets,
  20 cartes = 1 paquet**. Le stock se reconstitue au fil du temps, **un paquet toutes les 6, 20 ou 60 minutes** (tout le stock en 1 heure) ;
  ouvrir un seul paquet de 10 cartes laisse donc 2 paquets prêts, sans attente. La légende sous le paquet indique le stock :
  **« Ouvrir un paquet · 5 cartes · 1 paquet prêt sur 10 »**, et en dessous **« Prochain paquet dans »** avec un **décompte en minutes ET
  secondes** qui défile (visible tant que le stock n'est pas plein). Plaque sobre dont la **taille suit celle du paquet** (normal, remonté, mini,
  compact). Quand il n'y a plus de paquet prêt (« 0 paquet prêt sur 10 »), le paquet reste visible (ses animations continuent) mais un clic ne
  fait rien. Le décompte annonce le plus long entre la reconstitution du stock et la préparation des cartes (requêtes restantes, pause du
  pré-chargement, pause de Wikipédia, **plafond horaire simulé** sur le journal réel). Le pré-chargement repart dès qu'un paquet est ouvert,
  poliment (pauses de 3 s, 120 requêtes par heure au plus) : d'abord de quoi former un paquet, puis le reste du stock.
- **Fenêtre des cartes du paquet** (réglable) : à l'ouverture, les cartes apparaissent au milieu de l'écran, **une à une** (animation
  fluide d'environ 1,5 s, plus courte pour les petits paquets), **des plus communes aux plus rares**. Miniatures et fenêtre
  s'adaptent à la taille du paquet (5, 10 ou 20 cartes) et à l'écran. Un **✕ retire une carte** : elle est supprimée tout de suite et pour de
  bon (pas à la corbeille). « **Ajouter à la collection** » (ou Échap) ferme la fenêtre et fait entrer les cartes gardées dans la
  collection. Les cartes sont enregistrées dès l'ouverture : fermer la page ne perd rien.
- **Page Recherche** : cherche n'importe quel article Wikipédia (20 résultats par défaut, réglable de 1 à 20), vois ses **vues par
  jour** et son rang futur, coche ceux que tu veux et **importe-les** dans ta collection (jusqu'à 100 d'un coup, cochés sur plusieurs
  pages). Les articles que tu as déjà sont signalés. **Les plus vues d'abord** (ou ordre de Wikipédia, ou titre A→Z) ; bouton
  **« Résultat(s) suivant(s) »** (jusqu'à 200 résultats ; au bout de la recherche, le bouton reste affiché mais grisé) ; **pagination en haut et en bas** comme dans la collection. Aucune
  statistique n'est demandée à Wikipédia pour les résultats (une seule requête par lot) ; elles sont complétées plus tard pour les
  cartes gardées.
- **Rapatrier depuis un autre collectionneur** (Hall des collections, voir § 9) : copie ses cartes chez toi **sans aucune requête
  vers Wikipédia**.
- **Créer ses propres cartes** (Créateur de cartes, voir § 8).

## 2. Le paquet à ouvrir

- **10 styles prêts à l'emploi** : classique, or, nuit étoilée, holographique, braise, océan, forêt, bonbon, carbone, cosmos.
- **Paquet personnalisé : téléverse ta propre image** (PNG ou JPEG, 5 Mo au plus ; une très grande image est réduite à 1200 px si
  Pillow est installé). Le paquet s'adapte à **n'importe quelle image** sans prendre l'écran : **forme** au choix (proportions de
  l'image, rectangle vertical, rectangle horizontal, carré, **rond**), **cadrage** (recadrer pour remplir la forme, ou image entière),
  et ce qu'on place dessus : **rien (juste l'image)**, le **logo** du jeu ou un **texte**. Les proportions extrêmes sont bornées
  (de 1:5 à 5:1), la transparence des PNG est gardée, l'orientation des photos de téléphone est corrigée.
- **Confettis et paillettes** à la disparition du paquet, **adaptés à chaque animation** : gerbe de confettis et anneau (explosion),
  étoiles et anneau (flash), fontaine de confettis (rebond), spirales d'étincelles (rotation, tourbillon), traînée qui retombe (envol),
  poussière brillante qui monte (dissolution), nuage de poussière au sol (chute), petits cœurs (battement), petite gerbe (secousse).
- **10 animations d'ouverture** (toutes adaptées à n'importe quelle image) : secousse, flash, rotation, envol, dissolution, rebond,
  tourbillon, explosion, chute, battement de cœur — ou aucune. Aperçu et bouton « Tester l'animation » dans la Configuration ; elles
  s'arrêtent si ton système demande de réduire les animations.
- **Logo** du jeu sur le sachet (ou, sans logo, un mot ou une phrase au choix), légende « Ouvrir un paquet · N cartes », décompte.
- **Position du paquet dans la page** : **normal** (par défaut : grand sachet, texte en dessous), remonté, compacte (petit sachet, texte
  dessous), très compact ; ou paquet masqué (les cartes remontent).
- **Effet au passage de la souris**, au choix parmi **les mêmes que pour les cartes** : soulever (défaut), incliner, agrandir, flotter,
  ressort, pivot 3D, suit la souris (3D), brillance, halo, balancer, aucun.
- **Animation au repos** (sans souris), au choix parmi **les mêmes que la carte agrandie** : flottement, balancement, respiration, pivot
  3D, reflet qui passe, balancement 3D lent, ou aucune. Elles s'effacent pendant l'ouverture (l'animation d'ouverture garde la main)
  et avec « mouvement réduit ».

## 3. La carte

- **Visuel** : image de l'article, rang en lettres, titre, sous-titre (courte description), introduction (quelques phrases), vues par
  jour, date et heure du tirage, lien vers l'article, étoile (favori), icônes d'export.
- **Apparence de chaque rang** réglable avec aperçu en direct : **motif** (vagues, rayures, points, losanges, rayons), **3 couleurs**
  (fond haut, fond bas, accent ; le texte s'ajuste pour rester lisible), **reflet animé** parmi 10 : balayage, pulsation, étincelles
  (3 placements différents à chaque passage), arc-en-ciel, vague montante, faisceau tournant, balayage croisé, paillettes
  scintillantes, aurore, contour néon.
- **Pied de carte sur une seule ligne** : statistiques et date compactées par étapes selon la place, y compris dans les exports.
- **Statistiques** (optionnelles) : nombre de langues, taille de l'article, nombre de modifications, liens entrants. Elles
  **arrivent avec la carte** : à l'ouverture d'un paquet elles sont récupérées tout de suite (hors plafond horaire, pause plus courte
  de 0,3 s par défaut ; le décompte en tient compte). Les cartes préparées d'avance les reçoivent dès leur préparation. Si Wikipédia
  limite le débit, le paquet s'ouvre quand même et un fil de fond complète le reste, poliment.
- **Catégories** en petits bandeaux colorés au-dessus du titre (nom coupé avec « … », « +2 » au-delà, nom complet au survol).
- **Agrandir une carte** : clic sur l'image, avec animation d'ouverture au choix ; la carte agrandie reprend les icônes utiles (étoile,
  exports, lien) et reste active.
- **Effet au survol** des cartes au choix ; angles arrondis ou carrés ; largeur des cartes réglable.
- **Cartes personnalisées** : surnom en pied de carte, thème propre, image téléversée (voir § 8).

## 4. Ta collection

- **Base de données SQLite locale** (`data/collection.db`) : migrations automatiques entre versions, sauvegardes automatiques,
  vérification d'intégrité au démarrage.
- **Filtres** (cumulables, retrouvés au relancement) : par rang, par **favoris**, par **catégorie**, par **texte** (titre).
- **Tri** (6 ordres) : date (récentes / anciennes), vues par jour (élevées / faibles), titre A→Z / Z→A (sans tenir compte des
  accents ni des majuscules).
- **Pagination** (25 cartes par page par défaut) avec boutons en haut et en bas.
- **Curseur de taille des cartes** : effet immédiat et **enregistrement à la volée, sans message** ; ↺ pour revenir à la valeur de départ.
- **Mode sélection** : cases à cocher (un clic sur la carte la coche aussi), tout sélectionner (page), classer dans des catégories,
  exporter, ou envoyer à la corbeille.
- **Favoris** : étoile sur chaque carte, filtre « Favoris », compteur dans la barre des rangs.
- **Résumé** en tête : nombre de cartes, répartition par rang.
- **Corbeille** : supprimer ne détruit rien. Les cartes vont à la corbeille, qui a sa page : restaurer une, plusieurs ou tout, ou
  supprimer **définitivement** (avec confirmation). Compteur sur le bouton ; avec le menu à gauche en colonne, elle s'ouvre comme un
  message au milieu de l'écran.

### Catégories

- **Catégories créées par toi** : nom, couleur, 5 « mots-clés » (méta) par catégorie. À l'ouverture d'un paquet, une carte est classée
  automatiquement si un mot-clé apparaît dans sa courte description **ou dans les phrases de son introduction** (majuscules et accents
  ignorés ; mot entier ou non au choix ; plusieurs catégories possibles). « Classer maintenant les cartes existantes ».
  Supprimer une catégorie ne supprime jamais de cartes.
- **Trois catégories automatiques**, calculées toutes seules et renommables dans la Configuration (nom, couleur, activation) :
  - **Doublons** : deux cartes Wikipédia de même titre exact ; deux cartes **personnalisées** dont le titre, le sous-titre, la
    description ET le surnom sont tous identiques (bandeau « Doublon ×2 », liste « Doublons (N) ») ;
  - **Sans illustration** : cartes sans image ;
  - **Animée** (activée par défaut) : cartes dont l'illustration est un **GIF**.
- Compteurs entre parenthèses dans la liste « Catégorie » ; entrée « Sans catégorie ».

## 5. Exports et impression

- **Disquette** : enregistre la carte en **image PNG** dans `Export/<rang>/` (nom : rang, titre, date et heure du tirage).
- **PDF et Word** : document de **deux pages prêt à imprimer en recto verso** : recto = la carte, verso = dos aux couleurs du rang avec
  le **logo** et un **QR code** vers l'article ; repères de coupe aux quatre coins, taille réelle (63 mm par défaut, réglable),
  papier A4 ou autre, marges, résolution.
- Les catégories peuvent apparaître (ou non) sur les images exportées.
- Exports des **cartes personnalisées** avec leurs couleurs.
- Icônes d'export (PNG, PDF, Word, lien) activables une à une.

## 6. Page Profil et vitrines

- Ta **page de profil** présente le titre et la biographie de ta collection, le nombre de cartes, la répartition par rang et par
  catégorie, et des **vitrines** : un nombre réglable de vitrines (titre modifiable) de plusieurs emplacements chacune.
- **Choisir une carte pour un emplacement** : fenêtre de recherche dans **tout le texte des cartes — titre, sous-titre et
  description** — avec pagination ; carte déjà exposée signalée ; **filtres par rang** (boutons L, UR, SR, R, PC, C, cumulables) et **tri**
  (pertinence, date récentes / anciennes, titre A→Z / Z→A).
- Les cartes exposées s'affichent épurées ; agrandissement au clic.
- Les mêmes vitrines sont ce que **les autres collectionneurs voient** sur ton profil (si tu l'autorises).

## 7. Identité et apparence du site

- **Logo** (dossier `logo/`, détection automatique) en tête de toutes les pages ; hauteur réglable.
- **Titre et biographie** avec **emojis** permis (tous les types : drapeaux, couleurs de peau, familles…, la longueur compte ce qu'on voit)
  et tailles réglables.
- **20 thèmes** de site (sombre, clair, minuit étoilé, océan, forêt… et 5 d'ambiance : **années 80-90 fluo new age, arcade rétro 8 bits,
  jeu de société, chic tendance, album de cartes à collectionner**), accent de couleur (celui du thème ou le tien), angles
  arrondis/carrés.
- **Disposition de la page** (Configuration → Disposition, avec **maquette en direct**) :
  - menu de navigation : **centré**, à droite, ou en **colonne à gauche** ; boutons complets, compacts, **icônes seules** ou **menu
    replié** ;
  - barre d'outils de la collection : compacte, centrée, à gauche ou repliable ;
  - paquet : remonté, compacte, très compact, normal ;
  - **alignement du logo** : à gauche du titre, centré à gauche du titre (logo + titre centrés ensemble), au milieu au-dessus du titre,
    centré à droite du titre, à droite du titre ;
  - **alignement du titre, de la biographie et de la ligne d'infos** : à gauche, au milieu ou à droite, séparément.
- **Mention** optionnelle en bas des pages ; pied de page « contenu issu de Wikipédia sous licence libre ».

## 8. Créateur de cartes

- Crée une carte qui n'existe pas sur Wikipédia : **titre, sous-titre, description (3 phrases), surnom**, **image** (téléversée, vérifiée
  par son contenu), **adresse source** facultative, avec **aperçu en direct** de la carte et ses vraies animations.
- **Texte pris sur le web** : lecture sécurisée d'une page (adresses publiques seulement), détection de l'encodage (UTF-8, accents
  réparés), texte brut propre (sans balises ni renvois « [1] »).
- **Thème** : palier « Personnalisée » (réglé dans la Configuration : lettres, nom, motif, 3 couleurs, reflet) ou le thème exact de
  n'importe quel rang ; la carte garde son aspect, même si tu changes les réglages plus tard.
- Les cartes personnalisées ont leur place dans la collection, les exports, les vitrines, le partage ; elles ne comptent pas dans les
  statistiques de popularité.
- Fenêtre de confirmation après validation (« Voir la collection » / « Créer une autre carte »).

## 9. Hall des collections — partage entre collectionneurs (pair à pair)

Voir `README.md` (section dédiée) pour le détail et les limites.

- **Sans serveur central, sans inscription, sans e-mail ni mot de passe** : chaque programme est son propre nœud.
- **Identité** : une paire de clés Ed25519 créée sur ta machine (fichier séparé, jamais dans la base ni les sauvegardes) ; ton identifiant
  est ta clé publique. **Pseudo** unique « au mieux » (règle du premier arrivé, équivalences d'écriture comprises) avec un repère de clé
  qui ne s'imite pas, supprimable à tout moment.
- **Fiches signées** échangées de proche en proche (bouche à oreille) : pseudo, nom de collection, nombre de cartes, pastilles P et C.
- **Page « Hall des collections »** : liste de tous les collectionneurs connus (nom de la collection, pseudo, nombre de cartes,
  **pastille P** profil et **pastille C** collection — verte / rouge / grise), **recherche** et **filtres** (profil accessible,
  collection accessible, en ligne, nombre minimum de cartes), **tri**, pagination, ajout d'un collectionneur par **invitation**.
- **Voir un profil ou une collection** (lecture seule, depuis la base du propriétaire, sans rien relancer vers Wikipédia), avec ses
  thèmes, ses lettres de rang, ses statistiques, **filtres, tri, recherche, pagination en haut et en bas** ; zoom comme d'habitude ;
  boutons profil ↔ collection et Quitter.
- **Rapatrier** : coche des cartes, « Rapatrier » : elles sont recréées chez toi (titre, sous-titre, adresses, vues, statistiques),
  avec l'horodatage de maintenant, ton rang selon tes seuils et tes catégories.
- **Tu décides de ce qui est visible** : nœud désactivé par défaut ; pastilles P et C rouges par défaut. Jamais envoyés : favoris,
  corbeille, réglages, contact, chemins, clé secrète.
- **Personne ne peut modifier tes cartes** : serveur pair à pair séparé de la page locale, lecture seule (SQLite en lecture seule),
  sept adresses seulement, réponses signées, limites de débit et de taille, données reçues vérifiées et échappées.
- **Connexion par Tor** (recommandée : adresse IP cachée, aucune ouverture de port), ou en direct, ou en local pour les essais ;
  service oignon dérivé de ta clé ; délais longs et nouvel essai ; republication automatique si Tor est relancé.
- **Aide à l'écran si Tor manque** : détection, fenêtre pas à pas (Navigateur Tor ou Tor Expert Bundle, `torrc` à copier), bouton
  **« Lancer Tor »** (trouve `tor.exe`, écrit son `torrc`, le lance), case **« Lancer Tor au démarrage du programme »**, chemin de
  `tor.exe` pré-saisi (`<racine>\tor\tor.exe`, avec `\` ou `/`). Message « patiente une à deux minutes » à l'activation du nœud.

## 10. La page Configuration

- **13 sections** ordonnées : Identité, Apparence, Disposition, Paquets, Raretés, Collection, Profil, Export, **Sons et musique**, puis les réglages
  avancés (Wikipédia, Réserve, **Hall des collections**) et **Système** en dernier.
- **Menu « Aller à »** collant en haut de l'écran qui met en avant la section visible ; **barre flottante** : Enregistrer, Tout remettre
  aux valeurs de départ, état, **↑ Remonter**.
- Chaque réglage a son bouton **↺** (valeur de départ), son aide, sa validation (valeur refusée = rien n'est enregistré, message à côté
  du champ). **Aperçus en direct** : rangs, paquet (style, image, animation), disposition, thème, catégories.
- Réglages **enregistrés dans la base** et repris à chaque lancement ; certains s'appliquent tout de suite, d'autres au prochain
  démarrage (indiqué).
- Section **Système** : serveur local, dossiers, base de données (lecture seule), puis les **sauvegardes** :
  - **4 types** : **Ultra complète** (paramètres actuels, collection et arborescence complète du programme), **Complète** (paramètres et
    collection), **Uniquement les paramètres**, **Uniquement la collection** (cartes, catégories, vitrines, corbeille, réserve, annuaire
    du Hall) ; chaque sauvegarde est un fichier .zip avec son manifeste (type, date, cartes, version de la base) ;
  - **créer**, **exporter** (téléchargement du .zip), **importer** (un .zip reçu : il est vérifié, rien n'est changé), **restaurer**
    (avec confirmation qui dit ce qui sera remplacé) et **supprimer** ;
  - avant toute restauration, l'état actuel est sauvegardé automatiquement (« avant-restauration ») ;
  - la **clé secrète d'identité** du Hall n'est dans aucune sauvegarde, sauf case cochée pour l'ultra complète ; la restauration
    ultra complète n'écrase jamais le programme (fichiers extraits dans `data/restaurations/<date>/`) ;
  - archives refusées si elles sont piégées (chemins dangereux, liens, bombe de décompression, base abîmée ou plus récente) ; les
    adresses douteuses d'une collection importée sont écartées.

### Sons et musique (Configuration → Sons et musique)

- **Un son pour chaque événement** : ouverture du paquet (au moment où il disparaît), **chaque carte** qui apparaît dans la fenêtre du paquet
  (rejoué pour chacune, échelonné comme l'animation), **carte retirée de la fenêtre** (petite croix ✕), arrivée dans la collection, cartes à la
  corbeille, restauration depuis la corbeille, suppression définitive. Interrupteur général et volume des effets.
- **Musique d'ambiance** en boucle pendant l'utilisation (activée ou non, fichier, volume). Elle joue dans un **lecteur** : une fenêtre du haut qui
  affiche chaque page dans un cadre plein écran (adresse et titre suivent la page), donc **elle ne s'interrompt jamais quand on change de page**.
  Sans musique active, les pages s'ouvrent normalement, sans cadre.
- **Haut-parleur** en bas à gauche (🔊, au-dessus de la barre « Enregistrer » sur la Configuration) avec un **petit curseur de volume discret à sa
  droite**. Un clic le **barre** (🔇) : la musique se coupe et le curseur disparaît. Le **choix (barré ou non) et le volume sont gardés sur le
  serveur** : au lancement suivant la musique repart toute seule si elle n'était pas coupée. Si le navigateur exige un premier clic, le haut-parleur
  pulse (« clique n'importe où ») sans être barré, et la musique démarre au premier clic dans la page.
- **Lancer dans une fenêtre d'application** (option) : ouvre le programme dans une fenêtre d'Edge ou de Chrome à part (profil `data/navigateur`) qui
  autorise le son sans clic préalable : la musique démarre alors toute seule au lancement. Sans Edge ni Chrome, le navigateur habituel est utilisé.
  Réglages appliqués tout de suite après « Enregistrer ».
- **Tes fichiers** : dossier `sons/` à côté de `main.py`, ou **téléversement** depuis la page (mp3, ogg, opus, wav, m4a, aac, flac, webm ;
  60 Mo au plus ; contenu vérifié, un faux fichier est refusé) ; bouton ▶ pour écouter, suppression depuis la page. Aucun son fourni.
- Le dossier `sons/` fait partie des sauvegardes (paramètres, complète, ultra complète).

### Page « Paquets », contenu sensible, rafraîchissement d'image, accès réseau

- **Page « Paquets »** : page de démarrage du programme (adresse `/paquets`) : le paquet, sa légende « k paquets prêts sur N » et son décompte.
  Les cartes ajoutées vont directement dans la collection (la page ne les affiche pas) : on reste sur la page tant qu'on n'en change pas. La page **Collection** (`/`) n'a plus de paquet. Dans la fenêtre de pré-visualisation, jamais de case de sélection sur les cartes.
- **Son d'effet du paquet** : joué dès le clic sur le paquet (en plus des sons d'ouverture, de chaque carte, de la carte retirée...).
- **Recherche dans la collection** : titre, sous-titre et description. **Tri par défaut** : « Vues par jour · plus élevées d'abord » (tes
  changements de tri sont gardés). Les cases d'export PNG / PDF / Word sont dans la section **Export**.
- **Position de l'écran** : avec la pagination du **bas** (collection, visite d'une collection du Hall, recherche) on reste en bas ; avec celle
  du haut, on reste en haut. Dans la vitrine d'un autre collectionneur, un clic **n'importe où** sur une carte l'agrandit.
- **Contenu sensible** (section « Contenu sensible ») : **aucune liste n'est fournie, tout se règle dans cette section.** Par défaut (liste vide), aucune
  carte n'est floutée et aucune icône +18 n'apparaît. Tu écris **ta liste de mots et d'expressions** (un par ligne ou séparés par des virgules ;
  sans accents ni majuscules à respecter ; une étoile finale = début de mot) : une carte dont le titre, le sous-titre ou la description contient
  l'un d'eux garde son texte mais son **image est floutée** (collection, recherche, vitrines, collections visitées), avec une icône « interdit aux
  moins de 18 ans » sous l'étoile pour montrer ou flouter l'image. Tu règles aussi les **exceptions** (mots qui écartent une carte), l'intensité
  (4 à 40) et l'icône. Les cartes créées par toi ne sont jamais floutées d'office.
- **Icône ⟳ « rafraîchir l'image »** (Apparence, désactivée par défaut) : revoit l'article sur Wikipédia ; une illustration apparue ou
  changée est enregistrée sur la carte (et en base) ; sinon, rien ne change.
- **Partage (Hall) uniquement par Tor** : plus de mode direct ni local dans la Configuration. Réglage « relais d'entrée du même pays »
  (automatique d'après la langue de l'ordinateur) : Tor préfère ces relais (préférence seulement ; il faut le fichier `geoip` livré avec Tor) ;
  un peu moins de diversité, donc un anonymat légèrement moins bon.
- **Accès depuis le réseau et l'extérieur** (section « Accès réseau », au prochain lancement) : « Seulement cet ordinateur » (défaut, verrouillé)
  ou « Réseau local et extérieur » : le programme devient un **vrai serveur** (écoute sur toutes les interfaces). Tout appareil qui atteint son
  adresse (`http://192.168.x.x:8765/`, tunnel ngrok / Cloudflare / Tailscale en http ou https, adresse IP publique) l'utilise directement, **sans mot
  de passe** : ouvrir un paquet, modifier la collection, tout agit sur le PC qui fait tourner le programme. Un **code d'accès facultatif** (vide par
  défaut) peut limiter ce qui ne vient pas du PC (page de connexion, session par cookie, essais limités). Au lancement, chaque adresse du réseau est
  **testée** ; si elle ne répond pas (pare-feu Windows), la console et la Configuration l'indiquent avec la commande `netsh` à lancer en
  administrateur. Sans code, quiconque atteint l'adresse peut tout faire : à réserver à tes essais.

### Recherche, logo et cartes validées

- **Champs de recherche** (section « Recherche de cartes ») : pour la page Collection, la page Recherche et le choix d'une carte dans le Profil,
  des cases à cocher titre / sous-titre / description. **Par défaut : titre et sous-titre seulement.** Page Recherche : les résultats de Wikipédia
  dont les mots ne sont pas dans les champs cochés sont masqués (leur nombre est indiqué). Aucune case cochée : le titre.
- **Logo au-dessus du menu** (Disposition → Logo : alignement) : avec le menu en colonne à gauche, le logo se pose en haut de la colonne. Le logo garde sa proportion (jusqu'à la hauteur réglée) et le **menu se place toujours sous lui**, même avec un logo haut (mesuré par le script).
- **Cartes validées** : après « Ajouter à la collection », elles vont directement dans la collection ; la page Paquets ne les affiche pas.
- **Icône +18** : fonctionne dans toutes les pages (collection, recherche, profil, collections visitées, corbeille).

### Détails récents

- **Icône +18 : état gardé.** Montrer l'image d'une carte sensible (ou la flouter de nouveau) est **enregistré** : après avoir fermé puis relancé le
  programme, l'image reste telle que tu l'as laissée (clé : l'adresse de l'article ; 2 000 cartes au plus, les plus anciennes sont oubliées).
  Vaut dans toutes les pages (collection, recherche, collections visitées...).
- **Réglages avancés réservés au réseau local** (case dans la section **Système**, **cochée par défaut**) : les sections Wikipédia, Réserve, Hall des
  collections (réglages), Accès réseau et Système ne sont **visibles et modifiables que depuis cet ordinateur et le réseau local** (192.168.x.x,
  10.x.x.x, 172.16-31.x.x...). Depuis une adresse IP publique, un tunnel (nom de domaine public, adresse du vrai client annoncée par le relais) ou
  dans le doute, ces sections sont absentes de la page et les actions correspondantes (réglages avancés, sauvegardes, réserve) sont refusées par le
  serveur. Décoche la case pour les ouvrir à tous.
- **Pied de page** (mention et ligne) : centré sur le contenu de la page, même avec le menu en colonne à gauche.

### Affichage téléphone

Configuration → **Apparence**, deux listes seulement :
- **Affichage sur téléphone** : *Automatique* (défaut : optimisé dès que l'écran fait 720 px ou moins, ou qu'il est tactile jusqu'à 960 px ; la détection
  suit la largeur de l'écran, pas la marque de l'appareil, et se rétablit si la fenêtre s'élargit), *Toujours* (même sur ordinateur) ou *Jamais*.
- **Téléphone : en-tête** : *Compact* (défaut : logo, titre court et menu ; biographie et infos masquées), *Minimal* (logo et menu seulement) ou *Complet*.

Quand l'affichage téléphone est actif : menu réduit à ses icônes, sur une seule rangée ; rangs sur une ligne qui défile ; filtres, recherche, tri derrière
le bouton « Filtres » (la taille des cartes se règle toute seule) ; cartes sur **deux colonnes** (trois en paysage) ; Configuration allégée (menu « Aller à »
non collé, barre d'enregistrement basse). La page Paquets n'a plus de bouton « Filtres » inutile. L'icône +18 apparaît aussi sur la carte **agrandie** de la
page Recherche et des collections visitées.

### Icônes des cartes sans étoile, flou dans la liste de choix

- **Cartes sans étoile** (collection d'un autre collectionneur dans le Hall, page Recherche) : le lien ↗ se cale dans le coin en haut à droite (la place
  de l'étoile dans ta collection) et les icônes (+18, ⟳...) se suivent dessous, exactement comme dans ta collection.
- **Liste de choix d'une carte (page Profil)** : la vignette d'une carte sensible (d'après ta liste de mots) est floutée aussi, sauf si tu as montré son image.
- **features.txt** : la liste simple des fonctionnalités, version par version.

### Téléphone : pile de cartes, pastilles, profil ; recherche par pertinence

- **Pré-sélection du paquet sur téléphone** : une pile de cartes à découvrir, plein écran, sans défilement. Glisser à droite (ou bouton rond « collection ») = garder, la carte part
  en vert lumineux ; glisser à gauche (ou bouton rond « suppression ») = supprimer, la carte part en rouge lumineux. Sons « carte dans la collection » et « carte retirée ». Flèches et Échap
  fonctionnent aussi. Sur petit écran sans affichage téléphone : la grille classique, avec des croix de suppression plus petites.
- **Collection sur téléphone** : pastilles de rang = symbole + « (nombre) ». **Profil sur téléphone** : ⇄ (changer) et ✕ (retirer) à la place des mots.
- **Recherche** : tri par défaut par **pertinence** (titre exact, puis titre qui commence par la saisie, puis tous les mots dans le titre, puis sous-titre et introduction) ; un complément par
  préfixe de titre au premier lot ; « les plus vues » et « titre » restent au choix.

### Full-art, GOD PACK, grands écrans

- **Full-art** (Créateur de cartes → « ✨ Full-art ») : carte exceptionnelle avec deux calques PNG (**Zuul** puis **Gozer** par-dessus, fichiers `.png` des dossiers `zuul/` et `gozer/`
  à la racine du programme) et jusqu'à 3 des 12 effets animés. Calques sous les textes ; dos des PDF/Word avec les mêmes calques (sans effets), sous le logo et le QR code. Absent des collections
  visitées dans le Hall. Base : table `fullart` (schéma 13).
- **GOD PACK** : une chance sur N (Configuration → Paquets, 10 000 par défaut, 0 = jamais) d'un paquet de cartes toutes légendaires ; feu d'artifice, fanfare synthétisée, message « GOD PACK !!! » cliquable ; bouton d'essai.
- **Grands écrans** : facteur d'échelle de l'écran (1 jusqu'à 1800 px, 2,2 au plus) ; page centrée à droite du menu ; cartes, paquet, menu, titre et barres agrandis.
- **Téléphone** : l'adresse nue du programme ouvre la page Paquets. **Chaque page** affiche son nom sous la biographie.

### Finitions : full-art partagé, sons du GOD PACK, choix d'illustration

- **Full-art dans le Hall** : calques et effets visibles dans la collection et le profil partagés ; fichiers relayés et vérifiés (PNG, dimensions, 6 Mo) ; refusés s'ils ne servent pas à une carte partagée.
- **10 Zuul / 10 Gozer** fournis dans `zuul/` et `gozer/` ; effets Paillettes, Galaxie, Braises à particules aléatoires ; correctif du reflet doré sur Android.
- **GOD PACK** : sons d'explosion du feu d'artifice (synthétisés).
- **Carte sans image principale** : ⟳ propose les autres images de l'article (vignettes, pagination adaptative, choix revérifié par le serveur).

### Full-art définitif, rapatriement, choix d'illustration

- **Full-art définitif** : message de confirmation (« Opération irréversible ») avant d'appliquer ; ensuite la carte ne peut ni perdre ni changer son full-art (pas de bouton « Retirer »).
- **Cadres fins** : les Zuul de type cadre font environ 4 % de la largeur ; sous un Zuul le pied de carte est décalé vers l'intérieur pour ne rien recouvrir.
- **Rapatriement** : une carte full-art rapatriée du Hall reste full-art ; ses calques sont copiés chez toi après vérification (jamais d'écrasement).
- **Choix d'illustration** : sélection puis « Valider ce choix » ; changement possible pour une carte qui a déjà une image ; mise à jour immédiate de la carte.

### Correctifs : logos, carte agrandie, GOD PACK

- **Choix d'illustration** : logos SVG et logos larges proposés ; mise à jour immédiate de la carte agrandie.
- **GOD PACK** : choisi parmi les articles les plus vus ; vraies légendaires d'abord, puis les plus vues promues légendaires ; toujours le nombre complet de cartes, toutes légendaires.

### Illustration d'une carte : toutes les images, changer, retirer

- ⟳ liste toutes les images de l'article (actuelle, principale, autres ; icônes cachées par défaut) ; sélection puis validation ; « Retirer l'illustration » et remise possibles à tout moment.
- La liste réunit les images affichées dans la page (tous chapitres) et les fichiers utilisés par l'article, suites et redirections comprises (200 images au plus).
- Toutes les images sont listées (les icônes en dernier) ; l'illustration retirée est reproposée (« Retirée »). Catégorie « Animée » : seulement les GIF réellement animés (vérifiés en arrière-plan).
- Section « Redimensionner/Positionner l'image actuelle » : éditeur WYSIWYG (déplacer, agrandir ou RÉDUIRE de ×0,1 à ×4), réglage gardé par article et par image (les doublons le reçoivent), partagé dans le Hall. Disponible aussi sur les cartes créées à la main (icône ⟳) et directement dans l'aperçu du Créateur de cartes.
- Exclu : cartes full-art et cartes personnalisées.

### Images d'article

- Toute image vue un jour dans la liste d'un article y reste ; les fichiers qu'on ne peut pas lister sont comptés et expliqués au survol.

### Favicon

- Dossier ico/ : favicon.ico (16×16 ou 32×32) ou favicon.png (32×32) = icône de l'onglet du navigateur sur toutes les pages.

### Pagination et son en boucle

- Après un changement de page (haut ou bas), on repart du début de la liste. Le son d'effet du paquet peut jouer en boucle jusqu'à l'ouverture du paquet.

### Doublons

- Des doublons = des cartes identiques (texte, rang, image et cadrage de l'image) ; un rang, une image ou une taille différents en font deux cartes différentes.

### Mention d'auteur et message de bienvenue

- Pied de page fixe (Wikipédia, licence CC BY-SA du contenu, licence MIT, auteur) avec cinq liens ; message de bienvenue une fois par lancement, avec case « Ne plus afficher ce message au démarrage ».

### Cartes créées à la main et Hall

- Elles ne sont plus visibles ni prenables dans la collection partagée ; on ne les voit que dans les vitrines du profil (lecture seule).

## 11. Sécurité, robustesse et vie privée

- **Serveur local protégé** : écoute uniquement sur ta machine, **jeton** par session pour toute action, **hôtes** vérifiés, aucune
  page du site ne peut agir à ta place.
- **Données** : tout est vérifié (types, bornes, listes fermées) avant d'être enregistré ou affiché ; texte toujours échappé ; images
  vérifiées **par leur contenu** (jamais d'SVG), noms de fichiers non devinables, aucun chemin libre.
- **Requêtes sortantes polies et bornées** : adresses publiques seulement pour les pages web lues, tailles et délais limités, aucune
  redirection suivie.
- **Sauvegardes** automatiques de la base, **migrations** sans perte, base renommée automatiquement lors de l'évolution du programme.
- **Écritures atomiques**, transactions : en cas d'erreur, rien n'est à moitié enregistré.
- **Aucune télémétrie**, aucune inscription, aucun compte.

## 12. Confort et accessibilité

- Navigation au clavier partout, focus visible, fenêtres modales avec focus et Échap, lecteurs d'écran (rôles, noms accessibles,
  messages d'état), **mouvement réduit** respecté.
- Responsive : toutes les pages tiennent sur téléphone sans défilement horizontal.
- Mise en page stable : pied de carte sur une ligne, cartes centrées, pagination haut et bas.
- Les filtres, le tri, la taille des cartes et la position des éléments sont **retenus d'un lancement à l'autre**.

## 13. Qualité

- **Plus de 2 200 vérifications automatiques en Python**, plus de 600 en JavaScript et une trentaine de parcours complets dans un vrai
  navigateur (Chromium) couvrent le tirage, les rangs, les catégories, la corbeille, les exports, les vitrines, le Créateur, la
  Configuration, la disposition, les animations, le partage (identité, signatures, transport Tor simulé, sécurité du serveur, réseau de
  plusieurs nœuds) et les cas hostiles (données piégées, images piégées, injections).
- Limite connue : le partage via le **vrai réseau Tor** n'a pu être testé qu'avec des simulations conformes aux spécifications ;
  les premiers essais réels peuvent demander des ajustements.


## Importation de cartes en lot
- Configuration > Système : importer des cartes depuis un fichier .txt (un titre d'article par ligne). Analyse préalable sans requête, 20 titres par requête, une requête à la fois, pause réglable, `maxlag`,
  respect de « Retry-After », interruption automatique si Wikipédia demande sans cesse de ralentir.
- Fenêtre de progression qui verrouille le programme : compteur de cartes restantes, barre, temps restant estimé. Interruption et reprise possibles (même après fermeture du programme).


## Mettre à jour les statistiques d'une carte
- Clic sur la bande du bas d'une carte (même agrandie) : confirmation, puis relecture des vues, langues, modifications, liens entrants et taille ; le rang est recalculé (il peut monter ou descendre).
  Exclus : cartes créées à la main et full-art. Les « œ » et « æ » sont traités comme « oe » et « ae » dans les recherches et les meta.


## Journal d'activité
- Configuration > Système : activer le journal (`journal.log` à la racine du programme + fenêtre de commandes), l'ouvrir (lecture en direct), le supprimer. Désactivé : rien n'est écrit. Dates et heures
  précises ; actions humaines, actions du logiciel, requêtes à Wikipédia, erreurs ; jamais de secret.


## Photo de profil
- Page Profil : photo ronde (carte de la collection ou image de l'ordinateur), positionnement dans un éditeur rond, fichier `profil/profile.<extension>` ; une image de carte est téléchargée et reste même
  si la carte est supprimée. Incluse dans les sauvegardes complètes.
