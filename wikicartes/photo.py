"""La photo de profil (page de profil) : une image RONDE, choisie parmi les images des cartes de la collection ou envoyée depuis l'ordinateur, avec un positionnement
(zoom et déplacement) réglé au moment du choix.

- Le fichier est rangé dans le dossier `profil/` (à la racine du projet), nommé « profile » + l'extension de l'image : profile.jpg, profile.png, profile.bmp, profile.webp...
  Tout format que le navigateur sait afficher est accepté (png, jpg, gif, webp, bmp, avif, svg, ico). On peut aussi y déposer soi-même un fichier « profile.<extension> ».
- Une image prise sur une carte est TÉLÉCHARGÉE dans ce dossier : si la carte est supprimée ensuite, la photo reste, tant qu'on ne la supprime pas ou ne la change pas.
- Pendant le choix, l'image est mise de côté dans `_apercu.<extension>` : l'ancienne photo n'est remplacée qu'au moment d'ENREGISTRER (annuler ne change rien).
- Le positionnement (zoom de 1 à 4, point de vue x et y de 0 à 100) est gardé à part : l'image elle-même n'est jamais recadrée, on peut donc la repositionner à tout moment.
"""

import html as _html
import os
import re
import struct
import threading
from pathlib import Path

import requests

from . import api, config, images, journal

NOM = "profile"
APERCU = "_apercu"
PARTAGE = "profile_partage"            # la version PARTAGÉE avec le Hall : le carré visible dans le cercle (320 × 320), fabriqué par le navigateur à l'enregistrement
PARTAGE_MAX = 400 * 1024
PARTAGE_COTE = (64, 1024)
PARTAGE_FORMATS = ("png", "jpg", "webp")
TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".jfif": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".bmp": "image/bmp", ".avif": "image/avif", ".ico": "image/x-icon",
}
EXTENSIONS_SURES = ("png", "jpg", "gif", "webp", "bmp", "avif", "svg", "ico")
TAILLE_MAX = 15 * 1024 * 1024
TAILLE_SVG_MAX = 2 * 1024 * 1024
PIXELS_MAX = 60_000_000
ZOOM_MIN, ZOOM_MAX = 1.0, 4.0
RATIO_MIN, RATIO_MAX = 0.05, 20.0
_VERROU = threading.Lock()
_DANGEREUX_SVG = re.compile(rb"<\s*script|<\s*foreignObject|\bon[a-z]+\s*=|javascript\s*:", re.I)


class PhotoRefusee(ValueError):
    """L'image n'est pas acceptable (message lisible par l'utilisateur)."""


# ---------------------------------------------------------------------------------------------------------------------- reconnaître une image

def type_image(octets):
    """L'extension d'après le CONTENU du fichier (jamais d'après son nom) : png, jpg, gif, webp, bmp, avif, svg ou ico ; None sinon."""
    octets = bytes(octets[:4096])
    if octets[:3] == b"\xff\xd8\xff":
        return "jpg"
    if octets[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if octets[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
        return "webp"
    if octets[:2] == b"BM" and len(octets) >= 26 and struct.unpack("<I", octets[14:18])[0] in (12, 40, 52, 56, 64, 108, 124):
        return "bmp"
    if octets[:4] == b"\x00\x00\x01\x00" and len(octets) >= 22 and struct.unpack("<H", octets[4:6])[0] >= 1:
        return "ico"
    if octets[4:8] == b"ftyp" and octets[8:12] in (b"avif", b"avis"):
        return "avif"
    texte = octets.lstrip(b"\xef\xbb\xbf \t\r\n")
    if (texte[:5] == b"<?xml" or texte[:4] == b"<svg" or texte[:9].lower() == b"<!doctype") and b"<svg" in octets.lower():
        return "svg"
    return None


def dimensions(octets, ext=None):
    """(largeur, hauteur) en pixels lue dans l'en-tête, ou None (le navigateur donnera alors les vraies dimensions)."""
    octets = bytes(octets[:262144])
    ext = ext or type_image(octets)
    try:
        if ext in ("png", "jpg"):
            return images.dimensions(octets)
        if ext == "gif" and len(octets) >= 10:
            return struct.unpack("<HH", octets[6:10])
        if ext == "bmp" and len(octets) >= 26:
            largeur, hauteur = struct.unpack("<ii", octets[18:26])
            return abs(largeur), abs(hauteur)
        if ext == "ico" and len(octets) >= 8:
            return (octets[6] or 256), (octets[7] or 256)
        if ext == "webp" and len(octets) >= 30:
            fourcc = octets[12:16]
            if fourcc == b"VP8X":
                return 1 + int.from_bytes(octets[24:27], "little"), 1 + int.from_bytes(octets[27:30], "little")
            if fourcc == b"VP8L" and octets[20] == 0x2F:
                bits = int.from_bytes(octets[21:25], "little")
                return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
            if fourcc == b"VP8 " and octets[23:26] == b"\x9d\x01\x2a":
                return struct.unpack("<H", octets[26:28])[0] & 0x3FFF, struct.unpack("<H", octets[28:30])[0] & 0x3FFF
        if ext == "svg":
            texte = octets[:4096].decode("utf-8", "ignore")
            m = re.search(r"viewBox\s*=\s*[\"']\s*[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)", texte)
            if m and float(m.group(1)) > 0 and float(m.group(2)) > 0:
                return float(m.group(1)), float(m.group(2))
            l, h = re.search(r"\bwidth\s*=\s*[\"']([\d.]+)", texte), re.search(r"\bheight\s*=\s*[\"']([\d.]+)", texte)
            if l and h and float(l.group(1)) > 0 and float(h.group(1)) > 0:
                return float(l.group(1)), float(h.group(1))
    except (struct.error, ValueError, IndexError):
        pass
    return None


def verifier(octets):
    """Contrôle une image avant de la garder : (extension, dimensions ou None). Lève PhotoRefusee avec un message clair."""
    if not octets:
        raise PhotoRefusee("le fichier est vide")
    if len(octets) > TAILLE_MAX:
        raise PhotoRefusee(f"l'image est trop lourde ({len(octets) / 1048576:.1f} Mo ; {TAILLE_MAX // 1048576} Mo au maximum)")
    ext = type_image(octets)
    if ext is None:
        raise PhotoRefusee("ce n'est pas une image que le navigateur sait afficher (png, jpg, gif, webp, bmp, avif, svg ou ico)")
    if ext == "svg":
        if len(octets) > TAILLE_SVG_MAX:
            raise PhotoRefusee("le dessin SVG est trop lourd (2 Mo au maximum)")
        if _DANGEREUX_SVG.search(octets):
            raise PhotoRefusee("ce dessin SVG contient du code actif (script) : refusé par sécurité")
    dims = dimensions(octets, ext)
    if dims and (dims[0] <= 0 or dims[1] <= 0):
        raise PhotoRefusee("image invalide (dimensions nulles)")
    if dims and ext != "svg" and dims[0] * dims[1] > PIXELS_MAX:
        raise PhotoRefusee(f"l'image est trop grande ({int(dims[0])} × {int(dims[1])} pixels)")
    return ext, dims


# ---------------------------------------------------------------------------------------------------------------------- le dossier profil/

def dossier():
    return Path(config.DOSSIER_PROFIL)


def _trouver(prefixe):
    """Le fichier « <prefixe>.<extension> » du dossier profil/ (le plus récent s'il y en a plusieurs), ou None. Jamais un lien symbolique ni un dossier."""
    try:
        candidats = [f for f in dossier().iterdir()
                     if f.is_file() and not f.is_symlink() and f.stem.lower() == prefixe and f.suffix.lower() in TYPES and 0 < f.stat().st_size <= TAILLE_MAX]
    except OSError:
        return None
    return max(candidats, key=lambda f: f.stat().st_mtime_ns) if candidats else None


def trouver():
    """La photo de profil actuelle (profile.<extension>), ou None."""
    return _trouver(NOM)


def trouver_apercu():
    """L'image mise de côté pendant le choix (_apercu.<extension>), ou None."""
    return _trouver(APERCU)


def type_mime(fichier):
    return TYPES.get(Path(fichier).suffix.lower(), "application/octet-stream")


def _effacer(prefixe):
    try:
        for f in dossier().iterdir():
            if f.is_file() and f.stem.lower() == prefixe and f.suffix.lower() in TYPES:
                f.unlink()
    except OSError:
        pass


def mettre_de_cote(octets):
    """Garde l'image choisie dans _apercu.<extension> en attendant l'enregistrement (l'ancienne photo n'est pas touchée). Renvoie ses informations."""
    ext, dims = verifier(octets)
    with _VERROU:
        dossier().mkdir(parents=True, exist_ok=True)
        _effacer(APERCU)
        cible = dossier() / f"{APERCU}.{ext}"
        partiel = cible.with_name(cible.name + ".partiel")
        partiel.write_bytes(octets)
        os.replace(partiel, cible)
    return _infos(cible, ext, dims)


def _infos(fichier, ext, dims):
    ratio = (dims[0] / dims[1]) if dims and dims[1] else None
    return {"ext": ext, "largeur": None if not dims else round(dims[0]), "hauteur": None if not dims else round(dims[1]), "ratio": None if ratio is None else round(ratio, 5),
            "taille": fichier.stat().st_size, "version": fichier.stat().st_mtime_ns}


def installer_depuis(fichier):
    """Installe un fichier image comme photo de profil (restauration d'une sauvegarde) : contrôlé, rangé en profile.<extension>, l'ancienne photo effacée."""
    octets = Path(fichier).read_bytes()
    ext, _ = verifier(octets)
    with _VERROU:
        dossier().mkdir(parents=True, exist_ok=True)
        _effacer(NOM)
        cible = dossier() / f"{NOM}.{ext}"
        partiel = cible.with_name(cible.name + ".partiel")
        partiel.write_bytes(octets)
        os.replace(partiel, cible)
    return cible


# ---------------------------------------------------------------------------------------------------------------------- la version partagée (Hall des collections)

def trouver_partage():
    return _trouver(PARTAGE)


def signature_actuelle(conn):
    """Ce qui décide si la version partagée est à jour : la photo (sa date de modification) et son positionnement."""
    r = reglages(conn)
    return f"{r['version']}|{r['zoom']:g}|{r['x']:g}|{r['y']:g}|{r['ratio']:.5f}"


def partage_a_jour(conn):
    """La version partagée existe-t-elle et correspond-elle à la photo et au positionnement actuels ?"""
    from . import parametres
    return trouver() is not None and trouver_partage() is not None and parametres.lire_preference(conn, "profil.photo_partagee", "") == signature_actuelle(conn)


def enregistrer_partage(conn, octets):
    """Garde la version partagée de la photo (le carré visible dans le cercle, fabriqué par le navigateur) : png, jpg ou webp, 400 Ko au plus, de 64 à 1024 pixels de côté.
    Les visiteurs du Hall ne voient JAMAIS l'image d'origine, seulement ce carré. Lève PhotoRefusee."""
    from . import parametres
    if trouver() is None:
        raise PhotoRefusee("il n'y a pas de photo de profil")
    if not octets or len(octets) > PARTAGE_MAX:
        raise PhotoRefusee(f"la version partagée est vide ou trop lourde ({PARTAGE_MAX // 1024} Ko au maximum)")
    ext = type_image(octets)
    if ext not in PARTAGE_FORMATS:
        raise PhotoRefusee("la version partagée doit être une image png, jpg ou webp")
    dims = dimensions(octets, ext)
    if not dims or not (PARTAGE_COTE[0] <= dims[0] <= PARTAGE_COTE[1] and PARTAGE_COTE[0] <= dims[1] <= PARTAGE_COTE[1]):
        raise PhotoRefusee(f"dimensions refusées (de {PARTAGE_COTE[0]} à {PARTAGE_COTE[1]} pixels de côté)")
    with _VERROU:
        _effacer(PARTAGE)
        cible = dossier() / f"{PARTAGE}.{ext}"
        partiel = cible.with_name(cible.name + ".partiel")
        partiel.write_bytes(octets)
        os.replace(partiel, cible)
    parametres.ecrire(conn, "profil.photo_partagee", signature_actuelle(conn))
    journal.logiciel(f"Photo de profil : version partagée avec le Hall enregistrée ({len(octets) // 1024} Ko, {int(dims[0])}×{int(dims[1])})")


def partage_pour_le_hall():
    """(octets, type MIME, empreinte) de la version partagée, ou None s'il n'y en a pas (ou si la photo a disparu depuis)."""
    import hashlib
    fichier = trouver_partage()
    if fichier is None or trouver() is None:
        return None
    try:
        octets = fichier.read_bytes()
    except OSError:
        return None
    if type_image(octets) not in PARTAGE_FORMATS or len(octets) > PARTAGE_MAX:
        return None
    return octets, type_mime(fichier), hashlib.sha256(octets).hexdigest()[:16]


def abandonner():
    """Le choix est annulé : l'image mise de côté est effacée."""
    with _VERROU:
        _effacer(APERCU)


def purger_apercu_ancien(age_secondes=86400):
    """Au lancement : une image mise de côté et jamais enregistrée (page fermée en cours de choix) est effacée après un jour."""
    import time
    f = trouver_apercu()
    try:
        if f is not None and time.time() - f.stat().st_mtime > age_secondes:
            f.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------------------------- depuis une carte de la collection

def octets_de_carte(carte):
    """L'image d'une carte, en octets : le fichier local d'une carte créée à la main, ou l'image de l'article téléchargée sur Wikimedia (l'originale, sinon la
    miniature si l'originale est trop lourde ou ne vient pas). Lève PhotoRefusee."""
    derniere = None
    for adresse in (carte.get("image"), carte.get("miniature")):
        if not isinstance(adresse, str) or adresse in ("", "no-image"):
            continue
        try:
            if images.adresse_locale_valide(adresse):
                fichier = images.chemin(images.nom_depuis_adresse(adresse))
                if fichier is None:
                    continue
                octets = fichier.read_bytes()
            elif api.adresse_wikimedia(adresse):
                octets = api.telecharger(adresse, TAILLE_MAX)
            else:
                continue
            verifier(octets)
            return octets
        except PhotoRefusee as erreur:
            derniere = erreur
        except (OSError, requests.RequestException, ValueError) as erreur:
            derniere = PhotoRefusee(f"l'image de cette carte n'a pas pu être récupérée ({erreur})")
    raise derniere or PhotoRefusee("cette carte n'a pas d'image")


# ---------------------------------------------------------------------------------------------------------------------- positionnement et enregistrement

def cadrage_valide(zoom, x, y, ratio=None):
    """Le positionnement après vérification : (zoom, x, y, ratio). Lève PhotoRefusee s'il est invalide."""
    def nombre(v, mini, maxi, nom):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not (mini <= float(v) <= maxi):
            raise PhotoRefusee(f"positionnement invalide ({nom})")
        return float(v)
    z, px, py = nombre(zoom, ZOOM_MIN, ZOOM_MAX, "zoom"), nombre(x, 0, 100, "x"), nombre(y, 0, 100, "y")
    r = None if ratio is None else nombre(ratio, RATIO_MIN, RATIO_MAX, "ratio")
    return round(z, 3), round(px, 2), round(py, 2), None if r is None else round(r, 5)


def style(zoom, x, y, ratio):
    """Le CSS de l'image dans le cercle : l'image COUVRE le cercle (zoom 1), grandit avec le zoom, et se déplace selon x et y (0-100, 50 = centre). Les mêmes calculs sont
    dans static/photo.js (éditeur)."""
    ratio = ratio if ratio and RATIO_MIN <= ratio <= RATIO_MAX else 1.0
    largeur = (ratio if ratio >= 1 else 1.0) * zoom * 100.0
    hauteur = (1.0 if ratio >= 1 else 1.0 / ratio) * zoom * 100.0
    gauche, haut = (100.0 - largeur) * x / 100.0 + 0.0, (100.0 - hauteur) * y / 100.0 + 0.0          # (+ 0.0 : jamais de « -0.000% »)
    return f"width:{largeur:.3f}%;height:{hauteur:.3f}%;left:{gauche:.3f}%;top:{haut:.3f}%"


def reglages(conn):
    """L'état de la photo : existe, positionnement, ratio (lu dans le fichier, sinon celui enregistré), version (pour recharger l'image)."""
    from . import parametres
    fichier = trouver()
    z = parametres.lire_preference(conn, "profil.photo_zoom", 1.0)
    x = parametres.lire_preference(conn, "profil.photo_x", 50.0)
    y = parametres.lire_preference(conn, "profil.photo_y", 50.0)
    ratio = parametres.lire_preference(conn, "profil.photo_ratio", 1.0)
    if fichier is not None:
        try:
            with open(fichier, "rb") as f:
                tete = f.read(262144)
            dims = dimensions(tete, type_image(tete))
        except OSError:
            dims = None
        if dims and dims[1]:
            ratio = dims[0] / dims[1]
    return {"existe": fichier is not None, "nom": None if fichier is None else fichier.name, "zoom": float(z), "x": float(x), "y": float(y), "ratio": float(ratio),
            "version": 0 if fichier is None else fichier.stat().st_mtime_ns}


def _ecrire_reglages(conn, zoom, x, y, ratio):
    from . import parametres
    parametres.ecrire(conn, "profil.photo_zoom", zoom)
    parametres.ecrire(conn, "profil.photo_x", x)
    parametres.ecrire(conn, "profil.photo_y", y)
    if ratio is not None:
        parametres.ecrire(conn, "profil.photo_ratio", ratio)


def enregistrer(conn, zoom, x, y, ratio=None):
    """Garde l'image mise de côté comme photo de profil (profile.<extension>, l'ancienne est effacée) avec son positionnement. Lève PhotoRefusee."""
    zoom, x, y, ratio = cadrage_valide(zoom, x, y, ratio)
    with _VERROU:
        apercu = trouver_apercu()
        if apercu is None:
            raise PhotoRefusee("aucune image choisie (elle a peut-être expiré) : choisis-la de nouveau")
        ext = apercu.suffix.lower().lstrip(".")
        ext = "jpg" if ext in ("jpeg", "jfif") else ext
        _effacer(NOM)
        os.replace(apercu, dossier() / f"{NOM}.{ext}")
        _effacer(APERCU)
    _ecrire_reglages(conn, zoom, x, y, ratio)
    journal.logiciel(f"Photo de profil enregistrée : profil/{NOM}.{ext} (zoom {zoom:g}, position {x:g}/{y:g})")
    return reglages(conn)


def recadrer(conn, zoom, x, y, ratio=None):
    """Change seulement le positionnement de la photo actuelle. Lève PhotoRefusee s'il n'y a pas de photo."""
    zoom, x, y, ratio = cadrage_valide(zoom, x, y, ratio)
    if trouver() is None:
        raise PhotoRefusee("il n'y a pas de photo de profil")
    _ecrire_reglages(conn, zoom, x, y, ratio)
    journal.logiciel(f"Photo de profil repositionnée (zoom {zoom:g}, position {x:g}/{y:g})")
    return reglages(conn)


def supprimer(conn):
    """Supprime la photo de profil (et l'image mise de côté) ; le positionnement revient à celui de départ."""
    from . import parametres
    with _VERROU:
        _effacer(NOM)
        _effacer(APERCU)
        _effacer(PARTAGE)
    _ecrire_reglages(conn, 1.0, 50.0, 50.0, 1.0)
    parametres.ecrire(conn, "profil.photo_partagee", "")
    journal.logiciel("Photo de profil supprimée (la version partagée avec le Hall aussi)")
    return reglages(conn)


# ---------------------------------------------------------------------------------------------------------------------- la page

def html_avatar(conn):
    """Le rond de la page de profil : la photo (cliquable pour la changer) ou un cercle vide « Ajouter une photo »."""
    r = reglages(conn)
    _echapper = _html.escape
    if r["existe"]:
        contenu = (f'<span class="profil-photo__cercle"><img class="profil-photo__image" src="/profil-photo?v={r["version"]}" alt="Photo de profil" '
                   f'style="{style(r["zoom"], r["x"], r["y"], r["ratio"])}" draggable="false"></span><span class="profil-photo__crayon" aria-hidden="true">✎</span>')
        titre = "Changer la photo de profil"
    else:
        contenu = '<span class="profil-photo__cercle profil-photo__cercle--vide"><span class="profil-photo__plus" aria-hidden="true">＋</span><span class="profil-photo__libelle">Photo de profil</span></span>'
        titre = "Ajouter une photo de profil"
    return (f'<div class="profil-photo" id="profil-photo" data-existe="{1 if r["existe"] else 0}" data-zoom="{r["zoom"]:g}" data-x="{r["x"]:g}" data-y="{r["y"]:g}" '
            f'data-ratio="{r["ratio"]:.5f}" data-version="{r["version"]}" data-partage="{1 if (r["existe"] and partage_a_jour(conn)) or not r["existe"] else 0}">'
            f'<button type="button" class="profil-photo__bouton" id="profil-photo-modifier" aria-label="{_echapper(titre)}" title="{_echapper(titre)}">{contenu}</button></div>')
