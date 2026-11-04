"""Tous les appels à Wikipedia / Wikimedia (réseau uniquement, aucune mise en forme)."""

import calendar
import itertools
import queue
import re
import threading
import time
from concurrent.futures import Future
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from urllib.parse import quote, unquote, urlsplit

import requests

from . import cadrage, config, journal
from .rarete import calculer_vues, classer

TOP_URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
           "{langue}.wikipedia/all-access/{annee}/{mois:02d}/all-days")

# Les vues d'UN article, par le service dédié de Wikimedia (jour par jour) : sert de SECOURS quand la requête groupée (prop=pageviews) ne donne rien pour un article.
URL_VUES_ARTICLE = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{projet}/all-access/user/{titre}/daily/{debut}/{fin}")

SESSION = requests.Session()
_VERROU_RESEAU = threading.Lock()   # une seule requête à la fois, tous fils d'exécution confondus
_local = threading.local()          # mode « arrière-plan » du fil courant (voir en_arriere_plan)
_derniere_requete = 0.0
_dernier_depart = 0.0               # (mode parallèle) instant du dernier DÉPART de requête
_cache_vues = {}                    # titre -> vues par jour des articles tirés au hasard : leurs vues sont DÉJÀ connues (aucune requête de plus pour elles)
CACHE_VUES_MAX = 800
_mesures = {"requetes": 0, "somme": 0.0, "max": 0.0, "en_vol": 0, "max_en_vol": 0}     # ce que fait l'ouverture d'un paquet, pour le journal (voir mesures_zero / mesures)
_nb_mesures = 0                     # requêtes dont la durée a été mesurée depuis le lancement (tant qu'il y en a peu, la durée d'une requête est surtout une valeur de départ)
_pause_imposee = 0.0                # instant (monotone) avant lequel plus aucune requête ne part : Wikipédia a demandé de patienter à un fil auxiliaire (Retry-After)
_VERROU_DEPARTS = threading.Lock()  # espace les départs des requêtes du mode parallèle
_VERROU_MESURES = threading.Lock()
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


def mesures_zero():
    """Remet à zéro le décompte des requêtes (au début de l'ouverture d'un paquet)."""
    with _VERROU_MESURES:
        _mesures.update(requetes=0, somme=0.0, max=0.0, en_vol=0, max_en_vol=0)


def mesures():
    """{requetes, moyenne (s), plus_lente (s), simultanees_max} depuis mesures_zero : de quoi dire, dans le journal, ce que l'ouverture d'un paquet a demandé à Wikipédia."""
    with _VERROU_MESURES:
        n = _mesures["requetes"]
        return {"requetes": n, "moyenne": (_mesures["somme"] / n) if n else 0.0, "plus_lente": _mesures["max"], "simultanees_max": _mesures["max_en_vol"]}


def _requete_partie():
    with _VERROU_MESURES:
        _mesures["en_vol"] += 1
        _mesures["max_en_vol"] = max(_mesures["max_en_vol"], _mesures["en_vol"])


def _requete_finie(duree):
    with _VERROU_MESURES:
        _mesures["en_vol"] = max(0, _mesures["en_vol"] - 1)
        _mesures["requetes"] += 1
        _mesures["somme"] += duree
        _mesures["max"] = max(_mesures["max"], duree)


def memoriser_vues(pages):
    """Garde les vues des pages qui en ont (tirage au hasard) : quand l'une d'elles est tirée pour un paquet, ses vues sont déjà là."""
    with _VERROU_MESURES:
        for page in pages:
            if isinstance(page, dict) and page.get("title") and not vues_manquantes(page):
                _cache_vues[page["title"]] = dict(page["pageviews"])
        while len(_cache_vues) > CACHE_VUES_MAX:
            _cache_vues.pop(next(iter(_cache_vues)))


def vues_connues(titre):
    return _cache_vues.get(titre)


class LimiteParallele(requests.RequestException):
    """(mode parallèle) Wikipédia demande de ralentir pendant qu'on faisait plusieurs requêtes à la fois : on arrête les requêtes simultanées. `delai` : secondes à patienter."""

    def __init__(self, delai, message=""):
        super().__init__(message or f"Wikipédia demande de patienter {delai:.0f} s")
        self.delai = delai


class MaxLag(requests.RequestException):
    """Les serveurs de Wikipédia sont en retard (paramètre maxlag) : l'API demande de revenir dans quelques secondes. `delai` : secondes à patienter."""

    def __init__(self, delai, message=""):
        super().__init__(message or f"Les serveurs de Wikipédia sont chargés : patienter {delai:.0f} s")
        self.delai = delai


# L'importation en lot (lot.py) est exclusive : pendant qu'elle travaille, aucune autre requête à Wikipédia ne part (ni réserve, ni statistiques, ni GIF...).
bloque_par_lot = lambda: False                  # remplacé par lot.actif au chargement de lot.py


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


class Parallele:
    """Quelques fils auxiliaires qui font des requêtes EN MÊME TEMPS que le fil principal, pour l'ouverture d'un paquet (voir en_parallele). Les travaux sont pris par priorité
    (0 d'abord). Les départs de requêtes sont espacés (config.PAQUET_ECART) et le nombre de requêtes simultanées est borné (config.PAQUET_SIMULTANEES, fil principal compris)."""

    def __init__(self, simultanes, ecart):
        self.simultanes = max(1, int(simultanes))
        self.ecart = max(0.05, float(ecart))
        self.arret = threading.Event()               # levé à la première demande de ralentir de Wikipédia : plus de requêtes simultanées
        self._etat = {"ecart": self.ecart, "arret": self.arret, "travailleur": False}
        self._file = queue.PriorityQueue()
        self._compteur = itertools.count()
        self._fils = []
        self._ferme = False
        for i in range(self.simultanes - 1):
            fil = threading.Thread(target=self._boucle, name=f"paquet-{i}", daemon=True)
            fil.start()
            self._fils.append(fil)

    def _boucle(self):
        _local.parallele = {**self._etat, "travailleur": True}
        while True:
            _, _, tache = self._file.get()
            if tache is None:
                return
            futur, fonction, arguments = tache
            if not futur.set_running_or_notify_cancel():
                continue
            if self.arret.is_set():
                futur.set_exception(LimiteParallele(0, "requêtes simultanées arrêtées"))
                continue
            try:
                futur.set_result(fonction(*arguments))
            except BaseException as erreur:
                futur.set_exception(erreur)

    def soumettre(self, fonction, *arguments, priorite=1):
        """Un travail à faire par un fil auxiliaire ; renvoie un Future. Sans fil auxiliaire (une seule requête à la fois), il est fait tout de suite."""
        futur = Future()
        if not self._fils or self._ferme:
            try:
                futur.set_result(fonction(*arguments))
            except BaseException as erreur:
                futur.set_exception(erreur)
            return futur
        self._file.put((priorite, next(self._compteur), (futur, fonction, arguments)))
        return futur

    def fermer(self):
        """Annule ce qui n'a pas démarré, puis attend les requêtes déjà parties (au plus la durée d'une requête)."""
        self._ferme = True
        try:
            while True:
                _, _, tache = self._file.get_nowait()
                if tache is not None:
                    tache[0].cancel()
        except queue.Empty:
            pass
        for _ in self._fils:
            self._file.put((99, next(self._compteur), None))
        for fil in self._fils:
            fil.join(timeout=30)


@contextmanager
def en_parallele(simultanes=None, ecart=None):
    """Pour l'OUVERTURE D'UN PAQUET (une action de l'utilisateur, une quinzaine de requêtes) : plusieurs requêtes à la fois, au lieu d'une seule, pour qu'elle dure quelques secondes
    au lieu d'une demi-minute. Ce n'est PAS un déluge : au plus `simultanes` requêtes en même temps (3 par défaut, fil principal compris), un départ toutes les `ecart` secondes (0,3 s :
    3 requêtes par seconde au maximum), et à la première demande de ralentir de Wikipédia tout repasse à une requête à la fois. Le pré-chargement et les statistiques d'arrière-plan ne
    sont jamais parallèles. `simultanes` = 1 : comportement d'avant (une à la fois, avec la pause habituelle)."""
    parallele = Parallele(config.PAQUET_SIMULTANEES if simultanes is None else simultanes, config.PAQUET_ECART if ecart is None else ecart)
    precedent = getattr(_local, "parallele", None)
    if parallele._fils:
        _local.parallele = {**parallele._etat, "travailleur": False}
    try:
        yield parallele
    finally:
        _local.parallele = precedent
        parallele.fermer()


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
    global _derniere_requete, _latence, _dernier_depart, _pause_imposee, _nb_mesures
    SESSION.headers["User-Agent"] = _agent()      # le contact peut changer dans la configuration
    arriere = getattr(_local, "arriere", None)
    if bloque_par_lot() and not getattr(_local, "lot", False):
        if arriere:
            raise LimiteDebit(30, "importation en lot en cours")          # un fil de fond patiente
        raise requests.RequestException("une importation en lot est en cours : patiente jusqu'à sa fin")
    for essai in range(1 if arriere else config.MAX_ESSAIS):
        attente = _pause_imposee - time.monotonic()                         # Wikipédia a demandé de patienter (à un fil auxiliaire) : personne ne l'ignore
        if attente > 0 and not arriere:
            time.sleep(min(attente, 60.0))
        parallele = getattr(_local, "parallele", None)                      # le mode parallèle (ouverture d'un paquet) : voir en_parallele
        if parallele is not None and (parallele["arret"].is_set() or arriere):
            parallele = None                                                # Wikipédia a demandé de ralentir : on revient à UNE requête à la fois
        if parallele is not None:
            with _VERROU_DEPARTS:                                           # au plus une requête qui DÉMARRE toutes les `ecart` secondes (pas de rafale)
                attente = parallele["ecart"] - (time.monotonic() - _dernier_depart)
                if attente > 0:
                    time.sleep(attente)
                _dernier_depart = time.monotonic()
            debut = time.monotonic()
            _requete_partie()
            try:
                reponse = SESSION.get(url, params=params, timeout=15)
            except requests.RequestException as erreur_reseau:
                _requete_finie(time.monotonic() - debut)
                journal.erreur(f"Wikipédia injoignable ({type(erreur_reseau).__name__}) : {str(url)[:80]}")
                raise
            fin = time.monotonic()
            _requete_finie(fin - debut)
            with _VERROU_MESURES:
                _derniere_requete = fin
                journal.reseau(url, params, reponse.status_code, fin - debut)
                if reponse.status_code not in (429, 503):
                    _latence = min(5.0, max(0.05, 0.5 * _latence + 0.5 * (fin - debut)))
                    _nb_mesures += 1
        else:
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
                _requete_partie()
                try:
                    reponse = SESSION.get(url, params=params, timeout=15)
                except requests.RequestException as erreur_reseau:
                    _requete_finie(time.monotonic() - debut)
                    journal.erreur(f"Wikipédia injoignable ({type(erreur_reseau).__name__}) : {str(url)[:80]}")
                    raise
                _derniere_requete = time.monotonic()
                _requete_finie(_derniere_requete - debut)
                journal.reseau(url, params, reponse.status_code, _derniere_requete - debut)
                if reponse.status_code not in (429, 503):     # la durée d'une requête sert aux estimations
                    _latence = min(5.0, max(0.05, 0.5 * _latence + 0.5 * (_derniere_requete - debut)))
                    _nb_mesures += 1
        if arriere:
            arriere["derniere"] = time.monotonic()

        if reponse.status_code in (429, 503):
            try:
                delai = float(reponse.headers["Retry-After"])
            except (KeyError, ValueError):
                delai = 2 * 2 ** essai          # 2, 4, 8, 16, 32 s
            delai = min(delai, 3600 if arriere else 60)
            if parallele is not None:
                deja_signale = parallele["arret"].is_set()
                parallele["arret"].set()        # plus aucune requête simultanée : on revient à une seule à la fois
                if parallele["travailleur"]:
                    _pause_imposee = max(_pause_imposee, time.monotonic() + delai)   # la prochaine requête (du fil principal) attendra ce délai ; la page en est prévenue UNE fois
                    if not deja_signale:
                        journal.logiciel(f"Wikipédia demande de ralentir : toutes les requêtes patientent {delai:.0f} s")
                        if ecouteur_ralentissement is not None:
                            ecouteur_ralentissement(delai)
                    raise LimiteParallele(delai)    # un fil auxiliaire n'attend pas lui-même
            if arriere:
                raise LimiteDebit(delai)        # pas de nouvelle tentative en arrière-plan
            journal.logiciel(f"Wikipédia demande de ralentir : nouvelle tentative dans {delai:.0f} s")
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


def telecharger(url, max_octets, max_redirections=3):
    """Télécharge UN fichier (une image) d'un serveur Wikimedia, avec la même courtoisie que les autres requêtes (une à la fois, pause commune, jamais pendant une
    importation en lot) et sans jamais sortir de Wikimedia : chaque adresse, redirections comprises, doit être une adresse Wikimedia. Taille limitée à `max_octets`.
    Renvoie les octets. Lève ValueError (adresse refusée, trop gros) ou requests.RequestException."""
    global _derniere_requete
    if bloque_par_lot() and not getattr(_local, "lot", False):
        raise requests.RequestException("une importation en lot est en cours : patiente jusqu'à sa fin")
    SESSION.headers["User-Agent"] = _agent()
    for _ in range(max_redirections + 1):
        if not adresse_wikimedia(url):
            raise ValueError("adresse non autorisée (seuls les serveurs Wikimedia le sont)")
        with _VERROU_RESEAU:
            attente = config.PAUSE - (time.monotonic() - _derniere_requete)
            if attente > 0:
                time.sleep(attente)
            debut = time.monotonic()
            with SESSION.get(url, stream=True, timeout=20, allow_redirects=False) as reponse:
                _derniere_requete = time.monotonic()
                journal.reseau(url, {}, reponse.status_code, _derniere_requete - debut)
                if reponse.status_code in (301, 302, 303, 307, 308) and reponse.headers.get("Location"):
                    url = requests.compat.urljoin(url, reponse.headers["Location"])
                    continue
                reponse.raise_for_status()
                if int(reponse.headers.get("Content-Length") or 0) > max_octets:
                    raise ValueError("fichier trop lourd")
                morceaux, total = [], 0
                for morceau in reponse.iter_content(65536):
                    total += len(morceau)
                    if total > max_octets:
                        raise ValueError("fichier trop lourd")
                    morceaux.append(morceau)
                return b"".join(morceaux)
    raise ValueError("trop de redirections")


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


def prechauffer_top(delai=8.0):
    """Au lancement : charge (en arrière-plan, UNE requête, après `delai` secondes) le top des articles les plus vus du mois dernier, que le tirage d'un paquet demande toujours : le premier
    paquet n'a plus à l'attendre. Sans effet s'il est déjà en mémoire ; toute erreur est ignorée."""
    def travail():
        time.sleep(delai)
        try:
            if not top_en_cache():
                with en_arriere_plan(config.RESERVE_PAUSE, None):
                    charger_top_articles()
        except Exception:
            pass
    threading.Thread(target=travail, name="top-prechauffage", daemon=True).start()


def vues_manquantes(page):
    """Wikipédia n'a donné AUCUNE vue pour cette page dans la requête groupée (propriété absente, ou tous les jours « null »). Ce n'est pas « 0 vue » : pour une requête
    groupée, le service de vues répond souvent « pas de données » à des articles pourtant très lus. Sans cette distinction, un article à 700 vues par jour devenait un
    « 0 vue, rang C »."""
    vues = page.get("pageviews") if isinstance(page, dict) else None
    return not isinstance(vues, dict) or not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vues.values())


def vues_article(titre):
    """Les vues par jour d'UN article sur la période mesurée, par le service dédié de Wikimedia : {date: vues}. {} : Wikimedia dit n'avoir aucune vue (réponse 404, normale
    pour un article très peu lu). Lève requests.RequestException si le service ne répond pas (le titre est encodé en entier : apostrophes, barres, parenthèses...)."""
    fin = date.today() - timedelta(days=1)
    debut = fin - timedelta(days=max(1, int(config.JOURS_VUES)) - 1)
    url = URL_VUES_ARTICLE.format(projet=f"{config.LANGUE}.wikipedia", titre=quote(str(titre).replace(" ", "_"), safe=""),
                                  debut=debut.strftime("%Y%m%d"), fin=fin.strftime("%Y%m%d"))
    try:
        donnees = requete(url)
    except requests.HTTPError as erreur:
        if getattr(getattr(erreur, "response", None), "status_code", None) == 404:
            return {}
        raise
    jours = {}
    for element in (donnees.get("items") or []) if isinstance(donnees, dict) else []:
        if isinstance(element, dict) and isinstance(element.get("views"), int) and not isinstance(element.get("views"), bool) and element["views"] >= 0:
            jours[str(element.get("timestamp", ""))[:8]] = element["views"]
    return jours


def _vues_a_relire(page):
    """Cette page est un article dont la requête groupée n'a donné aucune vue : ses vues valent la peine d'être relues une par une."""
    return (isinstance(page, dict) and "missing" not in page and "invalid" not in page and bool(page.get("title")) and vues_manquantes(page)
            and page.get("ns", 0) == 0 and "disambiguation" not in (page.get("pageprops") or {}))


def completer_vues(pages, maximum=8):
    """Pour les pages SANS vues dans la requête groupée, relit leurs vues une par une (vues_article) et les met dans page["pageviews"] : le rang est alors calculé d'après de
    vraies vues. Au plus `maximum` relectures par appel (la politesse envers Wikimedia passe avant) ; à la première panne, on s'arrête. Renvoie le nombre de pages complétées."""
    faites = 0
    for page in pages:
        if not _vues_a_relire(page):                      # (une page d'homonymie ou hors article n'est pas une carte : pas de requête pour elle)
            continue
        if faites >= maximum:
            break
        try:
            jours = vues_article(page["title"])
        except Exception:                                  # le secours est facultatif : une panne, une réponse inattendue... ne doivent jamais gâcher un paquet ou une importation
            break
        faites += 1
        if jours:
            page["pageviews"] = jours
    return faites


def lot_aleatoire():
    """Tire TAILLE_LOT articles au hasard : [(titre, vues/jour)]. Un article pour lequel Wikipédia ne donne aucune vue est écarté (au lieu d'être compté « 0 vue, rang C » :
    il fausserait le tirage des rangs)."""
    pages = appeler_api({
        "action": "query", "format": "json",
        "generator": "random", "grnnamespace": 0, "grnlimit": config.TAILLE_LOT,
        "prop": "pageviews", "pvipdays": config.JOURS_VUES,
    })
    memoriser_vues(pages.values())                      # (les vues de ces articles sont connues : si l'un est tiré pour un paquet, aucune requête de plus)
    return [(p["title"], calculer_vues(p)[1]) for p in pages.values() if not vues_manquantes(p)]


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


def completer_stats(articles, rappel=None, echeance=None):
    """Récupère les modifications de la page et les liens entrants des articles qui n'en ont pas (une requête chacun),
    et les range dans les dictionnaires. À appeler dans un bloc en_arriere_plan : pas de nouvelle tentative après un 429
    ou un 503. S'ARRÊTE à la première erreur de réseau ou de limite (ce qui manque sera complété plus tard par le fil de
    fond) ; une page qui répond 400, 403 ou 404 est simplement laissée de côté. `rappel(restantes)` est appelé après
    chaque requête. `echeance` (temps monotone) : on ne commence pas une requête qui ne pourrait pas finir avant ; ce qui manque est complété plus tard par le fil de fond (c'est ce
    qui permet à l'ouverture d'un paquet de TENIR la durée annoncée). Renvoie le nombre de requêtes faites."""
    restantes = stats_manquantes_des(articles)
    faites = 0
    for art in articles:
        for cle in ("nb_revisions", "nb_liens_entrants"):
            if art.get(cle) is not None:
                continue
            if echeance is not None and time.monotonic() + 0.7 * _latence >= echeance:
                return faites                      # l'échéance promise approche : le paquet s'ouvre avec ce qu'on a
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
    completer_vues(par_titre.values())                     # les articles sans vues dans la requête groupée : relus un par un (un paquet n'en a que quelques-uns)

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


def _stats_en_erreur_definitive(erreur):
    """Cette erreur veut dire « pas de statistique pour cette page » (400, 403, 404) et non « Wikipédia ne répond pas » : on la laisse de côté, sans réessayer."""
    return isinstance(erreur, requests.HTTPError) and getattr(getattr(erreur, "response", None), "status_code", None) in (400, 403, 404)


def _ranger_stats(art, futur_modifications, futur_liens, echeance):
    """Range dans l'article les statistiques que les fils auxiliaires ont récupérées ; attend, au plus jusqu'à `echeance` (temps monotone), celles qui ne sont pas encore là.
    Ce qui manque est complété plus tard par le fil de fond. Renvoie le nombre de statistiques obtenues."""
    obtenues = 0
    for cle, futur in (("nb_revisions", futur_modifications), ("nb_liens_entrants", futur_liens)):
        if futur is None or art.get(cle) is not None:
            continue
        reste = None if echeance is None else max(0.0, echeance - time.monotonic())
        try:
            valeur = futur.result(timeout=reste)
        except BaseException:
            continue                                      # pas à temps, annulée, refusée ou en panne : pour plus tard
        if cle == "nb_revisions":
            art["nb_revisions"], art["revisions_plafonnees"] = valeur
        else:
            art["nb_liens_entrants"] = valeur
        obtenues += 1
    return obtenues


class SuiteStats:
    """Les statistiques (modifications, liens entrants) des cartes d'un paquet, demandées PENDANT l'ouverture (voir recuperer_paquet_rapide) mais qui peuvent continuer APRÈS : le paquet
    s'ouvre dès que ce qui est indispensable (détails, langues, vues) est là, et ces chiffres arrivent juste après, dans les cartes déjà affichées."""

    def __init__(self, parallele, futurs):
        self.parallele = parallele
        self.futurs = futurs                         # {titre: (Future des modifications, Future des liens entrants)}

    def attendre(self, articles, echeance=None):
        """Range dans les articles les statistiques arrivées ; attend, au plus jusqu'à `echeance` (temps monotone), celles qui ne sont pas là. Renvoie le nombre obtenu."""
        obtenues = 0
        for art in articles:
            futurs = self.futurs.get(art["titre"])
            if futurs:
                obtenues += _ranger_stats(art, futurs[0], futurs[1], echeance)
        return obtenues

    def fermer(self):
        self.parallele.fermer()


def lancer_stats(articles):
    """Demande, plusieurs requêtes à la fois (voir en_parallele), les statistiques qui manquent à ces articles (une carte venue de la réserve, un GOD PACK) : renvoie une SuiteStats."""
    parallele = Parallele(config.PAQUET_SIMULTANEES, config.PAQUET_ECART)
    futurs = {}
    for art in articles:
        fm = parallele.soumettre(nb_revisions, art["titre"], priorite=2) if art.get("nb_revisions") is None else None
        fl = parallele.soumettre(nb_liens_entrants, art["titre"], priorite=2) if art.get("nb_liens_entrants") is None else None
        if fm is not None or fl is not None:
            futurs[art["titre"]] = (fm, fl)
    return SuiteStats(parallele, futurs)


def recuperer_paquet_rapide(tirages, avec_langues=True, avec_statistiques=True):
    """Les cartes d'un paquet tiré en direct, le plus vite possible sans demander une requête de plus : plusieurs requêtes à la fois (voir en_parallele), dans l'ordre d'urgence :
    - tout de suite et en même temps : les DÉTAILS, les LANGUES, et les VUES des articles dont on ne les connaît pas déjà (celles des articles tirés au hasard sont déjà en mémoire) ;
    - en même temps mais après (priorité basse) : les STATISTIQUES de chaque article (modifications, liens), qui ne dépendent que de son titre.
    Renvoie (articles, suite) : les articles sont prêts (vues, rang, langues) ; `suite` (SuiteStats) porte les statistiques, qu'on peut attendre (suite.attendre) ou laisser arriver
    après l'ouverture ; il faut alors la fermer (suite.fermer)."""
    titres = [tirage[0] for tirage in tirages]
    avec_stat = bool(avec_statistiques and config.STATS_CARTES and config.STATS_AVEC_PAQUET)
    parallele = Parallele(config.PAQUET_SIMULTANEES, config.PAQUET_ECART)
    precedent = getattr(_local, "parallele", None)
    if parallele._fils:
        _local.parallele = {**parallele._etat, "travailleur": False}
    try:
        futurs_vues = {t: parallele.soumettre(vues_article, t, priorite=0) for t in titres if vues_connues(t) is None}
        futur_langues = parallele.soumettre(langues_wikipedia, titres, priorite=0) if (config.STATS_CARTES and avec_langues) else None
        stats = {}
        if avec_stat:                                    # (priorité basse : elles ne retardent pas ce qui est indispensable)
            for titre in titres:
                stats[titre] = (parallele.soumettre(nb_revisions, titre, priorite=2), parallele.soumettre(nb_liens_entrants, titre, priorite=2))
        par_titre = {}
        for debut in range(0, len(titres), LOT_DETAILS):
            if debut:
                time.sleep(max(0.0, float(config.PAUSE)))
            params = _params_details()
            params["titles"] = "|".join(titres[debut:debut + LOT_DETAILS])
            par_titre.update({page["title"]: page for page in appeler_api(params).values()})
        for titre, page in par_titre.items():            # les vues : relues une à une > déjà connues (tirage au hasard) > celles de la requête groupée
            jours = None
            if titre in futurs_vues:
                try:
                    jours = futurs_vues[titre].result()
                except BaseException:
                    jours = None
            if jours:
                page["pageviews"] = jours
            elif vues_connues(titre) is not None:
                page["pageviews"] = vues_connues(titre)
        encore = [page for page in par_titre.values() if _vues_a_relire(page) and page["title"] not in futurs_vues][:8]
        for page, futur in [(page, parallele.soumettre(vues_article, page["title"], priorite=0)) for page in encore]:
            try:
                jours = futur.result()
            except BaseException:
                continue
            if jours:
                page["pageviews"] = jours
        articles = []
        for titre, code_tire, tire_le in tirages:
            page = par_titre.get(titre)
            if page is not None:
                articles.append(_article(page, code_tire, tire_le))
        if futur_langues is not None:
            try:
                langues = futur_langues.result()
                for article in articles:
                    nombre = langues.get(str(article["titre"]).replace("_", " "))
                    if nombre is not None:
                        article["nb_langues"] = nombre
            except BaseException:
                pass                                     # les langues sont facultatives
    except BaseException:
        parallele.fermer()
        raise
    finally:
        _local.parallele = precedent
    return articles, SuiteStats(parallele, stats)


def recuperer_details_rapide(tirages, avec_langues=True, avec_statistiques=True, echeance=None):
    """Comme recuperer_paquet_rapide, mais attend les statistiques (jusqu'à `echeance`, temps monotone) et vérifie les GIF : des cartes COMPLÈTES, sans suite."""
    articles, suite = recuperer_paquet_rapide(tirages, avec_langues, avec_statistiques)
    try:
        marquer_gifs(articles)
        suite.attendre(articles, echeance)
    finally:
        suite.fermer()
    return articles


def completer_stats_rapide(articles, echeance=None):
    """Comme completer_stats (les modifications et liens entrants qui manquent), mais plusieurs requêtes en même temps (voir en_parallele) : pour les cartes qui n'ont pas
    déjà tout reçu (une carte venue de la réserve, un GOD PACK). Renvoie le nombre de statistiques obtenues."""
    obtenues = 0
    with en_parallele() as parallele:
        futurs = {}
        for art in articles:
            fm = parallele.soumettre(nb_revisions, art["titre"], priorite=2) if art.get("nb_revisions") is None else None
            fl = parallele.soumettre(nb_liens_entrants, art["titre"], priorite=2) if art.get("nb_liens_entrants") is None else None
            futurs[id(art)] = (fm, fl)
        for art in articles:
            obtenues += _ranger_stats(art, *futurs[id(art)], echeance)
    return obtenues


def simuler_pipeline(duree, simultanes, ecart, langues=True, relectures=0, stats=0):
    """Combien de temps dure recuperer_details_rapide, par un calcul (sans rien demander) : `duree` = durée d'une requête, `simultanes` requêtes à la fois, un départ toutes les
    `ecart` secondes ; les détails d'abord, puis les langues et les statistiques (tout de suite), les relectures de vues après les détails (prioritaires). Renvoie (total sans
    statistiques, total avec statistiques), en secondes."""
    def planifier(taches):
        lignes = [0.0] * max(1, int(simultanes))
        dernier = -ecart
        fin_details = 0.0
        fin_sans = 0.0
        ordre = []
        for nom, pret in taches:
            i = min(range(len(lignes)), key=lambda j: lignes[j])
            debut = max(lignes[i], pret, dernier + ecart)
            lignes[i] = debut + duree
            dernier = debut
            if nom == "details":
                fin_details = debut + duree
            ordre.append((nom, debut + duree))
        return max(fin for _, fin in ordre) if ordre else 0.0, fin_details
    # sans statistiques : détails (fil principal), langues, relectures (prêtes après les détails)
    taches = [("details", 0.0)] + ([("langues", 0.0)] if langues else [])
    total_sans, fin_details = planifier(taches + [("vues", duree)] * int(relectures))
    total_avec, _ = planifier(taches + [("vues", duree)] * int(relectures) + [("stats", 0.0)] * int(stats))
    return total_sans, max(total_avec, total_sans)


def details_par_titres(titres, maxlag=5, vues_de_secours=8):
    """Les détails (image, description, introduction, vues...) d'au plus 20 articles DONT ON CONNAÎT LE TITRE, en UNE requête. Les titres sont normalisés par Wikipédia
    (majuscule initiale, espaces) et les redirections suivies. Renvoie {titre demandé: page ou None} (None : l'article n'existe pas ou le titre est invalide).
    Paramètre `maxlag` : si les serveurs de Wikipédia sont en retard, l'API répond d'attendre (MaxLag) au lieu de les charger davantage. Lève LimiteDebit, MaxLag
    ou requests.RequestException."""
    titres = list(titres)[:LOT_DETAILS]
    params = _params_details()
    params.update({"titles": "|".join(titres), "redirects": 1, "maxlag": int(maxlag)})
    params["prop"] += "|pageprops"
    params["ppprop"] = "disambiguation"                     # pour écarter les pages d'homonymie
    donnees = requete(url_api(), params)
    erreur = donnees.get("error") if isinstance(donnees, dict) else None
    if erreur:
        if erreur.get("code") == "maxlag":
            raise MaxLag(max(5.0, float(erreur.get("lag") or 5)))
        raise requests.RequestException(f"Wikipédia a refusé la requête ({erreur.get('code')})")
    requete_ = donnees.get("query", {}) if isinstance(donnees, dict) else {}
    normalises = {n["from"]: n["to"] for n in requete_.get("normalized", []) if isinstance(n, dict) and "from" in n and "to" in n}
    redirections = {r["from"]: r["to"] for r in requete_.get("redirects", []) if isinstance(r, dict) and "from" in r and "to" in r}
    pages = {p["title"]: p for p in (requete_.get("pages") or {}).values() if isinstance(p, dict) and "title" in p}
    resultat = {}
    for titre in titres:
        final = normalises.get(titre, titre)
        for _ in range(6):                                   # (une redirection peut en cacher une autre)
            if final in redirections:
                final = redirections[final]
            else:
                break
        page = pages.get(final)
        resultat[titre] = None if (page is None or "missing" in page or "invalid" in page) else page
    if vues_de_secours:                                       # les pages sans vues dans la requête groupée : relues une par une (au plus `vues_de_secours` par appel)
        completer_vues({id(p): p for p in resultat.values() if p}.values(), maximum=int(vues_de_secours))
    return resultat


def article_depuis_page(page, tire_le):
    """La carte (dictionnaire) d'une page lue par details_par_titres : son rang vient de ses vues."""
    return _article(page, None, tire_le)


def rechercher(texte, limite, decalage=0, relire_vues=True):
    """Cherche des articles sur Wikipédia (recherche en texte intégral) et renvoie leurs détails,
    du plus pertinent au moins pertinent : [dict]. La requête donne aussi les vues de chaque article (donc leur rang). Les cartes ne sont pas enregistrées. `decalage` : nombre de résultats
    déjà vus (bouton « Voir plus de résultats ») ; chaque article reçoit `pertinence`, sa place dans la liste de Wikipédia.
    Pour que la recherche soit RAPIDE, la recherche en texte intégral et celle par préfixe du titre partent en même temps (voir en_parallele). `relire_vues=True` : on lit ensuite, en même
    temps aussi, les vues des résultats pour lesquels la requête groupée n'en a pas donné et on vérifie les GIF ; `relire_vues=False` : on répond TOUT DE SUITE, les résultats concernés sont
    marqués `a_completer` (voir completer_resultats, que la page appelle juste après)."""
    params = _params_details()
    params.update({"generator": "search", "gsrsearch": texte, "gsrnamespace": 0,
                   "gsrlimit": max(1, min(int(limite), 20)), "gsroffset": max(0, int(decalage))})
    premier_lot = int(decalage) == 0
    with en_parallele() as parallele:
        futur_prefixe = parallele.soumettre(_pages_prefixe, texte, priorite=0) if premier_lot else None      # (premier lot : les titres qui COMMENCENT par ce qui est tapé)
        ordonnees = sorted(appeler_api(params).values(), key=lambda page: page.get("index", 0))
        pages_prefixe = []
        if futur_prefixe is not None:
            try:
                connus = {page.get("pageid") for page in ordonnees}
                pages_prefixe = [page for page in futur_prefixe.result() if page.get("pageid") not in connus]
            except (requests.RequestException, KeyError, ValueError, TypeError):
                pages_prefixe = []                  # la recherche principale suffit : le complément est facultatif
        toutes = ordonnees + pages_prefixe
        for page in toutes:                         # les vues déjà connues (articles déjà tirés au hasard) : aucune requête
            if _vues_a_relire(page) and vues_connues(page.get("title")) is not None:
                page["pageviews"] = vues_connues(page["title"])
        provisoires = None
        if relire_vues:
            maximum = max(2, int(parallele.simultanes)) if parallele._fils else 2
            a_relire = [page for page in toutes if _vues_a_relire(page)][:maximum]
            futurs_vues = [(page, parallele.soumettre(vues_article, page["title"], priorite=0)) for page in a_relire]
            provisoires = [_article(page, None, None) for page in toutes]      # (pour la vérification des GIF, qui part en même temps que les lectures de vues)
            futur_gifs = parallele.soumettre(marquer_gifs, provisoires, priorite=0)
            for page, futur in futurs_vues:
                try:
                    jours = futur.result()
                except BaseException:
                    continue
                if jours:
                    page["pageviews"] = jours
            try:
                futur_gifs.result()
            except BaseException:
                pass
    articles = []
    for i, page in enumerate(toutes):
        article = _article(page, None, None)
        if provisoires is not None:
            article["gif_anime"] = provisoires[i].get("gif_anime", article.get("gif_anime"))
        article["pertinence"] = (max(0, int(decalage)) + i) if i < len(ordonnees) else len(ordonnees) + max(0, int(decalage))
        article["a_completer"] = _a_completer(article, page)
        articles.append(article)
    return articles


def _adresse_gif(art):
    adresse = art.get("miniature") if art.get("miniature") not in (None, "no-image") else art.get("image")
    return adresse if isinstance(adresse, str) and adresse.split("?", 1)[0].lower().endswith(".gif") else None


def _a_completer(article, page):
    """Ce résultat a encore quelque chose à compléter : ses vues (la requête groupée n'en a pas donné) ou la vérification de son GIF."""
    return bool(_vues_a_relire(page) or (_adresse_gif(article) and article.get("gif_anime") is None))


def completer_resultats(articles):
    """Complète, plusieurs requêtes à la fois (voir en_parallele), les résultats d'une recherche marqués `a_completer` : lit les vues manquantes (une requête chacun, au plus 12) et vérifie
    les GIF (une requête pour tous). Met à jour les dictionnaires (vues, rang, GIF) et renvoie ceux qui ont changé."""
    a_lire = [a for a in articles if a.get("vues_total", 0) == 0 and a.get("a_completer")][:12]
    changes = []
    with en_parallele() as parallele:
        futurs = [(a, parallele.soumettre(vues_article, a["titre"], priorite=0)) for a in a_lire]
        futur_gifs = parallele.soumettre(marquer_gifs, articles, priorite=0)
        for article, futur in futurs:
            try:
                jours = futur.result()
            except BaseException:
                continue
            if jours:
                total, moyenne = calculer_vues({"pageviews": jours})
                code, nom = classer(moyenne)
                article.update(vues_total=total, vues_moyenne=moyenne, rarete=code, rarete_nom=nom, rarete_tiree=code)
                changes.append(article)
        try:
            futur_gifs.result()
        except BaseException:
            pass
    for article in articles:
        if article.get("a_completer") and article not in changes and article.get("gif_anime") is not None:
            changes.append(article)
        article["a_completer"] = False
    return changes


def _pages_prefixe(texte, limite=6):
    """Les pages dont le titre COMMENCE par ce qu'on a tapé (recherche par préfixe de Wikipédia) : une requête de plus, au premier lot seulement. Elle retrouve l'article « Paris » quand on
    tape « par », que la recherche en texte intégral place parfois loin."""
    params = _params_details()
    params.update({"generator": "prefixsearch", "gpssearch": texte, "gpsnamespace": 0, "gpslimit": max(1, min(int(limite), 10))})
    return sorted(appeler_api(params).values(), key=lambda page: page.get("index", 0))


def _rechercher_prefixe(texte, limite=6):
    """(compatibilité) Les articles dont le titre commence par ce qu'on a tapé, avec leurs vues relues si besoin."""
    pages = _pages_prefixe(texte, limite)
    completer_vues(pages, maximum=3)
    return [_article(page, None, None) for page in pages]


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
