"""Les actions de la page « Hall des collections » (côté serveur local) : ton pseudo, ton partage, la liste des
collectionneurs, la visite d'un profil ou d'une collection, le rapatriement de cartes.

Chaque fonction renvoie (statut HTTP, dictionnaire JSON). Rien ici ne partage quoi que ce soit : les données que
les autres voient sont celles du serveur pair à pair (partage.py), décidées par tes pastilles P et C.
"""

import re
import threading

from . import (base, config, p2p_annuaire as annuaire, p2p_client as client, p2p_identite as ident, p2p_service,
               p2p_tor, p2p_transport as transport, parametres, rendu)

SERVICE = p2p_service.SERVICE


def _identite(creer=False):
    return ident.charger_ou_creer(creer=creer) if ident.DISPONIBLE else None


def etat_moi():
    """Mon état : pseudo, pastilles, invitation, état du nœud."""
    identite = _identite()
    pseudo, depuis = (None, 0)
    with base.connexion_lecture() as conn:
        if identite is not None:
            pseudo, depuis = annuaire.mon_pseudo(conn)
        cartes = base.compter(conn)
    invitation, avertissement = None, None
    if identite is not None:
        try:
            invitation = annuaire.invitation(SERVICE.ma_fiche())
        except transport.TransportErreur as erreur:
            avertissement = str(erreur)
    return {"disponible": ident.DISPONIBLE, "identite": identite is not None, "id": identite.id if identite else None,
            "repere": ident.repere(identite.id) if identite else None, "pseudo": pseudo,
            "etiquette": ident.etiquette(pseudo, identite.id) if identite and pseudo else None,
            "invitation": invitation, "avertissement": avertissement, "actif": bool(config.P2P_ACTIF),
            "profil": bool(config.P2P_PROFIL_PUBLIC), "collection": bool(config.P2P_COLLECTION_PUBLIQUE),
            "mode": config.P2P_TRANSPORT, "service": SERVICE.etat(), "cartes": cartes,
            "onion": identite.onion if identite else None, "tor": p2p_tor.etat_pour_page()}


def definir_pseudo(demande):
    if not ident.DISPONIBLE:
        return 501, {"erreur": "le partage demande : pip install cryptography"}
    try:
        pseudo = ident.valider_pseudo(demande.get("pseudo") if isinstance(demande, dict) else None)
    except ValueError as erreur:
        return 400, {"erreur": str(erreur)}
    identite = _identite(creer=True)
    with base.connexion_rapide() as conn:
        if annuaire.pseudo_pris(conn, pseudo, identite.id):
            return 409, {"erreur": "ce pseudo est déjà pris (ou trop proche d'un pseudo existant) dans le réseau que "
                                   "ton nœud connaît : choisis-en un autre"}
        ancien, depuis = annuaire.mon_pseudo(conn)
        garde = ancien and ident.cle_pseudo(ancien) == ident.cle_pseudo(pseudo)     # même pseudo : on garde l'ancienneté
        annuaire.definir_pseudo(conn, pseudo, depuis if garde else None)
    try:
        SERVICE.publier_localement()
    except transport.TransportErreur:
        pass                                    # adresse publique pas encore réglée : le pseudo est quand même créé
    SERVICE.reveiller()
    return 200, etat_moi()


def supprimer_pseudo():
    identite = _identite()
    if identite is None:
        return 200, etat_moi()
    with base.connexion_rapide() as conn:
        annuaire.definir_pseudo(conn, None)
    try:
        SERVICE.publier_localement()
    except transport.TransportErreur:
        pass
    SERVICE.reveiller()
    return 200, etat_moi()


def reinitialiser_identite(demande):
    """Supprime la clé : nouvelle identité, nouvel identifiant (l'ancien disparaît du réseau), pseudo effacé."""
    if not (isinstance(demande, dict) and demande.get("confirme") is True):
        return 400, {"erreur": "confirmation attendue"}
    identite = _identite()
    SERVICE.arreter()
    with base.connexion_rapide() as conn:
        annuaire.definir_pseudo(conn, None)
        if identite is not None:
            annuaire.oublier(conn, identite.id)
    ident.supprimer_identite()
    SERVICE._cache = (0.0, None)
    if config.P2P_ACTIF:
        SERVICE.demarrer()
    return 200, etat_moi()


def partage(demande):
    """Active ou coupe mon nœud, et règle les pastilles P et C (profil et collection visibles)."""
    if not isinstance(demande, dict):
        return 400, {"erreur": "demande invalide"}
    noms = {"actif": "P2P_ACTIF", "profil": "P2P_PROFIL_PUBLIC", "collection": "P2P_COLLECTION_PUBLIQUE"}
    valeurs = {}
    for cle, nom in noms.items():
        if cle in demande:
            if not isinstance(demande[cle], bool):
                return 400, {"erreur": f"{cle} : vrai ou faux attendu"}
            valeurs[nom] = demande[cle]
    if not valeurs:
        return 400, {"erreur": "aucun réglage reçu"}
    if valeurs.get("P2P_ACTIF") and not ident.DISPONIBLE:
        return 501, {"erreur": "le partage demande : pip install cryptography"}
    try:
        with base.connexion_rapide() as conn:
            parametres.enregistrer_tout(conn, valeurs)
    except parametres.ValeursInvalides as erreur:
        return 400, {"erreur": f"réglage refusé : {erreur.erreurs}"}
    if "P2P_ACTIF" in valeurs:
        SERVICE.appliquer_reglages()
    elif _identite() is not None:
        try:
            SERVICE.publier_localement()        # les pastilles changent : la fiche est republiée tout de suite
        except transport.TransportErreur:
            pass
        SERVICE.reveiller()
    return 200, etat_moi()


def liste(demande):
    if not isinstance(demande, dict):
        return 400, {"erreur": "demande invalide"}
    identite = _identite()
    try:
        q = str(demande.get("q", ""))[:60]
        minimum = int(demande.get("min_cartes", 0) or 0)
        page = int(demande.get("page", 1) or 1)
    except (TypeError, ValueError):
        return 400, {"erreur": "valeurs invalides"}
    with base.connexion_rapide() as conn:
        resultat = annuaire.lister(conn, identite.id if identite else "", q=q, p=demande.get("p") is True,
                                   c=demande.get("c") is True, min_cartes=max(0, min(minimum, 10**7)),
                                   en_ligne=demande.get("en_ligne") is True,
                                   tri=str(demande.get("tri", "pseudo")), page=max(1, page), par_page=30)
    return 200, resultat


def contact(demande):
    texte = demande.get("invitation") if isinstance(demande, dict) else None
    if not isinstance(texte, str) or len(texte) > 200:
        return 400, {"erreur": "invitation invalide"}
    try:
        fiche = SERVICE.ajouter_contact(texte)
    except ValueError as erreur:
        return 400, {"erreur": str(erreur)}
    except transport.TransportErreur as erreur:
        return 502, {"erreur": f"collectionneur injoignable : {erreur}"}
    except ident.FicheInvalide as erreur:
        return 502, {"erreur": f"fiche refusée : {erreur}"}
    return 200, {"ok": True, "pseudo": fiche["pseudo"], "collection": fiche["collection"], "id": fiche["id"]}


def actualiser():
    """Demande au réseau d'actualiser (en arrière-plan : cela peut prendre quelques secondes, surtout via Tor)."""
    def travail():
        try:
            SERVICE.publier_localement()
        except Exception:
            pass
        try:
            SERVICE.decouvrir()
        except Exception:
            pass
    threading.Thread(target=travail, daemon=True).start()
    return 202, {"ok": True}


def tor_lancer(demande):
    """« Lancer Tor » : lance le programme Tor trouvé sur la machine (torrc écrit par le programme), attend qu'il
    réponde, puis republie ton service oignon si ton nœud est actif."""
    try:
        p2p_tor.lancer()
    except p2p_tor.TorIntrouvable as erreur:
        return 404, {"erreur": str(erreur), "tor": p2p_tor.etat_pour_page()}
    except p2p_tor.TorEchec as erreur:
        return 502, {"erreur": str(erreur), "tor": p2p_tor.etat_pour_page()}
    if config.P2P_ACTIF:
        SERVICE.appliquer_reglages()
    return 200, {"ok": True, "tor": p2p_tor.etat_pour_page()}


def tor_auto(demande):
    """Case « Lancer Tor au démarrage du programme »."""
    valeur = demande.get("auto") if isinstance(demande, dict) else None
    if not isinstance(valeur, bool):
        return 400, {"erreur": "vrai ou faux attendu"}
    with base.connexion_rapide() as conn:
        parametres.enregistrer_tout(conn, {"P2P_TOR_AUTO": valeur})
    return 200, {"ok": True, "tor": p2p_tor.etat_pour_page()}


def tor_arreter(demande):
    """Arrête le Tor que CE programme a lancé (jamais un autre)."""
    p2p_tor.arreter()
    SERVICE.arreter()
    return 200, {"ok": True, "tor": p2p_tor.etat_pour_page()}


def _erreur(erreur):
    if isinstance(erreur, client.PartageRefuse):
        quoi = "profil" if erreur.quoi == "profil" else "collection"
        return 403, {"refus": quoi, "erreur": f"Ce collectionneur n'autorise pas la consultation de son {quoi} "
                                              "(pastille rouge)."}
    if isinstance(erreur, client.PairInconnu):
        return 404, {"erreur": "collectionneur inconnu : actualise la liste du Hall"}
    if isinstance(erreur, transport.TorErreur):
        return 502, {"erreur": f"collectionneur injoignable : {erreur} Retourne dans le Hall des collections : une aide "
                               "pour installer ou lancer Tor s'y affiche.", "tor": True}
    if isinstance(erreur, transport.TransportErreur):
        return 502, {"erreur": f"collectionneur injoignable : {erreur}"}
    if isinstance(erreur, client.DonneeInvalide):
        return 502, {"erreur": f"réponse refusée (données invalides) : {erreur}"}
    raise erreur


def _pair(demande):
    pair = demande.get("pair") if isinstance(demande, dict) else None
    try:
        ident.pub_depuis_id(pair)
    except ValueError:
        return None
    return pair


def _resume_json(apparence, resume):
    rangs = [{"code": r["code"], "symbole": r["symbole"], "nom": r["nom"], "n": resume["rangs"].get(r["code"], 0)}
             for r in apparence["rangs"]]
    if resume["rangs"].get(config.CODE_PERSO):
        rangs.append({"code": config.CODE_PERSO, "symbole": apparence["perso"]["symbole"],
                      "nom": apparence["perso"]["nom"], "n": resume["rangs"][config.CODE_PERSO]})
    return {"total": resume["total"], "rangs": rangs, "categories": resume["categories"],
            "sans_categorie": resume["sans_categorie"]}


def _bilan(donnees):
    categories = [{"nom": c["nom"], "couleur": c["couleur"], "nb_cartes": c["n"]} for c in donnees["resume"]["categories"]]
    if donnees["resume"]["sans_categorie"]:
        categories = categories      # « sans catégorie » est proposé dans le filtre de la collection
    return rendu.html_bilan(donnees["resume"]["total"], donnees["resume"]["rangs"], categories,
                            apparence=donnees["apparence"], qui="dans sa collection")


def collection(demande):
    pair = _pair(demande)
    if pair is None:
        return 400, {"erreur": "collectionneur invalide"}
    rangs = demande.get("rangs") if isinstance(demande.get("rangs"), list) else []
    try:
        donnees = client.collection_distante(
            pair, rangs=[r for r in rangs if isinstance(r, str)][:12], categorie=str(demande.get("categorie", ""))[:40],
            q=str(demande.get("q", ""))[:100], tri=str(demande.get("tri", ""))[:20],
            page=int(demande.get("page", 1) or 1), par_page=int(demande.get("par_page", config.CARTES_PAR_PAGE) or 24))
    except (client.PartageRefuse, client.PairInconnu, transport.TransportErreur, client.DonneeInvalide) as erreur:
        return _erreur(erreur)
    except (TypeError, ValueError):
        return 400, {"erreur": "valeurs invalides"}
    # Pas de bloc de résumé (nombre de cartes + rangs) dans la collection : les rangs et les catégories avec leur nombre
    # sont déjà dans la barre de filtres juste en dessous (il reste dans le PROFIL).
    return 200, {"titre": donnees["site"]["titre"], "bio": donnees["site"]["bio"],
                 "resume": _resume_json(donnees["apparence"], donnees["resume"]),
                 "css": client.css_apparence(donnees["apparence"]), "cartes_html": rendu.html_visite_cartes(donnees["cartes"]),
                 "page": donnees["page"], "pages": donnees["pages"], "total_filtre": donnees["total_filtre"],
                 "total": donnees["total"], "ecartees": donnees["ecartees"],
                 "tris": {k: v[0] for k, v in base.TRIS.items()}}


def profil(demande):
    pair = _pair(demande)
    if pair is None:
        return 400, {"erreur": "collectionneur invalide"}
    try:
        donnees = client.profil_distant(pair)
    except (client.PartageRefuse, client.PairInconnu, transport.TransportErreur, client.DonneeInvalide) as erreur:
        return _erreur(erreur)
    meta = donnees.get("photo")
    return 200, {"titre": donnees["site"]["titre"], "bio": donnees["site"]["bio"], "bilan_html": _bilan(donnees),
                 "css": client.css_apparence(donnees["apparence"]),
                 "vitrines_html": rendu.html_visite_vitrines(donnees["vitrines"]), "total": donnees["resume"]["total"],
                 "photo_url": None if not meta else f"/hall/photo?pair={pair}&v={meta['empreinte']}"}


def rapatrier(demande):
    pair = _pair(demande)
    ids = demande.get("ids") if isinstance(demande, dict) else None
    if pair is None or not isinstance(ids, list) or not ids or len(ids) > 100:
        return 400, {"erreur": "choisis entre 1 et 100 cartes"}
    try:
        resultat = client.rapatrier(pair, ids)
    except (client.PartageRefuse, client.PairInconnu, transport.TransportErreur) as erreur:
        return _erreur(erreur)
    except client.DonneeInvalide as erreur:
        return 400, {"erreur": str(erreur)}
    return 200, resultat


def fullart_calque(pair, genre, nom):
    """(statut, octets, type) d'un calque de full-art d'une carte d'un pair (relayé par ton nœud)."""
    try:
        ident.pub_depuis_id(pair)
        octets = client.fullart_relais(pair, genre, nom)
    except (ValueError, client.DonneeInvalide):
        return 404, b"", "text/plain"
    except client.PartageRefuse:
        return 403, b"", "text/plain"
    except (client.PairInconnu, transport.TransportErreur):
        return 502, b"", "text/plain"
    return 200, octets, "image/png"


def photo(pair, empreinte=""):
    """(statut, octets, type) de la photo de profil d'un pair (relayée par ton nœud)."""
    try:
        ident.pub_depuis_id(pair)
        octets, type_mime = client.photo_relais(pair, empreinte if re.fullmatch(r"[0-9a-f]{16}", empreinte or "") else None)
    except (ValueError, client.DonneeInvalide):
        return 404, b"", "text/plain"
    except client.PartageRefuse:
        return 403, b"", "text/plain"
    except (client.PairInconnu, transport.TransportErreur):
        return 502, b"", "text/plain"
    return 200, octets, type_mime


def image(pair, nom):
    """(statut, octets, type) d'une image de carte personnalisée d'un pair (relayée par ton nœud)."""
    try:
        ident.pub_depuis_id(pair)
        octets, type_mime = client.image_relais(pair, nom)
    except (ValueError, client.DonneeInvalide):
        return 404, b"", "text/plain"
    except client.PartageRefuse:
        return 403, b"", "text/plain"
    except (client.PairInconnu, transport.TransportErreur):
        return 502, b"", "text/plain"
    return 200, octets, type_mime


ROUTES = {
    "/api/hall/etat": lambda d: (200, etat_moi()),
    "/api/hall/pseudo": definir_pseudo,
    "/api/hall/pseudo/supprimer": lambda d: supprimer_pseudo(),
    "/api/hall/identite/reinitialiser": reinitialiser_identite,
    "/api/hall/partage": partage,
    "/api/hall/liste": liste,
    "/api/hall/contact": contact,
    "/api/hall/actualiser": lambda d: actualiser(),
    "/api/hall/collection": collection,
    "/api/hall/profil": profil,
    "/api/hall/rapatrier": rapatrier,
    "/api/hall/tor": lambda d: (200, p2p_tor.etat_pour_page()),
    "/api/hall/tor/lancer": tor_lancer,
    "/api/hall/tor/auto": tor_auto,
    "/api/hall/tor/arreter": tor_arreter,
}
