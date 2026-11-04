"""Page de profil : vitrines (lignes de cartes que l'on choisit soi-même).

Le titre d'une vitrine accepte les lettres (accents compris, toutes écritures), les chiffres, les
espaces, un peu de ponctuation et les emoji (y compris les emoji composés : drapeaux, familles,
couleurs de peau, chiffres encadrés). Les caractères de contrôle, le HTML (< >), les guillemets
droits et les caractères invisibles ou de direction du texte sont refusés.
"""

import unicodedata

TITRE_MAX = 40                   # caractères (un emoji compte pour un)
PONCTUATION = set("'’-–—.,;:!?()&+/#%@*_~«»·•…")
# Éléments qui servent à composer les emoji
COMPOSANTS_EMOJI = {"\u200d", "\ufe0f", "\ufe0e", "\u20e3"}    # liant, sélecteurs de variante, cadre


def nettoyer_titre(texte):
    """(titre nettoyé, message d'erreur). Les espaces en trop sont réduits ; un titre vide est
    permis (il efface le titre). En cas d'erreur, le titre est None."""
    if not isinstance(texte, str):
        return None, "le titre doit être du texte"
    texte = " ".join(unicodedata.normalize("NFC", texte).split())
    if len(texte) > TITRE_MAX:
        return None, f"le titre est trop long ({len(texte)} caractères, {TITRE_MAX} au maximum)"
    for caractere in texte:
        if not caractere_permis(caractere):
            if unicodedata.category(caractere)[0] in "CZ":
                return None, "un caractère invisible ou de contrôle n'est pas permis dans un titre"
            return None, f"le caractère « {caractere} » n'est pas permis dans un titre"
    return texte, ""


def caractere_permis(caractere):
    """Lettre, chiffre, espace, ponctuation courante, emoji (et ses composants) ?"""
    if caractere == " " or caractere in PONCTUATION or caractere in COMPOSANTS_EMOJI:
        return True
    categorie = unicodedata.category(caractere)
    if categorie == "Sk":            # « ` », « ^ », « ¨ »... refusés ; seules les 5 couleurs de peau passent
        return 0x1F3FB <= ord(caractere) <= 0x1F3FF
    # L : lettres, N : chiffres, M : accents combinés, So : symboles et emoji
    return categorie[0] in "LNM" or categorie == "So"
