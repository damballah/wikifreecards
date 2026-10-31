"""Lecture d'une page web pour le Créateur de cartes : titre, sous-titre, contenu et image principale.

Le programme va chercher la page lui-même (le navigateur n'a pas le droit de lire un autre site),
avec des protections, car l'adresse est saisie par l'utilisateur :
- seulement http et https, ports 80 et 443, sans identifiant dans l'adresse ;
- l'adresse doit pointer vers Internet : jamais l'ordinateur lui-même (localhost), le réseau local
  (192.168.x.x, 10.x.x.x...), les adresses réservées ou d'infrastructure (vérifié sur TOUTES les
  adresses du nom, et à chaque redirection : 4 au maximum, suivies une à une) ;
- 10 secondes au plus, 2 Mo de page au plus, 5 Mo d'image au plus, types de contenu contrôlés ;
- aucun cookie, aucun identifiant, pas de proxy ni de fichier .netrc.
Limite connue : un nom de domaine qui changerait d'adresse entre la vérification et la connexion
(« DNS rebinding ») n'est pas bloqué.
"""

import codecs
import html
import ipaddress
import re
import socket
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests

from . import api, images

TAILLE_PAGE_MAX = 2 * 1024 * 1024
REDIRECTIONS_MAX = 4
PORTS_PERMIS = (80, 443)
DELAIS = (5, 10)                  # connexion, lecture (secondes)
TYPES_PAGE = ("text/html", "application/xhtml+xml")


class AdresseRefusee(ValueError):
    """L'adresse n'est pas acceptable (message lisible par l'utilisateur)."""


def _session():
    session = requests.Session()
    session.trust_env = False        # ni proxy ni .netrc venus de l'environnement
    session.headers["User-Agent"] = api._agent()
    session.headers["Accept-Language"] = "fr,en;q=0.7"
    return session


def url_http(adresse):
    """L'adresse nettoyée si c'est une adresse http(s) plausible (sans la contacter), sinon None."""
    if not isinstance(adresse, str):
        return None
    adresse = adresse.strip()
    if not 8 <= len(adresse) <= 2000 or any(c.isspace() or unicodedata.category(c)[0] == "C"
                                            for c in adresse):
        return None
    try:
        morceaux = urlsplit(adresse)
        port = morceaux.port
    except ValueError:
        return None
    if morceaux.scheme not in ("http", "https") or not morceaux.hostname:
        return None
    return adresse if (port is None or port in PORTS_PERMIS) else None


def _motif_refus(adresse):
    """Pourquoi une adresse est refusée, en une phrase."""
    try:
        morceaux = urlsplit((adresse or "").strip())
        port = morceaux.port
    except (ValueError, AttributeError):
        return "adresse web invalide"
    if morceaux.scheme and morceaux.scheme not in ("http", "https"):
        return "seules les adresses http et https sont acceptées"
    if port is not None and port not in PORTS_PERMIS:
        return "seuls les ports 80 et 443 sont acceptés (site local ou service interne refusé)"
    return "adresse web invalide (vérifie qu'elle commence par https://)"


def _publique(ip):
    adresse = ipaddress.ip_address(ip.split("%")[0])
    if getattr(adresse, "ipv4_mapped", None):
        adresse = adresse.ipv4_mapped
    return adresse.is_global and not adresse.is_multicast


def verifier_adresse(adresse):
    """Vérifie qu'on peut contacter cette adresse sans danger (voir le haut du fichier) et la renvoie.
    Lève AdresseRefusee sinon."""
    propre = url_http(adresse)
    if propre is None:
        raise AdresseRefusee(_motif_refus(adresse))
    morceaux = urlsplit(propre)
    if morceaux.username or morceaux.password:
        raise AdresseRefusee("l'adresse ne doit pas contenir d'identifiant")
    port = morceaux.port or (443 if morceaux.scheme == "https" else 80)
    try:
        trouvees = socket.getaddrinfo(morceaux.hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise AdresseRefusee("ce site est introuvable (vérifie l'adresse)") from None
    if not trouvees or not all(_publique(info[4][0]) for info in trouvees):
        raise AdresseRefusee("cette adresse n'est pas un site public d'Internet : "
                             "ordinateur local et réseau local sont refusés")
    return propre


def telecharger(adresse, maximum, types=None):
    """Télécharge `adresse` (redirections suivies une à une et vérifiées). Renvoie
    (octets, type de contenu, adresse finale, jeu de caractères annoncé par le site ou None : celui de
    l'en-tête Content-Type, jamais la valeur par défaut de requests, qui est fausse). Lève AdresseRefusee, ValueError
    (contenu trop gros ou de mauvais type) ou une erreur réseau de requests."""
    session = _session()
    try:
        for _ in range(REDIRECTIONS_MAX + 1):
            adresse = verifier_adresse(adresse)
            reponse = session.get(adresse, timeout=DELAIS, stream=True, allow_redirects=False)
            try:
                if reponse.is_redirect or reponse.status_code in (301, 302, 303, 307, 308):
                    destination = reponse.headers.get("Location")
                    if not destination:
                        raise ValueError("redirection sans destination")
                    adresse = urljoin(adresse, destination)
                    continue
                reponse.raise_for_status()
                genre = reponse.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if types and genre not in types:
                    raise ValueError(f"contenu de type « {genre or 'inconnu'} » : ce n'est pas "
                                     "une page web lisible" if "html" in types[0] else
                                     f"contenu de type « {genre or 'inconnu'} » refusé")
                annonce = reponse.headers.get("Content-Length", "")
                if annonce.isdigit() and int(annonce) > maximum:
                    raise ValueError("le contenu est trop gros")
                morceaux, total = [], 0
                for morceau in reponse.iter_content(65536):
                    total += len(morceau)
                    if total > maximum:
                        raise ValueError("le contenu est trop gros")
                    morceaux.append(morceau)
                return (b"".join(morceaux), genre, adresse,
                        charset_entete(reponse.headers.get("Content-Type", "")))
            finally:
                reponse.close()
        raise ValueError("trop de redirections")
    finally:
        session.close()


# ------------------------------------------------------------------------------- lecture HTML

_IGNORES = {"script", "style", "noscript", "template", "svg", "nav", "footer", "aside", "form",
            "button", "select", "iframe", "head"}
_VIDES = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
          "track", "wbr"}


class LecteurPage(HTMLParser):
    """Rassemble ce qui sert à fabriquer une carte : balises meta, titre, premier h1, paragraphes,
    description courte (Wikipédia), images. Aucune exécution de code : c'est du texte."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.titre_balise = ""
        self.h1 = ""
        self.courte = ""
        self.paragraphes = []          # (texte, dans_contenu)
        self.images = []               # (adresse, dans_contenu, largeur)
        self.image_rel = None
        self._pile = []
        self._ignore = 0
        self._contenu = 0
        self._p = None
        self._titre = None
        self._h1 = None
        self._courte_niveau = None
        self._en_tete = 0

    # -- outils
    def _dans_contenu(self):
        return self._contenu > 0

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            cle = (a.get("property") or a.get("name") or "").lower()
            if cle and "content" in a and cle not in self.meta:
                self.meta[cle] = a["content"]
            return
        if tag == "link":
            if "image_src" in a.get("rel", "").lower().split() and a.get("href"):
                self.image_rel = a["href"]
            return
        if tag == "img":
            if not self._ignore:
                source = a.get("src") or a.get("data-src") or ""
                largeur = int(a["width"]) if a.get("width", "").isdigit() else None
                if source:
                    self.images.append((source, self._dans_contenu(), largeur))
            return
        if tag in _VIDES:
            return
        self._pile.append(tag)
        if tag in _IGNORES and tag != "head":
            self._ignore += 1
        if tag == "title":
            self._titre = []
        if tag in ("main", "article") or a.get("role") == "main":
            self._contenu += 1
            self._pile[-1] = tag + "#contenu"
        if tag == "h1" and not self.h1 and not self._ignore:
            self._h1 = []
        if tag == "div" and "shortdescription" in a.get("class", "").split() and not self.courte:
            self._courte_niveau = len(self._pile)
            self._courte = []
        if tag == "p" and not self._ignore and self._p is None:
            self._p = []

    def handle_endtag(self, tag):
        if tag in _VIDES:
            return
        while self._pile:
            sommet = self._pile.pop()
            base = sommet.split("#")[0]
            if base in _IGNORES and base != "head" and self._ignore:
                self._ignore -= 1
            if sommet.endswith("#contenu"):
                self._contenu = max(0, self._contenu - 1)
            if base == "title" and self._titre is not None:
                self.titre_balise = " ".join("".join(self._titre).split())
                self._titre = None
            if base == "h1" and self._h1 is not None:
                self.h1 = " ".join("".join(self._h1).split())
                self._h1 = None
            if base == "p" and self._p is not None:
                self.paragraphes.append((" ".join("".join(self._p).split()), self._dans_contenu()))
                self._p = None
            if (self._courte_niveau is not None and len(self._pile) < self._courte_niveau):
                self.courte = " ".join("".join(self._courte).split())
                self._courte_niveau = None
            if base == tag:
                break

    def handle_data(self, data):
        if self._titre is not None:
            self._titre.append(data)
        if self._ignore:
            return
        if self._h1 is not None:
            self._h1.append(data)
        if self._courte_niveau is not None:
            self._courte.append(data)
        if self._p is not None:
            self._p.append(data)


def charset_entete(genre):
    """Le jeu de caractères annoncé dans un en-tête Content-Type (« text/html; charset=UTF-8 »), ou None."""
    trouve = re.search(r"charset\s*=\s*[\"']?([\w.:-]+)", genre or "", re.I)
    return trouve.group(1) if trouve else None


_EQUIVALENTS = {"iso-8859-1": "cp1252", "latin1": "cp1252", "latin-1": "cp1252", "iso8859-1": "cp1252",
                "l1": "cp1252", "us-ascii": "cp1252", "ascii": "cp1252", "windows-1252": "cp1252"}


def _codec(nom):
    """Le nom Python d'un jeu de caractères annoncé (None s'il est inconnu). Comme les navigateurs,
    « ISO-8859-1 » est lu comme Windows-1252 (c'est ce que les sites veulent dire)."""
    if not nom:
        return None
    nom = nom.strip().strip("\"'").lower()
    nom = _EQUIVALENTS.get(nom, nom)
    try:
        return codecs.lookup(nom).name
    except LookupError:
        return None


_MOJIBAKE = re.compile("Ã[\u0080-\u00bf]|Â[\u00a0-\u00bf]|â€[\u0080-\u00bf\u2122\u0153]|Ã©|Ã¨")


def reparer_mojibake(texte):
    """Répare un texte UTF-8 lu par erreur comme Windows-1252 (« Ã©tÃ© » -> « été »)."""
    if not _MOJIBAKE.search(texte):
        return texte
    for jeu in ("cp1252", "latin-1"):
        try:
            corrige = texte.encode(jeu).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if len(_MOJIBAKE.findall(corrige)) < len(_MOJIBAKE.findall(texte)):
            return corrige

    def morceau(m):                                        # réparation morceau par morceau (texte mêlé)
        for jeu in ("cp1252", "latin-1"):
            try:
                return m.group(0).encode(jeu).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        return m.group(0)
    return re.sub("[ÂÃâ][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u02c6\u02dc"
                  "\u2013-\u203a\u20ac\u2122]{1,2}", morceau, texte)


def decoder(octets, annonce=None):
    """Convertit les octets d'une page en texte Unicode (UTF-8), le plus fidèlement possible :
    1. la marque d'ordre des octets (BOM) si elle existe ;
    2. UTF-8 s'il est valide (c'est quasi sûr dès qu'il y a des accents : un texte Windows-1252 n'est
       presque jamais de l'UTF-8 valide) : cela corrige les sites qui annoncent un mauvais jeu de caractères ;
    3. le jeu de caractères de l'en-tête, puis celui de la balise <meta charset> ;
    4. une détection automatique si la bibliothèque est installée ;
    5. Windows-1252 en dernier recours (caractère illisible remplacé plutôt qu'erreur)."""
    if octets.startswith(codecs.BOM_UTF8):
        return reparer_mojibake(octets[3:].decode("utf-8", errors="replace"))
    if octets.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return octets.decode("utf-16", errors="replace")
    try:
        return reparer_mojibake(octets.decode("utf-8"))
    except UnicodeDecodeError:
        pass
    meta = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([\w.:-]+)", octets[:4096], re.I)
    for nom in (annonce, meta.group(1).decode("ascii", "ignore") if meta else None):
        codec = _codec(nom)
        if codec and codec != "utf-8":
            try:
                return octets.decode(codec)
            except (UnicodeDecodeError, LookupError):
                continue
    try:                                                   # facultatif : charset_normalizer / chardet
        from requests.compat import chardet
        trouve = chardet.detect(octets[:200000]) if chardet is not None else None
        codec = _codec((trouve or {}).get("encoding"))
        if codec and (trouve.get("confidence") or 0) >= 0.6:
            return octets.decode(codec, errors="replace")
    except Exception:                                      # pragma: no cover - bibliothèque absente
        pass
    return octets.decode("cp1252", errors="replace")


_ESPACES = {ord(c): " " for c in "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
                              "\u2009\u200a\u202f\u205f\u3000\u2028\u2029\t\n\r\x0b\x0c"}
_INVISIBLES = {ord(c): None for c in "\u00ad\u200b\u200c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2060"
                                 "\u2061\u2062\u2063\u2064\u2066\u2067\u2068\u2069\ufeff\ufffd"}


_TAGS_EMOJI = range(0xE0020, 0xE0080)                 # lettres « invisibles » des drapeaux composés (Écosse, Pays de Galles...)
_NIVEAUX_PEAU = range(0x1F3FB, 0x1F400)
_INDICATEURS_REGIONAUX = range(0x1F1E6, 0x1F200)


def longueur_affichee(texte):
    """Longueur d'un texte telle qu'on la VOIT : un emoji compte pour 1, même composé (famille 👨‍👩‍👧, drapeau 🏴󠁧󠁢󠁳󠁣󠁴󠁿,
    peau 👍🏽, cœur ❤️), au lieu de 2 à 11 caractères techniques. Sert aux limites de longueur du titre et de la biographie."""
    n, i, texte = 0, 0, str(texte or "")
    while i < len(texte):
        c = texte[i]
        if ord(c) in _INDICATEURS_REGIONAUX and i + 1 < len(texte) and ord(texte[i + 1]) in _INDICATEURS_REGIONAUX:
            i += 2                                         # un drapeau (deux lettres régionales) = 1
            n += 1
            continue
        i += 1
        if c == "\u200d":                                  # le liant colle le caractère SUIVANT au précédent
            i += 1
            continue
        if (unicodedata.category(c) in ("Mn", "Me", "Mc") or ord(c) in _TAGS_EMOJI or ord(c) in _NIVEAUX_PEAU
                or c in "\ufe0e\ufe0f"):
            continue
        n += 1
    return n


def tronquer_affichage(texte, maxi):
    """Les `maxi` premiers caractères AFFICHÉS : ne coupe jamais un emoji composé en deux."""
    texte = str(texte or "")
    sortie = ""
    for c in texte:
        if longueur_affichee(sortie + c) > maxi:
            break
        sortie += c
    return sortie


def normaliser_caracteres(texte):
    """Retire ce qui n'est pas du vrai texte : espaces insécables et autres espaces spéciaux (-> espace
    simple), trait d'union conditionnel, caractères de largeur nulle ou de direction du texte, marque
    d'ordre des octets, caractère de remplacement « � » (signe d'un mauvais décodage) et caractères de
    contrôle. Les emoji composés gardent leur liant."""
    texte = unicodedata.normalize("NFC", str(texte or "")).translate({**_ESPACES, **_INVISIBLES})
    sortie = []
    for i, c in enumerate(texte):
        if c == "\u200d" and not (0 < i < len(texte) - 1
                                   and (unicodedata.category(texte[i - 1]) in ("So", "Sk") or texte[i - 1] == "\ufe0f")
                                   and unicodedata.category(texte[i + 1]) == "So"):
            continue                                       # liant « emoji » seulement entre deux symboles (couleur de peau, ❤️ permis)
        if ord(c) in _TAGS_EMOJI:                          # drapeau composé : les lettres cachées suivent un 🏴 (ou une autre)
            if sortie and (sortie[-1] == "\U0001F3F4" or ord(sortie[-1]) in _TAGS_EMOJI):
                sortie.append(c)
            continue
        if unicodedata.category(c)[0] == "C" and c != "\u200d":
            continue
        sortie.append(c)
    return "".join(sortie)


def texte_brut(texte):
    """Du TEXTE SEUL, sans aucune mise en forme venue du site : pas de balise (même mal fermée), pas
    d'entité (« &amp; », « &nbsp; » : décodées, même doublement encodées), pas de renvoi « [1] » ni
    « [modifier] », pas de puce en début de texte, pas d'espaces multiples ni de retours à la ligne. La
    seule mise en forme est ensuite celle de la carte."""
    texte = str(texte or "")
    for _ in range(2):                                     # « &amp;amp; » (doublement encodé) : 2 passes
        if re.search(r"&(?:[a-z][a-z0-9]{1,10}|#\d{1,7}|#x[0-9a-f]{1,6});", texte, re.I):
            texte = html.unescape(texte)
    texte = re.sub(r"<[a-zA-Z/!?][^<>]{0,300}>", " ", texte)           # une vraie balise commence par une lettre, /, ! ou ?
    texte = re.sub(r"\[(?:\d+|[a-z]|modifier(?: le code)?|edit|réf\. nécessaire|citation needed|source "
                   r"nécessaire)\]", "", texte, flags=re.I)
    texte = " ".join(normaliser_caracteres(texte).split())
    return re.sub(r"^(?:[•·▪▫‣◦▸►▶\-–—*]+\s+)+", "", texte)


def nettoyer_texte(texte):
    """Texte propre d'une page web (voir texte_brut)."""
    return texte_brut(texte)


def couper(texte, maxi):
    """Coupe `texte` à `maxi` caractères au plus, sur une fin de mot, avec « … »."""
    texte = texte.strip()
    if len(texte) <= maxi:
        return texte
    coupe = texte[:maxi - 1].rsplit(" ", 1)[0] if " " in texte[:maxi - 1] else texte[:maxi - 1]
    return coupe.rstrip(" ,;:-–—") + "…"


def phrases(texte, maximum):
    """Les `maximum` premières phrases du texte."""
    morceaux = re.split(r"(?<=[.!?…])\s+(?=[A-ZÀ-ÖØ-ÞŒ«\"'(0-9])", texte.strip())
    return " ".join(morceaux[:max(1, maximum)])


def lire_page(octets, adresse_finale, encodage=None, nb_phrases=3, max_titre=80, max_sous_titre=120,
              max_description=700):
    """Les informations d'une page HTML : {titre, sous_titre, description, image (adresse absolue ou
    None), url}. `description` : le début du contenu (nb_phrases phrases au plus)."""
    texte = decoder(octets, encodage)
    lecteur = LecteurPage()
    try:
        lecteur.feed(texte)
        lecteur.close()
    except (AssertionError, ValueError):                     # HTML trop abîmé : on garde ce qu'on a
        pass

    meta = lecteur.meta
    titre = (meta.get("og:title") or meta.get("twitter:title") or lecteur.h1 or lecteur.titre_balise)
    titre = re.sub(r"\s*[-–—|]\s*Wikip[ée]dia.*$", "", nettoyer_texte(titre), flags=re.I)
    description_meta = nettoyer_texte(meta.get("og:description") or meta.get("description")
                                      or meta.get("twitter:description") or "")

    courts = [t for t, dedans in lecteur.paragraphes if dedans and len(t) >= 40]
    tous = [t for t, _ in lecteur.paragraphes if len(t) >= 40]
    corps = nettoyer_texte(" ".join((courts or tous)[:6]))
    contenu = couper(phrases(corps, nb_phrases), max_description) if corps else \
        couper(phrases(description_meta, nb_phrases), max_description)

    sous_titre = nettoyer_texte(lecteur.courte)
    if not sous_titre and description_meta:
        sous_titre = phrases(description_meta, 1)
    sous_titre = couper(sous_titre, max_sous_titre) if sous_titre else ""
    if sous_titre and sous_titre == contenu:
        sous_titre = ""

    candidates = [meta.get("og:image:secure_url"), meta.get("og:image"), meta.get("twitter:image"),
                  meta.get("twitter:image:src"), lecteur.image_rel]
    candidates += [src for src, dedans, largeur in lecteur.images
                   if dedans and (largeur is None or largeur >= 150)]
    candidates += [src for src, dedans, largeur in lecteur.images        # hors article : seulement les grandes
                   if not dedans and largeur is not None and largeur >= 300]
    image = None
    for candidate in candidates:
        if not candidate or candidate.startswith("data:"):
            continue
        absolue = url_http(urljoin(adresse_finale, candidate.strip()))
        if absolue and not urlsplit(absolue).path.lower().endswith(".svg"):
            image = absolue
            break
    return {"titre": couper(titre, max_titre), "sous_titre": sous_titre, "description": contenu,
            "image": image, "url": adresse_finale}


def charger(adresse, nb_phrases=3, max_titre=80, max_sous_titre=120, max_description=700):
    """Va chercher la page, la lit et télécharge son image principale dans data/images/.
    Renvoie {titre, sous_titre, description, image (adresse locale ou None), url, avertissements}.
    Lève AdresseRefusee, ValueError ou une erreur réseau si la page ne peut pas être lue."""
    octets, _, finale, encodage = telecharger(adresse, TAILLE_PAGE_MAX, TYPES_PAGE)
    infos = lire_page(octets, finale, encodage, nb_phrases, max_titre, max_sous_titre, max_description)
    avertissements = []
    distante, infos["image"] = infos["image"], None
    if distante:
        try:
            donnees, _, _, _ = telecharger(distante, images.TAILLE_MAX)
            infos["image"] = images.enregistrer(donnees)
        except (AdresseRefusee, ValueError, requests.RequestException, images.ImageRefusee) as erreur:
            avertissements.append(f"image trouvée mais non récupérée : {erreur}")
    else:
        avertissements.append("aucune image principale trouvée sur cette page")
    if not infos["titre"]:
        avertissements.append("aucun titre trouvé : écris-le toi-même")
    if not infos["description"]:
        avertissements.append("aucun texte trouvé : écris la description toi-même")
    infos["avertissements"] = avertissements
    return infos
