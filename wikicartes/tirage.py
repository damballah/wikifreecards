"""Tirage pondéré par rareté : on tire d'abord le rang, puis l'article."""

import random
import threading
import time
from datetime import datetime

import requests

from . import api, config
from .rarete import classer


def estimer_requetes(nombre):
    """Nombre de requêtes à Wikipédia que l'ouverture d'un paquet de `nombre` cartes va
    probablement demander (sert au décompte) : le top des plus vus (seulement s'il n'est pas déjà
    en mémoire), un lot aléatoire si l'une des cartes risque d'être d'un rang modeste (probabilité
    d'au moins 50 %, d'après les POIDS), et la requête qui récupère les détails des articles.
    L'estimation est corrigée en direct pendant le tirage (voir tirer_titres)."""
    modestes = sum(config.POIDS[c] for c in config.CODES if config.SEUILS[c] <= config.SEUIL_TOP_UNIQUEMENT)
    total = sum(config.POIDS[c] for c in config.CODES) or 1
    proba = 1 - (1 - modestes / total) ** max(1, int(nombre))
    # + les détails des articles, + les langues si les statistiques sont affichées
    return ((0 if api.top_en_cache() else 1) + (1 if proba >= 0.5 else 0) + 1
            + (1 if config.STATS_CARTES else 0))


# Les candidats des rangs modestes, tirés d'avance : chaque lot aléatoire de Wikipédia donne 50 articles (avec leurs vues) dont un paquet n'utilise que quelques-uns. Les autres restent ici
# (en mémoire, le temps de la session) pour les paquets suivants, qui n'ont alors AUCUNE requête de tirage à faire. Un petit fil les renouvelle en arrière-plan (remplir_pool_en_fond).
_POOL = {"signature": None, "codes": {}}
_VERROU_POOL = threading.Lock()
POOL_MAX_PAR_RANG = 80
POOL_CIBLE = 30                         # en dessous, le fil d'arrière-plan va chercher un lot de plus
_pool_en_cours = threading.Event()


def pool():
    """Les candidats déjà tirés, par rang : {code: [titres]} (vidé si les seuils de rareté ont changé depuis : leurs rangs seraient faux)."""
    signature = tuple((str(p[0]), float(p[1])) for p in config.PALIERS)
    with _VERROU_POOL:
        if _POOL["signature"] != signature:
            _POOL["signature"], _POOL["codes"] = signature, {}
        for code in config.CODES:
            _POOL["codes"].setdefault(code, [])
        return _POOL["codes"]


def reinitialiser_pool():
    with _VERROU_POOL:
        _POOL["signature"], _POOL["codes"] = None, {}


def _taille_pool_modeste():
    candidats = pool()
    return sum(len(candidats[code]) for code in config.CODES if config.SEUILS[code] <= config.SEUIL_TOP_UNIQUEMENT)


def remplir_pool_en_fond(delai=0.0):
    """En arrière-plan et poliment (une requête, à la cadence douce de la réserve) : ajoute un lot de candidats si le stock est bas. Sans effet pendant une importation en lot ou si le stock
    suffit ; toute erreur est ignorée."""
    if _pool_en_cours.is_set():
        return

    def travail():
        try:
            time.sleep(delai)
            if _taille_pool_modeste() >= POOL_CIBLE:
                return
            with api.en_arriere_plan(config.RESERVE_PAUSE, None):
                candidats = pool()
                for titre, moyenne in api.lot_aleatoire():
                    liste = candidats[classer(moyenne)[0]]
                    if len(liste) < POOL_MAX_PAR_RANG and titre not in liste:
                        liste.append(titre)
        except Exception:
            pass
        finally:
            _pool_en_cours.clear()
    _pool_en_cours.set()
    threading.Thread(target=travail, name="candidats-paquet", daemon=True).start()


def preparer(nombre, forcer=None):
    """AVANT le décompte d'un paquet tiré en direct : charge le top des plus vus (mis en mémoire), tire d'avance le rang de chaque carte, et en déduit ce qu'il faut prévoir : les
    lots aléatoires à demander (un seul, en pratique, quand un rang modeste n'est pas assuré par le top). Renvoie {"codes": [rang de chaque carte], "lots": nombre de lots}. Le décompte
    peut ainsi annoncer une durée COMPLÈTE dès le départ (voir paquet.Annonceur.promettre) au lieu de la corriger à chaque requête."""
    try:
        top = api.charger_top_articles()
    except (requests.RequestException, KeyError, IndexError, ValueError):
        top = []
    codes = config.CODES
    poids = [config.POIDS[code] for code in codes]
    tires = [forcer if forcer in codes else random.choices(codes, weights=poids)[0] for _ in range(max(0, int(nombre)))]
    disponibles, besoins = {}, {}
    for _, moyenne in top:
        code = classer(moyenne)[0]
        disponibles[code] = disponibles.get(code, 0) + 1
    for code, liste in pool().items():                        # (les candidats déjà tirés d'avance comptent aussi)
        disponibles[code] = disponibles.get(code, 0) + len(liste)
    for code in tires:
        besoins[code] = besoins.get(code, 0) + 1
    lots = 0
    if forcer not in codes:                                   # (un tirage forcé, GOD PACK, ne passe que par le top)
        for code, voulus in besoins.items():
            if config.SEUILS[code] <= config.SEUIL_TOP_UNIQUEMENT and voulus > disponibles.get(code, 0):
                lots = 1                                      # un rang modeste qu'on n'a pas en réserve : un lot aléatoire (un suffit presque toujours)
                break
    return {"codes": tires, "lots": lots}


def requetes_finales():
    """Requêtes qui terminent un tirage : les détails des articles, et les langues."""
    return 1 + (1 if config.STATS_CARTES else 0)


def remplir_reserve(reserve, code, annonceur=None):
    """Tire des lots au hasard et les range par rang, jusqu'à en trouver un
    du rang voulu (ou jusqu'à MAX_LOTS requêtes). Renvoie True si trouvé."""
    for _ in range(config.MAX_LOTS):
        if annonceur is not None:
            annonceur.etape(1 + requetes_finales())       # ce lot, puis les détails (+ les langues)
        for titre, moyenne in api.lot_aleatoire():
            reserve[classer(moyenne)[0]].append(titre)
        for liste in reserve.values():                    # (le stock de candidats reste borné)
            del liste[:max(0, len(liste) - POOL_MAX_PAR_RANG)]
        if reserve[code]:
            return True
    return False


def piocher(code, top_par_rang, reserve, deja_pris, epuises, annonceur=None):
    """Renvoie un titre du rang demandé, ou None si on n'en trouve pas."""
    # 1) D'abord le top des plus consultés (indispensable pour L, UR, SR)
    liste = top_par_rang[code]
    while liste:
        titre = liste.pop(random.randrange(len(liste)))
        if titre not in deja_pris:
            return titre
    # 2) Sinon tirage aléatoire classique filtré par rang (rangs modestes)
    if config.SEUILS[code] > config.SEUIL_TOP_UNIQUEMENT or code in epuises:
        return None
    if not reserve[code]:
        try:
            trouve = remplir_reserve(reserve, code, annonceur)
        except requests.RequestException as erreur:
            print(f"  (Recherche aléatoire interrompue : {erreur})")
            epuises.update(config.CODES)   # on arrête de solliciter Wikipedia
            return None
        if not trouve:
            epuises.add(code)              # inutile de réessayer ce rang
            return None
    while reserve[code]:
        titre = reserve[code].pop()
        if titre not in deja_pris:
            return titre
    return None


def tirer_godpack(nombre, annonceur=None):
    """Les candidats d'un GOD PACK : les articles les PLUS consultés (le top du mois dernier). Sont d'abord proposés, dans le désordre, ceux que
    le top range déjà parmi les légendaires, puis les suivants, du plus vu au moins vu. On en tire 3 fois plus que de cartes : le rang d'une
    carte vient de ses vues des derniers jours, qui diffèrent parfois de la moyenne du mois, donc il faut pouvoir choisir (voir
    paquet.composer_godpack). [(titre, rang, horodatage)] ; vide si le top est indisponible."""
    try:
        top = api.charger_top_articles()
        if annonceur is not None:
            annonceur.etape(estimer_requetes(nombre))
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return []
    legendaire = config.CODES[0]
    classes = [titre for titre, moyenne in top if classer(moyenne)[0] == legendaire]
    autres = [titre for titre, moyenne in top if classer(moyenne)[0] != legendaire]          # (déjà du plus vu au moins vu)
    random.shuffle(classes)
    maintenant = datetime.now().astimezone()
    return [(titre, legendaire, maintenant) for titre in (classes + autres)[:max(3 * nombre, nombre + 8)]]


def tirer_titres(nombre, annonceur=None, exclus=(), forcer=None, codes_tires=None):
    """Tire le rang de chaque article selon POIDS, puis l'article correspondant.
    Renvoie [(titre, rang_tiré, horodatage du tirage)]. `annonceur` : prévient la page de ce qui
    reste à faire (voir paquet.Annonceur), pour le décompte ; `exclus` : titres à éviter ; `forcer` : un code de rang (« L ») : toutes
    les cartes sont tirées dans ce rang (GOD PACK), sans descendre d'un rang si on n'en trouve pas."""
    try:
        top = api.charger_top_articles()
        if annonceur is not None:                        # le top est chargé : on recalcule le reste
            annonceur.etape(estimer_requetes(nombre))
    except (requests.RequestException, KeyError, IndexError, ValueError):
        print("(Top des articles les plus vus indisponible : "
              "les rangs élevés seront introuvables.)")
        top = []

    codes = config.CODES
    top_par_rang = {code: [] for code in codes}
    for titre, moyenne in top:
        top_par_rang[classer(moyenne)[0]].append(titre)
    reserve = pool()                 # les candidats déjà tirés (et ceux que ce tirage ajoutera pour les paquets suivants)

    poids = [config.POIDS[code] for code in codes]
    deja_pris = set(exclus)          # titres à ne pas tirer (ex. déjà dans la réserve)
    epuises = set()
    tirages = []
    for i in range(nombre):
        if codes_tires and i < len(codes_tires) and codes_tires[i] in codes:      # (les rangs ont été tirés d'avance, pour prévoir la durée : voir preparer)
            code_tire = codes_tires[i]
        else:
            code_tire = forcer if forcer in codes else random.choices(codes, weights=poids)[0]
        titre = None
        # Si aucun article n'est trouvé dans ce rang, on descend d'un rang (sauf pour un tirage forcé : GOD PACK, que des légendaires)
        for code in ([code_tire] if forcer in codes else codes[codes.index(code_tire):]):
            titre = piocher(code, top_par_rang, reserve, deja_pris, epuises, annonceur)
            if titre:
                break
        if titre:
            deja_pris.add(titre)
            tirages.append((titre, code_tire, datetime.now().astimezone()))
    return tirages
