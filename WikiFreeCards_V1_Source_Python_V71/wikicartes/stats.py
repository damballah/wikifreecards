"""Statistiques des cartes : langues, taille, modifications de la page et liens entrants.

Elles s'affichent sous chaque carte. Elles arrivent en deux temps, pour rester poli avec Wikipédia :
- langues et taille arrivent AVEC la carte (une requête de plus pour tout le paquet : les liens
  interlangues réels de Wikipédia ; la taille vient de la requête des détails, sans coût) ;
- modifications de la page et liens entrants demandent une requête chacun, page par page : un fil de
  fond les récupère ensuite, doucement (cartes les plus récentes d'abord). La page se met à jour
  toute seule quand elles arrivent.

Les mêmes règles que le pré-chargement des cartes (voir reserve.py) s'appliquent : une requête à
la fois (verrou commun), pause douce (RESERVE_PAUSE), plafond horaire propre aux statistiques
(STATS_REQUETES_HEURE, compté dans la base), jamais de nouvelle tentative après un 429 ou un 503 (on
respecte Retry-After et on double l'attente à chaque échec, jusqu'à 4 h), priorité à l'utilisateur.
Une carte dont la page ne répond pas (supprimée...) est abandonnée après 3 essais.
Aucune donnée n'est jamais envoyée à Wikipédia en dehors du titre de l'article demandé.
"""

import threading
import time

import requests

from . import api, base, config, reserve

SOURCE = "stats"                # nom du plafond horaire dans le journal des requêtes
DELAI_DEMARRAGE = 20            # s après le lancement du programme
ATTENTE_REPOS = 20              # s entre deux vérifications quand il n'y a rien à faire
REQUETES_MIN = 2                # budget minimal pour démarrer un travail (une carte = 2 requêtes)
ATTENTE_ECHEC_BASE = 300
ATTENTE_ECHEC_MAX = 4 * 3600
LOT_BASE = 20                   # cartes dont on récupère langues et taille en une fois

_reveil = threading.Event()
_arret = threading.Event()
_fil = None
_verrou = threading.Lock()
_etat = {"en_cours": False, "echecs": 0, "pause_jusqu_a": 0.0, "derniere_erreur": ""}


def _budget(conn):
    """(requêtes de statistiques dans la dernière heure, plafond, secondes avant qu'une place se
    libère si le plafond est atteint, sinon 0)."""
    utilisees, plus_ancienne = base.reserve_requetes_recentes(conn, source=SOURCE)
    maxi = int(config.STATS_REQUETES_HEURE)
    attente = 0.0
    if utilisees >= maxi and plus_ancienne is not None:
        attente = max(1.0, plus_ancienne + 3600 - time.time())
    return utilisees, maxi, attente


def _avant_requete():
    """Appelé avant chaque requête de statistiques : la note et applique le plafond horaire."""
    with base.connexion_rapide() as conn:
        utilisees, maxi, _ = _budget(conn)
        if utilisees >= maxi:
            raise api.BudgetEpuise("plafond horaire de requêtes de statistiques atteint")
        base.reserve_noter_requete(conn, SOURCE)


def _echec(erreur):
    """Fixe l'attente avant la prochaine tentative (doublée à chaque échec de suite)."""
    with _verrou:
        _etat["echecs"] += 1
        attente = min(ATTENTE_ECHEC_MAX, ATTENTE_ECHEC_BASE * 2 ** (_etat["echecs"] - 1))
        if isinstance(erreur, api.LimiteDebit):
            attente = max(attente, erreur.delai)
        if isinstance(erreur, api.BudgetEpuise):
            attente = 60
            _etat["echecs"] = max(0, _etat["echecs"] - 1)       # le plafond n'est pas une panne
        _etat["pause_jusqu_a"] = time.monotonic() + attente
        _etat["derniere_erreur"] = str(erreur)[:200]


def _statut_http(erreur):
    reponse = getattr(erreur, "response", None)
    return getattr(reponse, "status_code", None)


def _completer_base():
    """Langues et taille d'un lot des cartes les plus récentes (2 requêtes pour 20 cartes)."""
    with base.connexion_rapide() as conn:
        lot = base.cartes_sans_base(conn, LOT_BASE)
    if not lot:
        return
    with api.en_arriere_plan(config.RESERVE_PAUSE, _avant_requete):
        tailles = api.tailles([titre for _, titre in lot])
        langues = api.langues_wikipedia([titre for _, titre in lot])
    with base.connexion_rapide() as conn:
        for identifiant, titre in lot:
            nom = titre.replace("_", " ")
            if nom not in tailles and nom not in langues:   # la page n'existe plus ou a changé de titre
                base.noter_echec_stats(conn, identifiant)
                continue
            base.enregistrer_stats(conn, identifiant, taille_octets=tailles.get(nom),
                                   nb_langues=langues.get(nom))
            if tailles.get(nom) is None or langues.get(nom) is None:
                base.noter_echec_stats(conn, identifiant)      # incomplet : on n'insiste pas à l'infini


def _completer_page(carte):
    """Modifications et liens entrants d'une carte : une requête chacun, enregistrés au fur et à
    mesure. Une page qui répond 404 est abandonnée après quelques essais."""
    try:
        with api.en_arriere_plan(config.RESERVE_PAUSE, _avant_requete):
            if carte["revisions"]:
                nombre, plafonne = api.nb_revisions(carte["titre"])
                with base.connexion_rapide() as conn:
                    base.enregistrer_stats(conn, carte["id"], nb_revisions=nombre,
                                           revisions_plafonnees=plafonne)
            if carte["liens"]:
                nombre = api.nb_liens_entrants(carte["titre"])
                with base.connexion_rapide() as conn:
                    base.enregistrer_stats(conn, carte["id"], nb_liens_entrants=nombre)
    except requests.HTTPError as erreur:
        if _statut_http(erreur) in (400, 403, 404):    # cette page-là ne répond pas : on la laisse
            with base.connexion_rapide() as conn:
                base.noter_echec_stats(conn, carte["id"])
            return
        raise


def cycle():
    """Un travail de statistiques : renvoie True s'il y avait quelque chose à faire (et qu'on l'a
    fait), False sinon (rien à compléter, plafond atteint, pause en cours, fonction désactivée)."""
    if not config.STATS_CARTES:
        return False
    with _verrou:
        if time.monotonic() < _etat["pause_jusqu_a"]:
            return False
    with base.connexion_rapide() as conn:
        utilisees, maxi, _ = _budget(conn)
        carte = base.prochaine_carte_a_completer(conn)
    if carte is None or maxi - utilisees < REQUETES_MIN:
        return False
    with _verrou:
        _etat["en_cours"] = True
    try:
        if carte["base"]:
            _completer_base()
        else:
            _completer_page(carte)
    except (requests.RequestException, KeyError, ValueError, IndexError, TypeError) as erreur:
        _echec(erreur)
        return False
    finally:
        with _verrou:
            _etat["en_cours"] = False
    with _verrou:
        _etat["echecs"] = 0
        _etat["derniere_erreur"] = ""
    return True


def _boucle():
    if _arret.wait(DELAI_DEMARRAGE):
        return
    while not _arret.is_set():
        attente = ATTENTE_REPOS
        try:
            if not config.STATS_CARTES:
                attente = 10
            elif reserve._utilisateurs > 0:
                attente = 2                            # priorité à l'utilisateur
            else:
                with _verrou:
                    restant = _etat["pause_jusqu_a"] - time.monotonic()
                if restant > 0:
                    attente = min(max(restant, 5), 600)
                elif cycle():
                    attente = 0.5                      # la pause entre requêtes cadence déjà
                else:
                    with base.connexion_rapide() as conn:
                        _, _, attente_budget = _budget(conn)
                    attente = min(max(attente_budget, ATTENTE_REPOS), 600) if attente_budget else ATTENTE_REPOS
        except Exception as erreur:                    # le fil de fond ne doit jamais s'arrêter
            print(f"  (Statistiques : {erreur})")
            attente = 60
        _reveil.wait(attente)
        _reveil.clear()


def demarrer():
    """Lance le fil de fond (une seule fois). Appelé au démarrage du serveur local."""
    global _fil
    if _fil is not None and _fil.is_alive():
        return
    _arret.clear()
    _fil = threading.Thread(target=_boucle, name="statistiques", daemon=True)
    _fil.start()


def arreter():
    _arret.set()
    _reveil.set()


def reveiller():
    """De nouvelles cartes sont arrivées : le fil de fond peut s'en occuper (et celui qui vérifie les GIF animés aussi)."""
    _reveil.set()
    try:
        from . import gifs
        gifs.reveiller()
    except Exception:                                  # (jamais bloquant)
        pass


def etat():
    """L'état des statistiques pour la page Configuration."""
    with base.connexion_rapide() as conn:
        restantes = base.stats_manquantes(conn)
        utilisees, maxi, attente_budget = _budget(conn)
    with _verrou:
        pause = max(0.0, _etat["pause_jusqu_a"] - time.monotonic())
        return {"actif": bool(config.STATS_CARTES), "restantes": restantes,
                "budget_utilise": utilisees, "budget_max": maxi,
                "budget_attente": round(attente_budget), "pause": round(pause),
                "echecs": _etat["echecs"], "derniere_erreur": _etat["derniere_erreur"],
                "en_cours": _etat["en_cours"], "fil_actif": _fil is not None and _fil.is_alive()}
