"""Ouverture d'un paquet de cartes : tirage, enregistrement dans la base, cartes à afficher.

Appelé par la page (bouton « paquet ») via le serveur local. Le nombre de cartes est
config.NOMBRE_CARTES_PAQUET (de 1 à 20, réglable dans la page Configuration).
"""

import random
import threading
import time

import requests

from datetime import datetime

from . import api, base, config, parametres, rendu, reserve, stats, terminal
from .tirage import estimer_requetes, requetes_finales, tirer_godpack, tirer_titres

_VERROU = threading.Lock()     # un seul paquet à la fois (le tirage interroge Wikipédia)


class PaquetEnCours(Exception):
    """Un autre paquet est déjà en cours d'ouverture."""


class PaquetImpossible(Exception):
    """Le tirage a échoué (Wikipédia injoignable, aucun article trouvé...)."""


class Annonceur:
    """Prévient la page de l'avancement du tirage, avec le temps restant CALCULÉ d'après les
    réglages (pause entre requêtes, durée mesurée d'une requête : voir api.estimer_duree). Chaque
    annonce est un dictionnaire : {"type": "plan" | "etape" | "ralentissement", "restantes": nombre
    de requêtes encore à faire, "duree": secondes avant l'ouverture du paquet, "pause": PAUSE}.
    `emettre` reçoit ces dictionnaires (le serveur les envoie à la page en direct)."""

    def __init__(self, emettre):
        self._emettre = emettre
        self.restantes = 0
        self.stats = 0                      # requêtes de statistiques à faire (à la cadence plus rapide STATS_PAUSE_PAQUET)

    def plan(self, restantes, stats=0):
        self.restantes = restantes
        self.stats = stats
        self._envoyer("plan")

    def etape(self, restantes, stats=None):
        self.restantes = restantes
        if stats is not None:
            self.stats = stats
        self._envoyer("etape")

    def ralentissement(self, delai):
        """Wikipédia a demandé de patienter `delai` secondes : le décompte s'allonge d'autant."""
        self._envoyer("ralentissement", delai=round(delai, 1))

    def _envoyer(self, genre, **plus):
        duree = api.estimer_duree(self.restantes) + plus.get("delai", 0)
        if self.stats > 0:                  # + les statistiques, une requête chacune, à la cadence des statistiques du paquet
            duree += self.stats * (float(config.STATS_PAUSE_PAQUET) + api._latence)
        self._emettre({"type": genre, "restantes": self.restantes + self.stats, "duree": round(duree, 2),
                       "pause": config.PAUSE, **plus})


def _completer_stats_du_paquet(articles, annonceur=None):
    """Les statistiques (modifications, liens entrants) des cartes du paquet arrivent AVEC les cartes : elles sont récupérées
    tout de suite, hors du plafond horaire (c'est une action de l'utilisateur, bornée par la taille du paquet), avec une pause
    plus courte que d'habitude. Si Wikipédia limite le débit ou tombe en panne, le paquet s'ouvre quand même et le fil de fond
    complète le reste plus tard."""
    if not (config.STATS_CARTES and config.STATS_AVEC_PAQUET):
        return
    total = api.stats_manquantes_des(articles)
    if not total:
        return
    if annonceur is not None:
        annonceur.etape(0, stats=total)
    with reserve.priorite_utilisateur():
        with api.en_arriere_plan(config.STATS_PAUSE_PAQUET, None, pause_reseau=config.STATS_PAUSE_PAQUET):
            api.completer_stats(articles, rappel=(lambda restantes: annonceur.etape(0, stats=restantes)) if annonceur else None)


class PaquetInvalide(ValueError):
    """Demande de retrait de cartes refusée (pas de paquet récent, cartes qui n'en font pas partie)."""


GODPACK = {"force": False}                   # (essais) vrai : le prochain paquet est un GOD PACK


def composer_godpack(articles, nombre):
    """Un GOD PACK ne contient que des cartes LÉGENDAIRES : parmi les articles les plus consultés, on garde d'abord ceux dont le rang réel est déjà
    légendaire, puis, s'il n'y en a pas assez ce jour-là, les plus vus des autres, qui sont PROMUS légendaires par le GOD PACK. Les cartes
    gardent leurs vraies vues ; seul leur rang est celui du GOD PACK. Renvoie `nombre` cartes au plus (moins s'il manque des articles)."""
    legendaire = config.CODES[0]
    vrais = [a for a in articles if a.get("rarete") == legendaire]
    autres = [a for a in articles if a.get("rarete") != legendaire]
    choisis = (vrais + autres)[:nombre]
    for art in choisis:
        art["rarete"] = legendaire
        art["rarete_nom"] = config.NOMS.get(legendaire, art.get("rarete_nom"))
        art["rarete_tiree"] = legendaire
    return choisis


def godpack_tire():
    """Ce paquet est-il un GOD PACK ? Une chance sur GODPACK_UN_SUR (0 : jamais) ; un paquet forcé (essais) l'est toujours."""
    n = int(config.GODPACK_UN_SUR or 0)
    if GODPACK["force"]:
        GODPACK["force"] = False
        return True
    return n > 0 and random.randrange(n) == 0


DERNIER = {"ids": [], "instant": 0.0}        # les cartes du dernier paquet ouvert (on peut en retirer pendant 1 heure)
_VERROU_DERNIER = threading.Lock()
DELAI_RETRAIT = 3600


def _donnees_collection(nouvelles, comptes, nb_favoris, total, doublons, compteurs, bandeaux):
    """Ce que la page affiche après l'ouverture (ou après le retrait de cartes) : les cartes du paquet, le résumé, les
    compteurs, les doublons, la pagination."""
    pages = max(1, -(-total // config.CARTES_PAR_PAGE))
    return {
        "cartes": rendu.fragments_cartes(nouvelles),
        "resume": rendu.html_resume(comptes, nb_favoris),
        "infos": rendu.texte_infos(total),
        "nombre": len(nouvelles),
        "total": total,
        "doublons": doublons,
        "compteurs": compteurs,
        "bandeaux": bandeaux,
        "pages": pages,
        "par_page": config.CARTES_PAR_PAGE,
        "pagination": rendu.html_pagination(1, pages),
    }


def retirer_du_paquet(identifiants):
    """Supprime TOUT DE SUITE (pour de bon, sans passer par la corbeille) des cartes du dernier paquet ouvert, que
    l'utilisateur ne veut pas garder. Seules les cartes de ce paquet, pendant 1 heure, peuvent être retirées. Renvoie les
    données mises à jour pour la page (cartes restantes du paquet, compteurs, résumé...)."""
    if (not isinstance(identifiants, list) or not identifiants or len(identifiants) > 20
            or any(isinstance(i, bool) or not isinstance(i, int) for i in identifiants)):
        raise PaquetInvalide("liste de cartes invalide")
    with _VERROU_DERNIER:
        actuelles = list(DERNIER["ids"])
        recent = time.time() - DERNIER["instant"] <= DELAI_RETRAIT
    if not recent or not actuelles:
        raise PaquetInvalide("aucun paquet récent dont on puisse retirer des cartes")
    if not set(identifiants) <= set(actuelles):
        raise PaquetInvalide("ces cartes ne font pas partie du dernier paquet")
    with base.connexion_rapide() as conn:
        base.supprimer_cartes_du_paquet(conn, set(identifiants))
        restantes = [i for i in actuelles if i not in set(identifiants)]
        nouvelles = base.cartes_par_identifiants(conn, restantes) if restantes else []
        comptes = base.compter_par_rang(conn)
        nb_favoris = base.compter_favoris(conn)
        total = base.compter(conn)
        doublons = base.compter_doublons(conn)
        compteurs = base.compteurs_categories(conn)
        bandeaux = rendu.bandeaux_meme_titre(conn, [c["titre"] for c in nouvelles], restantes) if nouvelles else {}
    with _VERROU_DERNIER:
        DERNIER["ids"] = restantes
    donnees = _donnees_collection(nouvelles, comptes, nb_favoris, total, doublons, compteurs, bandeaux)
    donnees["retirees"] = len(identifiants)
    return donnees


def ouvrir_paquet(annonceur=None):
    """Tire les cartes d'un paquet, les enregistre, les classe automatiquement dans les catégories
    dont une « meta » apparaît dans leur description, et renvoie ce qu'il faut afficher :
    {"cartes": HTML des nouvelles cartes, "resume": HTML des boutons de filtre,
     "infos": phrase d'en-tête, "nombre": cartes du paquet, "total": cartes de la collection,
     "pages", "par_page", "pagination": HTML de la pagination (page 1)}."""
    if not _VERROU.acquire(blocking=False):
        raise PaquetEnCours("un paquet est déjà en cours d'ouverture")
    api.ecouteur_ralentissement = annonceur.ralentissement if annonceur else None
    try:
        nombre = config.NOMBRE_CARTES_PAQUET
        godpack = godpack_tire()                  # une chance sur 10 000 (réglable) : un paquet de cartes TOUTES légendaires
        candidats_godpack = []
        if godpack:
            candidats_godpack = tirer_godpack(nombre, annonceur)
            if not candidats_godpack:             # le top des articles les plus vus est indisponible : un paquet ordinaire plutôt qu'une erreur
                godpack = False
        # 1) La réserve d'abord : cartes préparées d'avance (instantané, aucune requête). Un GOD PACK n'en vient pas : il est tiré à part.
        preleves = [] if godpack else reserve.prelever(nombre)
        inseres = False                       # vrai dès que les cartes sont dans la collection
        try:
            maintenant = datetime.now().astimezone()
            for art in preleves:
                art["tire_le"] = maintenant
            manquantes = nombre - len(preleves)
            # 2) Les cartes qui manquent sont tirées en direct (comme avant)
            articles_direct, avertissement = [], ""
            if manquantes > 0:
                with reserve.priorite_utilisateur():
                    try:
                        if annonceur is not None:             # le décompte démarre, d'après les réglages
                            annonceur.plan(estimer_requetes(manquantes),
                                           stats=2 * manquantes if config.STATS_CARTES and config.STATS_AVEC_PAQUET else 0)
                        tirages = candidats_godpack if godpack else tirer_titres(manquantes, annonceur)
                        if tirages and annonceur is not None:
                            annonceur.etape(requetes_finales())   # il ne reste que les détails (+ langues)
                        articles_direct = api.recuperer_details(tirages) if tirages else []
                        if godpack:
                            articles_direct = composer_godpack(articles_direct, nombre)
                    except requests.RequestException as erreur:
                        if not preleves:
                            raise PaquetImpossible(f"Wikipédia est injoignable ({erreur}).") from erreur
                        avertissement = (f"Wikipédia ne répond pas : paquet de {len(preleves)} carte"
                                         f"{'s' if len(preleves) > 1 else ''} au lieu de {nombre}.")
                if not articles_direct and not preleves:
                    raise PaquetImpossible("Aucun article trouvé : Wikipédia est peut-être injoignable "
                                           "ou ralentit. Réessaie dans un instant.")
                if not articles_direct and preleves and not avertissement:
                    avertissement = (f"Paquet de {len(preleves)} carte{'s' if len(preleves) > 1 else ''} "
                                     f"au lieu de {nombre} : Wikipédia n'a pas fourni le reste.")
            elif annonceur is not None:
                annonceur.plan(0)                             # tout vient de la réserve : pas d'attente
            articles = preleves + articles_direct
            api.marquer_gifs(articles)                        # un GIF n'est « animé » que s'il l'est vraiment (une requête, seulement s'il y a des GIF)
            _completer_stats_du_paquet(articles, annonceur)
            # Les cartes du paquet sont rangées des plus COMMUNES aux plus RARES (la plus rare en dernier) : elles ont toutes la
            # même date de tirage, et la collection range à date égale dans l'ordre d'enregistrement.
            ordre_rangs = {code: i for i, code in enumerate(reversed(config.CODES))}
            articles.sort(key=lambda a: ordre_rangs.get(a.get("rarete"), len(ordre_rangs)))

            with base.connexion_rapide() as conn:
                identifiants = list(dict.fromkeys(base.ajouter_cartes(conn, articles)))
                inseres = True
                stats.reveiller()                 # modifications et liens : récupérés en arrière-plan
                if config.CATEGORIES_AUTO:
                    base.classer_automatiquement(conn, identifiants)
                nouvelles = base.cartes_par_identifiants(conn, identifiants)
                comptes = base.compter_par_rang(conn)
                nb_favoris = base.compter_favoris(conn)
                total = base.compter(conn)
                doublons = base.compter_doublons(conn)
                compteurs = base.compteurs_categories(conn)
                bandeaux = rendu.bandeaux_meme_titre(conn, [c["titre"] for c in nouvelles],
                                                     identifiants)

        except BaseException:
            if not inseres:                   # un paquet qui échoue ne fait perdre aucune carte préparée
                reserve.rendre(preleves)
            raise
        terminal.afficher_resume(nouvelles)
        reserve.consommer_jeton()                 # un paquet de moins dans le stock (il se reconstitue avec le temps)
        with _VERROU_DERNIER:
            DERNIER["ids"], DERNIER["instant"] = list(identifiants), time.time()     # le paquet qu'on peut encore retoucher
        donnees = _donnees_collection(nouvelles, comptes, nb_favoris, total, doublons, compteurs, bandeaux)
        reel = godpack and len(nouvelles) == nombre and all(c.get("rarete") == config.CODES[0] for c in nouvelles)
        donnees.update({"depuis_reserve": len(preleves), "avertissement": avertissement, "godpack": bool(reel)})
        return donnees
    finally:
        api.ecouteur_ralentissement = None
        _VERROU.release()
