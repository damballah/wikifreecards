"""Tor pour le Hall des collections : le détecter, expliquer quoi faire s'il manque, et le lancer pour toi.

Le programme n'installe jamais Tor à ta place : il détecte s'il tourne (proxy SOCKS et port de contrôle), indique où le
télécharger, et peut LANCER un Tor déjà présent sur ta machine (« Lancer Tor », ou automatiquement au démarrage) avec
un fichier torrc qu'il écrit lui-même dans data/tor/. Il ne lance que le programme « tor » / « tor.exe ».
"""

import glob
import locale
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

from . import config, journal, p2p_transport as transport

URL_EXPERT_BUNDLE = "https://www.torproject.org/download/tor/"
URL_NAVIGATEUR = "https://www.torproject.org/download/"
DELAI_LANCEMENT = 25
_VERROU = threading.Lock()
_PROCESSUS = None
_DERNIERE_ERREUR = None


class TorIntrouvable(RuntimeError):
    """Aucun programme Tor n'a été trouvé sur la machine (message avec la marche à suivre)."""


class TorEchec(RuntimeError):
    """Tor a été lancé mais n'a pas démarré correctement."""


def _ouvert(adresse, delai=0.6):
    try:
        hote, port = transport.analyser_hote_port(adresse)
        socket.create_connection((hote, port), timeout=delai).close()
        return True
    except (OSError, transport.TransportErreur):
        return False


def detecter():
    """Tor tourne-t-il ? {socks: adresse qui répond ou None, controle: idem, navigateur: vrai si ce sont les ports du
    navigateur Tor}. Les ports d'origine ET ceux du navigateur Tor sont essayés (comme pour la connexion)."""
    socks = next((a for a in transport.candidats_tor("socks", config.P2P_TOR_SOCKS) if _ouvert(a)), None)
    controle = next((a for a in transport.candidats_tor("controle", config.P2P_TOR_CONTROLE) if _ouvert(a)), None)
    return {"socks": socks, "controle": controle, "navigateur": bool(controle and controle.endswith(":9151"))}


def _nom_valide(chemin):
    return os.path.basename(str(chemin).replace("\\", "/")).lower() in ("tor", "tor.exe")


def candidats_executables():
    """Les endroits où chercher le programme Tor : ton réglage, le PATH, puis les emplacements habituels."""
    liste = []
    if config.P2P_TOR_EXECUTABLE:
        liste.append(config.P2P_TOR_EXECUTABLE)
    liste += [shutil.which("tor"), shutil.which("tor.exe")]
    maison = Path.home()
    locaux = os.environ.get("LOCALAPPDATA", "")
    modeles = [
        str(maison / "Desktop" / "Tor Browser" / "Browser" / "TorBrowser" / "Tor" / "tor.exe"),
        str(Path(locaux) / "Tor Browser" / "Browser" / "TorBrowser" / "Tor" / "tor.exe") if locaux else "",
        str(maison / "Desktop" / "tor-expert-bundle*" / "tor" / "tor.exe"),
        str(maison / "Downloads" / "tor-expert-bundle*" / "tor" / "tor.exe"),
        str(maison / "Documents" / "tor-expert-bundle*" / "tor" / "tor.exe"),
        str(maison / "tor-expert-bundle*" / "tor" / "tor.exe"),
        "C:/Tor/tor.exe", "C:/Tor/Tor/tor.exe", "C:/tor-expert-bundle*/tor/tor.exe", "C:/Program Files/Tor/tor.exe",
        "/usr/bin/tor", "/usr/local/bin/tor", "/opt/homebrew/bin/tor", "/usr/sbin/tor",
    ]
    for modele in modeles:
        if modele:
            liste += sorted(glob.glob(modele), reverse=True)
    return [c for c in liste if c]


def trouver_executable():
    """Le premier programme « tor » ou « tor.exe » exécutable trouvé, ou None."""
    for c in candidats_executables():
        chemin = Path(c)
        if _nom_valide(c) and chemin.is_file() and os.access(chemin, os.X_OK):
            return chemin
    return None


def pays_systeme():
    """Le code pays (2 lettres, minuscules) de la langue de l'ordinateur (« fr_FR » -> « fr »), ou "" si on ne sait pas."""
    try:
        code = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""       # noqa: DEP (getdefaultlocale : repli)
    except (ValueError, TypeError, AttributeError):
        code = ""
    if "_" in code:
        pays = code.split("_")[1][:2].lower()
        return pays if len(pays) == 2 and pays.isalpha() else ""
    return ""


def pays_relais():
    """Le pays préféré pour les relais d'entrée : TOR_PAYS, « auto » étant le pays de l'ordinateur. "" : aucune préférence."""
    valeur = (config.TOR_PAYS or "").strip().lower()
    if valeur == "auto":
        return pays_systeme()
    return valeur if len(valeur) == 2 and valeur.isalpha() else ""


def fichiers_geoip():
    """(geoip, geoip6) livrés avec Tor (à côté de tor.exe, dans « data » ou « Data »), ou (None, None) s'ils manquent : sans eux
    Tor ne sait pas dans quel pays est un relais, et la préférence de pays est ignorée."""
    executable = trouver_executable()
    if executable is None:
        return None, None
    for dossier in (executable.parent / "data", executable.parent / "Data", executable.parent.parent / "data",
                    executable.parent / "geoip", executable.parent):
        v4, v6 = dossier / "geoip", dossier / "geoip6"
        if v4.is_file():
            return v4, (v6 if v6.is_file() else None)
    return None, None


def contenu_torrc(dossier=None):
    """Le fichier torrc que le programme écrit pour lancer Tor (ports d'après tes réglages ; relais d'entrée du pays préféré)."""
    socks = transport.analyser_hote_port(config.P2P_TOR_SOCKS)
    controle = transport.analyser_hote_port(config.P2P_TOR_CONTROLE)
    lignes = [f"SocksPort {socks[0]}:{socks[1]}", f"ControlPort {controle[0]}:{controle[1]}", "CookieAuthentication 1"]
    pays = pays_relais()
    if pays and dossier is not None:
        v4, v6 = fichiers_geoip()
        if v4 is not None:                                   # sans le fichier geoip, la préférence serait ignorée (voire refusée)
            lignes.append(f'GeoIPFile "{Path(v4).as_posix()}"')
            if v6 is not None:
                lignes.append(f'GeoIPv6File "{Path(v6).as_posix()}"')
            lignes += [f"EntryNodes {{{pays}}}", "StrictNodes 0"]         # préférence : Tor garde ses relais de secours
    if dossier is not None:
        lignes.append(f'DataDirectory "{Path(dossier).as_posix()}"')       # barres obliques : valables sous Windows aussi
    return "\n".join(lignes) + "\n"


def torrc_a_copier():
    """Le torrc à créer à la main (sans le dossier de données : Tor choisit le sien)."""
    return contenu_torrc(None)


def en_cours():
    with _VERROU:
        return _PROCESSUS is not None and _PROCESSUS.poll() is None


def lance_par_nous():
    return en_cours()


_TRAVAIL = None                      # (Windows) objet de travail qui tue Tor si le programme disparaît
_VERROU_TRAVAIL = threading.Lock()   # (jamais _VERROU : lancer() le tient quand il appelle lier_a_notre_vie, et un verrou ne se reprend pas lui-même)


def _structures_travail():
    """Les structures Windows de l'objet de travail (JOBOBJECT_EXTENDED_LIMIT_INFORMATION : 144 octets sous Windows 64 bits). Séparé pour pouvoir vérifier leur taille."""
    import ctypes

    class COMPTEURS(ctypes.Structure):
        _fields_ = [(nom, ctypes.c_uint64) for nom in ("lectures", "ecritures", "autres", "octets_lus", "octets_ecrits", "octets_autres")]

    class BASE(ctypes.Structure):
        _fields_ = [("temps_par_processus", ctypes.c_int64), ("temps_travail", ctypes.c_int64), ("options", ctypes.c_uint32), ("ens_min", ctypes.c_size_t),
                    ("ens_max", ctypes.c_size_t), ("processus_actifs", ctypes.c_uint32), ("affinite", ctypes.c_size_t), ("priorite", ctypes.c_uint32),
                    ("ordonnancement", ctypes.c_uint32)]

    class ETENDUE(ctypes.Structure):
        _fields_ = [("base", BASE), ("compteurs", COMPTEURS), ("memoire_processus", ctypes.c_size_t), ("memoire_travail", ctypes.c_size_t),
                    ("pic_processus", ctypes.c_size_t), ("pic_travail", ctypes.c_size_t)]
    return ETENDUE


def lier_a_notre_vie(processus):
    """Windows : rattache le processus Tor à un « objet de travail » réglé sur « tuer à la fermeture » : si le programme disparaît SANS pouvoir se nettoyer
    (gestionnaire des tâches, plantage), Windows arrête Tor avec lui. Sans effet ailleurs, et jamais bloquant (au pire, Tor reste lancé comme avant).
    Renvoie True si le rattachement a réussi."""
    global _TRAVAIL
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        ETENDUE = _structures_travail()
        noyau = ctypes.windll.kernel32
        noyau.CreateJobObjectW.restype = wintypes.HANDLE
        noyau.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        noyau.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        noyau.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        with _VERROU_TRAVAIL:
            if _TRAVAIL is None:
                travail = noyau.CreateJobObjectW(None, None)
                if not travail:
                    return False
                infos = ETENDUE()
                infos.base.options = 0x2000                    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                if not noyau.SetInformationJobObject(travail, 9, ctypes.byref(infos), ctypes.sizeof(infos)):      # 9 : JobObjectExtendedLimitInformation
                    return False
                _TRAVAIL = travail
        return bool(noyau.AssignProcessToJobObject(_TRAVAIL, wintypes.HANDLE(int(processus._handle))))
    except (AttributeError, OSError, ImportError, ValueError, TypeError):
        return False


def lancer(delai=DELAI_LANCEMENT):
    """Lance Tor avec un torrc écrit dans data/tor/ et attend que son port de contrôle réponde. Renvoie detecter().
    Lève TorIntrouvable (programme absent : message avec la marche à suivre) ou TorEchec."""
    global _PROCESSUS, _DERNIERE_ERREUR
    etat = detecter()
    if etat["socks"] and etat["controle"]:
        return etat                                                  # Tor tourne déjà : rien à faire
    executable = trouver_executable()
    if executable is None:
        raise TorIntrouvable("Je n'ai pas trouvé le programme Tor (tor.exe) sur cet ordinateur. Télécharge le « Tor Expert "
                             "Bundle » (lien ci-dessus), décompresse-le, puis place son dossier « tor » à côté de main.py (chemin "
                             "par défaut : tor\\tor.exe), ou indique le chemin de tor.exe dans la Configuration "
                             "(« Partage : chemin de tor.exe »), ou dépose le dossier dans « Téléchargements ».")
    with _VERROU:
        if _PROCESSUS is not None and _PROCESSUS.poll() is None:
            processus = _PROCESSUS
        else:
            dossier = Path(config.DOSSIER_DONNEES) / "tor"
            dossier.mkdir(parents=True, exist_ok=True)
            torrc = dossier / "torrc"
            torrc.write_text(contenu_torrc(dossier / "donnees"), encoding="utf-8")
            options = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}
            try:
                processus = subprocess.Popen([str(executable), "-f", str(torrc)], stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(executable.parent),
                                             **options)
            except OSError as erreur:
                _DERNIERE_ERREUR = f"Tor n'a pas pu être lancé : {erreur}"
                raise TorEchec(_DERNIERE_ERREUR) from erreur
            _PROCESSUS = processus
    journal.logiciel(f"Tor lancé par le programme (pid {processus.pid})")
    lier_a_notre_vie(processus)                                      # (Windows) Tor s'arrête aussi si le programme est tué brutalement (hors du verrou)
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        code = processus.poll()
        if code is not None:
            with _VERROU:
                _PROCESSUS = None
            _DERNIERE_ERREUR = (f"Tor s'est arrêté tout de suite (code {code}). Un autre Tor utilise peut-être déjà les "
                                f"ports {config.P2P_TOR_SOCKS} / {config.P2P_TOR_CONTROLE}, ou le fichier torrc est refusé.")
            raise TorEchec(_DERNIERE_ERREUR)
        etat = detecter()
        if etat["controle"] and etat["socks"]:
            _DERNIERE_ERREUR = None
            return etat
        time.sleep(0.3)
    arreter()
    _DERNIERE_ERREUR = f"Tor n'a pas répondu en {int(delai)} secondes."
    raise TorEchec(_DERNIERE_ERREUR)


def arreter(delai=5):
    """Arrête le Tor lancé par ce programme (jamais un Tor lancé par toi ou par le navigateur Tor). `delai` : secondes d'attente avant de le forcer (2 suffisent
    quand Windows ferme la fenêtre de commandes : il ne laisse qu'environ 5 secondes)."""
    global _PROCESSUS
    with _VERROU:
        processus, _PROCESSUS = _PROCESSUS, None
    if processus is not None and processus.poll() is None:
        processus.terminate()
        try:
            processus.wait(timeout=delai)
        except subprocess.TimeoutExpired:
            processus.kill()
        journal.logiciel("Tor arrêté (il avait été lancé par le programme)")


def etat_pour_page():
    """Ce que la page du Hall affiche à propos de Tor."""
    requis = config.P2P_TRANSPORT == "tor"
    detecte = detecter() if requis else {"socks": None, "controle": None, "navigateur": False}
    executable = trouver_executable() if requis else None
    return {"requis": requis, "detecte": bool(detecte["socks"] and detecte["controle"]), "socks": detecte["socks"],
            "controle": detecte["controle"], "navigateur": detecte["navigateur"],
            "executable": str(executable) if executable else None, "auto": bool(config.P2P_TOR_AUTO),
            "lance_par_nous": lance_par_nous(), "erreur": _DERNIERE_ERREUR, "torrc": torrc_a_copier(),
            "ports_testes": " / ".join(transport.candidats_tor("socks", config.P2P_TOR_SOCKS)
                                       + transport.candidats_tor("controle", config.P2P_TOR_CONTROLE)),
            "url_expert_bundle": URL_EXPERT_BUNDLE, "url_navigateur": URL_NAVIGATEUR}
