"""Accès au programme depuis le réseau local ou depuis l'extérieur (tunnel, adresse IP publique, mobile...).

Par défaut le serveur n'écoute que sur 127.0.0.1 (cet ordinateur) : rien ne change. Avec ACCES_RESEAU = « reseau » il écoute sur
toutes les interfaces : le programme est alors un vrai SERVEUR, utilisable depuis n'importe quel appareil qui peut l'atteindre
(réseau local, tunnel, adresse IP publique), SANS mot de passe. Si l'utilisateur définit un CODE D'ACCÈS (facultatif, vide par défaut),
toute requête qui ne vient pas de cet ordinateur doit alors être authentifiée par ce code :
- une requête est « locale » seulement si elle vient de l'adresse de bouclage (127.0.0.1 / ::1), vise un nom d'hôte local ET ne porte
  aucun en-tête de relais (X-Forwarded-*, Forwarded, CF-*, Via... que les tunnels ajoutent) : un tunnel ou un proxy inverse installé
  sur cet ordinateur ne peut donc pas faire passer une requête de l'extérieur pour une requête locale ;
- les autres doivent présenter un cookie de session (HttpOnly, SameSite=Strict, Secure derrière HTTPS) obtenu en tapant le code sur
  la page /connexion ; essais limités (verrouillage temporaire après plusieurs échecs, par client ET au total) ;
- le code est comparé en temps constant ; il est généré au hasard au premier besoin et affiché dans la Configuration.

Le trafic en clair (http) ne protège pas le code sur un réseau non fiable : pour l'extérieur, passe par un tunnel qui fournit HTTPS.
"""

import hmac
import html
import ipaddress
import secrets
import socket
import threading
import time
from collections import deque
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from . import config, favicon

NOM_COOKIE = "wikicartes_session"
DUREE_SESSION = 24 * 3600
HOTES_LOCAUX = ("127.0.0.1", "localhost", "[::1]", "::1")
EN_TETES_RELAIS = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port", "forwarded", "x-real-ip", "via",
                   "cf-connecting-ip", "cf-ray", "cf-visitor", "true-client-ip", "x-original-forwarded-for", "x-envoy-external-address",
                   "x-amzn-trace-id", "tailscale-user-login", "x-tunnel-id", "ngrok-trace-id", "x-forwarded-server")
ECHECS_MAX = 5                      # essais ratés avant verrouillage (par client)
ECHECS_GLOBAL_MAX = 25              # essais ratés au total, toutes origines confondues, sur la fenêtre
FENETRE_ECHECS = 600                # s
VERROU_BASE = 60                    # s, doublé à chaque verrouillage successif (3600 s au plus)

PORT = {"valeur": 0}                # port réel du serveur (pour afficher les adresses)

_verrou = threading.Lock()
_sessions = {}                      # jeton -> instant d'expiration
_echecs = {}                        # client -> deque d'instants d'échec
_verrouilles = {}                   # client -> (jusqu'à, nombre de verrouillages)
_echecs_globaux = deque()
_global_verrouille = [0.0]


def mode_reseau():
    return config.ACCES_RESEAU == "reseau"


def exige_code():
    """Un code d'accès est-il exigé des requêtes qui ne viennent pas de cet ordinateur ? Seulement en mode réseau ET si un code
    a été défini (facultatif, vide par défaut : aucun mot de passe)."""
    return mode_reseau() and bool(config.ACCES_CODE)


TEST = {"adresses": [], "ts": 0.0, "en_cours": False}


def tester_adresses(port, delai=1.5):
    """Essaie de joindre ce serveur par chacune de ses adresses du réseau local (comme le ferait un autre appareil). Une adresse qui
    ne répond pas est presque toujours bloquée par le PARE-FEU du système (Windows demande l'autorisation au premier lancement)."""
    TEST["en_cours"] = True
    resultats = []
    for ip in adresses_locales():
        try:
            with socket.create_connection((ip, int(port)), timeout=delai):
                resultats.append((ip, True))
        except OSError:
            resultats.append((ip, False))
    TEST["adresses"], TEST["ts"], TEST["en_cours"] = resultats, time.time(), False
    return resultats


def commande_pare_feu(port):
    """La commande Windows (à lancer dans une invite de commandes « en administrateur ») qui autorise ce port sur le réseau local."""
    return (f'netsh advfirewall firewall add rule name="WikiCartes {int(port)}" dir=in action=allow protocol=TCP '
            f'localport={int(port)} profile=private,domain')


def hote_d_ecoute():
    """L'adresse d'écoute du serveur : toutes les interfaces en mode réseau, sinon seulement cet ordinateur."""
    return "0.0.0.0" if mode_reseau() else "127.0.0.1"


def generer_code():
    """Un code d'accès au hasard (12 caractères sûrs, sans ambiguïté)."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


def nom_hote(valeur_host):
    """Le nom d'hôte sans le port (« localhost:8765 » -> « localhost » ; « [::1]:80 » -> « [::1] »)."""
    valeur = (valeur_host or "").strip().lower()
    if valeur.startswith("["):
        return valeur.split("]")[0] + "]"
    return valeur.split(":")[0]


def requete_locale(adresse_client, en_tetes):
    """La requête vient-elle vraiment de cet ordinateur (et non d'un tunnel ou d'un proxy qui relaie l'extérieur) ?"""
    if adresse_client not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return False
    if nom_hote(en_tetes.get("Host", "")) not in HOTES_LOCAUX:
        return False
    return not any(en_tetes.get(nom) is not None for nom in EN_TETES_RELAIS)


def origine_acceptable(en_tetes):
    """Contrôle d'origine d'une requête qui modifie quelque chose : sans en-tête Origin (outil, même site) ou avec la MÊME origine
    que le site demandé (le nom d'hôte et le port de l'adresse tapée). Une page d'un autre site est refusée."""
    origine = en_tetes.get("Origin")
    if origine is None:
        return True
    return urlsplit(origine).netloc.lower() == (en_tetes.get("Host") or "").strip().lower()


def _purger(maintenant):
    for jeton in [j for j, fin in _sessions.items() if fin <= maintenant]:
        del _sessions[jeton]


def creer_session(maintenant=None):
    maintenant = time.time() if maintenant is None else maintenant
    jeton = secrets.token_urlsafe(32)
    with _verrou:
        _purger(maintenant)
        _sessions[jeton] = maintenant + DUREE_SESSION
    return jeton


def session_valide(en_tete_cookie, maintenant=None):
    """Le cookie présenté contient-il une session ouverte et non expirée ?"""
    maintenant = time.time() if maintenant is None else maintenant
    if not en_tete_cookie:
        return False
    try:
        cookie = SimpleCookie(en_tete_cookie)
    except Exception:                                   # cookie mal formé : refusé
        return False
    morceau = cookie.get(NOM_COOKIE)
    if morceau is None:
        return False
    with _verrou:
        _purger(maintenant)
        fin = _sessions.get(morceau.value)
    return fin is not None and fin > maintenant


def fermer_session(en_tete_cookie):
    try:
        morceau = SimpleCookie(en_tete_cookie or "").get(NOM_COOKIE)
    except Exception:
        return
    if morceau is not None:
        with _verrou:
            _sessions.pop(morceau.value, None)


def en_tete_cookie(jeton, securise, expire=False):
    """La valeur de l'en-tête Set-Cookie (session ouverte, ou supprimée avec expire=True)."""
    morceaux = [f"{NOM_COOKIE}={'' if expire else jeton}", "Path=/", "HttpOnly", "SameSite=Strict",
                f"Max-Age={0 if expire else DUREE_SESSION}"]
    if securise:
        morceaux.append("Secure")
    return "; ".join(morceaux)


def attente_verrou(client, maintenant=None):
    """Secondes à attendre avant un nouvel essai (0 : essai permis)."""
    maintenant = time.time() if maintenant is None else maintenant
    with _verrou:
        jusqu_a = max(_verrouilles.get(client, (0.0, 0))[0], _global_verrouille[0])
    return max(0.0, jusqu_a - maintenant)


def noter_echec(client, maintenant=None):
    """Note un code faux ; verrouille le client (et, si ça s'accumule de partout, tout le monde) un moment."""
    maintenant = time.time() if maintenant is None else maintenant
    with _verrou:
        liste = _echecs.setdefault(client, deque())
        liste.append(maintenant)
        while liste and liste[0] < maintenant - FENETRE_ECHECS:
            liste.popleft()
        if len(liste) >= ECHECS_MAX:
            _, n = _verrouilles.get(client, (0.0, 0))
            _verrouilles[client] = (maintenant + min(3600, VERROU_BASE * (2 ** n)), n + 1)
            liste.clear()
        _echecs_globaux.append(maintenant)
        while _echecs_globaux and _echecs_globaux[0] < maintenant - FENETRE_ECHECS:
            _echecs_globaux.popleft()
        if len(_echecs_globaux) >= ECHECS_GLOBAL_MAX:
            _global_verrouille[0] = maintenant + VERROU_BASE * 5
            _echecs_globaux.clear()


def effacer_echecs(client):
    with _verrou:
        _echecs.pop(client, None)


def code_correct(candidat):
    """Le code tapé est-il le bon ? (comparaison en temps constant ; jamais vrai si aucun code n'est défini)"""
    attendu = config.ACCES_CODE or ""
    if not attendu or not isinstance(candidat, str):
        return False
    return hmac.compare_digest(candidat.encode("utf-8"), attendu.encode("utf-8"))


def retour_sur(chemin):
    """Où revenir après la connexion : un chemin du site (« /profil »), jamais une adresse extérieure ni « // »."""
    if isinstance(chemin, str) and chemin.startswith("/") and not chemin.startswith("//") and "\\" not in chemin \
            and "\n" not in chemin and "\r" not in chemin and len(chemin) <= 300:
        return chemin
    return "/paquets"


def adresses_locales():
    """Les adresses IP de cet ordinateur sur le réseau local (sans le bouclage), pour les afficher."""
    adresses = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in adresses:
                adresses.append(ip)
    except OSError:
        pass
    try:                                                # l'interface utilisée pour sortir (sans rien envoyer)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if not ip.startswith("127.") and ip not in adresses:
                adresses.insert(0, ip)
    except OSError:
        pass
    return adresses


def page_connexion(erreur="", retour="/paquets", attente=0):
    """La page de saisie du code (autonome : aucune ressource externe, aucun script)."""
    message = ""
    if attente > 0:
        message = f'<p class="erreur">Trop d\'essais : réessaie dans {int(attente) + 1} secondes.</p>'
    elif erreur:
        message = f'<p class="erreur">{html.escape(erreur)}</p>'
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">{favicon.lien_html()}<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light"><meta name="robots" content="noindex">
<title>{html.escape(config.TITRE_SITE)} — connexion</title>
<style>
body {{ font-family: system-ui, sans-serif; background: #0e0f14; color: #eceef5; display: grid; place-items: center; min-height: 100vh; margin: 0; }}
main {{ width: min(380px, 92vw); padding: 28px; background: #181a22; border: 1px solid #343846; border-radius: 14px; }}
h1 {{ font-size: 1.25rem; margin: 0 0 6px; }} p {{ color: #aab0c4; font-size: .92rem; line-height: 1.45; }}
label {{ display: block; margin: 16px 0 6px; font-weight: 600; }}
input[type=password] {{ width: 100%; box-sizing: border-box; padding: 12px; font-size: 1.05rem; border-radius: 8px; border: 1px solid #4a4f63; background: #0e0f14; color: inherit; }}
button {{ margin-top: 16px; width: 100%; padding: 12px; border: 0; border-radius: 999px; background: #ffd34d; color: #1b1500; font-weight: 700; font-size: 1rem; cursor: pointer; }}
.erreur {{ color: #ff8a80; font-weight: 600; }}
</style></head><body><main>
<h1>{html.escape(config.TITRE_SITE)}</h1>
<p>Cet accès est protégé. Tape le code d'accès affiché dans la Configuration, sur l'ordinateur qui fait tourner le programme.</p>
{message}
<form method="post" action="/connexion" autocomplete="off">
<input type="hidden" name="retour" value="{html.escape(retour_sur(retour), quote=True)}">
<label for="code">Code d'accès</label>
<input id="code" name="code" type="password" autocomplete="current-password" autofocus required maxlength="64">
<button type="submit">Entrer</button>
</form></main></body></html>
"""


# ---------------------------------------------------------------- « réseau local » : qui a le droit de voir les réglages avancés
EN_TETES_IP_RELAIS = ("x-forwarded-for", "x-real-ip", "cf-connecting-ip", "true-client-ip", "x-original-forwarded-for", "forwarded")


def _ip(texte):
    """Une adresse IP lue dans un texte (« 192.168.1.5 », « 192.168.1.5:5000 », « [::1] », « for="1.2.3.4" »), ou None."""
    t = str(texte or "").strip().strip('"').strip("[]").strip()
    for essai in (t, t.rsplit(":", 1)[0] if t.count(":") == 1 else t, t.split("%")[0]):
        try:
            ip = ipaddress.ip_address(essai)
        except ValueError:
            continue
        return ip.ipv4_mapped if getattr(ip, "ipv4_mapped", None) else ip
    return None


def ip_du_reseau_local(ip):
    """Cette adresse est-elle celle de cet ordinateur ou du réseau local (192.168.x.x, 10.x.x.x, 172.16-31.x.x, 169.254.x.x, ::1, fc00::/7,
    fe80::/10) ? Une adresse publique, ou le partage de connexion des opérateurs (100.64.x.x, VPN), n'en fait pas partie."""
    if ip is None:
        return False
    return any(ip in reseau for reseau in RESEAUX_LOCAUX if reseau.version == ip.version)


RESEAUX_LOCAUX = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10"))


def hote_du_reseau_local(valeur_host):
    """Le nom d'hôte demandé est-il local : « localhost », une adresse du réseau local, le nom de la machine (sans point), « .local » ?
    Un nom de domaine public (celui d'un tunnel) ne l'est pas."""
    nom = nom_hote(valeur_host)
    if not nom:
        return False
    ip = _ip(nom)
    if ip is not None:
        return ip_du_reseau_local(ip)
    return nom in HOTES_LOCAUX or "." not in nom or nom.endswith((".local", ".lan", ".home", ".internal"))


def _ips_annoncees(en_tetes):
    """Les adresses des clients annoncées par les relais (en-têtes X-Forwarded-For, Forwarded, CF-Connecting-IP...) ; None si l'une est illisible."""
    ips = []
    for nom in EN_TETES_IP_RELAIS:
        valeur = en_tetes.get(nom)
        if valeur is None:
            continue
        if nom == "forwarded":
            morceaux = [m.split("=", 1)[1] for partie in valeur.split(",") for m in partie.split(";") if m.strip().lower().startswith("for=")]
        else:
            morceaux = valeur.split(",")
        for m in morceaux:
            ip = _ip(m)
            if ip is None:
                return None
            ips.append(ip)
    return ips


def client_du_reseau_local(adresse_client, en_tetes):
    """La requête vient-elle de cet ordinateur ou du réseau local ? Les réglages avancés ne se montrent qu'à ces requêtes.
    - le client (adresse de la connexion) doit être de cet ordinateur ou du réseau local ;
    - un relais (tunnel, proxy) ajoute les adresses des vrais clients : si l'une est publique, ou illisible, ou si un en-tête de relais ne
      dit rien du client, la requête n'est PAS locale ;
    - sans relais, le nom d'hôte demandé ne doit pas être un nom de domaine public (un tunnel qui ne dit rien du client trahit son nom)."""
    pair = _ip(adresse_client)
    if not ip_du_reseau_local(pair):
        return False
    relais = any(en_tetes.get(nom) is not None for nom in EN_TETES_RELAIS)
    if relais:
        ips = _ips_annoncees(en_tetes)
        if not ips or not all(ip_du_reseau_local(ip) for ip in ips):
            return False
    elif any(en_tetes.get(nom) is not None for nom in ("x-forwarded-host", "x-forwarded-proto", "via", "cf-ray", "cf-visitor",
                                                          "x-forwarded-port", "x-envoy-external-address", "ngrok-trace-id")):
        return False                                    # un relais qui ne dit rien du client : on ne peut pas savoir
    return hote_du_reseau_local(en_tetes.get("Host", ""))
