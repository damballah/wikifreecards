"""Construction du formulaire de la page Configuration (HTML).

Chaque champ porte `data-param` (nom du paramètre dans config.py) et `data-defaut` (sa valeur de
départ, en JSON) : static/configuration.js lit ces attributs pour envoyer les valeurs au serveur
et pour les boutons « ↺ » qui rétablissent la valeur de config.py.
"""

import html
import json

from . import categories as cat
import time

from . import acces, config, logo, parametres, reserve, sauvegardes, sons, theme


def _e(valeur):
    return html.escape(str(valeur), quote=True)


def _json_attr(valeur):
    return _e(json.dumps(valeur, ensure_ascii=False))


def _nombre(valeur):
    """63.0 -> 63 ; 0.5 -> 0.5 (pour l'affichage dans un champ numérique)."""
    if isinstance(valeur, float) and valeur.is_integer():
        return int(valeur)
    return valeur


def _texte_defaut(valeur):
    if isinstance(valeur, bool):
        return "oui" if valeur else "non"
    if isinstance(valeur, (list, tuple)):
        return " × ".join(str(_nombre(x)) for x in valeur)
    return str(_nombre(valeur))


def _bouton_reinit(nom, defaut):
    return (f'<button type="button" class="champ__reinit" data-reinit="{_e(nom)}" '
            f'title="Valeur de config.py : {_e(_texte_defaut(defaut))}" '
            f'aria-label="Rétablir la valeur de config.py">↺</button>')


def _saisie(param, valeur, defaut):
    """Le contrôle de saisie d'un paramètre, selon son type."""
    nom = param.nom
    valeur, defaut = param.affichage(valeur), param.affichage(defaut)       # ce qu'on voit (ex. chemins avec « \\ »)
    base = (f'id="p-{_e(nom)}" data-param="{_e(nom)}" data-type="{_e(param.type)}" '
            f'data-defaut="{_json_attr(defaut)}"')
    if param.type in ("entier", "nombre"):
        return (f'<input type="number" inputmode="decimal" min="{param.mini}" max="{param.maxi}" '
                f'step="{param.pas}" value="{_e(_nombre(valeur))}" {base}>')
    if param.type == "bool":
        return f'<input type="checkbox" {"checked " if valeur else ""}{base}>'
    if param.type == "choix":
        options = "".join(
            f'<option value="{_e(cle)}"{" selected" if cle == valeur else ""}>{_e(libelle)}</option>'
            for cle, libelle in param.choix.items())
        return f'<select {base}>{options}</select>'
    if param.type == "couleur":
        return f'<input type="color" value="{_e(valeur)}" {base}>'
    if param.type == "papier":
        l, h = valeur
        return (f'<span class="champ__double" id="p-{_e(nom)}" data-param="{_e(nom)}" '
                f'data-type="papier" data-defaut="{_json_attr(list(defaut))}">'
                f'<input type="number" min="50" max="1000" step="0.1" value="{_e(_nombre(l))}" '
                f'data-index="0" aria-label="Largeur de la feuille" data-papier>'
                f' × '
                f'<input type="number" min="50" max="1000" step="0.1" value="{_e(_nombre(h))}" '
                f'data-index="1" aria-label="Hauteur de la feuille" data-papier></span>')
    if param.type == "son":                          # liste des fichiers du dossier sons/ + bouton « écouter »
        noms = sons.lister()
        options = '<option value="">(aucun son)</option>' + "".join(
            f'<option value="{_e(n)}"{" selected" if n == valeur else ""}>{_e(n)}</option>' for n in noms)
        if valeur and valeur not in noms:
            options += f'<option value="{_e(valeur)}" selected>{_e(valeur)} (fichier introuvable)</option>'
        return (f'<span class="champ__son"><select {base}>{options}</select>'
                f'<button type="button" class="bouton-son-essai" data-essai="{_e(nom)}" aria-label="Écouter ce son" '
                f'title="Écouter">▶</button></span>')
    if param.type == "image_paquet":                 # réglé par le bouton « Choisir une image » (champ caché)
        return f'<input type="hidden" value="{_e(valeur)}" {base}>'
    if param.type == "logo":
        choix = logo.options()
        if valeur not in choix:                  # fichier choisi puis retiré du dossier logo/
            choix[valeur] = f"{valeur} (introuvable)"
        options = "".join(
            f'<option value="{_e(cle)}"{" selected" if cle == valeur else ""}>{_e(libelle)}</option>'
            for cle, libelle in choix.items())
        return f'<select {base}>{options}</select>'
    if param.type == "zone":                          # un texte long, plusieurs lignes (ta liste de mots)
        return (f'<textarea rows="8" maxlength="{param.maxi or 20000}" spellcheck="false" autocomplete="off" '
                f'class="champ__zone" {base}>{_e(valeur)}</textarea>')
    # Titre et biographie : la limite se compte en caractères AFFICHÉS (un emoji = 1) et c'est le serveur qui la contrôle ;
    # le navigateur compte en unités UTF-16 (un emoji = 2 à 11) : on lui laisse donc plus de place.
    limite = (param.maxi or 100) * (14 if param.nom in ("TITRE_SITE", "BIO_SITE") else 1)
    return f'<input type="text" maxlength="{limite}" value="{_e(valeur)}" {base}>'


def html_champ(param, valeur, defaut):
    """Une ligne du formulaire : libellé, saisie, unité, bouton ↺, aide et zone d'erreur."""
    defaut_affiche = param.affichage(defaut)
    if param.type == "image_paquet":                 # pas de ligne : seulement le champ caché (voir le bloc « Ton propre paquet »)
        return f'<div hidden>{_saisie(param, valeur, defaut)}</div>'
    unite = f'<span class="champ__unite">{_e(param.unite)}</span>' if param.unite else ""
    aide = _e(param.aide)
    if param.redemarrage:
        aide = (aide + " " if aide else "") + "<em>(pris en compte au prochain lancement)</em>"
    return (
        f'<div class="champ champ--{_e(param.type)}" data-champ="{_e(param.nom)}">'
        f'<label for="p-{_e(param.nom)}">{_e(param.libelle)}</label>'
        f'<div class="champ__saisie">{_saisie(param, valeur, defaut)}{unite}'
        f'{_bouton_reinit(param.nom, defaut_affiche)}</div>'
        f'<p class="champ__aide">{aide}</p>'
        f'<p class="champ__erreur" data-erreur="{_e(param.nom)}" role="alert" hidden></p>'
        f'</div>')


# ------------------------------------------------------------------------ rangs

def _options(choix, courant):
    return "".join(
        f'<option value="{_e(cle)}"{" selected" if cle == courant else ""}>{_e(libelle)}</option>'
        for cle, libelle in choix.items())


def _html_rang(code, seuil, nom, poids, part, rang_theme, defaut_theme, dernier, apercu,
               symbole, defaut_symbole):
    c1, c2, c3 = rang_theme["couleurs"]
    seuil_html = (f'<input type="number" min="0" step="1" value="0" readonly '
                  f'data-palier-champ="seuil" aria-label="Seuil du rang {_e(code)}">'
                  if dernier else
                  f'<input type="number" min="0" step="1" value="{_e(_nombre(seuil))}" '
                  f'data-palier-champ="seuil" aria-label="Seuil du rang {_e(code)}">')
    note = ' <small>(dernier rang : toujours 0)</small>' if dernier else ""
    return (
        f'<article class="palier" data-palier="{_e(code)}" data-rarete="{_e(code)}" '
        f'data-defaut-theme="{_json_attr(defaut_theme)}" '
        f'data-defaut-symbole="{_e(defaut_symbole)}">'
        f'<div class="palier__apercu" aria-label="Aperçu du rang {_e(code)}">{apercu}</div>'
        f'<div class="palier__champs">'
        f'<div class="palier__titre"><span class="palier__code" '
        f'data-palier-code>{_e(symbole)}</span>'
        f'<label class="palier__symbole-etiquette">Lettres <input type="text" '
        f'class="palier__symbole" maxlength="3" value="{_e(symbole)}" size="4" '
        f'data-palier-champ="symbole" aria-label="Lettres du rang {_e(code)} (3 au maximum)" '
        f'autocomplete="off" spellcheck="false"></label>'
        f'<input type="text" class="palier__nom" maxlength="40" value="{_e(nom)}" '
        f'data-palier-champ="nom" aria-label="Nom du rang {_e(code)}"></div>'
        f'<div class="palier__ligne">'
        f'<label>Seuil {seuil_html} <span class="champ__unite">vues/jour</span>{note}</label>'
        f'<label>Probabilité <input type="number" min="0" step="0.5" value="{_e(_nombre(poids))}" '
        f'data-palier-champ="poids"> <output class="palier__part" data-palier-part>{part}</output>'
        f'</label></div>'
        f'<div class="palier__ligne">'
        f'<label>Motif <select data-palier-champ="motif">'
        f'{_options(theme.MOTIFS, rang_theme["motif"])}</select></label>'
        f'<label>Reflet animé <select data-palier-champ="reflet">'
        f'{_options(theme.REFLETS, rang_theme["reflet"])}</select></label></div>'
        f'<div class="palier__ligne palier__couleurs">'
        f'<label>Fond (haut) <input type="color" value="{_e(c1)}" data-palier-champ="c1"></label>'
        f'<label>Fond (bas) <input type="color" value="{_e(c2)}" data-palier-champ="c2"></label>'
        f'<label>Accent <input type="color" value="{_e(c3)}" data-palier-champ="c3"></label>'
        f'</div>'
        f'<button type="button" class="palier__reinit" data-palier-reinit="{_e(code)}">'
        f'↺ Apparence de départ de ce rang</button>'
        f'</div></article>')


def _html_rang_perso(valeurs, defauts, apercu):
    """Le palier des CARTES PERSONNALISÉES, tout en bas de la liste des rangs : le thème de base appliqué à
    une nouvelle carte créée dans le Créateur de cartes. Ni seuil ni probabilité (il n'est jamais tiré au
    hasard), mais des lettres (5 au maximum), un nom, un motif, trois couleurs et un reflet."""
    rang_theme = valeurs["PERSO_THEME"]
    c1, c2, c3 = rang_theme["couleurs"]
    symbole, nom = valeurs["PERSO_SYMBOLE"], valeurs["PERSO_NOM"]
    return (
        f'<article class="palier palier--perso" data-palier="{_e(config.CODE_PERSO)}" '
        f'data-rarete="{_e(config.CODE_PERSO)}" data-defaut-theme="{_json_attr(defauts["PERSO_THEME"])}" '
        f'data-defaut-symbole="{_e(defauts["PERSO_SYMBOLE"])}" data-defaut-nom="{_e(defauts["PERSO_NOM"])}">'
        f'<div class="palier__apercu" aria-label="Aperçu du palier des cartes personnalisées">{apercu}</div>'
        f'<div class="palier__champs">'
        f'<div class="palier__titre"><span class="palier__code" data-palier-code>{_e(symbole)}</span>'
        f'<label class="palier__symbole-etiquette">Lettres <input type="text" class="palier__symbole" '
        f'maxlength="{theme.SYMBOLE_PERSO_MAX}" value="{_e(symbole)}" size="6" data-palier-champ="symbole" '
        f'aria-label="Lettres du palier des cartes personnalisées ({theme.SYMBOLE_PERSO_MAX} au maximum)" '
        f'autocomplete="off" spellcheck="false"></label>'
        f'<input type="text" class="palier__nom" maxlength="{theme.PALIER_PERSO_MAX}" value="{_e(nom)}" '
        f'data-palier-champ="nom" aria-label="Nom du palier des cartes personnalisées"></div>'
        f'<p class="palier__note"><strong>Cartes personnalisées</strong> (page « Créateur de cartes ») : '
        f'c\'est le thème de base d\'une nouvelle carte créée. Pas de seuil ni de probabilité : ce palier n\'est '
        f'jamais tiré au hasard. Dans le Créateur, on peut aussi appliquer le thème des autres rangs.</p>'
        f'<div class="palier__ligne">'
        f'<label>Motif <select data-palier-champ="motif">'
        f'{_options(theme.MOTIFS, rang_theme["motif"])}</select></label>'
        f'<label>Reflet animé <select data-palier-champ="reflet">'
        f'{_options(theme.REFLETS, rang_theme["reflet"])}</select></label></div>'
        f'<div class="palier__ligne palier__couleurs">'
        f'<label>Fond (haut) <input type="color" value="{_e(c1)}" data-palier-champ="c1"></label>'
        f'<label>Fond (bas) <input type="color" value="{_e(c2)}" data-palier-champ="c2"></label>'
        f'<label>Accent <input type="color" value="{_e(c3)}" data-palier-champ="c3"></label>'
        f'</div>'
        f'<button type="button" class="palier__reinit" data-palier-reinit="{_e(config.CODE_PERSO)}">'
        f'↺ Apparence de départ de ce palier</button>'
        f'</div></article>')


def html_editeur_rangs(valeurs, defauts, apercu):
    """L'éditeur de rangs : nom, seuil, probabilité et apparence de chacun, avec aperçu.
    `apercu(code)` renvoie le HTML d'une carte d'exemple de ce rang."""
    paliers, poids, themes = valeurs["PALIERS"], valeurs["POIDS"], valeurs["THEMES_PALIERS"]
    symboles, symboles_defaut = valeurs["SYMBOLES_PALIERS"], defauts["SYMBOLES_PALIERS"]
    total = sum(poids.values()) or 1
    rangs = []
    for i, (code, seuil, nom) in enumerate(paliers):
        part = f"{poids.get(code, 0) / total * 100:.0f} %"
        rangs.append(_html_rang(
            code, seuil, nom, poids.get(code, 0), part, theme.theme_du_rang(themes, code),
            theme.theme_du_rang(defauts["THEMES_PALIERS"], code),
            dernier=(i == len(paliers) - 1), apercu=apercu(code),
            symbole=symboles.get(code, code), defaut_symbole=symboles_defaut.get(code, code)))
    rangs.append(_html_rang_perso(valeurs, defauts, apercu(config.CODE_PERSO)))      # tout dernier de la liste
    return (
        '<p class="panneau__intro">Chaque rang a un <strong>seuil</strong> (vues par jour '
        'minimum), une <strong>probabilité</strong> (valeurs relatives : 1 et 4 donnent 20 % et '
        '80 %) et sa propre apparence : un <strong>motif</strong>, trois <strong>couleurs</strong> '
        'et un <strong>reflet animé</strong>. Les <strong>lettres</strong> (3 au maximum) sont '
        'celles affichées en haut à gauche des cartes, sur les boutons de filtre et dans les '
        'noms de fichiers exportés. Le <strong>dernier palier de la liste, « Personnalisée »</strong>, est le '
        'thème de base des cartes créées dans le Créateur de cartes (lettres jusqu\'à 5 caractères, nom, '
        'motif, couleurs, reflet) : il n\'a ni seuil ni probabilité. L\'aperçu se met à jour en direct.</p>'
        '<div class="paliers">' + "".join(rangs) + '</div>')


# ----------------------------------------------------------------------- sections

def html_apercu_disposition():
    """Un schéma de la page de collection (maquette) qui montre, en direct, l'effet des quatre réglages de disposition :
    place du menu, taille des boutons, barre d'outils et paquet. Le cadre représente un écran : ce qui dépasse en bas
    n'est pas visible sans défiler, et on voit ainsi combien de cartes apparaissent tout de suite."""
    cases = lambda n, c="": "".join(f"<i{' class=\"' + c + '\"' if c else ''}></i>" for _ in range(n))
    return (
        f'<div class="dispo-apercu" id="dispo-apercu" data-menu-pos="{_e(config.MENU_POSITION)}" '
        f'data-menu="{_e(config.MENU_STYLE)}" data-barre="{_e(config.BARRE_OUTILS)}" '
        f'data-paquet="{_e(config.PAQUET_POSITION)}" data-logo-align="{_e(config.LOGO_ALIGNEMENT)}" data-titre-align="{_e(config.TITRE_ALIGNEMENT)}" '
        f'data-bio-align="{_e(config.BIO_ALIGNEMENT)}" data-infos-align="{_e(config.INFOS_ALIGNEMENT)}" role="img" '
        'aria-label="Maquette de la page : l\'emplacement du menu, de la barre d\'outils et du paquet change selon vos choix">'
        '<p class="dispo-apercu__legende">Maquette en direct <small>(le cadre est l\'écran : ce qui dépasse en bas demande de défiler)</small></p>'
        '<div class="dispo-apercu__ecran"><div class="dispo-apercu__page">'
        '<div class="dispo-apercu__haut">'
        '<div class="dispo-apercu__titre"><i class="dispo-logo"></i><span><b></b><b></b><b></b></span></div>'
        f'<div class="dispo-apercu__menu"><u></u>{cases(6, "dispo-bouton")}</div></div>'
        f'<div class="dispo-apercu__rangs">{cases(6, "dispo-pastille")}</div>'
        '<div class="dispo-apercu__bascule"><i></i></div>'
        f'<div class="dispo-apercu__barre"><i class="dispo-champ"></i>{cases(3, "dispo-liste")}<i class="dispo-curseur"></i></div>'
        '<div class="dispo-apercu__paquet"><i class="dispo-sachet"></i><span><b></b></span></div>'
        f'<div class="dispo-apercu__cartes">{cases(5, "dispo-carte")}</div>'
        '</div></div></div>')


def _lecture_seule():
    lignes = "".join(
        f'<div><dt>{_e(libelle)}</dt><dd>{_e(getattr(config, nom))}</dd></div>'
        for nom, libelle in parametres.LECTURE_SEULE.items())
    return ('<h3>Réglés dans config.py uniquement</h3>'
            '<p class="panneau__intro">Ces réglages ne se modifient pas ici : un mauvais choix '
            'pourrait rendre la page inaccessible.</p>'
            f'<dl class="lecture-seule">{lignes}</dl>')


# ------------------------------------------------------------------- catégories

def _html_categorie(c=None):
    """Un bloc de la liste des catégories : nom, couleur, 5 meta, suppression.
    Sans argument : le bloc vide (modèle utilisé pour « Ajouter une catégorie »)."""
    nouvelle = c is None
    c = c or {"id": "", "nom": "", "couleur": "#6f55ee", "metas": [""] * cat.NB_METAS, "nb_cartes": 0}
    metas = "".join(
        f'<label>Meta {i + 1} <input type="text" maxlength="{cat.LONGUEUR_META_MAX}" '
        f'value="{_e(c["metas"][i])}" data-categorie-champ="meta" data-index="{i}" '
        f'autocomplete="off"></label>' for i in range(cat.NB_METAS))
    nb = c["nb_cartes"]
    compte = f'{nb} carte{"s" if nb > 1 else ""}'
    reclasser = ("" if nouvelle else
                 '<button type="button" class="palier__reinit" data-categorie-reclasser>'
                 'Classer maintenant les cartes existantes qui correspondent</button>')
    return (
        f'<article class="categorie" data-categorie="{_e(c["id"])}">'
        f'<div class="categorie__tete">'
        f'<input type="text" class="categorie__nom" maxlength="{cat.LONGUEUR_NOM_MAX}" '
        f'value="{_e(c["nom"])}" placeholder="Nom de la catégorie" data-categorie-champ="nom" '
        f'aria-label="Nom de la catégorie" autocomplete="off">'
        f'<input type="color" value="{_e(c["couleur"])}" data-categorie-champ="couleur" '
        f'aria-label="Couleur du bandeau">'
        f'<span class="categorie__apercu" data-categorie-apercu title="Aperçu du bandeau sur une carte">'
        f'</span>'
        f'<span class="categorie__compte" data-categorie-compte>{"" if nouvelle else compte}</span>'
        f'<button type="button" class="categorie__supprimer" data-categorie-supprimer>Supprimer</button>'
        f'</div>'
        f'<div class="categorie__metas">{metas}</div>'
        f'<div class="categorie__pied">{reclasser}</div>'
        f'<p class="champ__erreur" data-categorie-erreur role="alert" hidden></p>'
        f'<p class="categorie__supprimee" data-categorie-supprimee hidden>Cette catégorie sera '
        f'supprimée à l\'enregistrement. <strong>Les cartes ne sont pas supprimées</strong> : '
        f'elles sont seulement retirées de la catégorie. '
        f'<button type="button" class="palier__reinit" data-categorie-annuler>Annuler</button></p>'
        f'</article>')


def html_editeur_categories(categories):
    """L'éditeur de catégories de la page Configuration."""
    existantes = "".join(_html_categorie(c) for c in categories)
    return (
        '<h3>Catégories de la collection</h3>'
        '<p class="panneau__intro">Les catégories classent les cartes <strong>en plus des '
        'rangs</strong>. Chacune a un nom, une couleur de bandeau (affiché en tout petit sur les '
        f'cartes) et jusqu\'à {cat.NB_METAS} <strong>meta</strong> : des mots ou expressions '
        'cherchés dans <strong>le titre</strong>, <strong>le sous-titre</strong> (la courte ligne sous le titre) '
        '<strong>et les phrases d\'introduction</strong> des cartes (chacun se règle dans la section Collection : '
        '« Meta : chercher dans… »). Quand tu ouvres un '
        'paquet, les cartes dont le titre, le sous-titre ou les phrases contiennent une meta sont classées '
        'automatiquement dans la catégorie (majuscules et accents ignorés). Pour classer les '
        'cartes à la main, utilise le bouton « Sélection » de la collection. Supprimer une '
        'catégorie <strong>ne supprime jamais les cartes</strong>.</p>'
        f'<div class="categories" id="categories-liste">{existantes}</div>'
        '<p class="categories__vide" id="categories-vide" role="status"'
        f'{" hidden" if categories else ""}>Aucune catégorie pour le moment.</p>'
        '<button type="button" class="bouton-site" id="categorie-ajouter">+ Ajouter une '
        'catégorie</button>'
        f'<template id="modele-categorie">{_html_categorie()}</template>')


def html_themes_site(courant, accent_perso):
    """Une pastille par thème du site : fond, motif, texte et accent (aperçu miniature)."""
    boutons = []
    for code, palette in theme.PALETTES_SITE.items():
        var = [f"--t-fond: {palette['fond']}", f"--t-texte: {palette['texte']}",
               f"--t-accent: {palette['accent'] or accent_perso}"]
        if palette["motif"]:
            var += [f"--t-motif: {palette['motif']}", f"--t-taille: {palette['taille'] or 'auto'}"]
        boutons.append(
            f'<button type="button" class="theme-site" data-theme-choix="{_e(code)}" '
            f'aria-pressed="{"true" if code == courant else "false"}" '
            f'title="{_e(palette["libelle"])}" style="{_e("; ".join(var))}">'
            f'<span class="theme-site__apercu"><span class="theme-site__ligne"></span>'
            f'<span class="theme-site__ligne theme-site__ligne--courte"></span>'
            f'<span class="theme-site__point"></span></span>'
            f'<span class="theme-site__nom">{_e(palette["libelle"])}</span></button>')
    return ('<div class="themes-site" id="themes-site" role="group" '
            'aria-label="Choisir le thème du site">' + "".join(boutons) + "</div>")


def html_reserve(e):
    """Le panneau d'état de la réserve de cartes (pré-chargement) : cartes prêtes, jauge, plafond
    horaire, boutons. Mis à jour toutes les quelques secondes par configuration.js."""
    cible = max(1, e["cible"])
    ratio = min(1.0, e["pretes"] / cible)
    remplissage = ("jamais" if not e["dernier_remplissage"] else
                   time.strftime("%d/%m/%Y à %H:%M", time.localtime(e["dernier_remplissage"])))
    erreur = e["derniere_erreur"]
    return (
        '<div class="reserve" id="reserve-etat">'
        f'<p class="reserve__titre"><strong id="reserve-pretes">{e["pretes"]}</strong> / '
        f'<span id="reserve-cible">{e["cible"]}</span> cartes prêtes · '
        f'<span id="reserve-paquets">{e["paquets_prets"]}</span> paquet(s) d\'avance</p>'
        f'<div class="reserve__jauge" role="progressbar" aria-label="Cartes prêtes" aria-valuemin="0" '
        f'aria-valuemax="{e["cible"]}" aria-valuenow="{e["pretes"]}" id="reserve-jauge-zone">'
        f'<i id="reserve-jauge" style="transform: scaleX({ratio:.3f})"></i></div>'
        '<ul class="reserve__details">'
        f'<li id="reserve-statut">{_e(reserve.texte_statut(e))}</li>'
        f'<li>Requêtes de pré-chargement cette heure : <b id="reserve-budget">'
        f'{e["budget_utilise"]} / {e["budget_max"]}</b></li>'
        f'<li>Dernier remplissage : <span id="reserve-remplissage">{_e(remplissage)}</span></li>'
        f'<li>Statistiques des cartes : <b id="stats-restantes">{e["stats"]["restantes"]}</b> à compléter '
        f'· requêtes cette heure : <b id="stats-budget">{e["stats"]["budget_utilise"]} / '
        f'{e["stats"]["budget_max"]}</b></li>'
        f'<li id="reserve-erreur" class="reserve__erreur"{"" if erreur else " hidden"}>'
        f'Dernier incident : <span id="reserve-erreur-texte">{_e(erreur)}</span></li>'
        '</ul>'
        '<div class="reserve__actions">'
        '<button type="button" class="bouton-site" id="reserve-remplir">Remplir maintenant</button>'
        '<button type="button" class="bouton-site" id="reserve-vider">Vider la réserve</button></div>'
        '<p class="reserve__note">Pré-chargement poli : une requête à la fois, pauses plus longues '
        'que d\'habitude, plafond par heure, arrêt automatique si Wikipédia ralentit, priorité à tes '
        'ouvertures de paquet et à tes recherches. « Remplir maintenant » respecte ces mêmes limites.</p>'
        '</div>')


def html_godpack():
    """Le bouton qui joue l'animation du GOD PACK (feu d'artifice, fanfare, message) pour la voir sans ouvrir de paquet."""
    return ('<div class="godpack-essai" id="godpack-essai-bloc"><button type="button" class="bouton-site" id="godpack-essai">'
            '🎆 Voir l\'animation du GOD PACK</button> <small>Un clic sur le message « GOD PACK !!! » la ferme. Le son suit le réglage '
            'des sons de la page.</small></div>')


def html_acces():
    """L'état de l'accès réseau : verrouillé (cet ordinateur seulement) ou ouvert (adresses à taper, code d'accès, avertissements)."""
    if not acces.mode_reseau():
        return ('<div class="acces" id="acces"><p class="acces__etat acces__etat--ferme">🔒 Accès verrouillé : seul cet ordinateur peut '
                'ouvrir le programme (127.0.0.1). Choisis « Réseau local et extérieur » ci-dessous, enregistre, puis relance le '
                'programme pour l\'ouvrir à un téléphone ou à un tunnel.</p></div>')
    port = acces.PORT["valeur"] or config.PORT_SERVEUR
    etat = dict(acces.TEST["adresses"])
    def ligne(ip):
        if not acces.TEST["adresses"] and acces.TEST["ts"] == 0.0:
            marque = '<small>(vérification en cours…)</small>'
        elif etat.get(ip):
            marque = '<small class="acces__ok">✓ répond</small>'
        else:
            marque = '<small class="acces__ko">⚠ ne répond pas : pare-feu ? (voir ci-dessous)</small>'
        return f'<li><code>http://{_e(ip)}:{port}/</code> {marque}</li>'
    adresses = "".join(ligne(ip) for ip in acces.adresses_locales()) or "<li><small>aucune adresse de réseau local détectée</small></li>"
    code = (f'<p>Code d\'accès défini : tout ce qui ne vient pas de cet ordinateur doit le taper <a href="/deconnexion">(fermer ma session)</a>.</p>'
            if acces.exige_code() else
            '<p class="acces__etat--ouvert">Aucun code : n\'importe quel appareil qui atteint ces adresses utilise le programme '
            '(ouvrir des paquets, modifier la collection...). Ajoute un code ci-dessous si tu veux le limiter.</p>')
    return (
        '<div class="acces" id="acces"><p class="acces__etat acces__etat--ouvert">🌐 Accès réseau ACTIVÉ : le programme est un serveur '
        'sur ton PC ; chaque appareil qui l\'atteint l\'utilise directement (pas besoin d\'y lancer quoi que ce soit).</p>'
        f'<p>Adresses à taper sur un autre appareil du même réseau :</p><ul class="acces__adresses">{adresses}</ul>{code}'
        '<ul class="acces__notes"><li><strong>Une adresse ne répond pas ?</strong> C\'est presque toujours le pare-feu de Windows : '
        'accepte la fenêtre « Autoriser l\'accès » (réseaux privés) ou, dans une invite de commandes en ADMINISTRATEUR : '
        f'<code>{_e(acces.commande_pare_feu(port))}</code>. Les adresses 192.168.56.x (VirtualBox) ou 172.x (WSL/Docker) ne '
        'servent qu\'à ces machines virtuelles.</li>'
        '<li><strong>Depuis l\'extérieur</strong> : un tunnel (ngrok, Cloudflare Tunnel, Tailscale Funnel...) pointé vers '
        f'<code>http://127.0.0.1:{port}</code> fonctionne tel quel, en http comme en https.</li>'
        f'<li><strong>Par ton adresse IP publique</strong> : ouvre le port {port} de ta box vers cet ordinateur (sans HTTPS).</li></ul></div>')


def html_sons():
    """Le bloc des fichiers sons de la section « Sons et musique » : téléverser un fichier, écouter ou supprimer ceux du dossier
    sons/. Les listes des événements (en dessous) proposent ces fichiers."""
    noms = sons.lister()
    return (
        '<div class="sons" id="sons">'
        '<h3>Tes fichiers sons</h3>'
        '<p class="sons__intro">Dépose tes fichiers (mp3, ogg, opus, wav, m4a, aac, flac ou webm, 60 Mo au plus) dans le dossier '
        '<code>sons</code> à côté de <code>main.py</code>, ou téléverse-les ici. Choisis ensuite un fichier pour chaque événement '
        'ci-dessous, puis « Enregistrer ». Aucun son n\'est fourni avec le programme.</p>'
        '<div class="sons__actions"><label class="bouton-site" for="son-fichier">📁 Téléverser un son…</label>'
        '<input type="file" id="son-fichier" class="sr-only" accept="audio/*,.mp3,.ogg,.oga,.opus,.wav,.m4a,.aac,.flac,.webm" multiple>'
        '<span class="sons__etat" id="sons-etat" role="status" aria-live="polite"></span></div>'
        '<ul class="sons__liste" id="sons-liste" aria-label="Fichiers sons">'
        + "".join(_ligne_son(n) for n in noms)
        + ('' if noms else '<li class="sons__vide">Aucun fichier son pour l\'instant.</li>')
        + '</ul></div>')


def _ligne_son(nom):
    taille = ""
    fichier = sons.chemin(nom)
    if fichier is not None:
        octets = fichier.stat().st_size
        taille = f"{octets / 1024 / 1024:.1f} Mo" if octets >= 1024 * 1024 else f"{max(1, octets // 1024)} Ko"
    return (f'<li class="sons__ligne" data-nom="{_e(nom)}"><span class="sons__nom">{_e(nom)}</span>'
            f'<small>{_e(taille)}</small>'
            f'<button type="button" class="bouton-son-essai" data-fichier="{_e(nom)}" aria-label="Écouter {_e(nom)}" '
            'title="Écouter">▶</button>'
            f'<button type="button" class="bouton-site sons__supprimer" data-supprimer="{_e(nom)}">Supprimer</button></li>')


def html_journal():
    """Le bloc « Journal d'activité » de la section Système : activer, ouvrir, supprimer (static/journal.js)."""
    return (
        '<div class="journal" id="journal-bloc">'
        '<h3 class="journal__titre">Journal d\'activité</h3>'
        '<p class="journal__intro">Écrit <strong>tout ce qui se passe</strong> quand tu utilises le logiciel — tes actions et celles du programme — avec la date et l\'heure précises, '
        'dans le fichier <code>journal.log</code> (à la racine du programme), et l\'affiche au fur et à mesure dans la fenêtre de commandes. '
        '<strong>Désactivé : rien n\'est écrit</strong>, ni dans le fichier ni à l\'écran. Aucun code, jeton, clé ni contenu de fichier n\'y est noté.</p>'
        '<label class="journal__case"><input type="checkbox" id="journal-actif"> Journal activé</label>'
        '<p class="journal__etat" id="journal-etat" role="status" aria-live="polite"></p>'
        '<div class="journal__actions">'
        '<button type="button" class="bouton-site" id="journal-ouvrir">📄 Ouvrir le journal</button>'
        '<button type="button" class="bouton-site" id="journal-externe" title="Ouvre journal.log avec l\'application par défaut (Bloc-notes...)">↗ Ouvrir dans le Bloc-notes</button>'
        '<button type="button" class="bouton-site" id="journal-supprimer">🗑 Supprimer le journal</button>'
        '</div>'
        '<p class="journal__message" id="journal-message" role="status" aria-live="polite"></p>'
        '</div>')


def html_lot():
    """Le bloc « Importer des cartes en lot » de la section Système : un bouton qui ouvre la fenêtre d'importation (static/lot.js)."""
    return (
        '<div class="lot" id="lot-bloc">'
        '<h3 class="lot__titre">Importer des cartes en lot</h3>'
        '<p class="lot__intro">Tu as un fichier <strong>.txt</strong> avec un titre d\'article Wikipédia par ligne ? Cette fonction crée les cartes correspondantes, '
        'doucement, sans jamais surcharger Wikipédia : 20 titres par requête, une seule requête à la fois, avec une pause entre deux requêtes '
        '(réglable plus haut : « Importation en lot : pause entre deux requêtes »). Pendant l\'importation, le reste du programme est verrouillé.</p>'
        '<div class="lot__actions"><button type="button" class="bouton-site bouton-site--principal" id="lot-ouvrir">📥 Importer des cartes depuis un fichier .txt</button></div>'
        '<p class="lot__etat" id="lot-bloc-etat" role="status" aria-live="polite"></p>'
        '</div>')


def html_sauvegardes():
    """Le bloc « Sauvegardes » de la section Système : créer (4 types), exporter, importer, restaurer, supprimer."""
    types = "".join(
        f'<label class="sauvegarde-type"><input type="radio" name="sauvegarde-type" value="{_e(code)}"'
        f'{" checked" if code == "complete" else ""}><span><strong>{_e(t["libelle"])}</strong>'
        f'<small>{_e(t["detail"])}</small></span></label>' for code, t in sauvegardes.TYPES.items())
    return (
        '<div class="sauvegardes" id="sauvegardes">'
        '<h3>Sauvegardes</h3>'
        '<p class="sauvegardes__intro">Une sauvegarde est un fichier .zip que tu peux garder, copier ou importer sur un autre '
        'ordinateur. Avant toute restauration, l\'état actuel est sauvegardé automatiquement (« avant-restauration »). '
        'La clé secrète d\'identité du Hall n\'est dans aucune sauvegarde, sauf si tu la demandes pour une sauvegarde '
        'ultra complète.</p>'
        f'<fieldset class="sauvegardes__types"><legend>Créer une sauvegarde</legend>{types}'
        '<label class="sauvegardes__cle" id="sauvegarde-cle-ligne" hidden><input type="checkbox" id="sauvegarde-cle">'
        '<span>Inclure la <strong>clé secrète d\'identité</strong> du Hall des collections (permet de retrouver ton identité '
        'sur un autre ordinateur ; <strong>ne partage jamais ce fichier</strong>)</span></label>'
        '<div class="sauvegardes__actions"><button type="button" class="bouton-site bouton-site--principal" '
        'id="sauvegarde-creer">Créer la sauvegarde</button>'
        '<label class="bouton-site" for="sauvegarde-fichier">📥 Importer une sauvegarde (.zip)…</label>'
        '<input type="file" id="sauvegarde-fichier" class="sr-only" accept=".zip,application/zip"></div></fieldset>'
        '<p class="sauvegardes__etat" id="sauvegardes-etat" role="status" aria-live="polite"></p>'
        '<div class="sauvegardes__confirmation" id="sauvegarde-confirmation" role="alertdialog" '
        'aria-labelledby="sauvegarde-confirmation-texte" hidden><p id="sauvegarde-confirmation-texte"></p>'
        '<div class="sauvegardes__actions"><button type="button" class="bouton-site bouton-site--principal" '
        'id="sauvegarde-confirmer">Confirmer</button><button type="button" class="bouton-site" '
        'id="sauvegarde-annuler">Annuler</button></div></div>'
        '<h4>Sauvegardes disponibles</h4>'
        '<ul class="sauvegardes__liste" id="sauvegardes-liste" aria-live="polite"><li class="sauvegardes__vide">Chargement…</li></ul>'
        '</div>')


def html_sections(valeurs, defauts, apercu, categories=None, apercu_booster="", etat_reserve=None, avance_visible=True):
    """Toutes les sections de la page Configuration."""
    sections = []
    for code_groupe, titre in parametres.GROUPES:
        if not avance_visible and code_groupe in parametres.GROUPES_AVANCES:
            continue                                       # réglages avancés : pas pour une adresse hors du réseau local
        if code_groupe == "raretes":
            contenu = html_editeur_rangs(valeurs, defauts, apercu)
        else:
            contenu = '<div class="champs">' + "".join(
                html_champ(param, valeurs[param.nom], defauts[param.nom])
                for param in parametres.PARAMETRES.values() if param.groupe == code_groupe
            ) + '</div>'
        if code_groupe == "apparence":
            contenu = (html_themes_site(valeurs["THEME_SITE"], valeurs["COULEUR_ACCENT"])
                       + contenu)
        if code_groupe == "reserve" and etat_reserve is not None:
            contenu = html_reserve(etat_reserve) + contenu
        if code_groupe == "paquets":
            contenu += apercu_booster
        if code_groupe == "disposition":
            contenu = html_apercu_disposition() + contenu
        if code_groupe == "collection":
            contenu += html_editeur_categories(categories or [])
        if code_groupe == "systeme":
            contenu += _lecture_seule() + html_journal() + html_lot() + html_sauvegardes()
        if code_groupe == "sons":
            contenu = html_sons() + contenu
        if code_groupe == "reseau":
            contenu = html_acces() + contenu
        if code_groupe == "paquets":
            contenu = html_godpack() + contenu
        avance = " panneau--avance" if code_groupe in parametres.GROUPES_AVANCES else ""
        explication = parametres.GROUPES_EXPLICATION.get(code_groupe, "")
        sections.append(f'<section class="panneau{avance}" id="groupe-{_e(code_groupe)}" tabindex="-1" '
                        f'aria-labelledby="titre-{_e(code_groupe)}">'
                        f'<h2 id="titre-{_e(code_groupe)}">{_e(titre)}'
                        f'{" <span class=\"panneau__etiquette\">avancé</span>" if avance else ""}</h2>'
                        f'<p class="panneau__resume">{_e(explication)}</p>{contenu}</section>')
    if not avance_visible:
        sections.append('<section class="panneau" id="avance-masque"><p class="panneau__resume">Les réglages avancés (Wikipédia, Réserve, '
                        'Hall des collections, Accès réseau, Système) ne sont visibles que depuis cet ordinateur et le réseau local.</p></section>')
    return "\n".join(sections)


def html_navigation_sections(avance_visible=True):
    """Le menu « Aller à » du haut de la page Configuration : un lien par section, dans l'ordre de la page ; les réglages
    avancés sont séparés des autres. Le script suit la section visible (aria-current)."""
    liens, avances = [], []
    for code, _ in parametres.GROUPES:
        if not avance_visible and code in parametres.GROUPES_AVANCES:
            continue
        lien = (f'<li><a href="#groupe-{_e(code)}" data-section="{_e(code)}">'
                f'{_e(parametres.GROUPES_COURTS.get(code, code))}</a></li>')
        (avances if code in parametres.GROUPES_AVANCES else liens).append(lien)
    return ('<nav class="config-nav" id="config-nav" aria-label="Aller à une section de la configuration">'
            '<span class="config-nav__titre">Aller à</span>'
            f'<ul class="config-nav__liste">{"".join(liens)}</ul>'
            '<span class="config-nav__titre config-nav__titre--avance">Avancé</span>'
            f'<ul class="config-nav__liste config-nav__liste--avance" aria-label="Réglages avancés">{"".join(avances)}</ul>'
            '</nav>')
