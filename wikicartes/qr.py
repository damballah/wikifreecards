"""Générateur de QR code sans dépendance : produit une image SVG à intégrer dans la page.

Implémente la norme QR Code (modèle 2), mode « octets », niveau de correction L : c'est le
plus compact, donc celui qui donne les plus gros modules (les petits carrés) et se lit le
mieux sur une petite carte.
"""

# Structure des blocs de mots de code, par version (1 à 20), niveau L.
# Chaque version : liste de groupes (nombre de blocs, mots de code par bloc,
# mots de données par bloc), d'après la norme ISO/IEC 18004.
BLOCS_L = {
    1: [(1, 26, 19)],
    2: [(1, 44, 34)],
    3: [(1, 70, 55)],
    4: [(1, 100, 80)],
    5: [(1, 134, 108)],
    6: [(2, 86, 68)],
    7: [(2, 98, 78)],
    8: [(2, 121, 97)],
    9: [(2, 146, 116)],
    10: [(2, 86, 68), (2, 87, 69)],
    11: [(4, 101, 81)],
    12: [(2, 116, 92), (2, 117, 93)],
    13: [(4, 133, 107)],
    14: [(3, 145, 115), (1, 146, 116)],
    15: [(5, 109, 87), (1, 110, 88)],
    16: [(5, 122, 98), (1, 123, 99)],
    17: [(1, 135, 107), (5, 136, 108)],
    18: [(5, 150, 120), (1, 151, 121)],
    19: [(3, 141, 113), (4, 142, 114)],
    20: [(3, 135, 107), (5, 136, 108)],
}

from html import escape
from urllib.parse import quote

VERSION_MAX = max(BLOCS_L)
_REMPLISSAGE = (0xEC, 0x11)


class TexteTropLong(ValueError):
    """Le texte ne tient dans aucun QR code géré (version 20, niveau L)."""


# --------------------------------------------------------------------------- données

def _mots_de_donnees(version):
    return sum(nombre * donnees for nombre, _, donnees in BLOCS_L[version])


def _bits_compteur(version):
    return 8 if version <= 9 else 16


def _choisir_version(octets):
    for version in range(1, VERSION_MAX + 1):
        if 4 + _bits_compteur(version) + 8 * len(octets) <= 8 * _mots_de_donnees(version):
            return version
    raise TexteTropLong(f"{len(octets)} octets : trop long pour un QR code")


def _encoder(octets, version):
    """Texte -> mots de données (mode octets, terminateur, remplissage)."""
    bits = []

    def ajouter(valeur, nombre):
        bits.extend((valeur >> i) & 1 for i in range(nombre - 1, -1, -1))

    ajouter(0b0100, 4)                                  # mode « octets »
    ajouter(len(octets), _bits_compteur(version))
    for octet in octets:
        ajouter(octet, 8)
    capacite = 8 * _mots_de_donnees(version)
    ajouter(0, min(4, capacite - len(bits)))            # terminateur
    ajouter(0, -len(bits) % 8)                          # on complète l'octet

    mots = [sum(bit << (7 - i) for i, bit in enumerate(bits[k:k + 8]))
            for k in range(0, len(bits), 8)]
    i = 0
    while len(mots) < _mots_de_donnees(version):        # octets de remplissage alternés
        mots.append(_REMPLISSAGE[i % 2])
        i += 1
    return mots


# ------------------------------------------------------- correction d'erreurs (Reed-Solomon)

def _multiplier(x, y):
    """Produit dans le corps de Galois GF(256) (polynôme 0x11D)."""
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _diviseur(degre):
    resultat = [0] * (degre - 1) + [1]
    racine = 1
    for _ in range(degre):
        for j in range(degre):
            resultat[j] = _multiplier(resultat[j], racine)
            if j + 1 < degre:
                resultat[j] ^= resultat[j + 1]
        racine = _multiplier(racine, 0x02)
    return resultat


def _reste(donnees, diviseur):
    resultat = [0] * len(diviseur)
    for octet in donnees:
        facteur = octet ^ resultat.pop(0)
        resultat.append(0)
        for i, coef in enumerate(diviseur):
            resultat[i] ^= _multiplier(coef, facteur)
    return resultat


def _mots_de_code(mots, version):
    """Ajoute la correction d'erreurs à chaque bloc, puis entrelace les blocs."""
    blocs_donnees, blocs_correction = [], []
    position = 0
    for nombre, total, donnees in BLOCS_L[version]:
        diviseur = _diviseur(total - donnees)
        for _ in range(nombre):
            bloc = mots[position:position + donnees]
            position += donnees
            blocs_donnees.append(bloc)
            blocs_correction.append(_reste(bloc, diviseur))

    resultat = []
    for i in range(max(len(b) for b in blocs_donnees)):
        resultat.extend(b[i] for b in blocs_donnees if i < len(b))
    for i in range(len(blocs_correction[0])):
        resultat.extend(b[i] for b in blocs_correction)
    return resultat


# ------------------------------------------------------------------------ matrice

def _positions_alignement(version):
    if version == 1:
        return []
    nombre = version // 7 + 2
    pas = 26 if version == 32 else (version * 4 + nombre * 2 + 1) // (nombre * 2 - 2) * 2
    taille = version * 4 + 17
    return [6] + [taille - 7 - i * pas for i in reversed(range(nombre - 1))]


def _bit(valeur, i):
    return (valeur >> i) & 1 != 0


class _Matrice:
    def __init__(self, version):
        self.version = version
        self.taille = version * 4 + 17
        self.modules = [[False] * self.taille for _ in range(self.taille)]
        self.fonction = [[False] * self.taille for _ in range(self.taille)]

    def poser(self, x, y, sombre):
        self.modules[y][x] = sombre
        self.fonction[y][x] = True

    def motifs_fixes(self):
        n = self.taille
        for i in range(n):                                   # lignes de synchronisation
            self.poser(6, i, i % 2 == 0)
            self.poser(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):      # trois grands carrés
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.poser(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        positions = _positions_alignement(self.version)
        dernier = len(positions) - 1
        for i, px in enumerate(positions):                   # petits carrés d'alignement
            for j, py in enumerate(positions):
                if (i == 0 and j == 0) or (i == 0 and j == dernier) or (i == dernier and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.poser(px + dx, py + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0)                                       # réserve la zone de format
        self.version_bits()

    def format(self, masque):
        """Écrit les 15 bits de format (niveau L + numéro de masque)."""
        donnees = (1 << 3) | masque                          # niveau L = 01
        reste = donnees
        for _ in range(10):
            reste = (reste << 1) ^ ((reste >> 9) * 0x537)
        bits = ((donnees << 10) | reste) ^ 0x5412
        n = self.taille
        for i in range(0, 6):
            self.poser(8, i, _bit(bits, i))
        self.poser(8, 7, _bit(bits, 6))
        self.poser(8, 8, _bit(bits, 7))
        self.poser(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self.poser(14 - i, 8, _bit(bits, i))
        for i in range(0, 8):
            self.poser(n - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self.poser(8, n - 15 + i, _bit(bits, i))
        self.poser(8, n - 8, True)                           # module toujours sombre

    def version_bits(self):
        if self.version < 7:
            return
        reste = self.version
        for _ in range(12):
            reste = (reste << 1) ^ ((reste >> 11) * 0x1F25)
        bits = (self.version << 12) | reste
        n = self.taille
        for i in range(18):
            a, b = n - 11 + i % 3, i // 3
            self.poser(a, b, _bit(bits, i))
            self.poser(b, a, _bit(bits, i))

    def placer_donnees(self, mots):
        """Écrit les mots de code en zigzag, par colonnes de deux modules."""
        n = self.taille
        i = 0
        for droite in range(n - 1, 0, -2):
            if droite <= 6:           # on saute la colonne de synchronisation (x = 6)
                droite -= 1
            for vertical in range(n):
                for j in range(2):
                    x = droite - j
                    monte = ((droite + 1) & 2) == 0
                    y = (n - 1 - vertical) if monte else vertical
                    if not self.fonction[y][x] and i < len(mots) * 8:
                        self.modules[y][x] = _bit(mots[i >> 3], 7 - (i & 7))
                        i += 1

    def appliquer_masque(self, masque):
        n = self.taille
        for y in range(n):
            for x in range(n):
                if not self.fonction[y][x] and _MASQUES[masque](x, y):
                    self.modules[y][x] = not self.modules[y][x]

    def penalite(self):
        """Score de lisibilité du motif (plus il est bas, mieux c'est)."""
        n, m = self.taille, self.modules
        total = 0
        lignes = m + [list(col) for col in zip(*m)]          # lignes puis colonnes
        for ligne in lignes:
            serie = 1
            for i in range(1, n):
                if ligne[i] == ligne[i - 1]:
                    serie += 1
                    continue
                if serie >= 5:
                    total += 3 + serie - 5
                serie = 1
            if serie >= 5:
                total += 3 + serie - 5
            texte = "".join("1" if c else "0" for c in ligne)
            total += 40 * (texte.count("10111010000") + texte.count("00001011101"))
        for y in range(n - 1):                               # blocs de 2 x 2 identiques
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    total += 3
        sombres = sum(sum(ligne) for ligne in m)
        total += 10 * ((abs(sombres * 20 - n * n * 10) + n * n - 1) // (n * n) - 1)
        return total


_MASQUES = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


def creer(texte):
    """Texte -> matrice de modules (liste de lignes de booléens, True = sombre)."""
    octets = texte.encode("utf-8")
    version = _choisir_version(octets)
    mots = _mots_de_code(_encoder(octets, version), version)

    matrice = _Matrice(version)
    matrice.motifs_fixes()
    matrice.placer_donnees(mots)

    meilleur, meilleur_score = 0, None
    for masque in range(8):                                  # on garde le masque le plus lisible
        matrice.appliquer_masque(masque)
        matrice.format(masque)
        score = matrice.penalite()
        if meilleur_score is None or score < meilleur_score:
            meilleur, meilleur_score = masque, score
        matrice.appliquer_masque(masque)                     # on annule
    matrice.appliquer_masque(meilleur)
    matrice.format(meilleur)
    return matrice.modules


# ------------------------------------------------------------------------------ SVG

def svg(texte, classe="carte__qr-image", description="QR code", bordure=2):
    """Renvoie le QR code sous forme d'élément <svg> prêt à intégrer dans du HTML.
    `bordure` : marge claire autour du code, en nombre de modules."""
    matrice = creer(texte)
    n = len(matrice)
    dimension = n + 2 * bordure

    traits = []
    for y, ligne in enumerate(matrice):
        x = 0
        while x < n:
            if not ligne[x]:
                x += 1
                continue
            debut = x
            while x < n and ligne[x]:
                x += 1
            traits.append(f"M{debut + bordure} {y + bordure}h{x - debut}v1h-{x - debut}z")

    return (f'<svg class="{classe}" viewBox="0 0 {dimension} {dimension}" '
            f'shape-rendering="crispEdges" role="img" aria-label="{description}">'
            f'<rect width="{dimension}" height="{dimension}" fill="#fff"/>'
            f'<path fill="#111" d="{" ".join(traits)}"/></svg>')


def svg_article(url, titre):
    """QR code (SVG) pointant vers l'article Wikipédia, ou "" s'il n'y a pas de lien.

    Le lien est forcé en https et encodé en ASCII (les accents deviennent %C3%A9...) pour
    que tous les lecteurs le comprennent. La marge blanche de 4 modules est celle que
    recommande la norme, pour bien le scanner."""
    if not url:
        return ""
    url = url.replace("http://", "https://", 1)
    url = quote(url, safe=":/%?&=#()~!*'+,;@$-._")
    try:
        return svg(url, bordure=4,
                   description=escape(f"QR code vers l'article {titre}", quote=True))
    except TexteTropLong:
        return ""                                   # lien démesuré : pas de QR code
