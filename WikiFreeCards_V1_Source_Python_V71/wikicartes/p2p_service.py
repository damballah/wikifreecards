"""Le service pair à pair : démarre le nœud (si tu l'as activé), le publie, et le tient à jour.

Rien ne démarre tant que « Partage : activer mon nœud » n'est pas coché. Quand il est actif :
1. le serveur pair à pair (lecture seule) écoute : en local sur 127.0.0.1 (modes Tor et local), ou sur toutes
   les interfaces (mode direct : c'est le but, il faut qu'on puisse te joindre) ;
2. en mode Tor, le service oignon de ton identité est publié par le port de contrôle de Tor ;
3. ta fiche signée est republiée toutes les 10 minutes (elle sert de battement de cœur) et complétée par celles
   que tes pairs connaissent (une visite toutes les 5 minutes, 5 pairs au plus à la fois).
"""

import threading
import time

from . import (base, config, p2p_annuaire as annuaire, p2p_identite as ident, p2p_serveur,
               p2p_transport as transport)

INTERVALLE_FICHE = 600
INTERVALLE_GOSSIP = 300
DELAI_PRET = 90                 # secondes après la publication du service oignon avant qu'il soit visible des autres
INTERVALLE_SURVEILLANCE = 20    # secondes entre deux vérifications de Tor (et nouvelle tentative si Tor était absent)
_COLLECTION_MAX = ident.COLLECTION_MAX


class Service:
    """Un nœud : sa fiche, son serveur, son éventuel service oignon."""

    def __init__(self):
        self._verrou = threading.RLock()
        self._arret = threading.Event()
        self._reveil = threading.Event()
        self._thread = None
        self._serveur = None
        self._tor = None
        self._etat = {"etat": "arrete", "message": "Le partage n'est pas activé.", "onion": None,
                      "adresse": None, "port": None, "bootstrap": None, "publie_le": None}
        self._dernier_essai_tor = 0.0
        self._cache = (0.0, None)
        self._dernier_t = 0

    # --------------------------------------------------------------------------- identité et fiche
    def identite(self):
        return ident.charger_ou_creer()

    def ma_fiche(self):
        """Ma fiche signée, d'après l'état actuel (pseudo, pastilles, nombre de cartes). Gardée 30 secondes."""
        with self._verrou:
            maintenant = time.time()
            if self._cache[1] is not None and maintenant - self._cache[0] < 30:
                return self._cache[1]
            fiche = self._fabriquer(maintenant)
            self._cache = (maintenant, fiche)
            return fiche

    def _adresse_publiee(self):
        if config.P2P_TRANSPORT == "tor":
            return None
        if config.P2P_ADRESSE_DIRECTE:
            return config.P2P_ADRESSE_DIRECTE
        if config.P2P_TRANSPORT == "local":
            return f"127.0.0.1:{self._etat['port'] or config.P2P_PORT}"
        return None

    def _fabriquer(self, maintenant):
        from . import web
        identite = self.identite()
        with base.connexion_lecture() as conn:
            pseudo, depuis = annuaire.mon_pseudo(conn)
            cartes = base.compter_partageables(conn)
        nom = web.tronquer_affichage(" ".join(web.normaliser_caracteres(config.TITRE_SITE).split()),
                                     _COLLECTION_MAX).strip() or "Ma collection"      # sans couper un emoji composé
        adresse = self._adresse_publiee()
        mode = config.P2P_TRANSPORT
        if mode != "tor" and adresse is None:
            raise transport.TransportErreur("adresse publique manquante (réglage « Partage : adresse publique »)")
        # La date de la fiche ne recule ni ne stagne jamais : deux changements dans la même seconde (pseudo supprimé
        # puis recréé...) donnent deux fiches de dates différentes, et la plus récente l'emporte partout.
        self._dernier_t = max(int(maintenant), self._dernier_t + 1)
        return ident.creer_fiche(identite, pseudo, depuis, nom, cartes, config.P2P_PROFIL_PUBLIC,
                                 config.P2P_COLLECTION_PUBLIQUE, mode, adresse, t=self._dernier_t)

    def publier_localement(self):
        """Range ma fiche dans mon annuaire (pour apparaître moi-même dans le Hall) et la renvoie."""
        with self._verrou:
            self._cache = (0.0, None)
        fiche = self.ma_fiche()
        with base.connexion_rapide() as conn:
            annuaire.fusionner(conn, ident.verifier_fiche(fiche), source="moi", forcer=True)
        return fiche

    # -------------------------------------------------------------------------------- cycle de vie
    def etat(self):
        """L'état du nœud. `pret` : le nœud est pleinement lancé et joignable (en mode Tor : Tor est connecté au réseau
        ET le service oignon est publié depuis assez longtemps pour être visible) ; sinon `attente` explique pourquoi
        il faut patienter (c'est ce qu'affiche le Hall)."""
        with self._verrou:
            e = dict(self._etat, actif=bool(config.P2P_ACTIF), mode=config.P2P_TRANSPORT)
        e["pret"], e["attente"] = False, None
        if e["etat"] == "en_ligne":
            if e["mode"] != "tor":
                e["pret"] = True
            else:
                progression, publie = e.get("bootstrap"), e.get("publie_le")
                reste = int(DELAI_PRET - (time.time() - publie)) if publie else DELAI_PRET
                if progression is not None and progression < 100:
                    e["attente"] = f"Tor se connecte au réseau ({progression} %)…"
                elif reste > 0:
                    e["attente"] = f"Ton service Tor vient d'être publié : encore environ {reste} s avant qu'il soit visible des autres."
                else:
                    e["pret"] = True
            if e["pret"]:
                e["message"] = "Nœud en ligne et joignable" + (" via Tor." if e["mode"] == "tor" else ".")
        elif e["etat"] in ("serveur", "demarrage"):
            e["attente"] = "Démarrage du nœud…"
        return e

    def _noter(self, etat, message, **autres):
        with self._verrou:
            self._etat.update({"etat": etat, "message": message, **autres})

    def demarrer(self):
        """Démarre le nœud en arrière-plan si le partage est activé (sans effet sinon, ou s'il tourne déjà)."""
        with self._verrou:
            if not config.P2P_ACTIF or (self._thread and self._thread.is_alive()):
                return False
            if not ident.DISPONIBLE:
                self._noter("erreur", "Le partage demande : pip install cryptography")
                return False
            self._arret.clear()
            self._noter("demarrage", "Démarrage du nœud…")
            self._thread = threading.Thread(target=self._travail, name="p2p", daemon=True)
            self._thread.start()
            return True

    def arreter(self):
        with self._verrou:
            thread, serveur, tor = self._thread, self._serveur, self._tor
            self._arret.set()
            self._reveil.set()
            self._serveur, self._tor, self._thread = None, None, None
        if serveur is not None:
            serveur.shutdown()
            serveur.server_close()
        if tor is not None:
            tor.fermer()
        if thread is not None:
            thread.join(timeout=5)
        self._noter("arrete", "Le partage n'est pas activé.", onion=None, adresse=None, port=None)

    def appliquer_reglages(self):
        """À appeler quand un réglage du partage change : arrête ou redémarre le nœud selon P2P_ACTIF."""
        self._cache = (0.0, None)
        if config.P2P_ACTIF:
            if self._thread and self._thread.is_alive():
                self.arreter()
            return self.demarrer()
        self.arreter()
        return False

    def reveiller(self):
        """Republie ma fiche et interroge des pairs tout de suite."""
        self._cache = (0.0, None)
        self._reveil.set()

    def _travail(self):
        try:
            identite = ident.charger_ou_creer()
            hote = "0.0.0.0" if config.P2P_TRANSPORT == "direct" else "127.0.0.1"
            serveur = p2p_serveur.creer_serveur(self, hote, int(config.P2P_PORT))
            port = serveur.server_address[1]
            with self._verrou:
                self._serveur = serveur
            threading.Thread(target=serveur.serve_forever, name="p2p-serveur", daemon=True).start()
            self._noter("serveur", f"Nœud à l'écoute (port {port}).", port=port)
            if config.P2P_TRANSPORT == "tor":
                self._publier_oignon(identite, port)
            else:
                self._noter("en_ligne", "Nœud en ligne.", adresse=self._adresse_publiee())
        except Exception as erreur:                                 # port pris, clé illisible...
            self._noter("erreur", f"Le nœud n'a pas pu démarrer : {erreur}")
            return
        derniere_fiche, dernier_gossip = 0.0, 0.0
        while not self._arret.is_set():
            maintenant = time.monotonic()
            try:
                if maintenant - derniere_fiche >= INTERVALLE_FICHE or self._reveil.is_set():
                    self.publier_localement()
                    derniere_fiche = maintenant
                if maintenant - dernier_gossip >= INTERVALLE_GOSSIP or self._reveil.is_set():
                    self.decouvrir()
                    dernier_gossip = maintenant
            except Exception as erreur:
                self._noter(self._etat["etat"], f"{self._etat['message']} (dernier incident : {erreur})")
            try:
                self._surveiller_tor()
            except Exception:
                pass
            self._reveil.clear()
            self._reveil.wait(timeout=15)

    def _maj_progression(self):
        with self._verrou:
            tor = self._tor
        if tor is None:
            return
        try:
            progression = tor.progression()
        except transport.TransportErreur:
            return
        with self._verrou:
            self._etat["bootstrap"] = progression

    def _surveiller_tor(self):
        """Tout au long de la vie du nœud en mode Tor : suit la connexion de Tor au réseau, détecte une connexion de
        contrôle perdue (Tor relancé, fermé...) et republie le service oignon dès que Tor est de nouveau là, sans que tu
        aies à décocher puis recocher « Activer mon nœud »."""
        if config.P2P_TRANSPORT != "tor" or self._etat["etat"] not in ("en_ligne", "erreur_tor") or self._arret.is_set():
            return
        with self._verrou:
            tor = self._tor
        if tor is not None:
            try:
                progression = tor.progression()
                with self._verrou:
                    self._etat["bootstrap"] = progression
                return
            except transport.TransportErreur:
                tor.fermer()
                with self._verrou:
                    self._tor = None
                self._noter("erreur_tor", "La connexion à Tor a été perdue : je réessaie toutes les 20 secondes. Vérifie que "
                                          "Tor est toujours lancé.", onion=None, publie_le=None, bootstrap=None)
        if time.monotonic() - self._dernier_essai_tor >= INTERVALLE_SURVEILLANCE:
            self._dernier_essai_tor = time.monotonic()
            self._publier_oignon(ident.charger_ou_creer(), self._etat["port"] or int(config.P2P_PORT))

    def _publier_oignon(self, identite, port):
        try:
            tor, derniere = None, None
            essais = transport.candidats_tor("controle", config.P2P_TOR_CONTROLE)
            for adresse in essais:                       # le réglage, puis les ports du navigateur Tor (9151)
                try:
                    tor = transport.TorControle(*transport.analyser_hote_port(adresse))
                    break
                except transport.TorErreur as erreur:
                    derniere = erreur
            if tor is None:
                raise transport.TorErreur(f"port de contrôle de Tor injoignable ({', '.join(essais)}) : "
                                          f"{str(derniere).split(': ', 1)[-1]}")
            tor.authentifier()
            onion = tor.publier(identite, port)
            with self._verrou:
                self._tor = tor
            self._noter("en_ligne", "Nœud démarré : Tor publie ton service (1 à 2 minutes avant d'être joignable).",
                        onion=onion, publie_le=time.time(), bootstrap=None)
            self._maj_progression()
        except transport.TransportErreur as erreur:
            self._noter("erreur_tor", f"Tor : {erreur}. Le nœud écoute mais personne ne peut te joindre : lance "
                                      "Tor puis réactive le partage. Navigateur Tor : laisse-le OUVERT (il utilise les ports "
                                      "9150 et 9151, essayés automatiquement). Sinon, lance tor.exe avec un fichier torrc "
                                      "contenant « ControlPort 9051 » et « CookieAuthentication 1 » (voir le README).")

    # ----------------------------------------------------------------------------- découverte
    def decouvrir(self, n=5):
        """Demande à quelques pairs en ligne les fiches qu'ils connaissent ; range celles qui sont valides."""
        nouvelles = 0
        with base.connexion_rapide() as conn:
            ids = annuaire.pairs_a_contacter(conn, n, mon_id=self.identite().id)
            annuaire.nettoyer(conn)
        for pair in ids:
            with base.connexion_rapide() as conn:
                fiche = annuaire.fiche_de(conn, pair)
            if fiche is None:
                continue
            try:
                statut, donnees = transport.appeler_json(fiche, "/p2p/pairs?n=100", timeout=15)
                recues = donnees.get("fiches") if statut == 200 else None
            except transport.TransportErreur:
                with base.connexion_rapide() as conn:
                    annuaire.marquer_echec(conn, pair)
                continue
            with base.connexion_rapide() as conn:
                annuaire.marquer_vu(conn, pair)
                for brute in (recues if isinstance(recues, list) else [])[:200]:
                    try:
                        nouvelle = ident.verifier_fiche(brute)
                    except ident.FicheInvalide:
                        continue
                    if nouvelle["id"] != self.identite().id and annuaire.fusionner(conn, nouvelle, source=pair):
                        nouvelles += 1
        return nouvelles

    def ajouter_contact(self, invitation):
        """Ajoute un pair à partir d'une invitation (« wcp1:<identifiant>[@hôte:port] ») : on le contacte, on vérifie
        sa fiche signée (elle doit être celle de l'identifiant donné) et on la range. Renvoie la fiche."""
        identifiant, adresse = annuaire.lire_invitation(invitation)
        if identifiant == self.identite().id:
            raise ValueError("c'est ta propre invitation")
        mode = "local" if config.P2P_TRANSPORT == "local" else "direct"
        provisoire = {"id": identifiant, "transport": "tor" if adresse is None else mode, "adresse": adresse}
        statut, donnees = transport.appeler_json(provisoire, "/p2p/salut", timeout=20)
        if statut != 200:
            raise transport.TransportErreur("le pair n'a pas répondu normalement")
        fiche = ident.verifier_fiche(donnees.get("fiche"), id_attendu=identifiant)
        with base.connexion_rapide() as conn:
            annuaire.fusionner(conn, fiche, source="contact")
            annuaire.marquer_vu(conn, identifiant)
        return fiche


SERVICE = Service()
