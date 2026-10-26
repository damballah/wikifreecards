"""Réglages de l'application : valeurs de départ de tout ce qu'on peut vouloir modifier.

Tous ces réglages (sauf les dossiers) se changent aussi depuis la page « Configuration » du
site : ils sont alors enregistrés dans la base de données. Règle : si tu modifies une valeur
ici, elle est prise en compte au lancement suivant ; sinon la valeur enregistrée dans la base
est reprise."""

import os
from pathlib import Path

# --- Dossiers du projet -------------------------------------------------------
RACINE = Path(__file__).resolve().parent.parent
DOSSIER_STATIC = RACINE / "static"        # CSS et JS de la page de cartes
DOSSIER_TEMPLATES = RACINE / "templates"  # gabarits HTML
DOSSIER_SORTIE = RACINE / "sortie"        # page générée (créé automatiquement)
DOSSIER_EXPORT = RACINE / "Export"        # cartes enregistrées : Export/<rang>/
DOSSIER_LOGO = RACINE / "logo"            # logo du jeu : une image nommée "logo" (logo.png...)
DOSSIER_ICO = RACINE / "ico"              # icône de l'onglet du navigateur : favicon.ico (16x16 ou 32x32) ou favicon.png (32x32)
DOSSIER_SONS = RACINE / "sons"            # sons des événements et musique d'ambiance (mp3, ogg, wav...)
DOSSIER_DONNEES = RACINE / "data"         # base de données locale et ses sauvegardes
FICHIER_BASE = DOSSIER_DONNEES / "collection.db"        # (avant : wikicartes.db, renommé tout seul)
DOSSIER_SAUVEGARDES = DOSSIER_DONNEES / "sauvegardes"

# --- Wikipedia ----------------------------------------------------------------
LANGUE = "fr"      # "en" pour Wikipedia anglais, etc.
NB_PHRASES = 3     # nombre maximum de phrases de l'introduction (1 à 10)
JOURS_VUES = 60    # période de mesure des vues pour classer un article (60 max)
TAILLE_MINIATURE = 720  # largeur (px) de l'image utilisée sur les cartes

# --- Identité du site : logo, titre et biographie -------------------------------
# Le logo s'affiche en haut à gauche de chaque page, sur le booster et au verso des documents.
# Le logo est le fichier nommé « logo » (logo.png, logo.svg...) du dossier logo/ : pour en changer, remplace ce fichier par un autre du même nom.
# Ce n'est plus un réglage de la Configuration (sa hauteur est fixe : LOGO_HAUTEUR plus bas).
GODPACK_UN_SUR = 10000          # GOD PACK : chance d'ouvrir un paquet de cartes TOUTES légendaires = 1 sur N (0 : jamais)
MOBILE_MODE = "auto"            # affichage sur téléphone : « auto » (détecté d'après l'écran), « toujours » (même sur ordinateur) ou « jamais »
MOBILE_ENTETE = "compact"       # en-tête sur téléphone : « compact » (logo, titre court, menu), « minimal » (logo et menu) ou « complet »
LOGO_HAUTEUR = 128              # hauteur du logo en haut de page, en pixels : FIXE (plus un réglage de la Configuration)
TITRE_SITE = "Ma collection Wikipédia"      # titre de la page : par exemple le nom de ta collection
TITRE_TAILLE = 36               # taille du titre, en pixels (de 18 à 80)
BIO_SITE = "Collectionneur d'articles Wikipédia"   # courte biographie sous le titre (vide = aucune)
BIO_TAILLE = 16                 # taille de la biographie, en pixels (de 10 à 40) : toujours plus
                                # petite que celle du titre

# --- Recherche de cartes ------------------------------------------------------
RECHERCHE_MAX_RESULTATS = 20    # cartes proposées par recherche sur Wikipédia (de 1 à 20) ; « Voir plus de résultats » en charge autant de plus

# --- Icônes en haut à droite des cartes ------------------------------------------------
ICONE_LIEN = True     # ouvrir l'article sur Wikipédia
ICONE_PNG = False     # enregistrer la carte en image PNG (disquette)
ICONE_PDF = False     # enregistrer la carte en PDF recto verso
ICONE_WORD = False    # enregistrer la carte en document Word recto verso
                      # (l'étoile des favoris est toujours affichée)

# --- Carte agrandie (clic sur une carte) --------------------------------------------------
ANIMATION_ZOOM = "flottement"   # léger mouvement de la carte agrandie : flottement, balancement,
                                # respiration, pivot, brillance, tilt (suit la souris) ou aucune

# --- Page de profil : les vitrines -----------------------------------------------------------
# Une vitrine est une ligne de cartes que tu choisis directement sur la page de profil (ainsi que
# le titre de chaque vitrine). Ici, seulement la forme de la page.
PROFIL_VITRINES = 3       # nombre de vitrines (lignes) sur la page de profil (de 0 à 12)
PROFIL_EMPLACEMENTS = 4   # nombre d'emplacements (cartes) par vitrine (de 1 à 5)

# --- Statistiques affichées sous les cartes --------------------------------------
# Sous chaque carte : langues disponibles (🌐), modifications de la page (✏️), liens entrants (🔗) et
# taille de l'article en Ko (📄). Langues et taille arrivent avec la carte (1 requête de plus par
# paquet) ; modifications et liens entrants demandent une requête chacun : ils sont
# récupérés ensuite, en arrière-plan et poliment (même pause que la réserve, plafond horaire).
STATS_CARTES = True             # False : pas de statistiques (rien n'est affiché ni demandé)
STATS_REQUETES_HEURE = 120      # plafond de requêtes de statistiques par heure (de 10 à 1000)
STATS_AVEC_PAQUET = True        # les statistiques d'un paquet arrivent AVEC les cartes (récupérées tout de suite, hors plafond horaire)
STATS_PAUSE_PAQUET = 0.3        # pause (s) entre deux requêtes de statistiques d'un paquet : plus courte que PAUSE, car la page attend

# --- Mention de bas de page ---------------------------------------------------------
MENTION_AFFICHER = True         # affiche la mention (licence, auteur), centrée, en bas de chaque page (son texte est fixe : voir projet.py)
ACCUEIL_AFFICHER = True         # message de bienvenue au démarrage (une fois par lancement ; décochable dans le message lui-même)

# --- Réserve de cartes (pré-chargement) ----------------------------------------
# Pour que l'ouverture d'un paquet soit instantanée et ne dépende plus de Wikipédia à ce moment-là,
# le programme prépare des cartes d'avance, en arrière-plan, et les range dans la base de données.
# Il le fait poliment : une requête à la fois, des pauses plus longues que d'habitude, un plafond
# par heure, et il s'arrête un moment si Wikipédia ralentit ou ne répond pas.
RESERVE_ACTIVE = True           # False : pas de pré-chargement (les paquets se tirent à l'ouverture)
RESERVE_PAQUETS = None          # paquets gardés d'avance : None = automatique selon le nombre de cartes du paquet (5 cartes : 10 paquets,
                                # 10 cartes : 3 paquets, 20 cartes : 1 paquet) ; un nombre force cette valeur (essais)
RESERVE_VALIDITE_JOURS = 7      # une carte préparée depuis plus longtemps est jetée (ses vues vieillissent)
RESERVE_PAUSE = 3.0             # secondes entre deux requêtes de pré-chargement (plus douce que PAUSE)
RESERVE_BLOQUER_OUVERTURE = True  # pas d'ouverture de paquet tant que la réserve n'est pas COMPLÈTE (cartes et statistiques) ;
                                  # un décompte en minutes indique quand le prochain paquet sera prêt
RECH_COLL_TITRE = True          # recherche dans la page Collection : dans le titre
RECH_COLL_SOUS_TITRE = True     # ... dans le sous-titre
RECH_COLL_DESCRIPTION = False   # ... dans la description (le texte de la carte)
RECH_PAGE_TITRE = True          # page « Recherche » (Wikipédia) : un résultat est gardé si les mots sont dans le titre
RECH_PAGE_SOUS_TITRE = True     # ... ou dans le sous-titre
RECH_PAGE_DESCRIPTION = False   # ... ou dans le début de l'article (description)
RECH_PROFIL_TITRE = True        # recherche de cartes dans la page Profil (vitrines) : titre
RECH_PROFIL_SOUS_TITRE = True   # ... sous-titre
RECH_PROFIL_DESCRIPTION = False # ... description
FLOU_ACTIF = True               # flouter par défaut les images des cartes à contenu sensible (anatomie, positions sexuelles...)
FLOU_FORCE = 18                 # intensité du flou (4 à 40)
FLOU_ICONE = True               # petite icône « interdit aux moins de 18 ans » sur ces cartes (pour montrer / flouter l'image)
FLOU_MOTS = ""                  # TA liste de mots et expressions à flouter (virgules ou lignes ; « * » final = début de mot) : vide = rien n'est flouté
FLOU_EXCEPTIONS = ""            # mots qui écartent une carte de la détection (elle n'est jamais floutée)
ICONE_RAFRAICHIR = False        # icône « rafraîchir l'image » sur les cartes (chercher l'illustration de l'article si elle a changé)
SONS_ACTIFS = True              # jouer les sons des événements
SONS_VOLUME = 70                # volume des sons des événements (0 à 100)
SON_EFFET_PAQUET = ""          # le paquet qu'on vient de cliquer s'anime (avant de disparaître)
SON_EFFET_PAQUET_BOUCLE = False  # joue ce son EN BOUCLE pendant que le paquet s'anime, jusqu'à son ouverture (seulement celui-là)
SON_OUVERTURE = ""              # nom d'un fichier du dossier sons/ (vide : aucun son)
SON_CARTE_FENETRE = ""          # chaque carte qui apparaît dans la fenêtre du paquet
SON_ARRIVEE = ""                # les cartes arrivent dans la collection
SON_CORBEILLE = ""              # des cartes vont à la corbeille
SON_RESTAURATION = ""           # des cartes sont restaurées depuis la corbeille
SON_SUPPRESSION = ""            # la corbeille est vidée (suppression définitive)
SON_RETRAIT = ""                # une carte est retirée de la fenêtre du paquet (✕) avant d'entrer dans la collection
MUSIQUE_ACTIVE = False          # musique d'ambiance pendant l'utilisation du programme
MUSIQUE_FICHIER = ""            # nom du fichier de la musique (dossier sons/)
MUSIQUE_VOLUME = 40             # volume de la musique (0 à 100) ; le petit curseur à côté du haut-parleur le règle aussi
MUSIQUE_COUPEE = False          # haut-parleur barré : on ne veut pas entendre la musique (choix gardé d'un lancement à l'autre)
FENETRE_APPLICATION = False     # lancer le programme dans sa propre fenêtre (Edge ou Chrome) : la musique démarre alors toute seule
PAQUET_FENETRE = True           # les cartes d'un paquet s'affichent d'abord dans une fenêtre (on peut en retirer) avant la collection
RESERVE_REQUETES_HEURE = 120    # plafond de requêtes de pré-chargement par heure (de 10 à 600) : les statistiques des cartes préparées en font partie

# --- Paquets de cartes et booster -----------------------------------------------
NOMBRE_CARTES_PAQUET = 5   # cartes dans chaque paquet : 5, 10 ou 20 (5 cartes : 10 paquets d'avance ; 10 : 3 ; 20 : 1)
BOOSTER_AFFICHER = True    # False : le paquet à ouvrir n'est pas affiché et la collection remonte
                           # (on ne peut plus tirer de cartes au hasard ; la page Recherche reste là)
# Le booster (le sachet cliquable) n'affiche que le logo. S'il n'y a pas de logo, il affiche
# le texte BOOSTER_TEXTE.
BOOSTER_THEME = "classique"     # classique, or, nuit, holo, braise, ocean, foret, bonbon, carbone ou cosmos
BOOSTER_ANIMATION = "secousse"  # à l'ouverture : secousse, flash, rotation, envol, dissolution, rebond, tourbillon,
                                # explosion, chute, battement (ou aucune)
                                # ou aucune (instantané)
BOOSTER_IMAGE = ""              # image PNG/JPEG du paquet personnalisé (« /image/<nom> », téléversée dans la Configuration)
BOOSTER_FORME = "image"         # forme du paquet personnalisé : image (ses proportions), vertical, carre, horizontal, rond
BOOSTER_AJUSTEMENT = "recadrer" # recadrer (l'image remplit la forme) ou entier (l'image entière est visible)
BOOSTER_IMAGE_CONTENU = "rien"  # sur l'image du paquet : rien (juste l'image), logo ou texte
BOOSTER_SURVOL = "soulever"    # effet du paquet sous la souris : les mêmes que EFFET_SURVOL des cartes (soulever, incliner, zoom...)
BOOSTER_REPOS = "aucune"        # animation du paquet au repos (sans souris) : les mêmes que ANIMATION_ZOOM (flottement, balancement...)
BOOSTER_TEXTE = "BOOSTER"       # mot ou phrase affiché sur le booster quand il n'y a pas de logo
BOOSTER_LEGENDE = True          # affiche « Ouvrir un paquet · 5 cartes » sous le booster
BOOSTER_DECOMPTE = True         # affiche, pendant l'ouverture, le décompte (en secondes) avant que le
                                # paquet s'ouvre : il est calculé d'après PAUSE (pause entre requêtes)
HALO_DUREE = 0                  # (le halo doré des nouvelles cartes a été retiré : plus d'option, toujours 0)
HALO_COULEUR = "#ffd54a"        # couleur du halo (doré par défaut)

# --- Apparence du site et des cartes ------------------------------------------
THEME_SITE = "sombre"      # sombre, clair, minuit, ocean, foret, crepuscule, sakura, parchemin, neon,
                           # lavande, graphite, braise, menthe, or-noir ou contraste
COULEUR_ACCENT = "#ffd34d"   # couleur d'accent du site (curseurs, boutons actifs, paquet...)
ACCENT_DU_THEME = True       # True : chaque thème (sauf « sombre » et « clair ») a sa propre couleur
                             # d'accent ; False : COULEUR_ACCENT s'applique à tous les thèmes
ANGLES_SITE = "arrondis"   # "arrondis" ou "carres" (angle droit) : boutons et panneaux du site
ANGLES_CARTES = "arrondis"   # "arrondis" ou "carres" : coins des cartes
EFFET_SURVOL = "soulever"  # effet des cartes sous la souris : soulever, incliner, zoom, flottement, ressort,
                           # pivot, tilt (suit la souris), brillance, halo, balancement ou aucun

# --- Rareté -------------------------------------------------------------------
# Paliers du plus populaire au moins populaire.
# Le seuil est le nombre MOYEN de vues par jour (minimum) pour obtenir ce rang.
PALIERS = [
    ("L", 10000, "Légendaire"),
    ("UR", 2000, "Ultra rare"),
    ("SR", 500, "Super rare"),
    ("R", 50, "Rare"),
    ("PC", 10, "Peu commun"),
    ("C", 0, "Commun"),
]

# Probabilités de tirage de chaque rang (valeurs relatives, pas besoin que le
# total fasse 100). Ici : L 1 %, UR 4 %, SR 10 %, R 20 %, PC 30 %, C 35 %.
POIDS = {"L": 1, "UR": 4, "SR": 10, "R": 20, "PC": 30, "C": 35}

# Lettres affichées pour chaque rang (en haut à gauche des cartes, dans les boutons de filtre,
# dans les noms de fichiers et de dossiers exportés) : de 1 à 3 lettres ou chiffres, toutes
# différentes. La clé (L, UR...) est l'identifiant interne du rang : ne la change pas ici.
SYMBOLES_PALIERS = {"L": "L", "UR": "UR", "SR": "SR", "R": "R", "PC": "PC", "C": "C"}

# Apparence de chaque rang. Pour chacun :
#   "motif"    : "aucun", "vagues", "rayures", "points", "losanges" ou "rayons"
#   "couleurs" : [fond du haut, fond du bas, couleur d'accent (motif, lettre du rang, halo)]
#   "reflet"   : animation de reflet : "aucune", "balayage", "pulsation", "etincelles",
#                "arcenciel" ou "montante"
THEMES_PALIERS = {
    "L": {"motif": "vagues", "couleurs": ["#ffe680", "#d49b14", "#fbc90d"], "reflet": "balayage"},
    "UR": {"motif": "vagues", "couleurs": ["#ff9a33", "#ffd7a1", "#ff9619"], "reflet": "balayage"},
    "SR": {"motif": "vagues", "couleurs": ["#ee6fa8", "#ffcfe2", "#ff7db3"], "reflet": "aucune"},
    "R": {"motif": "vagues", "couleurs": ["#c3a0ef", "#eee3fb", "#c9a9f3"], "reflet": "aucune"},
    "PC": {"motif": "vagues", "couleurs": ["#a6cbf4", "#e2eefc", "#b4d3f7"], "reflet": "aucune"},
    "C": {"motif": "vagues", "couleurs": ["#aeead0", "#e3f9ef", "#b7f0d7"], "reflet": "aucune"},
}

# --- Palier des cartes PERSONNALISÉES (Créateur de cartes) -------------------------------------
# Thème « de base » appliqué à une nouvelle carte créée : ses lettres (5 au maximum), son nom, son
# motif, ses trois couleurs et son reflet. Réglé dans la Configuration, tout en bas de « Raretés et
# apparence des cartes ». Dans le Créateur, on peut aussi appliquer le thème de n'importe quel autre rang.
PERSO_SYMBOLE = "PERSO"
PERSO_NOM = "Personnalisée"
PERSO_THEME = {"motif": "points", "couleurs": ["#5fd0c5", "#fff1c9", "#f08a5d"], "reflet": "balayage"}

# --- Disposition de la page : menu, barre d'outils, paquet (plusieurs solutions, à choisir dans la Configuration) ---
MENU_POSITION = "centre"        # centre (sous le titre), droite (disposition d'origine) ou lateral (colonne à gauche)
MENU_STYLE = "compact"          # complet, compact, icones (texte au survol) ou replie (bouton « ☰ Menu »)
BARRE_OUTILS = "compacte"       # compacte, centree, gauche (d'origine) ou repliable (bouton « Filtres, tri et taille »)
PAQUET_POSITION = "normal"      # normal (grand sachet, texte dessous), remonte (cartes visibles tout de suite), mini (petit sachet, texte dessous), compact
                                # (tout petit sachet, texte à côté) ou normal (d'origine)
LOGO_ALIGNEMENT = "gauche"      # logo de l'en-tête : gauche, gauche-centre (logo + titre centrés, logo à gauche), centre (au-dessus du titre),
                                # droite-centre (logo + titre centrés, logo à droite) ou droite
TITRE_ALIGNEMENT = "gauche"     # titre de la collection : gauche, centre ou droite
BIO_ALIGNEMENT = "gauche"       # biographie : gauche, centre ou droite
INFOS_ALIGNEMENT = "gauche"     # ligne d'infos (nombre de cartes, source, date) : gauche, centre ou droite

# --- Partage entre collectionneurs (Hall des collections, pair à pair) -----------------------
# Tout est DÉSACTIVÉ par défaut : rien n'est partagé tant que tu ne l'as pas décidé. Voir README.
P2P_ACTIF = False                   # démarre ton nœud : les autres collectionneurs peuvent te joindre
P2P_PROFIL_PUBLIC = False           # pastille « P » verte : ton profil (vitrines) peut être vu
P2P_COLLECTION_PUBLIQUE = False     # pastille « C » verte : ta collection peut être vue
P2P_TRANSPORT = "tor"               # « tor » (service oignon : aucune ouverture de port, ton adresse IP
                                    # reste cachée), « direct » (adresse publique + port ouvert) ou
                                    # « local » (essais sur ta machine ou ton réseau local)
P2P_PORT = 8766                     # port du nœud (écoute locale ; en « direct », port à ouvrir)
P2P_ADRESSE_DIRECTE = ""            # « hôte:port » publié aux autres (transport « direct » seulement)
P2P_TOR_SOCKS = "127.0.0.1:9050"    # proxy SOCKS de Tor (pour joindre les autres, transport « tor »)
CONFIG_AVANCE_LOCAL = True          # réglages avancés (Wikipédia, Réserve, Hall, Accès réseau, Système) : visibles et modifiables seulement depuis
                                    # cet ordinateur et le réseau local (jamais depuis une adresse IP publique, un tunnel...)
ACCES_RESEAU = "local"              # « local » : seulement cet ordinateur (127.0.0.1) ; « reseau » : réseau local, tunnel, adresse IP publique
                                    # (toute requête qui ne vient pas de cet ordinateur exige alors le code d'accès)
ACCES_CODE = ""                     # code d'accès (vide : généré au hasard au premier lancement en mode « reseau »)
TOR_PAYS = "auto"                   # relais d'ENTRÉE préférés, pour aller plus vite : « auto » (pays de l'ordinateur), un code de pays
                                    # (« fr »...) ou « » (aucune préférence). Préférence seulement : Tor garde ses relais de secours.
P2P_TOR_CONTROLE = "127.0.0.1:9051" # port de contrôle de Tor (pour publier ton service oignon)
# Chemin de tor.exe pour le bouton « Lancer Tor » : par défaut le dossier « tor » à la RACINE du programme (à côté de
# main.py) : <racine>\tor\tor.exe. On peut l'écrire avec « \ » ou « / » (le programme comprend les deux) ; vide : cherché
# automatiquement (PATH, Bureau, Téléchargements...).
P2P_TOR_EXECUTABLE = (RACINE / "tor" / "tor.exe").as_posix()
CHEMINS_AVEC_ANTISLASH = (os.name == "nt")   # affiche les chemins de la Configuration avec « \ » (Windows) ; stockés avec « / »
P2P_TOR_AUTO = False                # lance Tor au démarrage du programme (si Tor n'est pas déjà lancé)

# Au-dessus de ce seuil (vues/jour), un article ne sort quasiment jamais d'un
# tirage purement aléatoire : on le cherche donc uniquement dans le top des plus vus.
SEUIL_TOP_UNIQUEMENT = 200
TAILLE_LOT = 50    # articles tirés par requête lors de la recherche aléatoire
MAX_LOTS = 8       # nombre max de requêtes pour trouver un article d'un rang

# --- Politesse envers Wikipedia -----------------------------------------------
PAUSE = 1.0        # pause minimale (secondes) entre deux requêtes
MAX_ESSAIS = 5     # tentatives max si Wikipedia répond « trop de requêtes » (429)
# Wikimedia demande un User-Agent permettant de te contacter : mets ton e-mail.
CONTACT = "https://github.com/damballah/wikifreecards"

# --- Page de cartes -----------------------------------------------------------
OUVRIR_NAVIGATEUR = True   # ouvre la page automatiquement une fois générée
SERVEUR_LOCAL = True       # lance un petit serveur local : indispensable pour que l'icône
                           # disquette enregistre directement dans le dossier Export/
PORT_SERVEUR = 8765        # port du serveur local (le suivant est essayé s'il est pris)
LARGEUR_EXPORT = 600       # largeur de l'image exportée, en pixels (hauteur proportionnelle)

# --- Impression recto verso (boutons PDF et Word) -----------------------------
IMPRESSION_LARGEUR_MM = 63   # largeur de la carte imprimée, en mm ; la hauteur suit (≈ 90 mm)
IMPRESSION_DPI = 300         # finesse de l'image dans le document (300 = qualité d'impression)
IMPRESSION_MARGE_MM = 5      # marge autour de la carte, qui accueille les repères de coupe (≥ 5)
IMPRESSION_REPERES = True    # dessine de petits repères aux quatre coins pour découper
IMPRESSION_QR_MM = 26        # largeur du QR code, en bas du verso, en mm (zone blanche
                             # comprise). Plus il est grand, plus il se scanne facilement,
                             # mais moins il reste de place pour le logo (maximum : la moitié
                             # de la largeur de la carte).
PAPIER_MM = (210, 297)       # taille de la feuille : A4. Lettre US : (215.9, 279.4)
LARGEUR_CARTE = 220        # largeur d'une carte sur la page, en pixels ; la hauteur
                           # suit automatiquement. Conseillé : de 160 à 400.
LARGEUR_APERCU = 420       # largeur de la carte agrandie (au clic sur l'image), en pixels

# --- Collection, pagination et catégories ---------------------------------------
CARTES_PAR_PAGE = 25            # cartes affichées par page dans la collection (de 5 à 200)
CATEGORIE_LONGUEUR_MAX = 14     # caractères du nom d'une catégorie affichés sur la carte ; au-delà,
                                # le nom est coupé et terminé par « … »
CATEGORIES_MAX_SUR_CARTE = 3    # bandeaux de catégorie affichés sur une carte (les autres : « +2 »)
CATEGORIES_AUTO = True          # classe automatiquement les cartes d'un paquet d'après les « meta »
                                # des catégories (mots cherchés dans la courte description sous le
                                # titre et, avec META_DANS_INTRO, dans les phrases de l'introduction)
META_DANS_INTRO = True          # cherche aussi les meta dans les phrases de l'introduction (une actrice
                                # sans « seconde ligne » sous son titre est trouvée par « actrice »)
META_MOT_ENTIER = False         # False : la meta peut être une partie d'un mot ("foot" trouve
                                # "footballeur") ; True : elle doit être un mot entier
CATEGORIES_DANS_EXPORT = True   # affiche les bandeaux de catégorie sur les images PNG, PDF et Word
# Catégorie automatique « Doublons » : les cartes dont le titre est EXACTEMENT le même (quel que soit
# leur rang) portent un bandeau « Doublon ×2 », et la liste des catégories propose « Doublons ».
DOUBLONS_ACTIFS = True
DOUBLONS_COULEUR = "#f5a524"    # couleur du bandeau « Doublon »
SANS_ILLUSTRATION_ACTIF = True      # catégorie automatique « Sans illustration »
SANS_ILLUSTRATION_COULEUR = "#64748b"   # couleur de son bandeau
# Catégorie automatique « Animée » : les cartes dont l'illustration est une image animée (.gif).
ANIMEE_ACTIF = True                # activée par défaut ; False : plus de bandeau ni de filtre « Animée »
ANIMEE_COULEUR = "#a855f7"         # couleur de son bandeau
# Noms des trois catégories automatiques (modifiables dans la Configuration) : bandeau, liste « Catégorie ».
NOM_DOUBLONS = "Doublons"
NOM_SANS_ILLUSTRATION = "Sans illustration"
NOM_ANIMEE = "Animée"

# --- Base de données locale ----------------------------------------------------
SAUVEGARDE_TOUS_LES_JOURS = 1   # écart minimal entre deux sauvegardes automatiques (en jours)
SAUVEGARDES_GARDEES = 7         # nombre de sauvegardes conservées (les plus récentes)

# --- Valeurs dérivées (ne pas modifier) ---------------------------------------
CODES = []
SEUILS = {}
NOMS = {}


def recalculer():
    """Recalcule CODES, SEUILS et NOMS à partir de PALIERS (à rappeler si PALIERS change)."""
    CODES[:] = [code for code, _, _ in PALIERS]
    SEUILS.clear()
    SEUILS.update({code: seuil for code, seuil, _ in PALIERS})
    NOMS.clear()
    NOMS.update({code: nom for code, _, nom in PALIERS})


CODE_PERSO = "PERSO"        # rang de TOUTES les cartes créées dans le Créateur de cartes
NOM_PERSO = "Personnalisée"        # nom d'origine du palier des cartes personnalisées (voir PERSO_NOM)


def symbole(code):
    """Lettres affichées pour un rang (par défaut, son identifiant)."""
    return SYMBOLES_PALIERS.get(code, code)


def nom_rang(code):
    """Nom d'un rang (« Légendaire »...), ou « Personnalisée » pour les cartes du Créateur."""
    if code == CODE_PERSO:
        return PERSO_NOM
    return NOMS.get(code, code)


def dossier_images():
    """Dossier des images des cartes personnalisées (téléversées ou récupérées sur le web)."""
    return DOSSIER_DONNEES / "images"


recalculer()
