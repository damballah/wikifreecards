"""Recherche de cartes sur Wikipédia et rapatriement dans la collection.

Une recherche ne fait qu'UNE requête à l'API officielle de Wikipédia (qui renvoie aussi l'image,
la description, l'introduction et les vues de chaque résultat). Comme pour les paquets, les
requêtes sont espacées et identifiées (User-Agent avec le contact de config.CONTACT), et le
programme ralentit si Wikipédia le demande (voir api.py). Pour ne jamais « spammer » Wikipédia,
une seule recherche à la fois et au moins une seconde entre deux recherches.

Les cartes trouvées ne sont enregistrées que si on les « rapatrie » : elles sont alors classées
dans leur palier (d'après leurs vues) et dans les catégories dont une « meta » apparaît dans leur
description, exactement comme les cartes d'un paquet.
"""

import re
import threading
import time
import unicodedata
from datetime import datetime

import requests

from . import api, base, config, reserve, stats, terminal
from . import categories as cat

LONGUEUR_MAX = 100          # caractères de la recherche
TITRES_MAX = 100            # cartes rapatriées en une fois (chargées par lots de 20 : Wikipédia ne donne pas plus d'introductions par requête)
STATS_CARTES_RAPATRIEES = 12   # cartes dont les statistiques sont récupérées tout de suite au rapatriement (2 requêtes chacune)
DECALAGE_MAX = 1000         # on ne remonte pas plus loin dans les résultats de Wikipédia
INTERVALLE_MIN = 1.0        # secondes entre deux recherches

_VERROU = threading.Lock()
_derniere = 0.0


class RechercheInvalide(ValueError):
    """Le texte cherché ou la liste de titres est refusé."""


class RechercheTropRapide(Exception):
    """Une autre requête est en cours, ou la précédente est trop proche."""


class RechercheImpossible(Exception):
    """Wikipédia est injoignable ou limite le débit."""


def nettoyer_texte(texte):
    """Le texte cherché, sans espaces en trop (1 à 100 caractères, sans caractère de contrôle)."""
    if not isinstance(texte, str):
        raise RechercheInvalide("la recherche doit être un texte")
    texte = " ".join(texte.split())
    if not texte:
        raise RechercheInvalide("écris ce que tu cherches")
    if len(texte) > LONGUEUR_MAX:
        raise RechercheInvalide(f"la recherche fait {LONGUEUR_MAX} caractères au maximum")
    if any(unicodedata.category(c)[0] == "C" for c in texte):
        raise RechercheInvalide("la recherche contient un caractère invalide")
    return texte


def nettoyer_titres(titres):
    """La liste de titres à rapatrier : sans doublon, 1 à 20 titres valides."""
    if not isinstance(titres, list) or not titres:
        raise RechercheInvalide("aucune carte sélectionnée")
    propres = []
    for titre in titres:
        if (not isinstance(titre, str) or not 1 <= len(titre) <= 255 or "|" in titre
                or any(unicodedata.category(c)[0] == "C" for c in titre)):
            raise RechercheInvalide("titre invalide")
        if titre not in propres:
            propres.append(titre)
    if len(propres) > TITRES_MAX:
        raise RechercheInvalide(f"{TITRES_MAX} cartes au maximum à la fois")
    return propres


def _categories_prevues(article, categories):
    """Les catégories où la carte serait classée automatiquement (aperçu avant rapatriement)."""
    return [{"id": c["id"], "nom": c["nom"], "couleur": c["couleur"]} for c in categories
            if cat.metas_trouvees(article["description"], c["metas"], intro=article.get("intro"))]


def _norm(texte):
    """Sans accents, sans majuscules, ponctuation remplacée par des espaces : « Étoile-Polaire ! » -> « etoile polaire »."""
    t = cat.normaliser(str(texte or ""))
    return " ".join(re.sub(r"[^\w\s]", " ", t).replace("_", " ").split())


def score_pertinence(article, texte, rang_wikipedia=0):
    """Le score de PERTINENCE d'un résultat pour ce qui a été tapé (plus haut = plus pertinent). On part de l'ordre de Wikipédia
    (recherche en texte intégral), puis on récompense ce qu'un humain attend : le titre exact en premier, puis les titres qui commencent par
    la recherche, puis ceux qui contiennent tous les mots, puis les mots dans le sous-titre et l'introduction. Les pages d'homonymie et
    les listes passent après les vrais articles."""
    q = _norm(texte)
    mots = q.split()
    titre_brut = str(article.get("titre") or "")
    titre = _norm(titre_brut)
    sans_precision = _norm(re.sub(r"\s*\([^)]*\)\s*$", "", titre_brut))            # « Mercure (planète) » -> « mercure »
    mots_titre = set(titre.split())
    sous = _norm(article.get("description") if article.get("description") != "no-description" else "")
    intro = _norm(article.get("intro") if article.get("intro") != "no-intro" else "")
    mots_sous, mots_intro = set(sous.split()), set(intro.split())
    score = 0.0
    if not mots:
        return -float(rang_wikipedia)
    if q == titre:
        score += 120                                              # le titre EXACT d'abord
    elif q == sans_precision:
        score += 100                                              # « Mercure (planète) » pour « mercure »
    elif titre.startswith(q + " ") or sans_precision.startswith(q + " "):
        score += 70                                               # le titre commence par la recherche, mot entier
    elif titre.startswith(q) or sans_precision.startswith(q):
        score += 55                                               # le titre commence par ce qui est tapé (« par » -> « Paris »)
    elif all(m in mots_titre for m in mots):
        score += 48                                               # tous les mots sont dans le titre
    elif all(m in titre for m in mots):
        score += 34                                               # tous les mots sont dans le titre (début de mot compris)
    score += 12 * sum(1 for m in mots if m in mots_titre)
    score += 5 * sum(1 for m in mots if m not in mots_titre and m in titre)
    score += 6 * sum(1 for m in mots if m in mots_sous)
    score += 2 * sum(1 for m in mots if m in mots_intro)
    if len(mots) > 1:
        if q in sous:
            score += 8
        if q in intro:
            score += 4
    if "homonymie" in titre or "homonymie" in sous or sous.startswith("page d homonymie"):
        score -= 30 if q != sans_precision else 12                 # une page d'homonymie : après les vrais articles
    if titre.startswith(("liste de ", "liste des ", "list of ")):
        score -= 14
    score -= 0.8 * rang_wikipedia                                  # l'ordre de Wikipédia reste le départage
    return score


def classer_par_pertinence(articles, texte, decalage=0):
    """Range les résultats par pertinence décroissante et renumérote `pertinence` (la place dans la liste, à partir de `decalage`)."""
    notes = [(score_pertinence(a, texte, i), i, a) for i, a in enumerate(articles)]
    notes.sort(key=lambda n: (-n[0], n[1]))
    classes = [a for _, _, a in notes]
    for i, a in enumerate(classes):
        a["pertinence"] = max(0, int(decalage)) + i
    return classes


MASQUES = {"nombre": 0}          # résultats de la dernière recherche écartés par les champs choisis (lu par la route)


def champs_page():
    """Les champs de l'article où les mots doivent se trouver (cases « Page Recherche » de la Configuration) : titre, sous-titre
    (description courte), description (début de l'article). Aucune case cochée : le titre."""
    champs = [c for c, actif in (("titre", config.RECH_PAGE_TITRE), ("description", config.RECH_PAGE_SOUS_TITRE),
                                 ("intro", config.RECH_PAGE_DESCRIPTION)) if actif]
    return champs or ["titre"]


def _garder_champs(articles, texte):
    """Garde les résultats dont TOUS les mots de la recherche se trouvent dans les champs choisis (sans accents ni majuscules) ;
    compte les autres. Avec les trois champs cochés, Wikipédia a déjà décidé (recherche partout) : rien n'est écarté."""
    champs = champs_page()
    mots = base.mots_recherche(texte)
    if len(champs) >= 3 or not mots:
        MASQUES["nombre"] = 0
        return articles
    gardes = []
    for article in articles:
        contenu = cat.normaliser(" ".join(str(article.get(c) or "") for c in champs))
        if all(mot in contenu for mot in mots):
            gardes.append(article)
    MASQUES["nombre"] = len(articles) - len(gardes)
    return gardes


def chercher(texte, decalage=0):
    """Cherche sur Wikipédia. Renvoie la liste des cartes trouvées (dictionnaires prêts à afficher,
    avec `possede` : combien d'exemplaires sont déjà dans la collection, et `categories` : le
    classement automatique prévu). Rien n'est enregistré. `decalage` : résultats déjà affichés (« Voir plus de résultats »)."""
    global _derniere
    texte = nettoyer_texte(texte)
    if not isinstance(decalage, int) or isinstance(decalage, bool) or not 0 <= decalage <= DECALAGE_MAX:
        raise RechercheInvalide("position invalide dans les résultats")
    if not _VERROU.acquire(blocking=False):
        raise RechercheTropRapide("une recherche est déjà en cours")
    try:
        if time.monotonic() - _derniere < INTERVALLE_MIN:
            raise RechercheTropRapide("patiente une seconde entre deux recherches")
        try:
            with reserve.priorite_utilisateur():       # le pré-chargement patiente pendant ce temps
                articles = api.rechercher(texte, config.RECHERCHE_MAX_RESULTATS, decalage)
        except (requests.RequestException, KeyError, ValueError) as erreur:
            raise RechercheImpossible(f"Wikipédia est injoignable ({erreur}).") from erreur
        finally:
            _derniere = time.monotonic()
    finally:
        _VERROU.release()

    articles = _garder_champs(articles, texte)
    articles = classer_par_pertinence(articles, texte, decalage)
    with base.connexion_rapide() as conn:
        possedees = base.compter_par_url(conn, [a["url"] for a in articles])
        categories = ([c for c in base.lister_categories(conn) if any(c["metas"])]
                      if config.CATEGORIES_AUTO else [])
    for article in articles:
        article["id"] = None
        article["favori"] = False
        article["possede"] = possedees.get(article["url"], 0)
        article["categories"] = _categories_prevues(article, categories)
    return articles


def rapatrier(titres):
    """Enregistre dans la collection les cartes des articles choisis. Les données sont relues
    sur Wikipédia (on ne fait pas confiance à la page). Chaque carte reçoit son palier d'après
    ses vues, puis est classée automatiquement dans les catégories correspondantes.
    Renvoie {"importes": {titre: exemplaires dans la collection}, "introuvables": [titres],
    "total": cartes de la collection}."""
    titres = nettoyer_titres(titres)
    if not _VERROU.acquire(blocking=False):
        raise RechercheTropRapide("une autre opération avec Wikipédia est en cours")
    try:
        maintenant = datetime.now().astimezone().replace(microsecond=0)
        try:
            with reserve.priorite_utilisateur():
                # Aucune requête de statistiques ici : les langues, modifications et liens sont récupérés plus
                # tard, en arrière-plan (stats.reveiller), seulement pour les cartes qui entrent en collection.
                articles = api.recuperer_details([(titre, None, maintenant) for titre in titres],
                                                 avec_stats=False)
                if articles and config.STATS_CARTES and config.STATS_AVEC_PAQUET:
                    # Les modifications et liens entrants des premières cartes (STATS_CARTES_RAPATRIEES) arrivent AVEC elles,
                    # tout de suite et hors plafond horaire ; les suivantes sont complétées par le fil de fond.
                    with api.en_arriere_plan(config.STATS_PAUSE_PAQUET, None, pause_reseau=config.STATS_PAUSE_PAQUET):
                        api.completer_stats(articles[:STATS_CARTES_RAPATRIEES])
        except (requests.RequestException, KeyError, ValueError) as erreur:
            raise RechercheImpossible(f"Wikipédia est injoignable ({erreur}).") from erreur
    finally:
        _VERROU.release()

    trouves = {a["titre"] for a in articles}
    introuvables = [t for t in titres if t not in trouves]
    importes, total = {}, 0
    if articles:
        with base.connexion_rapide() as conn:
            identifiants = list(dict.fromkeys(base.ajouter_cartes(conn, articles)))
            stats.reveiller()
            if config.CATEGORIES_AUTO:
                base.classer_automatiquement(conn, identifiants)
            nouvelles = base.cartes_par_identifiants(conn, identifiants)
            possedees = base.compter_par_url(conn, [a["url"] for a in articles])
            total = base.compter(conn)
        for article in articles:
            importes[article["titre"]] = possedees.get(article["url"], 1)
        terminal.afficher_resume(nouvelles)
    else:
        with base.connexion_rapide() as conn:
            total = base.compter(conn)
    return {"importes": importes, "introuvables": introuvables, "total": total}
