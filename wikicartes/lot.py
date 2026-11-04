"""Importation de cartes EN LOT depuis un fichier .txt (un titre d'article Wikipédia par ligne), sans jamais surcharger Wikipédia.

Comment on reste poli avec Wikipédia (et on évite d'être bloqué), même pour 10 000 titres ou plus :
  1. LOTS DE 20 TITRES : une seule requête donne les détails (image, description, introduction, vues) de 20 articles. 10 000 titres = 500 requêtes, pas 10 000.
  2. UNE REQUÊTE À LA FOIS, jamais en parallèle (c'est ce que Wikimedia demande : plusieurs fils simultanés augmentent le risque d'être bloqué), avec une pause
     réglable entre deux requêtes (LOT_PAUSE, 2 s par défaut, jamais moins que PAUSE). Pendant l'importation, AUCUNE autre requête ne part du programme.
  3. Les titres déjà dans ta collection (et les doublons du fichier) sont écartés AVANT toute requête.
  4. `maxlag` : quand les serveurs de Wikipédia sont chargés, l'API demande d'attendre ; on attend, puis on ralentit encore.
  5. En cas de « trop de requêtes » (429/503), on respecte le délai demandé (Retry-After), on double les attentes à chaque nouvel avertissement et on augmente la
     pause ; après quelques avertissements de suite, l'importation s'interrompt d'elle-même (rien n'est perdu).
  6. Les statistiques secondaires (modifications, liens, GIF animés) ne sont PAS demandées pendant l'importation : elles arrivent ensuite, peu à peu, en arrière-plan.
  7. Tout est enregistré au fur et à mesure dans la base : l'importation peut être interrompue (par toi, par une panne, par la fermeture du programme) puis REPRISE là où elle
     s'est arrêtée.

Une seule importation à la fois. Tant qu'elle travaille, les pages du programme sont verrouillées par une fenêtre qui montre sa progression (static/lot.js).
"""

import math
import re
import sqlite3
import threading
import time
from datetime import datetime
from urllib.parse import unquote, urlsplit

import requests

from . import api, base, config, journal

TAILLE_LOT = 20                       # titres par requête (limite de Wikipédia pour les introductions)
MAX_OCTETS = 5_000_000                # taille maximale du fichier
MAX_LIGNES = 200_000
MAX_TITRES = 50_000                   # titres distincts maximum par importation
PAUSE_MAX = 10.0                      # la pause ne dépasse jamais 10 s, même après plusieurs ralentissements
AVERTISSEMENTS_MAX = 6                # avertissements « ralentis » de suite avant d'interrompre
ECHECS_MAX = 3                        # pannes réseau de suite avant d'interrompre
ATTENTE_RALENTISSEMENT = 20.0         # secondes d'attente au 1er avertissement « trop de requêtes » (puis ×2 à chaque nouvel avertissement, 15 min au plus)
ATTENTE_ECHEC = 5.0                   # secondes avant de réessayer après une panne réseau (puis ×3)

A_FAIRE, IMPORTE, POSSEDE, INTROUVABLE, IGNORE, ERREUR = 0, 1, 2, 3, 4, 5

_VERROU = threading.Lock()
_fil = None
_stop = threading.Event()
_vivant = {"phase": "", "message": "", "attente_jusqua": 0.0, "cycle": None, "pause": None, "debut": 0.0}


class LotImpossible(Exception):
    """Une importation ne peut pas démarrer (ou continuer) : le message dit pourquoi."""


# ---------------------------------------------------------------------------------------------------------------------- lecture du fichier

def nettoyer_ligne(ligne):
    """Un titre d'article d'après une ligne de fichier, ou None si la ligne n'en contient pas : espaces et caractères invisibles retirés, adresse Wikipédia
    convertie en titre, « _ » remplacé par une espace, partie « #section » ignorée, caractères interdits dans un titre refusés."""
    texte = str(ligne).replace("\ufeff", "").replace("\u200b", "").replace("\u00a0", " ")
    texte = re.sub(r"[\x00-\x1f\x7f]", " ", texte).strip()
    if not texte:
        return None
    if texte.lower().startswith(("http://", "https://")):
        morceaux = urlsplit(texte)
        if not (morceaux.hostname or "").endswith(".wikipedia.org") or not morceaux.path.startswith("/wiki/"):
            return None
        texte = unquote(morceaux.path[len("/wiki/"):])
    texte = texte.split("#", 1)[0].replace("_", " ")
    texte = re.sub(r"\s+", " ", texte).strip()
    if not texte or len(texte) > 255 or any(c in texte for c in "<>[]{}|"):
        return None
    return texte


def lire_titres(texte):
    """Les titres d'un fichier : (liste de titres distincts, dans l'ordre, {compteurs}). Compteurs : lignes, vides, invalides, doublons."""
    if not isinstance(texte, str):
        raise LotImpossible("le fichier n'est pas un texte")
    if len(texte.encode("utf-8", "ignore")) > MAX_OCTETS:
        raise LotImpossible(f"le fichier est trop gros (plus de {MAX_OCTETS // 1_000_000} Mo)")
    lignes = texte.splitlines()
    if len(lignes) > MAX_LIGNES:
        raise LotImpossible(f"le fichier a trop de lignes (plus de {MAX_LIGNES})")
    vus, titres = set(), []
    compteurs = {"lignes": len(lignes), "vides": 0, "invalides": 0, "doublons": 0}
    for ligne in lignes:
        if not ligne.strip():
            compteurs["vides"] += 1
            continue
        titre = nettoyer_ligne(ligne)
        if titre is None:
            compteurs["invalides"] += 1
            continue
        cle = titre[:1].upper() + titre[1:]                 # (Wikipédia met la 1re lettre en majuscule : « paris » et « Paris » sont le même article)
        if cle in vus:
            compteurs["doublons"] += 1
            continue
        vus.add(cle)
        titres.append(cle)
    if len(titres) > MAX_TITRES:
        raise LotImpossible(f"trop de titres distincts ({len(titres)} ; {MAX_TITRES} au plus par importation) : coupe ton fichier en plusieurs")
    return titres, compteurs


def _titres_possedes(conn):
    return {ligne[0] for ligne in conn.execute("SELECT titre FROM cartes WHERE supprime_le IS NULL AND personnalisee = 0")}


def duree_estimee(nb_titres, pause=None):
    """(nombre de requêtes, secondes estimées) pour `nb_titres` titres à demander à Wikipédia."""
    requetes = math.ceil(nb_titres / TAILLE_LOT)
    pause = max(float(config.LOT_PAUSE if pause is None else pause), float(config.PAUSE))
    cycle = pause + float(api._latence)
    return requetes, requetes * cycle


def analyser(texte, ignorer_possedes=True):
    """Ce que ferait l'importation de ce fichier, SANS rien demander à Wikipédia : titres lus, déjà possédés, requêtes et durée estimées."""
    titres, compteurs = lire_titres(texte)
    with base.connexion_rapide() as conn:
        possedes = _titres_possedes(conn)
    deja = [t for t in titres if t in possedes]
    a_importer = len(titres) - (len(deja) if ignorer_possedes else 0)
    requetes, secondes = duree_estimee(a_importer)
    return {"ok": True, **compteurs, "titres": len(titres), "deja_possedes": len(deja), "a_importer": a_importer, "requetes": requetes, "secondes": round(secondes),
            "taille_lot": TAILLE_LOT, "pause": max(float(config.LOT_PAUSE), float(config.PAUSE)), "exemples": titres[:5]}


# ---------------------------------------------------------------------------------------------------------------------- la tâche

def actif():
    """Une importation est-elle en train de travailler ? (rapide : sert à chaque page affichée)"""
    return _fil is not None and _fil.is_alive()


api.bloque_par_lot = actif


def _maintenant():
    return datetime.now().astimezone().replace(microsecond=0)


def _ligne_tache(conn):
    return conn.execute("SELECT * FROM import_lot WHERE id = 1").fetchone()


def _compteurs(conn):
    nombres = {code: 0 for code in range(6)}
    for etat, n in conn.execute("SELECT etat, COUNT(*) FROM import_lot_titre GROUP BY etat"):
        nombres[etat] = n
    return nombres


def etat():
    """L'état complet de l'importation, pour la fenêtre de progression : compteurs, cartes restantes, pourcentage, temps restant estimé, phase et message."""
    with base.connexion_rapide() as conn:
        t = _ligne_tache(conn)
        if t is None:
            return {"ok": True, "presente": False, "actif": False}
        n = _compteurs(conn)
    total = sum(n.values())
    restantes = n[A_FAIRE]
    travaille = actif()
    pause = _vivant["pause"] or max(float(t["pause"]), float(config.PAUSE))
    cycle = _vivant["cycle"] or (pause + float(api._latence))
    requetes_restantes = math.ceil(restantes / TAILLE_LOT)
    reste_attente = max(0.0, _vivant["attente_jusqua"] - time.monotonic()) if travaille else 0.0
    eta = requetes_restantes * cycle + reste_attente if travaille else None
    active = t["duree_active"] + ((time.monotonic() - _vivant["debut"]) if travaille and _vivant["debut"] else 0.0)
    return {"ok": True, "presente": True, "actif": travaille, "etat": t["etat"], "nom": t["nom"], "message": _vivant["message"] if travaille else t["message"],
            "phase": _vivant["phase"] if travaille else t["etat"], "total": total, "restantes": restantes, "importes": n[IMPORTE], "possedes": n[POSSEDE],
            "introuvables": n[INTROUVABLE], "ignores": n[IGNORE], "erreurs": n[ERREUR], "sans_vues": t["sans_vues"], "requetes": t["requetes"],
            "ralentissements": t["ralentissements"], "requetes_restantes": requetes_restantes, "pourcentage": round(100.0 * (total - restantes) / total, 1) if total else 100.0,
            "eta_s": None if eta is None else round(eta), "pause": round(pause, 1), "duree_s": round(active), "taille_lot": TAILLE_LOT,
            "ignorer_possedes": bool(t["ignorer_possedes"]), "moyenne_requete_s": None if not t["requetes"] else round(active / t["requetes"], 2)}


def _regler(**champs):
    """Met à jour la ligne de la tâche (message, état...)."""
    with base.connexion_rapide() as conn, base.transaction(conn):
        for nom, valeur in champs.items():
            conn.execute(f"UPDATE import_lot SET {nom} = ? WHERE id = 1", (valeur,))


def _vivant_maj(**champs):
    _vivant.update(champs)


def demarrer(texte, nom="", ignorer_possedes=True):
    """Crée l'importation et la lance. Lève LotImpossible si une autre est déjà là ou si le fichier est inutilisable."""
    global _fil
    with _VERROU:
        if actif():
            raise LotImpossible("une importation est déjà en cours")
        with base.connexion_rapide() as conn:
            existante = _ligne_tache(conn)
            if existante is not None and existante["etat"] == "interrompu" and _compteurs(conn)[A_FAIRE]:
                raise LotImpossible("une importation interrompue attend : reprends-la ou abandonne-la avant d'en lancer une autre")
        titres, _ = lire_titres(texte)
        if not titres:
            raise LotImpossible("aucun titre d'article trouvé dans ce fichier")
        pause = max(float(config.LOT_PAUSE), float(config.PAUSE))
        with base.connexion_rapide() as conn, base.transaction(conn):
            possedes = _titres_possedes(conn) if ignorer_possedes else set()
            conn.execute("DELETE FROM import_lot_titre")
            conn.execute("DELETE FROM import_lot")
            conn.execute("INSERT INTO import_lot (id, nom, etat, message, pause, ignorer_possedes, cree_le) VALUES (1, ?, 'en_cours', '', ?, ?, ?)",
                         (str(nom or "")[:200], pause, 1 if ignorer_possedes else 0, _maintenant().isoformat()))
            conn.executemany("INSERT INTO import_lot_titre (rang, titre, etat) VALUES (?, ?, ?)",
                             [(i, t, POSSEDE if t in possedes else A_FAIRE) for i, t in enumerate(titres)])
        journal.logiciel(f"Importation en lot démarrée : fichier « {str(nom or '')[:60]} », {len(titres)} titres distincts, {sum(1 for t in titres if t in possedes)} déjà possédés écartés, "
                         f"{math.ceil((len(titres) - sum(1 for t in titres if t in possedes)) / TAILLE_LOT)} requête(s) prévue(s), pause {pause:g} s")
        _lancer_fil()
    return etat()


def _lancer_fil():
    global _fil
    _stop.clear()
    _vivant.update(phase="requete", message="Démarrage…", attente_jusqua=0.0, cycle=None, pause=None, debut=time.monotonic())
    _fil = threading.Thread(target=_boucle, name="importation-lot", daemon=True)
    _fil.start()


def reprendre():
    with _VERROU:
        if actif():
            raise LotImpossible("l'importation travaille déjà")
        with base.connexion_rapide() as conn:
            t = _ligne_tache(conn)
            if t is None or t["etat"] == "termine" or not _compteurs(conn)[A_FAIRE]:
                raise LotImpossible("aucune importation à reprendre")
        _regler(etat="en_cours", message="")
        _lancer_fil()
    return etat()


def interrompre(attendre=0.0):
    """Demande l'arrêt : la requête en cours se termine, tout ce qui est fait reste enregistré, l'importation pourra être reprise."""
    _stop.set()
    if attendre and _fil is not None:
        _fil.join(attendre)
    return etat()


def abandonner():
    """Efface l'importation interrompue ou terminée (les cartes déjà importées restent)."""
    with _VERROU:
        if actif():
            raise LotImpossible("interromps d'abord l'importation en cours")
        with base.connexion_rapide() as conn, base.transaction(conn):
            conn.execute("DELETE FROM import_lot_titre")
            conn.execute("DELETE FROM import_lot")
    return {"ok": True, "presente": False, "actif": False}


def initialiser():
    """Au lancement du programme : une importation restée « en cours » (programme fermé pendant qu'elle travaillait) devient « interrompue » : on peut la reprendre."""
    try:
        with base.connexion_rapide() as conn:
            t = _ligne_tache(conn)
        if t is not None and t["etat"] == "en_cours" and not actif():
            _regler(etat="interrompu", message="Interrompue par la fermeture du programme : tu peux la reprendre.")
    except sqlite3.Error:
        pass


def arreter():
    """À la fermeture du programme."""
    _stop.set()


# ---------------------------------------------------------------------------------------------------------------------- le travail

def _attendre(secondes):
    """Attend `secondes` (par petits pas, pour pouvoir s'arrêter tout de suite). True si l'arrêt a été demandé."""
    fin = time.monotonic() + max(0.0, secondes)
    while True:
        reste = fin - time.monotonic()
        if reste <= 0:
            return _stop.is_set()
        if _stop.wait(min(0.5, reste)):
            return True


def _prochains():
    with base.connexion_rapide() as conn:
        return [(r[0], r[1]) for r in conn.execute("SELECT rang, titre FROM import_lot_titre WHERE etat = 0 ORDER BY rang LIMIT ?", (TAILLE_LOT,))]


def _terminer(etat_final, message=""):
    maintenant = time.monotonic()
    with base.connexion_rapide() as conn, base.transaction(conn):
        conn.execute("UPDATE import_lot SET etat = ?, message = ?, termine_le = ?, duree_active = duree_active + ? WHERE id = 1",
                     (etat_final, message[:400], _maintenant().isoformat() if etat_final == "termine" else None, max(0.0, maintenant - _vivant["debut"])))
    _vivant_maj(phase=etat_final, message=message)
    journal.logiciel(f"Importation en lot {'terminée' if etat_final == 'termine' else 'interrompue'}" + (f" : {message}" if message else ""))
    try:                                                  # les statistiques secondaires reprennent, à leur rythme, maintenant que l'importation est finie
        from . import gifs, stats
        stats.reveiller()
        gifs.reveiller()
    except Exception:
        pass


def _enregistrer(lot, resultat, ignorer_possedes):
    """Range les résultats d'une requête : cartes créées, titres introuvables, homonymies, doublons. Une seule transaction pour les cartes."""
    maintenant = _maintenant()
    etats, candidats = {}, []
    for rang, titre in lot:
        page = resultat.get(titre)
        if page is None:
            etats[rang] = INTROUVABLE
        elif page.get("ns", 0) != 0 or "disambiguation" in (page.get("pageprops") or {}):
            etats[rang] = IGNORE                          # pas un article (aide, catégorie...) ou page d'homonymie
        else:
            candidats.append((rang, api.article_depuis_page(page, maintenant)))
    with base.connexion_rapide() as conn:
        possedees = base.compter_par_url(conn, [a["url"] for _, a in candidats]) if (ignorer_possedes and candidats) else {}
    articles, urls_vues = [], set()
    for rang, article in candidats:
        if article["url"] in urls_vues or possedees.get(article["url"], 0) > 0:
            etats[rang] = POSSEDE                         # déjà chez toi, ou déjà vu dans cette requête (deux titres, même article)
        else:
            urls_vues.add(article["url"])
            articles.append(article)
            etats[rang] = IMPORTE
    sans_vues = sum(1 for a in articles if not a.get("vues_total"))
    if articles:                                          # (ces fonctions ont leurs propres transactions : on ne les imbrique pas)
        with base.connexion_rapide() as conn:
            identifiants = list(dict.fromkeys(base.ajouter_cartes(conn, articles)))
            if config.CATEGORIES_AUTO:
                base.classer_automatiquement(conn, identifiants)
    with base.connexion_rapide() as conn, base.transaction(conn):       # (si le programme s'arrête entre les deux, la reprise retrouve ces cartes comme « déjà possédées »)
        conn.executemany("UPDATE import_lot_titre SET etat = ? WHERE rang = ?", [(e, r) for r, e in etats.items()])
        conn.execute("UPDATE import_lot SET requetes = requetes + 1, sans_vues = sans_vues + ? WHERE id = 1", (sans_vues,))
    journal.logiciel(f"Importation en lot : {len(articles)} importée(s), {sum(1 for e in etats.values() if e == INTROUVABLE)} introuvable(s), "
                     f"{sum(1 for e in etats.values() if e == IGNORE)} ignorée(s), {sum(1 for e in etats.values() if e == POSSEDE)} déjà possédée(s) · {len(lot)} titres traités")


def _boucle():
    api._local.lot = True                                  # ce fil est le SEUL autorisé à parler à Wikipédia pendant l'importation
    try:
        with api.en_arriere_plan(0, None):                 # (jamais de nouvelle tentative automatique : on gère nous-mêmes les attentes)
            _travailler()
    except Exception as erreur:                            # une erreur imprévue interrompt proprement : rien n'est perdu
        try:
            _terminer("interrompu", f"Arrêtée par une erreur imprévue ({type(erreur).__name__}) : tu peux la reprendre.")
        except Exception:
            pass
    finally:
        api._local.lot = False


def _travailler():
    with base.connexion_rapide() as conn:
        t = _ligne_tache(conn)
    pause_base = max(float(t["pause"]), float(config.PAUSE))
    ignorer = bool(t["ignorer_possedes"])
    pause = pause_base
    _vivant_maj(pause=pause)
    debut_precedent = None
    avertissements = echecs = 0
    while True:
        if _stop.is_set():
            return _terminer("interrompu", "Interrompue : tu peux la reprendre quand tu veux.")
        lot = _prochains()
        if not lot:
            return _terminer("termine", "Importation terminée.")
        if debut_precedent is not None:                    # la pause se compte entre les DÉBUTS de deux requêtes
            reste = pause - (time.monotonic() - debut_precedent)
            if reste > 0:
                _vivant_maj(phase="pause", message="Pause de courtoisie entre deux requêtes…")
                if _attendre(reste):
                    continue
        debut = time.monotonic()
        _vivant_maj(phase="requete", message=f"Demande à Wikipédia des détails de {len(lot)} articles…", attente_jusqua=0.0)
        try:
            resultat = api.details_par_titres([titre for _, titre in lot])
        except (api.LimiteDebit, api.MaxLag) as erreur:
            avertissements += 1
            with base.connexion_rapide() as conn, base.transaction(conn):
                conn.execute("UPDATE import_lot SET ralentissements = ralentissements + 1 WHERE id = 1")
            if avertissements > AVERTISSEMENTS_MAX:
                return _terminer("interrompu", "Wikipédia demande sans cesse de ralentir : importation interrompue par prudence. Reprends-la plus tard.")
            delai = float(getattr(erreur, "delai", 0) or 0)
            attente = min(900.0, max(delai, ATTENTE_RALENTISSEMENT * 2 ** (avertissements - 1)))
            pause = min(PAUSE_MAX, pause * 1.5)            # on ralentit durablement (puis la pause redescend peu à peu)
            _vivant_maj(phase="ralentissement", pause=pause, attente_jusqua=time.monotonic() + attente,
                        message=f"Wikipédia demande de patienter : attente de {attente:.0f} s, puis on ralentit.")
            if _attendre(attente):
                continue
            debut_precedent = None
            continue
        except (requests.RequestException, ValueError, KeyError) as erreur:
            echecs += 1
            if echecs >= ECHECS_MAX:
                return _terminer("interrompu", f"Wikipédia ne répond pas ({erreur}) : importation interrompue. Reprends-la quand la connexion est revenue.")
            attente = ATTENTE_ECHEC * 3 ** (echecs - 1)
            _vivant_maj(phase="ralentissement", attente_jusqua=time.monotonic() + attente, message=f"Pas de réponse de Wikipédia : nouvelle tentative dans {attente:.0f} s…")
            if _attendre(attente):
                continue
            debut_precedent = None
            continue
        avertissements = echecs = 0
        try:
            _enregistrer(lot, resultat, ignorer)
        except sqlite3.Error as erreur:
            return _terminer("interrompu", f"Erreur d'enregistrement ({erreur}) : importation interrompue.")
        pause = max(pause_base, pause * 0.9)               # la pause redescend vers son réglage après un ralentissement
        fin = time.monotonic()
        cycle = (fin - debut_precedent) if debut_precedent is not None else (pause + (fin - debut))
        _vivant_maj(cycle=cycle if _vivant["cycle"] is None else 0.7 * _vivant["cycle"] + 0.3 * cycle, pause=pause)
        debut_precedent = debut


# ---------------------------------------------------------------------------------------------------------------------- routes (appelées par serveur.py)

def _route(fonction):
    def appel(demande):
        try:
            return 200, fonction(demande)
        except LotImpossible as erreur:
            return 409, {"erreur": str(erreur)}
        except sqlite3.Error as erreur:
            return 500, {"erreur": f"erreur interne : {erreur}"}
    return appel


ROUTES = {
    "/api/lot/analyser": _route(lambda d: analyser(d.get("texte"), d.get("ignorer_possedes", True) is not False)),
    "/api/lot/demarrer": _route(lambda d: demarrer(d.get("texte"), d.get("nom", ""), d.get("ignorer_possedes", True) is not False)),
    "/api/lot/etat": _route(lambda d: etat()),
    "/api/lot/interrompre": _route(lambda d: interrompre()),
    "/api/lot/reprendre": _route(lambda d: reprendre()),
    "/api/lot/abandonner": _route(lambda d: abandonner()),
}
