# Wikipédia – cartes aléatoires

Tire des articles Wikipédia au hasard, les classe par rareté (L, UR, SR, R, PC, C)
selon leur nombre de vues, puis génère une page HTML de cartes.

> La **liste complète des fonctionnalités** du programme est dans `FONCTIONNALITES.md`.

## Lancer

    pip install -r requirements.txt
    python main.py

Bibliothèques obligatoires : `requests` et `cryptography` (voir `requirements.txt`). `Pillow` est facultatif (réduction des images de paquet).
Python 3.9 ou plus récent (testé avec 3.12).

Le programme ne pose plus de question : il lance le site en local et ouvre la page dans le
navigateur. **Tout se fait ensuite depuis la page** : ouvrir des paquets de cartes, parcourir
la collection, régler la configuration, exporter les cartes. **Ctrl+C** dans le terminal arrête
le serveur local.

## Base de données locale

Tout est enregistré dans un seul fichier, `data/collection.db` (SQLite, fourni avec Python :
rien à installer). Au relancement, la collection, les favoris, les filtres et les réglages sont
retrouvés tels que tu les avais laissés.

- **Cartes** : titre, description, introduction, rareté (rang), date et heure du tirage, vues,
  lien de l'article Wikipédia, lien de l'image (s'il y en a une), QR code (SVG), langue, favori.
  Chaque tirage est une carte à part : tirer deux fois le même article donne deux exemplaires.
- **Catégories** : nom, couleur de bandeau et 5 « meta », avec les liens vers les cartes
  (une carte peut avoir plusieurs catégories). Supprimer une catégorie, ou une carte, ne supprime
  que les liens : jamais les cartes ni les autres catégories.
- **Paramètres** : tous les réglages (paquets, langue, rangs et leur apparence, tailles,
  impression, système...) sont enregistrés à chaque lancement et modifiables dans la page
  Configuration. `config.py` donne les valeurs de départ. Règle : si tu modifies une valeur dans
  `config.py`, elle est prise en compte au lancement suivant ; sinon c'est la valeur enregistrée
  qui est reprise. Seuls les dossiers et `SERVEUR_LOCAL` ne sont pas modifiables depuis la page :
  un mauvais réglage pourrait la rendre inaccessible.
- **Sauvegardes** : une copie par jour dans `data/sauvegardes/` (les 7 plus récentes).
  Pour restaurer à la main, remplace `data/collection.db` par une sauvegarde.
- **Intégrité** : la base est contrôlée à chaque lancement. Si le fichier est abîmé, il est mis
  de côté (`data/corrompue_<date>.db`) et la dernière sauvegarde valide est restaurée.
- **Protection** : requêtes SQL paramétrées (pas d'injection possible), contraintes de
  validité dans la base, écritures « tout ou rien », droits d'accès limités à ton compte
  (là où le système le permet), et toute écriture venant de la page exige le code secret du
  serveur local, qui n'est joignable que depuis ton ordinateur. Les données ne sont pas
  chiffrées : ce sont des informations publiques de Wikipédia et tes réglages.
- **Déplacer ta collection** : copie le dossier `data/` dans le nouveau dossier du programme.
- **Tout effacer** : supprime le dossier `data/` (il sera recréé, vide, au prochain lancement).

## Sur la page

- **En-tête** : le **logo** en haut à gauche (lien vers la collection), puis le **titre** (par
  exemple le nom de ta collection) et, en dessous et en plus petit, une **courte biographie**.
  Logo, titre, biographie et leurs tailles se règlent dans la Configuration (section « Identité du
  site »). Le logo est aussi en haut à gauche de la page Configuration.
- **Booster** (le paquet de cartes) : au milieu de la page (la case « Afficher le paquet à ouvrir »
  de la Configuration permet de le masquer : les cartes de la collection remontent alors, et la page
  Recherche reste le moyen d'ajouter des cartes). Il n'affiche que le **logo** du jeu ;
  sans logo, il affiche le mot ou la phrase de ton choix. Au survol, il se soulève et un reflet le
  traverse ; au clic, son animation d'ouverture se joue (moins d'une seconde) et les cartes du
  paquet apparaissent en fondu en tête de la collection. Style (10 au choix : classique, or, nuit
  étoilée, holographique, braise, océan, forêt, bonbon, carbone, cosmos — ou **ta propre image**), animation (10 au choix :
  secousse, flash lumineux, rotation, envol, dissolution, rebond, tourbillon, explosion, chute, battement de cœur ; ou aucune), texte sans logo et nombre de cartes par paquet (1 à 20) se
  règlent dans la Configuration, section « Paquets et booster », avec un aperçu et un bouton
  « Tester l'animation ». Les animations ne font que déplacer et estomper le sachet : elles
  sollicitent très peu l'ordinateur, et « prefers-reduced-motion » les désactive.
- **Décompte d'ouverture** : pour ne pas surcharger Wikipédia, l'ouverture d'un paquet enchaîne
  quelques requêtes espacées d'une pause (réglage « Pause entre deux requêtes », 1 s par défaut). Un
  décompte en secondes s'affiche sous le booster (« Ouverture dans 4 s », avec une barre de
  progression) et **colle aux réglages** : le serveur le calcule d'après la pause, le nombre de
  requêtes encore à faire (le top des plus vus s'il n'est pas en mémoire, un lot aléatoire si un rang
  modeste peut sortir, puis les détails des articles) et la durée mesurée des requêtes. Il est
  recalculé en direct à chaque étape, et s'allonge si Wikipédia demande de patienter. Quand il tombe
  à 0, le tirage est terminé et **c'est là que le paquet s'ouvre**. Réglage : « Décompte avant
  l'ouverture » (`BOOSTER_DECOMPTE`).
- **Halo doré** : quand les nouvelles cartes sont révélées, un halo doré fait **doucement le tour
  de chaque carte**, dans le sens des aiguilles d'une montre, pendant 5 secondes (un tour), puis
  s'estompe. Réglages : durée (`HALO_DUREE`, 0 pour le désactiver) et couleur (`HALO_COULEUR`).
- **Menu du site** (centré sous le titre par défaut ; voir « Disposition de la page ») : Collection, Profil, Créateur de cartes,
  Recherche, Hall des collections, Configuration, corbeille. Pour en ajouter un, ajoute une ligne à `BOUTONS_ENTETE` dans
  `wikicartes/navigation.py`.
- **Clic sur une carte** (n'importe où, sauf sur les boutons) : la carte s'affiche en grand au
  milieu de l'écran, sans étoile ni lien, avec le nombre de vues par jour. Un clic, la touche
  Échap ou la croix la referment.
- **À droite de l'image**, en colonne : étoile (favori, enregistré dans la base), disquette
  (image PNG), PDF et Word. Le lien vers l'article Wikipédia est à gauche de l'étoile.
- **Lettres du rang** : en haut à gauche de chaque carte (jusqu'à 3 lettres, au choix dans la
  Configuration). Elles servent aussi aux boutons de filtre et aux noms de fichiers exportés.
- **Catégories** : de petits bandeaux colorés **juste au-dessus du titre**, sous la photo (ils ne
  masquent donc jamais l'image), avec le nom coupé à quelques caractères et terminé par « … » (le
  nom complet s'affiche au survol) ; au-delà de quelques bandeaux, un « +2 » les résume.
- **Catégorie automatique « Doublons »** : deux cartes dont le **titre est exactement le même**
  (même si leurs rangs diffèrent) sont des doublons. Elles portent un bandeau orange « Doublon ×2 »
  (en premier ; l'infobulle donne le nombre de cartes et leurs rangs) et la liste déroulante des
  catégories propose **« Doublons (N) »** : un clic n'affiche que ces cartes. Cette catégorie ne se
  crée ni ne se supprime : elle se calcule toute seule (la corbeille ne compte pas) et se met à
  jour quand une carte arrive ou part. Réglages : `DOUBLONS_ACTIFS` et `DOUBLONS_COULEUR`.
- **En haut de la page** : des boutons par rareté et « Favoris », et une liste déroulante des
  catégories (ou « Sans catégorie »), pour filtrer ta collection. Les filtres se cumulent et sont
  retrouvés au relancement. Un curseur règle la taille des cartes (↺ revient à la valeur de départ).
- **Cartes centrées** : quel que soit le nombre de cartes affiché (une seule, deux après un filtre,
  une page pleine), elles sont centrées dans la page, jamais collées à gauche.
- **Liste « Trier »** (sous les boutons de rang, à côté du filtre « Catégorie ») : l'ordre
  d'affichage de la collection, enregistré d'un lancement à l'autre :
  « Date · plus récentes d'abord » (par défaut), « Date · plus anciennes d'abord »,
  « Vues par jour · plus élevées d'abord », « Vues par jour · plus faibles d'abord »,
  « Titre · de A à Z » et « Titre · de Z à A ». L'ordre alphabétique ignore les majuscules et les
  accents (« Écosse » se range avec les E). Le tri s'applique à toute la collection, puis se
  pagine, et se combine avec les filtres.
- **Bouton « Sélection »** : affiche de petites cases à cocher sur les cartes (un clic sur la carte
  la coche aussi). Une barre permet de choisir une ou plusieurs catégories puis « Ajouter » ou
  « Retirer » pour classer les cartes cochées, ou de **« Supprimer »** les cartes cochées (elles vont
  dans la corbeille, voir plus bas). « Tout sélectionner » coche la page affichée.
- **Pagination** : la collection est découpée en pages (25 cartes par défaut, réglable dans la
  Configuration), avec des liens en haut et en bas. Les filtres s'appliquent à toute la
  collection, pas seulement à la page affichée.
- **En bas de la carte** : nombre de vues par jour, date et heure du tirage.
- **Disquette** : enregistre la carte en image PNG dans `Export/<rang>/`, avec un nom de la forme
  `L_Thierry_Henry_13102026130835.png` (rang, titre sans espaces ni apostrophes, puis date et
  heure du tirage jjmmaaaahhmmss). Cet enregistrement direct dans les dossiers passe par le
  serveur local lancé par `main.py`.
- **Boutons PDF et Word** : créent un document de deux pages, prêt à imprimer en recto verso
  puis à découper et plastifier, dans `Export/<rang>/`, avec le même nom que le PNG
  (`.pdf` ou `.docx`).
  - page 1 (recto) : la carte, comme dans le PNG ;
  - page 2 (verso) : le dos de la carte, aux couleurs de son rang, sans image d'article ni
    texte. Au milieu, le **logo du jeu** (dossier `logo/`), plus grand que le **QR code**
    placé juste en dessous, en bas de la carte. Le QR code pointe vers l'article Wikipédia
    (lien https) ; c'est le seul endroit où il apparaît. Sans logo, le QR code est centré.
  La carte est centrée à la même place sur les deux pages, avec de petits repères de coupe
  aux quatre coins : le verso tombe pile derrière le recto, quel que soit le sens dans lequel
  l'imprimante retourne la feuille. À l'impression : **recto verso**, échelle **100 % / taille
  réelle** (pas « ajuster à la page »), sinon la carte ne mesure plus 63 mm.

## Nom de la base de données

La base s'appelle maintenant **`data/collection.db`** (avant : `wikicartes.db`). Si tu avais déjà une
collection, au prochain lancement le fichier est **renommé tout seul** (avec ses annexes `-wal` et
`-shm`) : rien n'est copié ni perdu, et si `collection.db` existe déjà, rien n'est touché. Les
sauvegardes s'appellent `collection_AAAAMMJJ_HHMMSS.db` ; les anciennes (`wikicartes_*.db`) restent
reconnues et sont restaurées au besoin.

## Créateur de cartes

Le bouton **Créateur de cartes** (en haut à droite de chaque page) ouvre `/createur` : une page épurée
pour fabriquer ses propres cartes. **Chaque carte créée est unique** : elle porte son propre style et
n'appartient à aucun rang de la Configuration (rang « PERSO », jamais tirée au hasard).

- **La carte** : au centre, une carte de base **blanche**, avec le haut (illustration, lettres du
  palier) et le bas (pied) d'une carte standard. Elle se met à jour **à la volée** pendant la saisie.
- **Palier** (à droite) : un **menu déroulant** liste d'abord le palier **« Personnalisée »** (le thème de base,
  choisi au départ), puis chaque rang de la Configuration. Choisir un palier applique à la carte **ses
  couleurs, son motif, son reflet, ses lettres et son nom** : tout vient de la Configuration (il n'y a plus de
  champs « Lettres » ni « Nom du palier » dans le Créateur). Ces valeurs sont recopiées sur la carte à la
  création : elle reste unique et ne change plus si tu modifies le palier plus tard.
- **Palier « Personnalisée »** : réglé dans la **Configuration**, section « Raretés et apparence des cartes »,
  **tout en bas de la liste** : lettres (jusqu'à 5 caractères), nom, motif, trois couleurs, reflet animé, avec
  aperçu en direct et bouton « ↺ Apparence de départ de ce palier ». Il n'a ni seuil ni probabilité : il
  n'est jamais tiré au hasard. Thème d'origine : motif points, turquoise / crème / corail, reflet balayage
  (plus de carte toute blanche).
- **Contenu** (à gauche) : titre (80 caractères), sous-titre (120), description (environ le nombre de
  phrases réglé dans la Configuration : 250 caractères par phrase, de 250 à 1500), image facultative
  (JPEG, PNG, GIF ou WebP, 5 Mo), et **surnom** de la carte.
- **Pied de la carte** : uniquement le **surnom à gauche** et la **date et l'heure de la validation à
  droite** : la carte ne représente pas un article, donc ni vues, ni statistiques, ni catégories
  d'article.
- **Deux façons de créer** : « Saisie manuelle », ou « Depuis une adresse web » : colle l'adresse d'une
  page, clique sur **Charger les informations** ; le programme lit la page (titre, courte description
  s'il y en a une, début du contenu, image principale) et la carte apparaît tout de suite. Les textes sont
  **convertis en UTF-8** avant d'être placés dans les champs (jeu de caractères de l'en-tête, de la balise
  `meta`, détection UTF-8, repli Windows-1252 ; « Ã© » réparé en « é ») et **réduits à du texte brut** :
  aucune balise, entité, style, police, retour à la ligne ni espace spécial du site ; la seule mise en forme
  est celle de la carte. Tout reste
  modifiable, y compris le surnom et le style. La carte garde l'adresse de la page (icône « ouvrir »).
- **Validation finale** : « Valider et ajouter à la collection » l'ajoute comme toutes les autres cartes
  et affiche une **fenêtre de confirmation au milieu de l'écran** (la carte validée, le nombre de cartes de
  la collection, « Voir la collection » ou « Créer une autre carte » ; Échap ou un clic à côté la ferme)
  (recherche, tri, favoris, catégories à mots-clés, corbeille, vitrines, zoom, export en PNG/PDF/Word
  dans `Export/PERSO/`, **avec les couleurs, le motif et les lettres choisis à la création**, recto et verso). Les cartes personnalisées ne sont jamais des « doublons » et ne reçoivent
  aucune statistique Wikipédia.

**Sécurité** (le programme va chercher des pages choisies par toi, donc il se protège) :
- adresses http/https seulement, ports 80 et 443, sans identifiant ; **jamais ton ordinateur ni ton
  réseau local** (localhost, 10.x, 192.168.x, 172.16.x, 169.254.x dont le service de métadonnées du
  cloud, IPv6 local, etc.), vérifié sur toutes les adresses du nom ET à chaque redirection (4 au
  maximum, suivies une à une) ; limite connue : un nom de domaine qui changerait d'adresse entre la
  vérification et la connexion n'est pas bloqué ;
- 10 secondes, 2 Mo de page, 5 Mo d'image au maximum ; types de contenu contrôlés ; aucun cookie ;
- les images sont **copiées sur ton ordinateur** (`data/images/`) après vérification de leur
  *contenu* (JPEG, PNG, GIF, WebP ; jamais de SVG) : tes cartes ne contactent plus aucun site, et
  l'export en image fonctionne. Servies avec un bac à sable (aucun script ne peut s'y exécuter) ; les
  noms sont des empreintes (aucun chemin ne peut sortir du dossier) ; les images jamais utilisées sont
  nettoyées après un jour ;
- tout texte, couleur, motif ou lettre est vérifié par le serveur et affiché en texte (jamais en HTML).

## Hall des collections : partage pair à pair

Le bouton **Hall des collections** ouvre `/hall` : tu y retrouves d'autres collectionneurs, tu visites leur **profil** et leur
**collection** (lecture seule) et tu **rapatries** des copies de leurs cartes. **Aucun serveur central, aucun hébergeur** :
chaque collection reste sur la machine de son propriétaire ; les programmes se parlent directement.

**Tout est désactivé par défaut.** Rien n'est partagé tant que tu ne l'as pas décidé.

### Ton identité et ton pseudo (sans e-mail ni mot de passe)
- Ton identité est une **paire de clés Ed25519** créée sur ta machine (`data/identite_p2p.key`, droits 600, **jamais dans la
  base ni dans ses sauvegardes**). Ton **identifiant pair** est ta clé publique (52 caractères). Personne ne peut l'usurper sans
  ta clé secrète. **Sauvegarde ce fichier** si tu veux garder ton identité en changeant de machine (le perdre = nouvelle identité).
- **Pas de mot de passe** : la clé joue ce rôle. Il n'y a rien d'autre à retenir, et ce serait inutile : personne n'a de compte sur un
  serveur.
- Première visite sans pseudo : le Hall te l'explique et te propose d'en créer un (« Plus tard » possible). Sans pseudo on ne te
  trouve pas. 3 à 24 caractères (lettres de toutes langues, chiffres, espace, `_ - .`), modifiable, **supprimable** à tout moment.
- **Unicité du pseudo : au mieux, pas absolue.** Sans autorité centrale, aucun programme ne peut garantir l'unicité mondiale.
  Règle : à pseudo équivalent (« Alice », « ALICE », « Àlice », « Al.ice », « A1ice » se valent), la fiche qui l'a revendiqué **en
  premier** le garde dans ce que ton nœud connaît ; ton nœud refuse un pseudo déjà détenu ; un pair muet depuis 30 jours ne le
  bloque plus. Chaque pseudo est **toujours affiché avec un repère tiré de la clé** (« Alice·K3QZ ») qui, lui, ne s'imite pas.
  Limite connue : une ancienneté déclarée peut être falsifiée.

### Comment les nœuds se trouvent
- Chaque nœud publie une **fiche signée** (pseudo, nom de collection, nombre de cartes, pastilles P et C, adresse). Personne ne peut
  la modifier. Les nœuds se passent les fiches de proche en proche (« bouche à oreille ») : il n'y a **pas de moteur de
  recherche global**, ton Hall liste les collectionneurs que ton nœud connaît.
- **Au début, colle l'invitation** d'un collectionneur (« wcp1:… », bouton « Copier » dans « Mon partage » de l'autre personne) dans
  « Ajouter un collectionneur » : tu apprends ensuite ceux qu'il connaît. Un seul premier contact suffit.
- Pastille **verte** : accepté et collectionneur en ligne ; **rouge** : refusé par le propriétaire (information fiable, signée) ;
  **grise** : accepté mais hors ligne ou pas vu récemment.
- Il faut que l'autre soit **en ligne** pour voir sa collection (rien n'est stocké ailleurs).

### Mettre ton nœud en ligne
1. `pip install cryptography` (nouveau prérequis, listé dans `requirements.txt`).
2. **Mode Tor (recommandé)** : aucune ouverture de port, **ton adresse IP reste cachée**, et ton adresse « .onion » est dérivée de
   ta clé (se connecter à elle prouve que l'on parle au propriétaire de la clé). **Tor doit tourner sur ta machine pendant que ton
   nœud est actif** (et aussi pour visiter les collectionneurs qui passent par Tor).
   **Si Tor est absent, le Hall le détecte et l'explique à l'écran** : une alerte apparaît dans « Mon partage » (« Tor n'est pas
   détecté… »), avec « Que faire ? » (fenêtre d'aide pas à pas : liens de téléchargement, torrc à copier, deux façons) et « Lancer
   Tor ». La même aide s'ouvre toute seule quand tu actives ton nœud sans Tor. Deux façons, au choix :
   - **Avec le navigateur Tor (le plus simple)** : installe le *Navigateur Tor* (torproject.org/download), **ouvre-le et laisse-le
     ouvert**. Il utilise les ports 9150 et 9151 : le programme les essaie tout seul quand tes réglages gardent leurs valeurs d'origine.
   - **Avec Tor seul (« Tor Expert Bundle », torproject.org/download/tor)** : décompresse-le (Bureau, « Téléchargements » ou
     `C:\Tor`), puis clique sur **« Lancer Tor »** dans le Hall : le programme trouve `tor.exe`, écrit lui-même le fichier `torrc`
     (dans `data/tor/`) et le lance. Il cherche `tor.exe` dans le réglage « Partage : chemin de tor.exe », le PATH, le Bureau, les
     Téléchargements, `C:\Tor`… et **ne lance jamais autre chose qu'un programme nommé `tor` ou `tor.exe`**. À la main : crée un
     fichier `torrc` à côté de `tor.exe` avec `SocksPort 9050`, `ControlPort 9051` et `CookieAuthentication 1`, puis `tor.exe -f torrc`
     (fenêtre laissée ouverte). Sous Linux : `sudo apt install tor`, mêmes lignes dans `/etc/tor/torrc`, `sudo systemctl restart tor`,
     et ton utilisateur dans le groupe `debian-tor`.
   - **Case « Lancer Tor automatiquement au démarrage du programme »** (dans l'aide, ou Configuration → Partage) : si Tor n'est pas
     déjà lancé, le programme le lance à chaque démarrage et **l'arrête en se fermant** (il n'arrête jamais un Tor que tu as lancé
     toi-même ou le navigateur Tor). Tor met 1 à 2 minutes à se connecter la première fois.
   **Patience :** quand tu actives ton nœud, le Hall affiche « patiente une à deux minutes avant de tester » (avancement de Tor, puis
   publication du service) et le retire tout seul quand le nœud est prêt. Une **première connexion via Tor** vers un collectionneur (ou vers
   ta propre collection) peut prendre jusqu'à une minute : le délai est de 75 secondes avec un nouvel essai automatique. Si Tor est fermé
   puis relancé, le programme **republie ton service tout seul** (vérification toutes les 20 secondes).
   Alternatives sans Tor : **Direct** (port ouvert, adresse publique : ton adresse IP est visible de tes visiteurs) ou **Local** (essais).
3. Dans le Hall, « Mon partage » (ou Configuration → « Partage entre collectionneurs ») : coche **Activer mon nœud**, puis
   **Profil visible (P)** et/ou **Collection visible (C)**.

### Ce que les autres voient (et ne voient jamais)
- Visibles si tu coches P : titre et biographie du site, résumé, vitrines. Si tu coches C : tes cartes, en lecture seule, avec leurs
  titres, sous-titres, descriptions, rangs (lettres, noms, couleurs, motifs : **elles s'affichent comme chez toi**), catégories,
  vues, statistiques et images (adresses Wikimedia ; images des cartes personnalisées envoyées par ton nœud).
- **Jamais** : tes favoris, ta corbeille, tes réglages et ta configuration, tes catégories automatiques, ton e-mail de contact, les
  chemins de ton disque, ta clé secrète. La liste des champs envoyés est une liste blanche (`partage.py`).
- **Personne ne peut supprimer tes cartes, changer leur catégorie ni leur aspect, ni modifier tes réglages** : le serveur pair à
  pair est **séparé** de ta page locale (autre port, autre code, **sept adresses** seulement, toutes en lecture ; seule écriture
  possible : ranger la fiche signée d'un autre collectionneur dans l'annuaire), et il lit la base avec une connexion **en lecture
  seule** (SQLite refuse toute écriture). Les pastilles P et C sont appliquées **chez toi** : un visiteur ne peut pas les contourner.
- Chaque réponse de ton nœud est **signée** (liée à la requête) : le visiteur sait que c'est bien toi et que rien n'a changé en route.
- Protections : 8 connexions simultanées au plus, débit limité, requêtes et corps bornés, aucune redirection.

### Visiter, filtrer, rapatrier
- Le **résumé** (nombre de cartes, rangs, catégories) est en tête du **profil** ; dans la **collection**, ces informations sont déjà
  dans la barre de filtres (rangs avec leur nombre, catégories avec leur nombre entre parenthèses), sous la ligne « N cartes ·
  collection en lecture seule ».
- Cliquer sur le **pseudo** ouvre d'abord son **profil**, cliquer sur le **nom de la collection** ouvre d'abord sa **collection**. Sur
  chaque page : un bouton vers l'autre page, et **Quitter** (retour au Hall). En tête : titre du site et biographie du
  collectionneur, nombre de cartes, rangs et **catégories avec leur nombre entre parenthèses**.
- La collection d'un autre se **filtre et se trie** comme la tienne (rang, catégorie, titre, tri, pages ; boutons de page **en haut et en bas**) : c'est son nœud qui répond.
  Les cartes ont **son** thème. Le zoom marche comme d'habitude. Pas d'icônes d'export ni d'étoile.
- Coche des cartes (clic sur la carte ou sa case) puis **Rapatrier** : ton nœud demande les cartes à l'autre et les recrée **sans
  aucune requête vers Wikipédia** (titre, sous-titre, introduction, adresses de l'article et de l'image, vues, statistiques). Le
  **horodatage est celui de maintenant** ; le **rang est recalculé avec tes seuils** d'après les vues (les cartes personnalisées
  gardent leur thème) ; **tes catégories** s'appliquent. Cartes déjà chez toi : signalées « Dans ta collection ».
  Ton navigateur charge toujours les miniatures depuis les serveurs Wikimedia, comme pour ta propre collection.

### Sécurité des données reçues
Tout ce qui vient d'un autre nœud est traité comme **hostile** : types et longueurs vérifiés, couleurs, motifs et reflets dans des
listes fermées, adresses d'article et d'image limitées à Wikipédia/Wikimedia, images vérifiées par leur contenu (jamais de SVG),
texte nettoyé puis **échappé** à l'affichage (un pair ne peut injecter ni script ni style). Une carte douteuse est écartée sans
bloquer les autres. Les adresses déclarées par un pair ne mènent jamais vers ta machine ni ton réseau local.

### Limites à connaître
- Je n'ai pas pu tester avec le vrai réseau Tor ni sur Internet : le protocole, la sécurité, les transports (clients SOCKS5 et port de
  contrôle de Tor contre des simulations conformes aux spécifications) et un réseau de plusieurs nœuds en local sont testés.
- L'unicité des pseudos et la découverte sont « au mieux » ; un réseau décentralisé reste exposé à des fiches factices en masse
  (l'annuaire garde 3000 fiches) et à la saturation d'un nœud.
- Seule l'authentification par **cookie** (ou sans authentification) du port de contrôle de Tor est gérée, pas le mot de passe.

## La page Configuration

- **Ordre des sections** : d'abord ce que tu règles couramment (Identité, Apparence, Disposition, Paquets, Raretés, Collection, Profil,
  Export), puis les réglages **avancés** (Wikipédia, Réserve), puis le plus complexe, le **Hall des collections** (partage pair à pair,
  Tor), et **tout à la fin le Système** (informations en lecture seule). Les sections avancées portent une étiquette « avancé ».
- **Menu « Aller à »** en haut de la page, juste avant les blocs de réglages : un lien par section, qui reste **collé en haut de l'écran**
  quand on défile et **met en avant la section visible**. Clic ou clavier (Tab puis Entrée) : on arrive sur la section, sous le menu.
  Sur téléphone il défile de côté dans son cadre.
- Chaque section a une phrase d'explication sous son titre.
- **Barre flottante du bas** : Enregistrer, Tout remettre aux valeurs de départ, l'état, et à droite **« ↑ Remonter »** qui ramène tout en
  haut de la page (sans rien enregistrer).

## Disposition de la page (menu, barre d'outils, paquet)

Configuration → **« Disposition de la page »** : quatre réglages, avec une **maquette en direct** (le cadre représente l'écran : ce
qui dépasse en bas demande de défiler). Le menu de la page Configuration change aussi tout de suite.
- **Menu : emplacement** : *centré sous le titre* (défaut), *à droite* (disposition d'origine), *colonne à gauche* (écrans de 1100 px et
  plus ; sinon il repasse centré).
- **Menu : taille des boutons** : *complet*, *compact* (défaut), *icônes seules* (le nom reste en info-bulle et pour les lecteurs
  d'écran), *replié* (un bouton « ☰ Menu », sans JavaScript).
- **Barre d'outils** (rangs, recherche, catégorie, tri, sélection, taille) : *compacte* (défaut : centrée, étiquettes masquées, une seule
  ligne), *centrée*, *à gauche* (d'origine), *repliable* (bouton « Filtres, tri et taille »).
- **Paquet** : *remonté* (défaut : sachet plus petit, légende à côté), *compacte* (petit sachet, **texte en dessous**), *très compact*
  (tout petit sachet, texte à côté), *normal* (d'origine).
- **Alignement du titre, de la biographie et de la ligne d'infos** (« 44 cartes dans la collection · … ») : chacun à gauche, au milieu
  ou à droite, séparément, sur toutes les pages ; la maquette et l'en-tête de la page Configuration le montrent en direct.
- **Menu à gauche en colonne** : la corbeille s'ouvre alors comme un **message au milieu de l'écran** (le reste s'assombrit ; clic à côté
  ou Échap pour fermer), car sa petite fenêtre habituelle sortait de l'écran.
Avec le menu centré, un petit espace sépare le menu de la ligne des rangs et de la barre d'outils. Avec les réglages par défaut, sur un écran de 688 px de haut, la première rangée de cartes est visible dès l'ouverture (elle commençait
sous le bord de l'écran avec l'ancienne disposition).

## Paquets, animations et reflets

- **10 styles de paquet** (classique, or, nuit, holo, braise + **océan, forêt, bonbon, carbone, cosmos**) et **10 animations d'ouverture**
  (secousse, flash, rotation, envol, dissolution + **rebond, tourbillon, explosion, chute, battement de cœur**), à choisir dans la
  Configuration (aperçu et bouton « Tester »).
- **10 reflets animés** pour les rangs et le palier « Personnalisée » (balayage, pulsation, étincelles, arc-en-ciel, vague montante +
  **faisceau tournant, balayage croisé, paillettes scintillantes, aurore, contour néon**). Les **étincelles** changent d'endroit à chaque
  passage (3 placements qui se suivent). Les animations s'arrêtent si ton système demande « réduire les animations ».

## Catégories automatiques : Doublons, Sans illustration, Animée

- **Animée** (nouveau, activée par défaut) : les cartes dont l'illustration affichée est un **GIF** reçoivent un bandeau « Animée » et
  l'entrée existe dans la liste « Catégorie » (ouverture d'un paquet, page Recherche, rapatriement depuis le Hall, cartes déjà en
  collection). Case, nom et couleur dans Configuration → Collection.
- **Les trois noms sont modifiables** (Configuration → Collection) : 1 à 30 caractères, sans balise ni « & », et différents entre eux.
  Le bandeau des doublons en est la forme au singulier (« Doublons » → « Doublon ×2 »).

## Ton propre paquet (image personnalisée)

Configuration → **Paquets et booster** → « Choisir une image… » : un **PNG ou JPEG** (5 Mo au plus). Il est vérifié par son contenu,
réduit à 1200 px s'il est très grand (si la bibliothèque **Pillow** est installée : `pip install pillow`, facultatif) et rangé dans
`data/images/` ; le style « Image personnalisée » est alors choisi pour toi. Tu règles ensuite :
- la **forme** : proportions de l'image (elle s'adapte), rectangle vertical, rectangle horizontal, carré ou rond ;
- le **cadrage** : recadrer (l'image remplit la forme) ou image entière (rien n'est coupé) ;
- **ce qu'on place dessus** : rien (juste l'image), le logo du jeu ou le texte du booster.
Le paquet reste contenu dans la même boîte que les sachets prêts à l'emploi (pas plus de 1,5 × sa largeur de haut ni 1,65 × de large :
une image énorme ou une bande très étroite ne prend jamais l'écran) et suit le réglage « Paquet à ouvrir : place dans la page ». Les 10
animations d'ouverture s'appliquent à ton image quelle qu'elle soit. « Retirer l'image » revient au sachet classique.

## Chemin de tor.exe

Par défaut : `<racine du programme>\tor\tor.exe`, pré-saisi dans le champ (Configuration → Hall des collections). Écris les dossiers
avec `\` ou `/` : le programme comprend les deux (et retire les guillemets de « Copier comme chemin »), il enregistre `/` et affiche `\`
sous Windows. Seul un programme nommé `tor` ou `tor.exe` peut être lancé.

## Petits réglages de confort

- **Taille des cartes** (curseur de la page Collection) : enregistrée **à la volée**, dès qu'on bouge le curseur (un petit « ✓ enregistrée »
  s'affiche), même si on quitte la page tout de suite. Enregistrer la Configuration ne la remet plus à zéro : le champ « Largeur des cartes »
  de la Configuration n'est envoyé que si on le modifie soi-même.
- **Emojis dans le titre et la biographie** : tous permis (simples 🎴, drapeaux 🇫🇷, couleurs de peau 👍🏽, cœur ❤️, familles 👨‍👩‍👧, métiers
  👩🏽‍🚀, drapeaux régionaux 🏴󠁧󠁢󠁳󠁣󠁴󠁿). La limite (60 et 160 caractères) compte ce qu'on **voit** : un emoji compte pour 1. Ils passent aussi dans le
  partage (nom de collection du Hall).
- **Choisir une carte pour une vitrine** (page Profil) : la recherche porte sur le **titre, le sous-titre et la description** ; chaque mot
  doit se trouver dans l'un des trois, et les cartes dont le titre correspond passent d'abord. La recherche de la page Collection reste
  limitée au titre.

## Nouveautés de cette version

- **Page Recherche** : 20 résultats par défaut ; bouton **« Voir 20 résultats de plus »** (Wikipédia ne donne que 20 introductions par
  requête, d'où les lots de 20 ; jusqu'à 200 résultats) ; résultats rangés **les plus vues d'abord** (liste « Trier » : ou ordre de
  Wikipédia, ou titre) ; **pagination en haut et en bas** ; sélection possible sur plusieurs pages ; rapatriement jusqu'à 100 cartes
  d'un coup (chargées par lots de 20).
- **Choisir une carte pour une vitrine** : filtres par rang (boutons cumulables) et tri (pertinence, date, titre A→Z / Z→A) ; la
  recherche porte sur le titre, le sous-titre et la description.
- **Paquet** : taille **normale** avec le texte en dessous par défaut ; **effet au passage de la souris** (mêmes choix que les cartes) et
  **animation au repos** (mêmes choix que la carte agrandie) dans Configuration → Paquets et booster ; à l'ouverture, les cartes
  arrivent **des plus communes aux plus rares**.
- **Doublons** : deux cartes sont des doublons si elles sont **identiques** : même titre, **même rang**, même sous-titre, même description, **même image** et même
  **taille et position de l'image** (une carte créée à la main compte aussi son surnom). Un L et un R ne sont donc jamais des doublons. Changer l'image d'une des deux,
  ou la redimensionner autrement, en fait deux cartes différentes ; remettre la même image et le même cadrage en refait des doublons. Le réglage de
  position et de taille est propre à chaque carte ; une nouvelle carte identique à une précédente (même article, même image) reprend le dernier
  réglage.
- **Top des plus vus** : si Wikimedia n'a pas encore publié le mois dernier (réponse 404, fréquent en début de mois), le programme
  prend le mois d'avant au lieu de signaler un incident.
- **Page Paquets, contenu sensible flouté, ⟳ rafraîchir l'image, accès réseau avec code, Hall uniquement par Tor** (voir plus bas) ;
- **Cartes par paquet : 5, 10 ou 20**, avec un stock de 10, 3 ou 1 paquets prêts qui se reconstitue en 1 heure ; légende « Ouvrir un paquet · 5 cartes ·
  1 paquet prêt sur 10 » et décompte « Prochain paquet dans » en minutes et secondes, de la taille du paquet ; **musique sans coupure** entre les pages,
  haut-parleur avec curseur de volume (choix gardé), son de la carte retirée ;
  **sons et musique d'ambiance** ; icônes d'export placées à la suite sous l'étoile.
- **Paquet bloqué tant que la réserve n'est pas complète** : le paquet reste visible mais un clic ne fait rien ; un décompte en minutes
  indique quand le prochain sera prêt (voir « Réserve et ouverture des paquets » plus bas). Case dans Configuration → Réserve.
- **Fenêtre des cartes** : à l'ouverture, les cartes apparaissent au milieu de l'écran, une à une ; on peut en retirer (✕, supprimées tout
  de suite) puis « Ajouter à la collection ». Case dans Configuration → Paquets.
- **Statistiques avec la carte** (voir plus bas), **confettis et paillettes** à la disparition du paquet (un effet par animation),
  **sauvegardes** en 4 types dans Configuration → Système, logo « centré à gauche / à droite du titre », doublons des cartes
  personnalisées (titre, sous-titre, description et surnom identiques).
- **5 nouveaux thèmes du site** : Années 80-90 fluo new age, Arcade rétro 8 bits, Jeu de société, Chic tendance, Album de cartes à
  collectionner.

## Réserve et ouverture des paquets

- **Cartes par paquet : 5, 10 ou 20.** Ce choix fixe le **stock de paquets prêts** : 5 cartes = 10 paquets, 10 cartes = 3 paquets, 20 cartes =
  1 paquet. Une réserve de 50, 30 ou 20 cartes (avec leurs statistiques) est préparée d'avance.
- Le stock se **reconstitue peu à peu** : un paquet toutes les 6 minutes (paquets de 5), 20 minutes (10) ou 60 minutes (20), donc tout le stock en
  1 heure. Ouvrir un seul paquet de 10 ne bloque rien (il en reste 2) ; ouvrir les 3 annonce environ 20 minutes pour le suivant.
- La légende indique le stock : « Ouvrir un paquet · 5 cartes · 1 paquet prêt sur 10 », et dessous « Prochain paquet dans » avec un **décompte en
  minutes et secondes** (tant que le stock n'est pas plein). À « 0 paquet prêt », le paquet reste **visible** (animations comprises) mais **un clic ne
  fait rien**. La case « Bloquer l'ouverture... » (Configuration → Réserve) le
  désactive ; sans pré-chargement actif, rien n'est jamais bloqué.
- Le décompte est le plus long de deux temps : celui de reconstitution du stock, et celui de préparation des cartes d'un paquet (requêtes à
  faire : tirage, détails, langues, 2 requêtes de statistiques par carte ; pause du pré-chargement (3 s) plus la durée mesurée d'une requête ;
  pause de Wikipédia en cours ; **plafond horaire** de requêtes (120 par défaut) simulé sur le journal réel).
- Le **pré-chargement repart dès qu'un paquet est ouvert** : d'abord de quoi former un paquet, puis le reste du stock, doucement (une requête à la
  fois, pauses, plafond horaire, arrêt si Wikipédia ralentit).
- **Fenêtre des cartes** : les cartes sont déjà enregistrées quand elle s'ouvre ; retirer une carte (✕) la supprime pour de bon, uniquement parmi
  les cartes du dernier paquet et pendant 1 heure ; « Ajouter à la collection » (ou Échap) les fait entrer dans la page.

## Page Paquets, contenu sensible, rafraîchissement d'image

- Le programme s'ouvre sur la page **Paquets** (`/paquets`) : le paquet, la légende « k paquets prêts sur N » et le décompte. Les cartes que tu
  ajoutes s'y rangent dessous ; la page **Collection** est à l'adresse `/`.
- **Contenu sensible** : section de la Configuration. **Aucune liste n'est fournie** : tu écris la tienne (un mot ou une expression par ligne). Liste
  vide = rien n'est flouté. Les cartes qui contiennent un de tes mots ont leur image floutée (le texte reste) et une icône +18 sous l'étoile ; tu règles
  aussi les exceptions et l'intensité.
- **⟳ rafraîchir l'image** (Apparence, désactivé par défaut) : cherche l'illustration de l'article ; enregistrée sur la carte si elle est apparue.
- **Hall des collections : uniquement Tor.** Réglage « Tor : relais d'entrée du même pays » : plus rapide, anonymat légèrement moins bon.

## Accès depuis un téléphone, le réseau local ou l'extérieur

Par défaut seul cet ordinateur peut ouvrir le programme (127.0.0.1). Pour l'utiliser depuis un autre appareil : Configuration → **Accès réseau** →
« Réseau local et extérieur », enregistre et **relance le programme**. Il devient un vrai serveur : tant qu'il tourne sur ton PC, tout appareil qui
atteint son adresse l'utilise directement (ouvrir un paquet, modifier la collection...), **sans mot de passe**.
- **Réseau local / téléphone** : tape l'adresse affichée dans la console et dans la Configuration (`http://192.168.x.x:8765/`). Si elle ne répond pas,
  c'est presque toujours le **pare-feu Windows** : accepte la fenêtre « Autoriser l'accès » (réseaux privés) ou, dans une invite de commandes
  ADMINISTRATEUR : `netsh advfirewall firewall add rule name="WikiCartes 8765" dir=in action=allow protocol=TCP localport=8765 profile=private,domain`.
  Le programme teste chaque adresse au lancement et l'indique. Les adresses 192.168.56.x (VirtualBox) ou 172.x (WSL/Docker) ne servent qu'aux machines
  virtuelles.
- **Tunnel** (ngrok, Cloudflare Tunnel, Tailscale Funnel...) : pointe-le vers `http://127.0.0.1:8765` ; ça marche tel quel, en http comme en https.
- **Adresse IP publique** : ouvre le port de ta box vers cet ordinateur (sans HTTPS).
- **Attention** : sans code, quiconque atteint l'adresse peut tout faire. Un **code d'accès facultatif** (Configuration → Accès réseau, vide par défaut)
  limite ce qui ne vient pas de ton PC.

## Recherche, logo, cartes validées

- **Recherche** : section « Recherche de cartes » : des cases titre / sous-titre / description pour la page Collection, la page Recherche et le
  Profil. Par défaut titre et sous-titre seulement.
- **Logo au-dessus du menu** (Disposition) : en haut de la colonne de gauche quand le menu est en colonne.
- Les cartes validées après l'ouverture d'un paquet vont directement dans la collection (la page Paquets ne les affiche pas).

## Détails récents

- **Icône +18** : montrer ou flouter l'image d'une carte sensible est **gardé** d'un lancement à l'autre.
- **Configuration** : les réglages avancés (Wikipédia, Réserve, Hall, Accès réseau, Système) ne sont visibles que depuis cet ordinateur et le **réseau
  local** (case « Réglages avancés : réseau local seulement » dans Système, cochée par défaut). Depuis une adresse publique ou un tunnel, ils sont
  absents de la page et refusés par le serveur.
- Le pied de page est centré sur le contenu, même avec le menu en colonne à gauche.

## Affichage sur téléphone

Configuration → Apparence : « **Affichage sur téléphone** » (automatique par défaut, toujours, jamais) et « **Téléphone : en-tête** » (compact par défaut,
minimal, complet). En automatique, l'affichage s'optimise dès que l'écran est étroit ou tactile : menu en icônes, filtres et tri derrière un bouton
« Filtres », cartes sur deux colonnes, bio et infos masquées (en-tête compact). Il se rétablit si la fenêtre s'élargit.

## Full-art et GOD PACK

- **Full-art** : Créateur de cartes → onglet « ✨ Full-art ». Dépose des fichiers **.png** dans les dossiers `zuul/` et `gozer/` (à côté de `main.py`) ; leurs noms (sans `.png`) remplissent
  les listes « Zuul » (premier calque) et « Gozer » (par-dessus). Choisis une carte, des effets (3 au plus), puis « Appliquer ».
- **GOD PACK** : Configuration → Paquets : « 1 chance sur N » (10 000 par défaut, 0 = jamais) et un bouton pour voir l'animation.

## Images d'une carte sans illustration

Avec l'icône ⟳ (Apparence → « choisir l'illustration »), une carte liste toutes les images de son article Wikipédia en vignettes : choisis celle qui l'illustrera (puis valide), ou retire son illustration ; tu peux en remettre une quand tu veux. Sans effet sur les cartes full-art et personnalisées.
Un full-art est **définitif** (une confirmation est demandée : la carte ne pourra plus revenir à son état d'origine). Le full-art fournit 10 Zuul et 10 Gozer d'exemple dans `zuul/` et `gozer/` ; ajoute les tiens (fichiers `.png`), supprime ceux que tu n'aimes pas.

## Sons et musique

Configuration → **Sons et musique**. Un fichier son (mp3, ogg, opus, wav, m4a, aac, flac ou webm, 60 Mo au plus) se choisit pour chaque événement :
ouverture du paquet, **chaque carte** de la fenêtre du paquet, **carte retirée de la fenêtre (✕)**, arrivée dans la collection, cartes à la
corbeille, restauration, suppression définitive. Dépose tes fichiers dans le dossier `sons` à côté de `main.py` ou téléverse-les depuis la page (le
contenu est vérifié) ; ▶ écoute un fichier. Aucun son n'est fourni.

**Musique d'ambiance** : activée ou non, fichier, volume, en boucle. Elle joue dans un **lecteur** (la fenêtre du haut affiche chaque page dans un
cadre plein écran), donc **elle ne se coupe plus quand tu changes de page**. En bas à gauche, un **haut-parleur** 🔊 et un **petit curseur de volume**
à sa droite : un clic sur le haut-parleur le barre (🔇), la musique se coupe et le curseur disparaît. **Ce choix et le volume sont gardés** : au
prochain lancement, la musique repart toute seule si elle n'était pas coupée. Un navigateur normal exige un premier clic avant de lancer un son : le
haut-parleur pulse alors, et la musique démarre dès ton premier clic. Pour qu'elle démarre **sans aucun clic**, coche « Lancer dans une fenêtre
d'application » : le programme s'ouvre dans une fenêtre d'Edge ou de Chrome à part (profil `data/navigateur`, son autorisé) ; sans Edge ni Chrome, le
navigateur habituel est utilisé. Le dossier `sons` est dans les sauvegardes (hors « Uniquement la collection »).

## Sauvegardes (Configuration → Système)

Quatre types, chacun étant un fichier **.zip** rangé dans `data/sauvegardes/archives/` : **Ultra complète** (paramètres actuels + collection +
arborescence complète du programme), **Complète** (paramètres + collection), **Uniquement les paramètres**, **Uniquement la collection**.
On peut **créer**, **exporter** (télécharger), **importer** un .zip (il est d'abord vérifié, rien n'est changé), **restaurer** (une
confirmation dit ce qui sera remplacé) et **supprimer**.
- Avant toute restauration, l'état actuel est sauvegardé tout seul (fichier « avant-restauration-… »).
- La **clé secrète d'identité** du Hall (`data/identite_p2p.key`) n'est dans AUCUNE sauvegarde, sauf si tu coches la case réservée à
  l'ultra complète : ne partage alors jamais ce fichier. Pour garder ton identité sur un autre ordinateur sans cela, copie le fichier toi-même.
- Restaurer une sauvegarde **ultra complète** remet les paramètres et la collection, mais **n'écrase jamais le programme en cours** :
  ses fichiers sont extraits dans `data/restaurations/<date>/`, à toi de les récupérer.
- Restaurer des paramètres remet d'abord tous les réglages à leur valeur de départ, puis applique ceux de la sauvegarde qui sont
  valides (les autres sont ignorés et listés). Restaurer une collection remplace cartes, catégories, vitrines, corbeille, réserve et annuaire
  du Hall, mais jamais les paramètres.
- Une archive piégée est refusée : chemins dangereux, liens, « bombe » de décompression, base abîmée ou plus récente que le programme.
  Les adresses douteuses d'une collection importée sont écartées.
- La création de l'ultra complète peut prendre un moment ; les dossiers `data/sauvegardes/`, `data/tor/`, les caches Python et
  `data/restaurations/` n'y sont pas repris.

## Statistiques avec la carte

Les modifications et les liens entrants d'un paquet sont récupérés **pendant l'ouverture**, hors plafond horaire (une requête chacun, pause
de 0,3 s par défaut : un paquet de 6 cartes demande une dizaine de secondes de plus, le décompte en tient compte). Les cartes préparées d'avance
(réserve) les reçoivent dès leur préparation, donc s'ouvrent instantanément ET complètes. Si Wikipédia limite le débit ou tombe en panne, le paquet
s'ouvre quand même et le fil de fond complète le reste poliment (plafond horaire, comme avant). Réglages (Configuration → Réserve) :
« Statistiques complètes à l'ouverture d'un paquet » et « Pause entre deux requêtes de statistiques d'un paquet ».

## Recherche : aucune statistique

Les cartes de la page **Recherche** n'affichent en bas que les **vues par jour** (ni statistiques, ni date et
heure), et la recherche ne dépense **aucune requête de statistiques** : une seule requête Wikipédia pour tous
les résultats. Quand tu rapatries des cartes dans la collection, une seule requête relit leurs détails ; les
langues, modifications et liens entrants sont ensuite récupérés **en arrière-plan** (avec la politesse
habituelle), seulement pour les cartes que tu as gardées.

## Carte agrandie : icônes visibles et actives

Quand tu cliques sur une carte de la collection (ou de ton profil), la carte agrandie affiche aussi ses
**icônes** : lien vers l'article, étoile des favoris, disquette (PNG), PDF et Word (selon les réglages
d'apparence). Elles **fonctionnent** : l'étoile met la vraie carte en favori (et se met à jour sur la carte
agrandie), les trois autres exportent la carte, le lien s'ouvre dans un nouvel onglet ; l'aperçu reste
ouvert. **Aucune icône n'est jamais incluse dans les images, PDF et Word exportés** : l'export part de la
vraie carte, dont les boutons sont retirés. Tab fait le tour de ces icônes sans sortir de l'aperçu.

Sur la page **Recherche**, un clic sur l'**image** d'un résultat l'affiche aussi agrandi, avec les mêmes
animations (réglage « Animation de la carte agrandie ») ; seul le lien vers l'article y est gardé (l'article
n'est pas encore dans ta collection). Un clic ailleurs sur la carte la coche toujours.

## Statistiques sous les cartes

Le pied de chaque carte affiche, de gauche à droite : les **vues par jour**, puis quatre statistiques
(que des chiffres, avec une info-bulle) et la date de tirage tout à droite :

| Icône | Statistique | Source |
|---|---|---|
| 🌐 52 | langues disponibles : **les liens interlangues de la page, exactement le « N langues » que Wikipédia affiche** (la langue de l'article n'est pas comptée) | `prop=langlinks` (1 requête pour tout le paquet, suite lue si Wikipédia découpe sa réponse) |
| ✏️ 1.2k | modifications de la page : le « nombre total de modifications » de la page « Informations sur la page » (« 30k+ » au-delà du plafond de 30 000 de l'API) | API REST de Wikipédia |
| 🔗 284 | articles de Wikipédia qui pointent vers l'article (espace principal) : ce n'est PAS le total de « Pages liées », qui inclut aussi les pages de discussion, les redirections, etc. | recherche `linksto:` |
| 📄 42 | taille de l'article en Ko : la « taille de la page » de Wikipédia (43 008 octets = 42 Ko) | requête des détails (sans coût) |

- **Langues et taille arrivent avec la carte** (une requête de plus par paquet). **Modifications et
  liens entrants** demandent une requête chacun, page par page : un fil de fond les récupère juste
  après l'ouverture, **doucement** (cartes les plus récentes d'abord), et la page se met à jour toute
  seule : un « – » grisé s'affiche en attendant. Jamais de chiffre inventé.
- **Même politesse que la réserve** : une requête à la fois, pause `RESERVE_PAUSE`, **plafond horaire
  propre aux statistiques** (`STATS_REQUETES_HEURE`, 120 par défaut, compté dans la base), arrêt et
  attente doublée à chaque échec, `Retry-After` respecté, priorité à tes ouvertures et recherches. Une
  carte dont la page ne répond pas (404) est abandonnée après 3 essais. Les cartes déjà présentes dans ta
  collection sont complétées progressivement de la même façon.
- Les vues par jour s'affichent en entier jusqu'à 9 999 (« 2 064 »), puis en compact (« 12k », « 1.2M ») pour que le pied ait la même forme sur toutes les cartes ; le nombre exact est dans l'info-bulle.
- Réglage « Statistiques sous les cartes » (`STATS_CARTES`) : décoché, rien n'est affiché ni demandé.
- **Toujours sur une seule ligne** : vues par jour à gauche, statistiques au milieu, date et heure à droite,
  quelle que soit la taille des cartes (curseur de taille, carte agrandie, images exportées) et la police de
  ton navigateur. Jamais de seconde ligne. Si tout ne tient pas, le pied se **compacte par étapes** (le
  moins important d'abord) : 1. le « /jour » disparaît ; 2. l'horloge ; 3. les statistiques se resserrent ;
  4. la date (jour/mois) disparaît, l'heure reste ; 5. en dernier recours, les statistiques sont masquées.
  Les statistiques sont exactement au centre quand les deux côtés sont assez étroits, sinon au milieu de la
  place restante. La mesure se fait **séparément** pour les cartes de la page (même niveau pour toutes), pour
  la carte agrandie (sa propre taille) et pour chaque image exportée en PNG, PDF ou Word (à la taille de
  l'image : une carte étroite à l'écran n'appauvrit donc pas l'export).

## Recherche dans la collection

Un champ « Rechercher une carte… » dans la barre d'outils de la collection (avant la liste des
catégories) cherche dans le **titre** des cartes :
- **plusieurs mots** possibles : une carte doit tous les contenir, dans n'importe quel ordre
  (« vinci leonard » trouve « Léonard de Vinci ») ; un morceau de mot suffit (« ron » : Ronaldo,
  Ronaldinho) ;
- **accents et majuscules ignorés** dans les deux sens (« ECOSSE » trouve « Écosse ») ;
- la recherche part toute seule 0,5 s après la dernière touche, ou tout de suite avec Entrée ; Échap
  ou le bouton « × » l'efface ; elle se combine avec les filtres de rang, les favoris, la catégorie et
  le tri, se pagine, et est mémorisée comme eux ;
- le texte est traité comme du texte : `%`, `_`, guillemets et tentatives d'injection SQL sont sans
  effet (requêtes paramétrées).

## Page de profil et vitrines

Le bouton **Profil** (en haut à droite de chaque page) ouvre `/profil` :
- **En-tête** : le titre et la courte biographie du site.
- **Résumé** : le nombre total de cartes de la collection, un logo par rang (la lettre attribuée dans
  la Configuration, avec les couleurs du rang) suivi du nombre de cartes, et une étiquette colorée par
  catégorie avec son nombre de cartes.
- **Vitrines** : des lignes d'emplacements vides (traits en pointillés). Un clic sur un emplacement
  ouvre la liste de tes cartes (recherche par titre, les plus récentes d'abord, « déjà en vitrine »
  signalé) ; choisis-en une, elle apparaît dans l'emplacement sans recharger la page. « Changer » et
  « Retirer » apparaissent au survol d'un emplacement occupé.
- **Une vitrine montre une COPIE** : la carte reste dans ta collection, intacte, et peut être exposée à
  plusieurs endroits. Les cartes de vitrine sont épurées : **ni icône d'ouverture Wikipédia, ni
  export, ni vues, statistiques ou date, ni catégories** (restent l'illustration, le rang, le titre, la
  description et l'étoile des favoris). Elles s'agrandissent au clic, toujours épurées.
- **Aucun ascenseur** : chaque vitrine est une ligne fixe, les cartes se partagent la largeur.
- **Titre de chaque vitrine** : se tape directement dans le champ au-dessus de la ligne (lettres,
  chiffres, espaces, ponctuation courante et **emoji** : 🏆 ⚽ 🇫🇷 👨‍👩‍👧 1️⃣…) et s'enregistre tout seul
  (40 caractères au maximum ; le HTML et les caractères invisibles sont refusés).
- **Réglages** (Configuration, section « Page de profil ») : le nombre de vitrines (0 à 12) et le
  nombre d'emplacements par vitrine (1 à 5). Choisir les cartes et les titres se fait uniquement sur la
  page de profil. Réduire ces nombres ne supprime rien : ce qui n'est plus affiché revient si tu les
  réaugmentes. Une carte mise à la corbeille disparaît de la vitrine et y revient si tu la restaures ;
  une carte supprimée définitivement libère son emplacement.

## Icônes des cartes, animation de la carte agrandie

- **Icônes en haut à droite** (Configuration, « Apparence du site et des cartes ») : quatre cases pour
  choisir lesquelles afficher : ouvrir l'article sur Wikipédia (cochée par défaut), enregistrer en
  PNG, en PDF, en Word (décochées par défaut). L'étoile des favoris est toujours là.
- **Animation de la carte agrandie** (clic sur une carte) : un léger mouvement, visible sans gêner
  la lecture : flottement léger (défaut, 9 px), balancement doux (1,4°), respiration (2,5 %), pivot 3D
  léger (6°), reflet qui passe, suit la souris (9° au maximum) ou aucune. Coupée avec « mouvement
  réduit ». Choisir l'animation dans la Configuration l'applique tout de suite.
- **Pied de carte** : les statistiques sont **centrées** (vues par jour à gauche, statistiques au
  milieu, date à droite). Si la police ou la largeur ne permet pas de tout mettre sur une ligne, le pied
  passe sur deux lignes : vues et date en haut, statistiques centrées en dessous.

## Catégorie automatique « Sans illustration »

Comme « Doublons », une catégorie automatique regroupe les cartes dont l'article n'a **pas d'image sur
Wikipédia** : entrée « Sans illustration (N) » dans la liste des catégories (après « Doublons »),
filtre de la collection, et bandeau gris-bleu « Sans illustration » sur ces cartes (info-bulle
explicative, jamais coupé). Réglages : activer / désactiver et couleur du bandeau (section
« Collection, pagination et catégories »). Les cartes de la corbeille ne comptent pas.

## Autres réglages d'apparence

- **Liste des catégories** : chaque entrée affiche son nombre de cartes entre parenthèses
  (« Toutes les catégories (41) », « Sans catégorie (12) », « Doublons (3) », « Sport (5) »), mis à
  jour sans recharger quand tu ouvres un paquet ou supprimes des cartes.
- **Effets des cartes au survol** (11 choix) : soulever, incliner, agrandir, flotter doucement,
  ressort (rebond), pivot 3D, suit la souris (3D), brillance (reflet qui passe), halo lumineux,
  balancer, aucun. Seuls transform, opacité et ombre bougent ; uniquement avec une vraie souris et
  coupés par « mouvement réduit ». Choisir un effet dans la Configuration l'applique tout de suite.
- **Mention de bas de page** (`MENTION_AFFICHER`) : centrée en bas de chaque page, « Gratuit. Contenu encyclopédique issu de Wikipédia, sous
  licence libre (CC BY-SA). WikiFreeCards, logiciel sous licence MIT, Copyright (c) 2026 Damballah Oueddo. ». Son texte est **fixe** (plus de
  réglage « Texte de la mention » : la licence MIT demande de conserver la mention d'auteur) ; « WikiFreeCards », « licence MIT » et « Damballah
  Oueddo » sont des liens qui s'ouvrent dans une nouvelle fenêtre (voir `wikicartes/projet.py`).
- **Message de bienvenue** (`ACCUEIL_AFFICHER`) : une fois à chaque lancement du programme (et par fenêtre de navigateur), à la première page affichée,
  avec le logo en haut à gauche (taille fixe de 72 px, indépendante du réglage du logo) et le lien GitHub du projet en gras. La case en bas à gauche
  « Ne plus afficher ce message au démarrage » l'enregistre ; le réglage « Message de bienvenue au démarrage » (Apparence) permet de le revoir.

## Réserve de cartes (pré-chargement)

Pour que l'ouverture d'un paquet soit **instantanée** et ne dépende plus de l'état de Wikipédia à ce
moment-là, le programme prépare des cartes **d'avance**, en arrière-plan, et les range dans la base
de données (table `reserve`).

- **À l'ouverture d'un paquet**, les cartes sont prises dans la réserve (aucune requête, pas de
  décompte). Si la réserve ne suffit pas, seules les cartes qui manquent sont tirées en direct. Si
  Wikipédia ne répond pas, le paquet s'ouvre quand même avec ce que la réserve contient, et la page
  le dit (« paquet de 2 cartes au lieu de 3 »). Un paquet qui échoue ne fait perdre aucune carte.
- **La taille suit tes réglages** : cible = « Paquets gardés d'avance » × « Cartes par paquet » (3 × 5
  = 15 par défaut). Si tu changes le nombre de cartes par paquet, la réserve s'adapte toute seule.
  Le tirage garde les mêmes probabilités de rang : chaque carte de la réserve est tirée comme une
  carte de paquet.
- **Remplissage économe** : le pré-chargement n'agit que lorsque la réserve passe sous la moitié de
  sa cible, puis la remplit d'un coup (un lot aléatoire de 50 articles + une requête de détails pour
  20 cartes : environ **3 requêtes pour 15 cartes**, contre 2 à 4 requêtes par paquet en tirage direct).
- **Politesse envers l'API de Wikipédia** :
  - une seule requête à la fois pour tout le programme (verrou commun), jamais en parallèle ;
  - pause plus douce que d'habitude entre ses requêtes (« Pause entre deux requêtes de
    pré-chargement », 3 s) ;
  - **plafond horaire strict** (60 requêtes par heure par défaut), noté dans la base : il survit à un
    redémarrage ;
  - jamais de nouvelle tentative après un 429 ou un 503 : il s'arrête, respecte `Retry-After` et
    double son attente à chaque échec (5 min, 10 min, 20 min... jusqu'à 4 h) ;
  - départ différé de 15 s après le lancement, et **priorité à toi** : il attend pendant tes
    ouvertures de paquet et tes recherches ;
  - requêtes publiques en lecture seule, identifiées par ton contact ou le lien du projet (réglage `CONTACT`) ; aucune
    donnée personnelle n'est envoyée.
- **Sécurité des données** : tout ce que Wikipédia renvoie est vérifié avant d'être rangé (longueurs,
  caractères, nombres, rang connu, et adresses limitées à `https://*.wikipedia.org` et
  `*.wikimedia.org`), puis enregistré par requêtes paramétrées avec des contraintes en base. Les
  textes sont toujours affichés échappés : un titre contenant du HTML s'affiche comme du texte.
- **Fraîcheur** : une carte préparée depuis plus de 7 jours (réglable) est jetée, car ses vues
  vieillissent ; les plus anciennes sont données en premier.
- **Page Configuration**, section « Réserve de cartes » : cartes prêtes, jauge, état (au repos, en
  cours, en pause, plafond atteint...), requêtes de l'heure, dernier incident, boutons « Remplir
  maintenant » et « Vider la réserve » (ils respectent les mêmes limites). Case à décocher pour
  désactiver complètement le pré-chargement (`RESERVE_ACTIVE = False`).

## Corbeille

Supprimer des cartes ne les efface pas : elles partent dans la **corbeille** et peuvent être
restaurées. Pour en supprimer, utilise le bouton « Sélection » de la collection, coche les cartes
(une seule ou beaucoup d'un coup), puis « Supprimer ».

- **L'icône « double corbeille »**, en haut à droite de chaque page, à côté des boutons :
  **grise avec « (0) »** quand la corbeille est vide, **rouge avec « (N) »** quand elle contient
  N cartes.
- **Un clic sur l'icône** ouvre une petite fenêtre : « La corbeille est vide. » ou « N cartes dans
  la corbeille. ». S'il y a des cartes, elle propose le bouton rouge **« Supprimer définitivement »**
  (un 2e clic dans les 4 secondes confirme ; une courte animation et le message « La corbeille
  est vide ! » montrent que c'est fait), le bouton **« Restaurer tout »** et un lien vers la page
  de la corbeille.
- **La page « Corbeille »** affiche les cartes mises de côté, avec leur date de suppression.
  Coche des cartes : « Restaurer la sélection » les remet dans la collection (avec leur rang,
  leurs catégories et leurs favoris), « Supprimer définitivement la sélection » les efface
  (confirmation par un 2e clic) ; les cartes non cochées restent dans la corbeille.
- Les cartes de la corbeille ne comptent plus dans la collection : boutons de filtre, nombre de
  cartes, pagination, catégories et pastille « Dans ta collection » de la recherche les ignorent.
- Seules des cartes **déjà dans la corbeille** peuvent être effacées pour de bon. Les images
  exportées (dossier Export) ne sont pas touchées.

## Page Recherche

Le bouton « Recherche » (en haut à droite) ouvre une page pour **chercher des cartes sur Wikipédia**
et les rapatrier dans ta collection :

1. Écris ce que tu cherches (un nom, un lieu, un sujet...) et valide : les articles trouvés
   s'affichent sous forme de cartes, du plus pertinent au moins pertinent. Le nombre de cartes
   proposées se règle dans la Configuration (« Résultats par recherche », 12 par défaut, 20 au
   maximum).
2. Chaque carte a une **case à cocher** (un clic sur la carte la coche aussi). Le bouton
   **« Tout sélectionner »** coche toutes les cartes ; il devient **« Tout désélectionner »** quand
   tout est coché. Une pastille « ✓ Dans ta collection » signale les articles déjà possédés.
3. **« Rapatrier la sélection »** enregistre les cartes cochées dans la collection. Comme pour un
   paquet, chaque carte reçoit son **palier** d'après les vues de l'article, puis est classée
   **automatiquement dans les catégories** dont une meta apparaît dans sa courte description ou dans
   les phrases de son introduction (les bandeaux affichés sur les résultats montrent le classement prévu).

Pour ne pas surcharger Wikipédia : une recherche = **une seule requête** à l'API officielle (qui
renvoie aussi l'image, l'introduction et les vues) ; une seule recherche à la fois et au moins une
seconde entre deux recherches ; requêtes identifiées par ton contact (réglage CONTACT) ; le
programme ralentit si Wikipédia le demande. Les données sont relues sur Wikipédia au moment du
rapatriement : rien n'est enregistré avant. Rapatrier un article déjà possédé crée une carte de
plus, comme un nouveau tirage.

## Page Configuration

Accessible par le bouton « Configuration » en haut à droite. Tous les réglages de `config.py`
y sont (sauf les dossiers et `SERVEUR_LOCAL`, qui restent dans `config.py`) ; ils sont
enregistrés dans la base de données, avec un bouton **↺** par réglage pour retrouver la valeur
de départ et **« Tout remettre aux valeurs de départ »** (deux clics) pour tout réinitialiser.

- **Paquets de cartes** : nombre de cartes par paquet (1 à 20).
- **Wikipédia et tirage** : langue, introduction, période des vues, recherche aléatoire...
- **Identité du site** : l'**image du logo** (liste des fichiers du dossier `logo/`, détection
  automatique ou aucun logo), sa hauteur en haut de page, le **titre**, sa taille, la **courte
  biographie** et sa taille (toujours plus petite que celle du titre).
- **Paquets et booster** : cartes par paquet, style du booster, animation d'ouverture, texte du
  booster (affiché seulement sans logo), légende sous le booster ; aperçu et test de l'animation.
- **Raretés et apparence des cartes** : pour chaque rang, ses **lettres** (1 à 3 lettres ou
  chiffres, toutes différentes), son nom, son seuil de vues par jour, sa
  probabilité de tirage et son apparence, avec un **aperçu en direct** de la carte :
  - **motif** : vagues, rayures, points, losanges, rayons (ou aucun) ;
  - **3 couleurs** : fond du haut, fond du bas, accent (motif, lettre du rang, halo). La couleur
    du texte s'ajuste toute seule pour rester lisible ;
  - **reflet animé** (10 au choix) : balayage, pulsation, étincelles, arc-en-ciel, vague montante, faisceau tournant, balayage
    croisé, paillettes, aurore, contour néon (ou aucun).
  N'importe quel rang peut recevoir n'importe quelle combinaison.
- **Collection, pagination et catégories** : cartes par page, longueur des noms de catégorie sur
  les cartes, nombre de bandeaux par carte, classement automatique, meta = mot entier ou non,
  catégories visibles sur les images exportées. Dessous, l'**éditeur de catégories** :
  - créer, renommer, recolorer ou supprimer une catégorie (**les cartes ne sont jamais
    supprimées** : elles sont seulement retirées de la catégorie) ; l'aperçu du bandeau montre
    le rendu sur une carte ;
  - **5 champs « meta »** par catégorie : des mots ou expressions. À l'ouverture d'un paquet, si une
    meta apparaît dans la courte description d'une carte (celle sous le titre) **ou dans les phrases de
    son introduction** (réglage « Meta : chercher aussi dans les phrases », activé par défaut : une
    actrice sans seconde ligne sous son titre est quand même trouvée par « actrice »), la carte est classée
    automatiquement dans la catégorie (majuscules et accents ignorés ; plusieurs catégories
    possibles) ;
  - « Classer maintenant les cartes existantes qui correspondent » : applique les meta aux cartes
    déjà dans la collection (utile quand on crée une catégorie après coup).
  Tout est enregistré d'un coup avec le bouton « Enregistrer » : si une valeur est refusée, rien
  n'est enregistré. « Tout remettre aux valeurs de départ » ne touche pas aux catégories.
- **Thèmes du site** (section « Apparence du site et des cartes ») : **20 thèmes** au choix, avec leurs
  couleurs et, pour la plupart, un motif de fond. Sombre, Clair, Minuit étoilé, Océan, Forêt,
  Crépuscule, Sakura, Parchemin, Néon arcade, Lavande, Graphite, Braise, Menthe, Or et noir et
  Contraste élevé, plus cinq thèmes d'ambiance : Années 80-90 fluo new age, Arcade rétro 8 bits, Jeu de société, Chic tendance
  et Album de cartes à collectionner. Une pastille par thème montre son aperçu ; un clic l'applique **tout de suite**
  à la page (rien n'est enregistré avant « Enregistrer »). Chaque thème (sauf Sombre et Clair) a sa
  propre couleur d'accent ; décoche « Couleur d'accent propre au thème » pour garder la tienne
  partout. Les couleurs des rangs et des cartes ne changent pas avec le thème.
- **Apparence du site et des cartes** : thème sombre ou clair, couleur d'accent, angles du site
  et des cartes (arrondis ou carrés), effet des cartes au survol (soulever, incliner, aucun),
  tailles des cartes.
- **Export et impression** : tailles des images, du papier, repères de coupe, QR code...
- **Système** : e-mail de contact pour Wikimedia, pauses, port du serveur, sauvegardes...
  (le port et l'ouverture du navigateur s'appliquent au prochain lancement).

Un réglage refusé (valeur hors limites, couleur invalide...) est expliqué en rouge sous le champ
et **rien n'est enregistré** tant que tout n'est pas valide.

## Organisation

    main.py              point d'entrée
    wikicartes/
        config.py        valeurs de départ de tous les réglages (langue, paliers, probabilités, tailles, e-mail...)
        api.py           appels à Wikipédia (réseau uniquement)
        rarete.py        calcul des vues et classement par palier
        tirage.py        tirage pondéré : on tire le rang, puis l'article
        terminal.py      saisie et affichage dans la console
        rendu.py         génération de la page HTML
        base.py          base de données SQLite : cartes, paramètres, sauvegardes, intégrité
        parametres.py    liste des réglages, vérifications, enregistrement dans la base
        theme.py         couleurs des rangs, listes de motifs et de reflets, CSS généré
        paquet.py        ouverture d'un paquet : tirage, enregistrement, classement automatique
        categories.py    catégories : vérification, meta, bandeaux, nom tronqué
        recherche.py     recherche d'articles sur Wikipédia et rapatriement dans la collection
        profil.py        page de profil : validation des titres de vitrine (lettres, chiffres, emoji)
        createur.py      Créateur de cartes : validation et création des cartes personnalisées
        images.py        images des cartes personnalisées (vérification du contenu, data/images/)
        web.py           lecture sécurisée d'une page web (adresses publiques seulement)
        p2p_identite.py  clés, identifiant pair, pseudo, fiches signées ; p2p_annuaire.py : annuaire des pairs
        p2p_transport.py Tor (SOCKS5, port de contrôle), connexions vers les pairs, réponses signées
        p2p_tor.py       détecter Tor, expliquer, le lancer (torrc écrit par le programme), lancement automatique
        p2p_serveur.py   serveur pair à pair en LECTURE SEULE ; partage.py : ce qui est partagé (liste blanche)
        p2p_client.py    visite, vérification des données reçues, rapatriement ; p2p_service.py : cycle de vie du nœud
        hall_api.py      actions de la page Hall des collections
        stats.py         statistiques des cartes (modifications, liens entrants, langues, taille) :
                         récupération polie en arrière-plan, plafond horaire, arrêt si Wikipédia ralentit
        reserve.py       réserve de cartes : pré-chargement poli en arrière-plan (plafond horaire,
                         pauses, arrêt si Wikipédia ralentit, vérification des données reçues)
        (corbeille)      base.py (mise à la corbeille, restauration, suppression définitive),
                         navigation.py (icône), static/corbeille.js et page_corbeille.js
        navigation.py    boutons de l'en-tête (en haut à droite de chaque page)
        formulaire.py    formulaire de la page Configuration
        export.py        nom des fichiers exportés et enregistrement dans Export/
        documents.py     création des documents PDF et Word recto verso (sans dépendance)
        serveur.py       petit serveur local (127.0.0.1) qui sert la page et reçoit les images
        qr.py            générateur de QR code (sans dépendance), renvoie une image SVG
    templates/           gabarits HTML (page.html, configuration.html, carte.html)
    static/              cartes.css (style, motifs, reflets, paquet), cartes.js (paquet,
                         favoris, filtres, export), apercu.js (carte agrandie et ses icônes, partagée avec la
                         page Recherche), createur.js (Créateur de cartes), configuration.js (Configuration)
    Export/              cartes enregistrées : un sous-dossier par rang (L, UR, SR, R, PC, C)
    data/                la base de données (collection.db), ses sauvegardes et les images des cartes personnalisées (images/)
    logo/                le logo du jeu : une image nommée « logo » (logo.png, logo.jpg...)
    sortie/              page générée (créé automatiquement)

## Où modifier quoi

- Réglages : dans la page Configuration. `wikicartes/config.py` garde les valeurs de départ
  (voir « Base de données locale » pour la règle entre `config.py` et la base).
- Ajouter un bouton en haut à droite : `BOUTONS_ENTETE` dans `wikicartes/navigation.py`.
- Dessin des motifs et des reflets : `static/cartes.css` (`data-motif`, `data-reflet`).

- Seuils et probabilités des rangs : `wikicartes/config.py`
- Taille des cartes sur la page : `LARGEUR_CARTE` (pixels), même fichier
- Taille de la carte agrandie : `LARGEUR_APERCU` ; taille de l'image exportée : `LARGEUR_EXPORT`
- Impression (PDF / Word) : `IMPRESSION_LARGEUR_MM` (63 mm par défaut), `IMPRESSION_DPI`,
  `IMPRESSION_MARGE_MM`, `IMPRESSION_REPERES` (repères de coupe), `IMPRESSION_QR_MM` (taille du
  QR code au verso, 26 mm par défaut) et `PAPIER_MM` (A4 par défaut)
- Logo : remplace l'image du dossier `logo/` (voir `logo/LISEZMOI.txt`)
- Désactiver le serveur local : `SERVEUR_LOCAL = False` (la disquette télécharge alors l'image)
- Couleurs d'un rang, lisibilité des textes : `static/cartes.css`
- Structure d'une carte : `templates/carte.html`


## Pagination et son d'effet en boucle

- **Changer de page** (numéros, « Suivant », « Précédent »), depuis la pagination du haut comme de celle du bas, affiche toujours la nouvelle page
  depuis son début (collection, corbeille, recherche, visite d'une collection du Hall, liste du Hall).
- **Son d'effet du paquet en boucle** (`SON_EFFET_PAQUET_BOUCLE`, Configuration > Sons) : le son d'effet recommence tant que le paquet s'anime et
  s'arrête à son ouverture. Les autres sons ne bouclent jamais.
