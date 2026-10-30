"""La fermeture du programme : que Tor (s'il a été lancé PAR le programme) se ferme avec lui.

Trois cas :
  - Ctrl+C : Python lève KeyboardInterrupt, la sortie de `serveur.servir` arrête Tor (déjà prévu) ;
  - la CROIX de la fenêtre de commandes (Windows : événement « CTRL_CLOSE_EVENT », fermeture de session, arrêt de l'ordinateur) ou un signal SIGTERM / SIGHUP
    (Linux, macOS) : Python ne passe pas par `finally`, le programme est coupé sans prévenir. On installe donc un gestionnaire qui arrête Tor avant ;
  - arrêt BRUTAL (gestionnaire des tâches, plantage) : aucun code ne peut s'exécuter. Sous Windows, Tor est donc rattaché à un « objet de travail » qui le tue
    quand le programme disparaît (voir p2p_tor.lier_a_notre_vie).

Seul le Tor lancé par ce programme est arrêté : un Tor lancé par toi, par le navigateur Tor ou par un autre programme n'est jamais touché.
"""

import atexit
import os
import signal
import threading

CTRL_C, CTRL_BREAK, CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN = 0, 1, 2, 5, 6
_installe = False
_gestionnaire_windows = None          # (doit rester référencé : Windows garde un pointeur dessus)
_verrou = threading.Lock()


def _nettoyer_une_fois(nettoyer):
    """Appelle `nettoyer` une seule fois, même si plusieurs voies de fermeture se déclenchent."""
    def appel():
        with _verrou:
            if getattr(appel, "fait", False):
                return
            appel.fait = True
        try:
            nettoyer()
        except Exception:                                     # (en fermeture, on ne s'arrête jamais sur une erreur)
            pass
    return appel


def evenement_windows(evenement, nettoyer):
    """Ce que fait le gestionnaire de la console Windows : Ctrl+C est laissé à Python (KeyboardInterrupt, déjà géré) ; la croix, Ctrl+Pause, la fermeture de
    session et l'arrêt de l'ordinateur arrêtent Tor tout de suite. Renvoie False : le comportement normal de Windows (fermer le programme) suit."""
    if evenement in (CTRL_BREAK, CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN):
        nettoyer()
    return False


def installer(nettoyer):
    """Branche `nettoyer` (arrêt de Tor et du partage) sur toutes les façons de fermer le programme. À appeler une fois, depuis le fil principal."""
    global _installe, _gestionnaire_windows
    if _installe:
        return False
    _installe = True
    unique = _nettoyer_une_fois(nettoyer)
    atexit.register(unique)                                   # sortie normale, sys.exit, exception non rattrapée
    if os.name == "nt":
        try:
            import ctypes
            prototype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint32)
            _gestionnaire_windows = prototype(lambda evenement: 1 if evenement_windows(evenement, unique) else 0)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_gestionnaire_windows, True)
        except (AttributeError, OSError, ImportError):
            pass
    else:
        def arret(numero, cadre):
            unique()
            raise KeyboardInterrupt                           # même sortie propre que Ctrl+C (le fil principal sort de serve_forever)
        for nom in ("SIGTERM", "SIGHUP"):
            numero = getattr(signal, nom, None)
            if numero is not None:
                try:
                    signal.signal(numero, arret)
                except (ValueError, OSError):                 # (pas dans le fil principal)
                    pass
    return True
