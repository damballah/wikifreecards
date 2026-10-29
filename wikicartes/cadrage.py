"""Le CADRAGE de l'illustration d'une carte : sa position et sa taille dans le cadre de la carte.

Trois nombres décrivent le cadrage : `zoom` (1 = l'image remplit tout juste le cadre ; de 0,1 = réduite à 10 % jusqu'à 4 = quatre fois plus grande ; au-dessous
de 1, l'image est plus petite que le cadre et laisse voir le fond de la carte), `x` et `y` (0 à 100 : où l'image se place dans la marge qui reste, comme `object-position`
en CSS ; 50 / 25 = le cadrage d'origine, un peu vers le haut pour garder les visages) et `ratio` (largeur / hauteur de l'image : il permet à la carte de calculer toute seule
la taille exacte de l'image dans le cadre, sans rien charger). Un ancien cadrage sans `ratio` (zoom de 1 à 4 seulement) reste valable.

Le cadrage appartient à (l'article, le FICHIER d'image) et non à une carte précise : une carte de la même image de la même page, tirée de nouveau plus
tard (un doublon), reçoit donc automatiquement le même cadrage. Une carte créée à la main a son propre « article » (perso:...).
"""

import math
from urllib.parse import unquote, urlsplit

ZOOM_MIN = 0.1
ZOOM_MAX = 4.0
RATIO_MIN, RATIO_MAX = 0.05, 20.0
DEFAUT = (1.0, 50.0, 25.0)          # zoom, x, y d'origine (l'image se place comme avant l'existence du cadrage)
RATIO_CADRE = 300 / 196             # largeur / hauteur du cadre de l'illustration d'une carte (voir cartes.css : 300 u sur 196 u)


def cle_image(adresse):
    """Le nom du fichier d'une adresse d'image (sans le dossier de miniature ni le préfixe « 330px- »), en minuscules : reconnaît le même fichier sous
    l'adresse de l'original, d'une miniature ou du rendu PNG d'un dessin SVG. Chaîne vide si l'adresse n'a pas de nom."""
    import re
    morceaux = [m for m in unquote(urlsplit(str(adresse or "")).path).split("/") if m]
    if not morceaux:
        return ""
    nom = morceaux[-2] if "thumb" in morceaux and len(morceaux) >= 2 and re.match(r"^\d+px-", morceaux[-1]) else morceaux[-1]
    return nom.lower().replace(" ", "_")


def nom_fichier(adresse):
    """Le nom d'un fichier d'après son adresse Wikimedia, avec ses majuscules (« Lio_2013_4.jpg » -> « Lio 2013 4.jpg »), ou None."""
    import re
    morceaux = [m for m in unquote(urlsplit(str(adresse or "")).path).split("/") if m]
    if not morceaux:
        return None
    nom = morceaux[-2] if "thumb" in morceaux and len(morceaux) >= 2 and re.match(r"^(lossy-|lossless-)?(page\d+-)?\d+px-", morceaux[-1]) else morceaux[-1]
    return nom.replace("_", " ") or None


def _nombre(v, mini, maxi, nom):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{nom} invalide")
    if not mini - 1e-9 <= v <= maxi + 1e-9:
        raise ValueError(f"{nom} hors limites ({mini} à {maxi})")
    return min(max(float(v), mini), maxi)


def valider(zoom, x, y, ratio=None):
    """(zoom, x, y, ratio) arrondis, ou ValueError : des nombres finis (pas de booléen), zoom de 0,1 à 4, x et y de 0 à 100, ratio de 0,05 à 20 (ou None : ancien cadrage,
    qui exige alors un zoom d'au moins 1)."""
    zoom = round(_nombre(zoom, ZOOM_MIN, ZOOM_MAX, "zoom"), 3)
    x = round(_nombre(x, 0.0, 100.0, "x"), 3)
    y = round(_nombre(y, 0.0, 100.0, "y"), 3)
    if ratio is None:
        if zoom < 1:
            raise ValueError("une image plus petite que le cadre demande son ratio")
        return zoom, x, y, None
    return zoom, x, y, round(_nombre(ratio, RATIO_MIN, RATIO_MAX, "ratio"), 4)


def est_defaut(zoom, x, y):
    return abs(zoom - DEFAUT[0]) < 0.005 and abs(x - DEFAUT[1]) < 0.05 and abs(y - DEFAUT[2]) < 0.05


def propre(cadrage):
    """Un cadrage reçu d'ailleurs (dictionnaire {zoom, x, y, ratio}) -> dictionnaire sûr, ou None s'il est abîmé ou s'il est le cadrage d'origine."""
    if not isinstance(cadrage, dict):
        return None
    try:
        zoom, x, y, ratio = valider(cadrage.get("zoom"), cadrage.get("x"), cadrage.get("y"), cadrage.get("ratio"))
    except ValueError:
        return None
    if est_defaut(zoom, x, y):
        return None
    resultat = {"zoom": zoom, "x": x, "y": y}
    if ratio is not None:
        resultat["ratio"] = ratio
    return resultat


def attributs(cadrage):
    """Les attributs de l'image de la carte (variables CSS), ou "" pour le cadrage d'origine. Avec un `ratio`, la carte calcule elle-même la taille et la place
    de l'image (data-cadre) ; sans, l'ancien réglage (zoom de 1 à 4) s'applique."""
    c = propre(cadrage)
    if c is None:
        return ""
    if "ratio" in c:
        return f' data-cadre="1" style="--cz:{c["zoom"]:g};--cx:{c["x"]:g};--cy:{c["y"]:g};--cr:{c["ratio"]:g}"'
    return f' style="--zi:{c["zoom"]:g};--xi:{c["x"]:g}%;--yi:{c["y"]:g}%"'


def style(cadrage):
    """(ancien nom) voir `attributs`."""
    return attributs(cadrage)
