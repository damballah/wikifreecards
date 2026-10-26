"""Paramètres du jeu et du site : enregistrés dans la base, rechargés à chaque lancement,
et modifiables depuis la page « Configuration ».

config.py donne les valeurs de départ. À chaque lancement, pour chaque paramètre :
- s'il n'est pas encore dans la base, il y est enregistré ;
- si tu as modifié sa valeur dans config.py depuis le dernier lancement, la nouvelle valeur
  de config.py est utilisée (et enregistrée) : tes modifications ne sont jamais ignorées ;
- sinon, la valeur enregistrée dans la base est reprise (celle choisie dans la page
  Configuration, ou avec le curseur de taille des cartes).

Les dossiers (DOSSIER_*, FICHIER_BASE) et SERVEUR_LOCAL ne sont pas modifiables depuis la page :
un mauvais réglage pourrait empêcher d'accéder à la page elle-même. Ils restent dans config.py.

Toute valeur lue dans la base ou reçue de la page est vérifiée avant d'être utilisée ; une valeur
invalide est refusée (page) ou ignorée (base : celle de config.py est gardée).
"""

import copy
import json
import re
import unicodedata

from . import base, booster, config, logo, profil, sons, theme, web

# ------------------------------------------------------------------ vérifications


def _entier(mini, maxi):
    return lambda v: (isinstance(v, int) and not isinstance(v, bool) and mini <= v <= maxi)


def _nombre(mini, maxi):
    return lambda v: (isinstance(v, (int, float)) and not isinstance(v, bool)
                      and mini <= v <= maxi)


def _booleen(v):
    return isinstance(v, bool)


PAYS_RELAIS = {"auto": "Automatique (le pays de cet ordinateur)", "": "Aucune préférence (choix habituel de Tor)",
               "fr": "France", "be": "Belgique", "ch": "Suisse", "lu": "Luxembourg", "de": "Allemagne", "nl": "Pays-Bas",
               "gb": "Royaume-Uni", "ie": "Irlande", "es": "Espagne", "pt": "Portugal", "it": "Italie", "at": "Autriche",
               "se": "Suède", "no": "Norvège", "dk": "Danemark", "fi": "Finlande", "pl": "Pologne", "cz": "Tchéquie",
               "ca": "Canada", "us": "États-Unis"}


def _code_acces(v):
    """Vide (généré au hasard) ou 8 à 64 caractères imprimables, sans espace."""
    return isinstance(v, str) and (v == "" or (8 <= len(v) <= 64 and v.isprintable() and " " not in v))


def _liste_mots(v):
    """Ta liste de mots : séparés par des virgules ou des retours à la ligne, 20 000 caractères au plus, sans autre caractère de
    contrôle."""
    return isinstance(v, str) and len(v) <= 20000 and not any(unicodedata.category(c)[0] == "C" and c not in "\n\r\t" for c in v)


def _son(v):
    """Vide (aucun son) ou le nom simple d'un fichier audio du dossier sons/ (le fichier lui-même n'est pas exigé ici)."""
    return v == "" or sons.nom_valide(v)


def _choix(options):
    return lambda v: isinstance(v, str) and v in options


def _couleur(v):
    return theme.couleur_valide(v)


def _langue(v):
    return isinstance(v, str) and re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})?", v) is not None


def _contact(v):
    """Texte affiché dans l'en-tête envoyé à Wikimedia : ASCII imprimable, sans retour à la ligne."""
    return isinstance(v, str) and len(v) <= 100 and re.fullmatch(r"[\x20-\x7e]*", v) is not None


def _texte(mini, maxi):
    """Texte libre (titre, biographie...) : de `mini` à `maxi` caractères, sans retour à la
    ligne ni caractère de contrôle ; les espaces autour sont ignorés."""
    def verifier(v):
        if not isinstance(v, str) or any(unicodedata.category(c)[0] == "C" for c in v):
            return False
        return mini <= len(v.strip()) <= maxi
    return verifier


def _texte_affiche(mini, maxi):
    """Comme _texte, pour du texte qui peut contenir des EMOJIS (titre, biographie) : la longueur est celle qu'on VOIT
    (un emoji compte pour 1, même composé) ; les emojis composés (famille, drapeaux, couleurs de peau) sont permis ;
    les caractères de contrôle, de direction, invisibles ou les espaces spéciaux ne le sont pas."""
    def verifier(v):
        if not isinstance(v, str) or web.normaliser_caracteres(v) != unicodedata.normalize("NFC", v):
            return False
        return mini <= web.longueur_affichee(v.strip()) <= maxi
    return verifier


def _papier(v):
    return (isinstance(v, (list, tuple)) and len(v) == 2
            and all(_nombre(50, 1000)(x) for x in v))


def _code(v):
    return isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9]{1,6}", v) is not None


def _paliers(v):
    """Liste de (code, seuil de vues par jour, nom) : seuils strictement décroissants,
    le dernier à 0, codes uniques."""
    if not isinstance(v, (list, tuple)) or not 2 <= len(v) <= 12:
        return False
    codes, seuils = [], []
    for palier in v:
        if not isinstance(palier, (list, tuple)) or len(palier) != 3:
            return False
        code, seuil, nom = palier
        if not _code(code) or not _nombre(0, 10**9)(seuil):
            return False
        if not (isinstance(nom, str) and 1 <= len(nom.strip()) <= 40):
            return False
        codes.append(code)
        seuils.append(seuil)
    return (len(set(codes)) == len(codes) and seuils[-1] == 0
            and all(a > b for a, b in zip(seuils, seuils[1:])))


def _poids(v):
    return (isinstance(v, dict) and 1 <= len(v) <= 12
            and all(_code(k) and _nombre(0, 10**6)(x) for k, x in v.items())
            and any(x > 0 for x in v.values()))


def _themes(v):
    """Pour chaque rang : un motif, trois couleurs (#rrggbb) et un reflet, parmi les choix."""
    if not isinstance(v, dict) or not 1 <= len(v) <= 12:
        return False
    for code, t in v.items():
        if not _code(code) or not isinstance(t, dict) or set(t) != {"motif", "couleurs", "reflet"}:
            return False
        if t["motif"] not in theme.MOTIFS or t["reflet"] not in theme.REFLETS:
            return False
        couleurs = t["couleurs"]
        if not (isinstance(couleurs, (list, tuple)) and len(couleurs) == 3
                and all(theme.couleur_valide(c) for c in couleurs)):
            return False
    return True


def _decoder_themes(v):
    """Couleurs en minuscules (pour comparer sans ambiguïté). Les clés en trop sont gardées :
    c'est la vérification qui les refuse."""
    return {code: {**t, "couleurs": [c.lower() if isinstance(c, str) else c
                                     for c in t["couleurs"]]} for code, t in v.items()}


def _symboles(v):
    """Lettres de chaque rang : de 1 à 3 lettres ou chiffres, toutes différentes (sans tenir
    compte des majuscules), et pas un nom réservé par Windows (elles servent de nom de dossier)."""
    if not isinstance(v, dict) or not 1 <= len(v) <= 12:
        return False
    reserves = {"con", "prn", "aux", "nul"}
    vus = set()
    for code, symbole in v.items():
        if not _code(code) or not isinstance(symbole, str):
            return False
        if not 1 <= len(symbole) <= 3 or not symbole.isalnum():
            return False
        cle = symbole.casefold()
        if cle in reserves or cle in vus:
            return False
        vus.add(cle)
    return True


def _theme_unique(v):
    """Un seul thème (motif, trois couleurs, reflet) : celui du palier des cartes personnalisées."""
    return _themes({"X": v})


def _symbole_perso(v):
    """Lettres du palier des cartes personnalisées : de 1 à 5 caractères (lettres, chiffres, symboles ou
    emoji), sans espace ni caractère de contrôle."""
    return (isinstance(v, str) and 1 <= len(v) <= theme.SYMBOLE_PERSO_MAX
            and all(profil.caractere_permis(c) and c != " " for c in v))


def _nom_perso(v):
    """Nom du palier des cartes personnalisées : 1 à 40 caractères."""
    return (isinstance(v, str) and 1 <= len(v.strip()) <= theme.PALIER_PERSO_MAX
            and all(profil.caractere_permis(c) for c in v))


_HOTE_PORT = re.compile(r"[A-Za-z0-9._\-\[\]:]{1,100}:\d{1,5}")


def _hote_port(v):
    """« hôte:port » (port de 1 à 65535) : lettres, chiffres, points, tirets."""
    if not (isinstance(v, str) and _HOTE_PORT.fullmatch(v)):
        return False
    return 1 <= int(v.rsplit(":", 1)[1]) <= 65535


def _nom_categorie_auto(v):
    """Nom d'une catégorie automatique : 1 à 30 caractères visibles, sans balise ni caractère de contrôle."""
    if not isinstance(v, str) or v != " ".join(v.split()) or not 1 <= len(v) <= 30:
        return False
    return not any(unicodedata.category(c)[0] == "C" or c in "<>&\"" for c in v)


_IMAGE_PAQUET = re.compile(r"/image/[0-9a-f]{32}\.(?:png|jpg)")


def _booster_image(v):
    """Vide (pas d'image), ou l'adresse locale d'une image PNG/JPEG téléversée (« /image/<32 caractères>.png »)."""
    return v == "" or (isinstance(v, str) and _IMAGE_PAQUET.fullmatch(v) is not None)


def _normaliser_chemin(v):
    """Ce que le programme enregistre pour un chemin saisi : sans espaces ni guillemets autour (« Copier comme chemin »
    de Windows en ajoute) et avec « / » comme séparateur, même si on a écrit « \\ »."""
    if not isinstance(v, str):
        return v
    return v.strip().strip('"').strip().replace("\\", "/")


def _afficher_chemin(v):
    """Un chemin tel qu'on le VOIT dans le champ : avec « \\ » sous Windows (il est enregistré avec « / »)."""
    return v.replace("/", "\\") if config.CHEMINS_AVEC_ANTISLASH and isinstance(v, str) else v


def _tor_executable(v):
    """Vide, ou le chemin d'un programme nommé « tor » ou « tor.exe » (on ne lance rien d'autre)."""
    if v == "":
        return True
    return (isinstance(v, str) and len(v) <= 300 and not any(unicodedata.category(c)[0] == "C" for c in v)
            and v.replace("\\", "/").rsplit("/", 1)[-1].lower() in ("tor", "tor.exe"))


def _adresse_directe(v):
    """Vide, ou « hôte:port » publié aux autres collectionneurs."""
    return isinstance(v, str) and (v == "" or _hote_port(v))


def _filtre_rangs(v):
    return isinstance(v, list) and len(v) <= 12 and all(_code(x) for x in v)


def _filtre_categorie(v):
    """Filtre de catégorie de la collection : rien (toutes), -1 (sans catégorie), -2 (doublons),
    -3 (sans illustration), -4 (animée) ou l'identifiant d'une catégorie."""
    return v is None or (isinstance(v, int) and not isinstance(v, bool) and v >= -4)


# ---------------------------------------------------------------------------- registre

class Param:
    """Un paramètre de config.py : sa vérification et sa description pour la page."""

    def __init__(self, nom, groupe, libelle, type_, verifier, decoder=None, aide="",
                 unite="", mini=None, maxi=None, pas=None, choix=None, redemarrage=False,
                 erreur="", affichage=None):
        self.nom, self.groupe, self.libelle, self.type = nom, groupe, libelle, type_
        self.verifier = verifier
        self.decoder = decoder or (lambda v: v)
        self.aide, self.unite = aide, unite
        self.mini, self.maxi, self.pas, self.choix = mini, maxi, pas, choix
        self.redemarrage = redemarrage
        self.erreur = erreur
        self.affichage = affichage or (lambda v: v)        # valeur -> ce qu'on VOIT dans le champ (ex. « / » -> « \\ »)

    def message(self):
        """Phrase d'erreur affichée quand la valeur est refusée."""
        if self.erreur:
            return self.erreur
        if self.type in ("entier", "nombre"):
            return f"doit être un nombre entre {self.mini} et {self.maxi}"
        if self.type == "choix":
            return "choix invalide"
        if self.type == "couleur":
            return "couleur invalide (format #rrggbb)"
        if self.type == "bool":
            return "doit être oui ou non"
        return "valeur refusée"


# Ordre de la page Configuration : d'abord ce qui se voit et se règle tous les jours (identité, apparence, disposition,
# paquets, rangs, collection, profil, export), puis les réglages techniques (Wikipédia, réserve), puis le plus complexe
# (Hall des collections : partage pair à pair, Tor), et TOUT À LA FIN le système (informations en lecture seule).
GROUPES = [
    ("identite", "Identité du site : logo, titre et biographie"),
    ("apparence", "Apparence du site et des cartes"),
    ("disposition", "Disposition de la page : menu, barre d'outils et paquet"),
    ("paquets", "Paquets et booster"),
    ("raretes", "Raretés et apparence des cartes"),
    ("collection", "Collection, pagination et catégories"),
    ("recherche", "Recherche de cartes"),
    ("sensible", "Contenu sensible : flou des images"),
    ("profil", "Page de profil : les vitrines"),
    ("export", "Export et impression"),
    ("sons", "Sons et musique"),
    ("wikipedia", "Wikipédia et tirage"),
    ("reserve", "Réserve de cartes (pré-chargement)"),
    ("partage", "Partage entre collectionneurs (Hall des collections)"),
    ("reseau", "Accès depuis le réseau et l'extérieur"),
    ("systeme", "Système"),
]

# Nom court de chaque section dans le menu « Aller à » du haut de la page, et phrase qui l'explique.
GROUPES_COURTS = {"identite": "Identité", "apparence": "Apparence", "disposition": "Disposition", "paquets": "Paquets",
                  "raretes": "Raretés", "collection": "Collection", "profil": "Profil", "recherche": "Recherche", "sensible": "Contenu sensible", "export": "Export", "sons": "Sons",
                  "wikipedia": "Wikipédia", "reserve": "Réserve", "partage": "Hall des collections", "reseau": "Accès réseau", "systeme": "Système"}
GROUPES_AVANCES = ("wikipedia", "reserve", "partage", "reseau", "systeme")      # réglages techniques ou complexes
GROUPES_EXPLICATION = {
    "identite": "Le nom, la biographie et le logo affichés en haut des pages.",
    "apparence": "Thème clair ou sombre, couleurs, tailles du titre et des cartes, effets.",
    "disposition": "Où se placent le menu, la barre d'outils et le paquet : choisis ce qui laisse voir tes cartes tout de suite.",
    "paquets": "Le paquet à ouvrir : nombre de cartes, style du sachet, animation d'ouverture.",
    "raretes": "Les rangs des cartes (seuils, probabilités, noms, couleurs, reflets) et le palier « Personnalisée ».",
    "collection": "Affichage de la collection, pagination et catégories (créées par toi ou automatiques).",
    "profil": "Les vitrines de ta page de profil.",
    "export": "Exports en image, PDF et Word.",
    "recherche": "Dans quels champs chaque recherche cherche-t-elle ? Titre et sous-titre par défaut ; coche « Description » pour chercher aussi dans le texte.",
    "sensible": "Les images des cartes qui parlent d'anatomie ou de pratiques sexuelles sont floutées d'office : on garde la carte, seule l'image est cachée.",
    "reseau": "Ouvrir le programme à d'autres appareils (téléphone, autre ordinateur, tunnel) : protégé par un code d'accès.",
    "sons": "Un son pour chaque événement (ouverture du paquet, cartes, corbeille...) et une musique d'ambiance : tes fichiers audio.",
    "wikipedia": "Réglages avancés : tirage aléatoire et politesse envers Wikipédia.",
    "reserve": "Réglages avancés : cartes pré-chargées en arrière-plan.",
    "partage": "Réglages avancés : partager ta collection avec d'autres collectionneurs (pair à pair, Tor). À lire avant de toucher.",
    "systeme": "Informations techniques en lecture seule : serveur local, dossiers, base de données.",
}


def _entier_p(nom, groupe, libelle, mini, maxi, aide="", unite="", redemarrage=False):
    return Param(nom, groupe, libelle, "entier", _entier(mini, maxi), aide=aide, unite=unite,
                 mini=mini, maxi=maxi, pas=1, redemarrage=redemarrage)


def _nombre_p(nom, groupe, libelle, mini, maxi, pas, aide="", unite=""):
    return Param(nom, groupe, libelle, "nombre", _nombre(mini, maxi), aide=aide, unite=unite,
                 mini=mini, maxi=maxi, pas=pas)


def _choix_p(nom, groupe, libelle, options, aide="", redemarrage=False):
    return Param(nom, groupe, libelle, "choix", _choix(options), aide=aide, choix=options, redemarrage=redemarrage)


def _liste_params():
    return [
        Param("TITRE_SITE", "identite", "Titre", "texte", _texte_affiche(1, 60), maxi=60,
              decoder=lambda v: v.strip() if isinstance(v, str) else v,
              aide="Le titre de la page : par exemple le nom de ta collection (60 caractères "
                   "au maximum). Les emojis sont permis 🎴✨ (chacun compte pour un caractère).",
              erreur="le titre doit faire de 1 à 60 caractères (emojis permis)"),
        _entier_p("TITRE_TAILLE", "identite", "Taille du titre", 18, 80, "", "px"),
        Param("BIO_SITE", "identite", "Courte biographie", "texte", _texte_affiche(0, 160), maxi=160,
              decoder=lambda v: v.strip() if isinstance(v, str) else v,
              aide="Une ligne sous le titre, en plus petit. Laisse vide pour ne rien afficher "
                   "(160 caractères au maximum). Les emojis sont permis 😀📚 (chacun compte pour un caractère).",
              erreur="la biographie fait 160 caractères au maximum (emojis permis)"),
        _entier_p("BIO_TAILLE", "identite", "Taille de la biographie", 10, 40,
                  "Toujours plus petite que la taille du titre.", "px"),
        Param("NOMBRE_CARTES_PAQUET", "paquets", "Cartes par paquet", "choix", lambda v: v in (5, 10, 20),
              decoder=lambda v: int(v) if v in ("5", "10", "20") else v,
              choix={5: "5 cartes : 10 paquets prêts à ouvrir", 10: "10 cartes : 3 paquets prêts à ouvrir",
                     20: "20 cartes : 1 paquet prêt à ouvrir"},
              aide="Le nombre de cartes de chaque paquet : 5, 10 ou 20. Il fixe aussi le stock de paquets prêts (10, 3 ou 1) : "
                   "quand on les a tous ouverts, il se reconstitue peu à peu, un paquet à la fois, pour qu'il soit de nouveau "
                   "plein en 1 heure (un paquet toutes les 6, 20 ou 60 minutes), sans jamais solliciter Wikipédia à l'excès. "
                   "Le décompte indique l'attente."),
        Param("RESERVE_ACTIVE", "reserve", "Pré-charger des cartes d'avance", "bool", _booleen,
              aide="Le programme prépare des cartes en arrière-plan, poliment : l'ouverture d'un paquet "
                   "devient instantanée et reste possible même si Wikipédia est indisponible."),
        _entier_p("STATS_REQUETES_HEURE", "reserve", "Requêtes de statistiques par heure (maximum)", 10,
                  1000, "Plafond strict pour récupérer les modifications et liens entrants des cartes "
                  "(2 requêtes par carte, en arrière-plan).", "requêtes"),
        Param("SONS_ACTIFS", "sons", "Jouer les sons des événements", "bool", _booleen,
              aide="Interrupteur général des effets sonores. Chaque événement a son fichier ci-dessous (aucun son par défaut : "
                   "dépose tes fichiers dans le dossier « sons » ou téléverse-les ici)."),
        _entier_p("SONS_VOLUME", "sons", "Volume des sons des événements", 0, 100, "De 0 à 100.", "%"),
        Param("SON_OUVERTURE", "sons", "Son : ouverture du paquet", "son", _son,
              aide="Joué au moment où le paquet disparaît."),
        Param("SON_EFFET_PAQUET", "sons", "Son : effet du paquet qui s'ouvre", "son", _son,
              aide="Joué dès que tu cliques sur le paquet, avec son animation (secousse, éclair, rotation...), avant qu'il "
                   "disparaisse. Le son « ouverture du paquet » ci-dessus est joué, lui, au moment où il disparaît."),
        Param("SON_EFFET_PAQUET_BOUCLE", "sons", "Jouer en boucle le son « effet du paquet qui s'ouvre »", "bool", _booleen,
              aide="Le son d'effet du paquet recommence tant que le paquet s'anime (secousse, rotation... pendant l'attente de Wikipédia) et "
                   "s'arrête dès que le paquet s'ouvre. Ne concerne que ce son-là : tous les autres se jouent une seule fois."),
        Param("SON_CARTE_FENETRE", "sons", "Son : chaque carte du paquet", "son", _son,
              aide="Joué pour CHAQUE carte qui apparaît, l'une après l'autre, dans la fenêtre du paquet (avant qu'elles "
                   "n'arrivent dans la collection)."),
        Param("SON_ARRIVEE", "sons", "Son : arrivée dans la collection", "son", _son,
              aide="Joué quand les cartes du paquet arrivent dans la collection."),
        Param("SON_CORBEILLE", "sons", "Son : cartes à la corbeille", "son", _son,
              aide="Joué quand des cartes sont supprimées et vont à la corbeille."),
        Param("SON_RETRAIT", "sons", "Son : carte retirée de la fenêtre du paquet", "son", _son,
              aide="Joué quand tu retires une carte avec la petite croix ✕ de la fenêtre du paquet (elle est supprimée "
                   "avant d'entrer dans la collection)."),
        Param("SON_RESTAURATION", "sons", "Son : restauration depuis la corbeille", "son", _son,
              aide="Joué quand des cartes sont restaurées depuis la corbeille."),
        Param("SON_SUPPRESSION", "sons", "Son : suppression définitive", "son", _son,
              aide="Joué quand des cartes de la corbeille sont supprimées pour de bon (vidage de la corbeille)."),
        Param("MUSIQUE_ACTIVE", "sons", "Musique d'ambiance", "bool", _booleen,
              aide="Une musique en boucle pendant que tu utilises le programme. Le navigateur peut attendre ton premier clic "
                   "avant de la lancer ; un petit bouton 🔊 en bas à gauche la coupe ou la relance."),
        Param("MUSIQUE_FICHIER", "sons", "Musique : fichier", "son", _son, aide="Le fichier de la musique d'ambiance."),
        _entier_p("MUSIQUE_VOLUME", "sons", "Musique : volume", 0, 100,
                  "De 0 à 100. Un petit curseur discret à côté du haut-parleur (en bas à gauche de l'écran) le règle aussi.", "%"),
        Param("MUSIQUE_COUPEE", "sons", "Musique : haut-parleur barré", "bool", _booleen,
              aide="Coché : la musique est coupée (haut-parleur barré) et ne repart pas au prochain lancement. Se règle "
                   "aussi en cliquant sur le haut-parleur ; ton choix est gardé d'un lancement à l'autre."),
        Param("FENETRE_APPLICATION", "sons", "Lancer dans une fenêtre d'application", "bool", _booleen, redemarrage=True,
              aide="Ouvre le programme dans sa propre fenêtre (Edge ou Chrome, avec son profil à part) au lieu de ton "
                   "navigateur habituel : la musique d'ambiance peut alors démarrer toute seule au lancement (un navigateur "
                   "normal exige un premier clic). Au prochain lancement ; sans Edge ni Chrome, le navigateur habituel est utilisé."),
        Param("RESERVE_BLOQUER_OUVERTURE", "reserve", "Bloquer l'ouverture tant que la réserve n'est pas complète", "bool", _booleen,
              aide="Le paquet reste visible mais un clic ne fait rien tant que le pré-chargement n'a pas rempli la réserve "
                   "(toutes les cartes ET toutes leurs statistiques). Un décompte en minutes indique quand le prochain paquet "
                   "sera prêt. Sans effet si le pré-chargement est désactivé."),
        Param("STATS_AVEC_PAQUET", "reserve", "Statistiques complètes à l'ouverture d'un paquet", "bool", _booleen,
              aide="Les modifications et les liens entrants des cartes d'un paquet sont récupérés TOUT DE SUITE et arrivent "
                   "avec les cartes (au lieu d'attendre le plafond horaire). Le décompte de l'ouverture en tient compte. "
                   "Si Wikipédia limite le débit, le paquet s'ouvre quand même et le reste est complété plus tard."),
        _nombre_p("STATS_PAUSE_PAQUET", "reserve", "Pause entre deux requêtes de statistiques d'un paquet", 0.1, 3, 0.1,
                  "Plus courte que la pause habituelle, car la page attend ces statistiques : avec 0,3 s, un paquet de 6 "
                  "cartes demande environ 5 s de plus à l'ouverture.", "s"),
        _entier_p("RESERVE_VALIDITE_JOURS", "reserve", "Durée de validité d'une carte préparée", 1, 60,
                  "Une carte préparée depuis plus longtemps est jetée : ses vues ont vieilli.", "jours"),
        _nombre_p("RESERVE_PAUSE", "reserve", "Pause entre deux requêtes de pré-chargement", 1, 60, 0.5,
                  "Plus douce que la pause normale : le pré-chargement n'est jamais pressé.",
                  "secondes"),
        _entier_p("RESERVE_REQUETES_HEURE", "reserve", "Requêtes de pré-chargement par heure (maximum)",
                  10, 600, "Plafond strict : au-delà, le pré-chargement attend.", "requêtes"),
        Param("BOOSTER_AFFICHER", "paquets", "Afficher le paquet à ouvrir", "bool", _booleen,
              aide="Décoché : le paquet disparaît de la page et les cartes de la collection "
                   "remontent. Tu ne peux alors plus tirer de cartes au hasard (la page "
                   "« Recherche » permet toujours d'en ajouter)."),
        _choix_p("BOOSTER_THEME", "paquets", "Style du booster", booster.choix_styles(),
                 "L'apparence du sachet : 10 styles prêts à l'emploi, ou « Image personnalisée » pour utiliser ta propre "
                 "image (à téléverser plus bas)."),
        _choix_p("BOOSTER_SURVOL", "paquets", "Paquet : effet au passage de la souris", theme.EFFETS_SURVOL,
                 "Ce que fait le paquet quand la souris passe dessus : les mêmes effets que pour les cartes. L'effet "
                 "se voit dans l'aperçu ci-dessous."),
        _choix_p("BOOSTER_REPOS", "paquets", "Paquet : animation au repos", theme.ANIMATIONS_ZOOM,
                 "Une animation douce quand la souris n'est PAS sur le paquet : les mêmes que celles de la carte "
                 "agrandie (« Suit la souris » devient un balancement 3D lent). « Aucune » : le paquet reste immobile."),
        _entier_p("GODPACK_UN_SUR", "paquets", "GOD PACK : 1 chance sur", 0, 1000000,
                  aide="À chaque ouverture, une chance sur ce nombre d'obtenir un GOD PACK : un paquet dont TOUTES les cartes sont "
                       "légendaires, annoncé par un feu d'artifice, une fanfare et un message « GOD PACK !!! » sur lequel on clique "
                       "pour ouvrir le paquet. 10 000 par défaut ; 0 : jamais. Le bouton ci-dessus montre l'animation.", unite="chance sur N"),
        Param("PAQUET_FENETRE", "paquets", "Afficher les cartes d'un paquet dans une fenêtre", "bool", _booleen,
              aide="À l'ouverture, les cartes apparaissent d'abord au milieu de l'écran, une à une : tu peux en retirer "
                   "(elles sont alors supprimées tout de suite) puis cliquer sur « Ajouter à la collection »."),
        Param("BOOSTER_IMAGE", "paquets", "Image du paquet personnalisé", "image_paquet", _booster_image,
              aide="L'image PNG ou JPEG de ton paquet (téléversée avec le bouton « Choisir une image » plus bas)."),
        _choix_p("BOOSTER_FORME", "paquets", "Paquet personnalisé : forme", booster.FORMES,
                 "La forme du paquet affiché : les proportions de l'image, un rectangle vertical ou horizontal, un carré "
                 "ou un rond. Seulement avec le style « Image personnalisée »."),
        _choix_p("BOOSTER_AJUSTEMENT", "paquets", "Paquet personnalisé : cadrage", booster.AJUSTEMENTS,
                 "Recadrer : l'image remplit la forme (les bords peuvent être coupés). Image entière : rien n'est coupé."),
        _choix_p("BOOSTER_IMAGE_CONTENU", "paquets", "Paquet personnalisé : ce qu'on place dessus", booster.CONTENUS,
                 "Rien (juste ton image), le logo du jeu, ou le texte du booster, centré sur l'image."),
        _choix_p("BOOSTER_ANIMATION", "paquets", "Animation d'ouverture", booster.choix_animations(),
                 "Courte (moins d'une seconde) et légère pour l'ordinateur."),
        Param("BOOSTER_TEXTE", "paquets", "Texte du booster (sans logo)", "texte", _texte(1, 40),
              maxi=40, decoder=lambda v: v.strip() if isinstance(v, str) else v,
              aide="Un mot ou une phrase, affiché sur le booster seulement quand il n'y a pas de "
                   "logo (40 caractères au maximum).",
              erreur="le texte doit faire de 1 à 40 caractères"),
        Param("BOOSTER_DECOMPTE", "paquets", "Décompte avant l'ouverture", "bool", _booleen,
              aide="Affiche, pendant l'ouverture, les secondes restantes avant que le paquet "
                   "s'ouvre. Il est calculé d'après la « Pause entre deux requêtes » (section "
                   "Système) et corrigé en direct."),
        Param("BOOSTER_LEGENDE", "paquets", "Légende sous le booster", "bool", _booleen,
              aide="Affiche « Ouvrir un paquet · 5 cartes » sous le booster."),
        Param("LANGUE", "wikipedia", "Langue de Wikipédia", "texte", _langue,
              aide="Code de la langue : fr, en, es, de... Les nouveaux tirages utilisent "
                   "cette langue."),
        _entier_p("RECHERCHE_MAX_RESULTATS", "wikipedia", "Résultats par recherche", 1, 20,
                  "Nombre de cartes chargées par la page « Recherche » (de 1 à 20, 20 par défaut), et "
                  "de plus à chaque clic sur « Voir plus de résultats ». Chaque chargement ne fait qu'une "
                  "requête à Wikipédia.", "cartes"),
        _entier_p("NB_PHRASES", "wikipedia", "Phrases de l'introduction", 1, 10,
                  "Nombre maximum de phrases de l'introduction affichées sur la carte.", "phrases"),
        _entier_p("JOURS_VUES", "wikipedia", "Période de mesure des vues", 1, 60,
                  "Nombre de jours sur lesquels on calcule les vues moyennes d'un article.",
                  "jours"),
        _entier_p("TAILLE_MINIATURE", "wikipedia", "Taille de la miniature", 100, 2000,
                  "Largeur de l'image utilisée sur les cartes.", "px"),
        _nombre_p("SEUIL_TOP_UNIQUEMENT", "wikipedia", "Seuil « top des plus vus »", 0, 10**9, 1,
                  "Au-dessus de ce nombre de vues par jour, un article est cherché uniquement "
                  "dans le top des plus consultés.", "vues/jour"),
        _entier_p("TAILLE_LOT", "wikipedia", "Articles par recherche aléatoire", 1, 50,
                  "Nombre d'articles tirés à chaque requête lors de la recherche d'un rang.",
                  "articles"),
        _entier_p("MAX_LOTS", "wikipedia", "Recherches maximum par rang", 1, 30,
                  "Nombre maximum de requêtes pour trouver un article d'un rang.", "requêtes"),
        Param("PALIERS", "raretes", "Rangs, seuils et noms", "special", _paliers,
              decoder=lambda v: [tuple(p) for p in v]),
        Param("POIDS", "raretes", "Probabilités de tirage", "special", _poids),
        Param("THEMES_PALIERS", "raretes", "Apparence des rangs", "special", _themes,
              decoder=_decoder_themes),
        Param("SYMBOLES_PALIERS", "raretes", "Lettres des rangs", "special", _symboles),
        Param("PERSO_THEME", "raretes", "Apparence du palier des cartes personnalisées", "special",
              _theme_unique, decoder=lambda v: {**v, "couleurs": [c.lower() if isinstance(c, str) else c
                                                                  for c in v.get("couleurs", [])]}),
        Param("PERSO_SYMBOLE", "raretes", "Lettres du palier des cartes personnalisées", "special",
              _symbole_perso),
        Param("PERSO_NOM", "raretes", "Nom du palier des cartes personnalisées", "special", _nom_perso,
              decoder=lambda v: v.strip() if isinstance(v, str) else v),
        Param("P2P_ACTIF", "partage", "Partage : activer mon nœud", "bool", _booleen,
              aide="Démarre ton nœud pair à pair : les autres collectionneurs peuvent te trouver dans le Hall "
                   "des collections. Désactivé par défaut. Rien n'est visible tant que les pastilles P et C "
                   "(ci-dessous) ne sont pas vertes : même nœud actif, on ne voit alors que ton pseudo.",
              redemarrage=False),
        Param("P2P_PROFIL_PUBLIC", "partage", "Partage : profil visible (pastille P verte)", "bool", _booleen,
              aide="Les autres peuvent voir ton profil : titre, biographie, résumé et vitrines."),
        Param("P2P_COLLECTION_PUBLIQUE", "partage", "Partage : collection visible (pastille C verte)", "bool",
              _booleen, aide="Les autres peuvent parcourir ta collection (lecture seule) et rapatrier des "
                             "copies de tes cartes. Tes favoris, ta corbeille et tes réglages ne sont jamais envoyés."),
        _choix_p("P2P_TRANSPORT", "partage", "Partage : mode de connexion",
                 {"tor": "Tor (aucune ouverture de port, adresse IP cachée)"},
                 aide="Le partage entre collectionneurs passe uniquement par Tor : aucune ouverture de port, ton adresse IP "
                      "n'est jamais visible. Tor demande que le programme Tor soit lancé sur ta machine (voir le README)."),
        _choix_p("TOR_PAYS", "partage", "Tor : relais d'entrée du même pays (plus rapide)", dict(PAYS_RELAIS),
                 aide="Tor préfère alors des relais d'entrée situés dans ce pays : les connexions sont en général plus rapides. "
                      "C'est une PRÉFÉRENCE (Tor garde ses relais de secours). Contrepartie : un peu moins de diversité, donc un "
                      "anonymat légèrement moins bon ; « Aucune préférence » rend à Tor son choix habituel. Pris en compte au "
                      "prochain lancement de Tor par le programme (il faut aussi le fichier « geoip » livré avec Tor)."),
        _entier_p("P2P_PORT", "partage", "Partage : port du nœud", 1024, 65535,
                  "Port d'écoute du nœud pair à pair (différent de celui de la page locale).", redemarrage=True),
        Param("P2P_TOR_SOCKS", "partage", "Partage : proxy SOCKS de Tor", "texte", _hote_port,
              aide="Adresse du proxy SOCKS de Tor, pour joindre les autres collectionneurs (mode Tor)."),
        Param("P2P_TOR_EXECUTABLE", "partage", "Partage : chemin de tor.exe", "texte", _tor_executable,
              decoder=_normaliser_chemin, affichage=_afficher_chemin,
              aide="Pour le bouton « Lancer Tor » : chemin complet de tor.exe (Tor Expert Bundle). Par défaut : le dossier "
                   "« tor » à côté de main.py (<racine du programme>\\tor\\tor.exe). Tu peux écrire les dossiers avec « \\ » "
                   "ou « / ». Vide : le programme le cherche tout seul (Bureau, Téléchargements, PATH...)."),
        Param("P2P_TOR_AUTO", "partage", "Partage : lancer Tor au démarrage du programme", "bool", _booleen,
              aide="Quand le programme démarre en mode Tor et que Tor n'est pas déjà lancé, il le lance tout seul "
                   "(il faut que tor.exe soit trouvable). Tor s'arrête avec le programme."),
        Param("P2P_TOR_CONTROLE", "partage", "Partage : port de contrôle de Tor", "texte", _hote_port,
              aide="Adresse du port de contrôle de Tor, pour publier ton service oignon (mode Tor). "
                   "L'authentification par cookie est prise en charge (pas le mot de passe)."),
        _entier_p("CARTES_PAR_PAGE", "collection", "Cartes par page", 5, 200,
                  "Nombre de cartes affichées sur chaque page de la collection.", "cartes"),
        _entier_p("CATEGORIE_LONGUEUR_MAX", "collection", "Longueur du nom d'une catégorie sur la carte",
                  4, 40, "Au-delà, le nom est coupé et terminé par « … » (le nom complet s'affiche "
                  "au survol).", "caractères"),
        _entier_p("CATEGORIES_MAX_SUR_CARTE", "collection", "Bandeaux de catégorie par carte", 1, 6,
                  "Les catégories en trop sont résumées par « +2 », « +3 »...", "bandeaux"),
        Param("CATEGORIES_AUTO", "collection", "Classement automatique à l'ouverture d'un paquet",
              "bool", _booleen, aide="Classe les nouvelles cartes d'après les meta des catégories "
                                     "(cherchées dans la courte description et dans les phrases)."),
        Param("META_DANS_INTRO", "collection", "Meta : chercher aussi dans les phrases", "bool", _booleen,
              aide="Coché : les meta sont cherchées dans la ligne sous le titre ET dans les phrases de "
                   "l'introduction (utile quand une carte n'a pas de ligne sous son titre). Décoché : "
                   "seulement la ligne sous le titre."),
        Param("META_MOT_ENTIER", "collection", "Meta = mot entier", "bool", _booleen,
              aide="Décoché : « foot » trouve aussi « footballeur ». Coché : la meta doit être un "
                   "mot entier."),
        Param("STATS_CARTES", "collection", "Statistiques sous les cartes", "bool", _booleen,
              aide="Affiche, sous chaque carte, les langues disponibles, les modifications de la page, "
                   "les liens entrants et la taille de l'article. Les récupérer demande quelques "
                   "requêtes à Wikipédia, faites poliment en arrière-plan."),
        _choix_p("MENU_POSITION", "disposition", "Menu de navigation : emplacement",
                 {"centre": "Centré sous le titre (gagne de la place en hauteur)",
                  "droite": "À droite du titre (disposition d'origine)",
                  "lateral": "Colonne à gauche de l'écran (écrans larges ; sinon centré)"},
                 aide="Où se place la ligne de boutons Collection, Profil, Créateur, Recherche, Hall, Configuration. "
                      "L'effet se voit tout de suite sur cette page."),
        _choix_p("MENU_STYLE", "disposition", "Menu de navigation : taille des boutons",
                 {"complet": "Complet (icône et texte)",
                  "compact": "Compact (boutons plus petits)",
                  "icones": "Icônes seules (le nom s'affiche au survol)",
                  "replie": "Replié (un seul bouton « ☰ Menu » qui déroule les autres)"},
                 aide="Pour réduire la place prise par le menu : des boutons plus petits, des icônes seules, ou un menu replié."),
        _choix_p("BARRE_OUTILS", "disposition", "Barre d'outils de la collection (rangs, recherche, catégorie, tri, taille)",
                 {"compacte": "Compacte (centrée, étiquettes masquées, éléments plus petits : tient sur une ligne)",
                  "centree": "Centrée (avec les étiquettes)",
                  "gauche": "À gauche (disposition d'origine)",
                  "repliable": "Repliable (un bouton « Filtres, tri et taille » la déroule)"},
                 aide="La zone sous le titre de la collection : boutons de rang, recherche, catégorie, tri, sélection, taille des cartes."),
        _choix_p("PAQUET_POSITION", "disposition", "Paquet à ouvrir : place dans la page",
                 {"normal": "Normal (grand sachet, texte en dessous)",
                  "remonte": "Remonté (sachet plus petit, texte à côté : les cartes se voient tout de suite)",
                  "mini": "Compacte (petit sachet, texte en dessous)",
                  "compact": "Très compact (tout petit sachet, texte à côté)"},
                 aide="Plus le paquet est haut et petit, plus la première rangée de cartes se voit sans défiler."),
        _choix_p("MOBILE_MODE", "apparence", "Affichage sur téléphone",
                 {"auto": "Automatique : optimisé dès que l'écran est étroit ou tactile (recommandé)",
                  "toujours": "Toujours optimisé (même sur un écran d'ordinateur)",
                  "jamais": "Jamais : le même affichage que sur ordinateur"},
                 aide="Sur un téléphone, le programme reprend la mise en page pour tenir sur un petit écran : menu réduit à ses "
                      "icônes, filtres et tri repliés derrière un bouton « Filtres », cartes sur deux colonnes (la taille se règle "
                      "toute seule), mise en page de la Configuration allégée. La détection se fait d'après la largeur de "
                      "l'écran, pas d'après la marque de l'appareil : une fenêtre étroite sur ordinateur est aussi optimisée."),
        _choix_p("MOBILE_ENTETE", "apparence", "Téléphone : en-tête",
                 {"compact": "Compact : logo, titre court et menu (biographie et infos masquées)",
                  "minimal": "Minimal : logo et menu seulement",
                  "complet": "Complet : logo, titre, biographie et infos"},
                 aide="Ce qu'on garde en haut des pages quand l'affichage téléphone est actif. Les filtres et le tri restent "
                      "accessibles derrière le bouton « Filtres »."),
        _choix_p("LOGO_ALIGNEMENT", "disposition", "Logo : alignement",
                 {"gauche": "À gauche du titre (le tout contre le bord gauche)",
                  "gauche-centre": "Centré, à gauche du titre (logo et titre centrés ensemble)",
                  "centre": "Au milieu, au-dessus du titre",
                  "droite-centre": "Centré, à droite du titre (logo et titre centrés ensemble)",
                  "droite": "À droite du titre (le tout contre le bord droit)",
                  "menu": "Au-dessus du menu (quand le menu est en colonne à gauche)"},
                 aide="Où se place le logo dans l'en-tête de toutes les pages. « Au-dessus du menu » : le logo se pose en haut de la "
                      "colonne de gauche, au-dessus des boutons (menu en colonne à gauche, écran large) ; sinon il reste à gauche du titre. « Centré » : le logo et le titre forment un seul "
                      "bloc placé au milieu de la page. L'effet se voit tout de suite sur cette page."),
        _choix_p("TITRE_ALIGNEMENT", "disposition", "Titre de la collection : alignement",
                 {"gauche": "À gauche", "centre": "Au milieu (centré)", "droite": "À droite"},
                 aide="Où se place le titre dans l'en-tête de toutes les pages. L'effet se voit tout de suite sur cette page."),
        _choix_p("BIO_ALIGNEMENT", "disposition", "Biographie : alignement",
                 {"gauche": "À gauche", "centre": "Au milieu (centrée)", "droite": "À droite"},
                 aide="Où se place la courte biographie sous le titre."),
        _choix_p("INFOS_ALIGNEMENT", "disposition", "Ligne d'infos : alignement",
                 {"gauche": "À gauche", "centre": "Au milieu (centrée)", "droite": "À droite"},
                 aide="La ligne « 44 cartes dans la collection · Wikipédia (fr) · page du… » sous la biographie."),
        Param("MENTION_AFFICHER", "apparence", "Mention en bas de page", "bool", _booleen,
              aide="Affiche la mention d'auteur et de licence, centrée, en bas de chaque page (son texte est fixe)."),
        Param("ACCUEIL_AFFICHER", "apparence", "Message de bienvenue au démarrage", "bool", _booleen,
              aide="Affiche, une fois à chaque lancement du programme, un petit message de bienvenue. Il propose lui-même de ne plus l'afficher : "
                   "recoche cette case pour le revoir."),
        Param("DOUBLONS_ACTIFS", "collection", "Catégorie automatique « Doublons »", "bool", _booleen,
              aide="Marque d'un bandeau les cartes IDENTIQUES : même titre, même rang, même sous-titre, même description, même image et même "
                   "taille et position de l'image. Si le rang ou l'image d'une des deux est différent, ou dimensionnée autrement, "
                   "ce ne sont plus des doublons. Ajoute « Doublons » à la liste des catégories de la collection."),
        Param("NOM_DOUBLONS", "collection", "Nom de la catégorie automatique « Doublons »", "texte", _nom_categorie_auto,
              aide="Le nom affiché dans la liste « Catégorie » (le bandeau des cartes en est la forme au singulier : "
                   "« Doublon ×2 »). 1 à 30 caractères, différent des deux autres catégories automatiques."),
        Param("DOUBLONS_COULEUR", "collection", "Couleur du bandeau « Doublon »", "couleur", _couleur,
              decoder=lambda v: v.lower() if isinstance(v, str) else v),
        Param("SANS_ILLUSTRATION_ACTIF", "collection", "Catégorie automatique « Sans illustration »",
              "bool", _booleen,
              aide="Marque d'un bandeau les cartes dont l'article n'a pas d'image sur Wikipédia et "
                   "ajoute « Sans illustration » à la liste des catégories de la collection."),
        Param("NOM_SANS_ILLUSTRATION", "collection", "Nom de la catégorie automatique « Sans illustration »", "texte",
              _nom_categorie_auto, aide="Nom du bandeau et de l'entrée de la liste « Catégorie » (1 à 30 caractères)."),
        Param("SANS_ILLUSTRATION_COULEUR", "collection", "Couleur du bandeau « Sans illustration »",
              "couleur", _couleur, decoder=lambda v: v.lower() if isinstance(v, str) else v),
        Param("CATEGORIES_DANS_EXPORT", "collection", "Catégories sur les images exportées", "bool",
              _booleen, aide="Affiche les bandeaux de catégorie sur les PNG, PDF et Word."),
        _choix_p("THEME_SITE", "apparence", "Thème du site", theme.THEMES_SITE),
        Param("ANIMEE_ACTIF", "collection", "Catégorie automatique « Animée »", "bool", _booleen,
              aide="Les cartes dont l'illustration est un GIF RÉELLEMENT animé (un GIF fixe n'est pas classé : il est vérifié en arrière-plan) reçoivent automatiquement un bandeau "
                   "« Animée » (ouverture d'un paquet, recherche, rapatriement) et la liste des catégories propose « Animée ». "
                   "Activée par défaut."),
        Param("NOM_ANIMEE", "collection", "Nom de la catégorie automatique « Animée »", "texte", _nom_categorie_auto,
              aide="Nom du bandeau et de l'entrée de la liste « Catégorie » (1 à 30 caractères)."),
        Param("ANIMEE_COULEUR", "collection", "Couleur du bandeau « Animée »", "couleur", _couleur,
              aide="La couleur du petit bandeau des cartes animées."),
        Param("COULEUR_ACCENT", "apparence", "Couleur d'accent du site", "couleur", _couleur,
              decoder=lambda v: v.lower() if isinstance(v, str) else v,
              aide="Curseurs, boutons actifs, paquet de cartes... Pour « sombre » et « clair » ; les "
                   "autres thèmes ont la leur (sauf si la case ci-dessous est décochée)."),
        Param("ACCENT_DU_THEME", "apparence", "Couleur d'accent propre au thème", "bool", _booleen,
              aide="Coché : chaque thème utilise sa couleur d'accent. Décoché : la couleur "
                   "d'accent ci-dessus est utilisée pour tous les thèmes."),
        _choix_p("ANGLES_SITE", "apparence", "Angles du site", theme.ANGLES,
                 "Boutons, panneaux et pastilles de la page."),
        _choix_p("ANGLES_CARTES", "apparence", "Angles des cartes", theme.ANGLES,
                 "Coins des cartes (page, aperçu, images, PDF et Word)."),
        _choix_p("EFFET_SURVOL", "apparence", "Effet des cartes au survol", theme.EFFETS_SURVOL),
        _choix_p("ANIMATION_ZOOM", "apparence", "Animation de la carte agrandie", theme.ANIMATIONS_ZOOM,
                 "Léger mouvement de la carte quand tu cliques dessus pour l'agrandir : visible, mais "
                 "sans gêner la lecture. Coupé si ton ordinateur demande moins de mouvements."),
        Param("ICONE_LIEN", "apparence", "Icône : ouvrir l'article sur Wikipédia", "bool", _booleen,
              aide="Les icônes en haut à droite de chaque carte (l'étoile des favoris est toujours là)."),
        Param("ICONE_RAFRAICHIR", "apparence", "Icône : choisir l'illustration de la carte", "bool", _booleen,
              aide="Ajoute, sous l'étoile, une icône ⟳ qui liste TOUTES les images de l'article sur Wikipédia : tu choisis l'illustration de la carte "
                   "(puis tu valides), ou tu la retires pour que la carte n'en ait pas ; tu peux en remettre une quand tu veux. "
                   "Indisponible sur les cartes full-art (leur illustration est définitive) et sur les cartes personnalisées."),
        _choix_p("ACCES_RESEAU", "reseau", "Accès au programme",
                 {"local": "Seulement cet ordinateur (127.0.0.1) : verrouillé, comme avant",
                  "reseau": "Réseau local et extérieur : le programme est un serveur (téléphone, autre PC, tunnel, adresse IP)"},
                 aide="En mode « Réseau local et extérieur », le programme écoute sur toutes les interfaces : tant qu'il tourne sur "
                      "ton PC, tout appareil qui atteint son adresse l'utilise vraiment (ouvrir un paquet, modifier la collection...). "
                      "Attention : sans code, QUICONQUE atteint l'adresse peut tout faire. Au prochain lancement.",
                 redemarrage=True),
        Param("ACCES_CODE", "reseau", "Code d'accès (facultatif)", "texte", _code_acces, maxi=64,
              aide="Laisse VIDE (le cas normal) : aucun mot de passe, n'importe quel appareil qui atteint l'adresse utilise le "
                   "programme. Si tu en mets un (8 à 64 caractères, sans espace), tout ce qui ne vient pas de cet ordinateur "
                   "devra le taper une fois."),
        Param("CONFIG_AVANCE_LOCAL", "systeme", "Réglages avancés : réseau local seulement", "bool", _booleen,
              aide="Coché (par défaut) : les sections avancées de cette page (Wikipédia, Réserve, Hall des collections, Accès réseau, "
                   "Système) ne sont visibles ni modifiables que depuis cet ordinateur et les adresses du réseau local "
                   "(192.168.x.x, 10.x.x.x...). Depuis une adresse IP publique ou un tunnel, elles sont absentes de la page et "
                   "refusées par le serveur. Décoche pour les ouvrir à tous."),
        Param("RECH_COLL_TITRE", "recherche", "Page Collection : chercher dans le titre", "bool", _booleen,
              aide="Les trois cases de chaque recherche : si aucune n'est cochée, le titre est utilisé."),
        Param("RECH_COLL_SOUS_TITRE", "recherche", "Page Collection : chercher dans le sous-titre", "bool", _booleen),
        Param("RECH_COLL_DESCRIPTION", "recherche", "Page Collection : chercher dans la description", "bool", _booleen,
              aide="Le texte de la carte (introduction de l'article). Cela vaut aussi pour la visite d'une collection du Hall."),
        Param("RECH_PAGE_TITRE", "recherche", "Page Recherche : mots dans le titre", "bool", _booleen,
              aide="La page Recherche interroge Wikipédia puis garde les résultats dont TOUS les mots sont dans les champs cochés "
                   "(les autres sont comptés comme « masqués »)."),
        Param("RECH_PAGE_SOUS_TITRE", "recherche", "Page Recherche : mots dans le sous-titre", "bool", _booleen),
        Param("RECH_PAGE_DESCRIPTION", "recherche", "Page Recherche : mots dans la description", "bool", _booleen,
              aide="Le début de l'article. Coche-la pour retrouver aussi ce qui ne figure ni dans le titre ni dans le sous-titre."),
        Param("RECH_PROFIL_TITRE", "recherche", "Page Profil (choix d'une carte) : titre", "bool", _booleen),
        Param("RECH_PROFIL_SOUS_TITRE", "recherche", "Page Profil (choix d'une carte) : sous-titre", "bool", _booleen),
        Param("RECH_PROFIL_DESCRIPTION", "recherche", "Page Profil (choix d'une carte) : description", "bool", _booleen),
        Param("FLOU_ACTIF", "sensible", "Flouter les images à contenu sensible", "bool", _booleen,
              aide="Les cartes dont le titre, le sous-titre ou la description évoquent l'anatomie sexuelle (masculine ou féminine), "
                   "des pratiques ou positions sexuelles, de la pornographie ou de l'érotisme — même dans un cadre médical — "
                   "gardent leur texte mais leur image est floutée. Cela concerne aussi les collections que tu visites."),
        _entier_p("FLOU_FORCE", "sensible", "Intensité du flou", 4, 40, "De 4 (léger) à 40 (image illisible).", "px"),
        Param("FLOU_ICONE", "sensible", "Icône « interdit aux moins de 18 ans » sur ces cartes", "bool", _booleen,
              aide="Une petite icône 🔞 sous l'étoile des cartes concernées : un clic montre l'image, un autre la floute de nouveau."),
        Param("FLOU_MOTS", "sensible", "Ta liste de mots et expressions à flouter", "zone", _liste_mots, maxi=20000,
              aide="AUCUNE liste n'est fournie : c'est toi qui décides de ce qui est sensible. Écris un mot ou une expression par "
                   "ligne (ou séparés par des virgules) ; sans accents ni majuscules à respecter. Une carte dont le titre, le "
                   "sous-titre ou la description contient l'un de ces mots (mot entier) voit son image floutée et reçoit l'icône "
                   "+18. Une étoile à la fin trouve tous les mots qui commencent ainsi : « lingerie* » trouve lingeries... "
                   "Liste vide : aucune carte n'est floutée, aucune icône +18."),
        Param("FLOU_EXCEPTIONS", "sensible", "Mots qui écartent une carte (exceptions)", "zone", _liste_mots, maxi=20000,
              aide="Si le texte d'une carte contient l'un de ces mots, elle n'est jamais floutée, même si elle contient un mot de "
                   "ta liste. Même écriture que ci-dessus."),
        Param("ICONE_PNG", "export", "Icône : enregistrer en image (PNG)", "bool", _booleen),
        Param("ICONE_PDF", "export", "Icône : enregistrer en PDF", "bool", _booleen),
        Param("ICONE_WORD", "export", "Icône : enregistrer en document Word", "bool", _booleen),
        _entier_p("PROFIL_VITRINES", "profil", "Nombre de vitrines", 0, 12,
                  "Une vitrine est une ligne de cartes sur la page de profil. Les cartes et le titre "
                  "de chaque vitrine se choisissent directement sur la page de profil.", "vitrines"),
        _entier_p("PROFIL_EMPLACEMENTS", "profil", "Emplacements par vitrine", 1, 5,
                  "Nombre de cartes que peut contenir chaque vitrine (5 au maximum).", "emplacements"),
        _entier_p("LARGEUR_CARTE", "apparence", "Largeur des cartes", 120, 700,
                  "Taille des cartes sur la page (le curseur de la page règle la même valeur).",
                  "px"),
        _entier_p("LARGEUR_APERCU", "apparence", "Largeur de la carte agrandie", 240, 900,
                  "Taille de la carte affichée au milieu de l'écran quand on clique dessus.",
                  "px"),
        _entier_p("LARGEUR_EXPORT", "export", "Largeur de l'image PNG exportée", 300, 1800,
                  "Hauteur proportionnelle.", "px"),
        _nombre_p("IMPRESSION_LARGEUR_MM", "export", "Largeur de la carte imprimée", 30, 150, 0.5,
                  "PDF et Word : la hauteur suit automatiquement.", "mm"),
        _entier_p("IMPRESSION_DPI", "export", "Finesse de l'impression", 72, 600,
                  "300 = qualité d'impression.", "dpi"),
        _nombre_p("IMPRESSION_MARGE_MM", "export", "Marge autour de la carte", 0, 30, 0.5,
                  "Accueille les repères de coupe (5 mm ou plus).", "mm"),
        Param("IMPRESSION_REPERES", "export", "Repères de coupe", "bool", _booleen,
              aide="Petits repères aux quatre coins de la carte, pour la découper."),
        _nombre_p("IMPRESSION_QR_MM", "export", "Taille du QR code (verso)", 15, 75, 0.5,
                  "Au plus la moitié de la largeur de la carte.", "mm"),
        Param("PAPIER_MM", "export", "Taille de la feuille", "papier", _papier,
              decoder=lambda v: tuple(v),
              aide="A4 : 210 × 297 mm. Lettre US : 215,9 × 279,4 mm.", unite="mm"),
        Param("CONTACT", "systeme", "Contact (e-mail) ou lien du projet", "texte", _contact,
              aide="Wikimedia demande un moyen de te contacter : ton e-mail, ou le lien de ton projet "
                   "(par défaut : https://github.com/damballah/wikifreecards). Lettres, chiffres et symboles courants uniquement."),
        _nombre_p("PAUSE", "systeme", "Pause entre deux requêtes", 0, 10, 0.1,
                  "Délai minimal entre deux appels à Wikipédia.", "s"),
        _entier_p("MAX_ESSAIS", "systeme", "Tentatives si Wikipédia ralentit", 1, 10,
                  "Nombre d'essais quand Wikipédia répond « trop de requêtes ».", "essais"),
        Param("OUVRIR_NAVIGATEUR", "systeme", "Ouvrir le navigateur au lancement", "bool",
              _booleen, redemarrage=True),
        _entier_p("PORT_SERVEUR", "systeme", "Port du serveur local", 1024, 65535,
                  "S'applique au prochain lancement du programme.", redemarrage=True),
        _nombre_p("SAUVEGARDE_TOUS_LES_JOURS", "systeme", "Écart entre deux sauvegardes", 0, 365,
                  1, "Sauvegarde automatique de la base de données.", "jours"),
        _entier_p("SAUVEGARDES_GARDEES", "systeme", "Sauvegardes conservées", 1, 60,
                  "Nombre de sauvegardes gardées (les plus récentes).", "sauvegardes"),
    ]


PARAMETRES = {p.nom: p for p in _liste_params()}

# Réglages en lecture seule affichés dans la page Configuration (nom dans config.py -> libellé)
LECTURE_SEULE = {
    "SERVEUR_LOCAL": "Serveur local (se règle dans config.py)",
    "DOSSIER_EXPORT": "Dossier des cartes exportées",
    "DOSSIER_LOGO": "Dossier du logo",
    "FICHIER_BASE": "Base de données",
    "DOSSIER_SAUVEGARDES": "Sauvegardes de la base",
}

# Préférences de la page (n'existent pas dans config.py) : clé -> vérification
PREFERENCES = {
    # les cartes sensibles dont l'utilisateur a MONTRÉ l'image (icône +18) : leurs adresses d'article, gardées d'un lancement à l'autre
    "ui.flou_reveles": lambda v: isinstance(v, list) and len(v) <= 2000 and all(isinstance(x, str) and 0 < len(x) <= 500 for x in v),
    "ui.filtre_rangs": _filtre_rangs,
    "ui.favoris_seulement": _booleen,
    "ui.filtre_categorie": _filtre_categorie,
    "ui.tri": lambda v: isinstance(v, str) and v in base.TRIS,
    "ui.recherche": lambda v: isinstance(v, str) and len(v) <= 100 and not any(
        unicodedata.category(c)[0] == "C" for c in v),
}

# Ce que la page principale a le droit de modifier (curseur de taille, filtres)
MODIFIABLES_PAR_LA_PAGE = ("LARGEUR_CARTE", "MUSIQUE_COUPEE", "MUSIQUE_VOLUME", "ui.filtre_rangs", "ui.favoris_seulement",
                           "ui.filtre_categorie", "ui.tri", "ui.recherche")

# Les paramètres qui concernent les rangs : ils doivent toujours porter sur les mêmes rangs
PARAMETRES_RANGS = ("PALIERS", "POIDS", "THEMES_PALIERS", "SYMBOLES_PALIERS")


def _json(valeur):
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True)


def _etat_coherent(paliers, poids, themes, symboles):
    """Probabilités, thèmes et lettres doivent concerner exactement les rangs de PALIERS."""
    codes = {p[0] for p in paliers}
    return set(poids) == codes and set(themes) == codes and set(symboles) == codes


# ------------------------------------------------------------------ chargement

def valeurs_du_fichier():
    """Valeurs actuelles de config.py (à lire au tout début, avant tout changement)."""
    return {nom: copy.deepcopy(getattr(config, nom)) for nom in PARAMETRES}


def appliquer(nom, valeur):
    setattr(config, nom, valeur)
    if nom == "PALIERS":
        config.recalculer()


def synchroniser(conn, valeurs_fichier=None):
    """À appeler une fois au lancement : enregistre les paramètres, reprend ceux de la base
    et les applique. Renvoie la liste des paramètres repris de la base (pour information)."""
    fichier = valeurs_fichier if valeurs_fichier is not None else valeurs_du_fichier()
    repris = []
    effectives = {}
    for nom, param in PARAMETRES.items():
        valeur_fichier = fichier[nom]
        json_fichier = _json(valeur_fichier)
        ligne = base.lire_parametre_brut(conn, nom)

        if ligne is None or ligne[1] != json_fichier:
            # nouveau paramètre, ou modifié dans config.py : config.py l'emporte
            base.ecrire_parametre_brut(conn, nom, json_fichier, json_fichier)
            effectives[nom] = valeur_fichier
            continue

        try:
            brut = json.loads(ligne[0])
            if nom == "NOMBRE_CARTES_PAQUET" and isinstance(brut, int) and not isinstance(brut, bool) and 1 <= brut <= 20:
                brut = 5 if brut <= 7 else (10 if brut <= 14 else 20)        # ancien choix libre (1 à 20) : le plus proche
            valeur_base = param.decoder(brut)
            valide = param.verifier(valeur_base)
        except (ValueError, TypeError, KeyError):
            valide = False
        if valide and _json(valeur_base) != json_fichier:
            effectives[nom] = valeur_base
            repris.append(nom)
        else:
            if not valide:                                     # valeur abîmée : on la répare
                base.ecrire_parametre_brut(conn, nom, json_fichier, json_fichier)
            effectives[nom] = valeur_fichier

    if not _etat_coherent(*(effectives[nom] for nom in PARAMETRES_RANGS)):
        for nom in PARAMETRES_RANGS:                              # rangs incohérents : config.py
            effectives[nom] = fichier[nom]
            base.ecrire_parametre_brut(conn, nom, _json(fichier[nom]), _json(fichier[nom]))
        repris = [n for n in repris if n not in PARAMETRES_RANGS]
    for nom, valeur in effectives.items():
        appliquer(nom, valeur)
    return repris


# ------------------------------------------------------------------ modifications

class ValeurInvalide(ValueError):
    """La valeur proposée n'est pas acceptable."""


class ValeursInvalides(ValeurInvalide):
    """Plusieurs valeurs refusées : `erreurs` = {nom du paramètre: explication}."""

    def __init__(self, erreurs):
        super().__init__("; ".join(f"{nom} : {texte}" for nom, texte in erreurs.items()))
        self.erreurs = erreurs


def valide(cle, valeur):
    """Dit si `valeur` est acceptable pour `cle`, sans rien enregistrer.
    Pour un paramètre de config.py, `None` (retour à config.py) est accepté."""
    try:
        if cle in PARAMETRES:
            param = PARAMETRES[cle]
            return valeur is None or bool(param.verifier(param.decoder(valeur)))
        if cle in PREFERENCES:
            return bool(PREFERENCES[cle](valeur))
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    return False


def preparer(valeurs):
    """Vérifie plusieurs valeurs SANS rien écrire. Renvoie {nom: valeur décodée} ou lève
    ValeursInvalides (avec une explication par réglage refusé)."""
    erreurs, decodees = {}, {}
    for nom, brute in valeurs.items():
        param = PARAMETRES.get(nom)
        if param is None:
            erreurs[nom] = "paramètre inconnu"
            continue
        try:
            valeur = param.decoder(brute)
            correcte = bool(param.verifier(valeur))
        except (ValueError, TypeError, KeyError, AttributeError):
            correcte = False
        if correcte:
            decodees[nom] = valeur
        else:
            erreurs[nom] = param.message()

    if not erreurs:
        etat = {nom: decodees.get(nom, getattr(config, nom)) for nom in PARAMETRES_RANGS}
        if not _etat_coherent(*(etat[nom] for nom in PARAMETRES_RANGS)):
            for nom in PARAMETRES_RANGS:
                erreurs[nom] = ("les rangs doivent être les mêmes partout (noms, probabilités, "
                                "thèmes, lettres)")
    if not erreurs:
        noms = {n: decodees.get(n, getattr(config, n)) for n in ("NOM_DOUBLONS", "NOM_SANS_ILLUSTRATION", "NOM_ANIMEE")}
        if len({v.casefold() for v in noms.values()}) < len(noms):
            for n in noms:
                erreurs[n] = "les trois catégories automatiques doivent avoir des noms différents"
    if not erreurs:
        titre = decodees.get("TITRE_TAILLE", config.TITRE_TAILLE)
        bio = decodees.get("BIO_TAILLE", config.BIO_TAILLE)
        if bio >= titre:
            erreurs["BIO_TAILLE"] = "doit être plus petite que la taille du titre"
    if erreurs:
        raise ValeursInvalides(erreurs)
    return decodees


def ecrire_decodees(conn, decodees):
    """Enregistre et applique des valeurs déjà vérifiées par preparer()."""
    lignes = []
    for nom, valeur in decodees.items():
        ligne = base.lire_parametre_brut(conn, nom)
        defaut = ligne[1] if ligne else _json(getattr(config, nom))
        lignes.append((nom, _json(valeur), defaut))
    base.ecrire_parametres_bruts(conn, lignes)
    for nom, valeur in decodees.items():
        appliquer(nom, valeur)


def enregistrer_tout(conn, valeurs):
    """Enregistre plusieurs paramètres d'un coup, après avoir tout vérifié : si une seule valeur
    est refusée, rien n'est enregistré (ValeursInvalides). Applique ensuite les valeurs."""
    ecrire_decodees(conn, preparer(valeurs))


def reinitialiser(conn, noms=None):
    """Remet des paramètres (tous par défaut) aux valeurs de config.py. Renvoie leurs noms."""
    noms = list(noms) if noms is not None else list(PARAMETRES)
    lignes, decodees = [], {}
    for nom in noms:
        param = PARAMETRES.get(nom)
        ligne = base.lire_parametre_brut(conn, nom)
        if param is None or ligne is None or ligne[1] is None:
            continue
        try:
            valeur = param.decoder(json.loads(ligne[1]))
        except (ValueError, TypeError, KeyError):
            continue
        if param.verifier(valeur):
            decodees[nom] = valeur
            lignes.append((nom, ligne[1], ligne[1]))
    base.ecrire_parametres_bruts(conn, lignes)
    for nom, valeur in decodees.items():
        appliquer(nom, valeur)
    return list(decodees)


def ecrire(conn, cle, valeur):
    """Enregistre un paramètre ou une préférence (après vérification).
    Pour un paramètre de config.py, `valeur = None` revient à la valeur de config.py."""
    if cle in PARAMETRES:
        if valeur is None:
            reinitialiser(conn, [cle])
            return
        enregistrer_tout(conn, {cle: valeur})
    elif cle in PREFERENCES:
        if not PREFERENCES[cle](valeur):
            raise ValeurInvalide(f"valeur refusée pour {cle}")
        base.ecrire_parametre_brut(conn, cle, _json(valeur), None)
    else:
        raise ValeurInvalide(f"paramètre inconnu : {cle}")


def lire_preference(conn, cle, defaut=None):
    """Valeur enregistrée d'une préférence de la page, ou `defaut` (valeur absente ou abîmée)."""
    ligne = base.lire_parametre_brut(conn, cle)
    if ligne is None:
        return defaut
    try:
        valeur = json.loads(ligne[0])
    except ValueError:
        return defaut
    verifier = PREFERENCES.get(cle)
    return valeur if verifier is not None and verifier(valeur) else defaut


def valeurs_par_defaut(conn):
    """Valeurs de config.py (celles de départ) de chaque paramètre : {nom: valeur décodée}."""
    resultat = {}
    for nom, param in PARAMETRES.items():
        ligne = base.lire_parametre_brut(conn, nom)
        source = ligne[1] if ligne and ligne[1] is not None else _json(getattr(config, nom))
        try:
            resultat[nom] = param.decoder(json.loads(source))
        except (ValueError, TypeError, KeyError):
            resultat[nom] = getattr(config, nom)
    return resultat
