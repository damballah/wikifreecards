"""Le FULL-ART : une carte exceptionnelle, plus belle que les autres.

Une carte full-art porte deux calques d'image PNG posés SUR la carte, sous ses textes (ils ne gênent jamais la lecture) :
d'abord un « Zuul » (fichier du dossier `zuul/` à la racine du programme), puis, par-dessus, un « Gozer » (dossier `gozer/`) ; plus
jusqu'à trois effets visuels animés (reflets holographiques, paillettes...). Le dos de la carte reçoit les mêmes calques, sans toucher
au logo ni au QR code. Rien d'autre ne change : la carte reste la carte de l'article.

Les noms proposés sont ceux des fichiers « .png » des deux dossiers, sans l'extension. Seuls ces fichiers peuvent être servis
(liste blanche : aucun chemin donné par le navigateur n'est jamais ouvert tel quel).
"""

import html
from pathlib import Path

from . import config

RACINE = Path(config.DOSSIER_STATIC).resolve().parent
DOSSIERS = {"zuul": RACINE / "zuul", "gozer": RACINE / "gozer"}
TAILLE_MAX = 12 * 1024 * 1024         # un calque PNG de plus de 12 Mo est ignoré
TAILLE_RELAIS_MAX = 6 * 1024 * 1024   # un calque envoyé à (ou reçu d')un autre collectionneur : 6 Mo au plus
EFFETS_MAX = 3

# Les effets « premium » : code -> nom affiché (le dessin de chacun est dans cartes.css, section « Full-art »)
EFFETS = {
    "holo": "Holographique",
    "paillettes": "Paillettes",
    "or": "Reflet doré",
    "prisme": "Prisme",
    "aurore": "Aurore boréale",
    "galaxie": "Galaxie",
    "eclair": "Éclair de lumière",
    "rayons": "Rayons arc-en-ciel",
    "braises": "Braises",
    "cristal": "Cristal",
    "chrome": "Chrome liquide",
    "neon": "Néon pulsé",
}


def lister(genre):
    """Les noms (sans l'extension) des fichiers .png du dossier « zuul » ou « gozer », triés sans tenir compte des majuscules."""
    dossier = DOSSIERS.get(genre)
    if dossier is None or not dossier.is_dir():
        return []
    noms = []
    try:
        for fichier in dossier.iterdir():
            if (fichier.is_file() and fichier.suffix.lower() == ".png" and 0 < len(fichier.stem) <= 100
                    and fichier.stat().st_size <= TAILLE_MAX):
                noms.append(fichier.stem)
    except OSError:
        return []
    return sorted(set(noms), key=lambda n: (n.casefold(), n))


def chemin(genre, nom):
    """Le fichier d'un calque, ou None : le nom doit être EXACTEMENT celui d'un fichier de la liste."""
    if not isinstance(nom, str) or nom not in lister(genre):
        return None
    dossier = DOSSIERS[genre]
    for fichier in dossier.iterdir():
        if fichier.suffix.lower() == ".png" and fichier.stem == nom:
            return fichier
    return None


def valider(genre_zuul, genre_gozer, effets):
    """Vérifie une demande : (zuul, gozer, effets) nettoyés, ou ValueError avec un message clair."""
    zuul = genre_zuul or ""
    gozer = genre_gozer or ""
    if zuul and chemin("zuul", zuul) is None:
        raise ValueError("ce Zuul n'est pas dans le dossier « zuul »")
    if gozer and chemin("gozer", gozer) is None:
        raise ValueError("ce Gozer n'est pas dans le dossier « gozer »")
    if effets is None:
        effets = []
    if not isinstance(effets, list) or any(not isinstance(e, str) or e not in EFFETS for e in effets):
        raise ValueError("effet inconnu")
    effets = list(dict.fromkeys(effets))
    if len(effets) > EFFETS_MAX:
        raise ValueError(f"{EFFETS_MAX} effets au plus")
    return zuul, gozer, effets


def adresse(genre, nom):
    from urllib.parse import quote
    return f"/fullart/{genre}/{quote(nom, safe='')}.png"


def adresse_relais(pair, genre, nom):
    """L'adresse d'un calque d'un AUTRE collectionneur : relayé par ton propre programme (ton navigateur ne contacte jamais le pair)."""
    from urllib.parse import quote
    return f"/hall/fullart?pair={quote(pair, safe='')}&genre={genre}&nom={quote(nom, safe='')}"


def nom_valide(nom):
    """Un nom de calque reçu d'un autre : texte court, sans chemin ni caractère de contrôle."""
    return (isinstance(nom, str) and 0 < len(nom) <= 100 and not any(c in nom for c in "/\\:*?\"<>|") and nom.strip() == nom
            and not any(ord(c) < 32 or ord(c) == 127 for c in nom) and nom not in (".", ".."))


def png_valide(octets, largeur_max=4000, hauteur_max=6000):
    """Un PNG reçu d'un autre (signature, premier bloc IHDR, dimensions raisonnables) : sinon refusé. Rien n'est jamais interprété."""
    if not isinstance(octets, (bytes, bytearray)) or len(octets) < 33 or len(octets) > TAILLE_RELAIS_MAX:
        return False
    if bytes(octets[:8]) != b"\x89PNG\r\n\x1a\n" or bytes(octets[12:16]) != b"IHDR":
        return False
    largeur = int.from_bytes(octets[16:20], "big")
    hauteur = int.from_bytes(octets[20:24], "big")
    return 16 <= largeur <= largeur_max and 16 <= hauteur <= hauteur_max


FICHIERS_MAX = 500          # nombre maximal de calques par dossier (on n'en ajoute plus au-delà)


def enregistrer_calque(genre, nom, octets):
    """Écrit dans TON dossier « zuul » ou « gozer » un calque reçu d'un autre collectionneur (rapatriement d'une carte full-art) et renvoie le nom
    sous lequel il est rangé. Le PNG est revérifié ; un fichier qui porte déjà ce nom et le même contenu est réutilisé ; un fichier du même nom
    mais différent n'est JAMAIS écrasé : le nouveau reçoit un nom voisin (« Nom (importé) », « Nom (importé 2) »...). Lève ValueError si le calque est refusé."""
    if genre not in DOSSIERS or not nom_valide(nom) or not png_valide(octets):
        raise ValueError("calque refusé")
    dossier = DOSSIERS[genre]
    dossier.mkdir(parents=True, exist_ok=True)
    existants = {f.stem: f for f in dossier.iterdir() if f.is_file() and f.suffix.lower() == ".png"}
    candidats = [nom] + [f"{nom} (importé)"] + [f"{nom} (importé {n})" for n in range(2, 30)]
    for candidat in candidats:
        if len(candidat) > 100:
            candidat = candidat[:100]
        if candidat in existants:
            try:
                if existants[candidat].read_bytes() == bytes(octets):
                    return candidat                              # déjà présent, identique
            except OSError:
                pass
            continue
        if len(existants) >= FICHIERS_MAX:
            raise ValueError("trop de calques dans le dossier")
        cible = dossier / f"{candidat}.png"
        if cible.resolve().parent != dossier.resolve():
            raise ValueError("nom refusé")
        temporaire = dossier / f".{candidat}.tmp"
        try:
            temporaire.write_bytes(bytes(octets))
            temporaire.replace(cible)
        except OSError as erreur:
            raise ValueError(f"écriture impossible : {erreur}") from None
        return candidat
    raise ValueError("trop de calques de même nom")


def public(fullart):
    """Le full-art d'une carte tel qu'il est envoyé aux autres (liste blanche : noms existants et codes d'effets connus), ou None."""
    if not fullart:
        return None
    zuul = fullart.get("zuul") if fullart.get("zuul") and chemin("zuul", fullart["zuul"]) is not None else ""
    gozer = fullart.get("gozer") if fullart.get("gozer") and chemin("gozer", fullart["gozer"]) is not None else ""
    effets = [e for e in (fullart.get("effets") or []) if e in EFFETS][:EFFETS_MAX]
    return {"zuul": zuul, "gozer": gozer, "effets": effets} if (zuul or gozer or effets) else None


def depuis_pair(donnee, pair):
    """Le full-art reçu d'un pair -> dictionnaire sûr (avec le `pair` pour le relais), ou None s'il est abîmé : on l'ignore alors."""
    if not isinstance(donnee, dict):
        return None
    zuul, gozer = donnee.get("zuul") or "", donnee.get("gozer") or ""
    effets = donnee.get("effets") or []
    if (zuul and not nom_valide(zuul)) or (gozer and not nom_valide(gozer)):
        return None
    if not isinstance(effets, list) or any(not isinstance(e, str) for e in effets):
        return None
    effets = [e for e in dict.fromkeys(effets) if e in EFFETS][:EFFETS_MAX]
    if not (zuul or gozer or effets):
        return None
    return {"zuul": zuul, "gozer": gozer, "effets": effets, "pair": pair}


# ---------------------------------------------------------------- les effets à particules : positions et mouvements ALÉATOIRES
def _particules(code, hasard):
    """Le contenu d'un effet à particules : chacune a sa place, sa taille, sa durée, son retard et sa dérive tirés au hasard."""
    morceaux = []
    if code == "paillettes":
        for _ in range(52):
            morceaux.append(f'<i style="left:{hasard.uniform(2, 98):.1f}%;top:{hasard.uniform(2, 98):.1f}%;--s:{hasard.uniform(.7, 3.4):.2f};'
                            f'--t:{hasard.uniform(1.1, 4.6):.2f}s;--d:-{hasard.uniform(0, 5):.2f}s;--dx:{hasard.uniform(-7, 7):.1f};'
                            f'--dy:{hasard.uniform(-7, 7):.1f};--r:{hasard.randint(0, 90)}deg"{" class=e" if hasard.random() < .3 else ""}></i>')
    elif code == "galaxie":
        for _ in range(3):
            morceaux.append(f'<b style="left:{hasard.uniform(-10, 70):.0f}%;top:{hasard.uniform(-10, 70):.0f}%;--w:{hasard.uniform(45, 75):.0f}%;'
                            f'--h:{hasard.randint(190, 330)};--t:{hasard.uniform(14, 30):.1f}s;--d:-{hasard.uniform(0, 20):.1f}s;'
                            f'--dx:{hasard.uniform(-18, 18):.1f}%;--dy:{hasard.uniform(-18, 18):.1f}%"></b>')
        for _ in range(78):
            morceaux.append(f'<i style="left:{hasard.uniform(1, 99):.1f}%;top:{hasard.uniform(1, 99):.1f}%;--s:{hasard.uniform(.5, 2.6):.2f};'
                            f'--t:{hasard.uniform(1.8, 7):.2f}s;--d:-{hasard.uniform(0, 7):.2f}s;--dx:{hasard.uniform(-3, 3):.1f};'
                            f'--dy:{hasard.uniform(-3, 3):.1f}"></i>')
    elif code == "braises":
        for _ in range(34):
            morceaux.append(f'<i style="left:{hasard.uniform(2, 98):.1f}%;--s:{hasard.uniform(.8, 3.2):.2f};--t:{hasard.uniform(2.6, 6.8):.2f}s;'
                            f'--d:-{hasard.uniform(0, 7):.2f}s;--h:{hasard.uniform(45, 105):.0f};--sw:{hasard.uniform(-14, 14):.1f};'
                            f'--sw2:{hasard.uniform(-10, 10):.1f}"></i>')
    return "".join(morceaux)


def _graine(fullart, graine):
    return f"{graine}|{fullart.get('zuul')}|{fullart.get('gozer')}"


def html_calques(fullart, graine=None):
    """Le HTML des calques à poser dans une carte (entre l'image et le texte), ou "" s'il n'y a rien à montrer. `graine` (l'identifiant de la
    carte) rend le hasard des particules STABLE d'un affichage à l'autre : la même carte garde le même ciel étoilé."""
    import random
    if not fullart:
        return ""
    pair = fullart.get("pair")
    morceaux = []
    for genre in ("zuul", "gozer"):
        nom = fullart.get(genre) or ""
        if not nom:
            continue
        if pair:
            if nom_valide(nom):
                src = adresse_relais(pair, genre, nom)
            else:
                continue
        elif chemin(genre, nom) is not None:
            src = adresse(genre, nom)
        else:
            continue
        morceaux.append(f'<img class="fa__calque fa__{genre}" src="{html.escape(src, quote=True)}" alt="" draggable="false" decoding="async">')
    for code in fullart.get("effets") or []:
        if code in EFFETS:
            hasard = random.Random(f"{_graine(fullart, graine)}|{code}")
            morceaux.append(f'<span class="fa__effet fa__effet--{code}">{_particules(code, hasard)}</span>')
    if not morceaux:
        return ""
    return '<div class="carte__fullart" aria-hidden="true">' + "".join(morceaux) + "</div>"


def attributs(fullart, graine=None):
    """Les attributs de la balise <article> d'une carte full-art (le dos de la carte en a besoin pour refaire les mêmes calques)."""
    if not fullart or not html_calques(fullart, graine):
        return ""
    return (f' data-fullart="1" data-fa-zuul="{html.escape(fullart.get("zuul") or "", quote=True)}"'
            f' data-fa-gozer="{html.escape(fullart.get("gozer") or "", quote=True)}"'
            f' data-fa-effets="{html.escape(" ".join(fullart.get("effets") or []), quote=True)}"')
