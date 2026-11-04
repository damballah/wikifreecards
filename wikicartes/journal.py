"""Journal d'activité : tout ce qui se passe quand on utilise le logiciel (actions humaines et actions du logiciel), avec la date et l'heure précises.

- Le fichier est `journal.log`, à la RACINE du programme (config.FICHIER_JOURNAL). Chaque ligne est aussi affichée dans la fenêtre de commandes, au fur et à mesure.
- C'est l'option JOURNAL_ACTIF (Configuration > Système) qui décide : désactivée, RIEN n'est écrit, ni dans le fichier ni à l'écran.
- Le fichier commence par un en-tête : date de démarrage de la session (le lancement du programme), date de création du journal, version, système. Supprimer le journal (Configuration
  > Système) en fait recommencer un autre tout de suite si l'option est active, avec un nouvel en-tête.
- Format d'une ligne :  2026-10-28 22:15:03.482 | HUMAIN    | POST /api/favori {id=12} → 200 (3 ms)
  Niveaux : HUMAIN (ce que TU fais : pages affichées, boutons...), LOGICIEL (ce que le programme fait seul : paquets, réserve, statistiques, importation...), WIKIPEDIA (chaque requête
  envoyée à Wikipédia), SYSTEME (démarrage, arrêt, réglages du journal), ERREUR.
- Respect de la vie privée : jamais de code d'accès, de jeton, de clé, de contact ni de contenu de fichier. Les valeurs sensibles sont remplacées par « ••• » et les longs textes par leur taille.
- Un problème d'écriture (disque plein, fichier verrouillé...) ne gêne jamais le programme : le journal s'en passe.
"""

import os
import platform
import re
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from . import config

SESSION_DEBUT = datetime.now()                  # le lancement du programme
TAILLE_MAX = 20 * 1024 * 1024                   # au-delà, le journal est archivé (journal.log.1) et un nouveau commence
LARGEUR_NIVEAU = 9

_VERROU = threading.Lock()
_SENSIBLE = re.compile(r"(code|mot_?de_?passe|password|jeton|token|secret|cle|contact|invitation|identite|pseudo_prive)", re.I)
_PAS_DE_DETAIL = ("/connexion", "/api/hall/", "/api/sauvegardes/importer")      # on ne détaille pas les champs de ces demandes (invitations, mots de passe, archives...)
_BRUYANTS = ("/api/journal/", "/api/lot/etat", "/api/reserve", "/api/cartes/stats", "/image/", "/fullart/", "/son", "/logo", "/favicon", "/static/")   # sondages de la page, fichiers


def actif():
    return bool(getattr(config, "JOURNAL_ACTIF", False))


def chemin():
    return Path(config.FICHIER_JOURNAL)


# ---------------------------------------------------------------------------------------------------------------------- écriture

def _entete(suite=False):
    maintenant = datetime.now()
    lignes = ["=" * 78, " WikiFreeCards — journal d'activité" + (" (suite : le précédent a atteint sa taille maximale)" if suite else "")]
    lignes.append(f" Session démarrée le {SESSION_DEBUT:%d/%m/%Y à %H:%M:%S} (lancement du programme)")
    lignes.append(f" Journal commencé le {maintenant:%d/%m/%Y à %H:%M:%S}")
    try:
        from . import projet
        version = projet.VERSION
    except Exception:
        version = "?"
    lignes.append(f" Version {version} · Python {platform.python_version()} · {platform.system()} {platform.release()}")
    lignes.append("=" * 78)
    return lignes


def _afficher(ligne):
    """La même ligne dans la fenêtre de commandes (sans jamais échouer : console absente, encodage limité...)."""
    flux = sys.stdout
    if flux is None:
        return
    try:
        print(ligne, flush=True)
    except UnicodeEncodeError:
        try:
            encodage = getattr(flux, "encoding", None) or "ascii"
            print(ligne.encode(encodage, "replace").decode(encodage, "replace"), flush=True)
        except Exception:
            pass
    except Exception:
        pass


def _ecrire_lignes(lignes):
    """Ajoute des lignes au fichier (créé avec son en-tête s'il n'existe pas ou est vide, archivé s'il est trop gros) et à l'écran. Dans le verrou."""
    fichier = chemin()
    avant = []
    try:
        taille = fichier.stat().st_size if fichier.exists() else 0
    except OSError:
        taille = 0
    if taille > TAILLE_MAX:
        try:
            archive = fichier.with_name(fichier.name + ".1")
            if archive.exists():
                archive.unlink()
            fichier.rename(archive)
            taille = 0
            avant = _entete(suite=True)
        except OSError:
            pass
    elif taille == 0:
        avant = _entete()
    with open(fichier, "a", encoding="utf-8", newline="\n") as f:
        for ligne in avant + lignes:
            f.write(ligne + "\n")
    for ligne in avant + lignes:
        _afficher(ligne)


def ecrire(niveau, texte):
    """Une ligne du journal (si l'option est active). Un texte sur plusieurs lignes est écrit en retrait. Ne lève jamais d'exception."""
    if not actif():
        return
    try:
        maintenant = datetime.now()
        debut = f"{maintenant:%Y-%m-%d %H:%M:%S}.{maintenant.microsecond // 1000:03d} | {str(niveau):<{LARGEUR_NIVEAU}} | "
        morceaux = str(texte).replace("\r", "").split("\n")
        lignes = [debut + morceaux[0]] + [" " * (len(debut) - 2) + "| " + m for m in morceaux[1:]]
        with _VERROU:
            _ecrire_lignes(lignes)
    except Exception:
        pass


def humain(texte):
    ecrire("HUMAIN", texte)


def logiciel(texte):
    ecrire("LOGICIEL", texte)


def systeme(texte):
    ecrire("SYSTEME", texte)


def erreur(texte, exception=None):
    if exception is not None:
        texte = f"{texte} : {type(exception).__name__}: {exception}\n" + "".join(traceback.format_exception(type(exception), exception, exception.__traceback__)[-4:]).rstrip()
    ecrire("ERREUR", texte)


# ---------------------------------------------------------------------------------------------------------------------- résumés sans données sensibles

def sensible(cle):
    return bool(_SENSIBLE.search(str(cle)))


def _valeur(cle, v):
    if sensible(cle):
        return "•••"
    if v is None or isinstance(v, (bool, int, float)):
        return str(v)
    if isinstance(v, str):
        return repr(v) if len(v) <= 60 else f"<texte de {len(v)} caractères>"
    if isinstance(v, (list, tuple)):
        if len(v) <= 6 and all(isinstance(x, (int, float, bool)) for x in v):
            return "[" + ", ".join(str(x) for x in v) + "]"
        return f"[{len(v)} éléments]"
    if isinstance(v, dict):
        return f"{{{len(v)} champs}}"
    return f"<{type(v).__name__}>"


def resumer_parametres(chemin_url, demande):
    """Les champs d'une demande du navigateur, sans rien de sensible : « id=12, favori=True ». Les réglages enregistrés (« valeurs ») sont détaillés un à un."""
    if not isinstance(demande, dict) or not demande:
        return ""
    if chemin_url.startswith(_PAS_DE_DETAIL):
        return f"{len(demande)} champ(s)"
    morceaux = []
    for cle, v in demande.items():
        if cle == "valeurs" and isinstance(v, dict):
            morceaux.append("réglages : " + ", ".join(f"{c}={_valeur(c, x)}" for c, x in list(v.items())[:40]))
        else:
            morceaux.append(f"{cle}={_valeur(cle, v)}")
    return ", ".join(morceaux)[:500]


def bruyant(methode, chemin_url, type_contenu="", statut=200):
    """Les requêtes qu'on ne note pas : sondages automatiques de la page, fichiers (images, sons, logo...). Les erreurs sont toujours notées."""
    if statut >= 400:
        return chemin_url.startswith("/api/journal/")
    if chemin_url.startswith(_BRUYANTS):
        return True
    if methode == "GET" and not str(type_contenu).startswith("text/html"):
        return True
    return False


def requete(methode, chemin_url, statut, duree_ms, type_contenu="", demande=None, requete_url=""):
    """Une requête du navigateur = une action humaine : page affichée ou bouton cliqué."""
    if not actif() or bruyant(methode, chemin_url, type_contenu, statut):
        return
    if methode == "GET":
        detail = ""
        for cle in ("page", "nouveau"):
            m = re.search(rf"(?:^|&){cle}=(\d+)", requete_url or "")
            if m:
                detail += f" {cle}={m.group(1)}"
        texte = f"Page {chemin_url}{detail} affichée" if statut < 400 else f"GET {chemin_url}{detail}"
    else:
        resume = resumer_parametres(chemin_url, demande)
        texte = f"Action {methode} {chemin_url}" + (f" {{{resume}}}" if resume else "")
    niveau = "ERREUR" if statut >= 500 else "HUMAIN"
    ecrire(niveau, f"{texte} → {statut} ({duree_ms:.0f} ms)")


def reseau(url, params, statut, duree_s):
    """Une requête envoyée à Wikipédia (jamais de secret dedans : seulement ce qu'on demande)."""
    if not actif():
        return
    try:
        p = dict(params or {})
        parties = []
        for cle in ("action", "list", "generator", "srsearch", "gsrsearch", "meta"):
            if cle in p:
                parties.append(f"{cle}={str(p[cle])[:60]}")
        if "prop" in p:
            parties.append(f"prop={str(p['prop'])[:50]}")
        if "titles" in p:
            titres = str(p["titles"]).split("|")
            parties.append(f"{len(titres)} titre(s) : " + " | ".join(t[:40] for t in titres[:3]) + ("…" if len(titres) > 3 else ""))
        hote = str(url).split("/")[2] if str(url).startswith("http") and len(str(url).split("/")) > 2 else str(url)[:40]
        if not parties and not p:
            parties.append(str(url).split("/")[-1][:60])
        ecrire("WIKIPEDIA", f"GET {hote} {' ; '.join(parties)} → {statut} ({duree_s * 1000:.0f} ms)")
    except Exception:
        pass


# ---------------------------------------------------------------------------------------------------------------------- l'état, la lecture, l'ouverture, la suppression (Configuration > Système)

def etat():
    fichier = chemin()
    taille, lignes = 0, 0
    try:
        if fichier.exists():
            taille = fichier.stat().st_size
            if taille <= 5_000_000:
                with open(fichier, "rb") as f:
                    lignes = sum(1 for _ in f)
    except OSError:
        pass
    return {"ok": True, "actif": actif(), "chemin": str(fichier), "existe": taille > 0, "taille": taille, "lignes": lignes, "session": f"{SESSION_DEBUT:%d/%m/%Y %H:%M:%S}"}


def lire(depuis=-1, maximum=150_000):
    """Du texte du journal pour la fenêtre de lecture. `depuis` : position déjà lue (-1 : la fin du fichier). Renvoie (texte, nouvelle position, taille, repart_de_zero)."""
    fichier = chemin()
    try:
        taille = fichier.stat().st_size
    except OSError:
        return "", 0, 0, depuis > 0
    repart = depuis > taille                         # le journal a été supprimé puis recréé : on repart du début
    fin_de_fichier = depuis == -1
    if repart:
        depuis = 0
    elif fin_de_fichier:
        depuis = max(0, taille - maximum)
    elif taille - depuis > maximum:
        depuis = taille - maximum
    with open(fichier, "rb") as f:
        f.seek(depuis)
        brut = f.read(taille - depuis)
    position = depuis + len(brut)
    if depuis > 0 and (fin_de_fichier or taille - depuis >= maximum):          # on est tombé au milieu d'une ligne : on commence à la suivante
        coupe = brut.find(b"\n")
        brut = brut[coupe + 1:] if coupe >= 0 else brut
    return brut.decode("utf-8", "replace"), position, taille, repart


def supprimer():
    """Supprime le journal (et son archive). S'il est actif, un nouveau journal commence tout de suite, avec son en-tête."""
    with _VERROU:
        fichier = chemin()
        for f in (fichier, fichier.with_name(fichier.name + ".1")):
            try:
                if f.exists():
                    f.unlink()
            except OSError as erreur:
                return False, f"impossible de supprimer {f.name} : {erreur}"
    systeme("Journal supprimé : nouveau journal commencé")
    return True, ""


def ouvrir_dans_le_systeme():
    """Ouvre le fichier avec l'application par défaut (Bloc-notes...). Le chemin est toujours celui du journal, jamais un chemin reçu du navigateur."""
    fichier = chemin()
    if not fichier.exists():
        return False, "il n'y a pas encore de journal"
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(fichier))                                         # noqa : Windows seulement
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(fichier)])
        else:
            subprocess.Popen(["xdg-open", str(fichier)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, AttributeError) as erreur:
        return False, f"impossible d'ouvrir le fichier : {erreur}"
    return True, ""


def _route(f):
    def appel(demande):
        try:
            return 200, f(demande)
        except OSError as erreur:
            return 500, {"erreur": str(erreur)}
    return appel


def _r_lire(d):
    depuis = d.get("depuis", -1)
    depuis = depuis if isinstance(depuis, int) and not isinstance(depuis, bool) and depuis >= -1 else -1
    texte, position, taille, repart = lire(depuis)
    return {"ok": True, "texte": texte, "position": position, "taille": taille, "repart": repart, "actif": actif()}


def _r_supprimer(d):
    ok, message = supprimer()
    if not ok:
        raise OSError(message)
    return etat()


def _r_ouvrir(d):
    ok, message = ouvrir_dans_le_systeme()
    if not ok:
        raise OSError(message)
    return {"ok": True}


ROUTES = {
    "/api/journal/etat": _route(lambda d: etat()),
    "/api/journal/lire": _route(_r_lire),
    "/api/journal/supprimer": _route(_r_supprimer),
    "/api/journal/ouvrir": _route(_r_ouvrir),
}
