"""Images des cartes personnalisées : téléversées depuis ton ordinateur, ou récupérées sur le web.

Chaque image est vérifiée (signature du fichier : JPEG, PNG, GIF ou WebP seulement ; jamais de SVG,
qui pourrait contenir du code) et rangée dans data/images/ sous un nom qui ne dépend que de son
contenu : <32 premiers caractères du SHA-256>.<extension>. Le navigateur la lit ensuite sur le
serveur local (/image/<nom>) : aucune requête vers un site tiers quand tu regardes tes cartes, et
l'export en image fonctionne (même origine).
"""

import hashlib
import re
import time

from . import config

TAILLE_MAX = 5 * 1024 * 1024            # 5 Mo
EXTENSIONS = ("jpg", "png", "gif", "webp")
_NOM = re.compile(r"[0-9a-f]{32}\.(?:jpg|png|gif|webp)")
TYPES_MIME = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}


class ImageRefusee(ValueError):
    """L'image n'est pas acceptable (message lisible par l'utilisateur)."""


def type_image(octets):
    """L'extension d'après le contenu du fichier (et non d'après son nom) : jpg, png, gif, webp ;
    None si ce n'est aucun de ces formats."""
    if octets[:3] == b"\xff\xd8\xff":
        return "jpg"
    if octets[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if octets[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if octets[:4] == b"RIFF" and octets[8:12] == b"WEBP":
        return "webp"
    return None


def dimensions(octets):
    """(largeur, hauteur) en pixels d'une image PNG ou JPEG lue dans ses premiers octets, ou None."""
    octets = bytes(octets)
    if octets[:8] == b"\x89PNG\r\n\x1a\n" and len(octets) >= 24:
        return int.from_bytes(octets[16:20], "big"), int.from_bytes(octets[20:24], "big")
    if octets[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(octets):
            if octets[i] != 0xFF:
                i += 1
                continue
            marqueur = octets[i + 1]
            if marqueur in (0xD8, 0x01) or 0xD0 <= marqueur <= 0xD7 or marqueur == 0xFF:
                i += 2 if marqueur != 0xFF else 1
                continue
            longueur = int.from_bytes(octets[i + 2:i + 4], "big")
            if 0xC0 <= marqueur <= 0xCF and marqueur not in (0xC4, 0xC8, 0xCC):    # SOF : le cadre de l'image
                return int.from_bytes(octets[i + 7:i + 9], "big"), int.from_bytes(octets[i + 5:i + 7], "big")
            i += 2 + longueur
    return None


def dimensions_fichier(nom):
    """(largeur, hauteur) d'une image locale (png ou jpg), ou None."""
    fichier = chemin(nom)
    if fichier is None:
        return None
    try:
        with open(fichier, "rb") as f:
            tete = f.read(131072)
    except OSError:
        return None
    return dimensions(tete)


COTE_MAX_PAQUET = 1200            # l'image du paquet est réduite à 1200 px au plus sur son grand côté (si Pillow est installé)
PIXELS_MAX = 40_000_000           # au-delà (par exemple 8000 × 6000) on refuse : trop lourd à décoder


def reduire(octets, maxi=COTE_MAX_PAQUET):
    """L'image réduite à `maxi` pixels sur son grand côté (orientation EXIF respectée, transparence PNG gardée), si la
    bibliothèque Pillow est installée ; sinon l'image telle quelle (le navigateur l'affiche de toute façon à la bonne taille).
    Renvoie (octets, réduite : bool). Lève ImageRefusee si l'image est illisible ou démesurée."""
    taille = dimensions(octets)
    if taille and taille[0] * taille[1] > PIXELS_MAX:
        raise ImageRefusee(f"l'image est trop grande ({taille[0]} × {taille[1]} pixels) : réduis-la d'abord")
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        return bytes(octets), False
    import io
    try:
        with Image.open(io.BytesIO(bytes(octets))) as image:
            format_ = image.format
            tournee = format_ == "JPEG" and image.getexif().get(0x0112, 1) not in (1, None)    # photo de téléphone « couchée »
            image = ImageOps.exif_transpose(image) if format_ == "JPEG" else image
            if max(image.size) <= maxi and not tournee:
                return bytes(octets), False
            image.thumbnail((maxi, maxi), Image.LANCZOS)
            sortie = io.BytesIO()
            if format_ == "PNG":
                image.save(sortie, "PNG", optimize=True)
            else:
                image.convert("RGB").save(sortie, "JPEG", quality=90, optimize=True)
            return sortie.getvalue(), True
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as erreur:
        raise ImageRefusee("image illisible ou corrompue") from erreur


def enregistrer_paquet(octets):
    """Range l'image d'un paquet personnalisé : PNG ou JPEG seulement, réduite si elle est très grande.
    Renvoie {url, largeur, hauteur, ratio, reduite}. Lève ImageRefusee (message lisible)."""
    if not isinstance(octets, (bytes, bytearray)) or len(octets) == 0:
        raise ImageRefusee("l'image est vide")
    if len(octets) > TAILLE_MAX:
        raise ImageRefusee(f"l'image est trop lourde ({len(octets) / 1024 / 1024:.1f} Mo, {TAILLE_MAX // 1024 // 1024} Mo au maximum)")
    if type_image(bytes(octets)) not in ("png", "jpg"):
        raise ImageRefusee("format non accepté pour le paquet : PNG ou JPEG seulement")
    octets, reduite = reduire(octets)
    taille = dimensions(octets)
    if not taille or min(taille) < 16:
        raise ImageRefusee("image trop petite ou illisible (16 pixels au moins de chaque côté)")
    adresse = enregistrer(octets)
    return {"url": adresse, "largeur": taille[0], "hauteur": taille[1], "ratio": ratio_borne(taille[0], taille[1]),
            "reduite": reduite}


def ratio_borne(largeur, hauteur):
    """Largeur / hauteur, borné entre 0,2 et 5 (une bande très étroite ne casse pas la page)."""
    if not largeur or not hauteur:
        return 1.0
    return round(max(0.2, min(5.0, largeur / hauteur)), 4)


def enregistrer(octets):
    """Range l'image dans data/images/ et renvoie son adresse locale « /image/<nom> ». Lève
    ImageRefusee si elle est vide, trop grosse (5 Mo) ou d'un format non accepté."""
    if not isinstance(octets, (bytes, bytearray)) or len(octets) == 0:
        raise ImageRefusee("l'image est vide")
    if len(octets) > TAILLE_MAX:
        raise ImageRefusee(f"l'image est trop lourde ({len(octets) / 1024 / 1024:.1f} Mo, "
                           f"{TAILLE_MAX // 1024 // 1024} Mo au maximum)")
    extension = type_image(bytes(octets))
    if extension is None:
        raise ImageRefusee("format d'image non accepté (JPEG, PNG, GIF ou WebP seulement)")
    nom = hashlib.sha256(octets).hexdigest()[:32] + "." + extension
    dossier = config.dossier_images()
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / nom
    if not chemin.exists():
        chemin.write_bytes(bytes(octets))
        try:
            chemin.chmod(0o600)
        except OSError:                                  # pragma: no cover - systèmes sans droits unix
            pass
    return "/image/" + nom


def chemin(nom):
    """Le fichier d'une image locale, ou None si le nom n'est pas un nom valide (jamais de « .. »,
    de sous-dossier ou de nom inventé) ou si le fichier n'existe pas."""
    if not isinstance(nom, str) or _NOM.fullmatch(nom) is None:
        return None
    fichier = config.dossier_images() / nom
    return fichier if fichier.is_file() else None


def nom_depuis_adresse(adresse):
    """« /image/<nom> » -> <nom> (ou None si ce n'est pas une adresse d'image locale)."""
    if isinstance(adresse, str) and adresse.startswith("/image/"):
        nom = adresse[len("/image/"):]
        return nom if _NOM.fullmatch(nom) else None
    return None


def adresse_locale_valide(adresse):
    """L'adresse est-elle celle d'une image locale qui existe ?"""
    nom = nom_depuis_adresse(adresse)
    return nom is not None and chemin(nom) is not None


def type_mime(nom):
    return TYPES_MIME[nom.rsplit(".", 1)[1]]


def purger_orphelines(conn, age_secondes=86400):
    """Supprime les images qu'aucune carte n'utilise et qui ont plus d'un jour (téléversées pour une
    carte jamais validée). Renvoie le nombre d'images supprimées."""
    dossier = config.dossier_images()
    if not dossier.is_dir():
        return 0
    utilisees = set()
    nom_paquet = nom_depuis_adresse(config.BOOSTER_IMAGE)          # l'image du paquet personnalisé n'est jamais « orpheline »
    if nom_paquet:
        utilisees.add(nom_paquet)
    for ligne in conn.execute("SELECT url_image, url_miniature FROM cartes"):
        for adresse in ligne:
            nom = nom_depuis_adresse(adresse)
            if nom:
                utilisees.add(nom)
    supprimees = 0
    for fichier in dossier.iterdir():
        if (fichier.is_file() and _NOM.fullmatch(fichier.name) and fichier.name not in utilisees
                and time.time() - fichier.stat().st_mtime > age_secondes):
            fichier.unlink()
            supprimees += 1
    return supprimees
