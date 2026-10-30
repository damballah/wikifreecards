"""Petit serveur local (127.0.0.1 uniquement) : sert la page de cartes et enregistre
les cartes exportées en image dans Export/<rang>/.

Un navigateur ne peut pas écrire tout seul dans un dossier de l'ordinateur : c'est ce
serveur, lancé par main.py, qui reçoit l'image envoyée par la page et l'écrit sur le disque.
"""

import copy
import hmac
import io
import json
import re
import sqlite3
import sys
import threading
import time
import unicodedata
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

import requests

from . import (acces, api, base, config, createur, export, hall_api, images, logo, navigateur, p2p_identite, p2p_service, p2p_tor, paquet, photo, sauvegardes, sensible, sons, fullart, gifs, cadrage, favicon, projet, fermeture, journal, lot,
               parametres, profil, rarete, recherche, rendu, reserve, stats, web)
from . import categories as cat

HOTE = "127.0.0.1"


def _chemin_affichable(chemin):
    try:
        return chemin.relative_to(config.RACINE).as_posix()
    except ValueError:
        return str(chemin)


# Les routes qui parleraient à Wikipédia : refusées pendant une importation en lot (qui est exclusive, voir lot.py).
ROUTES_RESEAU = ("/api/paquet", "/api/paquet/flux", "/api/paquet/retirer", "/api/cartes/image", "/api/cartes/image/choisir", "/api/cartes/image/retirer", "/api/cartes/stats", "/api/profil/photo/carte",
                 "/api/recherche", "/api/recherche/importer", "/api/reserve/remplir")


# Clic sur le pied d'une carte : « mettre à jour ses statistiques » (une même carte au plus toutes les 30 secondes : chaque mise à jour fait quelques requêtes à Wikipédia)
DELAI_MAJ_STATS = 30.0
_DERNIERES_MAJ_STATS = {}
_VERROU_MAJ_STATS = threading.Lock()


class _ServeurHTTP(ThreadingHTTPServer):
    """Le serveur HTTP : une erreur imprévue pendant une requête est notée dans le journal d'activité (les fermetures de connexion du navigateur, normales, ne le sont pas)."""

    def handle_error(self, request, client_address):
        erreur = sys.exc_info()[1]
        if erreur is not None and not isinstance(erreur, (ConnectionError, TimeoutError)):
            journal.erreur("Erreur imprévue pendant une requête", erreur)
        super().handle_error(request, client_address)


def creer_serveur(jeton, port=None):
    """Crée le serveur (sans le lancer). port=0 : port libre choisi automatiquement."""
    if not jeton:
        raise ValueError("un jeton est nécessaire")
    port_depart = config.PORT_SERVEUR if port is None else port

    class Gestionnaire(BaseHTTPRequestHandler):
        server_version = "WikiCartes"

        def log_message(self, *args):          # pas de bruit dans le terminal
            pass

        def handle_one_request(self):
            self._debut_requete = time.monotonic()
            self._corps_json = None                # (les champs de la demande, pour le journal)
            self._journalise = False
            self._flux_origine = None
            try:
                super().handle_one_request()
            finally:
                if self._flux_origine is not None:
                    self.rfile = self._flux_origine          # (la connexion reprend où elle en était pour la requête suivante)
                    self._flux_origine = None

        def parse_request(self):
            """Journal actif : le corps JSON d'une demande est lu ici, une fois, pour être noté (sans rien de sensible) ; le gestionnaire le relit ensuite comme avant.
            Journal désactivé : rien n'est touché."""
            valide = super().parse_request()
            if valide and self.command == "POST" and journal.actif():
                try:
                    longueur = int(self.headers.get("Content-Length", "0"))
                    if 0 < longueur <= 300_000 and "json" in self.headers.get("Content-Type", "").lower():
                        corps = self.rfile.read(longueur)
                        self._flux_origine = self.rfile
                        self.rfile = io.BytesIO(corps)
                        try:
                            self._corps_json = json.loads(corps.decode("utf-8"))
                        except (ValueError, UnicodeDecodeError):
                            pass
                except (ValueError, OSError):
                    pass
            return valide

        def _journaliser(self, statut, type_contenu):
            """Une ligne du journal pour cette requête du navigateur (action humaine), sans rien de sensible. Jamais d'erreur."""
            if self._journalise or not journal.actif():
                return
            self._journalise = True
            try:
                url = urlsplit(self.path)
                duree = (time.monotonic() - getattr(self, "_debut_requete", time.monotonic())) * 1000
                journal.requete(self.command, url.path, statut, duree, type_contenu, self._corps_json, url.query)
            except Exception:
                pass

        def _repondre(self, statut, corps=b"", type_contenu="application/json; charset=utf-8",
                      entetes=None):
            if isinstance(corps, (dict, list)):
                corps = json.dumps(corps, ensure_ascii=False).encode("utf-8")
            if (statut == 200 and type_contenu.startswith("text/html") and self.command == "GET"
                    and self.headers.get("Sec-Fetch-Dest") == "document" and rendu.musique_dans_le_lecteur()):
                # Musique d'ambiance : la page demandée s'affiche dans le LECTEUR (cadre plein écran dans la fenêtre du haut,
                # qui garde la musique en continu). Les chargements du cadre lui-même (Sec-Fetch-Dest: iframe) reçoivent la page.
                corps = rendu.page_lecteur(self.path, jeton).encode("utf-8")
            self.send_response(statut)
            self.send_header("Content-Type", type_contenu)
            self.send_header("Content-Length", str(len(corps)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for nom, valeur in (entetes or {}).items():
                self.send_header(nom, valeur)
            self.end_headers()
            self.wfile.write(corps)
            self._journaliser(statut, type_contenu)

        def _hote_autorise(self):
            """Refuse les requêtes venant d'un autre site (protection du serveur local). En mode réseau, n'importe quel nom d'hôte
            bien formé est accepté (adresse IP du réseau, nom de tunnel...) : c'est le CODE d'accès qui protège, et l'origine
            d'une requête doit rester le site lui-même."""
            if acces.mode_reseau():
                hote = self.headers.get("Host", "")
                return (0 < len(hote) <= 255 and all(c.isalnum() or c in ".-:[]_" for c in hote)
                        and acces.origine_acceptable(self.headers))
            port_reel = self.server.server_address[1]
            hotes = {f"{HOTE}:{port_reel}", f"localhost:{port_reel}"}
            if self.headers.get("Host", "") not in hotes:
                return False
            origine = self.headers.get("Origin")
            return origine is None or origine in {f"http://{h}" for h in hotes}

        def _accueil_vers_paquets(self):
            """Sur téléphone, l'adresse « nue » du programme (tapée ou ouverte depuis un favori, sans passer par un lien du site) mène à
            l'OUVERTURE DES PAQUETS, comme au lancement sur ordinateur. Le bouton « Collection » du menu, lui, arrive avec un Referer
            du site et garde la collection. Sans effet si l'affichage téléphone est sur « jamais »."""
            if urlsplit(self.path).query or self.headers.get("Referer") or config.MOBILE_MODE == "jamais":
                return False
            agent = self.headers.get("User-Agent", "")
            mobile = self.headers.get("Sec-CH-UA-Mobile") == "?1" or bool(re.search(r"Android|iPhone|iPad|iPod|Mobile", agent))
            if not mobile:
                return False
            self.send_response(302)
            self.send_header("Location", "/paquets")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Vary", "User-Agent, Sec-CH-UA-Mobile, Referer")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True

        def _avance_visible(self):
            """Les réglages avancés sont-ils visibles pour cette requête ? Oui si l'option « réseau local seulement » est décochée, ou si
            la requête vient de cet ordinateur ou du réseau local ; non pour une adresse IP publique ou un tunnel."""
            return (not config.CONFIG_AVANCE_LOCAL) or acces.client_du_reseau_local(self.client_address[0], self.headers)

        def _refuser_avance(self):
            """Réponse 403 pour une action réservée au réseau local. Renvoie True si la requête a été refusée."""
            if self._avance_visible():
                return False
            self._repondre(403, {"erreur": "réglage avancé : réservé à cet ordinateur et au réseau local"})
            return True

        def _client(self):
            """Une clé par client pour limiter les essais de code (l'adresse du client, ou celle annoncée par le relais)."""
            relais = (self.headers.get("X-Forwarded-For") or self.headers.get("CF-Connecting-IP") or "").split(",")[0].strip()
            return relais[:64] or self.client_address[0]

        def _acces_autorise(self):
            """Mode réseau : une requête qui ne vient pas de cet ordinateur doit avoir ouvert une session (code d'accès). Renvoie
            True si la requête peut continuer ; sinon la réponse (page de connexion ou 401) est déjà envoyée."""
            if not acces.exige_code() or acces.requete_locale(self.client_address[0], self.headers):
                return True                       # pas de code défini (le cas normal) : le serveur est ouvert, sans mot de passe
            if acces.session_valide(self.headers.get("Cookie")):
                return True
            chemin = urlsplit(self.path)
            if self.command == "GET" and (self.headers.get("Sec-Fetch-Dest") in ("document", "iframe")
                                          or "text/html" in self.headers.get("Accept", "")):
                self.send_response(303)
                self.send_header("Location", "/connexion?retour=" + quote(chemin.path + ("?" + chemin.query if chemin.query else ""), safe=""))
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return False
            self._repondre(401, {"erreur": "connexion nécessaire (code d'accès)"})
            return False

        def _connexion(self):
            """GET /connexion : la page de saisie du code. POST /connexion : vérifie le code et ouvre la session."""
            if not acces.exige_code():                           # aucun code défini : pas de page de connexion
                self.send_response(303)
                self.send_header("Location", "/paquets")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            requete = urlsplit(self.path)
            retour = (parse_qs(requete.query).get("retour") or ["/paquets"])[0]
            if self.command == "GET":
                return self._repondre(200, acces.page_connexion(retour=retour).encode("utf-8"), "text/html; charset=utf-8")
            try:
                longueur = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._repondre(400, {"erreur": "corps invalide"})
            if not 0 < longueur <= 2048:
                return self._repondre(400, {"erreur": "corps invalide"})
            formulaire = parse_qs(self.rfile.read(longueur).decode("utf-8", "replace"))
            retour = (formulaire.get("retour") or ["/paquets"])[0]
            client = self._client()
            attente = acces.attente_verrou(client)
            if attente > 0:
                return self._repondre(429, acces.page_connexion(retour=retour, attente=attente).encode("utf-8"),
                                      "text/html; charset=utf-8", {"Retry-After": str(int(attente) + 1)})
            if not acces.code_correct((formulaire.get("code") or [""])[0]):
                acces.noter_echec(client)
                time.sleep(0.4)                                  # ralentit les essais en série
                return self._repondre(401, acces.page_connexion("Code incorrect.", retour).encode("utf-8"), "text/html; charset=utf-8")
            acces.effacer_echecs(client)
            jeton_session = acces.creer_session()
            securise = self.headers.get("X-Forwarded-Proto", "").lower() == "https"
            self.send_response(303)
            self.send_header("Location", acces.retour_sur(retour))
            self.send_header("Set-Cookie", acces.en_tete_cookie(jeton_session, securise))
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _deconnexion(self):
            acces.fermer_session(self.headers.get("Cookie"))
            securise = self.headers.get("X-Forwarded-Proto", "").lower() == "https"
            self.send_response(303)
            self.send_header("Location", "/connexion")
            self.send_header("Set-Cookie", acces.en_tete_cookie("", securise, expire=True))
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            if not self._hote_autorise():
                return self._repondre(403, {"erreur": "hôte non autorisé"})
            chemin_url = urlsplit(self.path).path
            if chemin_url == "/connexion":
                return self._connexion()
            if chemin_url == "/deconnexion":
                return self._deconnexion()
            if chemin_url in ("/favicon", "/favicon.ico"):          # (l'icône de l'onglet : aussi pour la page de connexion, donc avant le contrôle d'accès)
                return self._envoyer_favicon()
            if not self._acces_autorise():
                return
            if chemin_url == "/logo":
                return self._envoyer_logo(parse_qs(urlsplit(self.path).query))
            if chemin_url in ("/profil-photo", "/profil-photo/apercu"):
                return self._envoyer_photo(apercu=chemin_url.endswith("/apercu"))
            if chemin_url == "/son":
                return self._envoyer_son(parse_qs(urlsplit(self.path).query))
            if chemin_url == "/api/reserve/ouverture":
                try:
                    return self._repondre(200, {"ok": True, **reserve.statut_ouverture()})
                except (sqlite3.Error, OSError) as erreur:
                    return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
            if chemin_url == "/api/reserve":
                if self._refuser_avance():
                    return
                try:
                    return self._repondre(200, {"ok": True, **reserve.etat(), "stats": stats.etat()})
                except (sqlite3.Error, OSError) as erreur:
                    return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
            if chemin_url in ("/hall", "/hall/profil", "/hall/collection", "/hall/image", "/hall/fullart", "/hall/photo"):
                return self._page_hall(chemin_url, urlsplit(self.path))
            if chemin_url == "/createur":
                try:
                    page = rendu.page_createur(jeton)
                except (sqlite3.Error, OSError) as erreur:
                    return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
                return self._repondre(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if chemin_url.startswith("/image/"):
                return self._envoyer_image(chemin_url[len("/image/"):])
            if chemin_url == "/paquets":
                try:
                    page = rendu.page_paquets(jeton)
                except (sqlite3.Error, OSError) as erreur:
                    return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
                return self._repondre(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if chemin_url == "/profil":
                try:
                    page = rendu.page_profil(jeton)
                except (sqlite3.Error, OSError) as erreur:
                    return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
                return self._repondre(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if chemin_url == "/api/sauvegardes":
                return self._api_sauvegardes_liste()
            if chemin_url == "/sauvegardes/telecharger":
                if self._refuser_avance():
                    return
                return self._envoyer_sauvegarde(parse_qs(urlsplit(self.path).query))
            if chemin_url == "/api/profil/cartes":
                return self._envoyer_cartes_a_exposer(parse_qs(urlsplit(self.path).query))
            if chemin_url == "/api/fullart/listes":
                return self._repondre(200, {"zuul": fullart.lister("zuul"), "gozer": fullart.lister("gozer"),
                                            "effets": [{"code": c, "nom": n} for c, n in fullart.EFFETS.items()],
                                            "effets_max": fullart.EFFETS_MAX})
            if chemin_url.startswith("/fullart/"):
                return self._envoyer_calque_fullart(chemin_url)
            if chemin_url == "/api/cartes/stats":
                return self._envoyer_stats(parse_qs(urlsplit(self.path).query))
            if chemin_url == "/corbeille":
                demande = parse_qs(urlsplit(self.path).query)
                try:
                    numero = int(demande.get("page", ["1"])[0])
                except ValueError:
                    numero = 1
                try:
                    page = rendu.page_corbeille(jeton, numero)
                except (sqlite3.Error, OSError) as erreur:
                    return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
                return self._repondre(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if chemin_url == "/recherche":
                try:
                    page = rendu.page_recherche(jeton)
                except OSError as erreur:
                    return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
                return self._repondre(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if chemin_url == "/configuration":
                try:
                    page = rendu.page_configuration(jeton, avance_visible=self._avance_visible())
                except (sqlite3.Error, OSError) as erreur:
                    return self._repondre(500, {"erreur": f"lecture de la base impossible : {erreur}"})
                return self._repondre(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if chemin_url not in ("/", "/index.html"):
                return self._repondre(404, {"erreur": "introuvable"})
            if self._accueil_vers_paquets():
                return
            demande = parse_qs(urlsplit(self.path).query)
            try:
                numero = int(demande.get("page", ["1"])[0])
                nouveau = int(demande.get("nouveau", ["0"])[0])
            except ValueError:
                numero, nouveau = 1, 0
            try:
                page = rendu.page_collection(             # toujours à jour : lue dans la base
                    jeton, numero, max(0, min(nouveau, 100)))
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"lecture de la base impossible : {erreur}"})
            self._repondre(200, page.encode("utf-8"), "text/html; charset=utf-8")

        def _envoyer_son(self, demande):
            """Un son du dossier sons/ (`?fichier=<nom>`), avec la lecture par morceaux (Range) dont les navigateurs ont besoin
            pour se positionner dans une musique. Le nom doit être celui d'un fichier audio du dossier, rien d'autre."""
            fichier = sons.chemin((demande.get("fichier") or [""])[0])
            if fichier is None:
                return self._repondre(404, {"erreur": "son introuvable"})
            try:
                taille = fichier.stat().st_size
            except OSError:
                return self._repondre(404, {"erreur": "son illisible"})
            debut, fin, statut = 0, taille - 1, 200
            plage = self.headers.get("Range", "")
            if plage:
                m = re.fullmatch(r"bytes=(\d*)-(\d*)", plage.strip())
                if m and (m.group(1) or m.group(2)):
                    if m.group(1):
                        debut = int(m.group(1))
                        fin = int(m.group(2)) if m.group(2) else taille - 1
                    else:                                              # « les N derniers octets »
                        debut = max(0, taille - int(m.group(2)))
                    fin = min(fin, taille - 1)
                    if debut > fin or debut >= taille:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{taille}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    statut = 206
            longueur = fin - debut + 1
            self.send_response(statut)
            self.send_header("Content-Type", sons.type_mime(fichier.name))
            self.send_header("Content-Length", str(longueur))
            self.send_header("Accept-Ranges", "bytes")
            if statut == 206:
                self.send_header("Content-Range", f"bytes {debut}-{fin}/{taille}")
            self.send_header("Cache-Control", "private, max-age=600")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
            self.end_headers()
            try:
                with open(fichier, "rb") as source:
                    source.seek(debut)
                    restant = longueur
                    while restant > 0:
                        morceau = source.read(min(256 * 1024, restant))
                        if not morceau:
                            break
                        self.wfile.write(morceau)
                        restant -= len(morceau)
            except (OSError, ConnectionError):
                pass                                                   # le navigateur a interrompu la lecture

        def _api_sons(self, url, longueur):
            """Téléverser un fichier son (`?nom=<nom>`, corps = le fichier) ou en supprimer un (`{"nom": ...}`)."""
            action = url.path.rsplit("/", 1)[1]
            if action == "televerser":
                if not 0 < longueur <= sons.TAILLE_MAX:
                    return self._repondre(413 if longueur > sons.TAILLE_MAX else 400,
                                          {"erreur": f"fichier vide ou trop lourd ({sons.TAILLE_MAX // 1024 // 1024} Mo au maximum)"})
                nom = (parse_qs(url.query).get("nom") or [""])[0]
                try:
                    enregistre = sons.enregistrer(nom, self.rfile.read(longueur))
                except sons.SonRefuse as erreur:
                    return self._repondre(400, {"erreur": str(erreur)})
                except OSError as erreur:
                    return self._repondre(500, {"erreur": f"enregistrement impossible : {erreur}"})
                return self._repondre(200, {"ok": True, "nom": enregistre, "sons": sons.lister()})
            demande, erreur_envoyee = self._lire_json(longueur, 2000)
            if erreur_envoyee:
                return
            if action == "supprimer" and isinstance(demande, dict):
                if not sons.nom_valide(demande.get("nom")) or not sons.supprimer(demande.get("nom")):
                    return self._repondre(404, {"erreur": "son introuvable"})
                return self._repondre(200, {"ok": True, "sons": sons.lister()})
            return self._repondre(404, {"erreur": "introuvable"})

        def _envoyer_favicon(self):
            """L'icône de l'onglet : favicon.ico (16×16 ou 32×32) ou favicon.png (32×32) du dossier ico/, seulement si son contenu est valide."""
            trouve = favicon.trouver()
            if trouve is None:
                return self._repondre(404, {"erreur": "aucun favicon"})
            octets, mime, _ = trouve
            self._repondre(200, octets, mime, {"Content-Security-Policy": "default-src 'none'; sandbox"})

        def _envoyer_logo(self, demande=None):
            """Renvoie le logo choisi (en-tête des pages, booster, verso des documents).
            `?fichier=<nom, auto ou aucun>` : aperçu d'un autre choix, avant de l'enregistrer
            (page Configuration). Seuls les fichiers du dossier logo/ peuvent être lus."""
            choix = (demande or {}).get("fichier", [None])[0]
            if choix is not None and not logo.choix_valide(choix):
                return self._repondre(400, {"erreur": "choix de logo invalide"})
            fichier = logo.trouver(choix)
            if fichier is None:
                return self._repondre(404, {"erreur": "aucun logo"})
            try:
                donnees = fichier.read_bytes()
            except OSError:
                return self._repondre(404, {"erreur": "logo illisible"})
            if len(donnees) > logo.TAILLE_MAX:
                return self._repondre(413, {"erreur": "logo trop volumineux"})
            # Un logo SVG ouvert directement ne doit jamais pouvoir exécuter de script
            entetes = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; "
                                                  "sandbox"}
            self._repondre(200, donnees, logo.TYPES[fichier.suffix.lower()], entetes)

        def _api_favori(self, url):
            """Marque ou démarque une carte comme favorite, dans la base."""
            params = parse_qs(url.query)
            identifiant = params.get("id", [""])[0]
            valeur = params.get("valeur", [""])[0]
            if not identifiant.isdigit() or valeur not in ("0", "1"):
                return self._repondre(400, {"erreur": "paramètres invalides"})
            try:
                with base.connexion_rapide() as conn:
                    trouvee = base.definir_favori(conn, int(identifiant), valeur == "1")
            except sqlite3.Error as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            if not trouvee:
                return self._repondre(404, {"erreur": "carte inconnue"})
            self._repondre(200, {"ok": True, "favori": valeur == "1"})

        def _api_preferences(self, longueur):
            """Enregistre des réglages faits dans la page (taille des cartes, filtres...)."""
            if not 0 < longueur <= 20000:
                return self._repondre(400, {"erreur": "corps invalide"})
            try:
                demandes = json.loads(self.rfile.read(longueur).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._repondre(400, {"erreur": "JSON invalide"})
            if (not isinstance(demandes, dict) or not demandes
                    or any(cle not in parametres.MODIFIABLES_PAR_LA_PAGE for cle in demandes)):
                return self._repondre(400, {"erreur": "réglage non autorisé"})
            if not all(parametres.valide(cle, valeur) for cle, valeur in demandes.items()):
                return self._repondre(400, {"erreur": "valeur invalide"})
            try:
                with base.connexion_rapide() as conn:
                    for cle, valeur in demandes.items():
                        parametres.ecrire(conn, cle, valeur)
            except parametres.ValeurInvalide as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except sqlite3.Error as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, {"ok": True, "LARGEUR_CARTE": config.LARGEUR_CARTE})

        def _paquet_bloque(self):
            """Réponse 409 si l'ouverture est soumise à une réserve complète et qu'elle ne l'est pas encore : le paquet ne
            s'ouvre pas (le décompte en minutes est donné). Renvoie True si la demande a été refusée."""
            try:
                statut = reserve.statut_ouverture()
            except (sqlite3.Error, OSError):
                return False
            if not statut["bloque"]:
                return False
            self._repondre(409, {"erreur": f"Le prochain paquet n'est pas encore prêt ({statut['texte'].lower()}).",
                                 "bloque": True, "minutes": statut["minutes"], "reste": statut["reste"],
                                 "secondes": statut["secondes"]})
            return True

        def _api_flou(self, longueur):
            """L'icône +18 : garde (ou oublie) le fait que l'image d'une carte sensible est montrée, d'un lancement à l'autre."""
            demande, erreur_envoyee = self._lire_json(longueur, 1000)
            if erreur_envoyee:
                return
            if (not isinstance(demande, dict) or not sensible.adresse_valide(demande.get("url"))
                    or not isinstance(demande.get("revele"), bool)):
                return self._repondre(400, {"erreur": "demande invalide"})
            try:
                nombre = sensible.definir_revelee(demande["url"], demande["revele"])
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, {"ok": True, "reveles": nombre})

        def _carte_pour_image(self, identifiant, reseau=True, perso=False):
            """La carte dont on veut choisir ou retirer l'illustration, ou (None, statut, message) si c'est impossible : carte inconnue ou à la
            corbeille, carte personnalisée (pas d'article), carte d'une autre langue, carte FULL-ART (son illustration est définitive)."""
            try:
                with base.connexion_rapide() as conn:
                    cartes = base.cartes_par_identifiants(conn, [identifiant])
                    corbeille = conn.execute("SELECT supprime_le FROM cartes WHERE id = ?", (identifiant,)).fetchone()
            except sqlite3.Error as erreur:
                return None, 500, f"lecture impossible : {erreur}"
            if not cartes or corbeille is None or corbeille[0] is not None:
                return None, 404, "carte inconnue"
            carte = cartes[0]
            if carte.get("personnalisee") and not perso:
                return None, 400, "une carte personnalisée n'a pas d'article Wikipédia"
            if carte.get("fullart"):
                return None, 409, "cette carte est full-art : son illustration est définitive"
            if reseau and not carte.get("personnalisee") and carte.get("langue") != config.LANGUE:
                return None, 400, (f"cet article vient de Wikipédia en {carte.get('langue')} : change la langue (réglage Wikipédia) pour changer son image")
            return carte, 200, ""

        def _propositions_image(self, carte):
            """TOUTES les images à proposer pour une carte : celle qu'elle porte (actuelle), l'image principale de l'article, l'illustration qu'on vient de
            retirer (pour pouvoir la remettre), puis toutes les autres, dans l'ordre de la page. Renvoie (liste, actuelle, avertissement). Lève
            requests.RequestException si Wikipédia ne répond pas du tout ; ArticleIntrouvable si l'article n'existe plus. Le 4e élément est une ligne de diagnostic
            (version du programme, d'où viennent les images)."""
            actuelle = carte["image"] if carte["image"] != "no-image" else None
            nb_memoire = nb_autres = 0
            principale = (None, None)
            avertissements = []
            for essai in range(2):                             # l'image principale : un 2e essai si Wikipédia a répondu de travers
                try:
                    principale = api.image_actuelle(carte["titre"])
                    break
                except api.ArticleIntrouvable:
                    raise
                except requests.RequestException:
                    if essai == 1:
                        avertissements.append("l'image principale de Wikipédia n'a pas pu être lue")
            erreur_liste = False
            try:
                candidats = api.images_article(carte["titre"])
            except requests.RequestException:
                candidats, erreur_liste = [], True
                avertissements.append("la liste des images de l'article n'a pas pu être chargée")
            if erreur_liste and len(avertissements) == 2:
                raise requests.ConnectionError("Wikipédia ne répond pas")
            try:
                with base.connexion_rapide() as conn:
                    precedente = base.image_retiree(conn, carte["id"])         # l'image d'origine de la carte, même si l'article ne la propose plus
                    d_autres = [{"nom": cadrage.nom_fichier(i) or "image", "image": i, "miniature": m, "largeur": 0, "hauteur": 0, "mineure": False}
                                for i, m in base.images_des_cartes_du_meme_article(conn, carte["url"]) if api.adresse_wikimedia(i) and api.adresse_wikimedia(m)]
                    memorisees = base.images_vues_lire(conn, carte["url"])
                    nb_memoire, nb_autres = len(memorisees), len(d_autres)
                    candidats = api.reunir_images(candidats, memorisees + d_autres)       # + celles déjà vues dans cet article, + celles de tes autres cartes de cet article : aucune ne disparaît
                    base.images_vues_ecrire(conn, carte["url"], candidats)
            except sqlite3.Error:
                precedente = None
            nb_candidats = len(candidats)
            liste = api.fusionner_images(candidats, principale, actuelle, carte.get("miniature") if actuelle else None, precedente)
            nb_fusion = len(liste)
            gardees = [e for e in liste if e.get("actuelle") or e.get("precedente") or (api.adresse_wikimedia(e["image"]) and api.adresse_wikimedia(e["miniature"]))]
            refusees = [e for e in liste if e not in gardees]
            liste = gardees
            nb_refusees = nb_fusion - len(liste)                           # adresses qui ne sont pas des adresses Wikimedia : jamais proposées
            avertissement = ("Attention : " + " et ".join(avertissements) + ". Réessaie dans un instant pour voir toutes les images.") if avertissements else ""
            src = api.sources_images(carte["titre"])
            nom_principale = (cadrage.nom_fichier(principale[0]) or "aucune") if principale and principale[0] else "aucune (non lue)"
            diagnostic = (f"Version {projet.VERSION} · lues dans la page : {src.get('page', 0)} · fichiers de l'article : {src.get('fichiers', 0)} · ignorés : {src.get('nb_ecartees', 0)} · "
                          f"service media-list : +{src.get('media', 0)} · déjà vues : {nb_memoire} · autres cartes : {nb_autres} · image principale de Wikipédia : {nom_principale} · "
                          f"réunies : {nb_candidats} · envoyées : {len(liste)} (refusées par sécurité : {nb_refusees}"
                          + ("" if not refusees else " : " + " ; ".join(f"{e['nom'][:25]} → {str(e['image'])[:70]}" for e in refusees[:3])) + ")"
                          + " · liste : " + " | ".join(f"{e['nom'][:22]}{'' if not (e.get('actuelle') or e.get('principale') or e.get('precedente')) else ' (' + ''.join(k for k, v in (('A', e.get('actuelle')), ('P', e.get('principale')), ('O', e.get('precedente'))) if v) + ')'}" for e in liste[:14]))
            return liste, actuelle, avertissement, diagnostic

        def _carte_pour_stats(self, identifiant):
            """La carte dont on veut relire les statistiques, ou (None, statut, message) : inconnue ou à la corbeille, créée à la main (pas d'article), FULL-ART
            (figée dans le temps), ou d'une autre langue de Wikipédia."""
            try:
                with base.connexion_rapide() as conn:
                    cartes = base.cartes_par_identifiants(conn, [identifiant])
                    corbeille = conn.execute("SELECT supprime_le FROM cartes WHERE id = ?", (identifiant,)).fetchone()
            except sqlite3.Error as erreur:
                return None, 500, f"lecture impossible : {erreur}"
            if not cartes or corbeille is None or corbeille[0] is not None:
                return None, 404, "carte inconnue"
            carte = cartes[0]
            if carte.get("personnalisee"):
                return None, 400, "une carte créée à la main n'a pas d'article Wikipédia : il n'y a pas de statistiques à mettre à jour"
            if carte.get("fullart"):
                return None, 409, "cette carte est full-art : figée dans le temps, ses statistiques ne changent plus"
            if carte.get("langue") != config.LANGUE:
                return None, 400, f"cet article vient de Wikipédia en {carte.get('langue')} : change la langue (réglage Wikipédia) pour mettre ses statistiques à jour"
            return carte, 200, ""

        def _api_carte_stats(self, longueur):
            """Clic sur le pied d'une carte (après confirmation) : relit ses statistiques sur Wikipédia — vues par jour, langues, modifications, liens entrants, taille —
            et recalcule son rang d'après les nouvelles vues (une carte C peut devenir R, ou UR ; une carte légendaire peut descendre : les chiffres font foi, même pour
            une carte tirée dans un GOD PACK). La date de la carte (celle du pied, qui range aussi la collection) devient celle de la mise à jour : la carte repasse parmi
            les dernières arrivées. Si Wikipédia ne donne aucune vue pour le moment, les vues, le rang et la date ne sont pas touchés."""
            demande, erreur_envoyee = self._lire_json(longueur, 500)
            if erreur_envoyee:
                return
            identifiant = demande.get("id") if isinstance(demande, dict) else None
            if isinstance(identifiant, bool) or not isinstance(identifiant, int):
                return self._repondre(400, {"erreur": "carte invalide"})
            carte, statut, message = self._carte_pour_stats(identifiant)
            if carte is None:
                return self._repondre(statut, {"erreur": message})
            maintenant = time.monotonic()
            with _VERROU_MAJ_STATS:
                if maintenant - _DERNIERES_MAJ_STATS.get(identifiant, -1e9) < DELAI_MAJ_STATS:
                    return self._repondre(429, {"erreur": f"les statistiques de cette carte viennent d'être mises à jour : réessaie dans {DELAI_MAJ_STATS:.0f} secondes"})
                _DERNIERES_MAJ_STATS[identifiant] = maintenant
            try:
                page = api.details_par_titres([carte["titre"]]).get(carte["titre"])
                if page is None:
                    return self._repondre(200, {"ok": True, "change": False, "message": "L'article n'existe plus sous ce titre sur Wikipédia."})
                article = api.article_depuis_page(page, datetime.now())
                if config.STATS_CARTES:
                    try:
                        api.ajouter_langues([article])
                    except requests.RequestException:
                        pass                                           # (le nombre de langues reste celui de la carte)
                    with api.en_arriere_plan(config.STATS_PAUSE_PAQUET, None, pause_reseau=config.STATS_PAUSE_PAQUET):
                        api.completer_stats([article])
            except (api.LimiteDebit, api.MaxLag):
                with _VERROU_MAJ_STATS:
                    _DERNIERES_MAJ_STATS.pop(identifiant, None)
                return self._repondre(429, {"erreur": "Wikipédia demande de patienter : réessaie dans quelques minutes"})
            except (requests.RequestException, ValueError, KeyError):
                with _VERROU_MAJ_STATS:
                    _DERNIERES_MAJ_STATS.pop(identifiant, None)
                return self._repondre(502, {"erreur": "Wikipédia ne répond pas pour le moment"})
            vues_lues = bool(article.get("vues_total")) or any(v for v in (page.get("pageviews") or {}).values() if v)
            rang_avant = carte["rarete"]
            rang_apres = rang_avant
            if vues_lues:
                rang_apres = article["rarete"]                    # le rang vient TOUJOURS des vues du moment (il peut monter ou descendre)
            try:
                with base.connexion_rapide() as conn:
                    base.mettre_a_jour_stats_carte(
                        conn, identifiant, vues_total=article["vues_total"] if vues_lues else None, vues_moyenne=article["vues_moyenne"] if vues_lues else None,
                        rarete=rang_apres if vues_lues else None, taille_octets=article.get("taille_octets"), nb_langues=article.get("nb_langues"),
                        nb_revisions=article.get("nb_revisions"), revisions_plafonnees=article.get("revisions_plafonnees"), nb_liens_entrants=article.get("nb_liens_entrants"))
                    nouvelle = base.cartes_par_identifiants(conn, [identifiant])[0]
                    etat = rendu.etat_collection(conn)
            except sqlite3.Error as erreur:
                return self._repondre(500, {"erreur": f"enregistrement impossible : {erreur}"})
            ordre = {code: i for i, code in enumerate(config.CODES)}
            sens = 0 if (rang_avant == rang_apres or rang_avant not in ordre or rang_apres not in ordre) else (1 if ordre[rang_apres] < ordre[rang_avant] else -1)       # 1 : le rang monte
            reponse = {"ok": True, "change": True, "carte": rendu.fragments_cartes([nouvelle]), "etat": etat, "vues_vues": vues_lues, "sens": sens,
                       "rang_avant": rang_avant, "rang_apres": rang_apres, "nom_rang_avant": config.nom_rang(rang_avant), "nom_rang_apres": config.nom_rang(rang_apres),
                       "vues_avant": float(carte["vues_moyenne"]), "vues_apres": float(nouvelle["vues_moyenne"])}
            reponse.update(self._effets_sur_doublons(nouvelle))
            self._repondre(200, reponse)

        def _api_carte_image(self, longueur):
            """Icône ⟳ : liste TOUTES les images de l'article (celle de la carte, l'image principale de Wikipédia, les autres) pour en choisir une, ou
            retirer l'illustration. Rien n'est enregistré ici : le choix se valide à part (/api/cartes/image/choisir, /retirer)."""
            demande, erreur_envoyee = self._lire_json(longueur, 500)
            if erreur_envoyee:
                return
            identifiant = demande.get("id") if isinstance(demande, dict) else None
            if isinstance(identifiant, bool) or not isinstance(identifiant, int):
                return self._repondre(400, {"erreur": "carte invalide"})
            carte, statut, message = self._carte_pour_image(identifiant, perso=True)
            if carte is None:
                return self._repondre(statut, {"erreur": message})
            if carte.get("personnalisee"):                         # carte créée à la main : pas d'article, mais son illustration peut être recadrée
                a_une_image = carte["image"] != "no-image" or carte["miniature"] != "no-image"
                if not a_une_image:
                    return self._repondre(200, {"ok": True, "change": False, "message": "Cette carte n'a pas d'illustration à régler."})
                return self._repondre(200, {"ok": True, "change": False, "candidats": [], "titre": carte["titre"], "actuelle": True, "perso": True,
                                            "avertissement": "", "sources": {}})
            try:
                liste, actuelle, avertissement, diagnostic = self._propositions_image(carte)
            except api.ArticleIntrouvable:
                return self._repondre(200, {"ok": True, "change": False, "message": "L'article n'existe plus sous ce titre."})
            except requests.RequestException:
                return self._repondre(502, {"erreur": "Wikipédia ne répond pas pour le moment"})
            if not liste and actuelle is None:
                return self._repondre(200, {"ok": True, "change": False, "message": "Cet article n'a aucune image."})
            self._repondre(200, {"ok": True, "change": False, "candidats": liste, "titre": carte["titre"], "actuelle": actuelle is not None,
                                 "avertissement": avertissement, "sources": api.sources_images(carte["titre"]), "diagnostic": diagnostic})

        def _api_carte_image_choisir(self, longueur):
            """Choisir, parmi les images de l'article, l'illustration d'une carte (changer l'image d'une carte qui en a déjà une, ou en mettre une
            sur une carte qui n'en a pas). L'adresse doit être l'une de celles que le serveur a lui-même proposées (jamais une adresse envoyée telle
            quelle par le navigateur)."""
            demande, erreur_envoyee = self._lire_json(longueur, 1500)
            if erreur_envoyee:
                return
            identifiant = demande.get("id") if isinstance(demande, dict) else None
            adresse = demande.get("image") if isinstance(demande, dict) else None
            if isinstance(identifiant, bool) or not isinstance(identifiant, int) or not isinstance(adresse, str):
                return self._repondre(400, {"erreur": "demande invalide"})
            carte, statut, message = self._carte_pour_image(identifiant)
            if carte is None:
                return self._repondre(statut, {"erreur": message})
            try:
                liste, actuelle, _, _ = self._propositions_image(carte)
            except api.ArticleIntrouvable:
                return self._repondre(404, {"erreur": "l'article n'existe plus sous ce titre"})
            except requests.RequestException:
                return self._repondre(502, {"erreur": "Wikipédia ne répond pas pour le moment"})
            choisie = next((c for c in liste if c["image"] == adresse), None)
            if choisie is None:
                return self._repondre(400, {"erreur": "cette image ne fait pas partie de celles de l'article"})
            if choisie.get("actuelle"):
                return self._repondre(400, {"erreur": "c'est déjà l'illustration de cette carte"})
            try:
                anime = None
                if choisie["miniature"].split("?", 1)[0].lower().endswith(".gif") or choisie["image"].split("?", 1)[0].lower().endswith(".gif"):
                    try:
                        anime = api.verifier_gifs([choisie["miniature"]]).get(choisie["miniature"])          # un GIF : est-il vraiment animé ?
                    except requests.RequestException:
                        anime = None
                with base.connexion_rapide() as conn:
                    base.mettre_a_jour_image(conn, identifiant, choisie["image"], choisie["miniature"])
                    if anime is not None:
                        base.marquer_gif(conn, identifiant, anime)
                    carte = base.cartes_par_identifiants(conn, [identifiant])[0]
                gifs.reveiller()
            except sqlite3.Error as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, dict({"ok": True, "change": True, "carte": rendu.fragments_cartes([carte])}, **self._effets_sur_doublons(carte)))

        def _effets_sur_doublons(self, carte):
            """Changer l'image ou son cadrage peut faire apparaître ou disparaître un « Doublon » : les bandeaux des AUTRES cartes du même titre déjà
            affichées, le nombre de doublons et les compteurs de la liste des catégories sont renvoyés pour être mis à jour tout de suite."""
            try:
                with base.connexion_rapide() as conn:
                    return {"bandeaux": rendu.bandeaux_meme_titre(conn, [carte["titre"]], [carte["id"]]), "doublons": base.compter_doublons(conn),
                            "compteurs": base.compteurs_categories(conn)}
            except sqlite3.Error:
                return {}

        def _api_carte_image_cadrage(self, longueur):
            """Enregistrer le cadrage (position et agrandissement) de l'illustration d'une carte. Il est gardé pour l'article et le fichier d'image :
            les prochaines cartes identiques (doublons, nouveaux paquets) le reçoivent automatiquement."""
            demande, erreur_envoyee = self._lire_json(longueur, 800)
            if erreur_envoyee:
                return
            identifiant = demande.get("id") if isinstance(demande, dict) else None
            if isinstance(identifiant, bool) or not isinstance(identifiant, int):
                return self._repondre(400, {"erreur": "carte invalide"})
            carte, statut, message = self._carte_pour_image(identifiant, reseau=False, perso=True)
            if carte is None:
                return self._repondre(statut, {"erreur": message})
            if carte["image"] == "no-image" and carte["miniature"] == "no-image":
                return self._repondre(400, {"erreur": "cette carte n'a pas d'illustration à cadrer"})
            if demande.get("ratio") is None:
                return self._repondre(400, {"erreur": "ratio de l'image manquant"})
            try:
                zoom, x, y, ratio = cadrage.valider(demande.get("zoom"), demande.get("x"), demande.get("y"), demande.get("ratio"))
            except ValueError as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            affichee = carte["image"] if carte["image"] != "no-image" else carte["miniature"]
            try:
                with base.connexion_rapide() as conn:
                    base.cadrage_ecrire_carte(conn, identifiant, carte["url"], cadrage.cle_image(affichee), zoom, x, y, ratio)
                    carte = base.cartes_par_identifiants(conn, [identifiant])[0]
            except sqlite3.Error as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, dict({"ok": True, "change": True, "carte": rendu.fragments_cartes([carte])}, **self._effets_sur_doublons(carte)))

        def _api_carte_image_retirer(self, longueur):
            """Enlever l'illustration d'une carte : elle redevient « Sans illustration » ; on pourra en remettre une quand on voudra (icône ⟳)."""
            demande, erreur_envoyee = self._lire_json(longueur, 500)
            if erreur_envoyee:
                return
            identifiant = demande.get("id") if isinstance(demande, dict) else None
            if isinstance(identifiant, bool) or not isinstance(identifiant, int):
                return self._repondre(400, {"erreur": "carte invalide"})
            carte, statut, message = self._carte_pour_image(identifiant)
            if carte is None:
                return self._repondre(statut, {"erreur": message})
            if carte["image"] == "no-image":
                return self._repondre(400, {"erreur": "cette carte n'a pas d'illustration"})
            try:
                with base.connexion_rapide() as conn:
                    base.retirer_image(conn, identifiant)
                    carte = base.cartes_par_identifiants(conn, [identifiant])[0]
            except sqlite3.Error as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, dict({"ok": True, "change": True, "carte": rendu.fragments_cartes([carte])}, **self._effets_sur_doublons(carte)))

        def _api_paquet_retirer(self, longueur):
            """Retire (supprime tout de suite) des cartes du paquet qu'on vient d'ouvrir."""
            demande, erreur_envoyee = self._lire_json(longueur, 2000)
            if erreur_envoyee:
                return
            if not isinstance(demande, dict):
                return self._repondre(400, {"erreur": "demande invalide"})
            try:
                resultat = paquet.retirer_du_paquet(demande.get("ids"))
            except paquet.PaquetInvalide as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"suppression impossible : {erreur}"})
            self._repondre(200, {"ok": True, **resultat})

        def _api_paquet(self):
            """Ouvre un paquet : tire des cartes, les enregistre, renvoie leur HTML."""
            if self._paquet_bloque():
                return
            try:
                resultat = paquet.ouvrir_paquet()
            except paquet.PaquetEnCours as erreur:
                return self._repondre(409, {"erreur": str(erreur)})
            except paquet.PaquetImpossible as erreur:
                return self._repondre(502, {"erreur": str(erreur)})
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"enregistrement impossible : {erreur}"})
            self._repondre(200, {"ok": True, **resultat})

        def _envoyer_image(self, nom):
            """Une image de carte personnalisée (data/images/), lue par le navigateur. Le nom doit être
            exactement <32 caractères hexadécimaux>.<jpg|png|gif|webp> : aucun chemin ne peut sortir
            du dossier. Contenu immuable (le nom est l'empreinte du fichier) donc mis en cache."""
            fichier = images.chemin(nom)
            if fichier is None:
                return self._repondre(404, {"erreur": "image introuvable"})
            try:
                corps = fichier.read_bytes()
            except OSError:
                return self._repondre(404, {"erreur": "image introuvable"})
            self.send_response(200)
            self.send_header("Content-Type", images.type_mime(nom))
            self.send_header("Content-Length", str(len(corps)))
            self.send_header("Cache-Control", "private, max-age=31536000, immutable")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
            self.end_headers()
            self.wfile.write(corps)

        def _api_createur_apercu(self, longueur):
            """L'aperçu d'une carte pendant la saisie : champs invalides remplacés par leur valeur de
            départ, titre non obligatoire. Renvoie le HTML de la carte."""
            demande, erreur_envoyee = self._lire_json(longueur, 40_000)
            if erreur_envoyee:
                return
            carte, erreurs = createur.valider(demande, strict=False)
            if carte is None:
                return self._repondre(400, {"erreur": "; ".join(erreurs)})
            self._repondre(200, {"ok": True, "html": rendu.html_apercu_createur(carte)})

        def _api_createur_charger(self, longueur):
            """Lit une page web (titre, sous-titre, début du contenu, image principale)."""
            demande, erreur_envoyee = self._lire_json(longueur, 5000)
            if erreur_envoyee:
                return
            if not isinstance(demande, dict) or set(demande) != {"url"} or not isinstance(demande["url"], str):
                return self._repondre(400, {"erreur": "demande invalide"})
            try:
                infos = web.charger(demande["url"], int(config.NB_PHRASES), createur.TITRE_MAX,
                                    createur.SOUS_TITRE_MAX, createur.limite_description())
            except (web.AdresseRefusee, ValueError) as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except requests.HTTPError as erreur:
                statut = getattr(erreur.response, "status_code", "?")
                return self._repondre(502, {"erreur": f"le site répond une erreur ({statut})"})
            except requests.RequestException:
                return self._repondre(502, {"erreur": "le site est injoignable ou trop lent"})
            except OSError as erreur:
                return self._repondre(500, {"erreur": f"enregistrement de l'image impossible : {erreur}"})
            self._repondre(200, {"ok": True, **infos})

        def _api_createur_image(self, longueur):
            """Reçoit une image (le fichier lui-même dans le corps de la requête) et la range."""
            if not 0 < longueur <= images.TAILLE_MAX:
                return self._repondre(413 if longueur > images.TAILLE_MAX else 400,
                                      {"erreur": "image vide ou trop lourde (5 Mo au maximum)"})
            try:
                adresse = images.enregistrer(self.rfile.read(longueur))
            except images.ImageRefusee as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except OSError as erreur:
                return self._repondre(500, {"erreur": f"enregistrement impossible : {erreur}"})
            self._repondre(200, {"ok": True, "url": adresse})

        def _api_sauvegardes_liste(self):
            """Les sauvegardes disponibles et les types qu'on peut créer (jeton demandé : liste de fichiers du disque)."""
            if not hmac.compare_digest(self.headers.get("X-Jeton", ""), jeton):
                return self._repondre(403, {"erreur": "jeton invalide"})
            if self._refuser_avance():
                return
            try:
                liste = sauvegardes.lister()
            except OSError as erreur:
                return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
            self._repondre(200, {"ok": True, "sauvegardes": liste,
                                 "types": {code: t["libelle"] for code, t in sauvegardes.TYPES.items()}})

        def _envoyer_sauvegarde(self, demande):
            """Exporte une sauvegarde : le fichier .zip à télécharger. Le jeton est dans l'adresse (?jeton=) car un lien de
            téléchargement ne peut pas envoyer d'en-tête ; le nom doit être celui d'une sauvegarde existante, rien d'autre."""
            if not hmac.compare_digest((demande.get("jeton") or [""])[0], jeton):
                return self._repondre(403, {"erreur": "jeton invalide"})
            try:
                fichier = sauvegardes.chemin((demande.get("nom") or [""])[0])
                taille = fichier.stat().st_size
            except sauvegardes.SauvegardeIntrouvable as erreur:
                return self._repondre(404, {"erreur": str(erreur)})
            except OSError as erreur:
                return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(taille))
            self.send_header("Content-Disposition", f'attachment; filename="{fichier.name}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                with open(fichier, "rb") as source:
                    while True:
                        morceau = source.read(1024 * 1024)
                        if not morceau:
                            break
                        self.wfile.write(morceau)
            except (OSError, ConnectionError):
                pass                                          # le navigateur a interrompu le téléchargement

        def _api_sauvegardes(self, chemin_api, longueur):
            """Créer, importer, restaurer ou supprimer une sauvegarde (voir sauvegardes.py)."""
            action = chemin_api.rsplit("/", 1)[1]
            try:
                if action == "importer":
                    return self._repondre(200, {"ok": True, "sauvegarde": sauvegardes.recevoir(self.rfile, longueur)})
                demande, erreur_envoyee = self._lire_json(longueur, 2000)
                if erreur_envoyee:
                    return
                if not isinstance(demande, dict):
                    return self._repondre(400, {"erreur": "demande invalide"})
                if action == "creer":
                    type_ = demande.get("type")
                    if not isinstance(type_, str) or type_ not in sauvegardes.TYPES:
                        return self._repondre(400, {"erreur": "type de sauvegarde inconnu"})
                    return self._repondre(200, {"ok": True, "sauvegarde": sauvegardes.creer(
                        type_, avec_cle=demande.get("avec_cle") is True)})
                nom = demande.get("nom")
                if action == "restaurer":
                    if demande.get("confirmation") is not True:
                        return self._repondre(400, {"erreur": "confirmation nécessaire"})
                    return self._repondre(200, {"ok": True, "resume": sauvegardes.restaurer(nom)})
                if action == "supprimer":
                    sauvegardes.supprimer(nom)
                    return self._repondre(200, {"ok": True})
                return self._repondre(404, {"erreur": "introuvable"})
            except sauvegardes.SauvegardeInvalide as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except sauvegardes.SauvegardeIntrouvable as erreur:
                return self._repondre(404, {"erreur": str(erreur)})
            except sauvegardes.SauvegardeEnCours as erreur:
                return self._repondre(409, {"erreur": str(erreur)})
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"opération impossible : {erreur}"})

        def _api_booster_image(self, longueur):
            """Reçoit l'image d'un paquet personnalisé (PNG ou JPEG, 5 Mo au plus) : réduite si elle est très grande, rangée
            dans data/images/. Renvoie son adresse et ses proportions ; le choix est enregistré avec la Configuration."""
            if not 0 < longueur <= images.TAILLE_MAX:
                return self._repondre(413 if longueur > images.TAILLE_MAX else 400,
                                      {"erreur": "image vide ou trop lourde (5 Mo au maximum)"})
            try:
                resultat = images.enregistrer_paquet(self.rfile.read(longueur))
            except images.ImageRefusee as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except OSError as erreur:
                return self._repondre(500, {"erreur": f"enregistrement impossible : {erreur}"})
            self._repondre(200, {"ok": True, **resultat})

        def _api_createur_valider(self, longueur):
            """Validation finale : la carte est ajoutée à la collection comme toutes les autres."""
            demande, erreur_envoyee = self._lire_json(longueur, 40_000)
            if erreur_envoyee:
                return
            carte, erreurs = createur.valider(demande, strict=True)
            if carte is None:
                return self._repondre(400, {"erreur": " ; ".join(erreurs), "erreurs": erreurs})
            try:
                with base.connexion_rapide() as conn:
                    identifiant = createur.creer(conn, carte)
                    total = base.compter(conn)
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"enregistrement impossible : {erreur}"})
            self._repondre(200, {"ok": True, "id": identifiant, "total": total,
                                 "message": f"Carte « {carte['titre']} » ajoutée à ta collection."})

        def _envoyer_calque_fullart(self, chemin_url):
            """Un calque PNG du dossier « zuul » ou « gozer » (seulement un fichier de la liste : jamais un chemin libre)."""
            morceaux = chemin_url.split("/")                         # ["", "fullart", genre, "nom.png"]
            if len(morceaux) != 4 or not morceaux[3].lower().endswith(".png"):
                return self._repondre(404, {"erreur": "introuvable"})
            fichier = fullart.chemin(morceaux[2], unquote(morceaux[3])[:-4])
            if fichier is None:
                return self._repondre(404, {"erreur": "introuvable"})
            try:
                octets = fichier.read_bytes()
            except OSError:
                return self._repondre(404, {"erreur": "introuvable"})
            self._repondre(200, octets, "image/png", {"Cache-Control": "private, max-age=120"})

        def _api_fullart(self, chemin, longueur):
            """Full-art d'une carte : aperçu (rien n'est enregistré) ou application, qui est DÉFINITIVE (jamais de retrait ni de modification)."""
            demande, erreur_envoyee = self._lire_json(longueur, 4000)
            if erreur_envoyee:
                return
            if not isinstance(demande, dict) or isinstance(demande.get("id"), bool) or not isinstance(demande.get("id"), int):
                return self._repondre(400, {"erreur": "carte invalide"})
            identifiant = demande["id"]
            try:
                zuul, gozer, effets = fullart.valider(demande.get("zuul") or "", demande.get("gozer") or "", demande.get("effets"))
                with base.connexion_rapide() as conn:
                    cartes = base.cartes_par_identifiants(conn, [identifiant])
                    if not cartes:
                        return self._repondre(404, {"erreur": "carte introuvable"})
                    if chemin == "/api/fullart/appliquer":
                        if not (zuul or gozer or effets):
                            return self._repondre(400, {"erreur": "choisis au moins un calque ou un effet"})
                        if demande.get("confirme") is not True:
                            return self._repondre(400, {"erreur": "l'application d'un full-art doit être confirmée : opération irréversible"})
                        base.fullart_ecrire(conn, identifiant, zuul, gozer, effets)
                        cartes = base.cartes_par_identifiants(conn, [identifiant])
                    else:                                                            # aperçu : on simule, sans rien enregistrer
                        if zuul or gozer or effets:
                            cartes[0]["fullart"] = {"zuul": zuul, "gozer": gozer, "effets": effets}
                        elif demande.get("existant") is not True:
                            cartes[0]["fullart"] = None                              # (sinon : la carte telle qu'elle est, avec son full-art)
                carte_html = rendu.fragments_cartes(cartes)
            except base.DejaFullArt:
                return self._repondre(409, {"erreur": "cette carte est déjà full-art : c'est définitif, elle ne peut plus changer"})
            except ValueError as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, {"ok": True, "html": carte_html})

        def _envoyer_cartes_a_exposer(self, demande):
            """Les cartes à proposer pour un emplacement de vitrine (`?q=` recherche par titre,
            `?page=`) : 24 par page, les plus récentes d'abord."""
            texte = (demande.get("q") or [""])[0]
            if len(texte) > 100 or any(unicodedata.category(c)[0] == "C" for c in texte):
                return self._repondre(400, {"erreur": "recherche invalide"})
            try:
                numero = int((demande.get("page") or ["1"])[0])
            except ValueError:
                return self._repondre(400, {"erreur": "page invalide"})
            codes = set(config.CODES) | {config.CODE_PERSO}
            rangs = [r for r in (demande.get("rangs") or [""])[0].split(",") if r in codes][:12]
            tri = (demande.get("tri") or [""])[0]
            if tri and tri not in base.TRIS_SELECTEUR:
                return self._repondre(400, {"erreur": "tri invalide"})
            try:
                with base.connexion_rapide() as conn:
                    resultat = base.cartes_a_exposer(conn, texte, numero, 24, rangs=rangs, tri=tri, avec_image=(demande.get("avec_image") or [""])[0] == "1")
                    avec_fullart = base.fullart_des_cartes(conn, [c["id"] for c in resultat["cartes"]])
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
            cartes = []
            for c in resultat["cartes"]:
                image = next((a for a in (c["url_miniature"], c["url_image"])
                              if images.adresse_locale_valide(a) or api.adresse_wikimedia(a)), "")
                cartes.append({"id": c["id"], "titre": c["titre"], "rarete": c["rarete"],
                               "symbole": config.symbole(c["rarete"]), "image": image,
                               "description": (c["description"] or "")[:120],
                               "placee": bool(c["placee"]), "fullart": c["id"] in avec_fullart,
                               # contenu sensible (d'après TA liste) : l'image de la vignette est floutée, sauf si tu l'as déjà montrée
                               "flou": bool(sensible.carte_sensible({"titre": c["titre"], "description": c["description"], "intro": c["intro"],
                                                                      "personnalisee": bool(c["personnalisee"])}))
                               and c["url_article"] not in sensible.reveles()})
            self._repondre(200, {"ok": True, "cartes": cartes, "page": resultat["page"],
                                 "pages": resultat["pages"], "total": resultat["total"]})

        def _api_profil_titre(self, longueur):
            """Donne un titre à une vitrine (lettres, chiffres, emoji)."""
            demande, erreur_envoyee = self._lire_json(longueur, 2000)
            if erreur_envoyee:
                return
            if not isinstance(demande, dict) or set(demande) != {"vitrine", "titre"}:
                return self._repondre(400, {"erreur": "demande invalide"})
            vitrine = demande["vitrine"]
            if (isinstance(vitrine, bool) or not isinstance(vitrine, int)
                    or not 1 <= vitrine <= int(config.PROFIL_VITRINES)):
                return self._repondre(400, {"erreur": "cette vitrine n'existe pas"})
            titre, message = profil.nettoyer_titre(demande["titre"])
            if titre is None:
                return self._repondre(400, {"erreur": message})
            try:
                with base.connexion_rapide() as conn:
                    base.definir_titre_vitrine(conn, vitrine, titre)
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, {"ok": True, "titre": titre})

        def _api_profil_carte(self, longueur):
            """Place une carte à un emplacement de vitrine (ou le vide avec carte_id: null). Renvoie
            le HTML des emplacements modifiés : celui-ci, et l'ancien emplacement de la carte."""
            demande, erreur_envoyee = self._lire_json(longueur, 2000)
            if erreur_envoyee:
                return
            if not isinstance(demande, dict) or set(demande) != {"vitrine", "emplacement", "carte_id"}:
                return self._repondre(400, {"erreur": "demande invalide"})
            vitrine, emplacement, carte_id = demande["vitrine"], demande["emplacement"], demande["carte_id"]
            entiers = all(isinstance(x, int) and not isinstance(x, bool) for x in (vitrine, emplacement))
            if not entiers or not (1 <= vitrine <= int(config.PROFIL_VITRINES)
                                   and 1 <= emplacement <= int(config.PROFIL_EMPLACEMENTS)):
                return self._repondre(400, {"erreur": "cet emplacement n'existe pas"})
            if carte_id is not None and (isinstance(carte_id, bool) or not isinstance(carte_id, int)
                                         or carte_id < 1):
                return self._repondre(400, {"erreur": "carte invalide"})
            try:
                with base.connexion_rapide() as conn:
                    if carte_id is None:
                        base.retirer_carte_vitrine(conn, vitrine, emplacement)
                        modifies = [(vitrine, emplacement)]
                    else:
                        modifies = base.placer_carte(conn, vitrine, emplacement, carte_id)
                        if modifies is None:
                            return self._repondre(404, {"erreur": "cette carte n'est plus dans la collection"})
                    cartes = base.cartes_des_vitrines(conn, config.PROFIL_VITRINES,
                                                      config.PROFIL_EMPLACEMENTS)
                    total, exposees = base.compter(conn), base.compter_carte_exposees(conn)
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, {
                "ok": True,
                "emplacements": {f"{v}-{e}": rendu.html_emplacement(v, e, cartes.get((v, e)))
                                 for v, e in modifies
                                 if v <= int(config.PROFIL_VITRINES) and e <= int(config.PROFIL_EMPLACEMENTS)},
                "infos": f"{total} carte{'s' if total > 1 else ''} dans la collection · "
                         f"{exposees} exposée{'s' if exposees > 1 else ''} en vitrine"})

        def _envoyer_stats(self, demande):
            """Pied de carte à jour (statistiques) de cartes déjà affichées : la page l'interroge tant
            que des statistiques manquent. `?ids=1,2,3` (200 au plus). Renvoie
            {"cartes": {id: {"complet": bool, "html": HTML des quatre statistiques}}}."""
            brut = (demande.get("ids") or [""])[0]
            try:
                identifiants = [int(x) for x in brut.split(",") if x.strip()]
            except ValueError:
                return self._repondre(400, {"erreur": "ids invalides"})
            if not 0 < len(identifiants) <= 200 or any(i < 1 for i in identifiants):
                return self._repondre(400, {"erreur": "ids invalides"})
            try:
                with base.connexion_rapide() as conn:
                    cartes = base.stats_de_cartes(conn, identifiants)
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
            self._repondre(200, {"ok": True, "cartes": {
                str(c["id"]): {"complet": rendu.stats_completes(c), "html": rendu.html_stats(c)}
                for c in cartes}})

        def _api_reserve(self, action, longueur):
            """Réserve de cartes : « remplir » demande un remplissage dès que possible (le plafond
            horaire et les pauses de politesse restent appliqués), « vider » jette les cartes
            préparées. Renvoie l'état de la réserve."""
            try:
                if action == "remplir":
                    if not config.RESERVE_ACTIVE:
                        return self._repondre(409, {"erreur": "le pré-chargement est désactivé"})
                    reserve.reveiller(demande=True)
                else:
                    reserve.vider()
                self._repondre(200, {"ok": True, **reserve.etat(), "stats": stats.etat()})
            except (sqlite3.Error, OSError) as erreur:
                self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})

        def _api_paquet_flux(self):
            """Ouvre un paquet comme /api/paquet, mais en envoyant à la page, EN DIRECT, l'avancement
            du tirage (une ligne JSON par événement) : le temps restant calculé d'après les réglages
            (décompte), puis la ligne finale {"type": "fin", "donnees": ...} ou {"type": "erreur"}.
            Si la page se déconnecte, le tirage va tout de même jusqu'au bout (les cartes sont
            enregistrées)."""
            if self._paquet_bloque():
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            etat = {"coupe": False}

            def emettre(evenement):
                if etat["coupe"]:
                    return
                try:
                    self.wfile.write((json.dumps(evenement, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush()
                except OSError:
                    etat["coupe"] = True

            try:
                resultat = paquet.ouvrir_paquet(paquet.Annonceur(emettre))
                emettre({"type": "fin", "donnees": {"ok": True, **resultat}})
            except paquet.PaquetEnCours as erreur:
                emettre({"type": "erreur", "code": 409, "message": str(erreur)})
            except paquet.PaquetImpossible as erreur:
                emettre({"type": "erreur", "code": 502, "message": str(erreur)})
            except (sqlite3.Error, OSError) as erreur:
                emettre({"type": "erreur", "code": 500,
                         "message": f"enregistrement impossible : {erreur}"})

        def _lire_json(self, longueur, maximum):
            """Lit le corps JSON d'une requête : (données, None) ou (None, réponse d'erreur envoyée)."""
            if not 0 < longueur <= maximum:
                self._repondre(400, {"erreur": "corps invalide"})
                return None, True
            try:
                self._corps_json = json.loads(self.rfile.read(longueur).decode("utf-8"))
                return self._corps_json, False
            except (ValueError, UnicodeDecodeError):
                self._repondre(400, {"erreur": "JSON invalide"})
                return None, True

        def _envoyer_photo(self, apercu=False):
            """La photo de profil (profile.<extension> du dossier profil/) ou l'image mise de côté pendant le choix. Jamais d'autre fichier ; un SVG ouvert directement ne
            peut exécuter aucun script."""
            fichier = photo.trouver_apercu() if apercu else photo.trouver()
            if fichier is None:
                return self._repondre(404, {"erreur": "aucune photo"})
            try:
                donnees = fichier.read_bytes()
            except OSError:
                return self._repondre(404, {"erreur": "photo illisible"})
            self._repondre(200, donnees, photo.type_mime(fichier), {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})

        def _api_photo(self, chemin, longueur):
            """La photo de profil : téléverser une image (ou prendre celle d'une carte), l'enregistrer avec son positionnement, la repositionner, la supprimer."""
            action = chemin.rsplit("/", 1)[-1]
            if action == "televerser":
                if not 0 < longueur <= photo.TAILLE_MAX:
                    return self._repondre(413 if longueur > photo.TAILLE_MAX else 400, {"erreur": f"image vide ou trop lourde ({photo.TAILLE_MAX // 1048576} Mo au maximum)"})
                try:
                    infos = photo.mettre_de_cote(self.rfile.read(longueur))
                except photo.PhotoRefusee as erreur:
                    return self._repondre(400, {"erreur": str(erreur)})
                except OSError as erreur:
                    return self._repondre(500, {"erreur": f"enregistrement impossible : {erreur}"})
                return self._repondre(200, {"ok": True, "apercu": {**infos, "url": f"/profil-photo/apercu?v={infos['version']}"}})
            if action == "partage":                      # la version partagée avec le Hall : le carré visible dans le cercle, fabriqué par le navigateur
                if not 0 < longueur <= photo.PARTAGE_MAX:
                    return self._repondre(413 if longueur > photo.PARTAGE_MAX else 400, {"erreur": f"image vide ou trop lourde ({photo.PARTAGE_MAX // 1024} Ko au maximum)"})
                try:
                    with base.connexion_rapide() as conn:
                        photo.enregistrer_partage(conn, self.rfile.read(longueur))
                except photo.PhotoRefusee as erreur:
                    return self._repondre(400, {"erreur": str(erreur)})
                except (sqlite3.Error, OSError) as erreur:
                    return self._repondre(500, {"erreur": f"enregistrement impossible : {erreur}"})
                return self._repondre(200, {"ok": True})
            demande = {}
            if longueur > 0:
                demande, erreur_envoyee = self._lire_json(longueur, 2000)
                if erreur_envoyee:
                    return
            if not isinstance(demande, dict):
                return self._repondre(400, {"erreur": "demande invalide"})
            if action == "carte":
                identifiant = demande.get("id")
                if isinstance(identifiant, bool) or not isinstance(identifiant, int):
                    return self._repondre(400, {"erreur": "carte invalide"})
                try:
                    with base.connexion_rapide() as conn:
                        cartes = base.cartes_par_identifiants(conn, [identifiant])
                        corbeille = conn.execute("SELECT supprime_le FROM cartes WHERE id = ?", (identifiant,)).fetchone()
                except sqlite3.Error as erreur:
                    return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
                if not cartes or corbeille is None or corbeille[0] is not None:
                    return self._repondre(404, {"erreur": "carte inconnue"})
                try:
                    infos = photo.mettre_de_cote(photo.octets_de_carte(cartes[0]))
                except photo.PhotoRefusee as erreur:
                    return self._repondre(400, {"erreur": str(erreur)})
                except OSError as erreur:
                    return self._repondre(500, {"erreur": f"enregistrement impossible : {erreur}"})
                journal.logiciel(f"Photo de profil : image de la carte « {cartes[0]['titre'][:50]} » téléchargée dans le dossier profil/ (en attente d'enregistrement)")
                return self._repondre(200, {"ok": True, "titre": cartes[0]["titre"], "apercu": {**infos, "url": f"/profil-photo/apercu?v={infos['version']}"}})
            try:
                with base.connexion_rapide() as conn:
                    if action == "enregistrer":
                        etat = photo.enregistrer(conn, demande.get("zoom"), demande.get("x"), demande.get("y"), demande.get("ratio"))
                    elif action == "recadrer":
                        etat = photo.recadrer(conn, demande.get("zoom"), demande.get("x"), demande.get("y"), demande.get("ratio"))
                    elif action == "supprimer":
                        etat = photo.supprimer(conn)
                    elif action == "abandonner":
                        photo.abandonner()
                        etat = photo.reglages(conn)
                    else:
                        return self._repondre(404, {"erreur": "introuvable"})
                    html_avatar = photo.html_avatar(conn)
            except photo.PhotoRefusee as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"enregistrement impossible : {erreur}"})
            self._repondre(200, {"ok": True, **etat, "html": html_avatar})

        def _api_journal(self, chemin, longueur):
            """Journal d'activité (Configuration > Système) : état, lecture, ouverture dans le Bloc-notes, suppression."""
            demande = {}
            if longueur > 0:
                demande, erreur_envoyee = self._lire_json(longueur, 2000)
                if erreur_envoyee:
                    return
            if not isinstance(demande, dict):
                return self._repondre(400, {"erreur": "demande invalide"})
            statut, donnees = journal.ROUTES[chemin](demande)
            self._repondre(statut, donnees)

        def _api_lot(self, chemin, longueur):
            """Importation de cartes en lot depuis un fichier .txt (analyse, démarrage, progression, interruption, reprise)."""
            demande = {}
            if longueur > 0:
                demande, erreur_envoyee = self._lire_json(longueur, 7_000_000)
                if erreur_envoyee:
                    return
            if not isinstance(demande, dict):
                return self._repondre(400, {"erreur": "demande invalide"})
            try:
                statut, donnees = lot.ROUTES[chemin](demande)
            except lot.LotImpossible as erreur:
                return self._repondre(409, {"erreur": str(erreur)})
            self._repondre(statut, donnees)

        def _api_hall(self, chemin, longueur):
            """Actions du Hall des collections (ton pseudo, ton partage, la visite d'un collectionneur...)."""
            demande = {}
            if longueur > 0:
                demande, erreur_envoyee = self._lire_json(longueur, 20000)
                if erreur_envoyee:
                    return
            if not isinstance(demande, dict):
                return self._repondre(400, {"erreur": "demande invalide"})
            try:
                statut, donnees = hall_api.ROUTES[chemin](demande)
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"erreur interne : {erreur}"})
            self._repondre(statut, donnees)

        def _page_hall(self, chemin_url, url):
            """Pages du Hall (GET) : liste, profil ou collection d'un collectionneur, et relais d'image."""
            params = {k: v[0] for k, v in parse_qs(url.query, max_num_fields=8).items()}
            try:
                if chemin_url == "/hall":
                    page = rendu.page_hall(jeton)
                elif chemin_url in ("/hall/image", "/hall/fullart", "/hall/photo"):
                    if chemin_url == "/hall/fullart":
                        statut, octets, type_mime = hall_api.fullart_calque(params.get("pair", ""), params.get("genre", ""), params.get("nom", ""))
                    elif chemin_url == "/hall/photo":
                        statut, octets, type_mime = hall_api.photo(params.get("pair", ""), params.get("v", ""))
                    else:
                        statut, octets, type_mime = hall_api.image(params.get("pair", ""), params.get("nom", ""))
                    if statut != 200:
                        return self._repondre(statut, {"erreur": "image indisponible"})
                    self.send_response(200)
                    self.send_header("Content-Type", type_mime)
                    self.send_header("Content-Length", str(len(octets)))
                    self.send_header("Cache-Control", "private, max-age=3600")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
                    self.end_headers()
                    self.wfile.write(octets)
                    return
                else:
                    pair = params.get("pair", "")
                    try:
                        p2p_identite.pub_depuis_id(pair)
                        page = rendu.page_visite(chemin_url.rsplit("/", 1)[1], pair, jeton)
                    except (ValueError, LookupError):
                        return self._repondre(404, {"erreur": "collectionneur inconnu"})
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
            return self._repondre(200, page.encode("utf-8"), "text/html; charset=utf-8")

        def _api_configuration(self, longueur):
            """Enregistre la configuration envoyée par la page Configuration : réglages et
            catégories (tout est vérifié avant d'écrire quoi que ce soit), ou la réinitialise."""
            demande, erreur_envoyee = self._lire_json(longueur, 400000)
            if erreur_envoyee:
                return
            if not isinstance(demande, dict):
                return self._repondre(400, {"erreur": "demande invalide"})
            valeurs = demande.get("valeurs")
            if not self._avance_visible():                       # réglages avancés : jamais modifiables depuis l'extérieur
                avances = [n for n in (valeurs or {}) if n in parametres.PARAMETRES
                           and parametres.PARAMETRES[n].groupe in parametres.GROUPES_AVANCES] if isinstance(valeurs, dict) else []
                if avances or demande.get("reinitialiser") is True:
                    return self._repondre(403, {"erreur": "réglages avancés : réservés à cet ordinateur et au réseau local"})
            liste_categories = demande.get("categories")
            supprimees = demande.get("categories_supprimees", [])
            reinitialiser = demande.get("reinitialiser") is True
            if valeurs is not None and not isinstance(valeurs, dict):
                return self._repondre(400, {"erreur": "réglages invalides"})
            if (not reinitialiser and not valeurs and liste_categories is None and not supprimees):
                return self._repondre(400, {"erreur": "aucune valeur reçue"})

            a_relancer = [nom for nom, p in parametres.PARAMETRES.items() if p.redemarrage]
            avant = {nom: copy.deepcopy(getattr(config, nom)) for nom in a_relancer}
            try:
                with base.connexion_rapide() as conn:
                    if reinitialiser:
                        parametres.reinitialiser(conn)
                        self._repondre(200, {"ok": True, "redemarrage": []})
                        return
                    # 1) tout vérifier, sans rien écrire
                    erreurs, erreurs_categories = {}, {}
                    decodees = {}
                    if valeurs:
                        try:
                            decodees = parametres.preparer(valeurs)
                        except parametres.ValeursInvalides as erreur:
                            erreurs = erreur.erreurs
                    propres = None
                    if liste_categories is not None or supprimees:
                        existantes = {c["id"]: c for c in base.lister_categories(conn)}
                        propres, erreurs_categories = cat.verifier_categories(
                            liste_categories if liste_categories is not None else [],
                            existantes, supprimees)
                    if erreurs or erreurs_categories:
                        return self._repondre(400, {
                            "erreur": "certaines valeurs sont refusées",
                            "erreurs": erreurs, "erreurs_categories": erreurs_categories})
                    # 2) tout est valide : on écrit
                    if decodees:
                        parametres.ecrire_decodees(conn, decodees)
                    if propres is not None:
                        base.enregistrer_categories(conn, propres, supprimees)
            except sqlite3.Error as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            changes = [parametres.PARAMETRES[nom].libelle for nom in a_relancer
                       if getattr(config, nom) != avant[nom]]
            if valeurs and any(nom.startswith("P2P_") for nom in valeurs):
                p2p_service.SERVICE.appliquer_reglages()        # réglages du partage : le nœud suit tout de suite
            self._repondre(200, {"ok": True, "redemarrage": changes})

        def _api_assigner(self, longueur):
            """Classe (ou retire) des cartes sélectionnées dans des catégories. Renvoie les
            bandeaux à jour de ces cartes."""
            demande, erreur_envoyee = self._lire_json(longueur, 100000)
            if erreur_envoyee:
                return

            def identifiants(cle, maximum):
                valeurs = demande.get(cle) if isinstance(demande, dict) else None
                if (not isinstance(valeurs, list) or not 0 < len(valeurs) <= maximum
                        or any(not isinstance(v, int) or isinstance(v, bool) or v < 1
                               for v in valeurs)):
                    return None
                return sorted(set(valeurs))

            cartes = identifiants("ids", 500)
            categories = identifiants("categories", cat.NB_CATEGORIES_MAX)
            action = demande.get("action") if isinstance(demande, dict) else None
            if cartes is None or categories is None or action not in ("ajouter", "retirer"):
                return self._repondre(400, {"erreur": "demande invalide"})
            try:
                with base.connexion_rapide() as conn:
                    if action == "ajouter":
                        liens = base.assigner_categories(conn, cartes, categories)
                    else:
                        liens = base.retirer_categories(conn, cartes, categories)
                    bandeaux = {str(c["id"]): cat.html_bandeaux(c["categories"])
                                for c in base.cartes_par_identifiants(conn, cartes)}
            except sqlite3.Error as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, {"ok": True, "liens": liens, "bandeaux": bandeaux})

        def _api_corbeille(self, action, longueur):
            """Corbeille : « mettre » des cartes à la corbeille (suppression réversible),
            « restaurer » des cartes (ou toute la corbeille avec {"tout": true}) ou les
            « supprimer » définitivement (seules des cartes DÉJÀ dans la corbeille peuvent l'être)."""
            demande, erreur_envoyee = self._lire_json(longueur, 100000)
            if erreur_envoyee:
                return
            if not isinstance(demande, dict):
                return self._repondre(400, {"erreur": "demande invalide"})
            valeurs = demande.get("ids")
            tout = demande.get("tout") is True and action != "mettre"
            if tout and valeurs is not None:
                return self._repondre(400, {"erreur": "demande invalide"})
            identifiants = None
            if not tout:
                if (not isinstance(valeurs, list) or not 0 < len(valeurs) <= 500
                        or any(not isinstance(v, int) or isinstance(v, bool) or v < 1
                               for v in valeurs)):
                    return self._repondre(400, {"erreur": "demande invalide"})
                identifiants = sorted(set(valeurs))
            page = demande.get("page", 1)
            if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                page = 1
            try:
                with base.connexion_rapide() as conn:
                    reponse = {"ok": True}
                    if action == "mettre":
                        titres = [c["titre"] for c in base.cartes_par_identifiants(conn, identifiants)]
                        reponse["deplacees"] = base.mettre_a_la_corbeille(conn, identifiants)
                        reponse.update(rendu.etat_collection(conn, page))
                        reponse["bandeaux"] = rendu.bandeaux_meme_titre(conn, titres)
                    elif action == "restaurer":
                        reponse["restaurees"] = base.restaurer_cartes(conn, identifiants)
                    else:
                        reponse["supprimees"] = base.supprimer_definitivement(conn, identifiants)
                    reponse["corbeille"] = base.compter_corbeille(conn)
            except sqlite3.Error as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, reponse)

        def _api_recherche(self, longueur):
            """Cherche des articles sur Wikipédia et renvoie les cartes trouvées (HTML)."""
            demande, erreur_envoyee = self._lire_json(longueur, 2000)
            if erreur_envoyee:
                return
            try:
                articles = recherche.chercher(demande.get("q") if isinstance(demande, dict) else None,
                                              demande.get("decalage", 0) if isinstance(demande, dict) else 0)
            except recherche.RechercheInvalide as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except recherche.RechercheTropRapide as erreur:
                return self._repondre(429, {"erreur": str(erreur)})
            except recherche.RechercheImpossible as erreur:
                return self._repondre(502, {"erreur": str(erreur)})
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"lecture impossible : {erreur}"})
            limite = int(config.RECHERCHE_MAX_RESULTATS)
            masques = recherche.MASQUES["nombre"]                       # écartés par les champs de recherche choisis
            self._repondre(200, {"ok": True, "nombre": len(articles), "html": rendu.html_resultats(articles),
                                 "limite": limite,                     # taille d'un lot
                                 "masques": masques,
                                 "suite": len(articles) + masques >= limite})    # un lot complet : il y a peut-être d'autres résultats

        def _api_rapatrier(self, longueur):
            """Enregistre dans la collection les cartes choisies (palier et catégories
            automatiques, comme pour un paquet)."""
            demande, erreur_envoyee = self._lire_json(longueur, 20000)
            if erreur_envoyee:
                return
            try:
                resultat = recherche.rapatrier(demande.get("titres") if isinstance(demande, dict)
                                               else None)
            except recherche.RechercheInvalide as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except recherche.RechercheTropRapide as erreur:
                return self._repondre(429, {"erreur": str(erreur)})
            except recherche.RechercheImpossible as erreur:
                return self._repondre(502, {"erreur": str(erreur)})
            except (sqlite3.Error, OSError) as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            resultat["ok"] = True
            self._repondre(200, resultat)

        def _api_reclasser(self, longueur):
            """Classe dans une catégorie les cartes existantes qui correspondent à ses meta."""
            demande, erreur_envoyee = self._lire_json(longueur, 2000)
            if erreur_envoyee:
                return
            identifiant = demande.get("id") if isinstance(demande, dict) else None
            if not isinstance(identifiant, int) or isinstance(identifiant, bool) or identifiant < 1:
                return self._repondre(400, {"erreur": "demande invalide"})
            try:
                with base.connexion_rapide() as conn:
                    existe = any(c["id"] == identifiant for c in base.lister_categories(conn))
                    ajoutees = base.classer_cartes_existantes(conn, identifiant) if existe else 0
            except sqlite3.Error as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            if not existe:
                return self._repondre(404, {"erreur": "catégorie inconnue"})
            self._repondre(200, {"ok": True, "ajoutees": ajoutees})

        def do_POST(self):
            url = urlsplit(self.path)
            if url.path == "/connexion":
                if not self._hote_autorise():
                    return self._repondre(403, {"erreur": "hôte non autorisé"})
                return self._connexion()
            if url.path not in ("/export", "/export-document", "/api/favori", "/api/preferences",
                                "/api/paquet", "/api/paquet/flux", "/api/paquet/retirer", "/api/cartes/image", "/api/cartes/image/choisir", "/api/cartes/image/retirer", "/api/cartes/image/cadrage", "/api/flou", "/api/fullart/apercu",
                            "/api/fullart/appliquer", "/api/configuration", "/api/categories/assigner",
                                "/api/categories/reclasser", "/api/recherche",
                                "/api/recherche/importer", "/api/corbeille/mettre",
                                "/api/corbeille/restaurer", "/api/corbeille/supprimer",
                                "/api/reserve/remplir", "/api/reserve/vider",
                                "/api/profil/titre", "/api/profil/carte", "/api/createur/apercu",
                                "/api/createur/charger", "/api/createur/image",
                                "/api/createur/valider", "/api/booster/image", "/api/sauvegardes/creer",
                                "/api/sauvegardes/importer", "/api/sauvegardes/restaurer",
                                "/api/sauvegardes/supprimer", "/api/sons/televerser",
                                "/api/sons/supprimer", "/api/cartes/stats", "/api/profil/photo/televerser", "/api/profil/photo/carte",
                                "/api/profil/photo/enregistrer", "/api/profil/photo/recadrer", "/api/profil/photo/supprimer", "/api/profil/photo/partage",
                                "/api/profil/photo/abandonner") + tuple(hall_api.ROUTES) + tuple(lot.ROUTES) + tuple(journal.ROUTES):
                return self._repondre(404, {"erreur": "introuvable"})
            if not self._hote_autorise():
                return self._repondre(403, {"erreur": "hôte non autorisé"})
            if not self._acces_autorise():
                return
            if not hmac.compare_digest(self.headers.get("X-Jeton", ""), jeton):
                return self._repondre(403, {"erreur": "jeton invalide"})

            try:
                longueur = int(self.headers.get("Content-Length", ""))
            except ValueError:
                longueur = 0
            if lot.actif() and url.path in ROUTES_RESEAU:            # pendant une importation en lot, tout ce qui parlerait à Wikipédia est refusé
                return self._repondre(409, {"erreur": "Une importation de cartes en lot est en cours : patiente jusqu'à sa fin (ou interromps-la)."})
            if url.path in lot.ROUTES:
                return self._api_lot(url.path, longueur)
            if url.path == "/api/cartes/stats":
                return self._api_carte_stats(longueur)
            if url.path in journal.ROUTES:
                return self._api_journal(url.path, longueur)
            if url.path.startswith("/api/profil/photo/"):
                return self._api_photo(url.path, longueur)
            if url.path == "/api/favori":
                return self._api_favori(url)
            if url.path == "/api/preferences":
                return self._api_preferences(longueur)
            if url.path == "/api/paquet":
                return self._api_paquet()
            if url.path == "/api/paquet/retirer":
                return self._api_paquet_retirer(longueur)
            if url.path == "/api/cartes/image":
                return self._api_carte_image(longueur)
            if url.path == "/api/cartes/image/choisir":
                return self._api_carte_image_choisir(longueur)
            if url.path == "/api/cartes/image/retirer":
                return self._api_carte_image_retirer(longueur)
            if url.path == "/api/cartes/image/cadrage":
                return self._api_carte_image_cadrage(longueur)
            if url.path == "/api/flou":
                return self._api_flou(longueur)
            if url.path.startswith("/api/fullart/"):
                return self._api_fullart(url.path, longueur)
            if url.path == "/api/paquet/flux":
                return self._api_paquet_flux()
            if url.path == "/api/createur/apercu":
                return self._api_createur_apercu(longueur)
            if url.path == "/api/createur/charger":
                return self._api_createur_charger(longueur)
            if url.path == "/api/createur/image":
                return self._api_createur_image(longueur)
            if url.path == "/api/booster/image":
                return self._api_booster_image(longueur)
            if url.path in ("/api/sons/televerser", "/api/sons/supprimer"):
                return self._api_sons(url, longueur)
            if (url.path.startswith("/api/sauvegardes/") or url.path in ("/api/reserve/remplir", "/api/reserve/vider")) \
                    and self._refuser_avance():
                return
            if url.path.startswith("/api/sauvegardes/"):
                return self._api_sauvegardes(url.path, longueur)
            if url.path == "/api/createur/valider":
                return self._api_createur_valider(longueur)
            if url.path == "/api/profil/titre":
                return self._api_profil_titre(longueur)
            if url.path == "/api/profil/carte":
                return self._api_profil_carte(longueur)
            if url.path == "/api/reserve/remplir":
                return self._api_reserve("remplir", longueur)
            if url.path == "/api/reserve/vider":
                return self._api_reserve("vider", longueur)
            if url.path == "/api/configuration":
                return self._api_configuration(longueur)
            if url.path == "/api/categories/assigner":
                return self._api_assigner(longueur)
            if url.path == "/api/categories/reclasser":
                return self._api_reclasser(longueur)
            if url.path == "/api/corbeille/mettre":
                return self._api_corbeille("mettre", longueur)
            if url.path == "/api/corbeille/restaurer":
                return self._api_corbeille("restaurer", longueur)
            if url.path == "/api/corbeille/supprimer":
                return self._api_corbeille("supprimer", longueur)
            if url.path in hall_api.ROUTES:
                return self._api_hall(url.path, longueur)
            if url.path == "/api/recherche":
                return self._api_recherche(longueur)
            if url.path == "/api/recherche/importer":
                return self._api_rapatrier(longueur)
            if longueur <= 0:
                return self._repondre(400, {"erreur": "corps vide"})
            document = url.path == "/export-document"
            maximum = export.TAILLE_MAX_DOCUMENT if document else export.TAILLE_MAX
            if longueur > maximum:
                return self._repondre(413, {"erreur": "image trop volumineuse"})

            donnees = self.rfile.read(longueur)
            params = parse_qs(url.query)
            code = params.get("rarete", [""])[0]
            fichier = params.get("fichier", [""])[0]
            try:
                if document:
                    chemin = export.enregistrer_document(
                        params.get("format", [""])[0], code, fichier, donnees)
                else:
                    chemin = export.enregistrer(code, fichier, donnees)
            except ValueError as erreur:
                return self._repondre(400, {"erreur": str(erreur)})
            except OSError as erreur:
                return self._repondre(500, {"erreur": f"écriture impossible : {erreur}"})
            self._repondre(200, {"fichier": _chemin_affichable(chemin)})

    for essai in range(10 if port_depart else 1):
        try:
            serveur_http = _ServeurHTTP((acces.hote_d_ecoute(), port_depart + essai), Gestionnaire)
            acces.PORT["valeur"] = serveur_http.server_address[1]
            return serveur_http
        except OSError:
            continue
    raise OSError("aucun port libre pour le serveur local")


def servir(jeton):
    """Lance le serveur et ouvre la page. Bloque jusqu'à Ctrl+C."""
    serveur = creer_serveur(jeton)
    url = f"http://{HOTE}:{serveur.server_address[1]}/"
    print(f"\nServeur local : {url}   (Ctrl+C pour arrêter)")
    if acces.mode_reseau():
        port_reel = serveur.server_address[1]
        print("ACCÈS RÉSEAU ACTIVÉ : le programme est un serveur, utilisable depuis tout appareil qui peut l'atteindre"
              + (" (code d'accès demandé)." if acces.exige_code() else ", sans mot de passe."))
        for ip in acces.adresses_locales():
            print(f"   à taper sur un autre appareil du réseau : http://{ip}:{port_reel}/")

        def _verifier_pare_feu():
            ko = [ip for ip, ok_ in acces.tester_adresses(port_reel) if not ok_]
            if ko:
                print(f"   ⚠ Ces adresses ne répondent pas ({', '.join(ko)}) : le pare-feu bloque probablement le port {port_reel}.")
                print("     Windows : accepte la fenêtre « Autoriser l'accès » (réseaux privés), ou dans une invite de commandes "
                      "ADMINISTRATEUR :")
                print("     " + acces.commande_pare_feu(port_reel))
        threading.Thread(target=_verifier_pare_feu, daemon=True).start()
        print("   Tunnel (ngrok, Cloudflare...) : pointe-le vers http://127.0.0.1:%d : ça marche tel quel." % port_reel)
    print("Ouvre des paquets de cartes depuis la page « Paquets » (page de démarrage) ; réglages dans « Configuration ».")
    print(f"Les cartes exportées (disquette, PDF, Word) vont dans : {config.DOSSIER_EXPORT}")
    if config.OUVRIR_NAVIGATEUR:
        navigateur.ouvrir(url + "paquets")                  # la page de démarrage : l'ouverture des paquets
    if config.RESERVE_ACTIVE:
        print(f"Réserve de cartes : pré-chargement poli en arrière-plan "
              f"(cible {reserve.cible()} cartes, démarrage dans {reserve.DELAI_DEMARRAGE} s).")
    try:
        with base.connexion_rapide() as conn:
            images.purger_orphelines(conn)       # images téléversées pour une carte jamais validée
    except (sqlite3.Error, OSError):
        pass
    journal.systeme(f"Serveur local prêt : {url}")
    photo.purger_apercu_ancien()        # une image mise de côté pour la photo de profil et jamais enregistrée
    lot.initialiser()                   # une importation en lot interrompue par la fermeture du programme peut être reprise
    reserve.demarrer()                  # le fil de fond ne travaille que si RESERVE_ACTIVE
    stats.demarrer()                    # statistiques des cartes (si STATS_CARTES)
    gifs.demarrer()                     # vérification des GIF réellement animés (catégorie « Animée »)
    def demarrer_partage():
        if config.P2P_TRANSPORT == "tor" and config.P2P_TOR_AUTO:
            try:
                if not p2p_tor.detecter()["controle"]:
                    print("Partage : lancement de Tor…")
                p2p_tor.lancer()
            except (p2p_tor.TorIntrouvable, p2p_tor.TorEchec) as erreur:
                print(f"Partage : Tor n'a pas pu être lancé automatiquement : {erreur}")
        if config.P2P_ACTIF and p2p_service.SERVICE.demarrer():
            print("Partage : ton nœud démarre (Hall des collections).")

    if config.P2P_ACTIF or (config.P2P_TRANSPORT == "tor" and config.P2P_TOR_AUTO):
        threading.Thread(target=demarrer_partage, name="partage-demarrage", daemon=True).start()
    def arret_complet():
        """Appelé aussi quand la fenêtre de commandes est fermée par sa croix : Tor lancé par le programme s'arrête avant que Windows coupe le programme."""
        journal.systeme("Fermeture du programme (Ctrl+C, croix de la fenêtre de commandes ou signal)")
        lot.arreter()                         # l'importation en lot s'arrête proprement (reprenable au prochain lancement)
        p2p_tor.arreter(2)                    # d'abord Tor : c'est lui qui resterait lancé
        p2p_service.SERVICE.arreter()
    fermeture.installer(arret_complet)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nServeur arrêté.")
    finally:
        p2p_service.SERVICE.arreter()
        p2p_tor.arreter()                     # seulement le Tor lancé par ce programme
        reserve.arreter()
        stats.arreter()
        gifs.arreter()
        serveur.server_close()
