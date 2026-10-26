"""Création des documents d'impression recto verso (PDF et Word), sans dépendance.

Chaque document contient deux pages : le recto (la carte) puis le verso (le dos de la
carte, aux couleurs de son rang). La carte est centrée sur la page, aux mêmes
coordonnées au recto et au verso : une fois imprimé en recto verso, le verso tombe
pile derrière le recto, quel que soit le sens dans lequel la feuille est retournée.
Les images sont des JPEG produits par la page (cartes.js) ; ils sont insérés tels quels.
"""

import io
import zipfile

from . import config

MM_PAR_POUCE = 25.4
SIGNATURE_JPEG = b"\xff\xd8\xff"


# --------------------------------------------------------------------------- JPEG

def lire_jpeg(donnees):
    """Renvoie (largeur, hauteur, composantes) d'un JPEG, lues dans son en-tête.
    Lève ValueError si ce n'est pas un JPEG lisible."""
    if not donnees.startswith(SIGNATURE_JPEG):
        raise ValueError("l'image n'est pas un JPEG")
    i, n = 2, len(donnees)
    while i + 4 <= n:
        if donnees[i] != 0xFF:
            raise ValueError("JPEG illisible")
        marqueur = donnees[i + 1]
        if marqueur == 0xFF:                       # octet de remplissage
            i += 1
            continue
        if marqueur == 0x01 or 0xD0 <= marqueur <= 0xD8:   # marqueurs sans longueur
            i += 2
            continue
        longueur = int.from_bytes(donnees[i + 2:i + 4], "big")
        if 0xC0 <= marqueur <= 0xCF and marqueur not in (0xC4, 0xC8, 0xCC):
            if i + 10 > n:
                break
            hauteur = int.from_bytes(donnees[i + 5:i + 7], "big")
            largeur = int.from_bytes(donnees[i + 7:i + 9], "big")
            return largeur, hauteur, donnees[i + 9]
        i += 2 + longueur
    raise ValueError("JPEG sans dimensions")


def _taille_mm(largeur_px, hauteur_px):
    """Taille réelle de l'image sur le papier, d'après la finesse IMPRESSION_DPI."""
    dpi = config.IMPRESSION_DPI
    larg, haut = largeur_px * MM_PAR_POUCE / dpi, hauteur_px * MM_PAR_POUCE / dpi
    papier_l, papier_h = config.PAPIER_MM
    if larg > papier_l - 4 or haut > papier_h - 4:
        raise ValueError("la carte est trop grande pour la feuille")
    return larg, haut


def _preparer(recto, verso):
    """Vérifie les deux images ; renvoie [(donnees, largeur_px, hauteur_px, composantes)]."""
    resultat = []
    for donnees in (recto, verso):
        largeur, hauteur, composantes = lire_jpeg(donnees)
        if composantes not in (1, 3):
            raise ValueError("JPEG non pris en charge (couleurs)")
        _taille_mm(largeur, hauteur)               # vérifie qu'il tient sur la feuille
        resultat.append((donnees, largeur, hauteur, composantes))
    return resultat


# ---------------------------------------------------------------------------- PDF

def creer_pdf(recto, verso):
    """PDF de deux pages (recto, verso), carte centrée à sa taille réelle."""
    images = _preparer(recto, verso)
    pt = 72 / MM_PAR_POUCE                         # millimètres -> points PDF
    page_l, page_h = config.PAPIER_MM[0] * pt, config.PAPIER_MM[1] * pt

    objets = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >>",
    }
    for i, (donnees, larg_px, haut_px, composantes) in enumerate(images):
        numero = 3 + 3 * i                         # page, contenu, image
        larg_mm, haut_mm = _taille_mm(larg_px, haut_px)
        larg, haut = larg_mm * pt, haut_mm * pt
        x, y = (page_l - larg) / 2, (page_h - haut) / 2
        espace = b"/DeviceRGB" if composantes == 3 else b"/DeviceGray"

        objets[numero] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_l:.3f} {page_h:.3f}] "
            f"/Resources << /XObject << /Im{i + 1} {numero + 2} 0 R >> >> "
            f"/Contents {numero + 1} 0 R >>").encode()
        flux = f"q {larg:.3f} 0 0 {haut:.3f} {x:.3f} {y:.3f} cm /Im{i + 1} Do Q".encode()
        objets[numero + 1] = b"<< /Length %d >>\nstream\n" % len(flux) + flux + b"\nendstream"
        objets[numero + 2] = (
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s "
            b"/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n"
            % (larg_px, haut_px, espace, len(donnees))
            + donnees + b"\nendstream")

    sortie = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    positions = {}
    for numero in sorted(objets):
        positions[numero] = len(sortie)
        sortie += b"%d 0 obj\n" % numero + objets[numero] + b"\nendobj\n"
    debut_xref = len(sortie)
    sortie += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objets) + 1)
    for numero in sorted(objets):
        sortie += b"%010d 00000 n \n" % positions[numero]
    sortie += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
               % (len(objets) + 1, debut_xref))
    return bytes(sortie)


# --------------------------------------------------------------------------- Word

_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
       'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')


def _paragraphe_image(numero, identifiant, nom, description, larg_mm, haut_mm, saut_de_page):
    cx, cy = round(larg_mm * 36000), round(haut_mm * 36000)      # 1 mm = 36 000 EMU
    saut = "<w:pageBreakBefore/>" if saut_de_page else ""
    return (
        f'<w:p><w:pPr>{saut}<w:spacing w:before="0" w:after="0" w:line="240" '
        f'w:lineRule="auto"/><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{identifiant}" name="{nom}" descr="{description}"/>'
        f'<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{identifiant}" name="{nom}.jpg"/><pic:cNvPicPr/>'
        f'</pic:nvPicPr><pic:blipFill><a:blip r:embed="rId{numero}"/><a:stretch><a:fillRect/>'
        f'</a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'</pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


def creer_docx(recto, verso):
    """Document Word de deux pages (recto, verso), carte centrée à sa taille réelle."""
    images = _preparer(recto, verso)
    twips = lambda mm: round(mm * 1440 / MM_PAR_POUCE)
    papier_l, papier_h = config.PAPIER_MM
    _, haut_mm = _taille_mm(images[0][1], images[0][2])

    # Centrage vertical par la marge haute : fonctionne dans Word, LibreOffice et Google Docs.
    marge_haute = twips((papier_h - haut_mm) / 2)
    sections = (f'<w:sectPr><w:pgSz w:w="{twips(papier_l)}" w:h="{twips(papier_h)}"/>'
                f'<w:pgMar w:top="{marge_haute}" w:right="{twips(10)}" w:bottom="{twips(5)}" '
                f'w:left="{twips(10)}" w:header="0" w:footer="0" w:gutter="0"/></w:sectPr>')

    noms = (("Recto", "Recto de la carte"), ("Verso", "Verso de la carte"))
    paragraphes = ""
    for i, (donnees, larg_px, haut_px, _) in enumerate(images):
        larg_mm, haut_mm = _taille_mm(larg_px, haut_px)
        paragraphes += _paragraphe_image(i + 1, i + 1, noms[i][0], noms[i][1],
                                         larg_mm, haut_mm, saut_de_page=(i == 1))

    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document {_NS}><w:body>{paragraphes}{sections}</w:body></w:document>')
    types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Default Extension="jpg" ContentType="image/jpeg"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '</Types>')
    relations = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                 '</Relationships>')
    relations_document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/recto.jpg"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/verso.jpg"/>'
        '</Relationships>')

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)          # doit venir en premier
        archive.writestr("_rels/.rels", relations)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", relations_document)
        archive.writestr("word/media/recto.jpg", images[0][0], zipfile.ZIP_STORED)
        archive.writestr("word/media/verso.jpg", images[1][0], zipfile.ZIP_STORED)
    return tampon.getvalue()
