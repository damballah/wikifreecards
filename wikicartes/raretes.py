"""Les rangs des cartes quand les SEUILS de rareté changent.

Le rang d'une carte (L, UR, SR, R, PC, C...) vient de ses vues moyennes par jour et des seuils de la Configuration (« Rangs, seuils et noms »). Quand un seuil change (ou qu'un
rang est ajouté, retiré, réordonné), tous les rangs déjà enregistrés sont à refaire : c'est ce module qui s'en charge, en arrière-plan, par lots, avec une progression que la page
affiche (barre de progression).

- Seuls le rang ACTUEL (`rarete`) est recalculé ; le rang « tiré » (celui du jour où la carte est arrivée) reste tel quel. Les cartes de la réserve (pas encore tirées) sont
  refaites entièrement.
- Ne sont PAS touchées : les cartes créées à la main (leur rang est un thème choisi) et les cartes full-art (leur rang est figé).
- Le recalcul n'utilise que ce qui est déjà en base (les vues moyennes) : aucune requête vers Wikipédia, c'est rapide.
- Changer seulement le NOM d'un rang, ses probabilités de tirage ou son apparence ne change aucune carte : aucun recalcul, aucune confirmation.
"""

import threading
import time

from . import base, config, journal

LOT = 500                                   # cartes mises à jour par transaction
_VERROU = threading.Lock()
_etat = {"actif": False, "termine": False, "total": 0, "faits": 0, "changees": 0, "montees": 0, "descendues": 0, "reserve": 0, "debut": 0.0, "fin": 0.0, "erreur": "", "relancer": False}

_CONCERNEES = "c.personnalisee = 0 AND NOT EXISTS (SELECT 1 FROM fullart f WHERE f.carte_id = c.id)"


def signature(paliers):
    """Ce qui décide du rang d'une carte : la suite des (code, seuil), dans l'ordre. Les noms ne comptent pas."""
    return [(str(p[0]), float(p[1])) for p in paliers]


def classer_avec(paliers, vues_moyennes):
    """Le code du rang correspondant à des vues moyennes, avec ces paliers (comme rarete.classer, mais pour des paliers donnés)."""
    for palier in paliers:
        if vues_moyennes >= palier[1]:
            return palier[0]
    return paliers[-1][0]


def changements(anciens, nouveaux):
    """Les différences à montrer pour la confirmation : [{code, nom, genre « modifie » | « ajoute » | « supprime », avant, apres}] ; vide si les rangs ne changent pas.
    (Un changement d'ordre seul est signalé comme « ordre ».)"""
    av = {str(p[0]): p for p in anciens}
    ap = {str(p[0]): p for p in nouveaux}
    liste = []
    for code, p in ap.items():
        if code not in av:
            liste.append({"code": code, "nom": str(p[2]), "genre": "ajoute", "avant": None, "apres": float(p[1])})
        elif float(av[code][1]) != float(p[1]):
            liste.append({"code": code, "nom": str(p[2]), "genre": "modifie", "avant": float(av[code][1]), "apres": float(p[1])})
    for code, p in av.items():
        if code not in ap:
            liste.append({"code": code, "nom": str(p[2]), "genre": "supprime", "avant": float(p[1]), "apres": None})
    if not liste and signature(anciens) != signature(nouveaux):
        liste.append({"code": "", "nom": "", "genre": "ordre", "avant": None, "apres": None})
    return liste


def _position(paliers, code):
    for i, p in enumerate(paliers):
        if p[0] == code:
            return i
    return len(paliers)                    # un code inconnu est tout en bas


def simuler(conn, nouveaux, anciens=None):
    """Ce que donnerait le recalcul, sans rien écrire : {cartes (concernées), changent, montent, descendent, reserve}. Une carte MONTE si son nouveau rang est plus haut dans la liste."""
    anciens = list(config.PALIERS) if anciens is None else list(anciens)
    nouveaux = list(nouveaux)
    cartes = changent = montent = descendent = 0
    for ligne in conn.execute(f"SELECT c.rarete, c.vues_moyenne FROM cartes c WHERE {_CONCERNEES}"):
        cartes += 1
        apres = classer_avec(nouveaux, ligne[1])
        if apres != ligne[0]:
            changent += 1
            if _position(nouveaux, apres) < _position(anciens, ligne[0]):
                montent += 1
            else:
                descendent += 1
    reserve = conn.execute("SELECT COUNT(*) FROM reserve").fetchone()[0]
    return {"cartes": cartes, "changent": changent, "montent": montent, "descendent": descendent, "reserve": reserve}


def etat():
    with _VERROU:
        e = dict(_etat)
    e.pop("relancer", None)
    e["pourcentage"] = 100 if (e["termine"] and e["total"] == 0) else (round(100 * e["faits"] / e["total"]) if e["total"] else 0)
    e["duree"] = round((e["fin"] if e["fin"] else time.time()) - e["debut"], 1) if e["debut"] else 0
    return e


def demarrer():
    """Lance le recalcul de tous les rangs, d'après les seuils ACTUELS de config.PALIERS (voir le module). Déjà en cours : il recommence une fois fini, avec les derniers seuils."""
    with _VERROU:
        if _etat["actif"]:
            _etat["relancer"] = True
            return False
        _etat.update(actif=True, termine=False, total=0, faits=0, changees=0, montees=0, descendues=0, reserve=0, debut=time.time(), fin=0.0, erreur="", relancer=False)
    threading.Thread(target=_travail, name="raretes", daemon=True).start()
    return True


def _travail():
    try:
        while True:
            paliers = [tuple(p) for p in config.PALIERS]                   # une photo des seuils : un changement en cours de route donne lieu à un second tour
            _un_tour(paliers)
            with _VERROU:
                if not _etat["relancer"]:
                    break
                _etat.update(relancer=False, total=0, faits=0, changees=0, montees=0, descendues=0, reserve=0, termine=False, debut=time.time())
    except Exception as erreur:                                           # le recalcul ne doit jamais laisser la page attendre sans fin
        with _VERROU:
            _etat["erreur"] = f"{type(erreur).__name__}: {erreur}"[:300]
        journal.erreur("Recalcul des rangs interrompu", erreur)
    finally:
        with _VERROU:
            _etat.update(actif=False, termine=True, fin=time.time(), relancer=False)
        e = etat()
        journal.logiciel(f"Recalcul des rangs terminé en {e['duree']} s : {e['changees']} carte(s) sur {e['total']} ont changé de rang "
                         f"({e['montees']} montent, {e['descendues']} descendent)" + (f", {e['reserve']} de la réserve" if e["reserve"] else "")
                         + (f" · ERREUR : {e['erreur']}" if e["erreur"] else ""))


def _un_tour(paliers):
    with base.connexion_rapide() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM cartes c WHERE {_CONCERNEES}").fetchone()[0]
    with _VERROU:
        _etat["total"] = total
    dernier = 0
    while True:
        with base.connexion_rapide() as conn:
            lignes = conn.execute(f"SELECT c.id, c.rarete, c.vues_moyenne FROM cartes c WHERE {_CONCERNEES} AND c.id > ? ORDER BY c.id LIMIT ?", (dernier, LOT)).fetchall()
            if not lignes:
                break
            maj, montees, descendues = [], 0, 0
            for ligne in lignes:
                apres = classer_avec(paliers, ligne[2])
                if apres != ligne[1]:
                    maj.append((apres, ligne[0]))
                    if _position(paliers, apres) < _position(paliers, ligne[1]):
                        montees += 1
                    else:
                        descendues += 1
            if maj:
                with base.transaction(conn):
                    conn.executemany("UPDATE cartes SET rarete = ? WHERE id = ?", maj)
        dernier = lignes[-1][0]
        with _VERROU:
            _etat["faits"] += len(lignes)
            _etat["changees"] += len(maj)
            _etat["montees"] += montees
            _etat["descendues"] += descendues
    with base.connexion_rapide() as conn:                                  # la réserve : des cartes pas encore tirées, refaites entièrement (rang actuel ET rang tiré)
        lignes = conn.execute("SELECT id, rarete, vues_moyenne FROM reserve").fetchall()
        maj = [(classer_avec(paliers, v), classer_avec(paliers, v), i) for i, r, v in lignes if classer_avec(paliers, v) != r]
        if maj:
            with base.transaction(conn):
                conn.executemany("UPDATE reserve SET rarete = ?, rarete_tiree = ? WHERE id = ?", maj)
    with _VERROU:
        _etat["reserve"] = len(maj)
        _etat["faits"] = _etat["total"]
