"""Ce que ton nœud fait chez les AUTRES : consulter un profil ou une collection, et rapatrier des cartes.

Tout ce qui arrive d'un autre nœud est une donnée NON FIABLE : chaque champ est vérifié, borné et nettoyé avant
d'être affiché ou enregistré (types stricts, longueurs, couleurs et motifs dans des listes fermées, adresses
Wikimedia seulement pour les images, aucun HTML jamais interprété). Une carte qui ne passe pas la vérification
est ignorée. Aucune requête n'est faite vers Wikipédia : tout vient du pair.
"""

import re
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

from . import (api, base, cadrage, categories as cat, config, fullart, images, p2p_annuaire as annuaire, p2p_transport as transport,
               rarete, stats, theme, web)

TTL_CACHE = 60
CACHE_MAX = 200
IMAGES_CACHE_OCTETS = 30 * 1024 * 1024


class DonneeInvalide(ValueError):
    """Une donnée reçue d'un pair n'est pas acceptable."""


class PairInconnu(LookupError):
    """Ce pair n'est pas dans l'annuaire."""


class PartageRefuse(Exception):
    """Le pair a refusé (pastille rouge) : `quoi` vaut « profil » ou « collection »."""

    def __init__(self, quoi):
        super().__init__(quoi)
        self.quoi = quoi


# ------------------------------------------------------------------------------ vérification

def _texte(v, maxi, nom, vide=True):
    if v is None and vide:
        return ""
    if not isinstance(v, str):
        raise DonneeInvalide(f"{nom} : du texte est attendu")
    t = " ".join(web.normaliser_caracteres(v).split())
    if web.longueur_affichee(t) > maxi or len(t) > maxi * 12:          # longueur AFFICHÉE : un emoji compte pour 1
        raise DonneeInvalide(f"{nom} : trop long")
    if not t and not vide:
        raise DonneeInvalide(f"{nom} : obligatoire")
    return t


def _entier(v, mini, maxi, nom, nul=False):
    if v is None and nul:
        return None
    if not isinstance(v, int) or isinstance(v, bool) or not mini <= v <= maxi:
        raise DonneeInvalide(f"{nom} : entier invalide")
    return v


def _reel(v, mini, maxi, nom):
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v or not mini <= v <= maxi:
        raise DonneeInvalide(f"{nom} : nombre invalide")
    return float(v)


def _couleur(v, nom):
    if not theme.couleur_valide(v):
        raise DonneeInvalide(f"{nom} : couleur invalide")
    return v.lower()


def _theme(d, nom):
    if not isinstance(d, dict) or set(d) != {"motif", "couleurs", "reflet"}:
        raise DonneeInvalide(f"{nom} : thème mal formé")
    if d["motif"] not in theme.MOTIFS or d["reflet"] not in theme.REFLETS:
        raise DonneeInvalide(f"{nom} : motif ou reflet inconnu")
    if not (isinstance(d["couleurs"], list) and len(d["couleurs"]) == 3):
        raise DonneeInvalide(f"{nom} : trois couleurs attendues")
    return {"motif": d["motif"], "reflet": d["reflet"], "couleurs": [_couleur(c, nom) for c in d["couleurs"]]}


def _code(v, nom):
    if not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9]{1,6}", v):
        raise DonneeInvalide(f"{nom} : code de rang invalide")
    return v


def valider_site(d):
    if not isinstance(d, dict):
        raise DonneeInvalide("site mal formé")
    return {"titre": _texte(d.get("titre"), 80, "titre du site", vide=False),
            "bio": _texte(d.get("bio"), 200, "biographie")}


def valider_apparence(d):
    """Les rangs du propriétaire (nom, lettres, thème), son palier « Personnalisée » et l'angle des cartes."""
    if not isinstance(d, dict) or not isinstance(d.get("rangs"), list) or len(d["rangs"]) > 12:
        raise DonneeInvalide("apparence mal formée")
    rangs = []
    for r in d["rangs"]:
        if not isinstance(r, dict):
            raise DonneeInvalide("rang mal formé")
        symbole = r.get("symbole")
        if not isinstance(symbole, str) or not re.fullmatch(r"[A-Za-z0-9]{1,3}", symbole):
            raise DonneeInvalide("lettres de rang invalides")
        rangs.append({"code": _code(r.get("code"), "rang"), "nom": _texte(r.get("nom"), 40, "nom du rang", False),
                      "symbole": symbole, "theme": _theme(r.get("theme"), "thème du rang")})
    perso = d.get("perso")
    if not isinstance(perso, dict):
        raise DonneeInvalide("palier personnalisé mal formé")
    symbole = perso.get("symbole")
    if not (isinstance(symbole, str) and 1 <= len(symbole) <= theme.SYMBOLE_PERSO_MAX
            and symbole == web.normaliser_caracteres(symbole) and " " not in symbole):
        raise DonneeInvalide("lettres du palier personnalisé invalides")
    angles = d.get("angles")
    if angles not in ("arrondis", "carres"):
        raise DonneeInvalide("angles inconnus")
    return {"rangs": rangs, "angles": angles,
            "perso": {"symbole": symbole, "nom": _texte(perso.get("nom"), 40, "nom du palier", False),
                      "theme": _theme(perso.get("theme"), "thème du palier personnalisé")}}


def valider_resume(d):
    if not isinstance(d, dict) or not isinstance(d.get("rangs"), dict) or not isinstance(d.get("categories"), list):
        raise DonneeInvalide("résumé mal formé")
    rangs = {_code(k, "rang"): _entier(v, 0, 10_000_000, "nombre de cartes") for k, v in list(d["rangs"].items())[:13]}
    categories = []
    for c in d["categories"][:200]:
        if not isinstance(c, dict):
            raise DonneeInvalide("catégorie mal formée")
        categories.append({"nom": _texte(c.get("nom"), 40, "catégorie", False), "couleur": _couleur(c.get("couleur"), "catégorie"),
                           "n": _entier(c.get("n"), 0, 10_000_000, "nombre de cartes")})
    return {"total": _entier(d.get("total"), 0, 10_000_000, "total"), "rangs": rangs, "categories": categories,
            "sans_categorie": _entier(d.get("sans_categorie"), 0, 10_000_000, "sans catégorie")}


def url_proxy(pair, nom):
    return f"/hall/image?pair={quote(pair)}&nom={quote(nom)}"


def _image(d, pair):
    """Image d'une carte reçue -> adresse à afficher : Wikimedia (https) telle quelle, ou notre relais local."""
    if d is None:
        return None
    if isinstance(d, dict) and d.get("type") == "wikimedia" and api.adresse_wikimedia(d.get("url")):
        return d["url"]
    if isinstance(d, dict) and d.get("type") == "locale" and isinstance(d.get("nom"), str) \
            and re.fullmatch(r"[0-9a-f]{32}\.(?:jpg|png|gif|webp)", d["nom"]):
        return url_proxy(pair, d["nom"])
    raise DonneeInvalide("image invalide")


def valider_carte(d, pair):
    """Une carte reçue -> dictionnaire au format des cartes affichées (le même que base._depuis_ligne), ou
    DonneeInvalide. `pair` : identifiant du propriétaire (pour le relais des images locales)."""
    if not isinstance(d, dict):
        raise DonneeInvalide("carte mal formée")
    perso = d.get("perso") is True
    url = d.get("url")
    if url is not None:
        ok_url = web.url_http(url) if perso else api.adresse_wikimedia(url)
        if not ok_url or len(url) > 2000:
            raise DonneeInvalide("adresse d'article invalide")
    elif not perso:
        raise DonneeInvalide("une carte d'article doit avoir son adresse")
    stats_d = d.get("stats")
    if not isinstance(stats_d, dict):
        raise DonneeInvalide("statistiques mal formées")
    try:
        tire = datetime.fromisoformat(str(d.get("tire_le")))
    except ValueError:
        raise DonneeInvalide("date invalide") from None
    if tire.tzinfo is None:
        tire = tire.replace(tzinfo=timezone.utc)
    langue = d.get("langue")
    if not isinstance(langue, str) or not re.fullmatch(r"[A-Za-z\-]{2,12}", langue):
        raise DonneeInvalide("langue invalide")
    cats = []
    for i, c in enumerate((d.get("categories") or [])[:20], start=1):
        if not isinstance(c, dict):
            raise DonneeInvalide("catégorie mal formée")
        cats.append({"id": i, "nom": _texte(c.get("nom"), 40, "catégorie", False),
                     "couleur": _couleur(c.get("couleur"), "catégorie"), "automatique": False})
    style = None
    if perso:
        style = theme.style_perso(d.get("style"))
    return {
        "id": _entier(d.get("id"), 1, 2**53, "identifiant"), "titre": _texte(d.get("titre"), 300, "titre", False),
        "description": _texte(d.get("description"), 500, "description") or "no-description",
        "intro": _texte(d.get("intro"), 4000, "introduction") or "no-intro",
        "rarete": _code(d.get("rarete"), "rang"), "rarete_nom": _texte(d.get("rarete_nom"), 40, "nom du rang"),
        "rarete_tiree": _code(d.get("rarete"), "rang"), "tire_le": tire,
        "vues_moyenne": _reel(d.get("vues_moyenne"), 0, 10**9, "vues"), "vues_total": _entier(d.get("vues_total"), 0, 10**13, "vues"),
        "url": url or "perso:visiteur", "image": _image(d.get("image"), pair) or "no-image",
        "miniature": _image(d.get("miniature"), pair) or _image(d.get("image"), pair) or "no-image",
        "qr_svg": "", "langue": langue, "favori": False, "categories": cats, "fullart": fullart.depuis_pair(d.get("fullart"), pair), "cadrage": cadrage.propre(d.get("cadrage")),
        "gif_anime": 1 if d.get("gif_anime") == 1 and not isinstance(d.get("gif_anime"), bool) else (0 if d.get("gif_anime") == 0 and not isinstance(d.get("gif_anime"), bool) else None),
        "nb_langues": _entier(stats_d.get("langues"), 0, 10_000, "langues", nul=True),
        "taille_octets": _entier(stats_d.get("taille"), 0, 10**9, "taille", nul=True),
        "nb_revisions": _entier(stats_d.get("modifications"), 0, 10**9, "modifications", nul=True),
        "revisions_plafonnees": stats_d.get("plafonne") is True,
        "nb_liens_entrants": _entier(stats_d.get("liens"), 0, 10**9, "liens", nul=True),
        "personnalisee": perso, "surnom": _texte(d.get("surnom"), 60, "surnom") if perso else "", "style": style,
        "supprime_le": None,
    }


def appliquer_apparence(art, apparence):
    """Donne à une carte l'apparence de son propriétaire : lettres, nom et thème de son rang (la page affiche
    ainsi les cartes exactement comme chez lui, même si tes rangs sont réglés autrement)."""
    if art["personnalisee"]:
        return art
    rang = next((r for r in apparence["rangs"] if r["code"] == art["rarete"]), None)
    if rang is not None:
        art["symbole_force"], art["theme_force"], art["rarete_nom"] = rang["symbole"], rang["theme"], rang["nom"]
    return art


def css_apparence(apparence):
    """CSS des rangs du propriétaire (couleurs des cartes et pastilles), généré depuis des valeurs VÉRIFIÉES."""
    return theme.css_theme({r["code"]: r["theme"] for r in apparence["rangs"]}, apparence["angles"],
                           config.ANGLES_SITE, config.COULEUR_ACCENT, perso=apparence["perso"]["theme"])


# ----------------------------------------------------------------------------------- appels

_CACHE = {}
_VERROU = threading.Lock()


def _fiche(identifiant):
    with base.connexion_rapide() as conn:
        fiche = annuaire.fiche_de(conn, identifiant)
    if fiche is None:
        raise PairInconnu(identifiant)
    return fiche


def appeler(identifiant, chemin, utiliser_cache=True):
    """Appelle un pair connu et renvoie sa réponse (dictionnaire). Résultats gardés une minute. Lève PartageRefuse
    (pastille rouge), PairInconnu ou transport.TransportErreur (pair hors ligne, réponse invalide...)."""
    cle = (identifiant, chemin)
    with _VERROU:
        en_cache = _CACHE.get(cle)
        if utiliser_cache and en_cache and time.monotonic() - en_cache[0] < TTL_CACHE:
            return en_cache[1]
    fiche = _fiche(identifiant)
    try:
        statut, donnees = transport.appeler_json(fiche, chemin)
    except transport.TransportErreur:
        with base.connexion_rapide() as conn:
            annuaire.marquer_echec(conn, identifiant)
        raise
    with base.connexion_rapide() as conn:
        annuaire.marquer_vu(conn, identifiant)
    if statut == 403 and donnees.get("refus") in ("profil", "collection"):
        raise PartageRefuse(donnees["refus"])
    if statut != 200:
        raise transport.TransportErreur(f"le pair a répondu {statut}")
    with _VERROU:
        if len(_CACHE) >= CACHE_MAX:
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]), None)
        _CACHE[cle] = (time.monotonic(), donnees)
    return donnees


def vider_cache():
    with _VERROU:
        _CACHE.clear()
        _IMAGES.clear()


def profil_distant(identifiant):
    """Le profil d'un pair, vérifié : {site, apparence, resume, vitrines:[{titre, emplacements:[carte|None]}]}."""
    d = appeler(identifiant, "/p2p/profil")
    apparence = valider_apparence(d.get("apparence"))
    vitrines = []
    for v in (d.get("vitrines") if isinstance(d.get("vitrines"), list) else [])[:12]:
        if not isinstance(v, dict) or not isinstance(v.get("emplacements"), list):
            raise DonneeInvalide("vitrine mal formée")
        emplacements = []
        for c in v["emplacements"][:5]:
            try:
                emplacements.append(None if c is None else appliquer_apparence(valider_carte(c, identifiant), apparence))
            except DonneeInvalide:
                emplacements.append(None)                    # une carte douteuse est simplement absente
        vitrines.append({"titre": _texte(v.get("titre"), 40, "titre de vitrine"), "emplacements": emplacements})
    return {"site": valider_site(d.get("site")), "apparence": apparence, "resume": valider_resume(d.get("resume")),
            "vitrines": vitrines}


def collection_distante(identifiant, rangs=(), categorie="", q="", tri="", page=1, par_page=24):
    """Une page de la collection d'un pair, vérifiée. Les cartes douteuses sont écartées (`ecartees`)."""
    chemin = "/p2p/collection?" + "&".join(
        f"{k}={quote(str(v))}" for k, v in (("rangs", ",".join(r for r in rangs if re.fullmatch(r"[A-Za-z0-9]{1,6}", r))),
                                            ("categorie", categorie), ("q", q), ("tri", tri), ("page", int(page)),
                                            ("par_page", int(par_page))) if v != "")
    d = appeler(identifiant, chemin)
    apparence = valider_apparence(d.get("apparence"))
    cartes, ecartees = [], 0
    for c in (d.get("cartes") if isinstance(d.get("cartes"), list) else [])[:partage_max()]:
        try:
            carte = valider_carte(c, identifiant)
        except DonneeInvalide:
            ecartees += 1
            continue
        if carte["personnalisee"]:
            continue                                      # (les cartes créées à la main ne se partagent plus : même un pair modifié ne peut pas en afficher ici)
        cartes.append(appliquer_apparence(carte, apparence))
    return {"site": valider_site(d.get("site")), "apparence": apparence, "resume": valider_resume(d.get("resume")),
            "cartes": cartes, "ecartees": ecartees, "page": _entier(d.get("page"), 1, 10**6, "page"),
            "pages": _entier(d.get("pages"), 1, 10**6, "pages"),
            "total_filtre": _entier(d.get("total_filtre"), 0, 10**7, "total"), "total": _entier(d.get("total"), 0, 10**7, "total")}


def partage_max():
    from . import partage
    return partage.PAR_PAGE_MAX


# ------------------------------------------------------------------------- images relayées

_IMAGES = {}
_CALQUES = {}


def fullart_relais(identifiant, genre, nom):
    """Un calque du full-art d'une carte d'un pair, relayé par ton nœud (ton navigateur ne contacte jamais le pair). Vérifié (PNG, dimensions
    raisonnables, 6 Mo au plus) et gardé en mémoire ; renvoie les octets."""
    if genre not in ("zuul", "gozer") or not fullart.nom_valide(nom):
        raise DonneeInvalide("calque invalide")
    cle = (identifiant, genre, nom)
    with _VERROU:
        if cle in _CALQUES:
            return _CALQUES[cle]
    fiche = _fiche(identifiant)
    statut, octets = transport.requete(fiche, f"/p2p/fullart/{genre}/{quote(nom, safe='')}.png", maxi=fullart.TAILLE_RELAIS_MAX)
    if statut == 403:
        raise PartageRefuse("collection")
    if statut != 200 or not fullart.png_valide(octets):
        raise DonneeInvalide("calque refusé")
    with _VERROU:
        while _CALQUES and sum(len(v) for v in _CALQUES.values()) + len(octets) > IMAGES_CACHE_OCTETS:
            _CALQUES.pop(next(iter(_CALQUES)))
        _CALQUES[cle] = octets
    return octets


def image_relais(identifiant, nom):
    """L'image d'une carte personnalisée d'un pair, relayée par ton nœud (ton navigateur ne contacte jamais le
    pair lui-même). Vérifiée par son contenu (JPEG, PNG, GIF ou WebP), 5 Mo au plus, gardée en mémoire."""
    if not isinstance(nom, str) or not re.fullmatch(r"[0-9a-f]{32}\.(?:jpg|png|gif|webp)", nom):
        raise DonneeInvalide("nom d'image invalide")
    cle = (identifiant, nom)
    with _VERROU:
        if cle in _IMAGES:
            return _IMAGES[cle]
    fiche = _fiche(identifiant)
    statut, octets = transport.requete(fiche, f"/p2p/image/{nom}", maxi=images.TAILLE_MAX)
    if statut == 403:
        raise PartageRefuse("collection")
    extension = images.type_image(octets) if statut == 200 else None
    if extension is None:
        raise DonneeInvalide("image refusée")
    resultat = (octets, images.TYPES_MIME[extension])
    with _VERROU:
        while _IMAGES and sum(len(v[0]) for v in _IMAGES.values()) + len(octets) > IMAGES_CACHE_OCTETS:
            _IMAGES.pop(next(iter(_IMAGES)))
        _IMAGES[cle] = resultat
    return resultat


# ---------------------------------------------------------------------------- rapatriement

def rapatrier(identifiant, ids):
    """Copie dans TA collection les cartes choisies chez un pair. Les cartes sont recréées à partir de ce que le
    pair envoie (titre, sous-titre, introduction, adresses de l'article et de l'image, vues, statistiques) :
    AUCUNE requête vers Wikipédia. L'horodatage est celui de maintenant ; le rang est recalculé d'après les vues
    avec TES seuils (les cartes personnalisées gardent leur thème) ; tes catégories s'appliquent."""
    ids = [i for i in ids if isinstance(i, int) and not isinstance(i, bool) and i > 0][:100]
    if not ids:
        raise DonneeInvalide("aucune carte choisie")
    d = appeler(identifiant, "/p2p/cartes?ids=" + ",".join(str(i) for i in ids), utiliser_cache=False)
    maintenant = datetime.now().astimezone().replace(microsecond=0)
    articles, ignorees, incompletes = [], 0, False
    for brute in (d.get("cartes") if isinstance(d.get("cartes"), list) else [])[:100]:
        try:
            carte = valider_carte(brute, identifiant)
        except DonneeInvalide:
            ignorees += 1
            continue
        perso = carte["personnalisee"]
        if perso:
            ignorees += 1                                 # une carte créée à la main ne se prend pas : on peut seulement la voir dans une vitrine
            continue
        image = miniature = None
        if perso:
            image = _copier_image(identifiant, brute.get("image"))
            miniature = _copier_image(identifiant, brute.get("miniature")) or image
        else:
            image = carte["image"] if carte["image"] != "no-image" else None
            miniature = carte["miniature"] if carte["miniature"] != "no-image" else image
        code = config.CODE_PERSO if perso else rarete.classer(carte["vues_moyenne"])[0]
        url = f"perso:{uuid.uuid4().hex}" if carte["url"] == "perso:visiteur" else carte["url"]
        stats_ok = None not in (carte["nb_langues"], carte["taille_octets"], carte["nb_revisions"],
                                carte["nb_liens_entrants"])
        incompletes = incompletes or (not stats_ok and not perso)
        fa_local = _copier_fullart(identifiant, carte.get("fullart"))      # le full-art suit la carte : ses calques sont copiés chez toi
        articles.append({
            "_fullart": fa_local, "_cadrage": carte.get("cadrage"),
            "titre": carte["titre"], "description": carte["description"], "intro": carte["intro"], "rarete": code,
            "rarete_tiree": code, "tire_le": maintenant, "vues_moyenne": carte["vues_moyenne"],
            "vues_total": carte["vues_total"], "url": url, "image": image or "no-image",
            "miniature": miniature or "no-image", "langue": carte["langue"], "nb_langues": carte["nb_langues"],
            "taille_octets": carte["taille_octets"], "nb_revisions": carte["nb_revisions"],
            "revisions_plafonnees": carte["revisions_plafonnees"], "nb_liens_entrants": carte["nb_liens_entrants"],
            "personnalisee": perso, "surnom": carte["surnom"], "style": carte["style"]})
    if not articles:
        return {"importes": 0, "ignorees": ignorees, "deja": 0, "total": _total()}
    with base.connexion_rapide() as conn:
        avant_total = base.compter(conn)
        urls = [a["url"] for a in articles if not a["url"].startswith("perso:")]
        deja = sum(1 for u in set(urls) if base.compter_par_url(conn, [u]).get(u))
        ids_alignes = base.ajouter_cartes(conn, [{k: v for k, v in a.items() if k not in ("_fullart", "_cadrage")} for a in articles])
        for art, nouvelle_id in zip(articles, ids_alignes):   # le cadrage de l'illustration suit la carte (sans écraser celui que la carte a déjà reçu ici)
            fichier = art.get("image") if art.get("image") not in (None, "no-image") else art.get("miniature")
            if art.get("_cadrage") and fichier and art.get("url") and base.cadrage_carte_lire(conn, nouvelle_id) is None:
                z = art["_cadrage"]
                try:
                    base.cadrage_ecrire_carte(conn, nouvelle_id, art["url"], cadrage.cle_image(fichier), z["zoom"], z["x"], z["y"], z.get("ratio"), modele="si_absent")
                except ValueError:
                    pass
        avec_fullart = 0
        for numero, nouvel_id in enumerate(ids_alignes):
            fa = articles[numero].get("_fullart")
            if fa and not base.fullart_existe(conn, nouvel_id):
                try:
                    base.fullart_ecrire(conn, nouvel_id, fa["zuul"], fa["gozer"], fa["effets"])
                    avec_fullart += 1
                except (ValueError, base.DejaFullArt):
                    pass
        identifiants = list(dict.fromkeys(ids_alignes))
        if config.CATEGORIES_AUTO:
            base.classer_automatiquement(conn, identifiants)
        total = base.compter(conn)
    if incompletes:
        stats.reveiller()                       # le propriétaire n'avait pas toutes les statistiques : le fil de fond complète
    # Nombre RÉELLEMENT ajouté : une carte déjà rapatriée à la même seconde (double clic) n'est pas dupliquée.
    return {"importes": total - avant_total, "ignorees": ignorees, "deja": deja, "total": total, "fullart": avec_fullart}


def _copier_fullart(identifiant, fa):
    """Le full-art d'une carte rapatriée : les calques sont téléchargés chez le pair, vérifiés et rangés dans TES dossiers « zuul » et « gozer »
    (sans jamais écraser un fichier existant) ; renvoie {"zuul", "gozer", "effets"} avec les noms LOCAUX, ou None s'il n'y a rien à copier.
    Un calque qui ne peut pas être récupéré est simplement omis : la carte arrive quand même (avec les autres calques et les effets)."""
    if not fa:
        return None
    noms = {}
    for genre in ("zuul", "gozer"):
        nom = fa.get(genre) or ""
        noms[genre] = ""
        if not nom:
            continue
        try:
            octets = fullart_relais(identifiant, genre, nom)
            noms[genre] = fullart.enregistrer_calque(genre, nom, octets)
        except (DonneeInvalide, PartageRefuse, PairInconnu, transport.TransportErreur, ValueError):
            noms[genre] = ""
    effets = [e for e in (fa.get("effets") or []) if e in fullart.EFFETS][:fullart.EFFETS_MAX]
    if not (noms["zuul"] or noms["gozer"] or effets):
        return None
    return {"zuul": noms["zuul"], "gozer": noms["gozer"], "effets": effets}


def _total():
    with base.connexion_rapide() as conn:
        return base.compter(conn)


def _copier_image(identifiant, description):
    """Rapatrie l'image locale d'une carte personnalisée : téléchargée chez le pair, vérifiée, rangée chez toi."""
    if not (isinstance(description, dict) and description.get("type") == "locale"):
        return None
    try:
        octets, _ = image_relais(identifiant, description.get("nom"))
        return images.enregistrer(octets)
    except (DonneeInvalide, PartageRefuse, transport.TransportErreur, images.ImageRefusee, OSError):
        return None
