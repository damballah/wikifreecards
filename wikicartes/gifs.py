"""Quelles cartes ont un GIF RÉELLEMENT animé ?

La catégorie automatique « Animée » ne se fie plus à l'extension .gif : un GIF peut être une image fixe. Pour chaque carte dont l'illustration est un
.gif, on demande à Wikimedia le nombre d'images du fichier (une requête pour 20 cartes) ; à défaut, on lit le début du fichier. Le résultat est gardé
dans la base (cartes.gif_anime : 1 animé, 0 fixe). Tant qu'un GIF n'est pas vérifié, la carte n'est pas classée « Animée ». Les GIF fixes ne le sont jamais.

Ce travail se fait en arrière-plan, doucement (comme les statistiques) : il démarre avec le serveur et se réveille quand des cartes arrivent.
"""

import threading
import time

import requests

from . import api, base, config

LOT = 20
DELAI_DEMARRAGE = 4.0          # secondes avant le premier passage
ATTENTE_REPOS = 120.0          # attente quand il n'y a rien à faire
REESSAI = 1800.0               # un GIF dont on n'a pas pu savoir s'il est animé est revu au bout de 30 minutes

_reveil = threading.Event()
_arret = threading.Event()
_fil = None
_echecs = {}                   # id de carte -> instant du dernier échec


def verifier_lot():
    """Vérifie un lot de cartes à GIF non vérifié. Renvoie True s'il y avait du travail (et qu'il a été fait), False sinon."""
    if not config.ANIMEE_ACTIF:
        return False
    with base.connexion_rapide() as conn:
        lot = [(i, a) for i, a in base.gifs_a_verifier(conn, 4 * LOT) if time.monotonic() - _echecs.get(i, -REESSAI) >= REESSAI][:LOT]
    if not lot:
        return False
    try:
        with api.en_arriere_plan(config.RESERVE_PAUSE, None):
            resultat = api.verifier_gifs([adresse for _, adresse in lot])
    except (requests.RequestException, KeyError, ValueError, TypeError) as erreur:
        print(f"  (GIF animés : {erreur})")
        for identifiant, _ in lot:
            _echecs[identifiant] = time.monotonic()
        return False
    with base.connexion_rapide() as conn:
        for identifiant, adresse in lot:
            anime = resultat.get(adresse)
            if anime is None:
                _echecs[identifiant] = time.monotonic()
            else:
                base.marquer_gif(conn, identifiant, anime)
    return True


def _boucle():
    if _arret.wait(DELAI_DEMARRAGE):
        return
    while not _arret.is_set():
        attente = ATTENTE_REPOS
        try:
            if verifier_lot():
                attente = 1.0
        except Exception as erreur:                    # le fil de fond ne doit jamais s'arrêter
            print(f"  (GIF animés : {erreur})")
            attente = 60.0
        _reveil.wait(attente)
        _reveil.clear()


def demarrer():
    global _fil
    if _fil is not None and _fil.is_alive():
        return
    _arret.clear()
    _fil = threading.Thread(target=_boucle, name="gifs-animes", daemon=True)
    _fil.start()


def arreter():
    _arret.set()
    _reveil.set()


def reveiller():
    """De nouvelles cartes (ou une nouvelle illustration) sont arrivées : le fil de fond peut les vérifier."""
    _reveil.set()
