"""Le projet WikiFreeCards : son nom, ses liens et sa mention d'auteur.

La mention de bas de page (logiciel sous licence MIT, Copyright (c) 2026 Damballah Oueddo) n'est PAS un réglage : elle ne se modifie pas
dans la Configuration (la licence MIT demande de conserver la mention d'auteur d'origine). Les liens s'ouvrent dans une nouvelle fenêtre.
"""

import html
import re
import secrets
import threading

from . import config

NOM = "WikiFreeCards"
VERSION = "2026.10.25-l"          # affichée dans la fenêtre d'illustration (ligne de diagnostic) : permet de vérifier quelle version tourne
URL_PROJET = "https://github.com/damballah/wikifreecards"
URL_LICENCE = "https://github.com/damballah/wikifreecards/blob/main/LICENSE"
URL_AUTEUR = "https://github.com/damballah"
URL_CC = "https://creativecommons.org/licenses/by-sa/4.0/deed.fr"          # la licence du contenu de Wikipédia
TITRE_CC = "Deed - Attribution - Partage dans les mêmes conditions 4.0 International - Creative Commons"
AUTEUR = "Damballah Oueddo"
ANNEE = 2026

# Un identifiant propre à CE lancement du programme : le message de bienvenue s'affiche une fois par lancement (et par fenêtre de navigateur).
DEMARRAGE = secrets.token_hex(6)

_verrou_accueil = threading.Lock()
_accueil_montre = False


def prendre_accueil():
    """Le message de bienvenue doit-il s'afficher avec CETTE page ? Oui une seule fois par lancement du programme : pour la toute première page affichée
    (quel que soit l'onglet, la fenêtre ou l'appareil), puis plus jamais tant que le programme n'est pas coupé puis relancé."""
    global _accueil_montre
    with _verrou_accueil:
        if _accueil_montre:
            return False
        _accueil_montre = True
        return True


class sans_consommer_accueil:
    """Fabriquer une page qui ne sera PAS vue dans le navigateur (la page de secours écrite au lancement, par exemple) ne doit pas compter comme « la première
    page » : le message de bienvenue reste pour la vraie première page. Usage : `with projet.sans_consommer_accueil(): ...`."""

    def __enter__(self):
        with _verrou_accueil:
            self.avant = _accueil_montre
        return self

    def __exit__(self, *erreur):
        global _accueil_montre
        with _verrou_accueil:
            _accueil_montre = self.avant
        return False


def reinitialiser_accueil():
    """Comme si le programme venait d'être relancé (nouvel identifiant de lancement) : pour les tests."""
    global _accueil_montre, DEMARRAGE
    with _verrou_accueil:
        _accueil_montre = False
        DEMARRAGE = secrets.token_hex(6)


BANNIERE = (
    "#############################\n"
    "######  WikiFreeCards  ######\n"
    "#############################"
)


def lien(adresse, texte, titre=None):
    """Un lien qui s'ouvre dans une NOUVELLE fenêtre (sans donner accès à la page d'origine). `titre` : l'info-bulle (le nom complet de la cible)."""
    info = f' title="{html.escape(titre, quote=True)}"' if titre else ""
    return f'<a href="{html.escape(adresse, quote=True)}" target="_blank" rel="noopener noreferrer"{info}>{html.escape(texte)}</a>'


def url_wikipedia():
    """La page d'accueil de la Wikipédia utilisée (la langue réglée dans la Configuration, « fr » par défaut)."""
    langue = str(getattr(config, "LANGUE", "fr") or "fr")
    return f"https://{langue}.wikipedia.org/" if re.fullmatch(r"[a-z][a-z0-9-]{0,19}", langue) else "https://fr.wikipedia.org/"


def mention_html():
    """La mention de bas de page : texte et liens (Wikipédia, licence CC BY-SA du contenu, WikiFreeCards, licence MIT, nom de l'auteur)."""
    return (f"Gratuit. Contenu encyclopédique issu de {lien(url_wikipedia(), 'Wikipédia')}, sous licence libre ({lien(URL_CC, 'CC BY-SA', TITRE_CC)}). "
            f"{lien(URL_PROJET, NOM)}, logiciel sous {lien(URL_LICENCE, 'licence MIT')}.<br>"
            f"Copyright (c) {ANNEE} {lien(URL_AUTEUR, AUTEUR)}.")


def mention_texte():
    """La même mention en texte simple (sans les liens)."""
    return (f"Gratuit. Contenu encyclopédique issu de Wikipédia, sous licence libre (CC BY-SA). {NOM}, logiciel sous licence MIT.\n"
            f"Copyright (c) {ANNEE} {AUTEUR}.")
