"""Identité pair à pair : une paire de clés Ed25519, un identifiant, un pseudo et des fiches signées.

Principes (aucune inscription, aucun e-mail, aucun mot de passe) :
- Ton IDENTITÉ est une paire de clés Ed25519 créée sur ta machine (fichier data/identite_p2p.key, droits 600,
  jamais dans la base ni dans les sauvegardes). Ton IDENTIFIANT PAIR est ta clé publique (52 caractères en
  base32) : il ne dépend de personne, ne peut pas être volé ni usurpé sans ta clé secrète, et il se vérifie
  tout seul. Avec Tor, la même clé donne ton adresse « .onion » : se connecter à cette adresse prouve que
  l'on parle au propriétaire de la clé.
- Ta FICHE (pseudo, nom de collection, nombre de cartes, pastilles P et C, adresse) est signée avec ta clé :
  personne ne peut la modifier ni en fabriquer une à ton nom, et les nœuds qui se la passent de proche en
  proche (« gossip ») vérifient chaque signature avant de la garder.
- Le PSEUDO est unique « au mieux » : un annuaire décentralisé n'a pas d'autorité pour l'attribuer. Règle
  déterministe : à pseudo équivalent, la fiche qui l'a revendiqué EN PREMIER (puis l'identifiant le plus
  petit) le garde ; les autres sont signalées. Chaque pseudo est de plus toujours affiché avec un court
  repère tiré de la clé (« Alice·K3QZ »), qui, lui, ne peut pas être imité.
"""

import base64
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

from . import config

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    DISPONIBLE = True
except ImportError:                                           # pragma: no cover - bibliothèque absente
    DISPONIBLE = False

VERSION_FICHE = 1
PSEUDO_MIN, PSEUDO_MAX = 3, 24
COLLECTION_MAX = 60
AGE_MAX_FICHE = 60 * 86400          # une fiche plus vieille de 60 jours est considérée comme périmée
AVANCE_MAX = 3600                   # une fiche datée de plus d'une heure dans le futur est refusée
TRANSPORTS = ("tor", "direct", "local")
_ID = re.compile(r"[a-z2-7]{52}")


class P2PIndisponible(RuntimeError):
    """La bibliothèque « cryptography » n'est pas installée."""


class IdentiteIllisible(RuntimeError):
    """Le fichier de clé existe mais n'est pas lisible : on ne l'écrase JAMAIS en silence."""


class FicheInvalide(ValueError):
    """Une fiche reçue n'est pas acceptable (signature, forme, valeurs)."""


def _exiger():
    if not DISPONIBLE:
        raise P2PIndisponible("le partage demande la bibliothèque « cryptography » : pip install cryptography")


# ------------------------------------------------------------------------------ identifiants

def b32(octets):
    return base64.b32encode(octets).decode("ascii").lower().rstrip("=")


def id_depuis_pub(pub):
    """Identifiant pair : la clé publique (32 octets) en base32 minuscule, 52 caractères."""
    if not (isinstance(pub, (bytes, bytearray)) and len(pub) == 32):
        raise ValueError("clé publique invalide")
    return b32(bytes(pub))


def pub_depuis_id(identifiant):
    """La clé publique (32 octets) d'un identifiant pair, ou ValueError s'il n'est pas canonique."""
    if not (isinstance(identifiant, str) and _ID.fullmatch(identifiant)):
        raise ValueError("identifiant pair invalide")
    pub = base64.b32decode(identifiant.upper() + "====")
    if len(pub) != 32 or id_depuis_pub(pub) != identifiant:
        raise ValueError("identifiant pair non canonique")
    return pub


def adresse_onion(pub):
    """L'adresse « .onion » (version 3) dérivée de la clé publique : sans autre information, on sait où
    joindre ce pair via Tor, et seul le propriétaire de la clé peut y répondre."""
    version = b"\x03"
    somme = hashlib.sha3_256(b".onion checksum" + bytes(pub) + version).digest()[:2]
    return b32(bytes(pub) + somme + version) + ".onion"


def adresse_onion_de(identifiant):
    return adresse_onion(pub_depuis_id(identifiant))


def repere(identifiant):
    """Court repère visuel unique d'un pair (4 caractères de sa clé) : « K3QZ »."""
    return identifiant[:4].upper()


def etiquette(pseudo, identifiant):
    """« Alice·K3QZ » : le pseudo et le repère de la clé."""
    return f"{pseudo}·{repere(identifiant)}" if pseudo else f"({repere(identifiant)})"


def cle_etendue_tor(graine):
    """Clé secrète « étendue » de 64 octets que Tor attend pour un service oignon v3 (ED25519-V3), calculée
    depuis la graine : le service oignon obtenu a EXACTEMENT l'adresse dérivée de la clé publique."""
    h = hashlib.sha512(graine).digest()
    a = bytearray(h[:32])
    a[0] &= 248
    a[31] &= 127
    a[31] |= 64
    return bytes(a) + h[32:]


# ----------------------------------------------------------------------------- l'identité locale

class Identite:
    """La paire de clés de ce nœud (charger_ou_creer)."""

    def __init__(self, graine):
        _exiger()
        self.graine = graine
        self._cle = Ed25519PrivateKey.from_private_bytes(graine)
        from cryptography.hazmat.primitives import serialization
        self.pub = self._cle.public_key().public_bytes(serialization.Encoding.Raw,
                                                       serialization.PublicFormat.Raw)
        self.id = id_depuis_pub(self.pub)
        self.onion = adresse_onion(self.pub)

    def signer(self, octets):
        return self._cle.sign(octets)

    def cle_etendue_tor(self):
        return cle_etendue_tor(self.graine)


_VERROU = threading.Lock()
_CACHE = {}


def chemin_cle():
    return Path(config.DOSSIER_DONNEES) / "identite_p2p.key"


def _ecrire_cle(chemin, graine):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(chemin.name + ".tmp")
    descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # droits dès la création
    with os.fdopen(descripteur, "w", encoding="ascii") as f:
        f.write(graine.hex() + "\n")
    os.replace(temporaire, chemin)
    try:
        os.chmod(chemin, 0o600)
    except OSError:                                                # pragma: no cover - systèmes sans droits unix
        pass


def existe():
    return chemin_cle().exists()


def charger_ou_creer(creer=True):
    """L'identité de ce nœud : lue dans data/identite_p2p.key, ou créée au premier besoin (si `creer`)."""
    _exiger()
    chemin = chemin_cle()
    with _VERROU:
        en_cache = _CACHE.get(str(chemin))
        if en_cache is not None and chemin.exists():
            return en_cache
        if chemin.exists():
            try:
                graine = bytes.fromhex(chemin.read_text(encoding="ascii").strip())
                if len(graine) != 32:
                    raise ValueError("longueur")
                identite = Identite(graine)
            except (ValueError, OSError) as erreur:
                raise IdentiteIllisible(f"{chemin.name} est illisible ({erreur}) : il n'est pas écrasé ; "
                                        "restaure ta sauvegarde ou supprime-le toi-même pour repartir de zéro") from erreur
        elif creer:
            graine = os.urandom(32)
            _ecrire_cle(chemin, graine)
            identite = Identite(graine)
        else:
            return None
        _CACHE[str(chemin)] = identite
        return identite


def supprimer_identite():
    """Supprime la clé : une nouvelle identité (et un nouvel identifiant) sera créée au prochain besoin."""
    chemin = chemin_cle()
    with _VERROU:
        _CACHE.pop(str(chemin), None)
        if chemin.exists():
            chemin.unlink()


# ------------------------------------------------------------------------------------- le pseudo

_AUTORISES = " _-."
_CONFUSABLES = str.maketrans({"0": "o", "1": "l", "i": "l"})


def valider_pseudo(pseudo):
    """Le pseudo nettoyé, ou ValueError : 3 à 24 caractères (lettres de toutes langues, chiffres, espace,
    « _ », « - », « . »), sans espace au début, à la fin ni double, avec au moins 2 lettres ou chiffres."""
    if not isinstance(pseudo, str):
        raise ValueError("le pseudo doit être un texte")
    pseudo = unicodedata.normalize("NFC", pseudo.strip())
    if not PSEUDO_MIN <= len(pseudo) <= PSEUDO_MAX:
        raise ValueError(f"le pseudo doit faire de {PSEUDO_MIN} à {PSEUDO_MAX} caractères")
    for c in pseudo:
        categorie = unicodedata.category(c)
        if not (categorie[0] in "LN" or c in _AUTORISES) or categorie in ("Lm", "Sk", "No", "Nl"):
            raise ValueError("le pseudo ne peut contenir que des lettres, des chiffres, des espaces et « _ - . »")
    if "  " in pseudo or pseudo != pseudo.strip():
        raise ValueError("pas d'espace double ni en bordure")
    if sum(1 for c in pseudo if unicodedata.category(c)[0] in "LN") < 2:
        raise ValueError("le pseudo doit contenir au moins 2 lettres ou chiffres")
    return pseudo


def cle_pseudo(pseudo):
    """Clé d'unicité d'un pseudo : sans majuscules, accents, espaces ni ponctuation, et avec les confusions
    usuelles ramenées (0/o, 1/l/i). « Alice », « ALICE », « Àlice », « Al.ice » et « A1ice » se valent."""
    texte = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", pseudo).casefold())
    texte = "".join(c for c in texte if not unicodedata.combining(c) and c not in _AUTORISES)
    return texte.translate(_CONFUSABLES)


# --------------------------------------------------------------------------------------- fiches

def canonique(objet):
    """Représentation JSON canonique (clés triées, sans espace) : c'est ce qui est signé."""
    return json.dumps(objet, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _b64(octets):
    return base64.urlsafe_b64encode(octets).decode("ascii").rstrip("=")


def _de_b64(texte):
    if not (isinstance(texte, str) and re.fullmatch(r"[A-Za-z0-9_\-]{1,200}", texte)):
        raise ValueError("signature mal formée")
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def texte_propre(valeur, maxi, nom):
    """Texte déjà propre (aucun caractère de contrôle, invisible ou de direction), de 0 à `maxi` caractères."""
    from . import web
    if not isinstance(valeur, str) or web.longueur_affichee(valeur) > maxi or len(valeur) > maxi * 12 \
            or web.normaliser_caracteres(valeur) != valeur or valeur != valeur.strip():   # longueur AFFICHÉE : les emojis comptent 1
        raise FicheInvalide(f"{nom} invalide")
    return valeur


def creer_fiche(identite, pseudo, depuis, collection, cartes, profil, collection_ok, transport, adresse,
                t=None):
    """La fiche signée de ce nœud."""
    fiche = {"v": VERSION_FICHE, "id": identite.id, "pseudo": pseudo, "collection": collection,
             "cartes": int(cartes), "p": bool(profil), "c": bool(collection_ok), "transport": transport,
             "adresse": adresse, "t": int(time.time() if t is None else t), "depuis": int(depuis or 0)}
    fiche["sig"] = _b64(identite.signer(canonique(fiche)))
    return fiche


def verifier_fiche(donnees, maintenant=None, id_attendu=None):
    """Vérifie une fiche reçue d'un autre pair et renvoie sa version nettoyée (dictionnaire neuf), ou lève
    FicheInvalide : forme exacte, types stricts, pseudo valide, signature correcte DE LA CLÉ QUI EST
    L'IDENTIFIANT, date raisonnable. Rien de ce qui n'est pas vérifié n'entre dans l'annuaire."""
    _exiger()
    maintenant = time.time() if maintenant is None else maintenant
    attendus = {"v", "id", "pseudo", "collection", "cartes", "p", "c", "transport", "adresse", "t", "depuis", "sig"}
    if not isinstance(donnees, dict) or set(donnees) != attendus:
        raise FicheInvalide("fiche mal formée")
    est_entier = lambda x: isinstance(x, int) and not isinstance(x, bool)
    try:
        if donnees["v"] != VERSION_FICHE or not est_entier(donnees["v"]):
            raise FicheInvalide("version de fiche inconnue")
        pub = pub_depuis_id(donnees["id"])
        if id_attendu is not None and donnees["id"] != id_attendu:
            raise FicheInvalide("la fiche n'est pas celle du pair attendu")
        pseudo = donnees["pseudo"]
        if pseudo is not None:
            if valider_pseudo(pseudo) != pseudo:
                raise FicheInvalide("pseudo non normalisé")
        collection = texte_propre(donnees["collection"], COLLECTION_MAX, "nom de collection")
        if not (est_entier(donnees["cartes"]) and 0 <= donnees["cartes"] <= 10_000_000):
            raise FicheInvalide("nombre de cartes invalide")
        if not (isinstance(donnees["p"], bool) and isinstance(donnees["c"], bool)):
            raise FicheInvalide("pastilles invalides")
        if donnees["transport"] not in TRANSPORTS:
            raise FicheInvalide("transport inconnu")
        adresse = donnees["adresse"]
        if donnees["transport"] == "tor":
            if adresse is not None:
                raise FicheInvalide("en mode Tor l'adresse se déduit de la clé : aucune adresse à publier")
        else:
            if not (isinstance(adresse, str) and re.fullmatch(r"[A-Za-z0-9._\-\[\]:]{1,100}:\d{1,5}", adresse)
                    and 1 <= int(adresse.rsplit(":", 1)[1]) <= 65535):
                raise FicheInvalide("adresse invalide")
        if not (est_entier(donnees["t"]) and est_entier(donnees["depuis"])):
            raise FicheInvalide("dates invalides")
        if donnees["t"] > maintenant + AVANCE_MAX or donnees["t"] < maintenant - AGE_MAX_FICHE:
            raise FicheInvalide("fiche datée hors des limites (trop ancienne ou dans le futur)")
        if not 0 <= donnees["depuis"] <= donnees["t"]:
            raise FicheInvalide("date de revendication du pseudo incohérente")
        signature = _de_b64(donnees["sig"])
    except FicheInvalide:
        raise
    except (ValueError, TypeError) as erreur:
        raise FicheInvalide(str(erreur)) from erreur
    corps = {k: donnees[k] for k in attendus if k != "sig"}
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(signature, canonique(corps))
    except (InvalidSignature, ValueError) as erreur:
        raise FicheInvalide("signature incorrecte") from erreur
    return {**corps, "sig": donnees["sig"]}


# ------------------------------------------------------------ signature des réponses (nonce)

def signer_reponse(identite, nonce_hex, chemin, corps):
    """Signature d'une réponse HTTP liée à la requête : nonce + chemin + empreinte du corps (anti-rejeu)."""
    return _b64(identite.signer(_message_reponse(nonce_hex, chemin, corps)))


def verifier_reponse(identifiant, nonce_hex, chemin, corps, signature):
    _exiger()
    try:
        Ed25519PublicKey.from_public_bytes(pub_depuis_id(identifiant)).verify(
            _de_b64(signature), _message_reponse(nonce_hex, chemin, corps))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _message_reponse(nonce_hex, chemin, corps):
    return b"wc1|" + nonce_hex.encode("ascii") + b"|" + chemin.encode("utf-8") + b"|" + hashlib.sha256(corps).digest()
