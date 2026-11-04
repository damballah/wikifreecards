"""Thème visuel du site et des cartes, d'après la configuration.

Chaque rang de carte a un motif, trois couleurs et un reflet animé (voir THEMES_PALIERS dans
config.py, ou la page Configuration). Les couleurs servent ainsi :
- couleur 1 : fond de la carte, en haut ; couleur 2 : fond de la carte, en bas ;
- couleur 3 : accent (motif en arrière-plan, lettre du rang, halo lumineux).
La couleur du texte est choisie automatiquement (foncée ou blanche) pour rester lisible.

Les motifs et les reflets eux-mêmes sont dessinés dans static/cartes.css, d'après les attributs
data-motif et data-reflet des cartes ; ce module fournit les couleurs (variables CSS) et les listes
de choix. Les formules de couleurs ci-dessous sont reprises à l'identique dans
static/configuration.js (aperçu en direct) : à modifier ensemble.
"""

import json
import re

from . import profil

# Choix possibles : valeur -> libellé affiché dans la page Configuration
MOTIFS = {
    "aucun": "Aucun",
    "vagues": "Vagues",
    "rayures": "Rayures",
    "points": "Points",
    "losanges": "Losanges",
    "rayons": "Rayons",
}
REFLETS = {
    "aucune": "Aucun",
    "balayage": "Balayage",
    "pulsation": "Pulsation",
    "etincelles": "Étincelles",
    "arcenciel": "Arc-en-ciel",
    "montante": "Vague montante",
    "tournant": "Faisceau tournant",
    "croise": "Balayage croisé",
    "paillettes": "Paillettes scintillantes",
    "aurore": "Aurore",
    "neon": "Contour néon",
}
ANGLES = {"arrondis": "Arrondis", "carres": "Carrés (angle droit)"}

# Thèmes (habillages) du site : couleurs et motif de fond. « sombre » et « clair » sont écrits dans
# static/cartes.css ; les autres sont générés par css_themes_site(). Pour chaque thème :
#   libelle, mode (« sombre » ou « clair »), fond, texte, discret (texte secondaire), erreur,
#   lueur (halo en haut à gauche), accent (couleur d'accent propre au thème, ou None : celle de la
#   configuration), motif (un fond décoratif en dégradés CSS, ou None) et taille (pas du motif).
# Le motif est un seul calque (une seule fonction de dégradé) répété à la taille indiquée.
PALETTES_SITE = {
    "sombre": {"libelle": "Sombre", "mode": "sombre", "fond": "#0e1016", "texte": "#e9ebf2",
               "discret": "#9aa0b4", "erreur": "#ff7b7b", "lueur": "rgba(120, 90, 255, .20)",
               "accent": None, "motif": None, "taille": None},
    "clair": {"libelle": "Clair", "mode": "clair", "fond": "#f2f3f8", "texte": "#15171e",
              "discret": "#5b6275", "erreur": "#c62828", "lueur": "rgba(120, 90, 255, .12)",
              "accent": None, "motif": None, "taille": None},
    "minuit": {"libelle": "Minuit étoilé", "mode": "sombre", "fond": "#0a1029", "texte": "#e6ebff",
               "discret": "#a3b3e3", "erreur": "#ff8a8a", "lueur": "rgba(80, 120, 255, .26)",
               "accent": "#8ab4ff",
               "motif": "radial-gradient(circle, rgba(255, 255, 255, .55) 0 1px, transparent 1.6px)",
               "taille": "83px 83px"},
    "ocean": {"libelle": "Océan", "mode": "sombre", "fond": "#06202b", "texte": "#e4f6f8",
              "discret": "#8fc3cc", "erreur": "#ff9b8a", "lueur": "rgba(0, 190, 200, .24)",
              "accent": "#2ee6d6",
              "motif": "radial-gradient(circle at 50% 100%, transparent 0 14px, rgba(120, 230, 240, .08) "
                       "15px 16px, transparent 17px)",
              "taille": "40px 20px"},
    "foret": {"libelle": "Forêt", "mode": "sombre", "fond": "#0f1c14", "texte": "#e8f3e4",
              "discret": "#9bbd9a", "erreur": "#ff9a8a", "lueur": "rgba(80, 200, 120, .22)",
              "accent": "#8fd16a",
              "motif": "radial-gradient(circle, rgba(160, 220, 140, .10) 0 3px, transparent 3.5px)",
              "taille": "36px 36px"},
    "crepuscule": {"libelle": "Crépuscule", "mode": "sombre", "fond": "#1b1030", "texte": "#f6e9ff",
                   "discret": "#c8b0e2", "erreur": "#ff8a9a", "lueur": "rgba(255, 120, 80, .26)",
                   "accent": "#ff8a5c",
                   "motif": "repeating-linear-gradient(135deg, rgba(255, 255, 255, .045) 0 2px, "
                            "transparent 2px 14px)",
                   "taille": None},
    "sakura": {"libelle": "Sakura", "mode": "clair", "fond": "#fff1f5", "texte": "#3a1522",
               "discret": "#82495d", "erreur": "#c62828", "lueur": "rgba(255, 120, 170, .24)",
               "accent": "#d6336c",
               "motif": "radial-gradient(circle, rgba(236, 72, 153, .10) 0 4px, transparent 5px)",
               "taille": "40px 40px"},
    "parchemin": {"libelle": "Parchemin", "mode": "clair", "fond": "#f3e9d2", "texte": "#2e2415",
                  "discret": "#65543a", "erreur": "#a82020", "lueur": "rgba(190, 140, 60, .22)",
                  "accent": "#9a5b13",
                  "motif": "repeating-linear-gradient(0deg, rgba(120, 90, 40, .06) 0 1px, "
                           "transparent 1px 4px)",
                  "taille": None},
    "neon": {"libelle": "Néon arcade", "mode": "sombre", "fond": "#07040f", "texte": "#f4eaff",
             "discret": "#b9a0d9", "erreur": "#ff6b8a", "lueur": "rgba(255, 0, 170, .26)",
             "accent": "#00f0ff",
             "motif": "conic-gradient(from 90deg at 1px 1px, transparent 90deg, "
                      "rgba(255, 60, 200, .14) 0)",
             "taille": "34px 34px"},
    "lavande": {"libelle": "Lavande", "mode": "clair", "fond": "#f1edff", "texte": "#1f1a3a",
                "discret": "#575083", "erreur": "#c62828", "lueur": "rgba(150, 120, 255, .24)",
                "accent": "#6d4aff",
                "motif": "repeating-conic-gradient(rgba(124, 92, 255, .06) 0 25%, transparent 0 50%)",
                "taille": "36px 36px"},
    "graphite": {"libelle": "Graphite", "mode": "sombre", "fond": "#17181a", "texte": "#ececec",
                 "discret": "#a3a3a3", "erreur": "#ff8080", "lueur": "rgba(255, 255, 255, .07)",
                 "accent": "#c9d1d9",
                 "motif": "repeating-linear-gradient(45deg, rgba(255, 255, 255, .03) 0 1px, "
                          "transparent 1px 7px)",
                 "taille": None},
    "braise": {"libelle": "Braise", "mode": "sombre", "fond": "#1d0c0a", "texte": "#fdeee8",
               "discret": "#d6aa9c", "erreur": "#ff9a8a", "lueur": "rgba(255, 90, 40, .26)",
               "accent": "#ff7a3d",
               "motif": "radial-gradient(circle, rgba(255, 140, 60, .14) 0 1.5px, transparent 2.5px)",
               "taille": "48px 48px"},
    "menthe": {"libelle": "Menthe", "mode": "clair", "fond": "#ebf8f1", "texte": "#12301f",
               "discret": "#46705a", "erreur": "#b3261e", "lueur": "rgba(60, 200, 140, .22)",
               "accent": "#0e8a56",
               "motif": "conic-gradient(from 90deg at 1px 1px, transparent 90deg, "
                        "rgba(20, 140, 90, .10) 0)",
               "taille": "30px 30px"},
    "or-noir": {"libelle": "Or et noir", "mode": "sombre", "fond": "#0b0b0c", "texte": "#f3ecd6",
                "discret": "#bdae80", "erreur": "#ff8a80", "lueur": "rgba(212, 175, 55, .18)",
                "accent": "#d4af37",
                "motif": "repeating-linear-gradient(45deg, rgba(212, 175, 55, .07) 0 1px, "
                         "transparent 1px 10px)",
                "taille": None},
    "contraste": {"libelle": "Contraste élevé", "mode": "sombre", "fond": "#000000",
                  "texte": "#ffffff", "discret": "#e0e0e0", "erreur": "#ff9a9a",
                  "lueur": "rgba(255, 255, 255, .0)", "accent": "#ffe600", "motif": None,
                  "taille": None},
    # --- Thèmes « ambiance » -------------------------------------------------------------------------
    "fluo-80": {"libelle": "Années 80-90 · fluo new age", "mode": "sombre", "fond": "#150433", "texte": "#fff4ff",
                "discret": "#d3a9ff", "erreur": "#ff6f9c", "lueur": "rgba(0, 255, 230, .30)",
                "accent": "#ff3df0",
                "motif": "linear-gradient(135deg, rgba(0, 255, 230, .13) 25%, transparent 25%)",
                "taille": "44px 44px"},
    "arcade-8bit": {"libelle": "Arcade rétro · jeu vidéo 8 bits", "mode": "sombre", "fond": "#080c26", "texte": "#eaffea",
                    "discret": "#8fd89a", "erreur": "#ff5c5c", "lueur": "rgba(57, 255, 20, .16)",
                    "accent": "#39ff14",
                    "motif": "conic-gradient(from 90deg at 2px 2px, transparent 90deg, rgba(57, 255, 20, .16) 0)",
                    "taille": "16px 16px"},
    "jeu-societe": {"libelle": "Jeu de société", "mode": "clair", "fond": "#fff4de", "texte": "#2b1a0b",
                    "discret": "#7a5a3a", "erreur": "#b3261e", "lueur": "rgba(230, 90, 50, .20)",
                    "accent": "#e4572e",
                    "motif": "repeating-conic-gradient(rgba(228, 87, 46, .09) 0 25%, transparent 0 50%)",
                    "taille": "56px 56px"},
    "chic": {"libelle": "Chic tendance", "mode": "clair", "fond": "#f5f2ec", "texte": "#1b1a18",
             "discret": "#6d675c", "erreur": "#a52a2a", "lueur": "rgba(176, 141, 87, .18)",
             "accent": "#1f5c4d",
             "motif": "repeating-linear-gradient(90deg, rgba(27, 26, 24, .04) 0 1px, transparent 1px 72px)",
             "taille": None},
    "album": {"libelle": "Album de cartes à collectionner", "mode": "sombre", "fond": "#2a1d15", "texte": "#f7ebd9",
              "discret": "#d1b894", "erreur": "#ff9a80", "lueur": "rgba(224, 177, 90, .22)",
              "accent": "#e0b15a",
              "motif": "radial-gradient(circle, rgba(255, 232, 196, .08) 0 1px, transparent 1.6px)",
              "taille": "7px 7px"},
}
THEMES_SITE = {code: p["libelle"] for code, p in PALETTES_SITE.items()}
THEMES_STATIQUES = ("sombre", "clair")      # déjà écrits dans static/cartes.css
EFFETS_SURVOL = {
    "soulever": "Soulever", "incliner": "Incliner", "zoom": "Agrandir (zoom)",
    "flottement": "Flotter doucement", "ressort": "Ressort (rebond)", "pivot": "Pivot 3D",
    "tilt": "Suit la souris (3D)", "brillance": "Brillance (reflet qui passe)",
    "halo": "Halo lumineux", "balancement": "Balancer", "aucun": "Aucun",
}

ANIMATIONS_ZOOM = {
    "flottement": "Flottement léger", "balancement": "Balancement doux",
    "respiration": "Respiration (zoom léger)", "pivot": "Pivot 3D léger",
    "brillance": "Reflet qui passe", "tilt": "Suit la souris (3D)", "aucune": "Aucune",
}

MOTIF_PAR_DEFAUT = "vagues"
REFLET_PAR_DEFAUT = "aucune"
COULEURS_PAR_DEFAUT = ("#c9ccd6", "#eceef3", "#b4b9c9")   # rang inconnu : gris neutre

TEXTE_FONCE = "#1a1a1f"
TEXTE_CLAIR = "#ffffff"

_COULEUR = re.compile(r"#[0-9a-fA-F]{6}")


def couleur_valide(valeur):
    return isinstance(valeur, str) and _COULEUR.fullmatch(valeur) is not None


# ------------------------------------------------------------------------- couleurs

def hex_vers_rvb(couleur):
    return tuple(int(couleur[i:i + 2], 16) for i in (1, 3, 5))


def _lineaire(composante):
    v = composante / 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminance(couleur):
    """Luminance relative d'une couleur (norme WCAG) : 0 = noir, 1 = blanc."""
    r, g, b = (_lineaire(c) for c in hex_vers_rvb(couleur))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def couleur_lisible(lum):
    """Texte foncé ou blanc, selon le meilleur contraste avec un fond de luminance `lum`."""
    contraste_fonce = (lum + 0.05) / (luminance(TEXTE_FONCE) + 0.05)
    contraste_clair = 1.05 / (lum + 0.05)
    return TEXTE_FONCE if contraste_fonce >= contraste_clair else TEXTE_CLAIR


def rgba(couleur, opacite):
    r, g, b = hex_vers_rvb(couleur)
    return f"rgba({r}, {g}, {b}, {opacite})"


def derives(couleurs):
    """Couleurs calculées à partir des trois couleurs choisies."""
    c1, c2, c3 = couleurs
    return {
        "texte": couleur_lisible((luminance(c1) + luminance(c2)) / 2),
        "badge-texte": couleur_lisible(luminance(c3)),
        "motif": rgba(c3, 0.34),
        "halo": rgba(c3, 0.5),
    }


def variables_rang(couleurs):
    """Variables CSS d'un rang : [(nom, valeur), ...]."""
    c1, c2, c3 = couleurs
    calculees = derives(couleurs)
    return [
        ("--c1", c1), ("--c2", c2), ("--c3", c3),
        ("--texte", calculees["texte"]),
        ("--badge-fond", c3), ("--badge-texte", calculees["badge-texte"]),
        ("--halo", calculees["halo"]), ("--motif", calculees["motif"]),
    ]


def style_en_ligne(couleurs):
    """Les variables d'un rang sous forme d'attribut style (aperçu dans la configuration)."""
    return "; ".join(f"{nom}: {valeur}" for nom, valeur in variables_rang(couleurs))


# ------------------------------------------------------------------ cartes personnalisées

# Style d'une carte créée dans le Créateur de cartes. Chaque carte porte son propre style (copié, au
# moment de la création, depuis le palier choisi : le palier « Personnalisée » de la Configuration ou
# un autre rang) : elle ne change plus ensuite. STYLE_PERSO_DEFAUT sert de repli (valeurs d'origine).
STYLE_PERSO_DEFAUT = {
    "motif": "points", "couleurs": ["#5fd0c5", "#fff1c9", "#f08a5d"], "reflet": "balayage",
    "symbole": "PERSO", "palier": "Personnalisée",
}
SYMBOLE_PERSO_MAX = 5          # lettres du palier : 5 au maximum (3 pour les rangs de la Configuration)
PALIER_PERSO_MAX = 40          # nom du palier (celui d'un rang peut aller jusqu'à 40 caractères)


def style_perso(brut):
    """Le style d'une carte personnalisée, vérifié : `brut` est du JSON (texte) ou un dictionnaire.
    Tout ce qui est absent ou invalide est remplacé par la valeur de départ (carte blanche) ; on ne
    renvoie jamais une couleur, un motif ou un texte douteux."""
    defaut = STYLE_PERSO_DEFAUT
    if isinstance(brut, str):
        try:
            brut = json.loads(brut)
        except ValueError:
            brut = {}
    if not isinstance(brut, dict):
        brut = {}
    couleurs = brut.get("couleurs")
    if not (isinstance(couleurs, list) and len(couleurs) == 3 and all(couleur_valide(c) for c in couleurs)):
        couleurs = defaut["couleurs"]
    symbole = brut.get("symbole")
    if not (isinstance(symbole, str) and 1 <= len(symbole) <= SYMBOLE_PERSO_MAX
            and all(profil.caractere_permis(c) and c != " " for c in symbole)):
        symbole = defaut["symbole"]
    palier = brut.get("palier")
    if not (isinstance(palier, str) and 1 <= len(palier.strip()) <= PALIER_PERSO_MAX
            and all(profil.caractere_permis(c) for c in palier)):
        palier = defaut["palier"]
    return {"motif": brut.get("motif") if brut.get("motif") in MOTIFS else defaut["motif"],
            "couleurs": [c.lower() for c in couleurs],
            "reflet": brut.get("reflet") if brut.get("reflet") in REFLETS else defaut["reflet"],
            "symbole": symbole, "palier": palier.strip()}


# ------------------------------------------------------------------------ par carte

def theme_du_rang(themes, code):
    """Thème d'un rang, ou un thème neutre si le rang n'a pas (ou plus) de thème."""
    theme = themes.get(code)
    if not theme:
        return {"motif": MOTIF_PAR_DEFAUT, "couleurs": list(COULEURS_PAR_DEFAUT),
                "reflet": REFLET_PAR_DEFAUT}
    return theme


# ------------------------------------------------------------------------------ CSS

def _accent_texte(accent):
    return couleur_lisible(luminance(accent))


def accent_effectif(theme_site, accent_perso, accent_du_theme):
    """La couleur d'accent affichée : celle du thème (si le réglage le demande et si le thème en
    a une), sinon celle choisie dans la configuration."""
    palette = PALETTES_SITE.get(theme_site) or {}
    return palette.get("accent") if (accent_du_theme and palette.get("accent")) else accent_perso


def css_themes_site():
    """CSS des thèmes du site (tous sauf « sombre » et « clair », écrits dans cartes.css).
    L'accent propre à un thème ne s'applique que si <html data-accent="theme"> : la page
    Configuration peut ainsi changer de thème, et d'accent, en direct."""
    lignes = ["/* Thèmes du site (voir PALETTES_SITE dans wikicartes/theme.py) */"]
    for code, palette in PALETTES_SITE.items():
        if code in THEMES_STATIQUES or not re.fullmatch(r"[a-z0-9-]{1,20}", code):
            continue
        sombre = palette["mode"] == "sombre"
        blanc_noir = "255, 255, 255" if sombre else "0, 0, 0"
        lignes += [
            f':root[data-theme="{code}"] {{',
            f"  color-scheme: {'dark' if sombre else 'light'};",
            f"  --page-fond: {palette['fond']};",
            f"  --page-texte: {palette['texte']};",
            f"  --page-discret: {palette['discret']};",
            f"  --surface: rgba({blanc_noir}, {.07 if sombre else .05});",
            f"  --surface-survol: rgba({blanc_noir}, {.13 if sombre else .09});",
            f"  --surface-active: rgba({blanc_noir}, {.20 if sombre else .14});",
            f"  --bord: rgba({blanc_noir}, {.14 if sombre else .16});",
            f"  --bord-fort: rgba({blanc_noir}, {.60 if sombre else .55});",
            f"  --erreur: {palette['erreur']};",
            f"  --lueur-1: {palette['lueur']};",
        ]
        if palette["motif"]:
            lignes.append(f"  --motif-site: {palette['motif']};")
            lignes.append(f"  --motif-taille: {palette['taille'] or 'auto'};")
        lignes.append("}")
        if palette["accent"]:
            rvb = ", ".join(str(c) for c in hex_vers_rvb(palette["accent"]))
            lignes += [
                f':root[data-theme="{code}"][data-accent="theme"] {{',
                f"  --accent: {palette['accent']};",
                f"  --accent-rgb: {rvb};",
                f"  --accent-texte: {_accent_texte(palette['accent'])};",
                "}",
            ]
    return "\n".join(lignes) + "\n"


def css_theme(themes, angles_cartes, angles_site, accent, perso=None):
    """CSS généré : angles, couleur d'accent et couleurs de chaque rang (`perso` : thème du palier des
    cartes personnalisées, pour ses pastilles)."""
    arrondi_carte = 18 if angles_cartes == "arrondis" else 0
    arrondi_site = "12px" if angles_site == "arrondis" else "0px"
    arrondi_pastille = "999px" if angles_site == "arrondis" else "0px"
    lignes = [
        "/* Thème généré d'après la configuration (page Configuration) */",
        ":root {",
        f"  --angle-carte: {arrondi_carte};",
        f"  --angle-site: {arrondi_site};",
        f"  --angle-pastille: {arrondi_pastille};",
        f"  --accent: {accent};",
        "  --accent-rgb: " + ", ".join(str(c) for c in hex_vers_rvb(accent)) + ";",
        f"  --accent-texte: {_accent_texte(accent)};",
        "}",
    ]
    lignes.append(f'[data-rarete="PERSO"] {{')            # pastilles des cartes personnalisées : blanc neutre
    lignes.extend(f"  {nom}: {valeur};" for nom, valeur in variables_rang(
        (perso or STYLE_PERSO_DEFAUT)["couleurs"]))
    lignes.append("}")
    for code, theme in themes.items():
        if not re.fullmatch(r"[A-Za-z0-9]{1,6}", code) or not all(
                couleur_valide(c) for c in theme["couleurs"]):
            continue                                     # on n'écrit jamais de CSS douteux
        lignes.append(f'[data-rarete="{code}"] {{')
        lignes.extend(f"  {nom}: {valeur};" for nom, valeur in variables_rang(theme["couleurs"]))
        lignes.append("}")
    return "\n".join(lignes) + "\n"
