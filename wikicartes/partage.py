"""Ce que ce nœud montre aux autres collectionneurs : des données en LECTURE SEULE, minimales.

Tout est construit à partir de la base ouverte en lecture seule (base.connexion_lecture) et d'une LISTE BLANCHE
de champs : un champ qui n'est pas listé ici n'est jamais envoyé. Ne partent JAMAIS : tes favoris, ta corbeille,
tes réglages, ta configuration, tes catégories automatiques, tes dossiers, ton adresse, ton e-mail de contact,
ni rien d'autre que ce qui est décrit ci-dessous. Les pastilles P (profil) et C (collection) sont appliquées ICI,
côté propriétaire : un visiteur ne peut pas les contourner.
"""

import re

from . import api, base, cadrage, config, fullart, images, photo, theme

PAR_PAGE_MAX = 60
IDS_MAX = 100
_NOM_CATEGORIE_MAX = 40


class Refuse(Exception):
    """Le propriétaire n'a pas autorisé ce partage (pastille rouge) : `quoi` vaut « profil » ou « collection »."""

    def __init__(self, quoi):
        super().__init__(quoi)
        self.quoi = quoi


def _image(adresse):
    """Une image de carte : adresse Wikimedia (le visiteur la charge lui-même) ou image locale d'une carte
    personnalisée (le visiteur la reçoit par ce nœud) ; sinon rien."""
    if not adresse:
        return None
    nom = images.nom_depuis_adresse(adresse)
    if nom:
        return {"type": "locale", "nom": nom}
    if api.adresse_wikimedia(adresse):
        return {"type": "wikimedia", "url": adresse}
    return None


def _categories(carte):
    return [{"nom": c["nom"][:_NOM_CATEGORIE_MAX], "couleur": c["couleur"]}
            for c in carte.get("categories", []) if c.get("id", 0) > 0]      # seulement les catégories créées


def carte_publique(carte):
    """Une carte (au format de base._depuis_ligne) -> le dictionnaire envoyé aux autres (liste blanche)."""
    perso = bool(carte.get("personnalisee"))
    url = carte["url"] if carte.get("url") and not str(carte["url"]).startswith("perso:") else None
    return {
        "id": int(carte["id"]), "titre": carte["titre"],
        "description": None if carte["description"] == "no-description" else carte["description"],
        "intro": None if carte["intro"] == "no-intro" else carte["intro"],
        "rarete": carte["rarete"], "rarete_nom": carte["rarete_nom"], "url": url,
        "image": _image(None if carte["image"] == "no-image" else carte["image"]),
        "miniature": _image(None if carte["miniature"] == "no-image" else carte["miniature"]),
        "langue": carte["langue"], "vues_moyenne": float(carte["vues_moyenne"]),
        "vues_total": int(carte["vues_total"]), "tire_le": carte["tire_le"].isoformat(timespec="seconds"),
        "stats": {"langues": carte["nb_langues"], "taille": carte["taille_octets"],
                  "modifications": carte["nb_revisions"], "plafonne": bool(carte["revisions_plafonnees"]),
                  "liens": carte["nb_liens_entrants"]},
        "categories": _categories(carte), "perso": perso, "surnom": carte["surnom"] if perso else "",
        "style": carte["style"] if perso else None,
        "fullart": fullart.public(carte.get("fullart")),          # calques et effets du full-art (les fichiers se demandent à part)
        "gif_anime": carte.get("gif_anime") if carte.get("gif_anime") in (0, 1) else None,         # GIF animé (1), fixe (0) ou pas encore vérifié
        "cadrage": cadrage.propre(carte.get("cadrage")),                                           # position et agrandissement de l'illustration
    }


def site():
    """Titre et biographie du site (ce que le visiteur voit en en-tête)."""
    return {"titre": config.TITRE_SITE, "bio": config.BIO_SITE}


def apparence():
    """De quoi afficher les cartes EXACTEMENT comme chez leur propriétaire : rangs (nom, lettres, thème),
    palier « Personnalisée » et angles des cartes. Aucun autre réglage."""
    rangs = [{"code": code, "nom": nom, "symbole": config.symbole(code),
              "theme": theme.theme_du_rang(config.THEMES_PALIERS, code)} for code, _, nom in config.PALIERS]
    return {"rangs": rangs,
            "perso": {"symbole": config.PERSO_SYMBOLE, "nom": config.PERSO_NOM, "theme": config.PERSO_THEME},
            "angles": config.ANGLES_CARTES}


def resume(conn):
    """Nombre de cartes, par rang et par catégorie (« Sport (5) »), et sans catégorie. Les cartes créées à la main n'y comptent PAS : elles ne sont
    pas partagées (on ne les voit que dans les vitrines du profil)."""
    categories = []
    for c in base.lister_categories(conn):
        n = conn.execute("SELECT COUNT(*) FROM cartes_categories x JOIN cartes k ON k.id = x.carte_id "
                         "WHERE x.categorie_id = ? AND k.supprime_le IS NULL AND k.personnalisee = 0", (c["id"],)).fetchone()[0]
        categories.append({"nom": c["nom"][:_NOM_CATEGORIE_MAX], "couleur": c["couleur"], "n": n})
    rangs = {ligne[0]: ligne[1] for ligne in conn.execute("SELECT rarete, COUNT(*) FROM cartes WHERE supprime_le IS NULL AND personnalisee = 0 GROUP BY rarete")}
    sans = conn.execute("SELECT COUNT(*) FROM cartes c WHERE c.supprime_le IS NULL AND c.personnalisee = 0 AND NOT EXISTS "
                        "(SELECT 1 FROM cartes_categories x WHERE x.carte_id = c.id)").fetchone()[0]
    return {"total": base.compter_partageables(conn), "rangs": rangs, "categories": categories, "sans_categorie": sans}


def _exiger(quoi):
    if quoi == "profil" and not config.P2P_PROFIL_PUBLIC:
        raise Refuse("profil")
    if quoi == "collection" and not config.P2P_COLLECTION_PUBLIQUE:
        raise Refuse("collection")


def profil(conn):
    """Le profil : site, apparence, résumé et vitrines (cartes exposées). Refusé si la pastille P est rouge."""
    _exiger("profil")
    titres = base.titres_vitrines(conn)
    cartes = base.cartes_des_vitrines(conn, config.PROFIL_VITRINES, config.PROFIL_EMPLACEMENTS)
    vitrines = [{"titre": titres.get(v, ""),
                 "emplacements": [carte_publique(cartes[(v, e)]) if (v, e) in cartes else None
                                  for e in range(1, int(config.PROFIL_EMPLACEMENTS) + 1)]}
                for v in range(1, int(config.PROFIL_VITRINES) + 1)]
    partagee = photo.partage_pour_le_hall()                 # la photo de profil : seulement le carré visible dans le cercle (jamais l'image d'origine)
    return {"site": site(), "apparence": apparence(), "resume": resume(conn), "vitrines": vitrines,
            "photo": None if partagee is None else {"taille": len(partagee[0]), "empreinte": partagee[2]}}


def photo_partagee(conn):
    """(octets, type MIME) de la photo de profil partagée, ou None. Refusé si la pastille P (profil) est rouge, comme le profil lui-même."""
    _exiger("profil")
    partagee = photo.partage_pour_le_hall()
    return None if partagee is None else (partagee[0], partagee[1])


def _filtres(params, conn):
    """Filtres demandés par un visiteur -> filtres de la base. Seuls rangs, catégorie (par nom), recherche et
    tri existent : pas de favoris, pas de corbeille, pas de doublons. Une valeur inconnue est ignorée."""
    codes = {c for c in config.CODES} | {config.CODE_PERSO}
    rangs = [r for r in str(params.get("rangs", "")).split(",") if r in codes][:12]
    filtres = {"rangs": rangs, "recherche": str(params.get("q", ""))[:100], "sans_personnalisees": True}      # (jamais les cartes créées à la main)
    nom = str(params.get("categorie", ""))
    if nom == "@sans":
        filtres["categorie"] = -1
    elif nom:
        trouve = next((c["id"] for c in base.lister_categories(conn) if c["nom"] == nom), None)
        filtres["categorie"] = trouve if trouve is not None else 0
    tri = str(params.get("tri", ""))
    return filtres, tri if tri in base.TRIS else base.TRI_DEFAUT


def _entier(valeur, defaut, mini, maxi):
    try:
        return max(mini, min(maxi, int(valeur)))
    except (TypeError, ValueError):
        return defaut


def collection(conn, params):
    """Une page de la collection (filtres : rangs, catégorie, recherche, tri). Refusé si la pastille C est rouge."""
    _exiger("collection")
    filtres, tri = _filtres(params, conn)
    if filtres.get("categorie") == 0:                               # catégorie inconnue : aucun résultat
        page = {"cartes": [], "page": 1, "pages": 1, "total_filtre": 0, "total": base.compter_partageables(conn)}
    else:
        page = base.lister_cartes_page(conn, filtres, _entier(params.get("page"), 1, 1, 100000),
                                       _entier(params.get("par_page"), 24, 5, PAR_PAGE_MAX), tri)
    return {"site": site(), "apparence": apparence(), "resume": resume(conn),
            "cartes": [carte_publique(c) for c in page["cartes"]], "page": page["page"],
            "pages": page["pages"], "total_filtre": page["total_filtre"], "total": base.compter_partageables(conn)}


def cartes_par_ids(conn, identifiants):
    """Les cartes demandées pour être rapatriées (100 au plus ; les cartes à la corbeille sont ignorées, et les cartes CRÉÉES À LA MAIN ne sont jamais
    données : on ne peut que les voir, dans les vitrines du profil)."""
    _exiger("collection")
    ids = []
    for x in identifiants[:IDS_MAX]:
        if isinstance(x, int) and not isinstance(x, bool) and x > 0:
            ids.append(x)
    cartes = base.cartes_par_identifiants(conn, ids) if ids else []
    return {"cartes": [carte_publique(c) for c in cartes if not c.get("supprime_le") and not c.get("personnalisee")]}


def _carte_visible(conn, condition_carte, parametres):
    """Une carte NON supprimée que les autres peuvent voir et qui répond à `condition_carte` : soit dans la collection partagée (si sa pastille est verte ;
    sans les cartes créées à la main), soit exposée dans une vitrine du profil (si la pastille du profil est verte ; les cartes créées à la main n'y sont
    visibles qu'à cet endroit)."""
    if config.P2P_COLLECTION_PUBLIQUE:
        if conn.execute(f"SELECT 1 FROM cartes c WHERE c.supprime_le IS NULL AND c.personnalisee = 0 AND ({condition_carte}) LIMIT 1", parametres).fetchone():
            return True
    if config.P2P_PROFIL_PUBLIC:
        if conn.execute(f"SELECT 1 FROM vitrine_cartes v JOIN cartes c ON c.id = v.carte_id WHERE c.supprime_le IS NULL AND v.vitrine <= ? AND v.emplacement <= ? "
                        f"AND ({condition_carte}) LIMIT 1", [int(config.PROFIL_VITRINES), int(config.PROFIL_EMPLACEMENTS)] + list(parametres)).fetchone():
            return True
    return False


def fullart_partage(conn, genre, nom):
    """Les octets d'un calque PNG du full-art (Zuul ou Gozer), seulement si une carte NON supprimée visible par les autres l'utilise (dans la collection
    partagée, ou dans une vitrine du profil) : on ne sert jamais un autre fichier du disque. None sinon."""
    if not (config.P2P_COLLECTION_PUBLIQUE or config.P2P_PROFIL_PUBLIC):
        _exiger("collection")
    if genre not in ("zuul", "gozer"):
        return None
    fichier = fullart.chemin(genre, nom)
    if fichier is None:
        return None
    if not _carte_visible(conn, f"EXISTS (SELECT 1 FROM fullart f WHERE f.carte_id = c.id AND f.{genre} = ?)", [nom]):
        return None
    try:
        if fichier.stat().st_size > fullart.TAILLE_RELAIS_MAX:
            return None
        octets = fichier.read_bytes()
    except OSError:
        return None
    return octets if fullart.png_valide(octets) else None


def image_partagee(conn, nom):
    """Les octets et le type d'une image locale (image d'une carte créée à la main, par exemple), seulement si une carte NON supprimée visible par les
    autres l'utilise : dans la collection partagée, ou dans une vitrine du profil (on ne sert jamais un autre fichier du disque)."""
    if not (config.P2P_COLLECTION_PUBLIQUE or config.P2P_PROFIL_PUBLIC):
        _exiger("collection")
    if images.chemin(nom) is None:
        return None
    adresse = "/image/" + nom
    if not _carte_visible(conn, "(c.url_image = ? OR c.url_miniature = ?)", [adresse, adresse]):
        return None
    try:
        return images.chemin(nom).read_bytes(), images.type_mime(nom)
    except OSError:
        return None
