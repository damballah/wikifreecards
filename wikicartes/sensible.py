"""Contenu sensible : flouter l'image des cartes dont le titre, le sous-titre ou la description contiennent un mot ou une expression de LA
LISTE DE L'UTILISATEUR (Configuration → Contenu sensible).

AUCUNE liste n'est fournie avec le programme : liste vide = rien n'est flouté et aucune icône +18 n'apparaît. On GARDE la carte ; seule son
image est floutée (réglage), avec une petite icône « interdit aux moins de 18 ans » pour la montrer ou la flouter de nouveau. La détection se
refait à l'affichage d'après la liste écrite par l'utilisateur (FLOU_MOTS) et ses exceptions (FLOU_EXCEPTIONS).

Les mots sont comparés sans accents ni majuscules, comme MOTS ENTIERS ou comme DÉBUTS de mot quand ils finissent par « * »
(« lingerie* » trouve lingerie, lingeries...).
"""

import json
import re
import threading
import time

from . import base
from . import categories as cat
from . import config

def _normaliser(mot):
    return cat.normaliser(mot).strip()


def _motif(mots):
    """Une expression régulière qui reconnaît ces mots (mots entiers ; « * » final = début de mot), ou None s'il n'y en a pas."""
    morceaux = []
    for mot in mots:
        mot = _normaliser(mot)
        if not mot:
            continue
        debut_de_mot = mot.endswith("*")
        mot = mot.rstrip("*").strip()
        if not mot:
            continue
        corps = re.escape(mot).replace(r"\ ", r"\s+").replace(r"\-", r"[-\s]?")
        morceaux.append(corps + (r"\w*" if debut_de_mot else ""))
    if not morceaux:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(sorted(morceaux, key=len, reverse=True)) + r")(?!\w)")


def mots_de_la_liste(texte):
    """Les mots et expressions d'un réglage (séparés par des virgules, des points-virgules ou des retours à la ligne), au plus 5000."""
    if not isinstance(texte, str):
        return []
    bruts = re.split(r"[,;\n]+", texte)
    return [m.strip() for m in bruts if m.strip()][:5000]


_cache = {"cle": None, "motifs": (None, None)}


def _motifs():
    cle = (config.FLOU_MOTS, config.FLOU_EXCEPTIONS)
    if _cache["cle"] != cle:
        _cache["motifs"] = (_motif(mots_de_la_liste(config.FLOU_MOTS)),
                            _motif(mots_de_la_liste(config.FLOU_EXCEPTIONS)))
        _cache["cle"] = cle
    return _cache["motifs"]


def est_sensible(titre="", sous_titre="", description=""):
    """La carte (titre, sous-titre, description) est-elle une carte à contenu sensible ? Les mots écartés par l'utilisateur l'emportent :
    un texte où l'on trouve un mot écarté n'est jamais sensible. Sans effet si le réglage est désactivé."""
    if not config.FLOU_ACTIF:
        return False
    trouve, ecarte = _motifs()
    if trouve is None:
        return False
    texte = " ".join(cat.normaliser(t) for t in (titre, sous_titre, description) if isinstance(t, str) and t not in ("no-description", "no-intro"))
    if not texte.strip():
        return False
    if ecarte is not None and ecarte.search(texte):
        return False
    return trouve.search(texte) is not None


def carte_sensible(art):
    """Comme est_sensible pour une carte (dictionnaire d'article ou de la base). Les cartes personnalisées sont celles de
    l'utilisateur : elles ne sont jamais floutées d'office."""
    if not isinstance(art, dict) or art.get("personnalisee"):
        return False
    return est_sensible(art.get("titre", ""), art.get("description", ""), art.get("intro", ""))


# ---------------------------------------------------------------- l'état « image montrée » de chaque carte, gardé d'un lancement à l'autre
CLE_REVELES = "ui.flou_reveles"
MAX_REVELEES = 2000                       # au-delà, les plus anciennes sont oubliées
_verrou = threading.Lock()
_cache_reveles = {"ts": 0.0, "urls": frozenset()}


def adresse_valide(url):
    """Une adresse d'article (http ou https, 500 caractères au plus, sans caractère de contrôle)."""
    return (isinstance(url, str) and 0 < len(url) <= 500 and url.startswith(("http://", "https://"))
            and not any(ord(c) < 32 or ord(c) == 127 for c in url))


def _lire():
    try:
        with base.connexion_rapide() as conn:
            ligne = base.lire_parametre_brut(conn, CLE_REVELES)
        valeur = json.loads(ligne[0]) if ligne else []
    except (ValueError, OSError, Exception):          # base illisible : on suppose « rien de montré » (tout reste flouté)
        return []
    return [u for u in valeur if adresse_valide(u)][:MAX_REVELEES] if isinstance(valeur, list) else []


def reveles(maintenant=None):
    """L'ensemble des adresses d'articles dont l'image a été montrée par l'utilisateur (lecture mise en cache une seconde)."""
    maintenant = time.monotonic() if maintenant is None else maintenant
    with _verrou:
        if maintenant - _cache_reveles["ts"] > 1.0:
            _cache_reveles["urls"], _cache_reveles["ts"] = frozenset(_lire()), maintenant
        return _cache_reveles["urls"]


def definir_revelee(url, revelee):
    """Garde (revelee vrai) ou oublie (faux) l'état « image montrée » d'une carte. Renvoie le nombre de cartes montrées."""
    if not adresse_valide(url):
        raise ValueError("adresse d'article invalide")
    with _verrou:
        liste = [u for u in _lire() if u != url]
        if revelee:
            liste.append(url)
        liste = liste[-MAX_REVELEES:]
        with base.connexion_rapide() as conn:
            base.ecrire_parametre_brut(conn, CLE_REVELES, json.dumps(liste, ensure_ascii=False, separators=(",", ":")))
        _cache_reveles["urls"], _cache_reveles["ts"] = frozenset(liste), time.monotonic()
        return len(liste)
