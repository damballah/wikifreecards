"""Catégories de cartes : noms, « meta » de classement automatique, bandeaux sur les cartes.

Une catégorie a un nom (40 caractères maximum), une couleur de fond et jusqu'à 5 « meta » :
des mots ou expressions cherchés dans la courte description d'une carte (celle sous le titre) ET,
par défaut, dans les phrases de son introduction (réglage META_DANS_INTRO).
Quand un paquet est ouvert, une carte dont la description ou l'introduction contient une meta est classée
automatiquement dans la catégorie correspondante.
"""

import html
import re
import unicodedata

from . import config, theme

NB_METAS = 5
LONGUEUR_NOM_MAX = 40
LONGUEUR_META_MAX = 40
NB_CATEGORIES_MAX = 60


def normaliser(texte):
    """Minuscules, sans accents, espaces simplifiés : « Footballeur  Français » -> « footballeur
    francais ». Sert à comparer les noms et à chercher les meta."""
    decompose = unicodedata.normalize("NFKD", str(texte).casefold())
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sans_accents).strip()


def tronquer(nom, maximum):
    """Coupe un nom trop long pour tenir sur la carte : « Footballeurs français » (14) ->
    « Footballeurs… ». Le résultat ne dépasse jamais `maximum` caractères, points compris."""
    lettres = list(nom)
    if len(lettres) <= maximum:
        return nom
    return "".join(lettres[:max(1, maximum - 1)]).rstrip() + "…"


def _propre(texte):
    """Texte sans caractère de contrôle (retours à la ligne, tabulations...)."""
    return isinstance(texte, str) and not any(unicodedata.category(c)[0] == "C" for c in texte)


# ------------------------------------------------------------------ vérification

def verifier_categories(demandees, existantes, supprimees=()):
    """Vérifie une liste de catégories envoyée par la page Configuration.

    `demandees` : [{"id": int ou None, "nom", "couleur", "metas": [..]}] ;
    `existantes` : {id: catégorie} déjà en base ; `supprimees` : ids à supprimer.
    Renvoie (propres, erreurs) : `propres` est la liste nettoyée (couleur en minuscules, 5 meta) ;
    `erreurs` : {position dans la liste: {champ: explication}}, vide si tout est valide."""
    erreurs, propres = {}, []

    def erreur(i, champ, texte):
        erreurs.setdefault(i, {})[champ] = texte

    if not isinstance(demandees, list):
        return [], {0: {"nom": "liste de catégories invalide"}}
    if not isinstance(supprimees, (list, tuple)) or any(
            not isinstance(i, int) or isinstance(i, bool) for i in supprimees):
        return [], {0: {"nom": "liste de suppressions invalide"}}
    touchees = {c.get("id") for c in demandees if isinstance(c, dict)}
    restantes = [i for i in existantes if i not in supprimees and i not in touchees]
    if len(restantes) + len(demandees) > NB_CATEGORIES_MAX:
        return [], {0: {"nom": f"{NB_CATEGORIES_MAX} catégories au maximum"}}

    cles_utilisees = {existantes[i]["cle"]: i for i in restantes}
    for i, c in enumerate(demandees):
        if not isinstance(c, dict):
            erreur(i, "nom", "catégorie invalide")
            continue
        identifiant = c.get("id")
        if identifiant is not None and (not isinstance(identifiant, int)
                                        or isinstance(identifiant, bool)
                                        or identifiant not in existantes
                                        or identifiant in supprimees):
            erreur(i, "nom", "catégorie inconnue (elle a peut-être été supprimée)")
            continue

        nom = c.get("nom")
        nom = nom.strip() if isinstance(nom, str) else None
        if not nom or len(nom) > LONGUEUR_NOM_MAX or not _propre(nom):
            erreur(i, "nom", f"un nom de 1 à {LONGUEUR_NOM_MAX} caractères est nécessaire")
        else:
            cle = normaliser(nom)
            if cle in cles_utilisees:
                erreur(i, "nom", "une autre catégorie porte déjà ce nom")
            cles_utilisees[cle] = identifiant

        couleur = c.get("couleur")
        if not theme.couleur_valide(couleur):
            erreur(i, "couleur", "couleur invalide (format #rrggbb)")

        metas = c.get("metas", [])
        if not isinstance(metas, list) or len(metas) > NB_METAS:
            erreur(i, "metas", f"{NB_METAS} meta au maximum")
            metas = []
        propres_metas = []
        for meta in metas:
            meta = meta.strip() if isinstance(meta, str) else None
            if meta is None or len(meta) > LONGUEUR_META_MAX or not _propre(meta):
                erreur(i, "metas", f"chaque meta fait {LONGUEUR_META_MAX} caractères au maximum")
                break
            propres_metas.append(meta)
        propres_metas += [""] * (NB_METAS - len(propres_metas))

        if i not in erreurs:
            propres.append({"id": identifiant, "nom": nom, "cle": normaliser(nom),
                            "couleur": couleur.lower(), "metas": propres_metas})
    return ([] if erreurs else propres), erreurs


# --------------------------------------------------------------- classement auto

def metas_trouvees(description, metas, mot_entier=None, intro=None):
    """Dit si une des meta apparaît dans la description de la carte (la ligne sous le titre) ou, si le
    réglage META_DANS_INTRO est actif, dans les phrases de son introduction (`intro`) — sans tenir
    compte des majuscules ni des accents. Chaque texte est examiné séparément (une meta ne peut pas
    « enjamber » la fin de l'un et le début de l'autre). `mot_entier` : la meta doit être un mot (ou
    une expression) entier."""
    if mot_entier is None:
        mot_entier = config.META_MOT_ENTIER
    textes = [normaliser(description or "")]
    if intro and config.META_DANS_INTRO:
        textes.append(normaliser(intro))
    cherches = [c for c in (normaliser(meta) for meta in metas) if c]
    for texte in textes:
        if not texte:
            continue
        for cherche in cherches:
            if mot_entier:
                if re.search(r"(?<!\w)" + re.escape(cherche) + r"(?!\w)", texte):
                    return True
            elif cherche in texte:
                return True
    return False


# ---------------------------------------------------------------- bandeaux (HTML)

def html_bandeaux(categories, longueur_max=None, max_affichees=None):
    """Les petits bandeaux de catégorie d'une carte (HTML). Le nom est coupé après
    `longueur_max` caractères ; au-delà de `max_affichees` bandeaux, un « +N » les résume."""
    if not categories:
        return ""
    longueur_max = config.CATEGORIE_LONGUEUR_MAX if longueur_max is None else longueur_max
    max_affichees = config.CATEGORIES_MAX_SUR_CARTE if max_affichees is None else max_affichees
    visibles, cachees = categories[:max_affichees], categories[max_affichees:]
    morceaux = []
    for c in visibles:
        texte = theme.couleur_lisible(theme.luminance(c["couleur"]))
        morceaux.append(
            f'<span class="carte__categorie" style="background: {c["couleur"]}; color: {texte}" '
            f'title="{html.escape(c.get("info") or c["nom"], quote=True)}">'
            f'{html.escape(tronquer(c["nom"], max(longueur_max, 20) if c.get("automatique") else longueur_max))}'
            f'</span>')          # les bandeaux automatiques (« Doublon ×2 », « Sans illustration ») ne sont pas coupés
    if cachees:
        noms = ", ".join(c["nom"] for c in cachees)
        morceaux.append(f'<span class="carte__categorie carte__categorie--plus" '
                        f'title="{html.escape(noms, quote=True)}">+{len(cachees)}</span>')
    return "".join(morceaux)
