"""Lancement du programme dans le navigateur.

Par défaut : le navigateur habituel (webbrowser). Avec le réglage « Lancer dans une fenêtre d'application » : une fenêtre à part
d'Edge ou de Chrome, avec son PROFIL à elle (dossier data/navigateur) et l'autorisation de lire du son sans clic préalable : la
musique d'ambiance peut alors démarrer toute seule au lancement. Sans Edge ni Chrome, ou si le lancement échoue, le navigateur
habituel est utilisé.
"""

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path

from . import config


def candidats():
    """Les exécutables Edge / Chrome possibles, dans l'ordre de préférence (chemins Windows, macOS, Linux, puis le PATH)."""
    dossiers = [os.environ.get(v) for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    liste = []
    for dossier in dossiers:
        if dossier:
            liste += [Path(dossier) / "Microsoft/Edge/Application/msedge.exe", Path(dossier) / "Google/Chrome/Application/chrome.exe"]
    liste += [Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
              Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    for nom in ("microsoft-edge", "msedge", "google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"):
        trouve = shutil.which(nom)
        if trouve:
            liste.append(Path(trouve))
    return liste


def trouver_navigateur():
    """Le premier Edge ou Chrome installé (chemin), ou None."""
    for chemin in candidats():
        try:
            if chemin.is_file():
                return chemin
        except OSError:
            continue
    return None


def commande(url, navigateur):
    """La ligne de commande d'une fenêtre d'application : profil à part, son autorisé, pas de bandeau de première utilisation."""
    profil = Path(config.DOSSIER_DONNEES) / "navigateur"
    return [str(navigateur), f"--app={url}", f"--user-data-dir={profil}", "--autoplay-policy=no-user-gesture-required",
            "--no-first-run", "--no-default-browser-check"]


def ouvrir(url):
    """Ouvre l'adresse dans le navigateur : une fenêtre d'application si le réglage est actif et qu'Edge/Chrome existe, sinon
    le navigateur habituel. Renvoie "application" ou "navigateur"."""
    if config.FENETRE_APPLICATION:
        navigateur = trouver_navigateur()
        if navigateur is not None:
            try:
                (Path(config.DOSSIER_DONNEES) / "navigateur").mkdir(parents=True, exist_ok=True)
                subprocess.Popen(commande(url, navigateur), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return "application"
            except (OSError, subprocess.SubprocessError):
                pass
    webbrowser.open(url)
    return "navigateur"
