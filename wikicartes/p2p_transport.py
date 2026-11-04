"""Transports du partage pair à pair : comment joindre un autre collectionneur (et se faire joindre).

- « tor » : chaque nœud publie un SERVICE OIGNON dont l'adresse est dérivée de sa clé d'identité (même clé :
  se connecter à l'adresse prouve que l'on parle au propriétaire de la clé) ; aucune ouverture de port,
  l'adresse IP de chacun reste cachée. Le programme parle à Tor par son port de contrôle (publication du
  service) et par son proxy SOCKS5 (connexions sortantes). Tor doit tourner sur ta machine.
- « direct » : adresse publique « hôte:port » (port ouvert) ; ton adresse IP est visible par tes visiteurs.
- « local » : essais sur ta machine ou ton réseau local.

Tout ce qui vient d'ailleurs est traité comme hostile : adresses publiques seulement (sauf en mode local),
réponses limitées en taille et en durée, aucune redirection, et CHAQUE réponse est signée par la clé du pair
contacté (liée à la requête par un nonce : pas de rejeu, pas de falsification en route).
"""

import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import socket
import struct
import time
from base64 import b64encode

from . import config, p2p_identite

TAILLE_REPONSE_MAX = 8 * 1024 * 1024
DELAI = 20
# Une connexion via Tor vers un service oignon demande Tor de retrouver sa description, de construire un circuit de
# 6 relais et d'établir le rendez-vous : la PREMIÈRE connexion (ou la première après un moment) prend couramment
# 20 à 60 secondes. Le délai « Tor » est donc bien plus long, et on réessaie une fois.
DELAI_TOR = 75
PAUSE_ENTRE_ESSAIS = 2.0
_HOTE_PORT = re.compile(r"(\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9._\-]+):(\d{1,5})")


class TransportErreur(Exception):
    """Un pair n'a pas pu être joint ou a répondu de façon invalide (message lisible)."""


class TorErreur(TransportErreur):
    """Tor n'est pas joignable ou refuse (message lisible)."""


def analyser_hote_port(texte):
    """« hôte:port » -> (hôte, port), ou TransportErreur."""
    trouve = _HOTE_PORT.fullmatch(texte or "")
    if not trouve or not 1 <= int(trouve.group(2)) <= 65535:
        raise TransportErreur("adresse « hôte:port » invalide")
    return trouve.group(1).strip("[]"), int(trouve.group(2))


def _adresses(hote, port):
    try:
        return [info[4][0] for info in socket.getaddrinfo(hote, port, type=socket.SOCK_STREAM)]
    except (socket.gaierror, UnicodeError):
        raise TransportErreur("hôte introuvable") from None


def _est_publique(ip):
    adresse = ipaddress.ip_address(ip.split("%")[0])
    if getattr(adresse, "ipv4_mapped", None):
        adresse = adresse.ipv4_mapped
    return adresse.is_global and not adresse.is_multicast


def verifier_hote_distant(hote, port, autoriser_local=False):
    """Un pair déclare une adresse « hôte:port » : on n'y va que si elle pointe vers Internet (jamais ton
    ordinateur ni ton réseau local, sinon un pair pourrait te faire contacter tes propres services). En
    mode « local » seulement, tout est permis."""
    if autoriser_local:
        return
    adresses = _adresses(hote, port)
    if not adresses or not all(_est_publique(ip) for ip in adresses):
        raise TransportErreur("adresse de pair non publique : refusée")


# --------------------------------------------------------------------------------------- SOCKS5

class ConnexionSocks(http.client.HTTPConnection):
    """Connexion HTTP qui passe par un proxy SOCKS5 (Tor) en lui laissant résoudre le nom : un nom « .onion »
    n'est jamais résolu par ta machine."""

    def __init__(self, hote, port, proxy, timeout=DELAI):
        super().__init__(hote, port, timeout=timeout)
        self._proxys = proxy if isinstance(proxy, list) else [proxy]      # un proxy, ou plusieurs à essayer

    def connect(self):
        prise, derniere = None, None
        for proxy in self._proxys:
            try:
                prise = socket.create_connection(proxy, timeout=min(self.timeout, 10))   # le proxy local répond tout de suite
                prise.settimeout(self.timeout)                                          # la suite peut être longue (circuits)
                break
            except OSError as erreur:
                derniere = (proxy, erreur)
        if prise is None:
            essais = ", ".join(f"{p[0]}:{p[1]}" for p in self._proxys)
            raise TorErreur(f"proxy SOCKS de Tor injoignable ({essais}) : {derniere[1]}. Tor est-il lancé ?") from derniere[1]
        try:
            prise.sendall(b"\x05\x01\x00")
            reponse = _lire(prise, 2)
            if reponse != b"\x05\x00":
                raise TorErreur("le proxy SOCKS refuse la connexion sans authentification")
            nom = self.host.encode("idna") if not self.host.endswith(".onion") else self.host.encode("ascii")
            if not 1 <= len(nom) <= 255:
                raise TorErreur("nom d'hôte invalide")
            prise.sendall(b"\x05\x01\x00\x03" + bytes([len(nom)]) + nom + struct.pack(">H", self.port))
            tete = _lire(prise, 4)
            if tete[0] != 5 or tete[1] != 0:
                raise TorErreur(f"Tor n'a pas pu joindre ce pair (code SOCKS {tete[1]} : "
                                f"{_CODES_SOCKS.get(tete[1], 'erreur')})")
            reste = {1: 4, 4: 16}.get(tete[3])
            if reste is None:
                reste = _lire(prise, 1)[0] if tete[3] == 3 else 0
            _lire(prise, reste + 2)
        except (OSError, TorErreur) as erreur:
            prise.close()
            if isinstance(erreur, TorErreur):
                raise erreur
            if isinstance(erreur, socket.timeout):
                raise TorErreur(f"Tor n'a pas pu joindre ce collectionneur en {int(self.timeout)} secondes. La première "
                                "connexion via Tor peut prendre jusqu'à une minute (son service oignon met 1 à 2 minutes "
                                "à devenir visible après son démarrage) : réessaie dans un instant.") from erreur
            raise TorErreur(f"échec SOCKS : {erreur}") from erreur
        self.sock = prise


_CODES_SOCKS = {1: "échec général", 2: "refusé", 3: "réseau inaccessible", 4: "hôte inaccessible",
                5: "connexion refusée", 6: "délai dépassé", 7: "commande non gérée", 8: "adresse non gérée"}


def _lire(prise, n):
    donnees = b""
    while len(donnees) < n:
        morceau = prise.recv(n - len(donnees))
        if not morceau:
            raise OSError("connexion fermée par le proxy")
        donnees += morceau
    return donnees


# ------------------------------------------------------------------------------ port de contrôle Tor

class TorControle:
    """Client minimal du port de contrôle de Tor : authentification (aucune, cookie ou cookie sûr) et
    publication d'un service oignon v3 avec NOTRE clé. Le service dure tant que cette connexion reste ouverte."""

    def __init__(self, hote, port, timeout=DELAI):
        try:
            self._prise = socket.create_connection((hote, port), timeout=timeout)
        except OSError as erreur:
            raise TorErreur(f"port de contrôle de Tor injoignable ({hote}:{port}) : {erreur}") from erreur
        self._tampon = b""

    def _envoyer(self, ligne):
        try:
            self._prise.sendall(ligne.encode("ascii") + b"\r\n")
        except OSError as erreur:
            raise TorErreur(f"connexion de contrôle de Tor perdue : {erreur}") from erreur

    def _ligne(self):
        while b"\r\n" not in self._tampon:
            try:
                morceau = self._prise.recv(4096)
            except OSError as erreur:
                raise TorErreur(f"connexion de contrôle de Tor perdue : {erreur}") from erreur
            if not morceau:
                raise TorErreur("Tor a fermé la connexion de contrôle")
            self._tampon += morceau
            if len(self._tampon) > 65536:
                raise TorErreur("réponse de contrôle trop longue")
        ligne, self._tampon = self._tampon.split(b"\r\n", 1)
        return ligne.decode("utf-8", "replace")

    def commande(self, ligne):
        """Envoie une commande et renvoie la liste des lignes de réponse (texte après le code) ; lève
        TorErreur si le code n'est pas 250."""
        self._envoyer(ligne)
        lignes = []
        while True:
            texte = self._ligne()
            if len(texte) < 4 or not texte[:3].isdigit():
                raise TorErreur("réponse de contrôle illisible")
            code, separateur, reste = texte[:3], texte[3], texte[4:]
            lignes.append(reste)
            if separateur == " ":
                if code != "250":
                    raise TorErreur(f"Tor a répondu {code} {reste}")
                return lignes
            if separateur not in "-+":
                raise TorErreur("réponse de contrôle illisible")

    def authentifier(self):
        infos = " ".join(self.commande("PROTOCOLINFO 1"))
        methodes = re.search(r"METHODS=([A-Z,]+)", infos)
        methodes = methodes.group(1).split(",") if methodes else []
        fichier = re.search(r'COOKIEFILE="((?:[^"\\]|\\.)*)"', infos)
        cookie = None
        if fichier and ("SAFECOOKIE" in methodes or "COOKIE" in methodes):
            try:
                with open(fichier.group(1).replace('\\\\', '\\'), "rb") as f:
                    cookie = f.read(33)
            except OSError as erreur:
                raise TorErreur(f"cookie d'authentification de Tor illisible : {erreur}") from erreur
            if len(cookie) != 32:
                raise TorErreur("cookie d'authentification de Tor invalide")
        if "NULL" in methodes:
            self.commande("AUTHENTICATE")
        elif "SAFECOOKIE" in methodes and cookie:
            nonce_client = os.urandom(32)
            reponse = " ".join(self.commande("AUTHCHALLENGE SAFECOOKIE " + nonce_client.hex()))
            serveur = re.search(r"SERVERHASH=([0-9A-Fa-f]{64})", reponse)
            nonce_serveur = re.search(r"SERVERNONCE=([0-9A-Fa-f]{64})", reponse)
            if not serveur or not nonce_serveur:
                raise TorErreur("réponse AUTHCHALLENGE invalide")
            serveur_nonce = bytes.fromhex(nonce_serveur.group(1))
            message = cookie + nonce_client + serveur_nonce
            attendu = hmac.new(b"Tor safe cookie authentication server-to-controller hash", message,
                               hashlib.sha256).hexdigest()
            if not hmac.compare_digest(attendu, serveur.group(1).lower()):
                raise TorErreur("Tor ne s'est pas authentifié correctement (SERVERHASH incorrect)")
            preuve = hmac.new(b"Tor safe cookie authentication controller-to-server hash", message,
                              hashlib.sha256).hexdigest()
            self.commande("AUTHENTICATE " + preuve)
        elif "COOKIE" in methodes and cookie:
            self.commande("AUTHENTICATE " + cookie.hex())
        else:
            raise TorErreur("authentification de Tor non prise en charge ici (seuls « aucune » et le cookie le "
                            "sont ; configure CookieAuthentication 1 dans torrc)")

    def publier(self, identite, port_local, port_virtuel=80):
        """Publie le service oignon de cette identité : joignable à identite.onion, il redirige vers
        127.0.0.1:port_local. Vérifie que Tor annonce bien l'adresse attendue."""
        cle = b64encode(identite.cle_etendue_tor()).decode("ascii")
        lignes = self.commande(f"ADD_ONION ED25519-V3:{cle} Flags=DiscardPK "
                               f"Port={int(port_virtuel)},127.0.0.1:{int(port_local)}")
        identifiant = next((l.split("=", 1)[1] for l in lignes if l.startswith("ServiceID=")), "")
        if identifiant + ".onion" != identite.onion:
            raise TorErreur("Tor a publié une autre adresse que celle de ta clé : abandon")
        return identite.onion

    def info(self, cle):
        """Valeur d'un « GETINFO » de Tor (par exemple « status/bootstrap-phase »), ou TorErreur."""
        for ligne in self.commande(f"GETINFO {cle}"):
            if ligne.startswith(cle + "="):
                return ligne.split("=", 1)[1]
        raise TorErreur(f"Tor n'a pas donné « {cle} »")

    def progression(self):
        """Avancement de la connexion de Tor au réseau, de 0 à 100 (100 = Tor est prêt)."""
        trouve = re.search(r"PROGRESS=(\d+)", self.info("status/bootstrap-phase"))
        return int(trouve.group(1)) if trouve else 0

    def fermer(self):
        try:
            self._prise.close()
        except OSError:
            pass


# --------------------------------------------------------------------------- ouverture d'une connexion

# Tor n'utilise pas les mêmes ports selon qu'il tourne seul (service ou tor.exe : SOCKS 9050, contrôle 9051) ou
# avec le NAVIGATEUR TOR (SOCKS 9150, contrôle 9151). Tant que les réglages gardent leur valeur d'origine, on essaie
# aussi les ports du navigateur Tor ; une valeur que tu as choisie toi-même est respectée telle quelle.
PORTS_TOR = {"controle": ("127.0.0.1:9051", "127.0.0.1:9151"), "socks": ("127.0.0.1:9050", "127.0.0.1:9150")}


def candidats_tor(genre, valeur):
    """Les adresses « hôte:port » à essayer pour joindre Tor (le réglage, puis les ports du navigateur Tor si le
    réglage est encore celui d'origine)."""
    defaut, alternative = PORTS_TOR[genre]
    return [valeur, alternative] if valeur == defaut else [valeur]


def _proxys_socks():
    return [analyser_hote_port(a) for a in candidats_tor("socks", config.P2P_TOR_SOCKS)]


def ouvrir_connexion(fiche, timeout=DELAI):
    """Une connexion HTTP vers le pair décrit par `fiche` (déjà vérifiée), selon son transport et le mien."""
    mon_mode = config.P2P_TRANSPORT
    if fiche["transport"] == "tor":
        return ConnexionSocks(p2p_identite.adresse_onion_de(fiche["id"]), 80, _proxys_socks(), timeout)
    hote, port = analyser_hote_port(fiche["adresse"])
    if fiche["transport"] == "local" and mon_mode != "local":
        raise TransportErreur("ce pair est en mode local : joignable seulement depuis un nœud en mode local")
    verifier_hote_distant(hote, port, autoriser_local=(mon_mode == "local"))
    if mon_mode == "tor" and fiche["transport"] == "direct":
        return ConnexionSocks(hote, port, _proxys_socks(), timeout)        # mon IP reste cachée
    return http.client.HTTPConnection(hote, port, timeout=timeout)


def _passe_par_tor(fiche):
    return fiche["transport"] == "tor" or (config.P2P_TRANSPORT == "tor" and fiche["transport"] == "direct")


def requete(fiche, chemin, methode="GET", corps=None, maxi=TAILLE_REPONSE_MAX, timeout=None):
    """Appelle un pair : renvoie (statut, octets) après avoir VÉRIFIÉ la signature de la réponse (clé du pair,
    nonce de cette requête, chemin, empreinte du corps). Aucune redirection n'est suivie. Via Tor, le délai est long
    (DELAI_TOR) et une connexion qui échoue est retentée une fois (les circuits Tor échouent parfois au premier essai)."""
    if not isinstance(chemin, str) or not chemin.startswith("/p2p/"):
        raise TransportErreur("chemin invalide")
    via_tor = _passe_par_tor(fiche)
    if timeout is None:
        timeout = DELAI_TOR if via_tor else DELAI
    essais = 2 if via_tor else 1
    for essai in range(essais):
        try:
            return _requete_une_fois(fiche, chemin, methode, corps, maxi, timeout)
        except _Retentable as erreur:
            if essai + 1 >= essais:
                raise erreur.origine from None
            time.sleep(PAUSE_ENTRE_ESSAIS)


class _Retentable(Exception):
    """Un échec de connexion qui vaut la peine d'être retenté (jamais une signature fausse ni une réponse invalide)."""

    def __init__(self, origine):
        super().__init__(str(origine))
        self.origine = origine


def _requete_une_fois(fiche, chemin, methode, corps, maxi, timeout):
    nonce = os.urandom(16).hex()
    entetes = {"X-WC-Nonce": nonce, "Connection": "close", "User-Agent": "WikiCartes-P2P/1"}
    if corps is not None:
        entetes["Content-Type"] = "application/json"
    try:
        connexion = ouvrir_connexion(fiche, timeout)
    except TorErreur as erreur:
        raise _Retentable(erreur) from erreur
    try:
        try:
            connexion.request(methode, chemin, body=corps, headers=entetes)
            reponse = connexion.getresponse()
            annonce = reponse.getheader("Content-Length", "")
            if annonce.isdigit() and int(annonce) > maxi:
                raise TransportErreur("réponse trop volumineuse")
            donnees = reponse.read(maxi + 1)
            if len(donnees) > maxi:
                raise TransportErreur("réponse trop volumineuse")
            signature = reponse.getheader("X-WC-Sig")
            statut = reponse.status
        except TorErreur as erreur:                       # échec SOCKS pendant la connexion : on peut réessayer
            raise _Retentable(erreur) from erreur
        except (OSError, http.client.HTTPException) as erreur:
            raise _Retentable(TransportErreur(f"pair injoignable : {erreur}")) from erreur
    finally:
        connexion.close()
    if not signature or not p2p_identite.verifier_reponse(fiche["id"], nonce, chemin, donnees, signature):
        raise TransportErreur("réponse non signée ou signature incorrecte : ignorée (ce n'est pas le bon pair)")
    return statut, donnees


def appeler_json(fiche, chemin, **options):
    """Comme requete(), avec la réponse décodée en JSON (dictionnaire) ; TransportErreur sinon."""
    statut, octets = requete(fiche, chemin, **options)
    try:
        donnees = json.loads(octets.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise TransportErreur("réponse du pair illisible") from None
    if not isinstance(donnees, dict):
        raise TransportErreur("réponse du pair invalide")
    return statut, donnees
