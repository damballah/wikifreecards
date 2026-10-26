"""Le booster : le sachet cliquable qui ouvre un paquet de cartes.

Il n'affiche que le logo du jeu (ou, sans logo, un mot ou une phrase au choix). Son apparence
(10 styles) et son animation d'ouverture (10 animations) se règlent dans la page Configuration.
Les dessins et mouvements sont dans static/cartes.css ; ce module donne leurs noms et leurs durées.
Les animations sont courtes et légères : elles ne déplacent que des éléments (transform) et
changent leur transparence (opacity), ce que le navigateur fait sans effort.
"""

import json

THEMES = {
    "classique": "Classique (violet)",
    "or": "Or",
    "nuit": "Nuit étoilée",
    "holo": "Holographique",
    "braise": "Braise",
    "ocean": "Océan",
    "foret": "Forêt",
    "bonbon": "Bonbon",
    "carbone": "Carbone",
    "cosmos": "Cosmos",
}

# Durées en millisecondes (elles doivent correspondre aux animations de cartes.css) :
# - attente : l'animation tourne pendant que le serveur tire les cartes (au moins ce temps) ;
# - sortie  : le booster s'ouvre et disparaît ; les cartes apparaissent ensuite.
# Paquet PERSONNALISÉ (image téléversée) : formes, ajustement, et ce qu'on place dessus.
FORMES = {"image": "Les proportions de l'image (elle s'adapte)", "vertical": "Rectangle vertical", "carre": "Carré",
          "horizontal": "Rectangle horizontal", "rond": "Rond"}
AJUSTEMENTS = {"recadrer": "Recadrer (l'image remplit la forme)", "entier": "Image entière (rien n'est coupé)"}
CONTENUS = {"rien": "Rien (juste l'image)", "logo": "Le logo du jeu", "texte": "Le texte du booster"}
THEME_IMAGE = "image"                       # valeur de BOOSTER_THEME qui choisit l'image personnalisée


def choix_styles():
    """Les choix du réglage « Style du booster » : les 10 styles prêts à l'emploi + l'image personnalisée."""
    return {**THEMES, THEME_IMAGE: "Image personnalisée (à téléverser ci-dessous)"}


ANIMATIONS = {
    "secousse": {"libelle": "Secousse", "attente": 450, "sortie": 300},
    "flash": {"libelle": "Flash lumineux", "attente": 250, "sortie": 350},
    "rotation": {"libelle": "Rotation", "attente": 150, "sortie": 500},
    "envol": {"libelle": "Envol", "attente": 250, "sortie": 450},
    "dissolution": {"libelle": "Dissolution", "attente": 300, "sortie": 400},
    "rebond": {"libelle": "Rebond", "attente": 400, "sortie": 400},
    "tourbillon": {"libelle": "Tourbillon", "attente": 300, "sortie": 500},
    "explosion": {"libelle": "Explosion", "attente": 450, "sortie": 350},
    "chute": {"libelle": "Chute", "attente": 250, "sortie": 450},
    "battement": {"libelle": "Battement de cœur", "attente": 600, "sortie": 400},
    "aucune": {"libelle": "Aucune (instantané)", "attente": 0, "sortie": 0},
}

DUREE_RETOUR = 350      # le booster revient en fondu, prêt pour un nouveau paquet


def choix_animations():
    """{code: libellé} pour la liste déroulante de la page Configuration."""
    return {code: info["libelle"] for code, info in ANIMATIONS.items()}


def json_animations():
    """Les durées de chaque animation, pour le JavaScript des pages (JSON compact)."""
    return json.dumps({code: {"attente": info["attente"], "sortie": info["sortie"],
                              "retour": DUREE_RETOUR if info["sortie"] else 0}
                              for code, info in ANIMATIONS.items()},
                      separators=(",", ":"))


def classe_texte(texte):
    """Taille du texte du booster selon sa longueur (pour qu'une phrase tienne sur le sachet)."""
    longueur = len(texte)
    if longueur <= 8:
        return "booster__texte--xl"
    if longueur <= 16:
        return "booster__texte--l"
    if longueur <= 28:
        return "booster__texte--m"
    return "booster__texte--s"


# ------------------------------------------------------------------------------------------------ confettis et paillettes
# Au moment où le paquet disparaît ou explose, quelques confettis, étincelles, grains de poussière ou cœurs jaillissent, selon
# l'animation (voir cartes.css, section 33) : une explosion fait une grande gerbe de confettis, une rotation ou un tourbillon
# des étincelles qui spiralent, un envol une traînée qui retombe, une chute un nuage de poussière au sol, un battement de cœur
# des petits cœurs... Les particules sont fabriquées une fois pour toutes avec des valeurs fixes (pas de hasard à l'affichage).
DUREE_CONFETTIS = 1700            # ms : la couche reste « active » ce temps-là après la disparition du paquet
_COULEURS_CONFETTIS = ("#ffd24a", "#ff5c8a", "#4ad8ff", "#7cff6b", "#b07bff", "#ff9a3c", "#ffffff")
_COULEURS_ETINCELLES = ("#ffffff", "#fff3b0", "#ffe08a", "#cfeaff")
_COULEURS_POUSSIERE = ("#ffffff", "#e8e8f0", "#d6d6e4")
_COULEURS_COEURS = ("#ff4d6d", "#ff7096", "#ff8fab", "#e63950")


def _particules():
    import math
    import random
    hasard = random.Random(2026)
    elements = []
    for genre, nombre, couleurs, distance, taille, sous_ensemble in (
            ("c", 18, _COULEURS_CONFETTIS, (70, 170), (7, 12), 6), ("e", 14, _COULEURS_ETINCELLES, (50, 150), (11, 22), 6),
            ("p", 12, _COULEURS_POUSSIERE, (40, 130), (3, 7), 6), ("h", 10, _COULEURS_COEURS, (40, 120), (16, 28), 0)):
        for i in range(nombre):
            angle = hasard.uniform(0, 360)
            rayon = hasard.uniform(*distance)
            dx, dy = rayon * math.cos(math.radians(angle)), rayon * math.sin(math.radians(angle))
            classes = genre + (" a" if i < sous_ensemble else "")
            elements.append(
                f'<i class="{classes}" style="--dx:{dx:.0f};--dy:{dy:.0f};--ay:{abs(dy):.0f};--a:{angle:.0f};--rad:{rayon:.0f};'
                f'--s:{hasard.uniform(*taille):.0f};--t:{hasard.randrange(0, 90)};--r:{hasard.randrange(-540, 540)};'
                f'--c:{hasard.choice(couleurs)}"></i>')
    return '<span class="paquet__particules" aria-hidden="true">' + "".join(elements) + "</span>"


PARTICULES_HTML = _particules()
