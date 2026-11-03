"""L'icône de l'onglet du navigateur (favicon).

Elle se dépose dans le dossier `ico/` (à côté de main.py) sous le nom « favicon » : `favicon.ico` ou `favicon.png`.
Formats acceptés (le CONTENU du fichier est vérifié, pas seulement son extension) :
  - favicon.ico : 16 × 16 ou 32 × 32 pixels (un fichier .ico peut contenir les deux tailles) ;
  - favicon.png : 32 × 32 pixels.
Si les deux fichiers existent, le .ico est utilisé d'abord (puis le .png si le .ico n'est pas valide). Un fichier qui n'a pas le bon format
est ignoré (le navigateur garde son icône par défaut) : `diagnostic()` dit pourquoi. Le programme ne lit jamais autre chose que ces deux fichiers.
"""

import struct
from urllib.parse import quote

from . import config

NOM = "favicon"
TYPES = {".ico": "image/x-icon", ".png": "image/png"}
TAILLES_ICO = {(16, 16), (32, 32)}
TAILLE_PNG = (32, 32)
TAILLE_MAX = 256 * 1024                    # un favicon est minuscule : au-delà, ce n'en est pas un


def dossier():
    return config.DOSSIER_ICO


def verifier_png(octets):
    """None si c'est un PNG valide de 32 × 32 pixels, sinon la raison du refus."""
    if len(octets) < 33 or octets[:8] != b"\x89PNG\r\n\x1a\n" or octets[12:16] != b"IHDR":
        return "ce n'est pas une image PNG"
    largeur, hauteur = struct.unpack(">II", octets[16:24])
    if (largeur, hauteur) != TAILLE_PNG:
        return f"le PNG doit faire 32 × 32 pixels (celui-ci fait {largeur} × {hauteur})"
    return None


def verifier_ico(octets):
    """None si c'est un fichier ICO valide dont toutes les images font 16 × 16 ou 32 × 32 pixels, sinon la raison du refus."""
    if len(octets) < 22 or octets[:4] != b"\x00\x00\x01\x00":
        return "ce n'est pas un fichier .ico"
    nombre = struct.unpack("<H", octets[4:6])[0]
    if not 1 <= nombre <= 16 or len(octets) < 6 + 16 * nombre:
        return "fichier .ico abîmé"
    for i in range(nombre):
        entree = octets[6 + 16 * i:22 + 16 * i]
        largeur, hauteur = entree[0] or 256, entree[1] or 256        # (0 signifie 256)
        taille, decalage = struct.unpack("<II", entree[8:16])
        if (largeur, hauteur) not in TAILLES_ICO:
            return f"le .ico doit contenir des images de 16 × 16 ou 32 × 32 pixels (celui-ci : {largeur} × {hauteur})"
        if decalage < 6 + 16 * nombre or taille == 0 or decalage + taille > len(octets):
            return "fichier .ico abîmé"
    return None


def _candidats():
    """Les fichiers favicon.ico / favicon.png du dossier (casse ignorée), .ico d'abord : [(chemin, extension)]."""
    d = dossier()
    if not d.is_dir():
        return []
    par_ext = {}
    for f in d.iterdir():
        if f.is_file() and not f.is_symlink() and f.stem.lower() == NOM and f.suffix.lower() in TYPES:
            par_ext.setdefault(f.suffix.lower(), f)
    return [(par_ext[e], e) for e in (".ico", ".png") if e in par_ext]


def _lire(chemin, extension):
    """(octets, raison du refus ou None)."""
    try:
        if chemin.stat().st_size > TAILLE_MAX:
            return None, f"le fichier est trop volumineux (plus de {TAILLE_MAX // 1024} Ko)"
        octets = chemin.read_bytes()
    except OSError as erreur:
        return None, f"fichier illisible ({erreur})"
    raison = verifier_ico(octets) if extension == ".ico" else verifier_png(octets)
    return (octets if raison is None else None), raison


def trouver():
    """(octets, type MIME, chemin) du favicon valide, ou None."""
    for chemin, extension in _candidats():
        octets, raison = _lire(chemin, extension)
        if octets is not None:
            return octets, TYPES[extension], chemin
    return None


def diagnostic():
    """Une phrase pour le lancement du programme : l'icône utilisée, ou pourquoi aucune ne l'est."""
    candidats = _candidats()
    if not candidats:
        return "Pas de favicon : dépose favicon.ico (16×16 ou 32×32) ou favicon.png (32×32) dans le dossier ico/."
    refus = []
    for chemin, extension in candidats:
        octets, raison = _lire(chemin, extension)
        if octets is not None:
            return f"Favicon : {chemin.parent.name}/{chemin.name}"
        refus.append(f"{chemin.name} ignoré : {raison}")
    return "Favicon non utilisé — " + " ; ".join(refus)


def lien_html(relatif=False):
    """La balise <link rel="icon"> à mettre dans le <head> des pages, ou "" s'il n'y a pas de favicon valide.
    `relatif` : pour la page de secours ouverte sans le programme (le fichier se lit dans ../ico/)."""
    trouve = trouver()
    if trouve is None:
        return ""
    octets, mime, chemin = trouve
    if relatif:
        adresse = "../" + dossier().name + "/" + quote(chemin.name)
    else:
        try:
            adresse = "/favicon?v=" + str(chemin.stat().st_mtime_ns)          # (change quand on remplace le fichier : le navigateur le recharge)
        except OSError:
            adresse = "/favicon"
    taille = ' sizes="32x32"' if mime == "image/png" else ""
    return f'<link rel="icon" type="{mime}"{taille} href="{adresse}">\n'
