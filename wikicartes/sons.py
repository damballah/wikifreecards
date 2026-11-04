"""Sons et musique : les fichiers audio du dossier sons/ (effets des événements et musique d'ambiance).

Les fichiers se déposent dans le dossier `sons/` à côté de main.py, ou se téléversent depuis la Configuration (section « Sons et
musique »). Seuls les formats audio courants sont acceptés (mp3, ogg, opus, wav, m4a, aac, flac, webm), et le CONTENU du fichier
est vérifié (on ne se fie pas à l'extension) : un fichier qui n'est pas un son est refusé. Le programme ne lit jamais un fichier
hors de ce dossier : un son se désigne par son nom simple, jamais par un chemin.
"""

import re
from pathlib import Path

from . import config

TYPES = {
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav",
    ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac", ".webm": "audio/webm",
}
TAILLE_MAX = 60 * 1024 * 1024            # 60 Mo par fichier (une musique d'ambiance peut être longue)
NB_MAX = 200                             # nombre de fichiers du dossier pris en compte

_SUFFIXES = "|".join(re.escape(e[1:]) for e in TYPES)
NOM_SUR = re.compile(rf"[A-Za-z0-9À-ÿ][A-Za-z0-9À-ÿ ._()'-]{{0,100}}\.(?:{_SUFFIXES})", re.IGNORECASE)

# Les événements qui peuvent jouer un son, dans l'ordre de la Configuration : nom du réglage -> clé utilisée par la page
EVENEMENTS = {
    "SON_EFFET_PAQUET": "effet",
    "SON_OUVERTURE": "ouverture",
    "SON_CARTE_FENETRE": "carte",
    "SON_ARRIVEE": "arrivee",
    "SON_CORBEILLE": "corbeille",
    "SON_RESTAURATION": "restauration",
    "SON_SUPPRESSION": "suppression",
    "SON_RETRAIT": "retrait",
}


def dossier():
    return Path(config.DOSSIER_SONS)


def nom_valide(nom):
    """Un nom de fichier son simple et sûr : jamais de chemin, de séparateur ou de « .. »."""
    return isinstance(nom, str) and NOM_SUR.fullmatch(nom) is not None and ".." not in nom


def lister():
    """Les noms des fichiers sons du dossier (valides, triés sans tenir compte de la casse)."""
    d = dossier()
    if not d.is_dir():
        return []
    noms = [f.name for f in d.iterdir() if f.is_file() and not f.is_symlink() and nom_valide(f.name)
            and f.suffix.lower() in TYPES]
    return sorted(noms, key=str.casefold)[:NB_MAX]


def chemin(nom):
    """Le fichier d'un son (ou None s'il n'existe pas ou si le nom est suspect)."""
    if not nom_valide(nom):
        return None
    fichier = dossier() / nom
    if not fichier.is_file() or fichier.is_symlink() or fichier.suffix.lower() not in TYPES:
        return None
    try:
        if fichier.resolve().parent != dossier().resolve():
            return None
    except OSError:
        return None
    return fichier


def type_mime(nom):
    return TYPES.get(Path(nom).suffix.lower(), "application/octet-stream")


def _famille(octets):
    """La famille audio reconnue d'après les premiers octets : mp3, ogg, wav, flac, mp4, webm, aac — ou None."""
    t = bytes(octets[:16])
    if t[:3] == b"ID3":
        return "mp3"
    if t[:4] == b"OggS":
        return "ogg"
    if t[:4] == b"RIFF" and t[8:12] == b"WAVE":
        return "wav"
    if t[:4] == b"fLaC":
        return "flac"
    if t[4:8] == b"ftyp":
        return "mp4"
    if t[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    if len(t) >= 2 and t[0] == 0xFF and (t[1] & 0xE0) == 0xE0:       # synchronisation MPEG audio ou AAC (ADTS)
        couche = (t[1] >> 1) & 0x03                                  # 00 : AAC ; 01, 10, 11 : mp3 (et mp2, mp1)
        return "aac" if couche == 0 else "mp3"
    return None


_FAMILLES_PAR_EXTENSION = {".mp3": ("mp3",), ".ogg": ("ogg",), ".oga": ("ogg",), ".opus": ("ogg",), ".wav": ("wav",),
                           ".m4a": ("mp4",), ".aac": ("aac", "mp4"), ".flac": ("flac",), ".webm": ("webm",)}


class SonRefuse(ValueError):
    """Fichier son refusé (message lisible)."""


def nom_propre(nom_original):
    """Un nom sûr tiré du nom envoyé : sans chemin, caractères douteux remplacés par « - »."""
    nom = str(nom_original or "").replace("\\", "/").split("/")[-1].strip()
    suffixe = Path(nom).suffix.lower()
    racine_nom = nom[:len(nom) - len(suffixe)] if suffixe else nom
    racine_nom = re.sub(r"[^A-Za-z0-9À-ÿ ._()'-]+", "-", racine_nom).strip(" .-_")[:80] or "son"
    racine_nom = racine_nom.replace("..", ".")
    return racine_nom + suffixe


def enregistrer(nom_original, octets):
    """Range un son téléversé dans le dossier sons/ : extension audio connue, taille raisonnable, contenu vérifié. Renvoie le
    nom du fichier (suffixé -2, -3... si un autre fichier du même nom existe déjà)."""
    nom = nom_propre(nom_original)
    suffixe = Path(nom).suffix.lower()
    if suffixe not in TYPES:
        raise SonRefuse("format non accepté : mp3, ogg, opus, wav, m4a, aac, flac ou webm")
    if not isinstance(octets, (bytes, bytearray)) or len(octets) < 64:
        raise SonRefuse("fichier vide ou trop court")
    if len(octets) > TAILLE_MAX:
        raise SonRefuse(f"fichier trop lourd ({len(octets) / 1024 / 1024:.0f} Mo ; {TAILLE_MAX // 1024 // 1024} Mo au maximum)")
    if _famille(octets) not in _FAMILLES_PAR_EXTENSION[suffixe]:
        raise SonRefuse("ce fichier n'est pas un son valide (son contenu ne correspond pas à son extension)")
    if not nom_valide(nom):
        raise SonRefuse("nom de fichier invalide")
    d = dossier()
    d.mkdir(parents=True, exist_ok=True)
    if len(lister()) >= NB_MAX and not (d / nom).exists():
        raise SonRefuse(f"trop de fichiers dans le dossier sons ({NB_MAX} au maximum)")
    cible, n = d / nom, 1
    while cible.exists():
        if cible.read_bytes() == bytes(octets):
            return cible.name                          # le même fichier est déjà là
        n += 1
        cible = d / f"{Path(nom).stem}-{n}{suffixe}"
    cible.write_bytes(bytes(octets))
    return cible.name


def supprimer(nom):
    """Supprime un son du dossier. Renvoie True si le fichier existait."""
    fichier = chemin(nom)
    if fichier is None:
        return False
    fichier.unlink()
    return True
