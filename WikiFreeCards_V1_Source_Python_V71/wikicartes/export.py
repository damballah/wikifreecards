"""Export des cartes en images : nom des fichiers et enregistrement dans Export/<rang>/."""

import re
from datetime import datetime
from pathlib import Path

from . import config, documents, logo

SIGNATURE_PNG = b"\x89PNG\r\n\x1a\n"
TAILLE_MAX = 15 * 1024 * 1024          # 15 Mo : largement assez pour une carte
TAILLE_MAX_DOCUMENT = 40 * 1024 * 1024  # recto + verso d'un document PDF / Word
FORMATS_DOCUMENT = {"pdf": documents.creer_pdf, "docx": documents.creer_docx}

# Espaces, apostrophes (droites et typographiques) et caractères interdits dans un
# nom de fichier : chaque série de ces caractères devient un seul "_".
_A_REMPLACER = re.compile("[\\s'\u2019\u2018`\u00b4\\\\/:*?\"<>|\\x00-\\x1f]+")
_NOM_VALIDE = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]{1,200}$')


def nettoyer_titre(titre):
    """'L'été de Jean-Paul II' -> 'L_été_de_Jean-Paul_II'."""
    nom = _A_REMPLACER.sub("_", titre).strip("_")
    return nom[:100].strip("_") or "article"


def nom_fichier(art):
    """Nom du fichier (sans extension) : <lettres du rang>_<titre nettoyé>_<jjmmaaaahhmmss>.
    Exemple : L_Thierry_Henry_13102026130835. Les lettres sont celles choisies pour le rang
    dans la page Configuration (3 au plus)."""
    tire_le = art.get("tire_le") or datetime.now()
    return f"{config.symbole(art['rarete'])}_{nettoyer_titre(art['titre'])}_{tire_le:%d%m%Y%H%M%S}"   # PERSO pour les cartes personnalisées


def dossier_rang(code):
    """Dossier d'export d'un rang : Export/<lettres du rang>/."""
    return config.DOSSIER_EXPORT / config.symbole(code)


def preparer_dossiers():
    """Crée Export/ (avec un sous-dossier par rang, nommé d'après ses lettres) et logo/."""
    for code in config.CODES:
        dossier_rang(code).mkdir(parents=True, exist_ok=True)
    config.DOSSIER_LOGO.mkdir(parents=True, exist_ok=True)
    config.DOSSIER_ICO.mkdir(parents=True, exist_ok=True)


# Le logo est géré par le module logo (choix du fichier, formats). Ces noms restent disponibles.
TYPES_LOGO = logo.TYPES
TAILLE_MAX_LOGO = logo.TAILLE_MAX


def trouver_logo():
    """Chemin du logo choisi (réglage LOGO_FICHIER), ou None s'il n'y en a pas."""
    return logo.trouver()


def _verifier_nom(code, fichier):
    if code not in config.CODES and code != config.CODE_PERSO:
        raise ValueError("rang inconnu")
    if not _NOM_VALIDE.match(fichier or "") or fichier.startswith("."):
        raise ValueError("nom de fichier invalide")
    if not fichier.startswith(config.symbole(code) + "_"):
        raise ValueError("le nom de fichier doit commencer par les lettres du rang")


def _ecrire(code, fichier, extension, donnees):
    """Écrit Export/<code>/<fichier>.<extension> et renvoie son chemin."""
    dossier = dossier_rang(code)
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{fichier}.{extension}"
    if Path(chemin).resolve().parent != dossier.resolve():
        raise ValueError("chemin invalide")
    chemin.write_bytes(donnees)
    return chemin


def enregistrer(code, fichier, donnees):
    """Écrit Export/<code>/<fichier>.png et renvoie son chemin.
    Lève ValueError si la demande est invalide."""
    _verifier_nom(code, fichier)
    if not donnees.startswith(SIGNATURE_PNG):
        raise ValueError("l'image n'est pas un PNG")
    if len(donnees) > TAILLE_MAX:
        raise ValueError("image trop volumineuse")
    return _ecrire(code, fichier, "png", donnees)


def enregistrer_document(format_, code, fichier, corps):
    """Crée Export/<code>/<fichier>.pdf (ou .docx) à partir des deux images reçues.

    `corps` : 4 octets (taille du recto, grand-boutiste), puis le JPEG du recto, puis
    le JPEG du verso. Lève ValueError si la demande est invalide."""
    if format_ not in FORMATS_DOCUMENT:
        raise ValueError("format inconnu")
    _verifier_nom(code, fichier)
    if len(corps) < 4 or len(corps) > TAILLE_MAX_DOCUMENT:
        raise ValueError("données invalides")
    taille_recto = int.from_bytes(corps[:4], "big")
    recto, verso = corps[4:4 + taille_recto], corps[4 + taille_recto:]
    if not recto or not verso:
        raise ValueError("recto ou verso manquant")
    document = FORMATS_DOCUMENT[format_](recto, verso)
    return _ecrire(code, fichier, format_, document)
