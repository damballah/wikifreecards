"""Le serveur pair à pair : ce que les AUTRES collectionneurs peuvent demander à ton nœud. LECTURE SEULE.

Ce serveur est totalement SÉPARÉ de la page locale (celle que tu utilises) : autre port, autre code, aucune
route en commun. Il ne connaît que sept adresses (liste blanche) ; tout le reste est refusé. Il ne peut rien
supprimer, rien modifier, ne touche à aucun réglage : les données viennent d'une connexion à la base en LECTURE
SEULE (partage.py), et la seule chose qu'il enregistre est une fiche d'annuaire SIGNÉE et vérifiée (annonce).

    GET  /p2p/salut        ta fiche signée
    GET  /p2p/pairs        des fiches d'annuaire (pour que les nœuds se découvrent entre eux)
    GET  /p2p/profil       le profil          (refusé si la pastille P est rouge)
    GET  /p2p/collection   une page de cartes (refusé si la pastille C est rouge)
    GET  /p2p/cartes       des cartes à rapatrier (idem)
    GET  /p2p/image/<nom>  l'image d'une carte personnalisée partagée (idem)
    POST /p2p/annonce      une fiche signée d'un autre pair (annuaire)

Chaque réponse est SIGNÉE par ta clé d'identité (liée à la requête par un nonce) : le visiteur sait que c'est bien
toi qui réponds et que rien n'a été changé en route. Protections : requêtes limitées en nombre et en taille,
8 connexions simultanées au plus, délai de 10 secondes, aucune redirection.
"""

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from . import base, config, images, p2p_annuaire, p2p_identite as ident, partage

SIMULTANES_MAX = 8
CORPS_MAX = 8 * 1024
CHEMINS_MAX = 600
_NONCE = re.compile(r"[0-9a-f]{32}")
_NOM_IMAGE = re.compile(r"/p2p/image/([0-9a-f]{32}\.(?:jpg|png|gif|webp))")
_CALQUE = re.compile(r"/p2p/fullart/(zuul|gozer)/([^/]{1,300})\.png")


class Limiteur:
    """Seau à jetons : `rafale` requêtes d'un coup, puis `debit` par seconde, pour tout le serveur."""

    def __init__(self, rafale=60, debit=3.0, horloge=time.monotonic):
        self.rafale, self.debit, self.horloge = rafale, debit, horloge
        self.jetons, self.dernier = float(rafale), horloge()
        self._verrou = threading.Lock()

    def autoriser(self):
        with self._verrou:
            maintenant = self.horloge()
            self.jetons = min(self.rafale, self.jetons + (maintenant - self.dernier) * self.debit)
            self.dernier = maintenant
            if self.jetons >= 1:
                self.jetons -= 1
                return True
            return False


def creer_serveur(service, hote="127.0.0.1", port=0, rafale=60, debit=3.0):
    """Le serveur pair à pair de ce nœud (non lancé). `service` fournit ma_fiche() et l'identité. `rafale` et
    `debit` : limite de requêtes pour tout le serveur (réglés pour les tests)."""
    limiteur = Limiteur(rafale, debit)
    annonces = Limiteur(rafale=20, debit=0.5)
    semaphore = threading.BoundedSemaphore(SIMULTANES_MAX)

    class Gestionnaire(BaseHTTPRequestHandler):
        timeout = 10
        server_version = "WikiCartes-P2P"
        sys_version = ""
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):                      # pas de journal (aucune trace des visiteurs)
            pass

        # -------------------------------------------------------------- réponses signées
        def _repondre(self, statut, corps, type_contenu="application/json; charset=utf-8", nonce=None):
            if not isinstance(corps, (bytes, bytearray)):
                corps = json.dumps(corps, ensure_ascii=False).encode("utf-8")
            self.send_response(statut)
            self.send_header("Content-Type", type_contenu)
            self.send_header("Content-Length", str(len(corps)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if nonce:
                self.send_header("X-WC-Sig", ident.signer_reponse(service.identite(), nonce, self.path, bytes(corps)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(corps)

        def _nonce(self):
            nonce = self.headers.get("X-WC-Nonce", "")
            return nonce if _NONCE.fullmatch(nonce) else None

        def _entree(self):
            """Contrôles communs : nonce, taille de la requête, simultanéité, débit. Renvoie le nonce, ou None si la
            requête est refusée (la réponse d'erreur est alors déjà envoyée, signée quand le nonce est valide, pour que le
            visiteur sache POURQUOI : trop de requêtes, trop de connexions...)."""
            nonce = self._nonce()
            if len(self.path) > CHEMINS_MAX:
                self._repondre(414, {"erreur": "adresse trop longue"}, nonce=nonce)
                return None
            if nonce is None:
                self._repondre(400, {"erreur": "en-tête X-WC-Nonce attendu (32 caractères hexadécimaux)"})
                return None
            if not semaphore.acquire(blocking=False):
                self._repondre(503, {"erreur": "trop de connexions"}, nonce=nonce)
                return None
            if not limiteur.autoriser():
                semaphore.release()
                self._repondre(429, {"erreur": "trop de requêtes, patiente"}, nonce=nonce)
                return None
            return nonce

        # ------------------------------------------------------------------------ GET
        def do_GET(self):
            nonce = self._entree()
            if nonce is None:
                return
            try:
                url = urlsplit(self.path)
                params = {k: v[0] for k, v in parse_qs(url.query, max_num_fields=12).items()}
                chemin = url.path
                try:
                    if chemin == "/p2p/salut":
                        return self._repondre(200, {"fiche": service.ma_fiche()}, nonce=nonce)
                    if chemin == "/p2p/pairs":
                        return self._repondre(200, {"fiches": self._pairs(params)}, nonce=nonce)
                    if chemin in ("/p2p/profil", "/p2p/collection", "/p2p/cartes"):
                        with base.connexion_lecture() as conn:
                            if chemin == "/p2p/profil":
                                donnees = partage.profil(conn)
                            elif chemin == "/p2p/collection":
                                donnees = partage.collection(conn, params)
                            else:
                                ids = [int(x) for x in str(params.get("ids", "")).split(",")[:partage.IDS_MAX]
                                       if x.strip().isdigit()]
                                donnees = partage.cartes_par_ids(conn, ids)
                        return self._repondre(200, donnees, nonce=nonce)
                    if chemin == "/p2p/photo":                    # la photo de profil (le carré visible dans le cercle), si le profil est public
                        with base.connexion_lecture() as conn:
                            partagee = partage.photo_partagee(conn)
                        if partagee is None:
                            return self._repondre(404, {"erreur": "pas de photo"}, nonce=nonce)
                        return self._repondre(200, partagee[0], partagee[1], nonce=nonce)
                    calque = _CALQUE.fullmatch(chemin)
                    if calque:                                    # un calque du full-art d'une carte partagée
                        with base.connexion_lecture() as conn:
                            octets = partage.fullart_partage(conn, calque.group(1), unquote(calque.group(2)))
                        if octets is None:
                            return self._repondre(404, {"erreur": "calque introuvable"}, nonce=nonce)
                        return self._repondre(200, octets, "image/png", nonce=nonce)
                    trouve = _NOM_IMAGE.fullmatch(chemin)
                    if trouve:
                        with base.connexion_lecture() as conn:
                            image = partage.image_partagee(conn, trouve.group(1))
                        if image is None:
                            return self._repondre(404, {"erreur": "image introuvable"}, nonce=nonce)
                        return self._repondre(200, image[0], image[1], nonce=nonce)
                    return self._repondre(404, {"erreur": "introuvable"}, nonce=nonce)
                except partage.Refuse as refus:
                    return self._repondre(403, {"refus": refus.quoi}, nonce=nonce)
                except Exception:                           # une erreur chez nous ne doit rien révéler
                    return self._repondre(500, {"erreur": "erreur du nœud"}, nonce=nonce)
            finally:
                semaphore.release()

        def _pairs(self, params):
            try:
                n = max(1, min(200, int(params.get("n", 100))))
            except ValueError:
                n = 100
            with base.connexion_lecture() as conn:
                fiches = p2p_annuaire.echantillon_gossip(conn, n)
            moi = service.ma_fiche()
            return [moi] + [f for f in fiches if f["id"] != moi["id"]][:n]

        # ----------------------------------------------------------------------- POST
        def do_POST(self):
            nonce = self._entree()
            if nonce is None:
                return
            try:
                if urlsplit(self.path).path != "/p2p/annonce":
                    return self._repondre(404, {"erreur": "introuvable"}, nonce=nonce)
                if not annonces.autoriser():
                    return self._repondre(429, {"erreur": "trop d'annonces"}, nonce=nonce)
                try:
                    longueur = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    return self._repondre(411, {"erreur": "longueur attendue"}, nonce=nonce)
                if not 0 < longueur <= CORPS_MAX:
                    return self._repondre(413, {"erreur": "corps trop gros"}, nonce=nonce)
                try:
                    donnees = json.loads(self.rfile.read(longueur).decode("utf-8"))
                    fiche = ident.verifier_fiche(donnees.get("fiche") if isinstance(donnees, dict) else None)
                except (ValueError, UnicodeDecodeError, ident.FicheInvalide) as erreur:
                    return self._repondre(400, {"erreur": f"fiche refusée : {erreur}"}, nonce=nonce)
                with base.connexion_rapide() as conn:
                    change = p2p_annuaire.fusionner(conn, fiche, source="annonce")
                return self._repondre(200, {"ok": True, "nouveau": bool(change)}, nonce=nonce)
            finally:
                semaphore.release()

        def _refuser(self):
            self.send_response(405)
            self.send_header("Allow", "GET, POST")
            self.send_header("Content-Length", "0")
            self.end_headers()

        # Aucune autre méthode : ni suppression, ni modification, ni dépôt de fichier.
        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _refuser

    class Serveur(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True
        request_queue_size = 32

    return Serveur((hote, port), Gestionnaire)
