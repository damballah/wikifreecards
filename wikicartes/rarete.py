"""Calcul des vues et classement d'un article dans un palier de rareté."""

from . import config


def classer(vues_moyennes):
    """Renvoie (code, nom) du palier correspondant aux vues moyennes par jour."""
    for code, seuil, nom in config.PALIERS:
        if vues_moyennes >= seuil:
            return code, nom
    dernier = config.PALIERS[-1]
    return dernier[0], dernier[2]


def calculer_vues(page):
    """Renvoie (total des vues, moyenne par jour) sur la période mesurée."""
    jours = [v for v in page.get("pageviews", {}).values() if v is not None]
    if not jours:
        return 0, 0.0
    total = sum(jours)
    return total, total / len(jours)
