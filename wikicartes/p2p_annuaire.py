"""L'annuaire des collectionneurs que ce nœud connaît (table p2p_pairs) : fiches signées, déjà vérifiées.

Il n'y a pas de serveur central : chaque nœud garde sa propre vue du réseau, qu'il enrichit en demandant aux pairs
qu'il connaît les fiches qu'ils connaissent (bouche à oreille, « gossip »). Les fiches se remettent à jour toutes
seules (un nœud actif republie la sienne régulièrement : sa date sert de battement de cœur).
"""

import json
import random
import time
import unicodedata

from . import base, p2p_identite as ident

FRAICHEUR = 90 * 60               # une fiche de moins de 90 minutes = pair en ligne
EXPIRATION_PSEUDO = 30 * 86400    # un pair muet depuis 30 jours ne bloque plus son pseudo
CAPACITE = 3000                   # fiches gardées au maximum
PAR_PAGE_MAX = 60
TRIS = {"pseudo": "pseudo", "collection": "collection", "cartes": "cartes", "recents": "recents"}


def _normaliser(texte):
    t = unicodedata.normalize("NFKD", (texte or "").casefold())
    return "".join(c for c in t if not unicodedata.combining(c))


def fusionner(conn, fiche, source=None, maintenant=None, forcer=False):
    """Range une fiche DÉJÀ VÉRIFIÉE (verifier_fiche) dans l'annuaire : seule la plus récente de chaque pair est
    gardée. `forcer` : pour MA propre fiche (je sais qu'elle est la plus récente). Renvoie True si l'annuaire a changé."""
    maintenant = int(time.time() if maintenant is None else maintenant)
    existant = conn.execute("SELECT t FROM p2p_pairs WHERE id = ?", (fiche["id"],)).fetchone()
    if existant is not None and existant["t"] >= fiche["t"] and not forcer:
        return False
    if existant is None:
        total = conn.execute("SELECT COUNT(*) FROM p2p_pairs").fetchone()[0]
        if total >= CAPACITE:                                             # plein : on écarte la fiche la plus vieille
            vieux = conn.execute("SELECT id, t FROM p2p_pairs ORDER BY t ASC LIMIT 1").fetchone()
            if vieux is None or vieux["t"] >= fiche["t"]:
                return False
            conn.execute("DELETE FROM p2p_pairs WHERE id = ?", (vieux["id"],))
    pseudo = fiche["pseudo"]
    conn.execute(
        "INSERT INTO p2p_pairs (id, fiche_json, pseudo_cle, pseudo, collection, nb_cartes, profil, collection_ok, "
        "t, depuis, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET fiche_json = excluded.fiche_json, pseudo_cle = excluded.pseudo_cle, "
        "pseudo = excluded.pseudo, collection = excluded.collection, nb_cartes = excluded.nb_cartes, "
        "profil = excluded.profil, collection_ok = excluded.collection_ok, t = excluded.t, "
        "depuis = excluded.depuis",
        (fiche["id"], json.dumps(fiche, sort_keys=True, ensure_ascii=False),
         ident.cle_pseudo(pseudo) if pseudo else None, pseudo, fiche["collection"], fiche["cartes"],
         1 if fiche["p"] else 0, 1 if fiche["c"] else 0, fiche["t"], fiche["depuis"], source))
    return True


def fiche_de(conn, identifiant):
    """La fiche (dictionnaire) d'un pair connu, ou None."""
    ligne = conn.execute("SELECT fiche_json FROM p2p_pairs WHERE id = ?", (identifiant,)).fetchone()
    return json.loads(ligne["fiche_json"]) if ligne else None


def oublier(conn, identifiant):
    conn.execute("DELETE FROM p2p_pairs WHERE id = ?", (identifiant,))


def marquer_vu(conn, identifiant, maintenant=None):
    conn.execute("UPDATE p2p_pairs SET vu_le = ?, echecs = 0 WHERE id = ?",
                 (int(time.time() if maintenant is None else maintenant), identifiant))


def marquer_echec(conn, identifiant):
    conn.execute("UPDATE p2p_pairs SET echecs = echecs + 1 WHERE id = ?", (identifiant,))


def nettoyer(conn, maintenant=None):
    """Retire les fiches périmées (plus de 60 jours sans mise à jour). Renvoie leur nombre."""
    limite = int(time.time() if maintenant is None else maintenant) - ident.AGE_MAX_FICHE
    return conn.execute("DELETE FROM p2p_pairs WHERE t < ?", (limite,)).rowcount


# ------------------------------------------------------------------------------------------ pseudo

def gagnants(conn, maintenant=None):
    """{clé de pseudo: identifiant du pair qui le détient} : à clé équivalente, la revendication la plus ancienne
    gagne (puis l'identifiant le plus petit). Les pairs muets depuis 30 jours ne comptent plus."""
    limite = int(time.time() if maintenant is None else maintenant) - EXPIRATION_PSEUDO
    resultat = {}
    for ligne in conn.execute("SELECT id, pseudo_cle, depuis FROM p2p_pairs WHERE pseudo_cle IS NOT NULL "
                              "AND t >= ? ORDER BY depuis ASC, id ASC", (limite,)):
        resultat.setdefault(ligne["pseudo_cle"], ligne["id"])
    return resultat


def pseudo_pris(conn, pseudo, mon_id, maintenant=None):
    """Ce pseudo (ou un équivalent) est-il déjà détenu par un AUTRE pair que ce nœud connaît ?"""
    detenteur = gagnants(conn, maintenant).get(ident.cle_pseudo(pseudo))
    return detenteur is not None and detenteur != mon_id


def mon_pseudo(conn):
    ligne = conn.execute("SELECT pseudo, pseudo_depuis FROM p2p_moi WHERE id = 1").fetchone()
    return (ligne["pseudo"], ligne["pseudo_depuis"] or 0) if ligne and ligne["pseudo"] else (None, 0)


def definir_pseudo(conn, pseudo, depuis=None):
    conn.execute("UPDATE p2p_moi SET pseudo = ?, pseudo_depuis = ? WHERE id = 1",
                 (pseudo, int(time.time() if depuis is None else depuis) if pseudo else None))


# ---------------------------------------------------------------------------------------- liste

def etat_pastille(drapeau, frais):
    """« vert » : accepté et pair en ligne ; « rouge » : refusé par le propriétaire ; « gris » : accepté mais pair
    hors ligne ou pas encore vu (on ne sait pas)."""
    if not drapeau:
        return "rouge"
    return "vert" if frais else "gris"


def lister(conn, mon_id, q="", p=None, c=None, min_cartes=0, en_ligne=False, tri="pseudo", page=1,
           par_page=30, maintenant=None):
    """La liste du Hall : uniquement les pairs avec un pseudo (c'est lui qui les rend trouvables). Filtres :
    texte (pseudo, collection, repère), pastille P ou C verte, nombre de cartes minimum, en ligne."""
    maintenant = int(time.time() if maintenant is None else maintenant)
    gagnant = gagnants(conn, maintenant)
    lignes = conn.execute("SELECT * FROM p2p_pairs WHERE pseudo IS NOT NULL").fetchall()
    mots = [m for m in _normaliser(q).split() if m]
    sortie = []
    for l in lignes:
        frais = maintenant - l["t"] < FRAICHEUR or (l["vu_le"] or 0) > maintenant - FRAICHEUR
        moi = l["id"] == mon_id
        pastille_p, pastille_c = etat_pastille(l["profil"], frais), etat_pastille(l["collection_ok"], frais)
        if moi:
            pastille_p, pastille_c = etat_pastille(l["profil"], True), etat_pastille(l["collection_ok"], True)
            frais = True
        cible = _normaliser(f"{l['pseudo']} {l['collection']} {l['id'][:4]}")
        if any(m not in cible for m in mots):
            continue
        if p and pastille_p != "vert" or c and pastille_c != "vert":
            continue
        if l["nb_cartes"] < min_cartes or (en_ligne and not frais):
            continue
        conflit = gagnant.get(l["pseudo_cle"], l["id"]) != l["id"]
        sortie.append({"id": l["id"], "pseudo": l["pseudo"], "repere": ident.repere(l["id"]),
                       "collection": l["collection"], "cartes": l["nb_cartes"], "p": pastille_p, "c": pastille_c,
                       "en_ligne": frais, "conflit": conflit, "moi": moi, "t": l["t"],
                       "transport": json.loads(l["fiche_json"])["transport"]})
    cles = {"pseudo": lambda x: (_normaliser(x["pseudo"]), x["id"]),
            "collection": lambda x: (_normaliser(x["collection"]), x["id"]),
            "cartes": lambda x: (-x["cartes"], _normaliser(x["pseudo"])),
            "recents": lambda x: (-x["t"], x["id"])}
    sortie.sort(key=cles.get(tri, cles["pseudo"]))
    par_page = max(1, min(PAR_PAGE_MAX, int(par_page)))
    total = len(sortie)
    pages = max(1, -(-total // par_page))
    page = max(1, min(int(page), pages))
    return {"pairs": sortie[(page - 1) * par_page:page * par_page], "total": total, "page": page, "pages": pages}


def echantillon_gossip(conn, n=200, maintenant=None):
    """Des fiches fraîches (au hasard, 200 au plus) à transmettre à un pair qui en demande."""
    limite = int(time.time() if maintenant is None else maintenant) - 14 * 86400
    lignes = conn.execute("SELECT fiche_json FROM p2p_pairs WHERE t >= ?", (limite,)).fetchall()
    random.shuffle(lignes)
    return [json.loads(l["fiche_json"]) for l in lignes[:max(1, min(200, n))]]


def pairs_a_contacter(conn, n=5, mon_id=None, maintenant=None):
    """Des pairs en ligne (fiche fraîche) à interroger pour découvrir d'autres fiches."""
    limite = int(time.time() if maintenant is None else maintenant) - FRAICHEUR
    lignes = conn.execute("SELECT id FROM p2p_pairs WHERE t >= ? AND echecs < 5 AND id != ?",
                          (limite, mon_id or "")).fetchall()
    random.shuffle(lignes)
    return [l["id"] for l in lignes[:n]]


def invitation(fiche):
    """Le texte à donner à quelqu'un pour qu'il te trouve : « wcp1:<identifiant> » (Tor : l'adresse se déduit de
    la clé) ou « wcp1:<identifiant>@hôte:port »."""
    return f"wcp1:{fiche['id']}" + (f"@{fiche['adresse']}" if fiche["transport"] != "tor" else "")


def lire_invitation(texte):
    """(identifiant, adresse ou None) d'une invitation, ou ValueError."""
    import re
    if not isinstance(texte, str):
        raise ValueError("invitation invalide (attendu : wcp1:<identifiant>[@hôte:port])")
    trouve = re.fullmatch(r"wcp1:([a-z2-7]{52})(?:@([A-Za-z0-9._\-\[\]:]{1,100}:\d{1,5}))?", texte.strip())
    if not trouve:
        raise ValueError("invitation invalide (attendu : wcp1:<identifiant>[@hôte:port])")
    ident.pub_depuis_id(trouve.group(1))
    return trouve.group(1), trouve.group(2)
