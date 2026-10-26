"""Génération de la page HTML de cartes à partir des articles tirés.

Le HTML vient de templates/ (page.html, carte.html), le style de static/cartes.css
et le comportement de static/cartes.js. La page produite est autonome : CSS et JS
sont intégrés dans le fichier, on peut donc la déplacer ou la partager telle quelle.
"""

import copy
import html
import json
import re
from collections import Counter
from datetime import datetime
from string import Template
from urllib.parse import quote

from . import (base, booster, cadrage, config, createur, export, favicon, formulaire, fullart, projet, images, logo, navigation, p2p_annuaire,
               p2p_identite, parametres, qr, reserve, sensible, sons, stats, theme, web)
from . import categories as cat

ESPACE_MILLIERS = "\u202f"   # espace fine insécable


def _lire(dossier, nom):
    return (dossier / nom).read_text(encoding="utf-8")


# Affichage TÉLÉPHONE : un petit script, lancé avant le premier affichage de la page, détecte un écran étroit ou tactile (ou obéit au réglage
# « toujours » / « jamais ») et adapte les réglages de disposition de la page : menu en icônes, filtres repliés, menu au centre. Les
# autres règles (en-tête, cartes sur deux colonnes...) sont dans cartes.css, section « Affichage téléphone ». Les choix d'origine sont
# rétablis si l'écran redevient large.
SCRIPT_MOBILE = (
    '(function(){var h=document.documentElement,m=h.getAttribute("data-mobile")||"auto";if(m==="jamais"||!window.matchMedia){return;}'
    'var q=window.matchMedia("(max-width: 720px), (pointer: coarse) and (max-width: 960px)"),o=null,'
    'N={m:"data-menu",b:"data-barre",p:"data-menu-pos",l:"data-logo-align"},V={m:"icones",b:"repliable",p:"centre",l:"gauche"};'
    'function a(){var on=m==="toujours"||q.matches,k;if(on){if(!o){o={};for(k in N){o[k]=h.getAttribute(N[k]);}}'
    'for(k in N){h.setAttribute(N[k],V[k]);}h.setAttribute("data-mobile-actif","1");}'
    'else if(o){for(k in N){if(o[k]===null){h.removeAttribute(N[k]);}else{h.setAttribute(N[k],o[k]);}}o=null;h.removeAttribute("data-mobile-actif");}}'
    'a();if(q.addEventListener){q.addEventListener("change",a);}else if(q.addListener){q.addListener(a);}})();')
# Grands écrans : --zoom-ecran (1 jusqu'à 1800 px de large, 2,2 au plus), recalculé quand la fenêtre change ou que l'affichage téléphone change.
SCRIPT_ECHELLE = (
    '(function(){var h=document.documentElement;function e(){var w=window.innerWidth||0,z=1;'
    'if(w>=1800&&h.getAttribute("data-mobile-actif")!=="1"){z=Math.min(2.2,Math.round(w/1800*20)/20);}'
    'h.style.setProperty("--zoom-ecran",String(z));}e();window.addEventListener("resize",e);'
    'if(window.MutationObserver){new MutationObserver(e).observe(h,{attributes:true,attributeFilter:["data-mobile-actif"]});}})();')


TITRES_DE_PAGE = {"collection": "Collection", "paquets": "Paquets", "profil": "Profil", "createur": "Créateur de cartes",
                  "recherche": "Recherche", "config": "Configuration", "corbeille": "Corbeille", "hall": "Hall des collections"}


def _ajouter_titre_de_page(page):
    """Sous la ligne de biographie (ou, sans biographie, sous le titre) : le nom de la page affichée, pour qu'on sache toujours où l'on est."""
    m = re.search(r'<main class="page ([^"]*)"', page)
    if not m:
        return page
    classes = m.group(1).split()
    nom = next((TITRES_DE_PAGE[c[6:]] for c in classes if c.startswith("page--") and c[6:] in TITRES_DE_PAGE), None)
    if nom is None:
        return page
    if "page--visite" in classes:
        nom = "Hall des collections · collection visitée"
    ligne = f'<p class="entete__page">{_echapper(nom)}</p>'
    suite = re.search(r'<p class="entete__bio"[^>]*>.*?</p>', page, flags=re.S) or re.search(r"</h1>", page)
    if not suite:
        return page
    return page[:suite.end()] + ligne + page[suite.end():]


class _Page(Template):
    """Gabarit d'une PAGE entière : ajoute à la balise <html> les attributs de disposition choisis dans la Configuration
    (menu, barre d'outils, paquet) ; le CSS (cartes.css, section « Disposition ») s'en sert. Ainsi toutes les pages les
    reçoivent, sans toucher chaque gabarit."""

    def substitute(self, *args, **kwargs):
        page = super().substitute(*args, **kwargs)
        page = page.replace('<html lang="fr"', '<html lang="fr" ' + attributs_disposition(accueil=bool(projet.prendre_accueil() and config.ACCUEIL_AFFICHER)), 1)
        page = _ajouter_titre_de_page(page)
        return page.replace("<head>", "<head>\n" + favicon.lien_html() + "<script>" + SCRIPT_MOBILE + SCRIPT_ECHELLE + "</script>", 1)       # avant le premier affichage : pas de saut


def reglages_sons():
    """Les réglages des sons pour le script de la page : interrupteur, volume, fichier de chaque événement (seulement ceux
    qui existent), musique d'ambiance."""
    evenements = {}
    for reglage, cle in sons.EVENEMENTS.items():
        nom = getattr(config, reglage, "")
        if nom and sons.chemin(nom) is not None:
            evenements[cle] = nom
    musique = config.MUSIQUE_FICHIER if config.MUSIQUE_FICHIER and sons.chemin(config.MUSIQUE_FICHIER) is not None else ""
    return {"actifs": bool(config.SONS_ACTIFS), "volume": int(config.SONS_VOLUME), "evenements": evenements,
            "boucles": {"effet": bool(config.SON_EFFET_PAQUET_BOUCLE)},          # (seul le son d'effet du paquet peut se jouer en boucle)
            "musique": {"actif": bool(config.MUSIQUE_ACTIVE and musique), "fichier": musique,
                        "volume": int(config.MUSIQUE_VOLUME), "coupee": bool(config.MUSIQUE_COUPEE)}}


def musique_dans_le_lecteur():
    """La musique d'ambiance est-elle activée (avec un fichier qui existe) ? Alors chaque page s'affiche dans le LECTEUR : une
    fenêtre du haut, qui garde la musique en continu quand on change de page."""
    return bool(reglages_sons()["musique"]["actif"])


def page_lecteur(adresse, jeton=""):
    """La page du lecteur : un cadre plein écran qui affiche `adresse` (la page demandée), et, par-dessus, le haut-parleur et le
    curseur de volume de la musique (sons.js). Le cadre est de même origine : l'adresse et le titre affichés suivent la page."""
    contenu = (
        '<!DOCTYPE html>\n<html lang="fr" data-theme="{theme}" data-accent="{accent}" data-survol="{survol}" '
        'data-anim-zoom="{zoom}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n<meta name="color-scheme" content="dark light">\n'
        '<title>{titre}</title>\n<style>{css}\nhtml, body {{ height: 100%; margin: 0; background: var(--page-fond); }}\n'
        '.lecteur__cadre {{ display: block; width: 100%; height: 100%; border: 0; background: var(--page-fond); }}</style>\n'
        '</head>\n<body class="lecteur" data-jeton="{jeton}">\n'
        '<iframe id="cadre" class="lecteur__cadre" src="{adresse}" title="{titre}" '
        'allow="clipboard-read; clipboard-write; fullscreen"></iframe>\n<script>\n{js}\n</script>\n</body>\n</html>\n')
    page = contenu.format(
        theme=_echapper(config.THEME_SITE), accent=_echapper(_accent_mode()), survol=_echapper(config.EFFET_SURVOL),
        zoom=_echapper(config.ANIMATION_ZOOM), titre=_echapper(config.TITRE_SITE), css=_css_complet(), jeton=_echapper(jeton),
        adresse=_echapper(adresse), js=_js("cadre.js"))
    page = page.replace('<html lang="fr"', '<html lang="fr" ' + attributs_disposition(), 1)
    return page.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + favicon.lien_html(), 1)       # (le cadre du lecteur : même icône)


def attributs_disposition(accueil=False):
    """Les attributs de <html>. `accueil` : le message de bienvenue s'affiche avec CETTE page (la première depuis le lancement, voir projet.prendre_accueil)."""
    return (f'style="--flou:{max(4, min(40, int(config.FLOU_FORCE)))}" '
            f'data-mobile="{_echapper(config.MOBILE_MODE)}" data-mobile-entete="{_echapper(config.MOBILE_ENTETE)}" '
            f'data-sons="{_echapper(json.dumps(reglages_sons(), ensure_ascii=False, separators=(",", ":")))}" '
            f'data-menu-pos="{_echapper(config.MENU_POSITION)}" data-menu="{_echapper(config.MENU_STYLE)}" '
            f'data-barre="{_echapper(config.BARRE_OUTILS)}" data-paquet="{_echapper(config.PAQUET_POSITION)}" '
            f'data-paquet-survol="{_echapper(config.BOOSTER_SURVOL)}" data-paquet-repos="{_echapper(config.BOOSTER_REPOS)}" '
            f'data-logo-align="{_echapper(config.LOGO_ALIGNEMENT)}" '
            f'data-titre-align="{_echapper(config.TITRE_ALIGNEMENT)}" data-bio-align="{_echapper(config.BIO_ALIGNEMENT)}" '
            f'data-infos-align="{_echapper(config.INFOS_ALIGNEMENT)}" '
            f'data-accueil="{"1" if accueil else "0"}" data-demarrage="{projet.DEMARRAGE}" '
            f'data-logo-accueil="{_echapper(logo.source() or "")}"')


def _echapper(texte):
    return html.escape(str(texte), quote=True)


def _nombre(valeur):
    """1250 -> '1 250' (espace fine insécable)."""
    return f"{round(valeur):,}".replace(",", ESPACE_MILLIERS)


def _html_image(art):
    """Renvoie (balise <img>, attribut hidden du visuel de secours)."""
    if art["miniature"] == "no-image":
        return "", ""           # pas d'image : le visuel de secours reste affiché
    balise = (f'<img class="carte__image" src="{_echapper(art["miniature"])}"{cadrage.attributs(art.get("cadrage"))} '
              f'alt="{_echapper(art["titre"])}" loading="lazy" decoding="async" '
              f'referrerpolicy="no-referrer">')
    return balise, " hidden"    # visuel de secours masqué tant que l'image charge


# Boutons en haut à droite des cartes (affichés selon les réglages ICONE_PNG, ICONE_PDF, ICONE_WORD)
BOUTON_PNG = (
    '<button class="carte__sauver" type="button" aria-label="Enregistrer la carte en image" title="Enregistrer la carte en image PNG (dossier Export)">\n<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 3h11l4 4v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M8 3v5h8V3"/><path d="M7 21v-7h10v7"/></svg>\n</button>'
)
BOUTON_PDF = (
    '<button class="carte__pdf" type="button" aria-label="Enregistrer la carte en PDF recto verso" title="Enregistrer en PDF recto verso, prêt à imprimer (dossier Export)">\n<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="1.5" y="1.5" width="21" height="21" rx="4.5" fill="#e5252a"/><text x="12" y="15.4" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="8.2" font-weight="700" fill="#fff">PDF</text></svg>\n</button>'
)
BOUTON_WORD = (
    '<button class="carte__word" type="button" aria-label="Enregistrer la carte en document Word recto verso" title="Enregistrer en document Word recto verso, prêt à imprimer (dossier Export)">\n<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="1.5" y="1.5" width="21" height="21" rx="4.5" fill="#2b579a"/><path d="M5.2 7.8l2.7 8.6 4.1-7.4 4.1 7.4 2.7-8.6" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>\n</button>'
)


BOUTON_SENSIBLE = (
    '<button class="carte__sensible" type="button" aria-pressed="false" aria-label="Montrer l\'image (contenu sensible)" '
    'title="Contenu sensible, interdit aux moins de 18 ans : l\'image est floutée. Clique pour la montrer ou la flouter de nouveau.">'
    '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9.6"/><path d="M5.2 18.8 18.8 5.2"/>'
    '<text x="12" y="15.3" text-anchor="middle" font-size="8.6" font-weight="800" font-family="sans-serif" fill="currentColor" '
    'stroke="none">18</text></svg></button>')
BOUTON_RAFRAICHIR = (
    '<button class="carte__rafraichir" type="button" aria-label="Rafraîchir l\'image de l\'article" '
    'title="Choisir l\'illustration de la carte parmi toutes les images de l\'article (ou la retirer)">'
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a9 9 0 0 0-15-6.7L3 8"/><path d="M3 3v5h5"/>'
    '<path d="M3 12a9 9 0 0 0 15 6.7l3-2.7"/><path d="M16 16h5v5"/></svg></button>')


def _bouton_place(html, classe, rang):
    """Un bouton d'export à son emplacement : `rang` 1 = juste sous l'étoile (favori), 2 = en dessous, 3 = encore en dessous.
    Seuls les boutons ACTIVÉS comptent : un seul bouton coché se place juste sous l'étoile, sans trou."""
    return html.replace(f'<button class="{classe}"', f'<button class="{classe}" style="--emplacement:{int(rang)}"', 1)


# Icônes colorées des statistiques (SVG intégrés à chaque carte : ils survivent à l'export en image)
_SVG = '<svg class="carte__stat-icone" viewBox="0 0 24 24" aria-hidden="true">{}</svg>'
ICONES_STATS = {
    "langues": _SVG.format(
        '<circle cx="12" cy="12" r="9.5" fill="#d8ecff" stroke="#1f7ae0" stroke-width="1.8"/>'
        '<ellipse cx="12" cy="12" rx="4.2" ry="9.5" fill="none" stroke="#1f7ae0" stroke-width="1.5"/>'
        '<path d="M2.9 8.8h18.2M2.9 15.2h18.2M12 2.5v19" fill="none" stroke="#1f7ae0" stroke-width="1.5"/>'),
    "revisions": _SVG.format(
        '<path d="M4.2 19.8l1-4.4L16.4 4.2a2.2 2.2 0 013.1 0l.3.3a2.2 2.2 0 010 3.1L8.6 18.8z" '
        'fill="#aab0ba" stroke="#4b5563" stroke-width="1.3" stroke-linejoin="round"/>'
        '<path d="M14.7 5.9l3.4 3.4" stroke="#4b5563" stroke-width="1.3"/>'
        '<path d="M4.2 19.8l1-4.4 3.4 3.4z" fill="#f3d2ad" stroke="#4b5563" stroke-width="1.2" '
        'stroke-linejoin="round"/><path d="M4.2 19.8l.65-2.9 2.25 2.25z" fill="#e5484d"/>'),
    "liens": _SVG.format(
        '<path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" fill="none" '
        'stroke="#7e57c2" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" fill="none" '
        'stroke="#7e57c2" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/>'),
    "taille": _SVG.format(
        '<path d="M6 2.5h8.5L19 7v13.5a.5.5 0 01-.5.5h-12a.5.5 0 01-.5-.5z" fill="#e6dcfb" '
        'stroke="#7e57c2" stroke-width="1.6" stroke-linejoin="round"/>'
        '<path d="M14.5 2.5V7H19" fill="#b9a5ef" stroke="#7e57c2" stroke-width="1.4" '
        'stroke-linejoin="round"/>'
        '<path d="M8.5 11.2h7M8.5 14.2h7M8.5 17.2h4.5" stroke="#7e57c2" stroke-width="1.4" '
        'stroke-linecap="round"/>'),
    "horloge": _SVG.format(
        '<circle cx="12" cy="12" r="9.5" fill="none" stroke="#b5651d" stroke-width="2"/>'
        '<path d="M12 6.5V12l3.6 2.2" fill="none" stroke="#b5651d" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"/>'),
}


def vues_carte(vues_par_jour):
    """Vues par jour affichées sur la carte : le nombre entier (« 2 064 ») jusqu'à 9 999, puis
    compact (« 12k », « 1.2M »). Ainsi le pied de la carte garde la même forme pour toutes les
    cartes ; le nombre exact reste dans l'info-bulle."""
    vues = round(vues_par_jour)
    return _nombre(vues) if vues < 10_000 else nombre_compact(vues)


def nombre_compact(valeur):
    """52 -> « 52 », 1234 -> « 1.2k », 12345 -> « 12k », 1500000 -> « 1.5M »."""
    valeur = int(valeur)
    if valeur < 1000:
        return str(valeur)
    if valeur < 999_500:
        texte = f"{valeur / 1000:.1f}" if valeur < 9950 else str(round(valeur / 1000))
        return texte.rstrip("0").rstrip(".") + "k" if "." in texte else texte + "k"
    return f"{valeur / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


def taille_ko(octets):
    """Taille d'un article : 43008 octets -> « 42 » (Ko) ; 7000 -> « 6.8 » ; 1,5 Mo -> « 1.5 Mo »."""
    ko = int(octets) / 1024
    if ko < 10:
        return f"{ko:.1f}".rstrip("0").rstrip(".") or "0"
    if round(ko) < 1000:
        return str(round(ko))
    return f"{ko / 1024:.1f}".rstrip("0").rstrip(".") + " Mo"


def _stat(genre, texte, titre):
    """Une statistique du pied de carte : icône + nombre (ou « – » si pas encore récupérée)."""
    valeur = f"<b>{texte}</b>" if texte is not None else '<b class="carte__stat-vide">–</b>'
    return (f'<span class="carte__stat carte__stat--{genre}" title="{_echapper(titre)}" '
            f'aria-label="{_echapper(titre)}">{ICONES_STATS[genre]}{valeur}</span>')


def stats_completes(art):
    """Toutes les statistiques de la carte sont-elles connues ?"""
    return all(art.get(cle) is not None
               for cle in ("nb_langues", "taille_octets", "nb_revisions", "nb_liens_entrants"))


def html_stats(art):
    """Les quatre statistiques du pied de carte (que des chiffres, avec une info-bulle) : langues
    disponibles, modifications de la page, liens entrants, taille de l'article en Ko."""
    langues = art.get("nb_langues")
    revisions = art.get("nb_revisions")
    liens = art.get("nb_liens_entrants")
    taille = art.get("taille_octets")
    return "".join((
        _stat("langues", None if langues is None else nombre_compact(langues),
              "Langues disponibles : donnée pas encore récupérée" if langues is None else
              f"{langues} édition{'s' if langues > 1 else ''} de Wikipédia (langues disponibles)"),
        _stat("revisions",
              None if revisions is None else nombre_compact(revisions) + ("+" if art.get("revisions_plafonnees") else ""),
              "Modifications de la page : donnée pas encore récupérée" if revisions is None else
              (f"{_nombre(revisions)} modifications de la page ou plus" if art.get("revisions_plafonnees")
               else f"{_nombre(revisions)} modification{'s' if revisions > 1 else ''} de la page")),
        _stat("liens", None if liens is None else nombre_compact(liens),
              "Liens entrants : donnée pas encore récupérée" if liens is None else
              f"{_nombre(liens)} page{'s' if liens > 1 else ''} de Wikipédia "
              f"pointe{'nt' if liens > 1 else ''} vers cet article"),
        _stat("taille", None if taille is None else taille_ko(taille),
              "Taille de l'article : donnée pas encore récupérée" if taille is None else
              f"Taille de l'article : {taille_ko(taille)} Ko ({_nombre(taille)} octets)"
              if not taille_ko(taille).endswith("Mo") else
              f"Taille de l'article : {taille_ko(taille)} ({_nombre(taille)} octets)")))


def _html_horodatage(art):
    """Date et heure du tirage, sur une seule ligne : « 13/10/26 14:32:05 ».
    Sur une carte étroite, le CSS masque l'année puis la date pour que tout tienne."""
    tire_le = art.get("tire_le")
    if tire_le is None:
        return ""
    return (f'<time class="carte__horodatage" '
            f'datetime="{tire_le.isoformat(timespec="seconds")}" '
            f'title="{"Créée" if art.get("personnalisee") else "Tiré"} le {tire_le:%d/%m/%Y à %H:%M:%S}">'
            f'{ICONES_STATS["horloge"]}'
            f'<span class="carte__horodatage-date">{tire_le:%d/%m}'
            f'<span class="carte__horodatage-annee">{tire_le:/%y}</span></span> '
            f'<span>{tire_le:%H:%M:%S}</span></time>')


def _html_lien(art):
    if not art["url"]:
        return ""
    return (f'<a class="carte__lien" href="{_echapper(art["url"])}" target="_blank" '
            f'rel="noopener noreferrer" title="Lire l\'article sur Wikipédia" '
            f'aria-label="Lire l\'article sur Wikipédia"><svg viewBox="0 0 24 24" '
            f'fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6"/>'
            f'<path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7'
            f'a1 1 0 0 1 1-1h5"/></svg></a>')


def _svg_qr(art):
    """QR code (SVG) pointant vers l'article Wikipédia, ou "" s'il n'y a pas de lien.

    Il n'est pas affiché sur la carte : il est stocké dans l'attribut data-qr, et la
    page (cartes.js) ne l'utilise que pour le VERSO des documents PDF et Word.
    On reprend celui enregistré dans la base ; à défaut, on le calcule."""
    if art.get("personnalisee") and web.url_http(art.get("url") or "") is None:
        return ""                           # carte sans adresse : pas de QR code
    return art.get("qr_svg") or qr.svg_article(art.get("url"), art["titre"])


def _categories_de_la_carte(art):
    """Les catégories à afficher sur la carte : celles qu'elle a déjà (dont le bandeau « Doublon »),
    plus « Sans illustration » si besoin (pour les cartes qui ne viennent pas de la base : recherche)."""
    liste = list(art.get("categories") or [])
    position = 1 if liste and liste[0].get("id") == 0 else 0
    if base.sans_illustration(art) and not any(c.get("id") == -3 for c in liste):
        liste.insert(position, base.bandeau_sans_illustration())
        position += 1
    if base.animee(art) and not any(c.get("id") == -4 for c in liste):
        liste.insert(position, base.bandeau_animee())
    return liste


def _html_carte(art, modele, vitrine=False, createur=False, recherche=False, visiteur=False):
    """Le HTML d'une carte. `vitrine` : copie épurée pour la page de profil. `createur` : aperçu du
    Créateur de cartes (sans boutons ni agrandissement : la carte n'est qu'un visuel). `recherche` : carte
    d'un résultat de recherche : en bas, SEULEMENT les vues par jour (ni statistiques, ni date et heure :
    on ne dépense aucune requête Wikipédia pour des cartes qui ne sont pas encore dans la collection).
    `visiteur` : carte de la collection d'UN AUTRE collectionneur (Hall des collections) : sa carte telle qu'il la
    montre (lettres, thème et statistiques à lui), sans étoile ni icônes d'export (rien ne s'exporte, rien ne se modifie),
    avec la case de sélection pour la rapatrier."""
    perso = bool(art.get("personnalisee"))
    style = theme.style_perso(art.get("style")) if perso else None
    image, sans_image_hidden = _html_image(art)
    # Les icônes se suivent sous l'étoile, sans trou : +18 (carte sensible), rafraîchir (si activé), puis PNG, PDF, Word
    sensible_carte = (not createur) and sensible.carte_sensible(art)
    rang_icone = 1                                    # (la carte sans étoile — collection visitée, recherche — garde les mêmes places : le lien ↗ prend
                                                      #  le coin, les icônes se suivent dessous : voir « data-sans-etoile » plus bas)
    place = {}
    for nom, actif in (("sensible", sensible_carte and config.FLOU_ICONE),
                       ("rafraichir", config.ICONE_RAFRAICHIR and not (visiteur or createur or recherche or vitrine or bool(art.get("fullart")))),
                       ("png", config.ICONE_PNG), ("pdf", config.ICONE_PDF), ("word", config.ICONE_WORD)):
        if actif:
            place[nom] = rang_icone
            rang_icone += 1
    description = ""
    if art["description"] != "no-description":
        description = (f'<p class="carte__description">'
                       f'{_echapper(art["description"])}</p>')
    intro = ""
    if art["intro"] != "no-intro":
        intro = f'<p class="carte__intro">{_echapper(art["intro"])}</p>'

    favori = bool(art.get("favori"))
    rang_theme = (style if perso else art.get("theme_force")
                  or theme.theme_du_rang(config.THEMES_PALIERS, art["rarete"]))
    symbole = style["symbole"] if perso else (art.get("symbole_force") or config.symbole(art["rarete"]))
    source_http = perso and web.url_http(art.get("url") or "") is not None
    html = modele.substitute(
        motif=_echapper(rang_theme["motif"]),
        reflet=_echapper(rang_theme["reflet"]),
        id=_echapper(art.get("id") or ""),
        favori_etat="true" if favori else "false",
        favori_libelle="Retirer des favoris" if favori else "Ajouter aux favoris",
        code=_echapper(art["rarete"]),
        symbole=_echapper(symbole),
        badge_long=" carte__badge--long" if len(symbole) > 3 else "",
        style_carte=(f' style="{_echapper(theme.style_en_ligne(style["couleurs"]))}"' if perso else ""),
        categories=cat.html_bandeaux(_categories_de_la_carte(art)),
        etiquette=art.get("etiquette", ""),
        bouton_sensible=_bouton_place(BOUTON_SENSIBLE, "carte__sensible", place["sensible"]) if "sensible" in place else "",
        bouton_rafraichir=_bouton_place(BOUTON_RAFRAICHIR, "carte__rafraichir", place["rafraichir"]) if "rafraichir" in place else "",
        bouton_png=_bouton_place(BOUTON_PNG, "carte__sauver", place["png"]) if "png" in place else "",
        bouton_pdf=_bouton_place(BOUTON_PDF, "carte__pdf", place["pdf"]) if "pdf" in place else "",
        bouton_word=_bouton_place(BOUTON_WORD, "carte__word", place["word"]) if "word" in place else "",
        stats=html_stats(art) if config.STATS_CARTES and not perso and not recherche else "",
        stats_etat=("aucune" if not config.STATS_CARTES or perso or recherche or visiteur else
                    "complet" if stats_completes(art) else "incomplet"),
        rarete_nom=_echapper(style["palier"] if perso else art["rarete_nom"]),
        titre=_echapper(art["titre"]),
        titre_attr=_echapper(art["titre"]),
        fichier=_echapper(export.nom_fichier(art)),
        initiale=_echapper(art["titre"].strip()[:1].upper() or "?"),
        image=image,
        sans_image_hidden=sans_image_hidden,
        description=description,
        intro=intro,
        vues=vues_carte(art["vues_moyenne"]),
        vues_titre=_echapper(f'{_nombre(art["vues_total"])} vues sur '
                             f'{config.JOURS_VUES} jours'),
        horodatage="" if recherche else _html_horodatage(art),
        qr_attr=_echapper(_svg_qr(art)),
        lien=(_html_lien(art) if config.ICONE_LIEN and not vitrine and (not perso or source_http)
              else ""),
    )
    if sensible_carte:                                   # image floutée d'office ; l'icône +18 la montre ou la floute de nouveau
        montree = art.get("url") in sensible.reveles()    # ... sauf si l'utilisateur l'a déjà montrée (état gardé)
        html = html.replace('<article class="carte"', f'<article class="carte" data-sensible="1" data-flou="{0 if montree else 1}"', 1)
        if montree:
            html = re.sub(r'(<button class="carte__sensible"[^>]*?)aria-pressed="false"', r'\1aria-pressed="true"', html, count=1)
    if perso:
        html = _pied_de_carte_personnalisee(html, art)
    if visiteur:
        html = _epurer_carte_visiteur(html)
    if recherche:
        html = re.sub(r'\s*<span class="carte__stats"></span>', "", html)
        html = html.replace('<footer class="carte__pied">', '<footer class="carte__pied carte__pied--vues">', 1)
    if vitrine:
        html = _epurer_carte_de_vitrine(html)
    fa = art.get("fullart")
    if fa and not createur and (not visiteur or fa.get("pair")):     # carte full-art : calques PNG et effets, sous les textes (chez un autre : relayés)
        graine = art.get("id") or art.get("titre")
        calques = fullart.html_calques(fa, graine)
        if calques:
            html = html.replace('<div class="carte__corps">', calques + '<div class="carte__corps">', 1)
            html = re.sub(r'(<article class="carte"[^>]*)>', lambda m: m.group(1) + fullart.attributs(fa, graine) + ">", html, count=1)
    if createur:
        html = _epurer_apercu_createur(html)
    elif recherche or 'class="carte__favori"' not in html:   # pas d'étoile visible (collection d'un autre, recherche) : le lien ↗ va dans le coin en haut à droite
        html = re.sub(r'(<article class="carte"[^>]*)>', r'\1 data-sans-etoile="1">', html, count=1)   # (à la fin de la balise : rien ne se décale)
    return html


def _pied_de_carte_personnalisee(html, art):
    """Le pied d'une carte personnalisée : son surnom à gauche, la date et l'heure de sa validation
    à droite. Rien d'autre (elle ne représente pas un article : ni vues, ni statistiques)."""
    surnom = _echapper(art.get("surnom") or "")
    pied = (f'<footer class="carte__pied carte__pied--perso"><span class="carte__surnom" '
            f'title="{surnom}">{surnom}</span>{_html_horodatage(art)}</footer>')
    return re.sub(r'<footer class="carte__pied">.*?</footer>', lambda _: pied, html, count=1, flags=re.S)


def _epurer_carte_visiteur(html):
    """Carte d'un autre collectionneur : ni étoile, ni export (disquette, PDF, Word). Le lien vers l'article,
    l'agrandissement et la case de sélection restent."""
    for classe in ("carte__sauver", "carte__pdf", "carte__word", "carte__favori", "carte__rafraichir"):
        html = re.sub(r'\s*<button class="%s".*?</button>' % classe, "", html, flags=re.S)
    return html


def _epurer_apercu_createur(html):
    """Aperçu du Créateur : la carte seule, sans boutons, agrandissement, étoile ni case."""
    html = re.sub(r'\s*<a class="carte__lien".*?</a>', "", html, flags=re.S)
    for classe in ("carte__sauver", "carte__pdf", "carte__word", "carte__favori", "carte__zoom", "carte__sensible",
                   "carte__rafraichir"):
        html = re.sub(r'\s*<button class="%s".*?</button>' % classe, "", html, flags=re.S)
    html = re.sub(r'\s*<label class="carte__selection".*?</label>', "", html, flags=re.S)
    return html.replace('<article class="carte"', '<article class="carte carte--apercu"', 1)


def _epurer_carte_de_vitrine(html):
    """Une carte de VITRINE est une copie d'affichage, épurée : ni lien vers Wikipédia, ni boutons
    d'export, ni catégories, ni pied (vues par jour, statistiques, date et heure). Restent
    l'illustration, le rang, le titre, la description et l'introduction (et l'étoile des favoris)."""
    html = re.sub(r'\s*<a class="carte__lien".*?</a>', "", html, flags=re.S)
    for classe in ("carte__sauver", "carte__pdf", "carte__word"):
        html = re.sub(r'\s*<button class="%s".*?</button>' % classe, "", html, flags=re.S)
    html = re.sub(r'\s*<div class="carte__categories">.*?</div>', "", html, flags=re.S)
    html = re.sub(r'\s*<footer class="carte__pied[^"]*">.*?</footer>', "", html, flags=re.S)
    html = html.replace('<article class="carte"', '<article class="carte carte--vitrine"', 1)
    return html.replace('data-stats="complet"', 'data-stats="aucune"').replace(
        'data-stats="incomplet"', 'data-stats="aucune"')


def comptes_depuis(articles):
    """Comptes d'une liste de cartes : ({code du rang: nombre}, nombre de favoris)."""
    return (dict(Counter(art["rarete"] for art in articles)),
            sum(1 for art in articles if art.get("favori")))


def html_resume(comptes, nb_favoris, filtre_rangs=(), favoris_seulement=False):
    """Boutons de filtre : un par rang présent dans la collection, plus « Favoris ».
    `comptes` : {code du rang: nombre de cartes} sur TOUTE la collection."""
    codes = list(config.CODES) + sorted(set(comptes) - set(config.CODES))
    lignes = []
    for code in codes:
        if comptes.get(code):
            actif = "true" if code in filtre_rangs else "false"
            lignes.append(
                f'        <li><button type="button" class="pastille" '
                f'data-rarete="{_echapper(code)}" data-filtre="{_echapper(code)}" '
                f'aria-pressed="{actif}"><span class="pastille__code">'
                f'{_echapper(config.symbole(code))}</span>'
                f'<span class="pastille__rang">{_echapper(config.nom_rang(code))} × <span class="pastille__n">{comptes[code]}</span></span>'
                f'</button></li>')
    if comptes:
        lignes.append(
            f'        <li><button type="button" class="pastille pastille--favoris" '
            f'data-filtre="favoris" aria-pressed="{"true" if favoris_seulement else "false"}">'
            f'<span class="pastille__code">★</span>'
            f'<span class="pastille__rang">Favoris × <span id="nb-favoris" class="pastille__n">{nb_favoris}</span></span></button></li>')
    return "\n".join(lignes)


def texte_infos(total, filtre=None):
    """Phrase affichée sous le titre. `filtre` : nombre de cartes correspondant aux filtres."""
    base_texte = f'{total} carte{"s" if total > 1 else ""} dans la collection'
    if filtre is not None and filtre != total:
        base_texte = f'{filtre} carte{"s" if filtre > 1 else ""} affichée{"s" if filtre > 1 else ""} sur {total}'
    return f'{base_texte} · Wikipédia ({config.LANGUE}) · page du {datetime.now():%d/%m/%Y à %H:%M}'


def html_pagination(page, pages, chemin="/"):
    """Pagination : « ‹ 1 2 [3] 4 … 12 › » (liens ?page=N). Rien s'il n'y a qu'une page.
    `chemin` : la page qui est paginée (« / » pour la collection, « /corbeille »...)."""
    if pages <= 1:
        return ""

    def adresse(n):
        return chemin if n == 1 else f"{chemin}?page={n}"

    def element(n, texte, libelle, courant=False, inactif=False):
        if inactif:
            return f'<span class="pagination__lien pagination__lien--inactif" aria-hidden="true">{texte}</span>'
        marque = ' aria-current="page"' if courant else ""
        return (f'<a class="pagination__lien" href="{adresse(n)}" aria-label="{libelle}"{marque}>'
                f'{texte}</a>')

    numeros = sorted({1, pages} | {n for n in range(page - 2, page + 3) if 1 <= n <= pages})
    morceaux = [element(page - 1, "‹", "Page précédente", inactif=(page == 1))]
    precedent = 0
    for n in numeros:
        if n - precedent > 1:
            morceaux.append('<span class="pagination__points" aria-hidden="true">…</span>')
        morceaux.append(element(n, str(n), f"Page {n}", courant=(n == page)))
        precedent = n
    morceaux.append(element(page + 1, "›", "Page suivante", inactif=(page == pages)))
    return ('<nav class="pagination" aria-label="Pagination de la collection">'
            + "".join(morceaux) + "</nav>")


def _html_tri(courant):
    """Liste déroulante « Trier » : l'ordre d'affichage de la collection."""
    if courant not in base.TRIS:
        courant = base.TRI_DEFAUT
    options = "".join(
        f'<option value="{_echapper(code)}"{" selected" if code == courant else ""}>'
        f'{_echapper(libelle)}</option>' for code, (libelle, _) in base.TRIS.items())
    return (f'<label class="outil outil--tri" for="tri-collection"><span>Trier</span>'
            f'<select id="tri-collection" data-defaut="{_echapper(base.TRI_DEFAUT)}">{options}</select></label>')


def _html_filtre_categorie(categories, courante, nb_doublons=0, compteurs=None):
    """Liste déroulante « Catégorie » : toutes, sans catégorie, doublons (catégorie automatique),
    ou une catégorie, chacune avec son nombre de cartes entre parenthèses : « Sport (4) ».
    `compteurs` : {"": toute la collection, "-1": sans catégorie, "-2": doublons, "<id>": cartes
    de la catégorie} (voir base.compteurs_categories). Le nom est gardé dans data-nom pour que la
    page puisse mettre le nombre à jour sans recharger."""
    compteurs = dict(compteurs or {})
    compteurs.setdefault("-2", nb_doublons)
    for c in categories:
        compteurs.setdefault(str(c["id"]), c.get("nb_cartes"))
    options = [('', "Toutes les catégories"), ('-1', "Sans catégorie")]
    if config.DOUBLONS_ACTIFS:
        options.append(('-2', config.NOM_DOUBLONS))
    if config.SANS_ILLUSTRATION_ACTIF:
        options.append(('-3', config.NOM_SANS_ILLUSTRATION))
    if config.ANIMEE_ACTIF:
        options.append(('-4', config.NOM_ANIMEE))
    options += [(str(c["id"]), c["nom"]) for c in categories]
    valeur = "" if courante is None else str(courante)
    lignes = "".join(
        f'<option value="{_echapper(v)}" data-nom="{_echapper(nom)}"'
        f'{" selected" if v == valeur else ""}>{_echapper(nom)}'
        f'{f" ({compteurs[v]})" if compteurs.get(v) is not None else ""}</option>'
        for v, nom in options)
    return (f'<label class="outil" for="filtre-categorie"><span>Catégorie</span>'
            f'<select id="filtre-categorie">{lignes}</select></label>')


def _html_panneau_selection(categories):
    """Barre qui apparaît en mode « Sélection » : classer les cartes cochées dans des catégories."""
    if categories:
        liste = "".join(
            f'<label class="selection-categorie"><input type="checkbox" value="{c["id"]}" '
            f'data-selection-categorie><span class="carte__categorie" style="background: '
            f'{c["couleur"]}; color: {theme.couleur_lisible(theme.luminance(c["couleur"]))}">'
            f'{_echapper(c["nom"])}</span></label>' for c in categories)
    else:
        liste = ('<p class="barre-selection__vide">Aucune catégorie : crée-en dans la page '
                 '<a href="/configuration">Configuration</a>.</p>')
    return (
        '<div class="barre-selection" id="barre-selection" role="region" '
        'aria-label="Classer les cartes sélectionnées" hidden>'
        '<span class="barre-selection__compte" id="selection-compte" role="status">'
        'Aucune carte sélectionnée</span>'
        '<button type="button" class="bouton-site" id="selection-tout">Tout sélectionner</button>'
        '<button type="button" class="bouton-site" id="selection-aucun">Tout désélectionner</button>'
        '<details class="barre-selection__categories" id="selection-categories">'
        '<summary class="bouton-site">Catégories <span id="selection-nb-categories">(0)</span>'
        f'</summary><div class="barre-selection__liste">{liste}</div></details>'
        '<button type="button" class="bouton-site bouton-site--principal" id="selection-ajouter" '
        'disabled>Ajouter</button>'
        '<button type="button" class="bouton-site" id="selection-retirer" disabled>Retirer</button>'
        '<button type="button" class="corbeille__supprimer" id="selection-supprimer" disabled '
        'title="Déplace les cartes cochées dans la corbeille (elles pourront être restaurées)">'
        'Supprimer</button>'
        '</div>')


def fragments_cartes(cartes):
    """HTML de plusieurs cartes (cadres compris), prêt à être inséré dans la grille."""
    modele = Template(_lire(config.DOSSIER_TEMPLATES, "carte.html"))
    return "\n".join(_html_carte(art, modele) for art in cartes)


def _css_complet():
    """Le CSS de la page : feuille de style + thème généré d'après la configuration."""
    return (_lire(config.DOSSIER_STATIC, "cartes.css") + "\n"
            + theme.css_themes_site() + "\n"
            + theme.css_theme(config.THEMES_PALIERS, config.ANGLES_CARTES,
                              config.ANGLES_SITE, config.COULEUR_ACCENT, perso=config.PERSO_THEME))


def _accent_mode():
    """« theme » : l'accent propre au thème choisi ; « perso » : COULEUR_ACCENT (data-accent de <html>)."""
    return "theme" if config.ACCENT_DU_THEME else "perso"


def image_paquet():
    """(adresse, ratio) de l'image du paquet personnalisé si elle existe sur le disque, sinon None. `ratio` : largeur / hauteur
    de l'image (borné), pour que le paquet prenne ses proportions sans attendre son chargement."""
    nom = images.nom_depuis_adresse(config.BOOSTER_IMAGE)
    if not nom or images.chemin(nom) is None:
        return None
    taille = images.dimensions_fichier(nom)
    return config.BOOSTER_IMAGE, (images.ratio_borne(*taille) if taille else 1.0)


def _marque_paquet_image(logo_src, texte, contenu, apercu):
    """Ce qu'on place SUR l'image du paquet : rien, le logo ou le texte. En aperçu (Configuration) les deux existent et le
    script montre celui qui est choisi."""
    if apercu:
        return ('<span class="booster__marque booster__marque--image" data-booster-marque-image>'
                f'<img class="booster__logo" alt="" draggable="false" data-booster-logo-image'
                f'{f" src={chr(34)}{_echapper(logo_src)}{chr(34)}" if logo_src else ""}'
                f'{"" if contenu == "logo" else " hidden"}>'
                f'<span class="booster__texte {booster.classe_texte(texte)}" data-booster-texte-image'
                f'{"" if contenu == "texte" else " hidden"}>{_echapper(texte)}</span></span>')
    if contenu == "logo" and logo_src:
        return ('<span class="booster__marque booster__marque--image">'
                f'<img class="booster__logo" src="{_echapper(logo_src)}" alt="" draggable="false"></span>')
    if contenu == "texte":
        return ('<span class="booster__marque booster__marque--image">'
                f'<span class="booster__texte {booster.classe_texte(texte)}">{_echapper(texte)}</span></span>')
    return ""


def html_booster_image(image, ratio, logo_src, texte, apercu=False, cache=False):
    """Le paquet PERSONNALISÉ : ton image (PNG ou JPEG), dans la forme choisie (proportions de l'image, rectangle vertical ou
    horizontal, carré, rond), avec, au choix, rien, le logo ou le texte par-dessus. Les animations d'ouverture s'appliquent à
    l'ensemble quelle que soit l'image."""
    return (
        '<span class="paquet__corps paquet__corps--image" data-variante="image" '
        f'data-forme="{_echapper(config.BOOSTER_FORME)}" data-ajustement="{_echapper(config.BOOSTER_AJUSTEMENT)}" '
        f'style="--ratio: {ratio}"{" hidden" if cache else ""}>'
        '<span class="booster booster--image">'
        f'<img class="booster__fond" src="{_echapper(image)}" alt="" draggable="false" data-booster-fond>'
        f'{_marque_paquet_image(logo_src, texte, config.BOOSTER_IMAGE_CONTENU, apercu)}'
        '<span class="paquet__reflet" aria-hidden="true"></span>'
        '<span class="paquet__flash" aria-hidden="true"></span>'
        '</span></span>')


def html_booster(logo_src, texte, theme_booster, apercu=False):
    """Le sachet : un fond (selon le style choisi) qui ne porte QUE le logo, ou, sans logo, un
    mot ou une phrase. `apercu` : version de la page Configuration, qui contient les deux
    (le logo et le texte) pour pouvoir passer de l'un à l'autre sans recharger la page.
    Avec le style « image » (paquet personnalisé) : ton image ; sans image téléversée, le style classique."""
    personnalise = image_paquet() if theme_booster == booster.THEME_IMAGE else None
    if theme_booster == booster.THEME_IMAGE:
        theme_booster = "classique"
    if personnalise and not apercu:
        return html_booster_image(personnalise[0], personnalise[1], logo_src, texte) + booster.PARTICULES_HTML
    if apercu:                                        # les deux versions : le script montre celle qui est choisie
        image = image_paquet()
        autre = html_booster_image(image[0], image[1], logo_src, texte, apercu=True, cache=not personnalise) if image else \
            html_booster_image("", 1.0, logo_src, texte, apercu=True, cache=True)
        return _html_booster_classique(logo_src, texte, theme_booster, True, cache=bool(personnalise)) + autre + booster.PARTICULES_HTML
    return _html_booster_classique(logo_src, texte, theme_booster, False) + booster.PARTICULES_HTML


def _html_booster_classique(logo_src, texte, theme_booster, apercu=False, cache=False):
    if apercu:
        marque = (f'<img class="booster__logo" alt="" draggable="false" data-booster-logo'
                  f'{f" src={chr(34)}{_echapper(logo_src)}{chr(34)}" if logo_src else " hidden"}>'
                  f'<span class="booster__texte {booster.classe_texte(texte)}" '
                  f'data-booster-texte{" hidden" if logo_src else ""}>{_echapper(texte)}</span>')
    elif logo_src:
        marque = (f'<img class="booster__logo" src="{_echapper(logo_src)}" alt="" '
                  f'draggable="false">')
    else:
        marque = (f'<span class="booster__texte {booster.classe_texte(texte)}">'
                  f'{_echapper(texte)}</span>')
    return (
        f'<span class="paquet__corps" data-variante="classique"{" hidden" if cache else ""}>'
        f'<span class="booster" data-booster="{_echapper(theme_booster)}">'
        '<span class="booster__crans booster__crans--haut" aria-hidden="true"></span>'
        '<span class="booster__crans booster__crans--bas" aria-hidden="true"></span>'
        f'<span class="booster__marque">{marque}</span>'
        '<span class="paquet__reflet" aria-hidden="true"></span>'
        '<span class="paquet__flash" aria-hidden="true"></span>'
        '</span></span>')


# Halo doré qui fait le tour d'une carte révélée (CSS : section « Halo » de cartes.css). Même HTML
# dans static/cartes.js (HALO_HTML) : un test vérifie qu'ils restent identiques.
HALO_HTML = ('<span class="halo" aria-hidden="true"><span class="halo__lueur"></span>'
             '<span class="halo__anneau"><span class="halo__tour"></span></span></span>')


def _halo_duree():
    """Durée du halo en secondes : toujours 0, le halo doré des nouvelles cartes a été retiré (plus d'option)."""
    return 0


def _style_halo():
    """Variables CSS du halo (durée et couleurs, la plus claire étant calculée) pour <body>."""
    rvb = theme.hex_vers_rvb(config.HALO_COULEUR)
    clair = tuple(round(c + (255 - c) * .55) for c in rvb)
    return (f"--halo-duree: {_halo_duree()}s; --halo-couleur: {config.HALO_COULEUR}; "
            f"--halo-clair: #{clair[0]:02x}{clair[1]:02x}{clair[2]:02x}; "
            f"--halo-rgb: {', '.join(str(c) for c in rvb)}")


def _html_decompte():
    """Le décompte (secondes avant l'ouverture), masqué tant qu'aucun paquet ne s'ouvre. Le
    JavaScript l'affiche et le met à jour d'après l'avancement envoyé par le serveur."""
    return ('<div class="paquet__decompte" id="paquet-decompte" role="timer" aria-live="off" hidden>'
            '<span class="paquet__decompte-libelle" id="paquet-decompte-libelle">Ouverture dans</span>'
            '<span class="paquet__decompte-valeur"><b id="paquet-decompte-nombre">0</b> s</span>'
            '<span class="paquet__decompte-barre" aria-hidden="true">'
            '<i id="paquet-decompte-progres"></i></span></div>')


def texte_stock(prets, capacite):
    """« 1 paquet prêt sur 10 » (accord compris) : le stock de paquets qu'on peut ouvrir tout de suite."""
    pluriel = "s" if prets > 1 else ""
    return f"{prets} paquet{pluriel} prêt{pluriel} sur {capacite}"


def _html_attente_paquet(statut):
    """Le décompte jusqu'au PROCHAIN paquet, en minutes ET secondes, sous la légende : visible tant que le stock n'est pas plein
    (le script le fait défiler chaque seconde et le recale d'après /api/reserve/ouverture)."""
    secondes = int(statut["secondes"])
    return ('<div class="paquet__attente" id="paquet-attente" role="timer" aria-live="off"'
            f'{"" if secondes else " hidden"} data-secondes="{secondes}">'
            '<span class="paquet__attente-libelle">Prochain paquet dans</span>'
            f'<span class="paquet__attente-valeur"><b id="paquet-attente-minutes">{int(statut["minutes"])}</b> min '
            f'<b id="paquet-attente-secondes">{int(statut["reste"]):02d}</b> s</span>'
            f'<span class="paquet__attente-detail" id="paquet-attente-detail">{_echapper(statut["raison"])}</span></div>')


def html_fenetre_paquet():
    """La fenêtre au milieu de l'écran où les cartes d'un paquet apparaissent une à une avant d'entrer dans la collection :
    on peut en retirer (elles sont supprimées tout de suite), puis « Ajouter à la collection »."""
    return (
        '<div class="fenetre-paquet" id="fenetre-paquet" role="dialog" aria-modal="true" aria-labelledby="fenetre-paquet-titre" hidden>'
        '<div class="fenetre-paquet__boite" id="fenetre-paquet-boite">'
        '<h2 class="fenetre-paquet__titre" id="fenetre-paquet-titre">Ton paquet</h2>'
        '<p class="fenetre-paquet__aide" id="fenetre-paquet-aide">Retire avec ✕ les cartes que tu ne veux pas garder (elles sont '
        'supprimées tout de suite), puis ajoute le reste à ta collection.</p>'
        '<div class="fenetre-paquet__grille" id="fenetre-paquet-grille"></div>'
        '<p class="fenetre-paquet__etat" id="fenetre-paquet-etat" role="status" aria-live="polite"></p>'
        '<div class="fenetre-paquet__actions"><button type="button" class="bouton-site bouton-site--principal" '
        'id="fenetre-paquet-ajouter">Ajouter à la collection</button></div></div></div>')


def _html_paquet(logo_src):
    """Le booster de la page principale (bouton) : le logo du jeu, rien d'autre sur le sachet."""
    nombre = config.NOMBRE_CARTES_PAQUET
    pluriel = "s" if nombre > 1 else ""
    try:
        statut = reserve.statut_ouverture()
    except Exception:                                  # base illisible : on n'empêche jamais d'afficher la page
        statut = {"bloque": False, "secondes": 0, "minutes": 0, "reste": 0, "texte": "", "raison": "", "prets": None}
    bloque = bool(statut["bloque"])
    # Tant que la réserve n'est pas complète, on ne dit PAS combien de cartes contient le paquet ni combien on pourra en ouvrir
    prets = statut.get("prets")
    texte_prets = (f" · {texte_stock(prets, statut['capacite'])}" if isinstance(prets, int) else "")
    legende = (f'<span class="paquet__legende">Ouvrir un paquet <small>· {nombre} carte{pluriel}'
               f'<span id="paquet-prets">{_echapper(texte_prets)}</span></small></span>' if config.BOOSTER_LEGENDE else "")
    decompte = bool(config.BOOSTER_DECOMPTE)
    # Sans légende, on garde de la place sous le sachet pour que le décompte n'y empiète pas
    reserve_cls = " zone-paquet--reserve" if decompte and not config.BOOSTER_LEGENDE else ""
    etiquette = (f"Paquet indisponible : prochain paquet dans {statut['minutes']} minutes et {statut['reste']} secondes" if bloque
                 else f"Ouvrir un paquet de {nombre} carte{pluriel}")
    capacite = int(statut.get("capacite") or 0)
    return (
        f'<section class="zone-paquet{reserve_cls}" aria-label="Ouvrir un paquet de cartes">'
        f'<button type="button" id="paquet" class="paquet" '
        f'data-animation="{_echapper(config.BOOSTER_ANIMATION)}" '
        f'data-animations="{_echapper(booster.json_animations())}" '
        f'data-decompte="{"1" if decompte else "0"}" '
        f'data-bloque="{"1" if bloque else "0"}" data-bloque-actif="{"1" if reserve.bloque_actif() else "0"}" '
        f'data-fenetre="{"1" if config.PAQUET_FENETRE else "0"}" '
        f'data-libelle="{_echapper(f"Ouvrir un paquet de {nombre} carte{pluriel}")}" data-nombre-cartes="{nombre}" '
        f'data-capacite="{capacite}" '
        f'aria-label="{_echapper(etiquette)}"{" aria-disabled=\"true\"" if bloque else ""}>'
        '<span class="paquet__lueur" aria-hidden="true"></span>'
        f'{html_booster(logo_src, config.BOOSTER_TEXTE, config.BOOSTER_THEME)}'
        f'{legende}</button>{_html_attente_paquet(statut) if reserve.bloque_actif() else ""}'
        f'{_html_decompte() if decompte else ""}</section>'
        f'{html_fenetre_paquet() if config.PAQUET_FENETRE else ""}')


def html_apercu_booster(logo_src):
    """Aperçu du booster dans la page Configuration, avec un bouton pour tester l'animation."""
    return (
        '<div class="booster-televersement" id="paquet-image">'
        '<p class="booster-televersement__titre">Ton propre paquet <small>(image PNG ou JPEG)</small></p>'
        '<div class="booster-televersement__ligne">'
        '<label class="bouton-site" for="paquet-image-fichier">📁 Choisir une image…</label>'
        '<input type="file" id="paquet-image-fichier" class="sr-only" accept="image/png,image/jpeg">'
        f'<button type="button" class="bouton-site" id="paquet-image-retirer"{"" if image_paquet() else " hidden"}>'
        'Retirer l\'image</button>'
        '<span class="booster-televersement__etat" id="paquet-image-etat" role="status" aria-live="polite"></span></div>'
        '<p class="booster-televersement__aide">5 Mo au plus ; une très grande image est réduite automatiquement. Après le '
        'téléversement, le style « Image personnalisée » est choisi pour toi : règle ensuite la forme (proportions de '
        'l\'image, rectangle, carré, rond), le cadrage et ce qu\'on place dessus (rien, le logo ou le texte). Les animations '
        'd\'ouverture s\'adaptent à ton image.</p></div>'
        '<div class="booster-apercu" id="booster-apercu" '
        f'data-animations="{_echapper(booster.json_animations())}">'
        f'<div class="paquet paquet--apercu" id="booster-apercu-paquet" '
        f'data-animation="{_echapper(config.BOOSTER_ANIMATION)}">'
        '<span class="paquet__lueur" aria-hidden="true"></span>'
        f'{html_booster(logo_src, config.BOOSTER_TEXTE, config.BOOSTER_THEME, apercu=True)}</div>'
        '<div class="booster-apercu__texte"><p>Aperçu : change le style, le texte ou le logo '
        'ci-dessus, tout se met à jour ici.</p>'
        '<button type="button" class="bouton-site" id="booster-tester">'
        '▶ Tester l\'animation</button></div></div>')


def _tailles_titre():
    """Taille du titre et de la biographie (px) : la biographie est toujours plus petite."""
    titre = int(config.TITRE_TAILLE)
    return titre, max(1, min(int(config.BIO_TAILLE), titre - 1))


def _html_logo_entete(logo_src):
    """Le logo en haut à gauche de la page (lien vers la collection), ou rien sans logo."""
    if not logo_src:
        return ""
    return (f'<a class="entete__logo" href="/" aria-label="Accueil">'
            f'<img src="{_echapper(logo_src)}" alt="Logo" draggable="false"></a>')


def _style_entete():
    titre, bio = _tailles_titre()
    hauteur = max(24, min(int(config.LOGO_HAUTEUR), 160))
    return f"--titre-taille: {titre}px; --bio-taille: {bio}px; --logo-hauteur: {hauteur}px"


def _html_bio():
    texte = (config.BIO_SITE or "").strip()
    return f'<p class="entete__bio">{_echapper(texte)}</p>' if texte else ""


def _js(*fichiers):
    """Les scripts des pages, mis bout à bout (chacun est autonome). La corbeille d'abord."""
    communs = ("sons.js", "defilement.js", "sensible.js", "disposition.js", "godpack.js", "cadrage.js", "accueil.js")
    fichiers = communs + tuple(f for f in fichiers if f not in communs)       # les sons et la musique : sur TOUTES les pages
    return "\n".join(_lire(config.DOSSIER_STATIC, nom) for nom in fichiers)


def _nb_corbeille():
    """Nombre de cartes dans la corbeille (0 si la base n'est pas lisible)."""
    try:
        with base.connexion_rapide() as conn:
            return base.compter_corbeille(conn)
    except (OSError, base.sqlite3.Error):
        return 0


def _impression():
    """Réglages d'impression (PDF et Word), avec des garde-fous contre les valeurs absurdes."""
    return {
        "largeur_mm": max(30, min(float(config.IMPRESSION_LARGEUR_MM), 150)),
        "dpi": max(72, min(int(config.IMPRESSION_DPI), 600)),
        "marge_mm": max(0, min(float(config.IMPRESSION_MARGE_MM), 30)),
        "reperes": bool(config.IMPRESSION_REPERES),
        # QR code : au moins 15 mm, et au plus la moitié de la carte, pour que le logo reste
        # toujours plus grand que lui
        "qr_mm": max(15, min(float(config.IMPRESSION_QR_MM), float(config.IMPRESSION_LARGEUR_MM) / 2)),
    }


def html_pied_page():
    """La mention de bas de page, centrée (réglage MENTION_AFFICHER), ou rien : « Gratuit. Contenu encyclopédique issu de Wikipédia, sous licence libre
    (CC BY-SA). WikiFreeCards, logiciel sous licence MIT, Copyright (c) 2026 Damballah Oueddo. », avec ses trois liens (nouvelle fenêtre). Son texte
    n'est pas modifiable (voir projet.py)."""
    if not config.MENTION_AFFICHER:
        return ""
    return f'<footer class="pied-page" role="contentinfo"><p>{projet.mention_html()}</p></footer>'


def _source_logo(logo_src):
    """None : le logo choisi dans la configuration ; "" : aucun ; sinon l'adresse donnée."""
    return logo.source() if logo_src is None else (logo_src or None)


def _html_demo(demo):
    """Données de démonstration du paquet (fichier d'aperçu ouvert sans serveur) : le sachet
    peut alors s'ouvrir « pour de faux » et montrer l'animation. Jamais utilisé par le site."""
    if not demo:
        return ""
    texte = json.dumps(demo, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/json" id="donnees-demo">{texte}</script>'


def generer_page(articles, jeton="", preferences=None, demo=None, categories=None,
                 pagination=None, comptes=None, nb_favoris=None, nouveau=0, logo_src=None,
                 nb_corbeille=0, nb_doublons=0, compteurs=None, mode="collection"):
    """Renvoie le HTML complet de la page de la collection (mode « collection ») ou de la page des PAQUETS (mode « paquets » : le
    paquet à ouvrir, son décompte et, dessous, les cartes ajoutées pendant la visite ; rien d'autre).
    `articles` : les cartes de la page courante (déjà filtrées), les plus récentes d'abord.
    `jeton` : code secret partagé avec le serveur local (voir serveur.py).
    `preferences` : filtres enregistrés {"filtre_rangs": [...], "favoris_seulement": bool,
                    "categorie": None / -1 / identifiant}.
    `demo` : cartes d'exemple pour un aperçu sans serveur (voir _html_demo).
    `categories` : toutes les catégories (liste déroulante, classement).
    `pagination` : {"page", "pages", "par_page", "total_filtre", "total"} (par défaut : tout sur
                   une seule page).
    `comptes`, `nb_favoris` : chiffres de TOUTE la collection pour les boutons de filtre.
    `nouveau` : les N premières cartes apparaissent en fondu (après l'ouverture d'un paquet).
    `logo_src` : adresse de l'image du logo (None : celui des réglages ; "" : aucun).
    `nb_corbeille` : nombre de cartes dans la corbeille (icône en haut à droite)."""
    logo_src = _source_logo(logo_src)
    modele_carte = Template(_lire(config.DOSSIER_TEMPLATES, "carte.html"))
    modele_page = _Page(_lire(config.DOSSIER_TEMPLATES, "page.html"))
    preferences = preferences or {}

    categories = categories or []
    if comptes is None:
        comptes, nb_favoris = comptes_depuis(articles)
    pagination = pagination or {"page": 1, "pages": 1, "par_page": max(1, len(articles)),
                                "total_filtre": len(articles), "total": len(articles)}
    infos = texte_infos(pagination["total"], pagination["total_filtre"])
    cartes_html = []
    for i, art in enumerate(articles):
        carte_html = _html_carte(art, modele_carte)
        if i < nouveau:                                   # arrivée en fondu, l'une après l'autre
            carte_html = carte_html.replace(
                '<div class="carte-cadre">',
                f'<div class="carte-cadre carte-cadre--entree" style="--delai: {i * 55}ms">'
                + (HALO_HTML if _halo_duree() else ""), 1)
        cartes_html.append(carte_html)
    pager = html_pagination(pagination["page"], pagination["pages"])

    # Garde-fous : on évite les valeurs absurdes (trop petites ou trop grandes)
    largeur = max(120, min(int(config.LARGEUR_CARTE), 700))
    largeur_apercu = max(240, min(int(config.LARGEUR_APERCU), 900))
    largeur_export = max(300, min(int(config.LARGEUR_EXPORT), 1800))
    impression = _impression()

    return modele_page.substitute(
        titre_page=_echapper(config.TITRE_SITE),
        titre_site=_echapper(config.TITRE_SITE),
        style_entete=_echapper(_style_entete()),
        logo_entete=_html_logo_entete(logo_src),
        bio=_html_bio(),
        theme_site=_echapper(config.THEME_SITE),
        accent_mode=_accent_mode(),
        pied_page=html_pied_page(),
        effet_survol=_echapper(config.EFFET_SURVOL),
        anim_zoom=_echapper(config.ANIMATION_ZOOM),
        actions=navigation.html_actions("paquets" if mode == "paquets" else "collection", nb_corbeille),
        zone_paquet=_html_paquet(logo_src) if (mode == "paquets" and config.BOOSTER_AFFICHER) else (
            "" if mode == "paquets" else ""),
        donnees_demo=_html_demo(demo),
        largeur_carte=largeur,
        largeur_apercu=largeur_apercu,
        largeur_export=largeur_export,
        impression=_echapper(json.dumps(impression)),
        jeton=_echapper(jeton),
        infos=_echapper(infos),
        langue=_echapper(config.LANGUE),
        resume=html_resume(comptes, nb_favoris or 0, preferences.get("filtre_rangs", ()),
                           preferences.get("favoris_seulement", False)),
        vide_masque="hidden" if pagination["total"] else "",
        aucun_masque="" if (pagination["total"] and not articles) else "hidden",
        page=pagination["page"],
        par_page=pagination["par_page"],
        export_categories="1" if config.CATEGORIES_DANS_EXPORT else "0",
        filtre_categorie=_html_filtre_categorie(categories, preferences.get("categorie"),
                                                nb_doublons, compteurs),
        tri=_html_tri(preferences.get("tri")),
        recherche=_echapper(preferences.get("recherche") or ""),
        recherche_effacer_masque="" if preferences.get("recherche") else " hidden",
        classe_page=("page--paquets" if mode == "paquets" else "page--collection page--sans-paquet"),
        mode_page=mode,
        style_halo=_echapper(_style_halo()),
        halo=_halo_duree(),
        vide_texte=('Ta collection est vide : ouvre ton premier paquet dans la page <a href="/paquets">Paquets</a> !'
                    if config.BOOSTER_AFFICHER else 'Ta collection est vide : ajoute des cartes avec la page '
                    '<a href="/recherche">Recherche</a>.'),
        panneau_selection=_html_panneau_selection(categories),
        pagination=pager,
        cartes="\n".join(cartes_html),
        css=_css_complet(),
        js=_js("survol.js", "pied.js", "corbeille.js", "apercu.js", "cartes.js"),
    )


def filtres_categorie_inactif(categorie):
    """Le filtre « Doublons » n'a plus de sens si la catégorie automatique est désactivée."""
    return ((categorie == -2 and not config.DOUBLONS_ACTIFS)
            or (categorie == -3 and not config.SANS_ILLUSTRATION_ACTIF)
            or (categorie == -4 and not config.ANIMEE_ACTIF))


def lire_filtres(conn):
    """Filtres enregistrés de la collection : rangs, favoris, catégorie."""
    filtres = {
        "filtre_rangs": parametres.lire_preference(conn, "ui.filtre_rangs", []),
        "favoris_seulement": parametres.lire_preference(conn, "ui.favoris_seulement", False),
        "categorie": parametres.lire_preference(conn, "ui.filtre_categorie", None),
        "tri": parametres.lire_preference(conn, "ui.tri", base.TRI_DEFAUT),
        "recherche": parametres.lire_preference(conn, "ui.recherche", ""),
    }
    if filtres_categorie_inactif(filtres["categorie"]):
        filtres["categorie"] = None
    return filtres


def page_collection(jeton="", page=1, nouveau=0, logo_src=None):
    """Une page de la collection, lue dans la base de données, avec les filtres enregistrés.
    `nouveau` : nombre de cartes à faire apparaître en fondu (après l'ouverture d'un paquet)."""
    with base.connexion_rapide() as conn:
        preferences = lire_filtres(conn)
        resultat = base.lister_cartes_page(
            conn, {"rangs": preferences["filtre_rangs"], "favoris": preferences["favoris_seulement"],
                   "categorie": preferences["categorie"], "recherche": preferences["recherche"]},
            page, config.CARTES_PAR_PAGE, preferences["tri"])
        comptes = base.compter_par_rang(conn)
        nb_favoris = base.compter_favoris(conn)
        categories = base.lister_categories(conn)
        nb_corbeille = base.compter_corbeille(conn)
        nb_doublons = base.compter_doublons(conn)
        compteurs = base.compteurs_categories(conn)
    return generer_page(resultat["cartes"], jeton, preferences, categories=categories,
                        pagination=resultat, comptes=comptes, nb_favoris=nb_favoris,
                        nb_corbeille=nb_corbeille, nb_doublons=nb_doublons, compteurs=compteurs,
                        nouveau=min(nouveau, len(resultat["cartes"])) if resultat["page"] == 1 else 0,
                        logo_src=logo_src)


def page_paquets(jeton="", logo_src=None):
    """La page d'ouverture des paquets : le paquet, sa légende, le décompte du prochain ; les cartes qu'on ajoute à la collection
    s'y rangent (on reste sur la page tant qu'on n'en change pas)."""
    with base.connexion_rapide() as conn:
        total = base.compter(conn)
        nb_corbeille = base.compter_corbeille(conn)
        comptes = base.compter_par_rang(conn)
        nb_favoris = base.compter_favoris(conn)
    pagination = {"page": 1, "pages": 1, "par_page": 500, "total_filtre": total, "total": total}
    return generer_page([], jeton, {}, categories=[], pagination=pagination, comptes=comptes, nb_favoris=nb_favoris,
                        nb_corbeille=nb_corbeille, logo_src=logo_src, mode="paquets")


def ecrire_page(articles, jeton="", preferences=None):
    """Écrit sortie/index.html et renvoie son chemin."""
    config.DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)
    chemin = config.DOSSIER_SORTIE / "index.html"
    chemin.write_text(generer_page(articles, jeton, preferences), encoding="utf-8")
    return chemin


def ecrire_page_collection(jeton=""):
    """Écrit une copie de la page de la collection dans sortie/index.html (utile si la page
    est ouverte sans le serveur local, en double-cliquant sur le fichier)."""
    config.DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)
    chemin = config.DOSSIER_SORTIE / "index.html"
    fichier_logo = logo.trouver()                 # ouverte sans serveur : le logo se lit dans ../logo/
    source = "" if fichier_logo is None else "../logo/" + quote(fichier_logo.name)
    with projet.sans_consommer_accueil():              # (cette page-là ne s'affiche pas dans le navigateur : elle ne compte pas comme « la première page »)
        texte = page_paquets(jeton, logo_src=source)       # page de secours : les paquets (démo)
    texte = texte.replace(favicon.lien_html(), favicon.lien_html(relatif=True), 1) if favicon.lien_html() else texte      # (sans serveur : l'icône se lit dans ../ico/)
    chemin.write_text(texte, encoding="utf-8")
    return chemin


def html_resultats(articles):
    """Les cartes trouvées par une recherche : les cartes habituelles (rang, motif, image,
    introduction), avec une case à cocher toujours visible, le classement automatique prévu
    (bandeaux) et, si l'article est déjà dans la collection, une pastille « ×N »."""
    modele_carte = Template(_lire(config.DOSSIER_TEMPLATES, "carte.html"))
    morceaux = []
    for art in articles:
        etiquette = html_possede(art["possede"]) if art.get("possede") else ""
        carte = _html_carte(dict(art, etiquette=etiquette), modele_carte, recherche=True)
        # Vues par jour et place dans la liste de Wikipédia : la page trie les résultats avec (les plus vues d'abord)
        carte = carte.replace('<article class="carte"', f'<article class="carte" data-vues="{float(art.get("vues_moyenne") or 0):.2f}" '
                              f'data-pertinence="{int(art.get("pertinence") or 0)}"', 1)
        morceaux.append(carte)
    return "\n".join(morceaux)


def html_possede(nombre):
    """La pastille « Dans ta collection ×N » d'une carte déjà possédée."""
    return (f'<div class="carte__possede" title="Cet article est déjà dans ta collection '
            f'({nombre} carte{"s" if nombre > 1 else ""})">✓ Dans ta collection'
            f'{f" ×{nombre}" if nombre > 1 else ""}</div>')


def bandeaux_meme_titre(conn, titres, exclure=()):
    """{identifiant: HTML des bandeaux} des cartes déjà dans la collection qui partagent un de ces
    titres : leur bandeau « Doublon » change quand un doublon apparaît ou disparaît."""
    return {str(c["id"]): cat.html_bandeaux(c["categories"])
            for c in base.cartes_meme_titre(conn, titres, exclure)}


def etat_collection(conn, page=1):
    """Ce que la page de la collection doit mettre à jour après un changement (cartes mises à la
    corbeille...) : boutons de filtre, phrase d'en-tête et pagination, avec les filtres enregistrés."""
    preferences = lire_filtres(conn)
    resultat = base.lister_cartes_page(
        conn, {"rangs": preferences["filtre_rangs"], "favoris": preferences["favoris_seulement"],
               "categorie": preferences["categorie"], "recherche": preferences["recherche"]},
        page, config.CARTES_PAR_PAGE, preferences["tri"])
    comptes = base.compter_par_rang(conn)
    return {
        "resume": html_resume(comptes, base.compter_favoris(conn), preferences["filtre_rangs"],
                              preferences["favoris_seulement"]),
        "infos": texte_infos(resultat["total"], resultat["total_filtre"]),
        "pagination": html_pagination(resultat["page"], resultat["pages"]),
        "total": resultat["total"],
        "doublons": base.compter_doublons(conn),
        "compteurs": base.compteurs_categories(conn),
    }


def html_cartes_corbeille(articles):
    """Les cartes de la corbeille : les cartes habituelles avec une case à cocher toujours
    visible et la date de suppression."""
    modele_carte = Template(_lire(config.DOSSIER_TEMPLATES, "carte.html"))
    morceaux = []
    for art in articles:
        supprime_le = art.get("supprime_le")
        etiquette = ""
        if supprime_le:
            etiquette = (f'<div class="carte__possede carte__supprimee" title="Mise à la corbeille '
                         f'le {supprime_le:%d/%m/%Y à %H:%M}">Supprimée le {supprime_le:%d/%m}</div>')
        morceaux.append(_html_carte(dict(art, etiquette=etiquette), modele_carte))
    return "\n".join(morceaux)


def page_corbeille(jeton="", page=1, logo_src=None):
    """La page de la corbeille : les cartes à restaurer, à supprimer définitivement ou à laisser."""
    with base.connexion_rapide() as conn:
        resultat = base.lister_corbeille_page(conn, page, config.CARTES_PAR_PAGE)
    logo_src = _source_logo(logo_src)
    modele = _Page(_lire(config.DOSSIER_TEMPLATES, "corbeille.html"))
    total = resultat["total"]
    pager = html_pagination(resultat["page"], resultat["pages"], "/corbeille")
    return modele.substitute(
        theme_site=_echapper(config.THEME_SITE),
        accent_mode=_accent_mode(),
        pied_page=html_pied_page(),
        effet_survol=_echapper(config.EFFET_SURVOL),
        anim_zoom=_echapper(config.ANIMATION_ZOOM),
        actions=navigation.html_actions("corbeille", total),
        style_entete=_echapper(_style_entete()),
        logo_entete=_html_logo_entete(logo_src),
        largeur_carte=int(config.LARGEUR_CARTE),
        largeur_apercu=int(config.LARGEUR_APERCU),
        langue=_echapper(config.LANGUE),
        jeton=_echapper(jeton),
        intro=_echapper(navigation.texte_corbeille(total)),
        page=resultat["page"],
        masque_contenu="" if total else "hidden",
        masque_vide="hidden" if total else "",
        pagination=pager,
        cartes=html_cartes_corbeille(resultat["cartes"]),
        css=_css_complet(),
        js=_js("survol.js", "pied.js", "corbeille.js", "page_corbeille.js"),
    )


def page_recherche(jeton="", logo_src=None):
    """La page « Recherche » : un formulaire, puis les cartes trouvées sur Wikipédia."""
    logo_src = _source_logo(logo_src)
    modele = _Page(_lire(config.DOSSIER_TEMPLATES, "recherche.html"))
    return modele.substitute(
        theme_site=_echapper(config.THEME_SITE),
        accent_mode=_accent_mode(),
        pied_page=html_pied_page(),
        effet_survol=_echapper(config.EFFET_SURVOL),
        anim_zoom=_echapper(config.ANIMATION_ZOOM),
        actions=navigation.html_actions("recherche", _nb_corbeille()),
        style_entete=_echapper(_style_entete()),
        logo_entete=_html_logo_entete(logo_src),
        largeur_carte=int(config.LARGEUR_CARTE),
        largeur_apercu=int(config.LARGEUR_APERCU),
        maximum=int(config.RECHERCHE_MAX_RESULTATS),
        par_page=int(config.RECHERCHE_MAX_RESULTATS),
        langue=_echapper(config.LANGUE),
        jeton=_echapper(jeton),
        css=_css_complet(),
        js=_js("survol.js", "pied.js", "corbeille.js", "apercu.js", "recherche.js"),
    )


def _article_apercu(code):
    """Carte d'exemple d'un rang (pour l'aperçu dans la page Configuration)."""
    return {
        "id": None, "titre": "Aperçu", "description": "Exemple de description",
        "intro": "Voici à quoi ressemblera une carte de ce rang, avec son motif, ses "
                 "couleurs et son reflet.",
        "rarete": code, "rarete_nom": config.nom_rang(code), "rarete_tiree": code,
        "tire_le": datetime.now().astimezone(), "vues_moyenne": 1234, "vues_total": 74040,
        "url": "", "image": "no-image", "miniature": "no-image", "favori": False,
    }


def _article_apercu_perso(style=None):
    """Carte d'exemple du palier « Personnalisée » (pour l'aperçu dans la page Configuration)."""
    style = style or createur.style_de_base()
    return {
        "id": None, "titre": "Aperçu", "description": "Exemple de sous-titre",
        "intro": "Voici à quoi ressemblera une carte créée avec ce palier.", "rarete": config.CODE_PERSO,
        "rarete_nom": style["palier"], "rarete_tiree": config.CODE_PERSO,
        "tire_le": datetime.now().astimezone(), "vues_moyenne": 0, "vues_total": 0, "url": "perso:apercu",
        "image": "no-image", "miniature": "no-image", "favori": False, "personnalisee": True,
        "surnom": "Ton surnom", "style": style,
    }


def page_configuration(jeton="", logo_src=None, avance_visible=True):
    """La page Configuration : tous les réglages, avec leur valeur actuelle.
    `logo_src` : adresse de l'image du logo (None : celui des réglages ; "" : aucun)."""
    with base.connexion_rapide() as conn:
        defauts = parametres.valeurs_par_defaut(conn)
        categories = base.lister_categories(conn)
        nb_corbeille = base.compter_corbeille(conn)
    etat_reserve = {**reserve.etat(), "stats": stats.etat()}
    valeurs = {nom: copy.deepcopy(getattr(config, nom)) for nom in parametres.PARAMETRES}
    modele_carte = Template(_lire(config.DOSSIER_TEMPLATES, "carte.html"))
    modele_page = _Page(_lire(config.DOSSIER_TEMPLATES, "configuration.html"))

    def apercu(code):
        if code == config.CODE_PERSO:
            return _html_carte(_article_apercu_perso(), modele_carte)
        return _html_carte(_article_apercu(code), modele_carte)

    logo_src = _source_logo(logo_src)
    return modele_page.substitute(
        theme_site=_echapper(config.THEME_SITE),
        accent_mode=_accent_mode(),
        pied_page=html_pied_page(),
        effet_survol=_echapper(config.EFFET_SURVOL),
        anim_zoom=_echapper(config.ANIMATION_ZOOM),
        actions=navigation.html_actions("configuration", nb_corbeille),
        style_entete=_echapper(_style_entete()),
        logo_entete=_html_logo_entete(logo_src),
        navigation=formulaire.html_navigation_sections(avance_visible),
        sections=formulaire.html_sections(valeurs, defauts, apercu, categories,
                                          html_apercu_booster(logo_src), etat_reserve, avance_visible),
        jeton=_echapper(jeton),
        css=_css_complet(),
        js=_js("survol.js", "pied.js", "corbeille.js", "configuration.js"),
    )


# ------------------------------------------------------------------ page de profil (vitrines)

def html_emplacement(vitrine, emplacement, carte, modele=None):
    """Un emplacement de vitrine : vide (bouton « Choisir une carte ») ou occupé par une carte
    (avec « Changer » et « Retirer »). C'est aussi ce que le serveur renvoie quand on le modifie."""
    attributs = f'data-vitrine="{int(vitrine)}" data-emplacement="{int(emplacement)}"'
    if carte is None:
        return (f'<div class="vitrine__emplacement vitrine__emplacement--vide" {attributs}>'
                f'<button type="button" class="vitrine__ajouter" aria-label="Choisir une carte pour '
                f"l'emplacement {int(emplacement)} de la vitrine {int(vitrine)}\">"
                f'<span class="vitrine__plus" aria-hidden="true">+</span>'
                f'<span class="vitrine__ajouter-texte">Choisir une carte</span></button></div>')
    modele = modele or Template(_lire(config.DOSSIER_TEMPLATES, "carte.html"))
    return (f'<div class="vitrine__emplacement" {attributs}>{_html_carte(carte, modele, vitrine=True)}'
            f'<div class="vitrine__actions">'
            f'<button type="button" class="vitrine__changer" aria-label="Changer la carte de '
            f"l'emplacement {int(emplacement)}\">Changer</button>"
            f'<button type="button" class="vitrine__retirer" aria-label="Retirer la carte de '
            f"l'emplacement {int(emplacement)}\">Retirer</button></div></div>")


def _html_vitrine(position, titre, cartes, modele):
    emplacements = "".join(html_emplacement(position, e, cartes.get((position, e)), modele)
                           for e in range(1, int(config.PROFIL_EMPLACEMENTS) + 1))
    return (f'<article class="vitrine" data-vitrine="{position}" '
            f'style="--k: {int(config.PROFIL_EMPLACEMENTS)}">'
            f'<header class="vitrine__entete">'
            f'<input type="text" class="vitrine__titre" value="{_echapper(titre)}" maxlength="80" '
            f'placeholder="Titre de la vitrine {position} (les emoji sont les bienvenus 🎉)" '
            f'aria-label="Titre de la vitrine {position}" autocomplete="off" spellcheck="false">'
            f'<span class="vitrine__etat" role="status" aria-live="polite"></span></header>'
            f'<div class="vitrine__ligne">{emplacements}</div></article>')


def html_bilan(total, comptes, categories, apparence=None, qui="dans la collection"):
    """Le résumé du haut de la page de profil : nombre total de cartes, une pastille par rang (la
    lettre du rang puis le nombre de cartes) et une étiquette par catégorie avec son nombre."""
    if apparence is not None:                  # collection d'un autre : ses rangs, ses lettres, ses noms
        symboles = {r["code"]: r["symbole"] for r in apparence["rangs"]}
        noms = {r["code"]: r["nom"] for r in apparence["rangs"]}
        symboles[config.CODE_PERSO], noms[config.CODE_PERSO] = apparence["perso"]["symbole"], apparence["perso"]["nom"]
        codes = [r["code"] for r in apparence["rangs"]] + sorted(set(comptes) - {r["code"] for r in apparence["rangs"]})
    else:
        symboles = {c: config.symbole(c) for c in list(config.CODES) + sorted(set(comptes))}
        noms = {c: config.nom_rang(c) for c in symboles}
        codes = list(config.CODES) + sorted(set(comptes) - set(config.CODES))
    rangs = "".join(
        f'<li class="pastille pastille--statique{" pastille--zero" if not comptes.get(code) else ""}" '
        f'data-rarete="{_echapper(code)}" title="{_echapper(noms.get(code, code))}">'
        f'<span class="pastille__code">{_echapper(symboles.get(code, code))}</span>'
        f'<b>{comptes.get(code, 0)}</b></li>'
        for code in codes)
    etiquettes = "".join(
        f'<li class="profil__categorie{" profil__categorie--zero" if not c["nb_cartes"] else ""}">'
        f'{html_bandeaux_categorie(c)}<b>{c["nb_cartes"]}</b></li>' for c in categories)
    categories_html = (f'<ul class="profil__categories" aria-label="Cartes par catégorie">{etiquettes}</ul>'
                       if categories else "")
    return (
        '    <section class="profil__bilan" aria-label="Résumé de la collection">\n'
        f'      <p class="profil__total"><strong id="profil-total">{total}</strong> '
        f'carte{"s" if total > 1 else ""} {_echapper(qui)}</p>\n'
        f'      <ul class="profil__rangs" aria-label="Cartes par rareté">{rangs}</ul>\n'
        f'      {categories_html}\n    </section>')


def html_bandeaux_categorie(categorie):
    """L'étiquette colorée d'une catégorie (même style que sur les cartes), sans troncature."""
    return cat.html_bandeaux([{"nom": categorie["nom"], "couleur": categorie["couleur"]}],
                                    longueur_max=60, max_affichees=1)


def _html_rangs_selecteur():
    """Les boutons de rang (filtre) de la fenêtre « Choisir une carte » : un par rang, avec ses lettres et son nom."""
    boutons = "".join(
        f'<li><button type="button" class="selecteur__filtre" data-rarete="{_echapper(code)}" aria-pressed="false" '
        f'title="{_echapper(config.nom_rang(code))}"><span class="pastille__code">{_echapper(config.symbole(code))}</span></button></li>'
        for code in config.CODES)
    return f'<ul class="selecteur__rangs" id="selecteur-rangs" aria-label="Filtrer par rang">{boutons}</ul>'


def _html_tris_selecteur():
    """La liste « Trier » de la fenêtre « Choisir une carte » : pertinence, date, titre."""
    options = [("", "Pertinence")] + [(code, base.TRIS[code][0]) for code in base.TRIS_SELECTEUR]
    return ('<label class="outil outil--tri" for="selecteur-tri"><span>Trier</span><select id="selecteur-tri">'
            + "".join(f'<option value="{_echapper(code)}">{_echapper(libelle)}</option>' for code, libelle in options)
            + "</select></label>")


def page_profil(jeton="", logo_src=None):
    """La page de profil : titre et biographie du site, résumé de la collection, puis les vitrines."""
    with base.connexion_rapide() as conn:
        total = base.compter(conn)
        comptes = base.compter_par_rang(conn)
        liste_categories = base.lister_categories(conn)
        titres = base.titres_vitrines(conn)
        cartes = base.cartes_des_vitrines(conn, config.PROFIL_VITRINES, config.PROFIL_EMPLACEMENTS)
        nb_corbeille = base.compter_corbeille(conn)
        exposees = base.compter_carte_exposees(conn)
    logo_src = _source_logo(logo_src)
    modele_carte = Template(_lire(config.DOSSIER_TEMPLATES, "carte.html"))
    if int(config.PROFIL_VITRINES) > 0:
        vitrines = "\n".join(_html_vitrine(i, titres.get(i, ""), cartes, modele_carte)
                             for i in range(1, int(config.PROFIL_VITRINES) + 1))
    else:
        vitrines = ('<p class="vide" role="status">Aucune vitrine pour l\'instant : règle leur nombre '
                    'dans la <a href="/configuration">Configuration</a> (section « Page de profil »).</p>')
    modele = _Page(_lire(config.DOSSIER_TEMPLATES, "profil.html"))
    return modele.substitute(
        theme_site=_echapper(config.THEME_SITE), accent_mode=_accent_mode(),
        effet_survol=_echapper(config.EFFET_SURVOL), anim_zoom=_echapper(config.ANIMATION_ZOOM),
        titre_page=_echapper(config.TITRE_SITE), titre_site=_echapper(config.TITRE_SITE),
        bio=_html_bio(),
        infos=_echapper(f"{total} carte{'s' if total > 1 else ''} dans la collection · "
                        f"{exposees} exposée{'s' if exposees > 1 else ''} en vitrine"),
        actions=navigation.html_actions("profil", nb_corbeille),
        style_entete=_echapper(_style_entete()), logo_entete=_html_logo_entete(logo_src),
        largeur_carte=int(config.LARGEUR_CARTE), largeur_apercu=int(config.LARGEUR_APERCU),
        largeur_export=max(300, min(int(config.LARGEUR_EXPORT), 1800)),
        impression=_echapper(json.dumps(_impression())),
        export_categories="1" if config.CATEGORIES_DANS_EXPORT else "0",
        style_halo=_echapper(_style_halo()), langue=_echapper(config.LANGUE), jeton=_echapper(jeton),
        bilan=html_bilan(total, comptes, liste_categories), vitrines=vitrines,
        rangs_selecteur=_html_rangs_selecteur(), tris_selecteur=_html_tris_selecteur(),
        pied_page=html_pied_page(), css=_css_complet(),
        js=_js("survol.js", "pied.js", "corbeille.js", "apercu.js", "cartes.js", "profil.js"))


# ------------------------------------------------------------------ Créateur de cartes

def html_apercu_createur(carte):
    """L'aperçu d'une carte du Créateur : `carte` est un dictionnaire validé (voir createur.valider)."""
    modele = Template(_lire(config.DOSSIER_TEMPLATES, "carte.html"))
    return _html_carte(createur.article_pour_affichage(carte), modele, createur=True)


def _options_paliers():
    """Le menu des paliers du Créateur : d'abord le palier « Personnalisée » (le thème de base réglé dans la
    Configuration, choisi au départ), puis chaque rang de la Configuration. Le thème, les lettres et le nom du
    palier choisi s'appliquent à la carte."""
    options = [f'<option value="" selected>{_echapper(config.PERSO_NOM)} '
               f'({_echapper(config.PERSO_SYMBOLE)}) — thème de base</option>']
    for code, _, nom in config.PALIERS:
        options.append(f'<option value="{_echapper(code)}">{_echapper(nom)} ({_echapper(config.symbole(code))})</option>')
    return "".join(options)


def page_createur(jeton="", logo_src=None):
    """La page « Créateur de cartes » : l'aperçu d'une carte blanche au départ, le contenu à gauche, le
    palier et l'apparence à droite (les mêmes propriétés que celles des rangs de la Configuration)."""
    with base.connexion_rapide() as conn:
        nb_corbeille = base.compter_corbeille(conn)
    logo_src = _source_logo(logo_src)
    carte_depart, _ = createur.valider({}, strict=False)
    modele = _Page(_lire(config.DOSSIER_TEMPLATES, "createur.html"))
    return modele.substitute(
        theme_site=_echapper(config.THEME_SITE), accent_mode=_accent_mode(),
        effet_survol=_echapper(config.EFFET_SURVOL), anim_zoom=_echapper(config.ANIMATION_ZOOM),
        titre_page=_echapper(config.TITRE_SITE), actions=navigation.html_actions("createur", nb_corbeille),
        style_entete=_echapper(_style_entete()), logo_entete=_html_logo_entete(logo_src),
        largeur_carte=int(config.LARGEUR_CARTE), largeur_apercu=int(config.LARGEUR_APERCU),
        largeur_export=max(300, min(int(config.LARGEUR_EXPORT), 1800)),
        impression=_echapper(json.dumps(_impression())),
        export_categories="1" if config.CATEGORIES_DANS_EXPORT else "0",
        style_halo=_echapper(_style_halo()), jeton=_echapper(jeton),
        description_max=createur.limite_description(), titre_max=createur.TITRE_MAX,
        sous_titre_max=createur.SOUS_TITRE_MAX, surnom_max=createur.SURNOM_MAX,
        image_max_mo=images.TAILLE_MAX // 1024 // 1024,
        options_paliers=_options_paliers(),
        carte_initiale=html_apercu_createur(carte_depart), pied_page=html_pied_page(),
        fa_rangs=_html_rangs_selecteur().replace("selecteur-rangs", "fa-rangs"),
        fa_tris=_html_tris_selecteur().replace("selecteur-tri", "fa-tri"),
        css=_css_complet(), js=_js("survol.js", "pied.js", "corbeille.js", "createur.js", "fullart.js"))


# ------------------------------------------------------------------ Hall des collections (pair à pair)

_CORPS_COLLECTION = """    <section class="visite__outils" id="visite-outils" aria-label="Filtres" hidden>
      <div class="recherche__ligne">
        <label class="sr-only" for="visite-q">Rechercher une carte par son titre</label>
        <input type="search" id="visite-q" maxlength="100" autocomplete="off" spellcheck="false" placeholder="Rechercher une carte…">
        <label class="sr-only" for="visite-categorie">Catégorie</label>
        <select id="visite-categorie"></select>
        <label class="sr-only" for="visite-tri">Trier</label>
        <select id="visite-tri"></select>
      </div>
      <ul class="profil__rangs visite__rangs" id="visite-rangs" aria-label="Filtrer par rang"></ul>
    </section>
    <div class="barre-selection" id="visite-selection" role="region" aria-label="Rapatrier les cartes sélectionnées" hidden>
      <span class="barre-selection__compte" id="visite-compte" role="status">Aucune carte sélectionnée</span>
      <button type="button" class="bouton-site" id="visite-tout">Tout sélectionner (page)</button>
      <button type="button" class="bouton-site" id="visite-rien">Tout désélectionner</button>
      <button type="button" class="bouton-site bouton-site--principal" id="visite-rapatrier" disabled>Rapatrier</button>
    </div>
    <nav class="hall__pages hall__pages--haut" id="visite-pages-haut" aria-label="Pages (haut)" hidden>
      <button type="button" class="bouton-site" id="visite-precedent-haut">← Précédent</button>
      <span id="visite-page-texte-haut" role="status"></span>
      <button type="button" class="bouton-site" id="visite-suivant-haut">Suivant →</button>
    </nav>
    <section class="grille grille--recherche" id="visite-cartes" aria-label="Cartes de la collection"></section>
    <nav class="hall__pages" id="visite-pages" aria-label="Pages" hidden>
      <button type="button" class="bouton-site" id="visite-precedent">← Précédent</button>
      <span id="visite-page-texte" role="status"></span>
      <button type="button" class="bouton-site" id="visite-suivant">Suivant →</button>
    </nav>"""


def page_hall(jeton="", logo_src=None):
    """La page « Hall des collections » : mon partage, la recherche des collectionneurs et leur liste. Les données
    (liste, état) sont chargées par la page (hall.js) : tout texte venu des autres est affiché en texte brut."""
    with base.connexion_rapide() as conn:
        nb_corbeille = base.compter_corbeille(conn)
    logo_src = _source_logo(logo_src)
    modele = _Page(_lire(config.DOSSIER_TEMPLATES, "hall.html"))
    return modele.substitute(
        theme_site=_echapper(config.THEME_SITE), accent_mode=_accent_mode(),
        effet_survol=_echapper(config.EFFET_SURVOL), anim_zoom=_echapper(config.ANIMATION_ZOOM),
        titre_page=_echapper(config.TITRE_SITE), actions=navigation.html_actions("hall", nb_corbeille),
        style_entete=_echapper(_style_entete()), logo_entete=_html_logo_entete(logo_src),
        largeur_carte=int(config.LARGEUR_CARTE), largeur_apercu=int(config.LARGEUR_APERCU),
        jeton=_echapper(jeton), pied_page=html_pied_page(), css=_css_complet(),
        js=_js("corbeille.js", "hall.js"))


def page_visite(mode, pair, jeton="", logo_src=None):
    """La page d'un collectionneur : `mode` « profil » ou « collection ». Le contenu vient du collectionneur (page
    chargée par visite.js) ; la structure ne dépend que de ton annuaire. Boutons : l'autre page, et « Quitter »."""
    if mode not in ("profil", "collection"):
        raise ValueError("mode inconnu")
    with base.connexion_rapide() as conn:
        fiche = p2p_annuaire.fiche_de(conn, pair)
    if fiche is None:
        raise LookupError("collectionneur inconnu")
    logo_src = _source_logo(logo_src)
    pseudo = fiche["pseudo"] or "collectionneur"
    if mode == "collection":
        corps, classe = _CORPS_COLLECTION, "mode-selection"
        lien_autre, libelle_autre = f"/hall/profil?pair={pair}", "Voir le profil"
        titre_onglet = f"Collection de {pseudo} · Hall des collections"
    else:
        corps, classe = '    <section class="vitrines" id="visite-vitrines" aria-label="Vitrines"></section>', ""
        lien_autre, libelle_autre = f"/hall/collection?pair={pair}", "Voir la collection"
        titre_onglet = f"Profil de {pseudo} · Hall des collections"
    modele = _Page(_lire(config.DOSSIER_TEMPLATES, "hall_visite.html"))
    return modele.substitute(
        theme_site=_echapper(config.THEME_SITE), accent_mode=_accent_mode(),
        effet_survol=_echapper(config.EFFET_SURVOL), anim_zoom=_echapper(config.ANIMATION_ZOOM),
        titre_onglet=_echapper(titre_onglet), classe_corps=classe, mode=mode, pair=_echapper(pair),
        par_page=int(config.CARTES_PAR_PAGE), style_entete=_echapper(_style_entete()),
        logo_entete=_html_logo_entete(logo_src), titre_collection=_echapper(fiche["collection"]),
        pseudo=_echapper(p2p_identite.etiquette(fiche["pseudo"], pair)),
        lien_autre=_echapper(lien_autre), libelle_autre=_echapper(libelle_autre),
        largeur_carte=int(config.LARGEUR_CARTE), largeur_apercu=int(config.LARGEUR_APERCU),
        jeton=_echapper(jeton), corps=corps, pied_page=html_pied_page(), css=_css_complet(),
        js=_js("survol.js", "pied.js", "corbeille.js", "apercu.js", "visite.js"))


def html_visite_cartes(cartes):
    """Les cartes d'un autre collectionneur (déjà vérifiées), prêtes à afficher : comme chez lui, sans étoile
    ni export, avec la case de sélection et, si tu l'as déjà, la pastille « Dans ta collection »."""
    modele = Template(_lire(config.DOSSIER_TEMPLATES, "carte.html"))
    with base.connexion_rapide() as conn:
        possedees = base.compter_par_url(conn, [c["url"] for c in cartes if not c["url"].startswith("perso:")])
    return "\n".join(_html_carte(dict(c, etiquette=html_possede(possedees[c["url"]]) if possedees.get(c["url"]) else ""),
                                 modele, visiteur=True) for c in cartes)


def html_visite_vitrines(vitrines):
    """Les vitrines d'un autre collectionneur, en lecture seule (cartes épurées, emplacements libres visibles)."""
    modele = Template(_lire(config.DOSSIER_TEMPLATES, "carte.html"))
    sortie = []
    for position, v in enumerate(vitrines, start=1):
        k = max(1, len(v["emplacements"]))
        emplacements = "".join(
            (f'<div class="vitrine__emplacement">{_html_carte(c, modele, vitrine=True, visiteur=True)}</div>' if c is not None else
             '<div class="vitrine__emplacement vitrine__emplacement--vide vitrine__emplacement--lecture">'
             '<span class="vitrine__ajouter-texte">Emplacement libre</span></div>')
            for c in v["emplacements"])
        titre = (f'<h3 class="vitrine__titre vitrine__titre--lecture">{_echapper(v["titre"])}</h3>' if v["titre"]
                 else f'<h3 class="vitrine__titre vitrine__titre--lecture vitrine__titre--vide">Vitrine {position}</h3>')
        sortie.append(f'<article class="vitrine" data-vitrine="{position}" style="--k: {k}"><header class="vitrine__entete">'
                      f'{titre}</header><div class="vitrine__ligne">{emplacements}</div></article>')
    return "\n".join(sortie) or '<p class="vide" role="status">Ce collectionneur n\'a pas de vitrine.</p>'
