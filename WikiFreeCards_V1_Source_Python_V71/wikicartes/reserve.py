"""Réserve de cartes : pré-chargement poli, en arrière-plan.

Pourquoi : à l'ouverture d'un paquet, le tirage interroge Wikipédia (2 à 4 requêtes espacées).
Si Wikipédia est lent, limite le débit ou ne répond pas, le paquet est lent ou impossible. La
réserve prépare des cartes D'AVANCE : l'ouverture d'un paquet puise dedans (instantané, aucune
requête) et ne tire en direct que les cartes qui manqueraient.

Comment, sans jamais « salir » l'API de Wikipédia :
- un seul fil d'exécution de fond, qui ne travaille que quand la réserve passe sous la moitié de
  sa cible (seuil bas), puis la remplit d'un coup en lots efficaces (un lot aléatoire de 50
  articles + une requête de détails pour 20 cartes : environ 2 requêtes pour 15 cartes) ;
- une requête à la fois (verrou commun à tout le programme : jamais de requêtes parallèles) ;
- une pause plus douce que la normale entre ses requêtes (RESERVE_PAUSE, 3 s par défaut) ;
- un plafond horaire strict (RESERVE_REQUETES_HEURE), compté dans la base : il survit à un
  redémarrage ; au-delà, on attend que la plus ancienne requête sorte de la fenêtre d'une heure ;
- jamais de nouvelle tentative après un 429 ou un 503 : on s'arrête, on respecte Retry-After et
  on double l'attente à chaque échec (5 min, 10 min, 20 min... jusqu'à 4 h) ;
- départ différé de 15 s après le lancement, et priorité à l'utilisateur : le pré-chargement
  attend quand tu ouvres un paquet ou fais une recherche ;
- requêtes publiques en lecture seule, identifiées par ton contact (User-Agent) : aucune donnée
  personnelle n'est envoyée ;
- tout ce que Wikipédia renvoie est vérifié avant d'être rangé (titre, textes, nombres, adresses
  limitées à wikipedia.org / wikimedia.org) puis enregistré par requêtes paramétrées.
"""

import math
from collections import deque
import threading
import time
import unicodedata
from contextlib import contextmanager

import requests

from . import api, base, config, tirage

DELAI_DEMARRAGE = 15            # s entre le lancement du programme et le premier pré-chargement
ATTENTE_REPOS = 30              # s entre deux vérifications quand tout va bien
LOT_MAX = 20                    # cartes préparées par cycle (= une seule requête de détails)
SEUIL_BAS = 0.5                 # on ne remplit que sous cette part de la cible
REQUETES_CYCLE_MIN = 3          # on ne démarre un cycle que s'il reste au moins ce budget
ATTENTE_ECHEC_BASE = 300        # s : 1er échec ; double à chaque échec de suite (plafond 4 h)
ATTENTE_ECHEC_MAX = 4 * 3600

_reveil = threading.Event()     # réveille le fil de fond (réserve consommée, remplissage demandé)
_arret = threading.Event()
_fil = None
_verrou = threading.Lock()
_etat = {"en_cours": False, "echecs": 0, "pause_jusqu_a": 0.0, "derniere_erreur": "",
         "dernier_remplissage": None, "preparees_total": 0, "demande": False}
_utilisateurs = 0               # opérations de l'utilisateur en cours (paquet en direct, recherche...)


# ---------------------------------------------------------------- priorité à l'utilisateur

@contextmanager
def priorite_utilisateur():
    """À utiliser autour de tout ce que l'utilisateur déclenche et qui interroge Wikipédia : le
    pré-chargement patiente tant que c'est en cours."""
    global _utilisateurs
    with _verrou:
        _utilisateurs += 1
    try:
        yield
    finally:
        with _verrou:
            _utilisateurs -= 1
        _reveil.set()


# ------------------------------------------------------------------------ tailles et budget

PAQUETS_PAR_TAILLE = {5: 10, 10: 3, 20: 1}       # paquets gardés d'avance selon le nombre de cartes du paquet
RENOUVELLEMENT = 3600                            # s : le stock vide se reconstitue complètement en 1 heure


def paquets_d_avance():
    """Combien de paquets on garde prêts à ouvrir : 10 paquets de 5 cartes, 3 de 10 cartes ou 1 de 20 cartes (ou la valeur
    forcée par RESERVE_PAQUETS, pour les essais)."""
    if config.RESERVE_PAQUETS is not None:
        return max(1, int(config.RESERVE_PAQUETS))
    return PAQUETS_PAR_TAILLE.get(int(config.NOMBRE_CARTES_PAQUET), 1)


def delai_paquet():
    """Secondes qui séparent deux paquets reconstitués : 1 heure divisée par le nombre de paquets du stock (6 min pour des
    paquets de 5 cartes, 20 min pour 10 cartes, 60 min pour 20 cartes)."""
    return RENOUVELLEMENT / paquets_d_avance()


def cible():
    """Cartes à garder d'avance : le stock de paquets × le nombre de cartes d'un paquet."""
    return paquets_d_avance() * int(config.NOMBRE_CARTES_PAQUET)


def seuil():
    """En dessous de ce nombre de cartes, le pré-chargement remplit la réserve."""
    return max(1, math.ceil(cible() * SEUIL_BAS))


def _budget(conn):
    """(requêtes de pré-chargement dans la dernière heure, plafond, secondes avant qu'une place se
    libère si le plafond est atteint, sinon 0)."""
    utilisees, plus_ancienne = base.reserve_requetes_recentes(conn)
    maxi = int(config.RESERVE_REQUETES_HEURE)
    attente = 0.0
    if utilisees >= maxi and plus_ancienne is not None:
        attente = max(1.0, plus_ancienne + 3600 - time.time())
    return utilisees, maxi, attente


def _avant_requete():
    """Appelé avant chaque requête de pré-chargement : note la requête et applique le plafond."""
    with base.connexion_rapide() as conn:
        utilisees, maxi, _ = _budget(conn)
        if utilisees >= maxi:
            raise api.BudgetEpuise("plafond horaire de requêtes de pré-chargement atteint")
        base.reserve_noter_requete(conn)


# ---------------------------------------------------------------------------- vérification

def _texte_sain(valeur, maximum, vide_ok=False):
    if not isinstance(valeur, str):
        return False
    if not vide_ok and not valeur.strip():
        return False
    return len(valeur) <= maximum and not any(
        unicodedata.category(c)[0] == "C" and c not in "\n\t" for c in valeur)


def valider_article(art):
    """Vérifie un article reçu de Wikipédia avant de le ranger dans la réserve (on ne fait pas
    confiance aux données reçues). Renvoie l'article, ou None s'il est refusé."""
    try:
        if not _texte_sain(art["titre"], 500) or ":" in art["titre"]:
            return None
        if not _texte_sain(art.get("description") or "", 2000, True):
            return None
        if not _texte_sain(art.get("intro") or "", 20000, True):
            return None
        if art["rarete"] not in config.CODES or art.get("rarete_tiree", art["rarete"]) not in config.CODES:
            return None
        if not (0 <= float(art["vues_moyenne"]) < 1e9) or not (0 <= int(art["vues_total"]) < 1e12):
            return None
        if api.adresse_wikimedia(art["url"]) is None:
            return None
        for cle in ("image", "miniature"):
            valeur = art.get(cle)
            if valeur not in (None, "", "no-image") and api.adresse_wikimedia(valeur) is None:
                return None
        if not isinstance(art.get("langue", config.LANGUE), str) or not 2 <= len(art.get("langue", config.LANGUE)) <= 12:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return art


# -------------------------------------------------------------------------- pré-chargement

def preparer(nombre):
    """Prépare `nombre` cartes (20 au plus) et les range dans la réserve, poliment (mode arrière-plan
    : pause douce, plafond horaire, aucune nouvelle tentative). Renvoie le nombre de cartes
    ajoutées. Lève une erreur réseau (LimiteDebit, BudgetEpuise...) si Wikipédia ne répond pas bien."""
    nombre = max(1, min(int(nombre), LOT_MAX))
    with base.connexion_rapide() as conn:
        deja = {ligne[0] for ligne in conn.execute("SELECT titre FROM reserve")}
    ajoutees = 0
    with api.en_arriere_plan(config.RESERVE_PAUSE, _avant_requete) as suivi:
        tirages = tirage.tirer_titres(nombre, exclus=deja)
        articles = api.recuperer_details(tirages) if tirages else []
        if articles and config.STATS_CARTES and config.STATS_AVEC_PAQUET:
            # Les statistiques (modifications, liens entrants) sont récupérées dès la préparation : la carte arrivera
            # COMPLÈTE à l'ouverture du paquet. S'il y a une limite (plafond, 429), ce qui manque est complété à l'ouverture.
            api.completer_stats(articles)
    propres = [a for a in articles if valider_article(a)]
    if propres:
        with base.connexion_rapide() as conn:
            ajoutees = base.reserve_ajouter(conn, propres)
    # Le tirage avale certaines erreurs réseau pour continuer : le pré-chargement, lui, doit les
    # connaître (pour patienter, doubler l'attente...). Les cartes déjà obtenues sont gardées.
    if suivi["erreur"] is not None:
        raise suivi["erreur"]
    if not tirages:
        raise requests.RequestException("Wikipédia n'a fourni aucun article")
    return ajoutees


def _stats_voulues():
    """Les statistiques des cartes préparées doivent-elles être complètes ? (réglages « statistiques » et « avec le paquet »)"""
    return bool(config.STATS_CARTES and config.STATS_AVEC_PAQUET)


def bloque_actif():
    """L'ouverture des paquets est-elle soumise à une réserve complète ? (réglage actif ET pré-chargement actif)"""
    return bool(config.RESERVE_BLOQUER_OUVERTURE and config.RESERVE_ACTIVE)


def completer_stats_reserve(lot=LOT_MAX):
    """Complète, poliment (mode arrière-plan, plafond horaire), les statistiques des cartes de la réserve auxquelles il en
    manque. Renvoie le nombre de cartes complétées entièrement. Lève une erreur réseau si Wikipédia ne répond pas bien."""
    with base.connexion_rapide() as conn:
        cartes = base.reserve_sans_stats(conn, lot)
    if not cartes:
        return 0
    articles = [{"id": c["id"], "titre": c["titre"], "nb_revisions": c["nb_revisions"],
                 "revisions_plafonnees": bool(c["revisions_plafonnees"]), "nb_liens_entrants": c["nb_liens_entrants"]}
                for c in cartes]
    with api.en_arriere_plan(config.RESERVE_PAUSE, _avant_requete) as suivi:
        api.completer_stats(articles)
    complets = 0
    with base.connexion_rapide() as conn:
        for art in articles:
            base.reserve_maj_stats(conn, art["id"], art.get("nb_revisions"), art.get("revisions_plafonnees"),
                                   art.get("nb_liens_entrants"))
            complets += art.get("nb_revisions") is not None and art.get("nb_liens_entrants") is not None
    if suivi["erreur"] is not None:
        raise suivi["erreur"]
    if complets == 0:                              # rien n'a pu être obtenu (pages introuvables...) : on ne boucle pas
        raise requests.RequestException("statistiques introuvables pour ces cartes")
    return complets


def cycle(forcer=False):
    """Un tour de pré-chargement : renvoie le nombre de cartes ajoutées (0 si rien à faire ou si
    l'attente est de mise). Appelé par le fil de fond, ou directement (tests, « Remplir maintenant »)."""
    with base.connexion_rapide() as conn:
        base.reserve_purger(conn, config.RESERVE_VALIDITE_JOURS)
        presentes = base.reserve_compter(conn)
        utilisees, maxi, attente_budget = _budget(conn)
        manques = base.reserve_manques_stats(conn) if _stats_voulues() else 0
    bloquant = bloque_actif()                          # ouverture bloquée tant que tout n'est pas prêt : on remplit TOUT
    if manques == 0 and (presentes >= cible() or (presentes >= seuil() and not forcer and not bloquant)):
        return 0
    with _verrou:
        if time.monotonic() < _etat["pause_jusqu_a"]:
            return 0                                   # on laisse Wikipédia souffler
    if maxi - utilisees < REQUETES_CYCLE_MIN:
        return 0                                       # budget horaire presque épuisé
    with _verrou:
        _etat["en_cours"] = True
    try:
        if manques > 0:                                # d'abord compléter les statistiques des cartes déjà là
            ajoutees = completer_stats_reserve()
        else:
            a_faire = cible() - presentes
            if bloquant:                               # d'abord de quoi former UN paquet (le décompte l'attend), le reste ensuite
                manquent_pour_un_paquet = int(config.NOMBRE_CARTES_PAQUET) - cartes_completes()
                if manquent_pour_un_paquet > 0:
                    a_faire = min(a_faire, manquent_pour_un_paquet)
            ajoutees = preparer(min(LOT_MAX, a_faire))
    except (requests.RequestException, KeyError, ValueError, IndexError) as erreur:
        _echec(erreur)
        return 0
    finally:
        with _verrou:
            _etat["en_cours"] = False
    with _verrou:
        _etat["echecs"] = 0
        _etat["derniere_erreur"] = ""
        _etat["pause_jusqu_a"] = 0.0
        _etat["demande"] = False
        _etat["preparees_total"] += ajoutees
        _etat["dernier_remplissage"] = time.time() if ajoutees else _etat["dernier_remplissage"]
    return ajoutees


def _echec(erreur):
    """Enregistre un échec et fixe l'attente avant la prochaine tentative (doublée à chaque
    échec de suite ; Retry-After de Wikipédia respecté)."""
    with _verrou:
        _etat["echecs"] += 1
        attente = min(ATTENTE_ECHEC_MAX, ATTENTE_ECHEC_BASE * 2 ** (_etat["echecs"] - 1))
        if isinstance(erreur, api.LimiteDebit):
            attente = max(attente, erreur.delai)
        if isinstance(erreur, api.BudgetEpuise):
            attente = 60
            _etat["echecs"] = max(0, _etat["echecs"] - 1)       # ce n'est pas une panne
        _etat["pause_jusqu_a"] = time.monotonic() + attente
        _etat["derniere_erreur"] = str(erreur)[:200]
        _etat["demande"] = False


# --------------------------------------------------------------------------- fil de fond

def _boucle():
    if _arret.wait(DELAI_DEMARRAGE):
        return
    while not _arret.is_set():
        attente = ATTENTE_REPOS
        try:
            if not config.RESERVE_ACTIVE:
                attente = 10
            elif _utilisateurs > 0:
                attente = 2                            # priorité à l'utilisateur
            else:
                with _verrou:
                    forcer = _etat["demande"]
                cycle(forcer)
                with _verrou:
                    restant = _etat["pause_jusqu_a"] - time.monotonic()
                if restant > 0:
                    attente = min(max(restant, 5), 600)
                else:
                    with base.connexion_rapide() as conn:
                        presentes = base.reserve_compter(conn)
                    en_attente_de_complet = bloque_actif() and not complete()      # l'ouverture attend : on enchaîne
                    attente = ATTENTE_REPOS if presentes >= seuil() and not en_attente_de_complet else 5
        except Exception as erreur:                    # le fil de fond ne doit jamais s'arrêter
            print(f"  (Pré-chargement : {erreur})")
            attente = 60
        _reveil.wait(attente)
        _reveil.clear()


def demarrer():
    """Lance le fil de fond (une seule fois). Appelé au démarrage du serveur local."""
    global _fil
    if _fil is not None and _fil.is_alive():
        return
    _arret.clear()
    _fil = threading.Thread(target=_boucle, name="reserve", daemon=True)
    _fil.start()


def arreter():
    _arret.set()
    _reveil.set()


def reveiller(demande=False):
    """Réveille le fil de fond ; `demande` : remplissage voulu même au-dessus du seuil bas."""
    if demande:
        with _verrou:
            _etat["demande"] = True
            _etat["pause_jusqu_a"] = 0.0 if _etat["echecs"] == 0 else _etat["pause_jusqu_a"]
    _reveil.set()


# ------------------------------------------------------------------------------ utilisation

def prelever(nombre):
    """Retire de la réserve jusqu'à `nombre` cartes pour un paquet (instantané, aucune requête) et
    réveille le pré-chargement s'il faut recompléter. Renvoie des articles au format du tirage,
    sans date de tirage (elle est donnée à l'ouverture)."""
    if not config.RESERVE_ACTIVE:
        return []
    with base.connexion_rapide() as conn:
        base.reserve_purger(conn, config.RESERVE_VALIDITE_JOURS)
        articles = base.reserve_prelever(conn, nombre, config.RESERVE_VALIDITE_JOURS)
    if articles:
        _reveil.set()
    return articles


def rendre(articles):
    """Remet dans la réserve des cartes prélevées pour un paquet qui n'a pas pu s'ouvrir (erreur
    inattendue) : elles ne sont jamais perdues."""
    if not articles:
        return 0
    try:
        with base.connexion_rapide() as conn:
            return base.reserve_ajouter(conn, articles)
    except Exception:                                  # pragma: no cover - dernier recours
        return 0


def vider():
    with base.connexion_rapide() as conn:
        return base.reserve_vider(conn)


def duree_lisible(secondes):
    """« 45 s », « 12 min », « 3 h 05 » : une durée courte à lire."""
    secondes = max(0, int(secondes))
    if secondes < 90:
        return f"{secondes} s"
    if secondes < 5400:
        return f"{round(secondes / 60)} min"
    return f"{secondes // 3600} h {round(secondes % 3600 / 60):02d}"


def texte_statut(e):
    """Ce que fait le pré-chargement en ce moment, en une phrase (page Configuration)."""
    if not e["actif"]:
        return "Désactivé : les paquets sont tirés à l'ouverture."
    if e["en_cours"]:
        return "Préparation de cartes en cours…"
    if e["pause"] > 0:
        return (f"En pause : Wikipédia a ralenti ou n'a pas répondu, reprise dans "
                f"{duree_lisible(e['pause'])} (échec n° {e['echecs']}).")
    if e["budget_attente"] > 0:
        return f"Plafond horaire atteint : reprise dans {duree_lisible(e['budget_attente'])}."
    if e["pretes"] >= e["cible"]:
        return "Réserve pleine."
    if e.get("bloque_actif"):
        return "Remplissage en cours : la réserve se complète poliment, un paquet est prêt dès qu'il a toutes ses cartes."
    if e["pretes"] >= e["seuil"]:
        return "Au repos : la réserve est suffisante (elle sera complétée sous le seuil bas)."
    if not e["fil_actif"]:
        return "Le pré-chargement démarre avec le serveur local (python main.py)."
    return "En attente : un remplissage va démarrer."


def etat():
    """L'état de la réserve pour la page Configuration."""
    with base.connexion_rapide() as conn:
        presentes = base.reserve_compter(conn)
        utilisees, maxi, attente_budget = _budget(conn)
        ancienne = base.reserve_plus_ancienne(conn)
    with _verrou:
        pause = max(0.0, _etat["pause_jusqu_a"] - time.monotonic())
        resultat = {
            "actif": bool(config.RESERVE_ACTIVE), "pretes": presentes, "cible": cible(),
            "seuil": seuil(), "paquets_prets": presentes // max(1, int(config.NOMBRE_CARTES_PAQUET)),
            "budget_utilise": utilisees, "budget_max": maxi,
            "budget_attente": round(attente_budget), "en_cours": _etat["en_cours"],
            "echecs": _etat["echecs"], "derniere_erreur": _etat["derniere_erreur"],
            "pause": round(pause), "plus_ancienne": ancienne,
            "dernier_remplissage": _etat["dernier_remplissage"],
            "preparees_total": _etat["preparees_total"],
            "fil_actif": _fil is not None and _fil.is_alive(),
            "bloque_actif": bloque_actif(), "paquets_cible": paquets_d_avance(), "delai_paquet": round(delai_paquet()),
        }
    resultat["jetons"] = round(jetons_disponibles(), 2) if resultat["bloque_actif"] else None
    return resultat


# ---------------------------------------------------------------- ouverture : jetons (stock de paquets) et réserve
#
# Le stock de paquets prêts à ouvrir est un « seau à jetons » : il contient au plus `paquets_d_avance()` jetons (10 paquets de
# 5 cartes, 3 de 10 cartes, 1 de 20 cartes). Ouvrir un paquet en consomme un ; un jeton se reconstitue toutes les
# `delai_paquet()` secondes (RENOUVELLEMENT / nombre de paquets = 1 h pour tout reconstituer). On peut ouvrir un paquet quand il
# reste au moins UN jeton ET au moins UN paquet de cartes COMPLÈTES (avec leurs statistiques) dans la réserve. Le pré-chargement
# se remet à remplir la réserve dès qu'un paquet est ouvert, poliment (pauses, plafond horaire). Le décompte annonce le plus long
# des deux : le temps qu'il faut pour qu'un jeton se reconstitue, ou pour que les cartes d'un paquet soient prêtes.

LATENCE_MIN = 0.2               # s : durée minimale supposée d'une requête dans l'estimation
ATTENTE_ENTRE_CYCLES = 5        # s : le fil de fond relance un cycle toutes les 5 s tant qu'il manque des cartes


def jetons_disponibles(maintenant=None):
    """Paquets qu'on peut ouvrir d'après le temps écoulé (nombre décimal : 2,4 = 2 paquets prêts et 40 % du suivant)."""
    maintenant = time.time() if maintenant is None else maintenant
    capacite = paquets_d_avance()
    with base.connexion_rapide() as conn:
        jetons, maj = base.jetons_lire(conn)
    if maj > maintenant:                                   # horloge remise en arrière : on repart de la valeur enregistrée
        maj = maintenant
    return max(0.0, min(float(capacite), jetons + (maintenant - maj) / delai_paquet()))


def consommer_jeton(maintenant=None):
    """Un paquet vient d'être ouvert : un jeton de moins (il se reconstituera avec le temps). Sans effet si l'ouverture n'est
    pas soumise au stock (réglage désactivé)."""
    if not bloque_actif():
        return None
    maintenant = time.time() if maintenant is None else maintenant
    restant = max(0.0, jetons_disponibles(maintenant) - 1.0)
    with base.connexion_rapide() as conn:
        base.jetons_ecrire(conn, restant, maintenant)
    return restant


def cartes_completes():
    """Cartes de la réserve prêtes à être ouvertes (avec leurs statistiques si elles sont demandées)."""
    with base.connexion_rapide() as conn:
        base.reserve_purger(conn, config.RESERVE_VALIDITE_JOURS)
        return base.reserve_compter_completes(conn, _stats_voulues())


def complete():
    """La réserve est PLEINE : toutes les cartes à garder d'avance sont là, avec toutes leurs statistiques (si elles sont
    demandées). Sert au pré-chargement (savoir quand il a fini), pas à l'ouverture d'un paquet."""
    with base.connexion_rapide() as conn:
        base.reserve_purger(conn, config.RESERVE_VALIDITE_JOURS)
        presentes = base.reserve_compter(conn)
        manques = base.reserve_manques_stats(conn) if _stats_voulues() else 0
    return presentes >= cible() and manques == 0


def _simuler(requetes, lots, instants, pause_jusqu_a):
    """Durée (s) de `requetes` requêtes faites l'une après l'autre : chacune dure RESERVE_PAUSE + la durée moyenne mesurée
    d'une requête ; 5 s entre deux cycles ; une pause de Wikipédia en cours retarde le début ; le PLAFOND HORAIRE est simulé
    requête par requête sur les instants réels du journal (`instants`, relatifs à maintenant) : quand il est atteint, on
    attend que la plus ancienne requête de la dernière heure en sorte, puis on reprend."""
    duree_requete = float(config.RESERVE_PAUSE) + max(LATENCE_MIN, api._latence)
    plafond = max(1, int(config.RESERVE_REQUETES_HEURE))
    t = max(0.0, pause_jusqu_a)
    fenetre = deque(instants)
    for _ in range(requetes):
        while fenetre and fenetre[0] + 3600 <= t:                            # sortie de la fenêtre d'une heure
            fenetre.popleft()
        if len(fenetre) >= plafond:                                          # plafond atteint : on attend une place
            t = max(t, fenetre[0] + 3600)
            while fenetre and fenetre[0] + 3600 <= t:
                fenetre.popleft()
        fenetre.append(t)
        t += duree_requete
    return t + lots * ATTENTE_ENTRE_CYCLES + api.TRAITEMENT


def _contexte(maintenant):
    with base.connexion_rapide() as conn:
        presentes = base.reserve_compter(conn)
        completes = base.reserve_compter_completes(conn, _stats_voulues())
        manques = base.reserve_manques_stats(conn) if _stats_voulues() else 0
        instants = [i - maintenant for i in base.reserve_instants(conn)]
    with _verrou:
        pause = _etat["pause_jusqu_a"] - time.monotonic()
    return presentes, completes, manques, instants, pause


def _requetes_nouvelles(nombre):
    """(requêtes, lots) pour tirer `nombre` cartes nouvelles, par lots de 20 : tirage + détails (+ langues), plus 2 requêtes de
    statistiques par carte."""
    stats_par_carte = 2 if _stats_voulues() else 0
    requetes, lots, restant = 0, 0, nombre
    while restant > 0:
        n = min(LOT_MAX, restant)
        requetes += tirage.estimer_requetes(n) + stats_par_carte * n
        restant -= n
        lots += 1
    return requetes, lots


def estimer_attente(maintenant=None):
    """Secondes avant que la réserve soit PLEINE (0 si elle l'est), d'après ce qu'il reste à faire : les cartes qui manquent
    (par lots de 20) et les statistiques qui manquent aux cartes déjà préparées (1 requête par valeur), au rythme du
    pré-chargement, avec le plafond horaire simulé (voir _simuler)."""
    maintenant = time.time() if maintenant is None else maintenant
    presentes, completes, manques, instants, pause = _contexte(maintenant)
    manquantes = max(0, cible() - presentes)
    if manquantes == 0 and manques == 0:
        return 0.0
    requetes, lots = _requetes_nouvelles(manquantes)
    requetes += manques
    if manques:
        lots += math.ceil(manques / (2 * LOT_MAX))
    return _simuler(requetes, lots, instants, pause)


def estimer_attente_cartes(voulues, maintenant=None):
    """Secondes avant qu'il y ait `voulues` cartes COMPLÈTES dans la réserve (0 s s'il y en a assez) : on complète d'abord
    les cartes qui n'ont pas toutes leurs statistiques, puis on en tire de nouvelles, au rythme du pré-chargement."""
    maintenant = time.time() if maintenant is None else maintenant
    presentes, completes, manques, instants, pause = _contexte(maintenant)
    a_obtenir = max(0, int(voulues) - completes)
    if a_obtenir == 0:
        return 0.0
    incompletes = max(0, presentes - completes)
    utilisables = min(a_obtenir, incompletes)
    requetes = min(2 * utilisables, manques) if utilisables else 0
    lots = math.ceil(utilisables / LOT_MAX) if utilisables else 0
    r, l = _requetes_nouvelles(a_obtenir - utilisables)
    return _simuler(requetes + r, lots + l, instants, pause)


def estimer_attente_paquet(maintenant=None):
    """Secondes avant qu'il y ait de quoi ouvrir UN paquet (0 s s'il y a assez de cartes complètes pour en former un)."""
    return estimer_attente_cartes(int(config.NOMBRE_CARTES_PAQUET), maintenant)


def bloque_actif():
    """L'ouverture des paquets est-elle soumise à une réserve complète ? (réglage actif ET pré-chargement actif)"""
    return bool(config.RESERVE_BLOQUER_OUVERTURE and config.RESERVE_ACTIVE)


def completer_stats_reserve(lot=LOT_MAX):
    """Complète, poliment (mode arrière-plan, plafond horaire), les statistiques des cartes de la réserve auxquelles il en
    manque. Renvoie le nombre de cartes complétées entièrement. Lève une erreur réseau si Wikipédia ne répond pas bien."""
    with base.connexion_rapide() as conn:
        cartes = base.reserve_sans_stats(conn, lot)
    if not cartes:
        return 0
    articles = [{"id": c["id"], "titre": c["titre"], "nb_revisions": c["nb_revisions"],
                 "revisions_plafonnees": bool(c["revisions_plafonnees"]), "nb_liens_entrants": c["nb_liens_entrants"]}
                for c in cartes]
    with api.en_arriere_plan(config.RESERVE_PAUSE, _avant_requete) as suivi:
        api.completer_stats(articles)
    complets = 0
    with base.connexion_rapide() as conn:
        for art in articles:
            base.reserve_maj_stats(conn, art["id"], art.get("nb_revisions"), art.get("revisions_plafonnees"),
                                   art.get("nb_liens_entrants"))
            complets += art.get("nb_revisions") is not None and art.get("nb_liens_entrants") is not None
    if suivi["erreur"] is not None:
        raise suivi["erreur"]
    if complets == 0:                              # rien n'a pu être obtenu (pages introuvables...) : on ne boucle pas
        raise requests.RequestException("statistiques introuvables pour ces cartes")
    return complets


def cycle(forcer=False):
    """Un tour de pré-chargement : renvoie le nombre de cartes ajoutées (0 si rien à faire ou si
    l'attente est de mise). Appelé par le fil de fond, ou directement (tests, « Remplir maintenant »)."""
    with base.connexion_rapide() as conn:
        base.reserve_purger(conn, config.RESERVE_VALIDITE_JOURS)
        presentes = base.reserve_compter(conn)
        utilisees, maxi, attente_budget = _budget(conn)
        manques = base.reserve_manques_stats(conn) if _stats_voulues() else 0
    bloquant = bloque_actif()                          # ouverture bloquée tant que tout n'est pas prêt : on remplit TOUT
    if manques == 0 and (presentes >= cible() or (presentes >= seuil() and not forcer and not bloquant)):
        return 0
    with _verrou:
        if time.monotonic() < _etat["pause_jusqu_a"]:
            return 0                                   # on laisse Wikipédia souffler
    if maxi - utilisees < REQUETES_CYCLE_MIN:
        return 0                                       # budget horaire presque épuisé
    with _verrou:
        _etat["en_cours"] = True
    try:
        if manques > 0:                                # d'abord compléter les statistiques des cartes déjà là
            ajoutees = completer_stats_reserve()
        else:
            a_faire = cible() - presentes
            if bloquant:                               # d'abord de quoi former UN paquet (le décompte l'attend), le reste ensuite
                manquent_pour_un_paquet = int(config.NOMBRE_CARTES_PAQUET) - cartes_completes()
                if manquent_pour_un_paquet > 0:
                    a_faire = min(a_faire, manquent_pour_un_paquet)
            ajoutees = preparer(min(LOT_MAX, a_faire))
    except (requests.RequestException, KeyError, ValueError, IndexError) as erreur:
        _echec(erreur)
        return 0
    finally:
        with _verrou:
            _etat["en_cours"] = False
    with _verrou:
        _etat["echecs"] = 0
        _etat["derniere_erreur"] = ""
        _etat["pause_jusqu_a"] = 0.0
        _etat["demande"] = False
        _etat["preparees_total"] += ajoutees
        _etat["dernier_remplissage"] = time.time() if ajoutees else _etat["dernier_remplissage"]
    return ajoutees


def _echec(erreur):
    """Enregistre un échec et fixe l'attente avant la prochaine tentative (doublée à chaque
    échec de suite ; Retry-After de Wikipédia respecté)."""
    with _verrou:
        _etat["echecs"] += 1
        attente = min(ATTENTE_ECHEC_MAX, ATTENTE_ECHEC_BASE * 2 ** (_etat["echecs"] - 1))
        if isinstance(erreur, api.LimiteDebit):
            attente = max(attente, erreur.delai)
        if isinstance(erreur, api.BudgetEpuise):
            attente = 60
            _etat["echecs"] = max(0, _etat["echecs"] - 1)       # ce n'est pas une panne
        _etat["pause_jusqu_a"] = time.monotonic() + attente
        _etat["derniere_erreur"] = str(erreur)[:200]
        _etat["demande"] = False


# --------------------------------------------------------------------------- fil de fond

def _boucle():
    if _arret.wait(DELAI_DEMARRAGE):
        return
    while not _arret.is_set():
        attente = ATTENTE_REPOS
        try:
            if not config.RESERVE_ACTIVE:
                attente = 10
            elif _utilisateurs > 0:
                attente = 2                            # priorité à l'utilisateur
            else:
                with _verrou:
                    forcer = _etat["demande"]
                cycle(forcer)
                with _verrou:
                    restant = _etat["pause_jusqu_a"] - time.monotonic()
                if restant > 0:
                    attente = min(max(restant, 5), 600)
                else:
                    with base.connexion_rapide() as conn:
                        presentes = base.reserve_compter(conn)
                    en_attente_de_complet = bloque_actif() and not complete()      # l'ouverture attend : on enchaîne
                    attente = ATTENTE_REPOS if presentes >= seuil() and not en_attente_de_complet else 5
        except Exception as erreur:                    # le fil de fond ne doit jamais s'arrêter
            print(f"  (Pré-chargement : {erreur})")
            attente = 60
        _reveil.wait(attente)
        _reveil.clear()


def demarrer():
    """Lance le fil de fond (une seule fois). Appelé au démarrage du serveur local."""
    global _fil
    if _fil is not None and _fil.is_alive():
        return
    _arret.clear()
    _fil = threading.Thread(target=_boucle, name="reserve", daemon=True)
    _fil.start()


def arreter():
    _arret.set()
    _reveil.set()


def reveiller(demande=False):
    """Réveille le fil de fond ; `demande` : remplissage voulu même au-dessus du seuil bas."""
    if demande:
        with _verrou:
            _etat["demande"] = True
            _etat["pause_jusqu_a"] = 0.0 if _etat["echecs"] == 0 else _etat["pause_jusqu_a"]
    _reveil.set()


# ------------------------------------------------------------------------------ utilisation

def prelever(nombre):
    """Retire de la réserve jusqu'à `nombre` cartes pour un paquet (instantané, aucune requête) et
    réveille le pré-chargement s'il faut recompléter. Renvoie des articles au format du tirage,
    sans date de tirage (elle est donnée à l'ouverture)."""
    if not config.RESERVE_ACTIVE:
        return []
    with base.connexion_rapide() as conn:
        base.reserve_purger(conn, config.RESERVE_VALIDITE_JOURS)
        articles = base.reserve_prelever(conn, nombre, config.RESERVE_VALIDITE_JOURS)
    if articles:
        _reveil.set()
    return articles


def rendre(articles):
    """Remet dans la réserve des cartes prélevées pour un paquet qui n'a pas pu s'ouvrir (erreur
    inattendue) : elles ne sont jamais perdues."""
    if not articles:
        return 0
    try:
        with base.connexion_rapide() as conn:
            return base.reserve_ajouter(conn, articles)
    except Exception:                                  # pragma: no cover - dernier recours
        return 0


def vider():
    with base.connexion_rapide() as conn:
        return base.reserve_vider(conn)


def duree_lisible(secondes):
    """« 45 s », « 12 min », « 3 h 05 » : une durée courte à lire."""
    secondes = max(0, int(secondes))
    if secondes < 90:
        return f"{secondes} s"
    if secondes < 5400:
        return f"{round(secondes / 60)} min"
    return f"{secondes // 3600} h {round(secondes % 3600 / 60):02d}"


def texte_statut(e):
    """Ce que fait le pré-chargement en ce moment, en une phrase (page Configuration)."""
    if not e["actif"]:
        return "Désactivé : les paquets sont tirés à l'ouverture."
    if e["en_cours"]:
        return "Préparation de cartes en cours…"
    if e["pause"] > 0:
        return (f"En pause : Wikipédia a ralenti ou n'a pas répondu, reprise dans "
                f"{duree_lisible(e['pause'])} (échec n° {e['echecs']}).")
    if e["budget_attente"] > 0:
        return f"Plafond horaire atteint : reprise dans {duree_lisible(e['budget_attente'])}."
    if e["pretes"] >= e["cible"]:
        return "Réserve pleine."
    if e.get("bloque_actif"):
        return "Remplissage en cours : la réserve se complète poliment, un paquet est prêt dès qu'il a toutes ses cartes."
    if e["pretes"] >= e["seuil"]:
        return "Au repos : la réserve est suffisante (elle sera complétée sous le seuil bas)."
    if not e["fil_actif"]:
        return "Le pré-chargement démarre avec le serveur local (python main.py)."
    return "En attente : un remplissage va démarrer."


def etat():
    """L'état de la réserve pour la page Configuration."""
    with base.connexion_rapide() as conn:
        presentes = base.reserve_compter(conn)
        utilisees, maxi, attente_budget = _budget(conn)
        ancienne = base.reserve_plus_ancienne(conn)
    with _verrou:
        pause = max(0.0, _etat["pause_jusqu_a"] - time.monotonic())
        resultat = {
            "actif": bool(config.RESERVE_ACTIVE), "pretes": presentes, "cible": cible(),
            "seuil": seuil(), "paquets_prets": presentes // max(1, int(config.NOMBRE_CARTES_PAQUET)),
            "budget_utilise": utilisees, "budget_max": maxi,
            "budget_attente": round(attente_budget), "en_cours": _etat["en_cours"],
            "echecs": _etat["echecs"], "derniere_erreur": _etat["derniere_erreur"],
            "pause": round(pause), "plus_ancienne": ancienne,
            "dernier_remplissage": _etat["dernier_remplissage"],
            "preparees_total": _etat["preparees_total"],
            "fil_actif": _fil is not None and _fil.is_alive(),
            "bloque_actif": bloque_actif(), "paquets_cible": paquets_d_avance(), "delai_paquet": round(delai_paquet()),
        }
    resultat["jetons"] = round(jetons_disponibles(), 2) if resultat["bloque_actif"] else None
    return resultat


# ---------------------------------------------------------------- ouverture : jetons (stock de paquets) et réserve
#
# Le stock de paquets prêts à ouvrir est un « seau à jetons » : il contient au plus `paquets_d_avance()` jetons (10 paquets de
# 5 cartes, 3 de 10 cartes, 1 de 20 cartes). Ouvrir un paquet en consomme un ; un jeton se reconstitue toutes les
# `delai_paquet()` secondes (RENOUVELLEMENT / nombre de paquets = 1 h pour tout reconstituer). On peut ouvrir un paquet quand il
# reste au moins UN jeton ET au moins UN paquet de cartes COMPLÈTES (avec leurs statistiques) dans la réserve. Le pré-chargement
# se remet à remplir la réserve dès qu'un paquet est ouvert, poliment (pauses, plafond horaire). Le décompte annonce le plus long
# des deux : le temps qu'il faut pour qu'un jeton se reconstitue, ou pour que les cartes d'un paquet soient prêtes.

LATENCE_MIN = 0.2               # s : durée minimale supposée d'une requête dans l'estimation
ATTENTE_ENTRE_CYCLES = 5        # s : le fil de fond relance un cycle toutes les 5 s tant qu'il manque des cartes


def jetons_disponibles(maintenant=None):
    """Paquets qu'on peut ouvrir d'après le temps écoulé (nombre décimal : 2,4 = 2 paquets prêts et 40 % du suivant)."""
    maintenant = time.time() if maintenant is None else maintenant
    capacite = paquets_d_avance()
    with base.connexion_rapide() as conn:
        jetons, maj = base.jetons_lire(conn)
    if maj > maintenant:                                   # horloge remise en arrière : on repart de la valeur enregistrée
        maj = maintenant
    return max(0.0, min(float(capacite), jetons + (maintenant - maj) / delai_paquet()))


def consommer_jeton(maintenant=None):
    """Un paquet vient d'être ouvert : un jeton de moins (il se reconstituera avec le temps). Sans effet si l'ouverture n'est
    pas soumise au stock (réglage désactivé)."""
    if not bloque_actif():
        return None
    maintenant = time.time() if maintenant is None else maintenant
    restant = max(0.0, jetons_disponibles(maintenant) - 1.0)
    with base.connexion_rapide() as conn:
        base.jetons_ecrire(conn, restant, maintenant)
    return restant


def cartes_completes():
    """Cartes de la réserve prêtes à être ouvertes (avec leurs statistiques si elles sont demandées)."""
    with base.connexion_rapide() as conn:
        base.reserve_purger(conn, config.RESERVE_VALIDITE_JOURS)
        return base.reserve_compter_completes(conn, _stats_voulues())


def complete():
    """La réserve est PLEINE : toutes les cartes à garder d'avance sont là, avec toutes leurs statistiques (si elles sont
    demandées). Sert au pré-chargement (savoir quand il a fini), pas à l'ouverture d'un paquet."""
    with base.connexion_rapide() as conn:
        base.reserve_purger(conn, config.RESERVE_VALIDITE_JOURS)
        presentes = base.reserve_compter(conn)
        manques = base.reserve_manques_stats(conn) if _stats_voulues() else 0
    return presentes >= cible() and manques == 0


def _simuler(requetes, lots, instants, pause_jusqu_a):
    """Durée (s) de `requetes` requêtes faites l'une après l'autre : chacune dure RESERVE_PAUSE + la durée moyenne mesurée
    d'une requête ; 5 s entre deux cycles ; une pause de Wikipédia en cours retarde le début ; le PLAFOND HORAIRE est simulé
    requête par requête sur les instants réels du journal (`instants`, relatifs à maintenant) : quand il est atteint, on
    attend que la plus ancienne requête de la dernière heure en sorte, puis on reprend."""
    duree_requete = float(config.RESERVE_PAUSE) + max(LATENCE_MIN, api._latence)
    plafond = max(1, int(config.RESERVE_REQUETES_HEURE))
    t = max(0.0, pause_jusqu_a)
    fenetre = deque(instants)
    for _ in range(requetes):
        while fenetre and fenetre[0] + 3600 <= t:                            # sortie de la fenêtre d'une heure
            fenetre.popleft()
        if len(fenetre) >= plafond:                                          # plafond atteint : on attend une place
            t = max(t, fenetre[0] + 3600)
            while fenetre and fenetre[0] + 3600 <= t:
                fenetre.popleft()
        fenetre.append(t)
        t += duree_requete
    return t + lots * ATTENTE_ENTRE_CYCLES + api.TRAITEMENT


def _contexte(maintenant):
    with base.connexion_rapide() as conn:
        presentes = base.reserve_compter(conn)
        completes = base.reserve_compter_completes(conn, _stats_voulues())
        manques = base.reserve_manques_stats(conn) if _stats_voulues() else 0
        instants = [i - maintenant for i in base.reserve_instants(conn)]
    with _verrou:
        pause = _etat["pause_jusqu_a"] - time.monotonic()
    return presentes, completes, manques, instants, pause


def _requetes_nouvelles(nombre):
    """(requêtes, lots) pour tirer `nombre` cartes nouvelles, par lots de 20 : tirage + détails (+ langues), plus 2 requêtes de
    statistiques par carte."""
    stats_par_carte = 2 if _stats_voulues() else 0
    requetes, lots, restant = 0, 0, nombre
    while restant > 0:
        n = min(LOT_MAX, restant)
        requetes += tirage.estimer_requetes(n) + stats_par_carte * n
        restant -= n
        lots += 1
    return requetes, lots


def estimer_attente(maintenant=None):
    """Secondes avant que la réserve soit PLEINE (0 si elle l'est), d'après ce qu'il reste à faire : les cartes qui manquent
    (par lots de 20) et les statistiques qui manquent aux cartes déjà préparées (1 requête par valeur), au rythme du
    pré-chargement, avec le plafond horaire simulé (voir _simuler)."""
    maintenant = time.time() if maintenant is None else maintenant
    presentes, completes, manques, instants, pause = _contexte(maintenant)
    manquantes = max(0, cible() - presentes)
    if manquantes == 0 and manques == 0:
        return 0.0
    requetes, lots = _requetes_nouvelles(manquantes)
    requetes += manques
    if manques:
        lots += math.ceil(manques / (2 * LOT_MAX))
    return _simuler(requetes, lots, instants, pause)


def estimer_attente_paquet(maintenant=None):
    """Secondes avant qu'il y ait de quoi ouvrir UN paquet : les cartes complètes qui manquent pour en former un (on
    complète d'abord celles qui n'ont pas toutes leurs statistiques, puis on en tire de nouvelles). 0 s s'il y en a assez."""
    maintenant = time.time() if maintenant is None else maintenant
    presentes, completes, manques, instants, pause = _contexte(maintenant)
    voulues = int(config.NOMBRE_CARTES_PAQUET)
    a_obtenir = max(0, voulues - completes)
    if a_obtenir == 0:
        return 0.0
    incompletes = max(0, presentes - completes)
    utilisables = min(a_obtenir, incompletes)
    requetes = min(2 * utilisables, manques) if utilisables else 0
    lots = math.ceil(utilisables / LOT_MAX) if utilisables else 0
    nouvelles = a_obtenir - utilisables
    r, l = _requetes_nouvelles(nouvelles)
    return _simuler(requetes + r, lots + l, instants, pause)


def bloque_actif():
    """L'ouverture des paquets est-elle soumise au stock de paquets prêts ? (réglage actif ET pré-chargement actif)"""
    return bool(config.RESERVE_BLOQUER_OUVERTURE and config.RESERVE_ACTIVE)


def statut_ouverture(maintenant=None):
    """Ce que la page doit savoir pour la légende du paquet, son décompte et le blocage du clic :
    {bloque, prets, capacite, secondes, minutes, reste, texte, raison}.
    - `prets` : combien de paquets on peut ouvrir tout de suite (le plus petit du stock de jetons et du nombre de paquets de
      cartes complètes de la réserve) ; `capacite` : le stock complet (10, 3 ou 1) ;
    - `bloque` : plus aucun paquet prêt (le clic ne fait rien) ;
    - `secondes` (`minutes` + `reste`) : l'attente jusqu'au PROCHAIN paquet : le plus long du temps de reconstitution du stock et
      du temps de préparation de ses cartes ; 0 quand le stock est plein (rien à attendre).
    Sans ouverture soumise au stock (réglage désactivé ou pré-chargement inactif), `prets` vaut None."""
    capacite = paquets_d_avance()
    vide = {"bloque": False, "prets": None, "capacite": capacite, "secondes": 0, "minutes": 0, "reste": 0, "texte": "", "raison": ""}
    if not bloque_actif():
        return vide
    maintenant = time.time() if maintenant is None else maintenant
    jetons = jetons_disponibles(maintenant)
    voulues = int(config.NOMBRE_CARTES_PAQUET)
    cartes = cartes_completes()
    prets = min(int(jetons + 1e-9), cartes // voulues)
    # Le PROCHAIN paquet (le n° prets + 1) demande un jeton de plus ET les cartes complètes d'un paquet de plus ; s'il n'y en a plus
    # à gagner (tout le stock est prêt), il n'y a rien à attendre.
    suivant = prets + 1
    attente_jeton = attente_cartes = 0.0
    if suivant <= capacite:
        attente_jeton = max(0.0, (suivant - jetons) * delai_paquet())
        if cartes < suivant * voulues:
            attente_cartes = estimer_attente_cartes(suivant * voulues, maintenant)
    prochain = max(attente_jeton, attente_cartes)
    secondes = max(1, math.ceil(prochain)) if prochain > 0 else 0
    with _verrou:
        pause = max(0.0, _etat["pause_jusqu_a"] - time.monotonic())
        erreur = _etat["derniere_erreur"] if pause > 0 else ""
    if not secondes:
        raison = ""
    elif erreur:
        raison = "Wikipédia a ralenti ou n'a pas répondu : nouvel essai bientôt."
    elif attente_jeton >= attente_cartes:
        raison = (f"Les paquets se reconstituent peu à peu : un toutes les {duree_lisible(delai_paquet())} "
                  f"(stock de {capacite}).")
    else:
        raison = "Préparation des cartes et de leurs statistiques…"
    minutes, reste = divmod(secondes, 60)
    return {"bloque": prets < 1, "prets": prets, "capacite": capacite, "secondes": secondes, "minutes": minutes,
            "reste": reste, "texte": f"Prochain paquet dans {minutes} min {reste:02d} s" if secondes else "", "raison": raison}
