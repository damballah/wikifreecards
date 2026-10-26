"""Tous les appels à Wikipedia / Wikimedia (réseau uniquement, aucune mise en forme)."""

import calendar
import re
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from urllib.parse import quote, unquote, urlsplit

import requests

from . import cadrage, config
from .rarete import calculer_vues, classer

TOP_URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
           "{langue}.wikipedia/all-access/{annee}/{mois:02d}/all-days")

SESSION = requests.Session()
_VERROU_RESEAU = threading.Lock()   # une seule requête à la fois, tous fils d'exécution confondus
_local = threading.local()          # mode « arrière-plan » du fil courant (voir en_arriere_plan)
_derniere_requete = 0.0
_latence = 0.5                  # durée moyenne d'une requête (s), affinée à chaque requête réussie
TRAITEMENT = 0.15               # s : enregistrement en base et mise en forme des cartes, après les requêtes
ecouteur_ralentissement = None  # appelé avec le délai (s) quand Wikipédia demande de patienter

DUREE_CACHE_TOP = 6 * 3600     # le top des articles les plus vus change peu : on le garde 6 h
_cache_top = {}


def vider_cache():
    _cache_top.clear()


def estimer_duree(requetes, pause=None):
    """Secondes qu'il faut pour envoyer encore `requetes` requêtes à Wikipédia, d'après les réglages :
    l'attente de politesse avant la prochaine (PAUSE depuis la fin de la dernière requête), PAUSE
    entre deux requêtes suivantes, la durée moyenne mesurée d'une requête, et le temps de
    traitement des cartes. C'est ce qui alimente le décompte de l'ouverture d'un paquet."""
    if requetes <= 0:
        return 0.0
    pause = config.PAUSE if pause is None else pause
    attente = max(0.0, pause - (time.monotonic() - _derniere_requete))
    return attente + requetes * _latence + (requetes - 1) * pause + TRAITEMENT


def _cle_top():
    mois_dernier = date.today().replace(day=1) - timedelta(days=1)
    return (config.LANGUE, mois_dernier.year, mois_dernier.month)


def top_en_cache():
    """Le top des articles les plus vus est-il déjà en mémoire (donc sans requête) ?"""
    en_cache = _cache_top.get(_cle_top())
    return bool(en_cache and time.monotonic() - en_cache[0] < DUREE_CACHE_TOP)


def _agent():
    """En-tête User-Agent demandé par Wikimedia (avec le contact de config.CONTACT)."""
    return f"WikiAleatoire/1.0 (projet personnel local; {config.CONTACT})"


class LimiteDebit(requests.RequestException):
    """Wikipédia demande de ralentir (429 ou 503). `delai` : secondes à patienter."""

    def __init__(self, delai, message=""):
        super().__init__(message or f"Wikipédia demande de patienter {delai:.0f} s")
        self.delai = delai


class BudgetEpuise(requests.RequestException):
    """Le plafond de requêtes de pré-chargement est atteint (voir reserve.py)."""


@contextmanager
def en_arriere_plan(pause, avant_requete=None, pause_reseau=None):
    """Mode « arrière-plan » pour le pré-chargement de la réserve, valable pour le fil d'exécution
    courant : pause plus douce que PAUSE entre ses propres requêtes, JAMAIS de nouvelle tentative
    après un 429 ou un 503 (on lève LimiteDebit : le pré-chargement s'arrête et patiente), et
    `avant_requete()` appelé avant chaque requête (plafond horaire ; peut lever BudgetEpuise).
    Le bloc reçoit un dictionnaire dont la clé « erreur » garde la dernière erreur réseau : le tirage
    d'articles avale certaines erreurs pour continuer, mais le pré-chargement doit les connaître."""
    _local.arriere = {"pause": float(pause), "derniere": 0.0, "avant": avant_requete, "erreur": None,
                      "pause_reseau": None if pause_reseau is None else float(pause_reseau)}
    try:
        yield _local.arriere
    finally:
        _local.arriere = None


def requete(url, params=None):
    """GET poli et sûr : voir _requete. En arrière-plan, garde la dernière erreur réseau."""
    arriere = getattr(_local, "arriere", None)
    if arriere is None:
        return _requete(url, params)
    try:
        return _requete(url, params)
    except requests.RequestException as erreur:
        arriere["erreur"] = erreur
        raise


def _requete(url, params=None):
    """GET avec pause entre les requêtes et nouvelles tentatives si Wikipedia
    répond 429 (trop de requêtes) ou 503. Renvoie le JSON de la réponse.
    Toutes les requêtes du programme passent ici, une à la fois (verrou) : jamais de requêtes
    parallèles, même entre l'ouverture d'un paquet et le pré-chargement en arrière-plan."""
    global _derniere_requete, _latence
    SESSION.headers["User-Agent"] = _agent()      # le contact peut changer dans la configuration
    arriere = getattr(_local, "arriere", None)
    for essai in range(1 if arriere else config.MAX_ESSAIS):
        if arriere:
            if arriere["avant"] is not None:
                arriere["avant"]()                 # plafond horaire
            attente = arriere["pause"] - (time.monotonic() - arriere["derniere"])
            if attente > 0:
                time.sleep(attente)                # pause douce, hors verrou : n'empêche personne
        with _VERROU_RESEAU:
            pause_reseau = config.PAUSE                    # pause commune à toutes les requêtes du programme...
            if arriere and arriere.get("pause_reseau") is not None:
                pause_reseau = min(config.PAUSE, arriere["pause_reseau"])      # ... plus courte pour les statistiques d'un paquet
            attente = pause_reseau - (time.monotonic() - _derniere_requete)
            if attente > 0:
                time.sleep(attente)
            debut = time.monotonic()
            reponse = SESSION.get(url, params=params, timeout=15)
            _derniere_requete = time.monotonic()
            if reponse.status_code not in (429, 503):     # la durée d'une requête sert aux estimations
                _latence = min(5.0, max(0.05, 0.5 * _latence + 0.5 * (_derniere_requete - debut)))
        if arriere:
            arriere["derniere"] = time.monotonic()

        if reponse.status_code in (429, 503):
            try:
                delai = float(reponse.headers["Retry-After"])
            except (KeyError, ValueError):
                delai = 2 * 2 ** essai          # 2, 4, 8, 16, 32 s
            delai = min(delai, 3600 if arriere else 60)
            if arriere:
                raise LimiteDebit(delai)        # pas de nouvelle tentative en arrière-plan
            print(f"  (Wikipedia demande de ralentir : nouvelle tentative "
                  f"dans {delai:.0f} s...)")
            if ecouteur_ralentissement is not None:      # la page affiche le temps d'attente en plus
                ecouteur_ralentissement(delai)
            time.sleep(delai)
            continue

        reponse.raise_for_status()
        return reponse.json()

    raise requests.RequestException(
        "Wikipedia limite le débit (429). Réessaie dans quelques minutes.")


def url_api():
    """Adresse de l'API de la Wikipédia dans la langue choisie (config.LANGUE)."""
    return f"https://{config.LANGUE}.wikipedia.org/w/api.php"


def appeler_api(params):
    """Appelle l'API Wikipedia (action=query) et renvoie les pages obtenues."""
    return requete(url_api(), params).get("query", {}).get("pages", {})


def charger_top_articles():
    """Top des articles les plus vus le mois dernier : [(titre, vues/jour)]. Si Wikimedia n'a pas encore publié ce
    mois-là (réponse 404, fréquent en début de mois), on prend le mois d'avant plutôt que d'échouer."""
    mois_dernier = date.today().replace(day=1) - timedelta(days=1)
    cle = (config.LANGUE, mois_dernier.year, mois_dernier.month)
    if top_en_cache():
        return list(_cache_top[cle][1])
    articles, mois = None, mois_dernier
    for essai in range(2):                       # le mois dernier, puis (s'il n'est pas publié) celui d'avant
        url = TOP_URL.format(langue=config.LANGUE, annee=mois.year, mois=mois.month)
        try:
            articles = requete(url)["items"][0]["articles"]
            break
        except requests.HTTPError as erreur:
            statut = getattr(getattr(erreur, "response", None), "status_code", None)
            if statut != 404 or essai == 1:
                raise
            mois = mois.replace(day=1) - timedelta(days=1)
    nb_jours = calendar.monthrange(mois.year, mois.month)[1]

    resultat = []
    for art in articles:
        titre = art["article"].replace("_", " ")
        # On écarte les pages spéciales (Spécial:, Wikipédia:, Fichier:...)
        if ":" in titre or titre == "Main Page":
            continue
        resultat.append((titre, art["views"] / nb_jours))
    _cache_top.clear()
    _cache_top[cle] = (time.monotonic(), resultat)
    return list(resultat)


def lot_aleatoire():
    """Tire TAILLE_LOT articles au hasard : [(titre, vues/jour)]."""
    pages = appeler_api({
        "action": "query", "format": "json",
        "generator": "random", "grnnamespace": 0, "grnlimit": config.TAILLE_LOT,
        "prop": "pageviews", "pvipdays": config.JOURS_VUES,
    })
    return [(p["title"], calculer_vues(p)[1]) for p in pages.values()]


def _params_details():
    """Ce qu'on demande à Wikipédia pour chaque article : image, description, adresse,
    introduction et vues (une seule requête pour tous les articles)."""
    return {
        "action": "query", "format": "json",
        "prop": "pageimages|description|info|extracts|pageviews",
        "pvipdays": config.JOURS_VUES,
        "piprop": "original|thumbnail",         # image d'origine + miniature
        "pithumbsize": config.TAILLE_MINIATURE,
        "inprop": "url",
        "exintro": 1,                           # uniquement l'introduction
        "explaintext": 1,                       # texte brut, sans balises HTML
        "exsentences": config.NB_PHRASES,       # limite à N phrases
        "exlimit": "max",
    }


HOTES_AUTORISES = (".wikipedia.org", ".wikimedia.org")


def adresse_wikimedia(url):
    """`url` si c'est une adresse https d'un site de Wikipédia ou Wikimedia, sinon None. Tout ce que
    Wikipédia renvoie est traité comme une donnée non fiable : une adresse étrangère, un schéma
    inattendu (javascript:, data:, http:) ou une adresse démesurée n'entre jamais dans une carte."""
    if not isinstance(url, str) or not 8 <= len(url) <= 2000:
        return None
    try:
        morceaux = urlsplit(url)
    except ValueError:
        return None
    hote = (morceaux.hostname or "").lower()
    if morceaux.scheme != "https" or not any(hote.endswith(h) for h in HOTES_AUTORISES):
        return None
    return url


def _entier_positif(valeur):
    if isinstance(valeur, bool) or not isinstance(valeur, int) or valeur < 0:
        return None
    return valeur


def _article(page, code_tire, tire_le):
    """Une page Wikipédia -> dictionnaire d'article (rang calculé d'après les vues).
    `code_tire` : rang tiré au sort (None : le rang de l'article, ex. une carte cherchée)."""
    total_vues, moyenne = calculer_vues(page)
    code, nom_rarete = classer(moyenne)
    image = adresse_wikimedia(page.get("original", {}).get("source")) or "no-image"
    miniature = adresse_wikimedia(page.get("thumbnail", {}).get("source")) or image
    return {
        "rarete": code,
        "rarete_nom": nom_rarete,
        "rarete_tiree": code_tire or code,
        "tire_le": tire_le,      # date et heure du tirage de l'article
        "vues_total": total_vues,
        "vues_moyenne": moyenne,
        "titre": page.get("title", "sans titre"),
        "description": page.get("description", "no-description"),
        "intro": page.get("extract", "").strip() or "no-intro",
        "image": image,          # lien de l'image d'origine (ou "no-image")
        "miniature": miniature,  # version allégée, utilisée sur les cartes
        "taille_octets": _entier_positif(page.get("length")),   # taille de l'article (octets)
        "nb_langues": None,      # langues : liens interlangues de la page (voir ajouter_langues)
        "nb_revisions": None, "revisions_plafonnees": False, "nb_liens_entrants": None,
        "url": adresse_wikimedia(page.get("fullurl")) or (
            f"https://{config.LANGUE}.wikipedia.org/wiki/{quote(page.get('title', 'sans titre').replace(' ', '_'))}"),
        "langue": config.LANGUE,
    }


LOT_DETAILS = 20


def stats_manquantes_des(articles):
    """Nombre de requêtes qu'il faut pour compléter les statistiques de ces articles (modifications et liens entrants :
    une requête chacun, seulement ceux qui n'ont pas encore la valeur)."""
    return sum((art.get("nb_revisions") is None) + (art.get("nb_liens_entrants") is None) for art in articles)


def completer_stats(articles, rappel=None):
    """Récupère les modifications de la page et les liens entrants des articles qui n'en ont pas (une requête chacun),
    et les range dans les dictionnaires. À appeler dans un bloc en_arriere_plan : pas de nouvelle tentative après un 429
    ou un 503. S'ARRÊTE à la première erreur de réseau ou de limite (ce qui manque sera complété plus tard par le fil de
    fond) ; une page qui répond 400, 403 ou 404 est simplement laissée de côté. `rappel(restantes)` est appelé après
    chaque requête. Renvoie le nombre de requêtes faites."""
    restantes = stats_manquantes_des(articles)
    faites = 0
    for art in articles:
        for cle in ("nb_revisions", "nb_liens_entrants"):
            if art.get(cle) is not None:
                continue
            try:
                if cle == "nb_revisions":
                    nombre, plafonne = nb_revisions(art["titre"])
                    art["nb_revisions"], art["revisions_plafonnees"] = nombre, plafonne
                else:
                    art["nb_liens_entrants"] = nb_liens_entrants(art["titre"])
            except requests.HTTPError as erreur:
                statut = getattr(getattr(erreur, "response", None), "status_code", None)
                if statut not in (400, 403, 404):
                    return faites
            except (requests.RequestException, KeyError, ValueError, TypeError, AttributeError, IndexError):
                return faites                      # limite de débit, plafond, panne : on s'arrête, le fil de fond reprendra
            faites += 1
            restantes -= 1
            if rappel is not None:
                rappel(max(0, restantes))
    return faites


class ArticleIntrouvable(Exception):
    """L'article n'existe plus (ou plus sous ce titre) sur Wikipédia."""


def image_actuelle(titre):
    """(image, miniature) actuelles de l'article sur Wikipédia, ou (None, None) s'il n'a toujours pas d'illustration : UNE seule
    requête (l'icône « rafraîchir l'image » d'une carte). Lève requests.RequestException si Wikipédia ne répond pas."""
    articles = recuperer_details([(titre, "C", datetime.now())], avec_stats=False)
    if not articles:
        raise ArticleIntrouvable(titre)
    article = articles[0]
    image = None if article["image"] == "no-image" else article["image"]
    miniature = None if article["miniature"] == "no-image" else article["miniature"]
    return image, miniature


IMAGES_FORMATS = ("image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml")      # un logo est souvent un dessin vectoriel (SVG) : Wikimedia en fait une image PNG
IMAGES_EXCLUES = ("commons-logo", "wikidata", "wiki-", "wikiquote", "wikisource", "wikibooks", "wiktionary", "wikinews", "wikiversity",
                  "wikivoyage", "wikimedia", "question_book", "ambox", "edit-clear", "crystal_clear", "increase2", "decrease2", "steady2",
                  "folder_hexagonal", "portal", "symbol_", "padlock", "red_pencil", "blue_pencil", "flag_of", "loudspeaker", "speaker_icon",
                  "nuvola", "oojs", "ooui", "disambig", "info_icon", "mergefrom", "p_vip", "pictogram", "gnome-", "emblem-", "status_icon",
                  "star_full", "star_empty", "stub", "bandeau", "icon_", "_icon", "lock-", "semi-protection", "cscr-", "featured_article",
                  "good_article", "gloss-", "x-circle", "check_mark", "text-x-generic", "ambox", "wikipedia-logo", "commons-emblem")
IMAGES_EXTENSIONS_EXCLUES = (".ogg", ".oga", ".webm", ".ogv", ".pdf", ".djvu", ".tif", ".tiff", ".mid", ".wav", ".mp3", ".mp4", ".stl", ".xcf")
_cache_images = {}
_sources_images = {}
CACHE_IMAGES_SECONDES = 600
LARGEUR_IMAGE = 960          # largeurs « standard » de Wikimedia (330 et 960) : seules celles-là sont servies sans détour
LARGEUR_VIGNETTE = 330


def _fichier_image(titre_fichier):
    """Un fichier qui est une IMAGE (ni son, ni vidéo, ni document) : il peut figurer dans la liste de choix."""
    nom = str(titre_fichier or "").split(":", 1)[-1].lower()
    return bool(nom) and not nom.endswith(IMAGES_EXTENSIONS_EXCLUES)


def _fichier_mineur(titre_fichier):
    """Une icône d'interface, un logo de projet Wikimedia, un drapeau, un pictogramme : présent dans l'article, mais rarement voulu comme illustration.
    Ces images sont listées aussi (« toutes les images de l'article »), mais cachées tant qu'on ne demande pas à les voir."""
    nom = str(titre_fichier or "").split(":", 1)[-1].lower().replace(" ", "_")
    return any(m in nom for m in IMAGES_EXCLUES)


def _fichier_candidat(titre_fichier):
    """Un fichier d'image d'article qui peut illustrer une carte sans être une icône d'interface (voir _fichier_mineur)."""
    return _fichier_image(titre_fichier) and not _fichier_mineur(titre_fichier)


def _rendu_png_svg(adresse, largeur):
    """L'adresse du rendu PNG (de `largeur` px) d'un dessin SVG, d'après l'adresse de l'original, quand Wikimedia n'en donne pas : la forme est toujours la même
    (…/commons/a/ab/Nom.svg -> …/commons/thumb/a/ab/Nom.svg/960px-Nom.svg.png). None si l'adresse n'a pas cette forme."""
    m = re.match(r"^(https://upload\.wikimedia\.org/wikipedia/[^/]+/)([0-9a-f]/[0-9a-f]{2}/)([^/]+\.svg)$", str(adresse or ""), re.I)
    return f"{m.group(1)}thumb/{m.group(2)}{m.group(3)}/{largeur}px-{m.group(3)}.png" if m else None


def _vignette(adresse_miniature):
    """La même miniature en 330 px (la liste est demandée en 960 px, taille standard)."""
    return adresse_miniature.replace(f"/{LARGEUR_IMAGE}px-", f"/{LARGEUR_VIGNETTE}px-") if f"/{LARGEUR_IMAGE}px-" in adresse_miniature else adresse_miniature


def cle_fichier(adresse):
    return cadrage.cle_image(adresse)


def _ancienne_cle_fichier(adresse):
    """Le nom du fichier d'une adresse Wikimedia (sans le dossier de miniature ni le préfixe « 330px- »), pour reconnaître la MÊME image sous
    deux adresses (l'original, une miniature, un rendu PNG d'un SVG)."""
    from urllib.parse import unquote, urlsplit
    morceaux = [m for m in unquote(urlsplit(str(adresse or "")).path).split("/") if m]
    if not morceaux:
        return ""
    nom = morceaux[-2] if "thumb" in morceaux and len(morceaux) >= 2 and re.match(r"^\d+px-", morceaux[-1]) else morceaux[-1]
    return nom.lower().replace(" ", "_")


def _cle_titre(titre_fichier):
    """Le nom d'un fichier d'après son TITRE (« Fichier:Lio 2013 4.jpg » ou « File:Lio_2013_4.jpg » -> « lio_2013_4.jpg ») : sert à reconnaître le même
    fichier d'une source à l'autre, quelle que soit la langue du préfixe et l'écriture des espaces."""
    return str(titre_fichier or "").split(":", 1)[-1].strip().replace(" ", "_").lower()


def appeler_api_complet(params, suites_max=10):
    """Comme appeler_api, mais SUIT les suites (« continue ») de Wikipédia et FUSIONNE les pages : les listes (images, imageinfo...) sont mises bout à
    bout au lieu d'être écrasées, et les redirections de fichiers sont gardées. Renvoie (pages, {titre demandé: titre final})."""
    params = dict(params)
    pages, redirections = {}, {}
    for _ in range(suites_max):
        donnees = requete(url_api(), params)
        requete_ = donnees.get("query", {}) if isinstance(donnees, dict) else {}
        for cle, page in (requete_.get("pages") or {}).items():
            if not isinstance(page, dict):
                continue
            existante = pages.setdefault(str(page.get("title") or page.get("pageid") or cle), {})      # (le titre : les pages absentes n'ont que des numéros négatifs, réutilisés d'une suite à l'autre)
            for nom, valeur in page.items():
                if isinstance(valeur, list) and isinstance(existante.get(nom), list):
                    existante[nom].extend(valeur)
                else:
                    existante[nom] = valeur
        for r in (requete_.get("normalized") or []) + (requete_.get("redirects") or []):
            if isinstance(r, dict) and "from" in r and "to" in r:
                redirections[r["from"]] = r["to"]
        suite = donnees.get("continue") if isinstance(donnees, dict) else None
        if not suite:
            break
        params.update(suite)
    return pages, redirections


def nom_fichier(adresse):
    """Le nom d'un fichier d'après son adresse Wikimedia, avec ses majuscules (« Lio_2013_4.jpg » -> « Lio 2013 4.jpg »), ou None."""
    return cadrage.nom_fichier(adresse)


_LIEN_FICHIER = re.compile(r"""(?:/wiki/|\./)(?:Fichier|File|Image):([^"'#?<>\s]+)""")
_IMAGE_HTML = re.compile(r"(?:https?:)?//upload\.wikimedia\.org/[^\"'\s<>]+")          # (les noms de fichiers contiennent souvent des parenthèses : « Nom_(recadrée).jpg »)


def _nettoyer_adresse(adresse):
    """Retire d'une adresse trouvée dans le HTML ce qui ne lui appartient pas : une virgule de « srcset », une parenthèse fermante de « url(...) » (mais pas
    celles du nom du fichier, qui vont par paires)."""
    while adresse and (adresse[-1] in ",;" or (adresse[-1] == ")" and adresse.count(")") > adresse.count("("))):
        adresse = adresse[:-1]
    return adresse


def _titres_page_html(titre):
    """Les fichiers d'image AFFICHÉS dans l'article, dans l'ordre de la page, tous chapitres confondus : on lit la page telle que Wikipédia la montre
    (infobox, photos, galeries, images ajoutées par les modèles et par Wikidata). Une requête. Facultatif : en cas d'échec, la liste des fichiers
    utilisés par l'article (imagelinks) suffit."""
    try:
        donnees = requete(url_api(), {"action": "parse", "page": titre, "prop": "text", "format": "json", "redirects": 1,
                                      "disableeditsection": 1, "disabletoc": 1, "disablelimitreport": 1})
        texte = (donnees.get("parse") or {}).get("text")
        if isinstance(texte, dict):
            texte = texte.get("*")
        if not isinstance(texte, str):
            return []
    except (requests.RequestException, ValueError, AttributeError, KeyError, TypeError):
        return []
    trouves = []                                           # (position dans la page, nom du fichier) : deux façons de repérer chaque image affichée
    for m in _IMAGE_HTML.finditer(texte):                  # 1) l'adresse de l'image (src, srcset, style...)
        adresse = _nettoyer_adresse(m.group(0))
        trouves.append((m.start(), nom_fichier("https:" + adresse if adresse.startswith("//") else adresse)))
    for m in _LIEN_FICHIER.finditer(texte):                # 2) le LIEN vers la page du fichier (<a href="/wiki/Fichier:Nom.jpg">) : présent même si l'image se charge autrement
        trouves.append((m.start(), unquote(m.group(1)).replace("_", " ")))
    titres, vus = [], set()
    for _, nom in sorted(trouves, key=lambda x: x[0]):
        if nom and _cle_titre(nom) not in vus and re.search(r"\.[A-Za-z0-9]{2,5}$", nom):
            vus.add(_cle_titre(nom))
            titres.append("File:" + nom)
    return titres


def _titres_media_liste(titre):
    """Les fichiers d'image de l'article d'après le service « media-list » de Wikipédia (tout ce que la page affiche, infobox et Wikidata compris), dans
    l'ordre de la page. Source supplémentaire et facultative : en cas d'échec, les autres sources suffisent."""
    try:
        donnees = requete(f"https://{config.LANGUE}.wikipedia.org/api/rest_v1/page/media-list/{quote(str(titre).replace(' ', '_'), safe='')}")
        elements = donnees.get("items") or []
    except (requests.RequestException, ValueError, AttributeError, KeyError, TypeError):
        return []
    titres = []
    for element in elements:
        if isinstance(element, dict) and element.get("type") in (None, "image") and isinstance(element.get("title"), str):
            titres.append(element["title"])
    return titres


def images_article(titre, maxi=200):
    """TOUTES les images d'un article, de tous ses chapitres : [{"nom", "image", "miniature", "largeur", "hauteur", "mineure"}], dans l'ordre de la page
    (logo ou photo d'en-tête, puis chaque chapitre). Deux sources sont réunies : les images AFFICHÉES dans la page (« media-list », qui comprend aussi ce
    que les modèles et Wikidata y ajoutent) et les fichiers UTILISÉS par l'article (imagelinks). Les suites de résultats de Wikipédia sont suivies et les
    fichiers renommés (redirections) retrouvés : aucune image n'est perdue en route. `mineure` : icône ou pictogramme (drapeau, logo de projet Wikimedia,
    image minuscule ou démesurée) listé aussi mais caché par défaut. Un dessin SVG est proposé sous la forme de son rendu PNG (960 px). Seuls des adresses
    Wikimedia et des formats d'image courants sont gardés. Gardé 10 minutes en mémoire. Lève requests.RequestException si Wikipédia ne répond pas."""
    cle = (config.LANGUE, str(titre))
    maintenant = time.monotonic()
    if cle in _cache_images and maintenant - _cache_images[cle][0] < CACHE_IMAGES_SECONDES:
        return [dict(i) for i in _cache_images[cle][1]]
    titres = []
    vus = set()

    def ajouter(titre_fichier):
        k = _cle_titre(titre_fichier)
        if k and k not in vus and _fichier_image(titre_fichier):
            vus.add(k)
            titres.append(titre_fichier)
    sources = {"page": 0, "fichiers": 0}
    raisons = {}                                           # clé du fichier -> pourquoi il n'est pas utilisable (pour le diagnostic)
    for t in _titres_page_html(titre):
        ajouter(t)
    sources["page"] = len(titres)
    for t in _titres_media_liste(titre):                   # 3e source : le service « media-list » (infobox et images de Wikidata comprises)
        ajouter(t)
    sources["media"] = len(titres) - sources["page"]       # (ce qu'elle a apporté en plus de la page)
    pages, _ = appeler_api_complet({"action": "query", "format": "json", "titles": titre, "prop": "images", "imlimit": "max", "redirects": 1})
    avant_fichiers = len(titres)
    for page in pages.values():
        for image in page.get("images") or []:
            if isinstance(image, dict):
                ajouter(image.get("title"))
    sources["fichiers"] = sum(1 for page in pages.values() for _ in (page.get("images") or []))
    titres = titres[:maxi]
    trouvees = {}                                          # clé du fichier FINAL -> description
    suivi = {}                                             # clé du fichier demandé -> clé du fichier final (après redirection)
    for debut in range(0, len(titres), 40):
        if debut:
            time.sleep(max(0.0, float(config.PAUSE)))
        lot = titres[debut:debut + 40]
        infos, redirections = appeler_api_complet({"action": "query", "format": "json", "titles": "|".join(lot), "prop": "imageinfo", "redirects": 1,
                                                   "iiprop": "url|size|mime", "iiurlwidth": LARGEUR_IMAGE})
        for demande in lot:
            final = redirections.get(demande, demande)
            suivi[_cle_titre(demande)] = _cle_titre(redirections.get(final, final))
        for page in infos.values():
            cle_page = _cle_titre(page.get("title"))
            if not page.get("imageinfo"):
                raisons[cle_page] = "Wikimedia ne donne aucune information sur ce fichier"
            for info in page.get("imageinfo") or []:
                largeur, hauteur = info.get("width"), info.get("height")
                vecteur = info.get("mime") == "image/svg+xml"
                if info.get("mime") not in IMAGES_FORMATS:
                    raisons[cle_page] = f"format non pris en charge ({info.get('mime')})"
                    continue
                if not isinstance(largeur, int) or not isinstance(hauteur, int) or isinstance(largeur, bool) or isinstance(hauteur, bool) or largeur < 1 or hauteur < 1:
                    raisons[cle_page] = "dimensions inconnues"
                    continue
                petit, grand = min(largeur, hauteur), max(largeur, hauteur)
                mineure = (_fichier_mineur(page.get("title")) or petit < 40 or largeur * hauteur < 10000 or grand > 12 * petit)
                original = adresse_wikimedia(info.get("url"))
                rendu_svg = (adresse_wikimedia(info.get("thumburl")) or _rendu_png_svg(original, LARGEUR_IMAGE)) if vecteur else None   # (un SVG sans vignette : on la déduit)
                miniature_api = adresse_wikimedia(info.get("thumburl")) or rendu_svg or original
                url = rendu_svg if vecteur else original
                if not url or not miniature_api:
                    raisons[cle_page] = "adresse du fichier absente ou non Wikimedia"
                    continue
                trouvees[_cle_titre(page.get("title"))] = {"nom": str(page.get("title", "")).split(":", 1)[-1][:120], "image": url,
                                                          "miniature": _vignette(miniature_api), "largeur": largeur, "hauteur": hauteur, "mineure": bool(mineure)}
    resultat, deja = [], set()
    for t in titres:                                       # dans l'ordre de la page, sans doublon (un fichier renommé n'est listé qu'une fois)
        k = suivi.get(_cle_titre(t), _cle_titre(t))
        if k in trouvees and k not in deja:
            deja.add(k)
            resultat.append(trouvees[k])
    for k, image in trouvees.items():                      # (un fichier reçu sous un nom inattendu n'est pas perdu)
        if k not in deja:
            deja.add(k)
            resultat.append(image)
    ecartees = []                                          # les fichiers de l'article qu'on n'a pas pu lister, avec la raison (jamais en silence)
    for t in titres:
        k = suivi.get(_cle_titre(t), _cle_titre(t))
        if k not in trouvees:
            ecartees.append([str(t).split(":", 1)[-1][:80], raisons.get(k) or raisons.get(_cle_titre(t)) or "Wikimedia ne donne aucune information sur ce fichier"])
    _cache_images[cle] = (maintenant, resultat)
    _sources_images[cle] = dict(sources, total=len(resultat), ecartees=ecartees[:30], nb_ecartees=len(ecartees))
    return [dict(i) for i in resultat]


def reunir_images(frais, memorisees):
    """Les images qu'on vient de lire dans l'article, PUIS celles qu'on avait déjà vues dans cet article lors d'un chargement précédent et que ce chargement-ci ne
    retrouve pas : une image présente un jour dans la liste ne disparaît plus (page lue de travers, fichier renommé, panne passagère...). Sans doublon."""
    vues = {cle_fichier(i["image"]) for i in frais}
    reste = []
    for i in memorisees or []:
        k = cle_fichier(i.get("image"))
        if k and k not in vues:
            vues.add(k)
            reste.append(dict(i))
    return [dict(i) for i in frais] + reste


def sources_images(titre):
    """D'où viennent les images listées pour cet article : {"page": images affichées dans la page, "fichiers": fichiers utilisés par l'article, "total"}."""
    return dict(_sources_images.get((config.LANGUE, str(titre)), {}))


def fusionner_images(candidats, principale=None, actuelle=None, miniature_actuelle=None, precedente=None):
    """La liste à proposer pour une carte : l'image que la carte porte DÉJÀ (`actuelle: True`), l'image principale de l'article choisie par Wikipédia
    (`principale: True`), l'illustration qu'on vient de retirer (`precedente: True`, pour pouvoir la remettre), puis TOUTES les autres, dans l'ordre de
    la page. Les icônes et pictogrammes (`mineure`) viennent à la fin, mais sont listés. Une image qui figure deux fois (sous deux adresses) n'est
    listée qu'une fois. `principale`, `precedente` : (image, miniature) ou (None, None)."""
    liste = []
    vues = {}

    def ajouter(entree):
        k = cle_fichier(entree["image"])
        if k in vues:
            vues[k].update({c: v for c, v in entree.items() if c in ("actuelle", "principale", "precedente") and v})
            return
        entree.setdefault("actuelle", False)
        entree.setdefault("principale", False)
        entree.setdefault("precedente", False)
        entree.setdefault("mineure", False)
        vues[k] = entree
        liste.append(entree)
    par_cle = {cle_fichier(c["image"]): c for c in candidats}

    def entree_de(adresse, miniature, nom_defaut):
        return dict(par_cle.get(cle_fichier(adresse)) or {"nom": (nom_fichier(adresse) or nom_defaut)[:120], "image": adresse, "miniature": miniature or adresse,
                                                          "largeur": 0, "hauteur": 0, "mineure": False})
    if actuelle:
        e = entree_de(actuelle, miniature_actuelle, "image actuelle")
        e["actuelle"] = True
        ajouter(e)
    if principale and principale[0]:
        e = entree_de(principale[0], principale[1], "image principale")
        e["principale"] = True
        e["mineure"] = False                        # l'image principale choisie par Wikipédia n'est jamais « mineure »
        ajouter(e)
    if precedente and precedente[0]:
        e = entree_de(precedente[0], precedente[1], "image d'origine")
        e["precedente"] = True
        e["mineure"] = False
        ajouter(e)
    for c in candidats:
        ajouter(dict(c))
    return [e for e in liste if not e["mineure"]] + [e for e in liste if e["mineure"]]


# ----------------------------------------------------- GIF : réellement animé ?

def gif_anime_octets(donnees):
    """Un fichier GIF (ses premiers octets) est-il RÉELLEMENT animé ? True (plusieurs images), False (une seule image : GIF fixe), None (on ne sait pas : le
    début du fichier ne suffit pas, ou il est abîmé). Le fichier n'est jamais interprété autrement que par sa structure (blocs)."""
    b = bytes(donnees or b"")
    if len(b) < 13 or b[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    i = 13
    if b[10] & 0x80:
        i += 3 * (2 << (b[10] & 7))                   # palette globale
    images = 0
    while i < len(b):
        bloc = b[i]
        if bloc == 0x3B:                              # fin du fichier : on a tout vu
            return images > 1
        if bloc == 0x21:                              # extension (commentaire, contrôle d'image...) : des sous-blocs
            i += 2
        elif bloc == 0x2C:                            # une image
            if i + 10 > len(b):
                break
            images += 1
            if images >= 2:
                return True
            drapeaux = b[i + 9]
            i += 10
            if drapeaux & 0x80:
                i += 3 * (2 << (drapeaux & 7))        # palette locale
            i += 1                                    # taille minimale du code LZW
        else:
            return None
        while i < len(b):                             # les sous-blocs (longueur puis données, fini par une longueur 0)
            n = b[i]
            i += 1
            if n == 0:
                break
            i += n
        else:
            break
    return True if images >= 2 else None


def _nombre_images_gif(info):
    """Le nombre d'images d'un GIF d'après les métadonnées de Wikimedia (frameCount), ou None."""
    meta = info.get("metadata")
    if isinstance(meta, dict):
        valeur = meta.get("frameCount")
    elif isinstance(meta, list):
        valeur = next((m.get("value") for m in meta if isinstance(m, dict) and m.get("name") == "frameCount"), None)
    else:
        return None
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    return int(valeur)


def _gif_anime_telecharge(adresse):
    """Dernier recours (Wikimedia n'a pas de métadonnées pour ce fichier) : on lit le DÉBUT du GIF (jusqu'à 4 Mo, par tranches) et on compte ses images."""
    if adresse_wikimedia(adresse) is None:
        return None
    recu = b""
    for fin in (262143, 4194303):
        time.sleep(max(0.0, float(config.PAUSE)))
        reponse = SESSION.get(adresse, headers={"Range": f"bytes=0-{fin}", "User-Agent": _agent()}, timeout=(6, 25), stream=True)
        try:
            reponse.raise_for_status()
            recu = reponse.raw.read(fin + 1, decode_content=True) if reponse.status_code == 206 or reponse.status_code == 200 else b""
            complet = reponse.status_code == 200 or len(recu) <= fin
        finally:
            reponse.close()
        resultat = gif_anime_octets(recu)
        if resultat is not None or complet:
            return resultat
    return None


def verifier_gifs(adresses, telechargements_max=3):
    """{adresse: True (animé) / False (fixe) / None (inconnu)} pour des adresses d'images GIF : une requête à Wikimedia pour 40 fichiers (leurs
    métadonnées : nombre d'images). Pour ceux dont Wikimedia ne dit rien, on lit le début du fichier (au plus `telechargements_max` à la fois)."""
    adresses = [a for a in dict.fromkeys(adresses) if isinstance(a, str)]
    resultat = {a: None for a in adresses}
    par_cle = {}
    for adresse in adresses:
        nom = nom_fichier(adresse)
        if nom:
            par_cle.setdefault(_cle_titre(nom), []).append((adresse, nom))
    cles = list(par_cle)
    for debut in range(0, len(cles), 40):
        if debut:
            time.sleep(max(0.0, float(config.PAUSE)))
        noms = [par_cle[k][0][1] for k in cles[debut:debut + 40]]
        pages, redirections = appeler_api_complet({"action": "query", "format": "json", "titles": "|".join("File:" + n for n in noms), "prop": "imageinfo",
                                                   "iiprop": "metadata|mime", "redirects": 1})
        finales = {}
        for page in pages.values():
            for info in page.get("imageinfo") or []:
                finales[_cle_titre(page.get("title"))] = info
        for k in cles[debut:debut + 40]:
            nom = par_cle[k][0][1]
            final = redirections.get("File:" + nom, "File:" + nom)
            info = finales.get(_cle_titre(redirections.get(final, final))) or finales.get(k)
            if info is None or info.get("mime") not in (None, "image/gif"):
                continue
            images = _nombre_images_gif(info)
            if images is not None:
                for adresse, _ in par_cle[k]:
                    resultat[adresse] = images > 1
    restants = [a for a in adresses if resultat[a] is None][:max(0, int(telechargements_max))]
    for adresse in restants:
        try:
            resultat[adresse] = _gif_anime_telecharge(adresse)
        except (requests.RequestException, OSError, ValueError):
            resultat[adresse] = None
    return resultat


def marquer_gifs(articles):
    """Ajoute `gif_anime` (True/False) aux articles dont l'illustration est un .gif, en une requête. Sans effet (None) si Wikimedia ne répond pas."""
    def affichee(art):
        adresse = art.get("miniature") if art.get("miniature") not in (None, "no-image") else art.get("image")
        return adresse if isinstance(adresse, str) and adresse.split("?", 1)[0].lower().endswith(".gif") else None
    gifs = {id(a): affichee(a) for a in articles if a.get("gif_anime") is None and affichee(a)}
    if not gifs:
        return
    try:
        res = verifier_gifs(list(gifs.values()))
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return
    for art in articles:
        if id(art) in gifs:
            art["gif_anime"] = res.get(gifs[id(art)])


def recuperer_details(tirages, avec_stats=True):
    """Récupère les détails des articles tirés :
    [(titre, rang_tiré, horodatage)] -> [dict]. Avec STATS_CARTES (et `avec_stats`), ajoute le nombre de
    langues (une requête de plus pour tous les articles : voir langues_wikipedia). `avec_stats=False` :
    aucune requête de statistiques (recherche : les statistiques sont récupérées plus tard, avec la
    politesse habituelle, pour les seules cartes qui entrent dans la collection)."""
    titres = [tirage[0] for tirage in tirages]
    # Wikipédia ne donne l'introduction que de 20 articles par requête : on découpe par lots de 20 (un paquet n'en a pas plus).
    par_titre = {}
    for debut in range(0, len(titres), LOT_DETAILS):
        if debut:
            time.sleep(max(0.0, float(config.PAUSE)))             # politesse entre deux lots
        params = _params_details()
        params["titles"] = "|".join(titres[debut:debut + LOT_DETAILS])
        par_titre.update({page["title"]: page for page in appeler_api(params).values()})

    articles = []
    for titre, code_tire, tire_le in tirages:
        page = par_titre.get(titre)
        if page is None:
            continue
        articles.append(_article(page, code_tire, tire_le))
    if config.STATS_CARTES and avec_stats:
        try:
            ajouter_langues(articles)
        except requests.RequestException:
            pass          # les langues sont facultatives : une panne ne bloque pas un paquet
    return articles


def rechercher(texte, limite, decalage=0):
    """Cherche des articles sur Wikipédia (recherche en texte intégral) et renvoie leurs détails,
    du plus pertinent au moins pertinent : [dict]. UNE seule requête, qui donne aussi les vues
    de chaque article (donc leur rang). Les cartes ne sont pas enregistrées. `decalage` : nombre de résultats
    déjà vus (bouton « Voir plus de résultats ») ; chaque article reçoit `pertinence`, sa place dans la liste de Wikipédia."""
    params = _params_details()
    params.update({"generator": "search", "gsrsearch": texte, "gsrnamespace": 0,
                   "gsrlimit": max(1, min(int(limite), 20)), "gsroffset": max(0, int(decalage))})
    pages = appeler_api(params)
    ordonnees = sorted(pages.values(), key=lambda page: page.get("index", 0))
    articles = []
    for i, page in enumerate(ordonnees):
        article = _article(page, None, None)
        article["pertinence"] = max(0, int(decalage)) + i
        articles.append(article)
    if int(decalage) == 0:                      # premier lot : on ajoute les articles dont le TITRE commence par ce qui est tapé
        try:
            connus = {a["url"] for a in articles}
            for article in _rechercher_prefixe(texte):
                if article["url"] not in connus:
                    article["pertinence"] = len(articles)        # (le classement par pertinence se fait ensuite, dans recherche.py)
                    articles.append(article)
        except (requests.RequestException, KeyError, ValueError):
            pass                                  # la recherche principale suffit : le complément est facultatif
    marquer_gifs(articles)                        # un résultat n'est « Animé » que si son GIF l'est vraiment
    return articles


def _rechercher_prefixe(texte, limite=6):
    """Les articles dont le titre COMMENCE par ce qu'on a tapé (recherche par préfixe de Wikipédia) : une requête de plus, au premier lot
    seulement. Elle retrouve l'article « Paris » quand on tape « par », que la recherche en texte intégral place parfois loin."""
    params = _params_details()
    params.update({"generator": "prefixsearch", "gpssearch": texte, "gpsnamespace": 0, "gpslimit": max(1, min(int(limite), 10))})
    pages = appeler_api(params)
    return [_article(page, None, None) for page in sorted(pages.values(), key=lambda page: page.get("index", 0))]


# ----------------------------------------------------- statistiques des articles

MAX_SUITES = 12          # au plus 12 requêtes de suite pour compter les liens interlangues d'un lot


def langues_wikipedia(titres):
    """{titre: nombre de langues} : EXACTEMENT le « N langues » que Wikipédia affiche pour l'article,
    c'est-à-dire le nombre de ses liens interlangues (les autres éditions de Wikipédia : la langue
    de l'article lui-même n'est pas comptée). Une requête pour 50 articles au plus ; si Wikipédia
    découpe sa réponse (500 liens au maximum par réponse), on lit la suite. Un article introuvable
    est absent du résultat."""
    titres = list(dict.fromkeys(t.replace("_", " ") for t in titres if isinstance(t, str) and t.strip()))
    resultat = {}
    for debut in range(0, len(titres), 50):
        params = {"action": "query", "format": "json", "prop": "langlinks", "lllimit": "max",
                  "titles": "|".join(titres[debut:debut + 50])}
        for _ in range(MAX_SUITES):
            donnees = requete(url_api(), params)
            for page in ((donnees.get("query") or {}).get("pages") or {}).values():
                if isinstance(page, dict) and "title" in page and "missing" not in page:
                    resultat[page["title"]] = (resultat.get(page["title"], 0)
                                               + len(page.get("langlinks") or []))
            suite = donnees.get("continue")
            if not suite:
                break
            params = {**params, **suite}
    return resultat


def ajouter_langues(articles):
    """Complète `nb_langues` de ces articles (dictionnaires ayant un « titre »)."""
    langues = langues_wikipedia([a["titre"] for a in articles])
    for article in articles:
        nombre = langues.get(str(article["titre"]).replace("_", " "))
        if nombre is not None:
            article["nb_langues"] = nombre


def tailles(titres):
    """{titre: taille de l'article en octets} d'articles déjà connus : la « taille de la page » de
    Wikipédia (page « Informations sur la page »). Un article disparu est absent du résultat."""
    pages = appeler_api({"action": "query", "format": "json", "prop": "info",
                         "titles": "|".join(titres)})
    return {page["title"]: _entier_positif(page.get("length"))
            for page in pages.values() if isinstance(page, dict) and "title" in page}


def nb_revisions(titre):
    """(nombre de modifications de la page, plafonné ?) : une seule requête (API REST). Wikipédia
    plafonne le décompte des pages très modifiées (30 000) : « plafonné » vaut alors True."""
    chemin = quote(str(titre).replace(" ", "_"), safe="")
    donnees = requete(f"https://{config.LANGUE}.wikipedia.org/w/rest.php/v1/page/{chemin}"
                      "/history/counts/edits")
    nombre = donnees["count"]
    if isinstance(nombre, bool) or not isinstance(nombre, int) or nombre < 0:
        raise ValueError("nombre de modifications invalide")
    return nombre, bool(donnees.get("limit"))


def nb_liens_entrants(titre):
    """Nombre de pages de Wikipédia (articles) qui pointent vers cette page : une seule requête
    (le total des résultats d'une recherche « linksto: »)."""
    sans_guillemets = str(titre).replace('"', " ")
    donnees = requete(url_api(), {
        "action": "query", "format": "json", "list": "search", "srnamespace": 0, "srlimit": 1,
        "srinfo": "totalhits", "srprop": "", "srsearch": f'linksto:"{sans_guillemets}"'})
    nombre = donnees["query"]["searchinfo"]["totalhits"]
    if isinstance(nombre, bool) or not isinstance(nombre, int) or nombre < 0:
        raise ValueError("nombre de liens invalide")
    return nombre
