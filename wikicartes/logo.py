"""Le logo du jeu : choix du fichier dans le dossier logo/, et adresse pour l'afficher.

Le réglage LOGO_FICHIER dit quel fichier utiliser :
- "auto"  : le fichier nommé « logo » du dossier logo/ (logo.png, logo.jpg, logo.webp...) ;
- "aucun" : pas de logo (le booster affiche alors son texte) ;
- un nom de fichier du dossier logo/, par exemple "mon-logo.png".
"""

import re

from . import config

# Formats acceptés, avec leur type MIME. Pour le mode « auto », si plusieurs fichiers « logo »
# existent, le premier de cette liste est utilisé.
TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
    ".avif": "image/avif",
}
TAILLE_MAX = 30 * 1024 * 1024
AUTO = "auto"
AUCUN = "aucun"

# Nom de fichier simple : lettres (accents compris), chiffres, espace, point, tiret, souligné,
# parenthèses. Jamais de séparateur de dossier : on ne peut pas sortir du dossier logo/.
_NOM = re.compile(r"[\w .()\-]{1,80}")


def nom_valide(nom):
    """Un nom de fichier utilisable pour LOGO_FICHIER (le fichier n'a pas besoin d'exister)."""
    if not isinstance(nom, str) or not _NOM.fullmatch(nom) or nom.startswith(".") or nom != nom.strip():
        return False
    extension = "." + nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
    return extension in TYPES


def choix_valide(valeur):
    """Valeur acceptée pour LOGO_FICHIER : "auto", "aucun" ou un nom de fichier valide."""
    return valeur in (AUTO, AUCUN) or nom_valide(valeur)


def lister():
    """Les images du dossier logo/ (noms de fichiers), dans l'ordre alphabétique."""
    dossier = config.DOSSIER_LOGO
    if not dossier.is_dir():
        return []
    return sorted((f.name for f in dossier.iterdir() if f.is_file() and nom_valide(f.name)),
                  key=str.lower)


def _automatique():
    """Le fichier logo/logo.<extension> (le premier selon l'ordre de priorité des formats)."""
    dossier = config.DOSSIER_LOGO
    if not dossier.is_dir():
        return None
    candidats = {}
    for fichier in sorted(dossier.iterdir()):
        if (fichier.is_file() and fichier.stem.lower() == "logo"
                and fichier.suffix.lower() in TYPES):
            candidats.setdefault(fichier.suffix.lower(), fichier)
    for extension in TYPES:
        if extension in candidats:
            return candidats[extension]
    return None


def trouver(choix=None):
    """Chemin du fichier logo correspondant au réglage (`choix`, par défaut LOGO_FICHIER),
    ou None s'il n'y a pas de logo (réglage « aucun », fichier absent...)."""
    choix = AUTO if choix is None else choix                 # le logo : toujours le fichier « logo.* » du dossier logo/ (plus de réglage)
    if choix == AUCUN or not choix_valide(choix):
        return None
    if choix == AUTO:
        return _automatique()
    dossier = config.DOSSIER_LOGO
    fichier = dossier / choix
    try:
        if fichier.is_file() and fichier.resolve().parent == dossier.resolve():
            return fichier
    except OSError:
        pass
    return None


def source():
    """Adresse de l'image du logo pour les pages servies par le serveur local, ou None."""
    return "/logo" if trouver() is not None else None


def options():
    """Les choix proposés dans la page Configuration : {valeur: libellé}."""
    choix = {AUTO: "Détection automatique (fichier nommé logo.*)", AUCUN: "Aucun logo"}
    for nom in lister():
        choix[nom] = nom
    return choix
