"""Boutons de l'en-tête du site (en haut à droite de chaque page).

Pour ajouter un bouton plus tard, il suffit d'ajouter une ligne à BOUTONS_ENTETE :
- "libelle" : le texte du bouton ;   - "icone" : un petit symbole devant le texte ;
- "url" : la page vers laquelle il mène ;
- "pages" : les pages où le bouton est affiché ("collection", "configuration", ...).
"""

import html

BOUTONS_ENTETE = [
    {"id": "paquets", "libelle": "Paquets", "icone": "🎴", "url": "/paquets",
     "pages": ("collection", "configuration", "recherche", "corbeille", "profil", "createur", "hall")},
    {"id": "collection", "libelle": "Collection", "icone": "▦", "url": "/",
     "pages": ("paquets", "configuration", "recherche", "corbeille", "profil", "createur", "hall")},
    {"id": "profil", "libelle": "Profil", "icone": "☺", "url": "/profil",
     "pages": ("paquets", "collection", "configuration", "recherche", "corbeille", "profil", "createur", "hall")},
    {"id": "createur", "libelle": "Créateur de cartes", "icone": "✚", "url": "/createur",
     "pages": ("paquets", "collection", "configuration", "recherche", "corbeille", "profil", "createur", "hall")},
    {"id": "recherche", "libelle": "Recherche", "icone": "⌕", "url": "/recherche",
     "pages": ("paquets", "collection", "configuration", "recherche", "corbeille", "profil", "createur", "hall")},
    {"id": "hall", "libelle": "Hall des collections", "icone": "⬡", "url": "/hall",
     "pages": ("paquets", "collection", "configuration", "recherche", "corbeille", "profil", "createur", "hall")},
    {"id": "configuration", "libelle": "Configuration", "icone": "⚙", "url": "/configuration",
     "pages": ("paquets", "collection", "configuration", "recherche", "corbeille", "profil", "createur", "hall")},
]

# Icône « double corbeille » : une petite corbeille derrière une autre (traits seulement : la
# couleur vient du texte du bouton, grise quand la corbeille est vide, rouge sinon).
_PATH_CORBEILLE = ("M3 7h18M9 7V4.5c0-.3.2-.5.5-.5h5c.3 0 .5.2.5.5V7M5.5 7l.9 12.4c.1 1 .8 1.6 "
                   "1.8 1.6h7.6c1 0 1.7-.6 1.8-1.6L18.5 7")
ICONE_CORBEILLE = (
    '<svg class="corbeille__icone" viewBox="0 0 28 26" fill="none" stroke="currentColor" '
    'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    f'<g opacity=".5" transform="translate(9 -1.2) scale(.78)"><path d="{_PATH_CORBEILLE}"/></g>'
    f'<g transform="translate(-.5 2.2) scale(.95)"><path d="{_PATH_CORBEILLE}M10 11v6M14 11v6"/>'
    '</g></svg>')
ICONE_VALIDE = (
    '<svg class="corbeille__valide" viewBox="0 0 52 52" fill="none" stroke="currentColor" '
    'stroke-width="4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle class="corbeille__valide-cercle" cx="26" cy="26" r="22"/>'
    '<path class="corbeille__valide-trait" d="M15 27l8 8 15-17"/></svg>')


def texte_corbeille(nombre):
    """« La corbeille est vide. » ou « 3 cartes dans la corbeille. »"""
    if nombre <= 0:
        return "La corbeille est vide."
    return f"{nombre} carte{'s' if nombre > 1 else ''} dans la corbeille."


def html_corbeille(nombre, page_courante=""):
    """L'icône corbeille (grise avec « (0) » si elle est vide, rouge avec « (N) » sinon) et la
    petite fenêtre qui s'ouvre au clic : contenu de la corbeille, « Restaurer tout » et le bouton
    rouge « Supprimer définitivement ». Le JavaScript est dans static/corbeille.js."""
    nombre = max(0, int(nombre))
    etat = "pleine" if nombre else "vide"
    cache = "" if nombre else " hidden"
    # Après une restauration, la collection et la corbeille doivent se mettre à jour ;
    # après un vidage définitif, seule la page de la corbeille change.
    recharge_restauration = "1" if page_courante in ("collection", "corbeille", "profil") else "0"
    recharge_vidage = "1" if page_courante == "corbeille" else "0"
    libelle = "Corbeille : vide" if not nombre else f"Corbeille : {nombre} carte{'s' if nombre > 1 else ''}"
    return (
        f'<div class="corbeille corbeille--{etat}" id="corbeille-zone" data-nombre="{nombre}" '
        f'data-recharge-restauration="{recharge_restauration}" data-recharge-vidage="{recharge_vidage}">'
        f'<button type="button" class="bouton-site bouton-corbeille" id="corbeille-bouton" '
        f'aria-haspopup="dialog" aria-expanded="false" aria-controls="corbeille-info" '
        f'aria-label="{libelle}" title="Corbeille">{ICONE_CORBEILLE}'
        f'<span class="corbeille__nombre" id="corbeille-nombre">({nombre})</span></button>'
        f'<div class="corbeille__info" id="corbeille-info" role="dialog" aria-label="Corbeille" hidden>'
        f'<p class="corbeille__titre">Corbeille</p>'
        f'<p class="corbeille__etat" id="corbeille-etat" role="status">{texte_corbeille(nombre)}</p>'
        f'<div class="corbeille__actions" id="corbeille-actions"{cache}>'
        f'<button type="button" class="corbeille__supprimer" id="corbeille-vider">'
        f'Supprimer définitivement</button>'
        f'<button type="button" class="bouton-site" id="corbeille-restaurer">Restaurer tout</button>'
        f'</div>'
        f'<a class="corbeille__lien" href="/corbeille">Voir les cartes de la corbeille</a>'
        f'<div class="corbeille__succes" id="corbeille-succes" role="status" hidden>'
        f'{ICONE_VALIDE}<span id="corbeille-succes-texte">La corbeille est vide !</span></div>'
        f'<p class="corbeille__erreur" id="corbeille-erreur" role="alert" hidden></p>'
        f'</div></div>')


def html_actions(page_courante, corbeille=0):
    """La zone de boutons en haut à droite : <nav class="actions-site">, avec l'icône corbeille
    (`corbeille` : nombre de cartes qu'elle contient)."""
    boutons = []
    for bouton in BOUTONS_ENTETE:
        if page_courante not in bouton["pages"]:
            continue
        courant = ' aria-current="page"' if bouton["id"] == page_courante else ""
        boutons.append(
            f'<a class="bouton-site" href="{html.escape(bouton["url"], quote=True)}"{courant} '
            f'title="{html.escape(bouton["libelle"], quote=True)}">'
            f'<span class="bouton-site__icone" aria-hidden="true">{html.escape(bouton["icone"])}</span> '
            f'<span class="bouton-site__texte">{html.escape(bouton["libelle"])}</span></a>')
    # La case et l'étiquette « ☰ Menu » ne servent qu'avec le style de menu « Replié » (sans JavaScript : case à cocher).
    return ('<div class="menu-site">'
            '<input type="checkbox" id="menu-bascule" class="menu-bascule__case" aria-controls="menu-navigation">'
            '<label for="menu-bascule" class="bouton-site menu-bascule" title="Afficher ou masquer le menu">'
            '<span aria-hidden="true">☰</span> <span>Menu</span></label>'
            '<nav class="actions-site" id="menu-navigation" aria-label="Navigation du site">'
            + "".join(boutons) + html_corbeille(corbeille, page_courante) + "</nav></div>")
