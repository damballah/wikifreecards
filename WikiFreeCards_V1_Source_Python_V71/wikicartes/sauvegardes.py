"""Sauvegardes de WikiCartes : créer, exporter, importer et restaurer, en 4 types.

Une sauvegarde est un fichier .zip (rangé dans data/sauvegardes/archives/) :

    manifest.json    type, date, version de la base, nombre de cartes, contenu
    parametres.json  les paramètres actuels (Configuration)                        } types ultra, complète, paramètres
    collection.db    la collection : cartes, catégories, vitrines, corbeille,      } types ultra, complète, collection
                     réserve, annuaire du Hall (SANS les paramètres)
    images/          les images des cartes personnalisées (et de la collection)     } collection, complète, ultra
                     ou, pour « paramètres seuls », l'image du paquet personnalisé
    logo/            le dossier du logo                                              } paramètres, complète, ultra
    sons/            les fichiers sons et la musique (dossier sons/)                 } paramètres, complète, ultra
    programme/       toute l'arborescence du programme (code, gabarits, exports...)  } ultra seulement

Les 4 types :
    ultra       Ultra complète : paramètres actuels + collection + arborescence complète du programme
    complete    Complète : paramètres actuels + collection
    parametres  Uniquement les paramètres
    collection  Uniquement la collection

La clé secrète d'identité du Hall (data/identite_p2p.key) n'est dans AUCUNE sauvegarde, sauf si on le demande
expressément pour une sauvegarde ultra complète (case « inclure la clé » : à ne jamais partager).

Importer une sauvegarde ne change rien : elle est d'abord vérifiée (noms de fichiers sûrs, pas de lien, pas de « bombe »
de décompression, version de la base, intégrité). La RESTAURER demande une confirmation côté page, fait AVANT une sauvegarde
de sécurité de l'état actuel (« avant-restauration »), puis remplace ce que la sauvegarde contient. Pour une sauvegarde
ultra complète, les fichiers du programme ne sont jamais écrasés : ils sont extraits dans
data/restaurations/<date>/ (à toi de les récupérer).
"""

import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from . import api, base, config, images, logo, parametres, sons

FORMAT = "wikicartes-sauvegarde"
VERSION_FORMAT = 1

TYPES = {
    "ultra": {"libelle": "Ultra complète",
              "detail": "Paramètres actuels, collection et arborescence complète du programme"},
    "complete": {"libelle": "Complète", "detail": "Paramètres actuels et collection"},
    "parametres": {"libelle": "Uniquement les paramètres", "detail": "Les réglages de la Configuration"},
    "collection": {"libelle": "Uniquement la collection", "detail": "Cartes, catégories, vitrines, corbeille, réserve"},
}
AVEC_PARAMETRES = ("ultra", "complete", "parametres")
AVEC_COLLECTION = ("ultra", "complete", "collection")

NOM_FICHIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.zip")
_NOM_LOGO = re.compile(r"[A-Za-z0-9À-ÿ][A-Za-z0-9À-ÿ ._-]{0,80}")
_NOM_IMAGE = re.compile(r"[0-9a-f]{32}\.(?:jpg|png|gif|webp)")

TAILLE_MAX_IMPORT = 4 * 1024 ** 3           # 4 Go : taille maximale d'une sauvegarde importée
TAILLE_MAX_DECOMPRESSEE = 24 * 1024 ** 3    # taille maximale du contenu une fois décompressé
NB_FICHIERS_MAX = 300_000
TAILLE_MAX_JSON = 8 * 1024 * 1024
DOSSIERS_IGNORES = {"__pycache__", ".git", ".pytest_cache", "node_modules", ".idea", ".vscode"}
HOTES_ECRITURE = 1024 * 1024

_VERROU = threading.Lock()


class SauvegardeInvalide(ValueError):
    """La sauvegarde est refusée (message lisible)."""


class SauvegardeIntrouvable(FileNotFoundError):
    """Aucune sauvegarde de ce nom."""


class SauvegardeEnCours(RuntimeError):
    """Une autre sauvegarde ou restauration est déjà en cours."""


# ------------------------------------------------------------------------------------------------ dossiers et noms

def dossier():
    """Le dossier des sauvegardes créées ou importées (créé au besoin, droits 700)."""
    d = Path(config.DOSSIER_SAUVEGARDES) / "archives"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def chemin(nom):
    """Le fichier d'une sauvegarde d'après son nom (jamais un chemin libre : nom simple et fichier existant)."""
    if not isinstance(nom, str) or NOM_FICHIER.fullmatch(nom) is None:
        raise SauvegardeIntrouvable("nom de sauvegarde invalide")
    fichier = dossier() / nom
    if not fichier.is_file():
        raise SauvegardeIntrouvable("sauvegarde introuvable")
    return fichier


def _nom_libre(prefixe, type_):
    base_nom = f"{prefixe}-{type_}-{datetime.now():%Y%m%d-%H%M%S}"
    cible = dossier() / f"{base_nom}.zip"
    n = 1
    while cible.exists():
        n += 1
        cible = dossier() / f"{base_nom}-{n}.zip"
    return cible


# ------------------------------------------------------------------------------------------------ création

def _parametres_actuels(conn):
    """{nom: valeur} de tous les paramètres de la Configuration (valeurs décodées du JSON de la base)."""
    resultat = {}
    for cle, valeur in conn.execute("SELECT cle, valeur FROM parametres"):
        if cle in parametres.PARAMETRES and valeur is not None:
            try:
                resultat[cle] = json.loads(valeur)
            except ValueError:
                continue
    return resultat


def _instantane_collection(conn, destination):
    """Copie cohérente de la base dans `destination`, sans les paramètres (ils sont dans parametres.json)."""
    copie = sqlite3.connect(destination)
    try:
        conn.backup(copie)
        copie.execute("DELETE FROM parametres")
        copie.commit()
        copie.execute("VACUUM")
    finally:
        copie.close()


def _fichiers_programme(avec_cle):
    """Les fichiers de l'arborescence du programme (chemin relatif à la racine) pour une sauvegarde ultra complète.
    Ne sont PAS repris ici : ce qui a sa place dédiée dans l'archive (base, images, logo), les anciennes sauvegardes, le
    cache de Tor, les caches Python. Les liens symboliques ne sont jamais suivis."""
    racine = Path(config.RACINE)
    donnees = Path(config.DOSSIER_DONNEES)
    exclus = {Path(config.DOSSIER_SAUVEGARDES), config.dossier_images(), Path(config.DOSSIER_LOGO), Path(config.DOSSIER_SONS),
              donnees / "tor", donnees / "restaurations"}
    cle = donnees / "identite_p2p.key"
    base_db = Path(config.FICHIER_BASE)
    fichiers, ignores = [], []
    for dossier_courant, sous_dossiers, noms in os.walk(racine, followlinks=False):
        courant = Path(dossier_courant)
        sous_dossiers[:] = [d for d in sous_dossiers
                            if d not in DOSSIERS_IGNORES and (courant / d) not in exclus and not (courant / d).is_symlink()]
        for nom in noms:
            fichier = courant / nom
            if fichier.is_symlink() or nom.endswith((".pyc", ".pyo", ".tmp", ".partiel")):
                continue
            if fichier.name.startswith(base_db.name) and fichier.parent == base_db.parent:
                continue                                            # la base : instantané à part
            if fichier == cle and not avec_cle:
                continue
            if fichier.name.startswith("identite_p2p.key") and fichier != cle:
                continue
            fichiers.append(fichier.relative_to(racine))
    return fichiers, ignores


def creer(type_, avec_cle=False, prefixe="wikicartes"):
    """Crée une sauvegarde du type demandé et renvoie son entrée (voir lister). `avec_cle` : seulement pour « ultra »,
    ajoute la clé secrète d'identité du Hall au dossier data/ du programme."""
    if type_ not in TYPES:
        raise SauvegardeInvalide("type de sauvegarde inconnu")
    avec_cle = bool(avec_cle) and type_ == "ultra"
    if not _VERROU.acquire(blocking=False):
        raise SauvegardeEnCours("une sauvegarde ou une restauration est déjà en cours")
    try:
        return _creer(type_, avec_cle, prefixe)
    finally:
        _VERROU.release()


def _creer(type_, avec_cle, prefixe):
    cible = _nom_libre(prefixe, type_)
    partiel = cible.with_name(cible.name + ".partiel")
    temporaire = Path(tempfile.mkdtemp(prefix="sauvegarde-", dir=dossier()))
    ignores = []
    try:
        with base.connexion_rapide() as conn:
            nb_cartes = base.compter(conn)
            valeurs = _parametres_actuels(conn) if type_ in AVEC_PARAMETRES else {}
            if type_ in AVEC_COLLECTION:
                _instantane_collection(conn, temporaire / "collection.db")
        contenu = []
        with zipfile.ZipFile(partiel, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            if type_ in AVEC_PARAMETRES:
                z.writestr("parametres.json", json.dumps(valeurs, ensure_ascii=False, indent=1, sort_keys=True))
                contenu.append("parametres")
            if type_ in AVEC_COLLECTION:
                z.write(temporaire / "collection.db", "collection.db")
                contenu.append("collection")
                for fichier in sorted(config.dossier_images().glob("*")) if config.dossier_images().is_dir() else []:
                    if _NOM_IMAGE.fullmatch(fichier.name) and fichier.is_file() and not fichier.is_symlink():
                        z.write(fichier, f"images/{fichier.name}", compress_type=zipfile.ZIP_STORED)
                contenu.append("images")
            elif type_ == "parametres":
                nom = images.nom_depuis_adresse(valeurs.get("BOOSTER_IMAGE"))        # l'image du paquet personnalisé
                if nom and images.chemin(nom) is not None:
                    z.write(images.chemin(nom), f"images/{nom}", compress_type=zipfile.ZIP_STORED)
                    contenu.append("image du paquet")
            if type_ in AVEC_PARAMETRES and Path(config.DOSSIER_LOGO).is_dir():
                for fichier in sorted(Path(config.DOSSIER_LOGO).iterdir()):
                    if (fichier.is_file() and not fichier.is_symlink() and _NOM_LOGO.fullmatch(fichier.name)
                            and fichier.suffix.lower() in logo.TYPES and fichier.stat().st_size <= logo.TAILLE_MAX):
                        z.write(fichier, f"logo/{fichier.name}")
                contenu.append("logo")
                for nom_son in sons.lister():
                    fichier_son = sons.chemin(nom_son)
                    if fichier_son is not None:
                        z.write(fichier_son, f"sons/{nom_son}", compress_type=zipfile.ZIP_STORED)
                contenu.append("sons")
            if type_ == "ultra":
                fichiers, ignores = _fichiers_programme(avec_cle)
                for relatif in fichiers:
                    try:
                        z.write(Path(config.RACINE) / relatif, "programme/" + relatif.as_posix())
                    except OSError as erreur:                  # fichier verrouillé ou disparu : on le note, on continue
                        ignores.append(f"{relatif.as_posix()} ({erreur.strerror or erreur})")
                contenu.append("programme")
            manifeste = {
                "format": FORMAT, "version_format": VERSION_FORMAT, "type": type_,
                "cree_le": datetime.now().astimezone().isoformat(timespec="seconds"), "programme": "WikiCartes",
                "schema_base": base.VERSION_SCHEMA, "nb_cartes": nb_cartes, "contenu": contenu,
                "cle_identite": bool(avec_cle), "ignores": ignores[:200],
            }
            z.writestr("manifest.json", json.dumps(manifeste, ensure_ascii=False, indent=1))
        os.replace(partiel, cible)
        try:
            os.chmod(cible, 0o600)
        except OSError:
            pass
    except BaseException:
        partiel.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(temporaire, ignore_errors=True)
    return entree(cible)


# ------------------------------------------------------------------------------------------------ lecture

def _lire_manifeste(zf):
    try:
        info = zf.getinfo("manifest.json")
    except KeyError:
        raise SauvegardeInvalide("ce fichier n'est pas une sauvegarde WikiCartes (manifest.json absent)") from None
    if info.file_size > 200_000:
        raise SauvegardeInvalide("manifeste trop gros")
    try:
        manifeste = json.loads(zf.read(info).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SauvegardeInvalide("manifeste illisible") from None
    if not isinstance(manifeste, dict) or manifeste.get("format") != FORMAT:
        raise SauvegardeInvalide("ce fichier n'est pas une sauvegarde WikiCartes")
    version = manifeste.get("version_format")
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= VERSION_FORMAT:
        raise SauvegardeInvalide("format de sauvegarde inconnu (créée par une autre version du programme ?)")
    if manifeste.get("type") not in TYPES:
        raise SauvegardeInvalide("type de sauvegarde inconnu")
    schema = manifeste.get("schema_base")
    if schema is not None and (isinstance(schema, bool) or not isinstance(schema, int) or schema < 0):
        raise SauvegardeInvalide("version de base invalide")
    return manifeste


def _nom_membre_sur(nom):
    """Le nom d'un fichier de l'archive est-il sans danger (chemin relatif, pas de « .. », de disque, de barre inverse) ?"""
    if not nom or len(nom) > 400 or "\x00" in nom or "\\" in nom or nom.startswith("/") or ":" in nom.split("/")[0]:
        return False
    parties = nom.split("/")
    if any(p in ("", ".", "..") for p in parties[:-1]) or parties[-1] in ("", ".", ".."):
        return False
    return True


def inspecter(fichier):
    """Vérifie une sauvegarde SANS rien en extraire ni rien changer. Renvoie son manifeste, ou lève SauvegardeInvalide :
    archive valide, noms de fichiers sûrs, aucun lien symbolique, pas de « bombe » de décompression, taille raisonnable,
    contenu conforme au type, base de données pas plus récente que ce programme."""
    try:
        zf = zipfile.ZipFile(fichier)
    except (zipfile.BadZipFile, OSError):
        raise SauvegardeInvalide("ce fichier n'est pas une archive .zip valide") from None
    with zf:
        membres = zf.infolist()
        if len(membres) > NB_FICHIERS_MAX:
            raise SauvegardeInvalide("trop de fichiers dans l'archive")
        total = 0
        presents = set()
        for info in membres:
            nom = info.filename
            if info.is_dir():
                continue
            if not _nom_membre_sur(nom):
                raise SauvegardeInvalide("nom de fichier dangereux dans l'archive")
            if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise SauvegardeInvalide("lien symbolique dans l'archive")
            haut = nom.split("/")[0]
            if nom not in ("manifest.json", "parametres.json", "collection.db") and haut not in ("images", "logo", "sons", "programme"):
                raise SauvegardeInvalide("fichier inattendu dans l'archive")
            if info.flag_bits & 0x1:
                raise SauvegardeInvalide("archive chiffrée : non prise en charge")
            if info.file_size > 50 * 1024 * 1024 and info.compress_size * 400 < info.file_size:
                raise SauvegardeInvalide("taux de compression suspect (bombe de décompression ?)")
            total += info.file_size
            if total > TAILLE_MAX_DECOMPRESSEE:
                raise SauvegardeInvalide("contenu décompressé trop volumineux")
            presents.add(nom)
        manifeste = _lire_manifeste(zf)
        type_ = manifeste["type"]
        if type_ in AVEC_PARAMETRES and "parametres.json" not in presents:
            raise SauvegardeInvalide("parametres.json manque dans cette sauvegarde")
        if type_ in AVEC_COLLECTION and "collection.db" not in presents:
            raise SauvegardeInvalide("collection.db manque dans cette sauvegarde")
        if type_ == "ultra" and not any(n.startswith("programme/") for n in presents):
            raise SauvegardeInvalide("le dossier programme/ manque dans cette sauvegarde ultra complète")
        schema = manifeste.get("schema_base")
        if schema is not None and schema > base.VERSION_SCHEMA:
            raise SauvegardeInvalide(f"cette sauvegarde vient d'une version plus récente du programme (base v{schema}, ce "
                                     f"programme gère jusqu'à v{base.VERSION_SCHEMA}) : mets le programme à jour")
        if "parametres.json" in presents and zf.getinfo("parametres.json").file_size > TAILLE_MAX_JSON:
            raise SauvegardeInvalide("parametres.json trop gros")
    return manifeste


def entree(fichier):
    """Description d'une sauvegarde pour la page : nom, type, libellé, date, taille, cartes, clé incluse, et « invalide »."""
    fichier = Path(fichier)
    donnees = {"nom": fichier.name, "taille": fichier.stat().st_size, "invalide": False, "type": None,
               "libelle": "Sauvegarde illisible", "cree_le": datetime.fromtimestamp(fichier.stat().st_mtime).astimezone()
               .isoformat(timespec="seconds"), "nb_cartes": None, "cle_identite": False,
               "avant_restauration": fichier.name.startswith("avant-restauration-")}
    try:
        with zipfile.ZipFile(fichier) as zf:
            manifeste = _lire_manifeste(zf)
    except (SauvegardeInvalide, zipfile.BadZipFile, OSError) as erreur:
        donnees["invalide"] = True
        donnees["erreur"] = str(erreur)
        return donnees
    donnees.update(type=manifeste["type"], libelle=TYPES[manifeste["type"]]["libelle"],
                   detail=TYPES[manifeste["type"]]["detail"], cree_le=str(manifeste.get("cree_le") or donnees["cree_le"])[:40],
                   nb_cartes=manifeste.get("nb_cartes") if isinstance(manifeste.get("nb_cartes"), int) else None,
                   cle_identite=bool(manifeste.get("cle_identite")))
    return donnees


def lister():
    """Les sauvegardes du dossier, les plus récentes d'abord."""
    fichiers = [f for f in dossier().iterdir() if f.is_file() and NOM_FICHIER.fullmatch(f.name)]
    fichiers.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return [entree(f) for f in fichiers]


def supprimer(nom):
    fichier = chemin(nom)
    fichier.unlink()


# ------------------------------------------------------------------------------------------------ importation

def recevoir(flux, longueur):
    """Reçoit une sauvegarde envoyée par la page (corps de la requête), la range dans le dossier des sauvegardes sous le nom
    « importee-<date>.zip » et la vérifie. Ne restaure rien. Renvoie son entrée ; si elle est refusée, elle est effacée."""
    if not isinstance(longueur, int) or longueur <= 0:
        raise SauvegardeInvalide("fichier vide")
    if longueur > TAILLE_MAX_IMPORT:
        raise SauvegardeInvalide(f"fichier trop gros ({longueur / 1024 ** 3:.1f} Go ; {TAILLE_MAX_IMPORT // 1024 ** 3} Go au maximum)")
    cible = dossier() / f"importee-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.zip"
    partiel = cible.with_name(cible.name + ".partiel")
    restant = longueur
    try:
        with open(partiel, "wb") as sortie:
            while restant > 0:
                morceau = flux.read(min(HOTES_ECRITURE, restant))
                if not morceau:
                    raise SauvegardeInvalide("envoi interrompu")
                sortie.write(morceau)
                restant -= len(morceau)
        inspecter(partiel)
        os.replace(partiel, cible)
        try:
            os.chmod(cible, 0o600)
        except OSError:
            pass
    except BaseException:
        partiel.unlink(missing_ok=True)
        raise
    return entree(cible)


# ------------------------------------------------------------------------------------------------ restauration

def _extraire(zf, prefixe, destination, limite=TAILLE_MAX_DECOMPRESSEE):
    """Extrait les fichiers de l'archive qui commencent par `prefixe` dans `destination`, sans jamais sortir de ce dossier
    et en comptant les octets réellement écrits (on ne croit pas les tailles annoncées). Renvoie la liste des chemins."""
    destination = Path(destination).resolve()
    ecrits, octets = [], 0
    for info in zf.infolist():
        if info.is_dir() or not info.filename.startswith(prefixe) or not _nom_membre_sur(info.filename):
            continue
        cible = (destination / (info.filename[len(prefixe):] or info.filename)).resolve()      # (un fichier précis : son propre nom)
        if destination not in cible.parents:
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as source, open(cible, "wb") as sortie:
            while True:
                morceau = source.read(HOTES_ECRITURE)
                if not morceau:
                    break
                octets += len(morceau)
                if octets > limite:
                    raise SauvegardeInvalide("contenu décompressé trop volumineux")
                sortie.write(morceau)
        ecrits.append(cible)
    return ecrits


def _restaurer_parametres(zf, conn):
    """Remet les paramètres de la sauvegarde : d'abord tout aux valeurs de départ, puis les valeurs de la sauvegarde qui sont
    valides (les autres sont ignorées et listées). Renvoie (nombre appliqué, noms ignorés)."""
    try:
        valeurs = json.loads(zf.read("parametres.json").decode("utf-8"))
    except (ValueError, UnicodeDecodeError, KeyError):
        raise SauvegardeInvalide("parametres.json illisible") from None
    if not isinstance(valeurs, dict):
        raise SauvegardeInvalide("parametres.json invalide")
    ignores = sorted(cle for cle in valeurs if cle not in parametres.PARAMETRES)
    candidates = {cle: v for cle, v in valeurs.items() if cle in parametres.PARAMETRES}
    decodees = {}
    for _ in range(len(candidates) + 1):
        try:
            decodees = parametres.preparer(candidates)
            break
        except parametres.ValeursInvalides as erreur:
            mauvais = [cle for cle in erreur.erreurs if cle in candidates]
            if not mauvais:                       # incohérence entre plusieurs réglages : on les écarte tous
                mauvais = list(erreur.erreurs) or list(candidates)
            for cle in mauvais:
                candidates.pop(cle, None)
                ignores.append(cle)
            decodees = {}
    parametres.reinitialiser(conn)
    parametres.ecrire_decodees(conn, decodees)
    return len(decodees), sorted(set(ignores))


def _nettoyer_adresses(conn):
    """Après une restauration, toute adresse d'image ou d'article qui n'est pas une adresse connue (Wikimedia, image locale,
    carte personnalisée) est écartée : un fichier de sauvegarde venu d'ailleurs ne peut pas y glisser autre chose."""
    corrections = 0
    lignes = conn.execute("SELECT id, url_article, url_image, url_miniature FROM cartes").fetchall()
    for identifiant, article, image, miniature in lignes:
        nouveau = []
        for valeur in (image, miniature):
            bonne = valeur is None or images.nom_depuis_adresse(valeur) is not None or api.adresse_wikimedia(valeur) is not None
            nouveau.append(valeur if bonne else None)
        if not (isinstance(article, str) and (article.startswith("perso:") or api.adresse_wikimedia(article))):
            article = "perso:" + uuid.uuid4().hex
            corrections += 1
        if nouveau != [image, miniature]:
            corrections += 1
        conn.execute("UPDATE cartes SET url_article = ?, url_image = ?, url_miniature = ? WHERE id = ?",
                     (article, nouveau[0], nouveau[1], identifiant))
    return corrections


def _restaurer_collection(fichier_db, conn):
    """Remplace la collection (toutes les tables sauf les paramètres) par celle de la copie `fichier_db`, après l'avoir
    vérifiée et mise à la version actuelle du schéma. Renvoie le nombre de cartes de la collection restaurée."""
    copie = sqlite3.connect(fichier_db, isolation_level=None)
    try:
        if copie.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SauvegardeInvalide("la base de la sauvegarde est abîmée (contrôle d'intégrité échoué)")
        if copie.execute("PRAGMA application_id").fetchone()[0] != base.ID_APPLICATION:
            raise SauvegardeInvalide("la base de la sauvegarde n'est pas une base WikiCartes")
        if copie.execute("PRAGMA user_version").fetchone()[0] > base.VERSION_SCHEMA:
            raise SauvegardeInvalide("la base de la sauvegarde est plus récente que ce programme")
        base._migrer(copie)                                  # remise à niveau de l'ancienne structure
    except sqlite3.DatabaseError as erreur:
        raise SauvegardeInvalide(f"base de la sauvegarde illisible : {erreur}") from None
    finally:
        copie.close()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("ATTACH DATABASE ? AS sauv", (str(fichier_db),))
        try:
            tables = [n for (n,) in conn.execute("SELECT name FROM sauv.sqlite_master WHERE type = 'table' "
                                                 "AND name NOT LIKE 'sqlite_%'")]
            with base.transaction(conn):
                for table in tables:
                    if table == "parametres":
                        continue
                    colonnes_dest = [c[1] for c in conn.execute(f'PRAGMA main.table_info("{table}")')]
                    colonnes_src = [c[1] for c in conn.execute(f'PRAGMA sauv.table_info("{table}")')]
                    if not colonnes_dest:
                        continue
                    communes = [c for c in colonnes_dest if c in colonnes_src]
                    liste = ", ".join(f'"{c}"' for c in communes)
                    conn.execute(f'DELETE FROM main."{table}"')
                    conn.execute(f'INSERT INTO main."{table}" ({liste}) SELECT {liste} FROM sauv."{table}"')
                _nettoyer_adresses(conn)
                if conn.execute("PRAGMA foreign_key_check").fetchall():
                    raise SauvegardeInvalide("la collection de la sauvegarde est incohérente (liens cassés)")
        finally:
            conn.execute("DETACH DATABASE sauv")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return base.compter(conn)


def restaurer(nom):
    """Restaure une sauvegarde (créée ici ou importée). Avant de toucher à quoi que ce soit, l'état actuel est sauvegardé
    (type complète, « avant-restauration »). Renvoie un résumé : {type, libelle, nb_cartes, parametres, parametres_ignores,
    images, logo, programme, securite}. Lève SauvegardeInvalide si la sauvegarde est refusée."""
    fichier = chemin(nom)
    manifeste = inspecter(fichier)
    type_ = manifeste["type"]
    if not _VERROU.acquire(blocking=False):
        raise SauvegardeEnCours("une sauvegarde ou une restauration est déjà en cours")
    temporaire = Path(tempfile.mkdtemp(prefix="restauration-", dir=dossier()))
    try:
        securite = _creer("complete", False, "avant-restauration")["nom"]          # état actuel mis à l'abri
        resume = {"type": type_, "libelle": TYPES[type_]["libelle"], "securite": securite, "nb_cartes": None,
                  "parametres": 0, "parametres_ignores": [], "images": 0, "logo": 0, "sons": 0, "programme": None}
        with zipfile.ZipFile(fichier) as zf:
            # 1) images et logo d'abord : les paramètres et les cartes y font référence
            if any(n.startswith("images/") for n in zf.namelist()):
                for ecrit in _extraire(zf, "images/", temporaire / "images"):
                    if _NOM_IMAGE.fullmatch(ecrit.name):
                        with open(ecrit, "rb") as f:
                            vrai = images.type_image(f.read(16))
                        cible = config.dossier_images() / ecrit.name
                        if vrai is not None and not cible.exists():
                            cible.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(ecrit, cible)
                            resume["images"] += 1
            if any(n.startswith("logo/") for n in zf.namelist()):
                for ecrit in _extraire(zf, "logo/", temporaire / "logo"):
                    if (_NOM_LOGO.fullmatch(ecrit.name) and ecrit.suffix.lower() in logo.TYPES
                            and ecrit.stat().st_size <= logo.TAILLE_MAX):
                        cible = Path(config.DOSSIER_LOGO) / ecrit.name
                        if not cible.exists():
                            cible.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(ecrit, cible)
                            resume["logo"] += 1
            if any(n.startswith("sons/") for n in zf.namelist()):
                for ecrit in _extraire(zf, "sons/", temporaire / "sons"):
                    if sons.nom_valide(ecrit.name) and ecrit.stat().st_size <= sons.TAILLE_MAX:
                        with open(ecrit, "rb") as f:
                            tete = f.read(16)
                        cible = Path(config.DOSSIER_SONS) / ecrit.name
                        if sons._famille(tete) in sons._FAMILLES_PAR_EXTENSION.get(ecrit.suffix.lower(), ()) and not cible.exists():
                            cible.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(ecrit, cible)
                            resume["sons"] += 1
            # 2) collection
            if type_ in AVEC_COLLECTION:
                _extraire(zf, "collection.db", temporaire / "base")
                with base.connexion_rapide() as conn:
                    resume["nb_cartes"] = _restaurer_collection(temporaire / "base" / "collection.db", conn)
            # 3) paramètres
            if type_ in AVEC_PARAMETRES:
                with base.connexion_rapide() as conn:
                    resume["parametres"], resume["parametres_ignores"] = _restaurer_parametres(zf, conn)
            # 4) programme (ultra) : jamais par-dessus le programme en cours
            if type_ == "ultra":
                cible = Path(config.DOSSIER_DONNEES) / "restaurations" / f"{datetime.now():%Y%m%d-%H%M%S}"
                _extraire(zf, "programme/", cible)
                resume["programme"] = str(cible)
        if resume["nb_cartes"] is None:
            with base.connexion_rapide() as conn:
                resume["nb_cartes"] = base.compter(conn)
        return resume
    finally:
        shutil.rmtree(temporaire, ignore_errors=True)
        _VERROU.release()
