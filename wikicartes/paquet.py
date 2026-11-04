"""Ouverture d'un paquet de cartes : tirage, enregistrement dans la base, cartes à afficher.

Appelé par la page (bouton « paquet ») via le serveur local. Le nombre de cartes est
config.NOMBRE_CARTES_PAQUET (de 1 à 20, réglable dans la page Configuration).
"""

import random
import threading
import time

import requests

from datetime import datetime

from . import api, base, config, gifs, journal, parametres, rendu, reserve, stats, tirage
from .tirage import estimer_requetes, requetes_finales, tirer_godpack, tirer_titres

_VERROU = threading.Lock()     # un seul paquet à la fois (le tirage interroge Wikipédia)


class PaquetEnCours(Exception):
    """Un autre paquet est déjà en cours d'ouverture."""


# ---------------------------------------------------------------------------------------------------------------------- l'ouverture en cours (reprise après un changement de page)
# Quand on change de page pendant l'ouverture d'un paquet, le tirage continue sur le serveur. Ce suivi permet à la page suivante de REPRENDRE l'animation (le paquet qui
# bouge, le son, le décompte) puis de montrer les cartes à leur arrivée, au lieu d'un paquet immobile et d'un message d'erreur si on clique dessus.

VALIDITE_RESULTAT = 1800                      # s : un paquet ouvert et jamais montré à l'écran (page quittée) est présenté à la prochaine page, pendant 30 minutes
_OUVERTURE = {"actif": False, "debut": 0.0, "fin_prevue": 0.0, "resultat": None, "erreur": None, "instant": 0.0, "vu": True}
_VERROU_OUVERTURE = threading.Lock()


def _ouverture_debut():
    with _VERROU_OUVERTURE:
        maintenant = time.time()
        _OUVERTURE.update(actif=True, debut=maintenant, fin_prevue=maintenant, resultat=None, erreur=None, vu=True)


def _ouverture_duree(secondes):
    """Le serveur vient d'annoncer (décompte) qu'il reste `secondes` avant l'ouverture : la page qui reprend s'en sert."""
    with _VERROU_OUVERTURE:
        _OUVERTURE["fin_prevue"] = time.time() + max(0.0, float(secondes))


def _ouverture_fin(donnees=None, erreur=None):
    with _VERROU_OUVERTURE:
        _OUVERTURE.update(actif=False, resultat=donnees, erreur=erreur, instant=time.time(), vu=False)


def marquer_vu():
    """La page qui a demandé le paquet a bien reçu le résultat : personne d'autre n'a à le montrer."""
    with _VERROU_OUVERTURE:
        _OUVERTURE.update(vu=True, resultat=None)


def etat_ouverture(recuperer=False):
    """L'état de l'ouverture : {en_cours, restant (s avant l'ouverture), ecoule (s depuis le début), termine (un résultat attend d'être montré), erreur}.
    `recuperer` : si un résultat attend, il est renvoyé (clé « donnees ») et marqué comme montré (une seule page le reçoit)."""
    with _VERROU_OUVERTURE:
        maintenant = time.time()
        etat = {"en_cours": bool(_OUVERTURE["actif"]), "restant": max(0.0, _OUVERTURE["fin_prevue"] - maintenant) if _OUVERTURE["actif"] else 0.0,
                "ecoule": max(0.0, maintenant - _OUVERTURE["debut"]) if _OUVERTURE["actif"] else 0.0, "termine": False, "erreur": None}
        recent = (not _OUVERTURE["actif"] and not _OUVERTURE["vu"] and maintenant - _OUVERTURE["instant"] <= VALIDITE_RESULTAT)
        if recent and _OUVERTURE["resultat"] is not None:
            etat["termine"] = True
            if recuperer:
                etat["donnees"] = {"ok": True, **_OUVERTURE["resultat"]}
                _OUVERTURE.update(vu=True, resultat=None)
        elif recent and _OUVERTURE["erreur"]:
            etat["erreur"] = _OUVERTURE["erreur"]
            if recuperer:
                _OUVERTURE.update(vu=True, erreur=None)
    return etat


def _calibrage_lire(mode, defaut):
    """Le coefficient appris sur cet ordinateur (durée réelle / durée calculée d'un paquet) pour ce mode (« p » : requêtes simultanées, « s » : une à la fois) ; `defaut` tant qu'on n'a rien appris."""
    try:
        with base.connexion_rapide() as conn:
            k = parametres.lire_preference(conn, f"reseau.k_paquet_{mode}", None)
    except Exception:
        k = None
    return float(k) if isinstance(k, (int, float)) and not isinstance(k, bool) and 0.5 <= k <= 6.0 else float(defaut)


def _latence_lire():
    """La durée d'une requête mesurée lors d'une session PRÉCÉDENTE (ou None) : au lancement, le programme n'a encore rien mesuré, mais sait déjà si ce réseau est lent."""
    try:
        with base.connexion_rapide() as conn:
            v = parametres.lire_preference(conn, "reseau.latence", None)
    except Exception:
        return None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and 0.05 <= v <= 5.0 else None


def _calibrage_ecrire(mode, k):
    try:
        with base.connexion_rapide() as conn:
            parametres.ecrire(conn, f"reseau.k_paquet_{mode}", round(float(k), 3))
    except Exception:
        pass                                    # le calibrage est un plus : jamais une raison de faire échouer un paquet


class PaquetImpossible(Exception):
    """Le tirage a échoué (Wikipédia injoignable, aucun article trouvé...)."""


class Annonceur:
    """Prévient la page de l'avancement du tirage. Le DÉCOMPTE est une PROMESSE faite UNE SEULE FOIS, avant le début du travail réel (promettre) : toutes les requêtes à faire sont comptées
    d'avance, d'après les réglages et la durée mesurée d'une requête (api.estimer_duree, api.simuler_pipeline), corrigées par ce qu'on a APPRIS de la vitesse réelle de cet ordinateur
    sur les paquets précédents, avec une marge. La page décompte ensuite régulièrement jusqu'à cette échéance, SANS qu'elle soit jamais corrigée en cours de route :
    - le travail finit plus tôt : le paquet attend l'échéance (terminer), pour que le décompte arrive à zéro exactement à l'ouverture ;
    - le travail dure plus longtemps (rare) : la page écrit « Presque prêt » au lieu de repartir d'un nombre inventé ;
    - seule une demande EXPLICITE de Wikipédia de patienter (erreur 429) prolonge la promesse, avec un message.
    Chaque annonce est un dictionnaire : {"type": "plan" | "etape" | "ralentissement", ...} ; seules celles qui portent "promesse": True et "duree" (secondes avant l'ouverture) règlent le
    décompte. `emettre` reçoit ces dictionnaires (le serveur les envoie à la page en direct)."""

    MARGE = 1.12                    # la promesse est 12 % plus longue que l'estimation corrigée...
    MARGE_FIXE = 0.6                # ...plus 0,6 s : mieux vaut attendre un peu trop que remonter
    ATTENTE_MAX = 2.5               # au plus 2,5 s d'attente pour tenir la promesse (si le travail finit bien plus tôt que prévu, le paquet s'ouvre sans attendre le reste)
    K_DEPART = {"p": 1.3, "s": 1.6}  # avant tout apprentissage : l'estimation est multipliée par 1,3 (plusieurs requêtes à la fois) ou 1,6 (une à la fois : un vieil ordinateur est plus lent que le calcul)
    PART_SANS_VUES = 0.35           # part estimée des articles dont la requête groupée ne donne pas les vues (relus un par un)

    def __init__(self, emettre):
        verrou = threading.Lock()                       # (plusieurs fils peuvent annoncer : une annonce à la fois dans le flux)

        def emission_protegee(evenement):
            with verrou:
                emettre(evenement)
        self._emettre = emission_protegee
        self.restantes = 0
        self.stats = 0                      # (informatif) requêtes de statistiques à faire
        self.fin = None                     # l'échéance promise (temps monotone) ; None : pas de décompte (paquet venu de la réserve)
        self.echeance_stats = None          # on n'attend plus les statistiques au-delà (un peu avant la promesse) : le reste arrive en arrière-plan
        self._debut = self._brut = self._duree_travail = self._parametres = None
        self._k = 1.0
        self._mode = "p"

    def _estimer(self, latence):
        """(durée jusqu'à l'ouverture, durée des statistiques attendues avant l'ouverture) en secondes, calculées (sans rien demander) pour une durée de requête `latence`, d'après les
        paramètres de la promesse (voir promettre)."""
        lots, nombre, details, stats, relectures = self._parametres
        simultanes = max(1, int(config.PAQUET_SIMULTANEES))
        serie = api.estimer_duree(lots) if lots else 0.0                    # (le tirage aléatoire : une requête à la fois, avec la pause habituelle)
        if simultanes > 1:
            sans, avec = api.simuler_pipeline(latence, simultanes, float(config.PAQUET_ECART), bool(config.STATS_CARTES), relectures, stats)
            coeur, complet = serie + sans, serie + avec
        else:
            coeur = serie + api.estimer_duree(details)
            complet = coeur + stats * (float(config.STATS_PAUSE_PAQUET) + latence)
        attente_stats = max(0.0, float(config.STATS_ATTENTE_PAQUET))          # (0 par défaut : le paquet ne les attend pas)
        if simultanes > 1:
            budget_stats = min(max(0.0, complet - coeur), attente_stats) if stats else 0.0
        else:                                                              # (une requête à la fois, comme avant : les statistiques sont attendues avant l'ouverture)
            budget_stats = max(0.0, complet - coeur) if stats else 0.0
        return coeur, budget_stats

    def promettre(self, lots, nombre, details, stats, relectures=None):
        """Annonce la durée du tirage en direct jusqu'à l'ouverture du paquet : `lots` requêtes de tirage aléatoire, `nombre` cartes, `details` requêtes de détails (+ langues), `stats`
        requêtes de statistiques, `relectures` articles dont les vues sont à relire (ceux qui viennent du top).
        - Le paquet s'ouvre dès que l'ESSENTIEL est là (détails, langues, vues) : les statistiques (modifications, liens) arrivent ensuite, dans les cartes affichées. Elles ne comptent dans
          la promesse que si STATS_ATTENTE_PAQUET demande de les attendre (au plus ce nombre de secondes).
        - Tout cela se fait EN PARTIE EN MÊME TEMPS (voir api.en_parallele) : la durée est calculée en conséquence (api.simuler_pipeline)."""
        simultanes = max(1, int(config.PAQUET_SIMULTANEES))
        self._mode = "p" if simultanes > 1 else "s"
        self._k = _calibrage_lire(self._mode, self.K_DEPART[self._mode])
        latence = max(api._latence, 0.05)
        if api._nb_mesures < 3:                                             # (presque rien mesuré depuis le lancement : on se souvient de la vitesse de la dernière session)
            enregistree = _latence_lire()
            if enregistree is not None:
                latence = max(latence, enregistree)
        if relectures is None:
            relectures = int(-(-self.PART_SANS_VUES * nombre // 1))
        self._parametres = (lots, nombre, details, stats, relectures)
        coeur, budget_stats = self._estimer(latence)
        self._brut = coeur + budget_stats
        duree = self._brut * self._k * self.MARGE + self.MARGE_FIXE
        self._debut = time.monotonic()
        self.fin = self._debut + duree
        # Si on a demandé d'attendre les statistiques (STATS_ATTENTE_PAQUET > 0) : au plus ce temps après l'essentiel ; sinon elles arrivent après l'ouverture.
        attente = max(0.0, float(config.STATS_ATTENTE_PAQUET)) if simultanes > 1 else budget_stats
        self.echeance_stats = (self._debut + coeur * self._k * self.MARGE + self.MARGE_FIXE + attente) if (stats and attente > 0) else None
        self.restantes, self.stats = lots + details, stats
        self._emettre({"type": "plan", "promesse": True, "duree": round(duree, 2), "restantes": lots + details + stats, "pause": config.PAUSE})

    def plan(self, restantes, stats=0):
        """(compatibilité) Avancement seulement : ne change JAMAIS le décompte."""
        self.restantes, self.stats = restantes, stats
        self._emettre({"type": "etape", "restantes": restantes + stats})

    def etape(self, restantes, stats=None):
        """Avancement seulement : ne change JAMAIS le décompte (voir promettre)."""
        self.restantes = restantes
        if stats is not None:
            self.stats = stats
        self._emettre({"type": "etape", "restantes": self.restantes + self.stats})

    def ralentissement(self, delai):
        """Wikipédia a demandé de patienter `delai` secondes : la promesse s'allonge d'autant, avec un message (c'est la seule prolongation)."""
        evenement = {"type": "ralentissement", "delai": round(delai, 1)}
        if self.fin is not None:
            self.fin += float(delai)
            evenement.update(promesse=True, duree=round(max(0.0, self.fin - time.monotonic()), 2))
        self._emettre(evenement)

    def travail_termine(self):
        """Tout le travail est fait (cartes complètes) : on note combien de temps il a VRAIMENT pris, avant l'attente de l'échéance."""
        if self._debut is not None and self._duree_travail is None:
            self._duree_travail = time.monotonic() - self._debut

    def enregistrer_calibrage(self):
        """Apprend de ce paquet : le rapport entre la durée réelle du travail et son estimation (moyenné avec ce qui a été appris avant), pour que la prochaine promesse soit plus
        juste. Sans effet pour un paquet qui n'a pas eu de décompte."""
        if self.fin is None or self._duree_travail is None or not self._brut or self._brut < 0.5:
            return
        # Le coefficient mesure ce que le CALCUL ne voit pas (traitement, ordinateur lent), PAS la lenteur du réseau (déjà mesurée à part, via la durée d'une requête) : on recalcule
        # donc l'estimation avec la durée de requête RÉELLEMENT observée pendant ce paquet, sinon la lenteur du réseau serait corrigée deux fois.
        brut = self._brut
        observee = api.mesures()["moyenne"]
        if observee > 0.02 and self._parametres is not None:
            coeur, budget = self._estimer(observee)
            brut = max(0.3, coeur + budget)
        k = min(5.0, max(0.6, 0.5 * self._k + 0.5 * (self._duree_travail / brut)))
        _calibrage_ecrire(self._mode, k)
        try:
            with base.connexion_rapide() as conn:
                parametres.ecrire(conn, "reseau.latence", round(float(api._latence), 3))
        except Exception:
            pass

    def terminer(self):
        """Le travail est fini : si l'échéance promise n'est pas encore là, on l'attend, pour que le décompte arrive à zéro EXACTEMENT au moment où le paquet s'ouvre."""
        if self.fin is None:
            return
        limite = time.monotonic() + self.ATTENTE_MAX
        while True:
            reste = min(self.fin, limite) - time.monotonic()
            if reste <= 0:
                return
            time.sleep(min(reste, 0.25))


def _completer_stats_du_paquet(articles, annonceur=None):
    """Les statistiques (modifications, liens entrants) des cartes du paquet arrivent AVEC les cartes : elles sont récupérées
    tout de suite, hors du plafond horaire (c'est une action de l'utilisateur, bornée par la taille du paquet), avec une pause
    plus courte que d'habitude. Si Wikipédia limite le débit ou tombe en panne, le paquet s'ouvre quand même et le fil de fond
    complète le reste plus tard."""
    if not (config.STATS_CARTES and config.STATS_AVEC_PAQUET):
        return
    total = api.stats_manquantes_des(articles)
    if not total:
        return
    if annonceur is not None:
        annonceur.etape(0, stats=total)
    echeance = annonceur.echeance_stats if annonceur is not None else None     # (la promesse de durée : ce qui n'est pas arrivé à temps arrive ensuite, en arrière-plan)
    with reserve.priorite_utilisateur():
        if int(config.PAQUET_SIMULTANEES) > 1:
            api.completer_stats_rapide(articles, echeance=echeance)            # (plusieurs requêtes à la fois, une carte venue de la réserve ou un GOD PACK)
            return
        with api.en_arriere_plan(config.STATS_PAUSE_PAQUET, None, pause_reseau=config.STATS_PAUSE_PAQUET):
            api.completer_stats(articles, rappel=(lambda restantes: annonceur.etape(0, stats=restantes)) if annonceur else None, echeance=echeance)


def _stats_en_fond(articles, ids_par_titre, suite, debut):
    """Les statistiques (modifications, liens entrants) d'un paquet déjà ouvert : elles arrivent quelques secondes plus tard et sont écrites dans les cartes, que la page met à jour toute
    seule. `suite` : celle de l'ouverture (api.recuperer_paquet_rapide), ou None ; les cartes qui n'y figurent pas (venues de la réserve, GOD PACK) sont demandées à part. Dans un fil à
    part, plusieurs requêtes à la fois (réglage) ; ce qui manque encore à la fin est repris par le fil de fond habituel."""
    def travail():
        suites = []
        with reserve.priorite_utilisateur():                    # (le fil de fond habituel patiente pendant ce temps : pas de requêtes en double)
            try:
                if suite is not None:
                    suites.append(suite)
                deja = suite.futurs if suite is not None else {}
                manquantes = [a for a in articles if a["titre"] not in deja and (a.get("nb_revisions") is None or a.get("nb_liens_entrants") is None)]
                if manquantes:
                    suites.append(api.lancer_stats(manquantes))
                limite = time.monotonic() + 90.0
                complets = 0
                for art in articles:
                    identifiant = ids_par_titre.get(art["titre"])
                    futurs = next((s.futurs[art["titre"]] for s in suites if art["titre"] in s.futurs), None)
                    if identifiant is None or futurs is None:
                        continue
                    api._ranger_stats(art, futurs[0], futurs[1], limite)
                    champs = {cle: art[cle] for cle in ("nb_revisions", "revisions_plafonnees", "nb_liens_entrants") if art.get(cle) is not None}
                    if champs:
                        with base.connexion_rapide() as conn:
                            base.mettre_a_jour_stats_carte(conn, identifiant, maj_date=False, **champs)
                    if art.get("nb_revisions") is not None and art.get("nb_liens_entrants") is not None:
                        complets += 1
                journal.logiciel(f"Statistiques du paquet : {complets}/{len(articles)} cartes complètes, {time.monotonic() - debut:.1f} s après le clic")
                if complets < len(articles):
                    stats.reveiller()                    # ce qui manque (Wikipédia a demandé de patienter...) : le fil de fond habituel s'en charge, poliment
            except Exception as erreur:
                journal.erreur(f"Statistiques du paquet interrompues : {type(erreur).__name__}")
                stats.reveiller()
            finally:
                for s in suites:
                    s.fermer()
    threading.Thread(target=travail, name="stats-paquet", daemon=True).start()


class PaquetInvalide(ValueError):
    """Demande de retrait de cartes refusée (pas de paquet récent, cartes qui n'en font pas partie)."""


GODPACK = {"force": False}                   # (essais) vrai : le prochain paquet est un GOD PACK


def composer_godpack(articles, nombre):
    """Un GOD PACK ne contient que des cartes LÉGENDAIRES : parmi les articles les plus consultés, on garde d'abord ceux dont le rang réel est déjà
    légendaire, puis, s'il n'y en a pas assez ce jour-là, les plus vus des autres, qui sont PROMUS légendaires par le GOD PACK. Les cartes
    gardent leurs vraies vues ; seul leur rang est celui du GOD PACK. Renvoie `nombre` cartes au plus (moins s'il manque des articles)."""
    legendaire = config.CODES[0]
    vrais = [a for a in articles if a.get("rarete") == legendaire]
    autres = [a for a in articles if a.get("rarete") != legendaire]
    choisis = (vrais + autres)[:nombre]
    for art in choisis:
        art["rarete"] = legendaire
        art["rarete_nom"] = config.NOMS.get(legendaire, art.get("rarete_nom"))
        art["rarete_tiree"] = legendaire
    return choisis


def godpack_tire():
    """Ce paquet est-il un GOD PACK ? Une chance sur GODPACK_UN_SUR (0 : jamais) ; un paquet forcé (essais) l'est toujours."""
    n = int(config.GODPACK_UN_SUR or 0)
    if GODPACK["force"]:
        GODPACK["force"] = False
        return True
    return n > 0 and random.randrange(n) == 0


DERNIER = {"ids": [], "instant": 0.0}        # les cartes du dernier paquet ouvert (on peut en retirer pendant 1 heure)
_VERROU_DERNIER = threading.Lock()
DELAI_RETRAIT = 3600


def _donnees_collection(nouvelles, comptes, nb_favoris, total, doublons, compteurs, bandeaux):
    """Ce que la page affiche après l'ouverture (ou après le retrait de cartes) : les cartes du paquet, le résumé, les
    compteurs, les doublons, la pagination."""
    pages = max(1, -(-total // config.CARTES_PAR_PAGE))
    return {
        "cartes": rendu.fragments_cartes(nouvelles),
        "resume": rendu.html_resume(comptes, nb_favoris),
        "infos": rendu.texte_infos(total),
        "nombre": len(nouvelles),
        "total": total,
        "doublons": doublons,
        "compteurs": compteurs,
        "bandeaux": bandeaux,
        "pages": pages,
        "par_page": config.CARTES_PAR_PAGE,
        "pagination": rendu.html_pagination(1, pages),
    }


def retirer_du_paquet(identifiants):
    """Supprime TOUT DE SUITE (pour de bon, sans passer par la corbeille) des cartes du dernier paquet ouvert, que
    l'utilisateur ne veut pas garder. Seules les cartes de ce paquet, pendant 1 heure, peuvent être retirées. Renvoie les
    données mises à jour pour la page (cartes restantes du paquet, compteurs, résumé...)."""
    if (not isinstance(identifiants, list) or not identifiants or len(identifiants) > 20
            or any(isinstance(i, bool) or not isinstance(i, int) for i in identifiants)):
        raise PaquetInvalide("liste de cartes invalide")
    with _VERROU_DERNIER:
        actuelles = list(DERNIER["ids"])
        recent = time.time() - DERNIER["instant"] <= DELAI_RETRAIT
    if not recent or not actuelles:
        raise PaquetInvalide("aucun paquet récent dont on puisse retirer des cartes")
    if not set(identifiants) <= set(actuelles):
        raise PaquetInvalide("ces cartes ne font pas partie du dernier paquet")
    with base.connexion_rapide() as conn:
        base.supprimer_cartes_du_paquet(conn, set(identifiants))
        restantes = [i for i in actuelles if i not in set(identifiants)]
        nouvelles = base.cartes_par_identifiants(conn, restantes) if restantes else []
        comptes = base.compter_par_rang(conn)
        nb_favoris = base.compter_favoris(conn)
        total = base.compter(conn)
        doublons = base.compter_doublons(conn)
        compteurs = base.compteurs_categories(conn)
        bandeaux = rendu.bandeaux_meme_titre(conn, [c["titre"] for c in nouvelles], restantes) if nouvelles else {}
    with _VERROU_DERNIER:
        DERNIER["ids"] = restantes
    donnees = _donnees_collection(nouvelles, comptes, nb_favoris, total, doublons, compteurs, bandeaux)
    donnees["retirees"] = len(identifiants)
    return donnees


def ouvrir_paquet(annonceur=None):
    """Tire les cartes d'un paquet, les enregistre, les classe automatiquement dans les catégories
    dont une « meta » apparaît dans leur description, et renvoie ce qu'il faut afficher :
    {"cartes": HTML des nouvelles cartes, "resume": HTML des boutons de filtre,
     "infos": phrase d'en-tête, "nombre": cartes du paquet, "total": cartes de la collection,
     "pages", "par_page", "pagination": HTML de la pagination (page 1)}."""
    if not _VERROU.acquire(blocking=False):
        raise PaquetEnCours("un paquet est déjà en cours d'ouverture")
    api.ecouteur_ralentissement = annonceur.ralentissement if annonceur else None
    t_debut = time.monotonic()
    api.mesures_zero()                              # (pour dire dans le journal ce que l'ouverture a demandé à Wikipédia)
    phases = {}                                     # durées des étapes, pour le journal
    suite_stats = None                              # les statistiques qui arriveront après l'ouverture (voir _stats_en_fond)
    rapide = int(config.PAQUET_SIMULTANEES) > 1
    _ouverture_debut()
    if annonceur is not None:                       # le temps restant annoncé à la page est aussi gardé : une page qui reprend l'animation s'en sert
        emission_originale = annonceur._emettre

        def emission_suivie(evenement):
            if isinstance(evenement, dict) and "duree" in evenement:
                _ouverture_duree(evenement["duree"])
            emission_originale(evenement)
        annonceur._emettre = emission_suivie
    try:
        nombre = config.NOMBRE_CARTES_PAQUET
        godpack = godpack_tire()                  # une chance sur 10 000 (réglable) : un paquet de cartes TOUTES légendaires
        candidats_godpack = []
        if godpack:
            candidats_godpack = tirer_godpack(nombre, annonceur)
            if not candidats_godpack:             # le top des articles les plus vus est indisponible : un paquet ordinaire plutôt qu'une erreur
                godpack = False
        # 1) La réserve d'abord : cartes préparées d'avance (instantané, aucune requête). Un GOD PACK n'en vient pas : il est tiré à part.
        preleves = [] if godpack else reserve.prelever(nombre)
        inseres = False                       # vrai dès que les cartes sont dans la collection
        try:
            maintenant = datetime.now().astimezone()
            for art in preleves:
                art["tire_le"] = maintenant
            manquantes = nombre - len(preleves)
            # 2) Les cartes qui manquent sont tirées en direct (comme avant)
            articles_direct, avertissement = [], ""
            if manquantes > 0:
                with reserve.priorite_utilisateur():
                    try:
                        preparation = None
                        if annonceur is not None:             # le décompte démarre : une PROMESSE de durée complète, faite une seule fois (voir Annonceur)
                            stats_prevues = 2 * manquantes if config.STATS_CARTES and config.STATS_AVEC_PAQUET else 0
                            if godpack:
                                annonceur.promettre(0, manquantes, -(-len(candidats_godpack) // api.LOT_DETAILS) + (1 if config.STATS_CARTES else 0), stats_prevues)
                            else:
                                preparation = tirage.preparer(manquantes)          # (charge le top, tire les rangs d'avance, prévoit les lots)
                                phases["préparation"] = time.monotonic() - t_debut
                                relectures = sum(1 for code in preparation["codes"] if config.SEUILS[code] > config.SEUIL_TOP_UNIQUEMENT)       # (les articles du top : leurs vues sont à lire)
                                annonceur.promettre(preparation["lots"], manquantes, tirage.requetes_finales(), stats_prevues, relectures)
                        tirages = candidats_godpack if godpack else tirer_titres(manquantes, annonceur, codes_tires=(preparation or {}).get("codes"))
                        phases["tirage"] = time.monotonic() - t_debut
                        if tirages and annonceur is not None:
                            annonceur.etape(requetes_finales())   # il ne reste que les détails (+ langues)
                        if tirages and rapide:
                            # Plusieurs requêtes à la fois : les détails, les langues et les vues (l'essentiel) sont demandés tout de suite ; les statistiques de chaque carte partent en même temps, avec
                            # une priorité plus basse, et arriveront APRÈS l'ouverture (voir _stats_en_fond). Un GOD PACK tire d'abord plus de candidats qu'il n'en garde : ses statistiques
                            # sont demandées ensuite, pour les seules cartes gardées.
                            articles_direct, suite_stats = api.recuperer_paquet_rapide(tirages, avec_statistiques=not godpack)
                            if suite_stats.futurs and float(config.STATS_ATTENTE_PAQUET) > 0:        # (réglage : attendre les statistiques, au plus ce temps, avant d'ouvrir)
                                suite_stats.attendre(articles_direct, annonceur.echeance_stats if (annonceur is not None and annonceur.echeance_stats) else time.monotonic() + float(config.STATS_ATTENTE_PAQUET))
                        else:
                            articles_direct = api.recuperer_details(tirages) if tirages else []
                        phases["détails"] = time.monotonic() - t_debut
                        if godpack:
                            articles_direct = composer_godpack(articles_direct, nombre)
                    except requests.RequestException as erreur:
                        if not preleves:
                            raise PaquetImpossible(f"Wikipédia est injoignable ({erreur}).") from erreur
                        avertissement = (f"Wikipédia ne répond pas : paquet de {len(preleves)} carte"
                                         f"{'s' if len(preleves) > 1 else ''} au lieu de {nombre}.")
                if not articles_direct and not preleves:
                    raise PaquetImpossible("Aucun article trouvé : Wikipédia est peut-être injoignable "
                                           "ou ralentit. Réessaie dans un instant.")
                if not articles_direct and preleves and not avertissement:
                    avertissement = (f"Paquet de {len(preleves)} carte{'s' if len(preleves) > 1 else ''} "
                                     f"au lieu de {nombre} : Wikipédia n'a pas fourni le reste.")
            elif annonceur is not None:
                annonceur.plan(0)                             # tout vient de la réserve : pas d'attente
            articles = preleves + articles_direct
            if not rapide:
                api.marquer_gifs(articles)                    # un GIF n'est « animé » que s'il l'est vraiment (une requête, seulement s'il y a des GIF)
                _completer_stats_du_paquet(articles, annonceur)       # (les statistiques d'abord, une requête à la fois, puis le paquet s'ouvre)
            # Les cartes du paquet sont rangées des plus COMMUNES aux plus RARES (la plus rare en dernier) : elles ont toutes la
            # même date de tirage, et la collection range à date égale dans l'ordre d'enregistrement.
            ordre_rangs = {code: i for i, code in enumerate(reversed(config.CODES))}
            articles.sort(key=lambda a: ordre_rangs.get(a.get("rarete"), len(ordre_rangs)))

            with base.connexion_rapide() as conn:
                identifiants = list(dict.fromkeys(base.ajouter_cartes(conn, articles)))
                inseres = True
                if not rapide:
                    stats.reveiller()             # modifications et liens : récupérés en arrière-plan
                else:
                    gifs.reveiller()              # (un GIF animé : vérifié en arrière-plan)
                if config.CATEGORIES_AUTO:
                    base.classer_automatiquement(conn, identifiants)
                nouvelles = base.cartes_par_identifiants(conn, identifiants)
                comptes = base.compter_par_rang(conn)
                nb_favoris = base.compter_favoris(conn)
                total = base.compter(conn)
                doublons = base.compter_doublons(conn)
                compteurs = base.compteurs_categories(conn)
                bandeaux = rendu.bandeaux_meme_titre(conn, [c["titre"] for c in nouvelles],
                                                     identifiants)

        except BaseException:
            if not inseres:                   # un paquet qui échoue ne fait perdre aucune carte préparée
                reserve.rendre(preleves)
            if suite_stats is not None:
                suite_stats.fermer()
            raise
        reserve.consommer_jeton()                 # un paquet de moins dans le stock (il se reconstitue avec le temps)
        with _VERROU_DERNIER:
            DERNIER["ids"], DERNIER["instant"] = list(identifiants), time.time()     # le paquet qu'on peut encore retoucher
        donnees = _donnees_collection(nouvelles, comptes, nb_favoris, total, doublons, compteurs, bandeaux)
        reel = godpack and len(nouvelles) == nombre and all(c.get("rarete") == config.CODES[0] for c in nouvelles)
        donnees.update({"depuis_reserve": len(preleves), "avertissement": avertissement, "godpack": bool(reel)})
        journal.logiciel(f"Paquet ouvert{' (GOD PACK)' if reel else ''} : {len(nouvelles)} carte(s), dont {len(preleves)} venue(s) de la réserve · collection : {total}\n"
                         + " · ".join(f"{c['titre'][:40]} [{c['rarete']}]" for c in nouvelles)
                         + (f"\nAvertissement : {avertissement}" if avertissement else ""))
        if annonceur is not None:
            annonceur.travail_termine()               # (tout le travail est fait : sa durée réelle sert à mieux promettre la prochaine fois)
            annonceur.enregistrer_calibrage()         # ce qu'on a appris de la vitesse de cet ordinateur : la prochaine promesse sera plus juste
            annonceur.terminer()                      # l'échéance promise au décompte : le paquet s'ouvre quand il arrive à zéro, ni avant ni après
        duree = time.monotonic() - t_debut
        mesure = api.mesures()
        phases["ouverture"] = duree
        direct = bool(articles_direct)
        journal.logiciel(f"Paquet ouvert en {duree:.1f} s{'' if direct else ' (tout venait de la réserve)'} : "
                         + " · ".join(f"{nom} {valeur:.1f} s" for nom, valeur in phases.items() if nom != "ouverture")
                         + (f" · {mesure['requetes']} requête(s) à Wikipédia, {mesure['simultanees_max']} en même temps au plus, {mesure['moyenne']:.1f} s en moyenne, la plus lente {mesure['plus_lente']:.1f} s"
                            if mesure["requetes"] else ""))
        if config.PAQUET_AFFICHER_DUREE:
            donnees["duree_ouverture"] = round(duree, 1)
            donnees["requetes_ouverture"] = mesure["requetes"]
        if rapide:                                    # ce qui n'était pas indispensable arrive maintenant, dans les cartes déjà affichées
            _stats_en_fond(articles, {c["titre"]: c["id"] for c in nouvelles}, suite_stats, t_debut)
            if direct:
                tirage.remplir_pool_en_fond(delai=1.5)       # des candidats d'avance pour les paquets suivants (une requête, poliment)
        _ouverture_fin(donnees=donnees)
        return donnees
    except BaseException as erreur:
        _ouverture_fin(erreur=str(erreur) or type(erreur).__name__)
        raise
    finally:
        api.ecouteur_ralentissement = None
        _VERROU.release()
