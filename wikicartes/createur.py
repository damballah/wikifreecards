"""Créateur de cartes : des cartes que tu fabriques toi-même (saisie manuelle, ou depuis une page web).

Une carte personnalisée est UNIQUE : elle porte son propre style (motif, trois couleurs, reflet,
lettres et nom du palier), enregistré avec elle ; elle ne dépend d'aucun rang de la Configuration et
ne peut pas être tirée au hasard. Elle ne représente pas un article de Wikipédia : son pied ne montre
que son surnom (à gauche) et la date et l'heure de sa validation (à droite).
"""

import unicodedata
import uuid
from datetime import datetime

from . import base, cadrage, config, images, profil, theme, web

TITRE_MAX = 80
SOUS_TITRE_MAX = 120
SURNOM_MAX = 30
CHAMPS = {"titre", "sous_titre", "description", "surnom", "theme_rang", "image", "source", "cadrage"}


def style_de_base():
    """Le style du palier « Personnalisée » tel qu'il est réglé dans la Configuration (PERSO_THEME,
    PERSO_SYMBOLE, PERSO_NOM) : motif, trois couleurs, reflet, lettres et nom. Repli : les valeurs d'origine."""
    return theme.style_perso({**config.PERSO_THEME, "symbole": config.PERSO_SYMBOLE,
                              "palier": config.PERSO_NOM})


def limite_description():
    """Nombre de caractères permis dans la description : environ ce qu'une introduction de
    NB_PHRASES phrases (réglage de la Configuration) occupe sur une carte standard."""
    return max(250, min(1500, int(config.NB_PHRASES) * 250))


def _texte_sain(texte):
    """Pas de caractère de contrôle, de direction du texte, privé ou inconnu (sauf le liant des emoji)."""
    return all(c == "\u200d" or unicodedata.category(c)[0] != "C" for c in texte)


def nettoyer(valeur, maxi, nom, obligatoire=False):
    """(texte nettoyé, erreur) : espaces réduits, longueur et caractères contrôlés."""
    if valeur is None:
        valeur = ""
    if not isinstance(valeur, str):
        return None, f"{nom} : du texte est attendu"
    texte = " ".join(web.normaliser_caracteres(valeur).split())     # espaces spéciaux, caractères invisibles
    if obligatoire and not texte:
        return None, f"{nom} : obligatoire"
    if len(texte) > maxi:
        return None, f"{nom} : trop long ({len(texte)} caractères, {maxi} au maximum)"
    if not _texte_sain(texte):
        return None, f"{nom} : contient un caractère invisible ou de contrôle"
    return texte, ""


def valider(donnees, strict=True):
    """Vérifie les champs d'une carte à créer. Renvoie (carte, erreurs) : `carte` est un dictionnaire
    propre (jamais de valeur douteuse), `erreurs` une liste de messages. En mode non strict (aperçu
    pendant la saisie), un champ invalide est simplement remplacé par sa valeur de départ et le titre
    n'est pas obligatoire."""
    erreurs = []
    if not isinstance(donnees, dict) or not set(donnees) <= CHAMPS:
        return None, ["demande invalide"]

    def champ(cle, maxi, nom, obligatoire=False):
        texte, erreur = nettoyer(donnees.get(cle), maxi, nom, obligatoire and strict)
        if erreur:
            erreurs.append(erreur)
            return ""
        return texte

    titre = champ("titre", TITRE_MAX, "titre", True)
    sous_titre = champ("sous_titre", SOUS_TITRE_MAX, "sous-titre")
    description = champ("description", limite_description(), "description")
    surnom = champ("surnom", SURNOM_MAX, "surnom")

    # Le thème (couleurs, motif, reflet), les lettres et le nom du palier viennent TOUS de la Configuration :
    # soit le palier « Personnalisée » (le thème de base des cartes créées), soit un des autres rangs. On
    # les recopie sur la carte au moment de la création : elle reste unique et ne change plus ensuite.
    code = donnees.get("theme_rang") or ""
    if code in ("", config.CODE_PERSO):
        base_perso = style_de_base()
        motif, couleurs, reflet = base_perso["motif"], base_perso["couleurs"], base_perso["reflet"]
        symbole, palier = base_perso["symbole"], base_perso["palier"]
    elif isinstance(code, str) and code in config.CODES:
        rang = theme.theme_du_rang(config.THEMES_PALIERS, code)
        motif, couleurs, reflet = rang["motif"], list(rang["couleurs"]), rang["reflet"]
        symbole = config.symbole(code)[:theme.SYMBOLE_PERSO_MAX]
        palier = config.nom_rang(code)[:theme.PALIER_PERSO_MAX]
    else:
        erreurs.append("palier inconnu")
        base_perso = style_de_base()
        motif, couleurs, reflet = base_perso["motif"], base_perso["couleurs"], base_perso["reflet"]
        symbole, palier = base_perso["symbole"], base_perso["palier"]

    image = donnees.get("image")
    if image in (None, ""):
        image = None
    elif not images.adresse_locale_valide(image):
        erreurs.append("image : fichier introuvable (téléverse-la à nouveau)")
        image = None
    source = donnees.get("source")
    if source in (None, ""):
        source = None
    elif web.url_http(source) is None:
        erreurs.append("adresse source invalide")
        source = None
    else:
        source = web.url_http(source)

    # Le cadrage de l'illustration (position et taille réglées dans l'aperçu) : {zoom, x, y, ratio}, seulement s'il y a une image ; le cadrage d'origine n'est pas gardé.
    cadrage_carte = None
    brut = donnees.get("cadrage")
    if brut is not None:
        if not isinstance(brut, dict) or not set(brut) <= {"zoom", "x", "y", "ratio"}:
            erreurs.append("cadrage de l'image invalide")
        else:
            try:
                zoom, x, y, ratio = cadrage.valider(brut.get("zoom"), brut.get("x"), brut.get("y"), brut.get("ratio"))
                if ratio is None:
                    raise ValueError("ratio manquant")
                if not cadrage.est_defaut(zoom, x, y) and image is not None:
                    cadrage_carte = {"zoom": zoom, "x": x, "y": y, "ratio": ratio}
            except ValueError:
                erreurs.append("cadrage de l'image invalide")
    carte = {"titre": titre, "sous_titre": sous_titre, "description": description, "surnom": surnom,
             "image": image, "source": source, "cadrage": cadrage_carte,
             "style": {"motif": motif, "couleurs": [c.lower() for c in couleurs], "reflet": reflet,
                       "symbole": symbole, "palier": palier}}
    if not strict:
        return carte, []
    return (carte if not erreurs else None), erreurs


def article_pour_affichage(carte, tire_le=None, identifiant=None):
    """La carte (validée) au format des articles affichés : sert à l'aperçu et à l'enregistrement."""
    style = carte["style"]
    return {
        "id": identifiant, "titre": carte["titre"] or "Titre de la carte",
        "description": carte["sous_titre"] or "no-description", "intro": carte["description"] or "no-intro",
        "rarete": config.CODE_PERSO, "rarete_nom": style["palier"], "rarete_tiree": config.CODE_PERSO,
        "tire_le": tire_le or datetime.now().astimezone(), "vues_moyenne": 0, "vues_total": 0,
        "url": carte["source"] or "perso:apercu", "image": carte["image"] or "no-image",
        "miniature": carte["image"] or "no-image", "cadrage": carte.get("cadrage"), "qr_svg": "", "langue": config.LANGUE,
        "favori": False, "categories": [], "personnalisee": True, "surnom": carte["surnom"],
        "style": style, "nb_langues": None, "taille_octets": None, "nb_revisions": None,
        "revisions_plafonnees": False, "nb_liens_entrants": None, "supprime_le": None,
    }


def creer(conn, carte):
    """Valide la carte en l'ajoutant à la collection comme toutes les autres. La date et l'heure sont
    celles de la validation. Renvoie l'identifiant de la nouvelle carte."""
    article = article_pour_affichage(carte)
    article["url"] = carte["source"] or f"perso:{uuid.uuid4().hex}"
    identifiants = base.ajouter_cartes(conn, [article])
    c = carte.get("cadrage")
    if c and carte["image"]:                                    # la position et la taille de l'illustration réglées dans l'aperçu
        base.cadrage_ecrire_carte(conn, identifiants[0], article["url"], cadrage.cle_image(carte["image"]), c["zoom"], c["x"], c["y"], c["ratio"])
    if config.CATEGORIES_AUTO:
        base.classer_automatiquement(conn, identifiants)       # les catégories à mots-clés s'appliquent aussi
    return identifiants[0]
