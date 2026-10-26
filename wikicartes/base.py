"""Base de données locale (SQLite) : la collection de cartes et les paramètres.

Tout tient dans un seul fichier, data/collection.db. SQLite est fourni avec Python :
il n'y a rien à installer ni de serveur à lancer.

Ce qui est mis en place pour que la base soit fiable et un peu protégée :
- requêtes paramétrées partout (aucune donnée n'est collée dans une requête SQL) ;
- contraintes dans la base (types, longueurs, valeurs possibles) en plus des
  vérifications faites par le programme ;
- écritures groupées en transactions (tout ou rien) et journal WAL ;
- vérification d'intégrité à chaque ouverture : si le fichier est abîmé, il est mis de
  côté et remplacé par la dernière sauvegarde valide ;
- sauvegarde automatique (une par jour, les plus récentes sont gardées) ;
- droits d'accès restreints au propriétaire (là où le système le permet) ;
- suppression « sûre » des données effacées (secure_delete) et schéma non fiable refusé.
"""

import json
import os
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import categories as cat
from . import cadrage, config, qr, theme, web

ID_APPLICATION = 0x57494B49          # « WIKI » : reconnaît nos fichiers
VERSION_SCHEMA = 18                   # à augmenter à chaque changement de structure

# Structure de la base, par version. Pour la faire évoluer plus tard : ajouter une
# entrée (2: [...]) avec les commandes de migration et augmenter VERSION_SCHEMA.
MIGRATIONS = {
    1: [
        """CREATE TABLE cartes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            titre         TEXT    NOT NULL CHECK (length(titre) BETWEEN 1 AND 500),
            description   TEXT    CHECK (description IS NULL OR length(description) <= 2000),
            intro         TEXT    CHECK (intro IS NULL OR length(intro) <= 20000),
            rarete        TEXT    NOT NULL CHECK (length(rarete) BETWEEN 1 AND 10),
            rarete_tiree  TEXT    NOT NULL CHECK (length(rarete_tiree) BETWEEN 1 AND 10),
            tire_le       TEXT    NOT NULL,
            vues_moyenne  REAL    NOT NULL CHECK (vues_moyenne >= 0),
            vues_total    INTEGER NOT NULL CHECK (vues_total >= 0),
            url_article   TEXT    NOT NULL CHECK (length(url_article) <= 2000),
            url_image     TEXT    CHECK (url_image IS NULL OR length(url_image) <= 2000),
            url_miniature TEXT    CHECK (url_miniature IS NULL OR length(url_miniature) <= 2000),
            qr_svg        TEXT    CHECK (qr_svg IS NULL OR length(qr_svg) <= 200000),
            langue        TEXT    NOT NULL CHECK (length(langue) BETWEEN 2 AND 12),
            favori        INTEGER NOT NULL DEFAULT 0 CHECK (favori IN (0, 1)),
            cree_le       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            UNIQUE (url_article, tire_le)
        )""",
        "CREATE INDEX cartes_tire_le ON cartes (tire_le DESC)",
        "CREATE INDEX cartes_rarete ON cartes (rarete)",
        """CREATE TABLE parametres (
            cle    TEXT NOT NULL PRIMARY KEY CHECK (length(cle) BETWEEN 1 AND 100),
            valeur TEXT NOT NULL CHECK (length(valeur) <= 100000),
            defaut TEXT,
            maj_le TEXT NOT NULL
        ) WITHOUT ROWID""",
    ],
    # Version 2 : catégories de cartes. Supprimer une catégorie (ou une carte) supprime seulement
    # les liens (ON DELETE CASCADE) : jamais les cartes elles-mêmes.
    2: [
        """CREATE TABLE categories (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            nom      TEXT NOT NULL CHECK (length(nom) BETWEEN 1 AND 40),
            cle      TEXT NOT NULL UNIQUE CHECK (length(cle) BETWEEN 1 AND 200),
            couleur  TEXT NOT NULL CHECK (length(couleur) = 7),
            meta1    TEXT NOT NULL DEFAULT '' CHECK (length(meta1) <= 40),
            meta2    TEXT NOT NULL DEFAULT '' CHECK (length(meta2) <= 40),
            meta3    TEXT NOT NULL DEFAULT '' CHECK (length(meta3) <= 40),
            meta4    TEXT NOT NULL DEFAULT '' CHECK (length(meta4) <= 40),
            meta5    TEXT NOT NULL DEFAULT '' CHECK (length(meta5) <= 40),
            position INTEGER NOT NULL DEFAULT 0,
            cree_le  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )""",
        """CREATE TABLE cartes_categories (
            carte_id     INTEGER NOT NULL REFERENCES cartes (id) ON DELETE CASCADE,
            categorie_id INTEGER NOT NULL REFERENCES categories (id) ON DELETE CASCADE,
            PRIMARY KEY (carte_id, categorie_id)
        ) WITHOUT ROWID""",
        "CREATE INDEX cartes_categories_categorie ON cartes_categories (categorie_id)",
    ],
    # Version 3 : corbeille. Une carte supprimée garde sa ligne, marquée par la date de mise à la
    # corbeille (supprime_le) ; elle disparaît de la collection mais peut être restaurée. Seule la
    # suppression définitive efface la ligne (et les liens avec les catégories).
    3: [
        "ALTER TABLE cartes ADD COLUMN supprime_le TEXT",
        "CREATE INDEX cartes_supprime_le ON cartes (supprime_le)",
    ],
    # Version 4 : recherche rapide des doublons (cartes au titre identique).
    4: [
        "CREATE INDEX cartes_titre ON cartes (titre)",
    ],
    # Version 5 : réserve de cartes préparées d'avance (pré-chargement) et journal des requêtes
    # de pré-chargement (pour le plafond horaire, qui survit aux redémarrages).
    5: [
        """CREATE TABLE reserve (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            titre         TEXT    NOT NULL CHECK (length(titre) BETWEEN 1 AND 500),
            description   TEXT    CHECK (description IS NULL OR length(description) <= 2000),
            intro         TEXT    CHECK (intro IS NULL OR length(intro) <= 20000),
            rarete        TEXT    NOT NULL CHECK (length(rarete) BETWEEN 1 AND 10),
            rarete_tiree  TEXT    NOT NULL CHECK (length(rarete_tiree) BETWEEN 1 AND 10),
            vues_moyenne  REAL    NOT NULL CHECK (vues_moyenne >= 0),
            vues_total    INTEGER NOT NULL CHECK (vues_total >= 0),
            url_article   TEXT    NOT NULL CHECK (length(url_article) BETWEEN 1 AND 2000),
            url_image     TEXT    CHECK (url_image IS NULL OR length(url_image) <= 2000),
            url_miniature TEXT    CHECK (url_miniature IS NULL OR length(url_miniature) <= 2000),
            langue        TEXT    NOT NULL CHECK (length(langue) BETWEEN 2 AND 12),
            prepare_le    TEXT    NOT NULL,
            UNIQUE (url_article)
        )""",
        "CREATE INDEX reserve_prepare_le ON reserve (prepare_le)",
        """CREATE TABLE reserve_requetes (
            instant REAL NOT NULL
        )""",
        "CREATE INDEX reserve_requetes_instant ON reserve_requetes (instant)",
    ],
    # Version 6 : statistiques des cartes (langues, taille, modifications, liens entrants) et
    # journal des requêtes par source (réserve / statistiques). Une valeur vide (NULL) veut dire
    # « pas encore récupérée ».
    6: [
        "ALTER TABLE cartes ADD COLUMN nb_langues INTEGER CHECK (nb_langues IS NULL OR nb_langues >= 0)",
        "ALTER TABLE cartes ADD COLUMN taille_octets INTEGER CHECK (taille_octets IS NULL OR taille_octets >= 0)",
        "ALTER TABLE cartes ADD COLUMN nb_revisions INTEGER CHECK (nb_revisions IS NULL OR nb_revisions >= 0)",
        "ALTER TABLE cartes ADD COLUMN revisions_plafonnees INTEGER NOT NULL DEFAULT 0 CHECK (revisions_plafonnees IN (0, 1))",
        "ALTER TABLE cartes ADD COLUMN nb_liens_entrants INTEGER CHECK (nb_liens_entrants IS NULL OR nb_liens_entrants >= 0)",
        "ALTER TABLE cartes ADD COLUMN stats_essais INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE reserve ADD COLUMN nb_langues INTEGER CHECK (nb_langues IS NULL OR nb_langues >= 0)",
        "ALTER TABLE reserve ADD COLUMN taille_octets INTEGER CHECK (taille_octets IS NULL OR taille_octets >= 0)",
        "ALTER TABLE reserve_requetes ADD COLUMN source TEXT NOT NULL DEFAULT 'reserve'",
    ],
    # Version 7 : page de profil. Chaque vitrine (ligne de cartes) a un titre, et chaque
    # emplacement de vitrine contient au plus une carte. Une carte n'est exposée qu'à un seul
    # endroit. Les emplacements sont mémorisés même si on réduit leur nombre dans la configuration
    # (ils reviennent si on le réaugmente) ; une carte supprimée définitivement libère le sien.
    7: [
        """CREATE TABLE vitrines (
            position INTEGER PRIMARY KEY CHECK (position >= 1),
            titre    TEXT NOT NULL DEFAULT '' CHECK (length(titre) <= 200)
        )""",
        """CREATE TABLE vitrine_cartes (
            vitrine     INTEGER NOT NULL CHECK (vitrine >= 1),
            emplacement INTEGER NOT NULL CHECK (emplacement >= 1),
            carte_id    INTEGER NOT NULL REFERENCES cartes (id) ON DELETE CASCADE,
            PRIMARY KEY (vitrine, emplacement),
            UNIQUE (carte_id)
        )""",
    ],
    # Version 8 : une vitrine contient une COPIE d'affichage de la carte : la même carte peut être
    # exposée à plusieurs endroits (la contrainte d'unicité est retirée) ; elle reste dans la collection.
    8: [
        """CREATE TABLE vitrine_cartes_v8 (
            vitrine     INTEGER NOT NULL CHECK (vitrine >= 1),
            emplacement INTEGER NOT NULL CHECK (emplacement >= 1),
            carte_id    INTEGER NOT NULL REFERENCES cartes (id) ON DELETE CASCADE,
            PRIMARY KEY (vitrine, emplacement)
        )""",
        "INSERT INTO vitrine_cartes_v8 (vitrine, emplacement, carte_id) "
        "SELECT vitrine, emplacement, carte_id FROM vitrine_cartes",
        "DROP TABLE vitrine_cartes",
        "ALTER TABLE vitrine_cartes_v8 RENAME TO vitrine_cartes",
        "CREATE INDEX vitrine_cartes_carte ON vitrine_cartes (carte_id)",
    ],
    # Version 9 : cartes créées par l'utilisateur (Créateur de cartes) : rang « PERSO », surnom en
    # bas à gauche et style propre à chaque carte (motif, trois couleurs, reflet, lettres et nom du
    # palier), enregistré en JSON validé.
    9: [
        "ALTER TABLE cartes ADD COLUMN personnalisee INTEGER NOT NULL DEFAULT 0 CHECK (personnalisee IN (0, 1))",
        "ALTER TABLE cartes ADD COLUMN surnom TEXT CHECK (surnom IS NULL OR length(surnom) <= 200)",
        "ALTER TABLE cartes ADD COLUMN style_json TEXT CHECK (style_json IS NULL OR length(style_json) <= 2000)",
    ],
    # Version 10 : partage pair à pair (Hall des collections). `p2p_pairs` : l'annuaire des collectionneurs
    # connus (fiches SIGNÉES par leur propriétaire, vérifiées avant d'entrer ici) ; `p2p_moi` : mon pseudo.
    # La clé secrète d'identité n'est JAMAIS dans la base (fichier à part, droits 600) : une sauvegarde
    # ou une copie de la base ne la contient pas.
    10: [
        """CREATE TABLE p2p_pairs (
            id          TEXT PRIMARY KEY CHECK (length(id) = 52),
            fiche_json  TEXT NOT NULL CHECK (length(fiche_json) <= 3000),
            pseudo_cle  TEXT,
            pseudo      TEXT,
            collection  TEXT NOT NULL DEFAULT '',
            nb_cartes   INTEGER NOT NULL DEFAULT 0 CHECK (nb_cartes >= 0),
            profil      INTEGER NOT NULL DEFAULT 0 CHECK (profil IN (0, 1)),
            collection_ok INTEGER NOT NULL DEFAULT 0 CHECK (collection_ok IN (0, 1)),
            t           INTEGER NOT NULL,
            depuis      INTEGER NOT NULL DEFAULT 0,
            vu_le       INTEGER,
            echecs      INTEGER NOT NULL DEFAULT 0,
            source      TEXT
        )""",
        "CREATE INDEX p2p_pairs_pseudo ON p2p_pairs (pseudo_cle)",
        """CREATE TABLE p2p_moi (
            id            INTEGER PRIMARY KEY CHECK (id = 1),
            pseudo        TEXT,
            pseudo_depuis INTEGER
        )""",
        "INSERT INTO p2p_moi (id, pseudo, pseudo_depuis) VALUES (1, NULL, NULL)",
    ],
    # Version 11 : les cartes préparées d'avance (réserve) gardent aussi leurs modifications et leurs liens entrants, pour
    # que les statistiques arrivent AVEC la carte à l'ouverture d'un paquet.
    11: [
        "ALTER TABLE reserve ADD COLUMN nb_revisions INTEGER CHECK (nb_revisions IS NULL OR nb_revisions >= 0)",
        "ALTER TABLE reserve ADD COLUMN revisions_plafonnees INTEGER NOT NULL DEFAULT 0 CHECK (revisions_plafonnees IN (0, 1))",
        "ALTER TABLE reserve ADD COLUMN nb_liens_entrants INTEGER CHECK (nb_liens_entrants IS NULL OR nb_liens_entrants >= 0)",
    ],
    # Version 12 : les « jetons d'ouverture » (un par paquet qu'on peut ouvrir tout de suite) : le stock de paquets se
    # reconstitue au fil du temps, un paquet à la fois, et survit à un redémarrage.
    12: [
        """CREATE TABLE ouverture_jetons (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            jetons REAL NOT NULL CHECK (jetons >= 0),
            maj REAL NOT NULL
        )""",
        "INSERT INTO ouverture_jetons (id, jetons, maj) VALUES (1, 1000, 0)",
    ],
    13: [                       # le FULL-ART d'une carte : deux calques PNG (Zuul puis Gozer) et des effets (voir fullart.py)
        """CREATE TABLE fullart (
            carte_id INTEGER PRIMARY KEY REFERENCES cartes (id) ON DELETE CASCADE,
            zuul     TEXT NOT NULL DEFAULT '' CHECK (length(zuul) <= 120),
            gozer    TEXT NOT NULL DEFAULT '' CHECK (length(gozer) <= 120),
            effets   TEXT NOT NULL DEFAULT '' CHECK (length(effets) <= 120)
        )""",
    ],
    14: [                       # GIF réellement animé ? (NULL : pas encore vérifié, 0 : image fixe, 1 : animée) et l'illustration retirée d'une carte
        "ALTER TABLE cartes ADD COLUMN gif_anime INTEGER CHECK (gif_anime IS NULL OR gif_anime IN (0, 1))",
        """CREATE TABLE image_retiree (
            carte_id  INTEGER PRIMARY KEY REFERENCES cartes (id) ON DELETE CASCADE,
            image     TEXT NOT NULL CHECK (length(image) <= 2000),
            miniature TEXT CHECK (miniature IS NULL OR length(miniature) <= 2000)
        )""",
    ],
    15: [                       # le cadrage (position et agrandissement) d'une illustration : par article ET par fichier d'image (voir cadrage.py)
        """CREATE TABLE cadrage_image (
            url_article TEXT NOT NULL CHECK (length(url_article) <= 2000),
            image       TEXT NOT NULL CHECK (length(image) <= 500),
            zoom        REAL NOT NULL CHECK (zoom >= 1 AND zoom <= 4),
            x           REAL NOT NULL CHECK (x >= 0 AND x <= 100),
            y           REAL NOT NULL CHECK (y >= 0 AND y <= 100),
            PRIMARY KEY (url_article, image)
        )""",
    ],
    16: [                       # le cadrage peut RÉDUIRE l'image (zoom de 0,1 à 4) et garde le ratio de l'image (largeur / hauteur)
        """CREATE TABLE cadrage_image_v16 (
            url_article TEXT NOT NULL CHECK (length(url_article) <= 2000),
            image       TEXT NOT NULL CHECK (length(image) <= 500),
            zoom        REAL NOT NULL CHECK (zoom >= 0.1 AND zoom <= 4),
            x           REAL NOT NULL CHECK (x >= 0 AND x <= 100),
            y           REAL NOT NULL CHECK (y >= 0 AND y <= 100),
            ratio       REAL CHECK (ratio IS NULL OR (ratio >= 0.05 AND ratio <= 20)),
            PRIMARY KEY (url_article, image)
        )""",
        "INSERT INTO cadrage_image_v16 (url_article, image, zoom, x, y) SELECT url_article, image, zoom, x, y FROM cadrage_image",
        "DROP TABLE cadrage_image",
        "ALTER TABLE cadrage_image_v16 RENAME TO cadrage_image",
    ],
    17: [                       # le cadrage devient celui de CHAQUE CARTE (deux cartes identiques peuvent être dimensionnées autrement : ce ne sont plus des doublons) ;
        """CREATE TABLE cadrage_carte (       -- cadrage_image reste le MODÈLE : le dernier réglage de l'article et de l'image, repris par les nouvelles cartes
            carte_id INTEGER PRIMARY KEY REFERENCES cartes (id) ON DELETE CASCADE,
            zoom     REAL NOT NULL CHECK (zoom >= 0.1 AND zoom <= 4),
            x        REAL NOT NULL CHECK (x >= 0 AND x <= 100),
            y        REAL NOT NULL CHECK (y >= 0 AND y <= 100),
            ratio    REAL CHECK (ratio IS NULL OR (ratio >= 0.05 AND ratio <= 20))
        )""",
        lambda conn: _reprendre_cadrages(conn),
    ],
    18: [                       # les images déjà VUES dans la liste d'un article : elles n'en disparaissent plus
        """CREATE TABLE image_vue (
            url_article TEXT NOT NULL CHECK (length(url_article) <= 2000),
            cle         TEXT NOT NULL CHECK (length(cle) <= 500),
            nom         TEXT NOT NULL CHECK (length(nom) <= 200),
            image       TEXT NOT NULL CHECK (length(image) <= 2000),
            miniature   TEXT NOT NULL CHECK (length(miniature) <= 2000),
            largeur     INTEGER NOT NULL DEFAULT 0,
            hauteur     INTEGER NOT NULL DEFAULT 0,
            mineure     INTEGER NOT NULL DEFAULT 0 CHECK (mineure IN (0, 1)),
            ordre       INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (url_article, cle)
        )""",
    ],
}


class BaseTropRecente(Exception):
    """La base a été créée par une version plus récente du programme."""


# ------------------------------------------------------------------ fichiers et droits

def _proteger(chemin, mode):
    """Restreint les droits d'accès (propriétaire seulement). Sans effet réel sous
    Windows, où ce sont les droits de ton dossier utilisateur qui s'appliquent."""
    try:
        os.chmod(chemin, mode)
    except OSError:
        pass


def _dossier(chemin):
    chemin.mkdir(parents=True, exist_ok=True)
    _proteger(chemin, 0o700)


def _maintenant():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ------------------------------------------------------------------------ connexion

# Ordres d'affichage de la collection : code -> (libellé affiché dans la liste, ORDER BY).
# Le texte du ORDER BY vient d'ici seulement : une valeur venue de la page n'est jamais insérée
# dans la requête, elle sert uniquement à choisir une entrée de ce dictionnaire.
TRI_DEFAUT = "vues-desc"          # « Vues par jour · plus élevées d'abord » : l'ordre proposé tant qu'on n'en a pas choisi un autre
TRIS = {
    "date-desc": ("Date · plus récentes d'abord", "c.tire_le DESC, c.id ASC"),
    "date-asc": ("Date · plus anciennes d'abord", "c.tire_le ASC, c.id DESC"),
    "vues-desc": ("Vues par jour · plus élevées d'abord",
                  "c.vues_moyenne DESC, c.tire_le DESC, c.id ASC"),
    "vues-asc": ("Vues par jour · plus faibles d'abord",
                 "c.vues_moyenne ASC, c.tire_le DESC, c.id ASC"),
    "titre-asc": ("Titre · de A à Z", "c.titre COLLATE francais ASC, c.tire_le DESC, c.id ASC"),
    "titre-desc": ("Titre · de Z à A", "c.titre COLLATE francais DESC, c.tire_le DESC, c.id ASC"),
}


def _normaliser_sql(texte):
    """Fonction SQL norm(texte) : minuscules, sans accents (pour la recherche d'une carte)."""
    return cat.normaliser(texte) if isinstance(texte, str) else ""


def mots_recherche(texte):
    """Les mots d'une recherche de carte, normalisés (sans accents ni majuscules) : au plus 8, de
    100 caractères au plus au total. Une carte doit contenir TOUS les mots dans son titre."""
    if not isinstance(texte, str):
        return []
    return cat.normaliser(texte[:100]).split()[:8]


def _comparer_titres(a, b):
    """Ordre alphabétique « à la française » : sans tenir compte des majuscules ni des accents
    (Écosse se range avec les E), puis, à égalité, le texte exact."""
    cle_a, cle_b = (cat.normaliser(a), a), (cat.normaliser(b), b)
    return (cle_a > cle_b) - (cle_a < cle_b)


ANCIEN_NOM_BASE = "wikicartes.db"


def migrer_ancien_nom():
    """La base s'appelait data/wikicartes.db : elle devient data/collection.db (le fichier et ses
    annexes -wal et -shm sont renommés ensemble, rien n'est copié ni perdu). Sans effet si la
    nouvelle base existe déjà, s'il n'y a pas d'ancienne base, ou si le nom a été choisi autrement.
    Renvoie True si le renommage a eu lieu."""
    nouveau = config.FICHIER_BASE
    ancien = nouveau.with_name(ANCIEN_NOM_BASE)
    if nouveau.name != "collection.db" or nouveau.exists() or not ancien.exists():
        return False
    for suffixe in ("", "-wal", "-shm"):
        source = Path(str(ancien) + suffixe)
        if source.exists():
            os.replace(source, Path(str(nouveau) + suffixe))
    print(f"Base de données renommée : {ancien.name} -> {nouveau.name}")
    return True


def _connecter():
    _dossier(config.DOSSIER_DONNEES)
    migrer_ancien_nom()
    nouveau = not config.FICHIER_BASE.exists()
    # isolation_level=None : on gère nous-mêmes les transactions (BEGIN / COMMIT)
    conn = sqlite3.connect(config.FICHIER_BASE, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA trusted_schema = OFF")      # refuse les fonctions cachées dans un schéma
    conn.execute("PRAGMA secure_delete = ON")        # écrase les données supprimées
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")        # écriture sûre, lectures simultanées
    conn.execute("PRAGMA synchronous = FULL")        # on attend que les données soient sur le disque
    conn.create_collation("francais", _comparer_titres)   # tri alphabétique des titres
    conn.create_function("norm", 1, _normaliser_sql, deterministic=True)   # recherche de cartes
    conn.create_function("signature_carte", 10, _signature_carte, deterministic=True)   # doublons : ce qui rend deux cartes identiques
    conn.create_function("cle_image_sql", 1, lambda adresse: cadrage.cle_image(adresse) if adresse else "", deterministic=True)
    if nouveau:
        _proteger(config.FICHIER_BASE, 0o600)
    return conn


def _verifier(conn):
    """Lève sqlite3.DatabaseError si le fichier est abîmé ou n'est pas notre base."""
    resultat = conn.execute("PRAGMA quick_check").fetchall()
    if len(resultat) != 1 or resultat[0][0] != "ok":
        raise sqlite3.DatabaseError("contrôle d'intégrité échoué : "
                                    + "; ".join(str(ligne[0]) for ligne in resultat[:3]))
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    identifiant = conn.execute("PRAGMA application_id").fetchone()[0]
    if version != 0 and identifiant != ID_APPLICATION:
        raise sqlite3.DatabaseError("ce fichier n'est pas une base WikiCartes")


def _migrer(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > VERSION_SCHEMA:
        raise BaseTropRecente(
            f"la base est en version {version}, ce programme gère jusqu'à {VERSION_SCHEMA} : "
            "mets le programme à jour")
    while version < VERSION_SCHEMA:
        version += 1
        with transaction(conn):
            for commande in MIGRATIONS[version]:
                if callable(commande):                          # (une étape qui a besoin de Python : elle reçoit la connexion)
                    commande(conn)
                else:
                    conn.execute(commande)
            conn.execute(f"PRAGMA user_version = {int(version)}")
    conn.execute(f"PRAGMA application_id = {ID_APPLICATION}")


@contextmanager
def transaction(conn):
    """Groupe des écritures : tout est enregistré, ou rien (en cas d'erreur)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _reprendre_cadrages(conn):
    """Migration 17 : chaque carte existante reprend le cadrage de son article et de son image (fonctionne même sur une connexion sans nos fonctions SQL)."""
    conn.create_function("cle_image_sql", 1, lambda adresse: cadrage.cle_image(adresse) if adresse else "", deterministic=True)
    conn.execute("INSERT INTO cadrage_carte (carte_id, zoom, x, y, ratio) SELECT c.id, k.zoom, k.x, k.y, k.ratio FROM cartes c "
                 "JOIN cadrage_image k ON k.url_article = c.url_article AND k.image = cle_image_sql(COALESCE(c.url_image, c.url_miniature))")


def ouvrir():
    """Ouvre la base : la crée si besoin, vérifie son intégrité (en cas de problème, la
    remplace par la dernière sauvegarde valide) et applique les mises à jour de structure."""
    conn = None
    try:
        conn = _connecter()
        _verifier(conn)
    except sqlite3.DatabaseError as erreur:
        if conn is not None:
            conn.close()
        _remettre_en_etat(erreur)
        conn = _connecter()
        _verifier(conn)
    _migrer(conn)
    return conn


@contextmanager
def connexion():
    """Ouvre la base (avec vérification complète) pour un bloc `with`, puis la referme."""
    conn = ouvrir()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def connexion_lecture():
    """Connexion en LECTURE SEULE (PRAGMA query_only) : toute tentative d'écriture échoue. Le serveur pair à
    pair l'utilise pour lire les cartes qu'il partage : même si un défaut s'y glissait, il ne pourrait ni
    supprimer une carte, ni changer une catégorie, ni modifier un réglage."""
    conn = _connecter()
    try:
        conn.execute("PRAGMA query_only = ON")
        yield conn
    finally:
        conn.close()


@contextmanager
def connexion_rapide():
    """Comme connexion(), sans la vérification d'intégrité : pour les requêtes de la page,
    une fois la base déjà contrôlée au lancement du programme."""
    conn = _connecter()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------- sauvegardes et réparation

def lister_sauvegardes():
    """Sauvegardes existantes, de la plus ancienne à la plus récente."""
    trouvees = (list(config.DOSSIER_SAUVEGARDES.glob("collection_*.db"))
                + list(config.DOSSIER_SAUVEGARDES.glob("wikicartes_*.db")))     # anciennes sauvegardes
    return sorted(trouvees, key=lambda f: (f.stat().st_mtime, f.name))


def sauvegarder(conn, forcer=False):
    """Copie la base dans data/sauvegardes/ (au plus une fois par jour, sauf `forcer`),
    puis ne garde que les plus récentes. Renvoie le chemin créé, ou None.
    Une base vide n'est pas sauvegardée : il n'y a rien à perdre."""
    if not forcer and compter(conn) == 0:
        return None
    _dossier(config.DOSSIER_SAUVEGARDES)
    existantes = lister_sauvegardes()
    if existantes and not forcer:
        age_jours = (time.time() - existantes[-1].stat().st_mtime) / 86400
        if age_jours < config.SAUVEGARDE_TOUS_LES_JOURS:
            return None

    base_nom = f"collection_{datetime.now():%Y%m%d_%H%M%S}"
    cible = config.DOSSIER_SAUVEGARDES / f"{base_nom}.db"
    n = 1
    while cible.exists():                       # jamais d'écrasement d'une sauvegarde existante
        n += 1
        cible = config.DOSSIER_SAUVEGARDES / f"{base_nom}_{n}.db"
    destination = sqlite3.connect(cible)
    try:
        conn.backup(destination)               # copie cohérente, même pendant une écriture
    finally:
        destination.close()
    _proteger(cible, 0o600)

    for ancienne in lister_sauvegardes()[:-config.SAUVEGARDES_GARDEES]:
        ancienne.unlink()
    return cible


def _remettre_en_etat(erreur):
    """Base abîmée : on met le fichier de côté et on restaure la dernière sauvegarde valide."""
    fichier = config.FICHIER_BASE
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"\n⚠ La base de données est abîmée ({erreur}).")
    for suffixe in ("", "-wal", "-shm"):
        source = Path(str(fichier) + suffixe)
        if source.exists():
            shutil.move(source, Path(str(config.DOSSIER_DONNEES / f"corrompue_{horodatage}.db")
                                     + suffixe))
    print(f"  Le fichier abîmé est conservé dans {config.DOSSIER_DONNEES} "
          f"(corrompue_{horodatage}.db).")

    for sauvegarde in reversed(lister_sauvegardes()):
        shutil.copy2(sauvegarde, fichier)
        essai = None
        try:
            essai = sqlite3.connect(fichier)
            ligne = essai.execute("PRAGMA quick_check").fetchall()
            if len(ligne) == 1 and ligne[0][0] == "ok":
                print(f"  Base restaurée depuis la sauvegarde {sauvegarde.name}.")
                return
        except sqlite3.DatabaseError:
            pass
        finally:
            if essai is not None:
                essai.close()
        fichier.unlink(missing_ok=True)
    print("  Aucune sauvegarde valide : une nouvelle base vide est créée.")


# --------------------------------------------------------------------------- cartes

_COLONNES = ("titre, description, intro, rarete, rarete_tiree, tire_le, vues_moyenne, "
             "vues_total, url_article, url_image, url_miniature, qr_svg, langue, nb_langues, "
             "taille_octets, nb_revisions, revisions_plafonnees, nb_liens_entrants, personnalisee, "
             "surnom, style_json, gif_anime")


def _entier_ou_none(valeur):
    """Un nombre entier positif ou None (statistique pas encore récupérée)."""
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        valeur = int(valeur)
    except (TypeError, ValueError):
        return None
    return valeur if valeur >= 0 else None


def _ou_none(valeur, absent):
    return None if valeur in (None, "", absent) else valeur


def _vers_ligne(art):
    """Article (dictionnaire produit par api.recuperer_details) -> valeurs à enregistrer."""
    tire_le = art["tire_le"]
    if hasattr(tire_le, "isoformat"):
        tire_le = tire_le.isoformat(timespec="seconds")
    image = _ou_none(art.get("image"), "no-image")
    return (
        str(art["titre"]),
        _ou_none(art.get("description"), "no-description"),
        _ou_none(art.get("intro"), "no-intro"),
        str(art["rarete"]),
        str(art.get("rarete_tiree") or art["rarete"]),
        str(tire_le),
        float(art["vues_moyenne"]),
        int(art["vues_total"]),
        str(art.get("url") or ""),
        image,
        _ou_none(art.get("miniature"), "no-image") or image,
        art.get("qr_svg") or ("" if str(art.get("url") or "").startswith("perso:")
                              else qr.svg_article(art.get("url"), art["titre"])) or None,
        str(art.get("langue") or config.LANGUE),
        _entier_ou_none(art.get("nb_langues")),
        _entier_ou_none(art.get("taille_octets")),
        _entier_ou_none(art.get("nb_revisions")),
        1 if art.get("revisions_plafonnees") else 0,
        _entier_ou_none(art.get("nb_liens_entrants")),
        1 if art.get("personnalisee") else 0,
        (str(art.get("surnom")) or None) if art.get("personnalisee") else None,
        json.dumps(theme.style_perso(art.get("style")), ensure_ascii=False)
        if art.get("personnalisee") else None,
        1 if art.get("gif_anime") in (1, True) else (0 if art.get("gif_anime") in (0, False) else None),
    )


def ajouter_cartes(conn, articles):
    """Enregistre des cartes (une seule transaction). Renvoie leurs identifiants, dans
    l'ordre. Une carte déjà présente (même article, même instant) n'est pas dupliquée."""
    identifiants = []
    with transaction(conn):
        for art in articles:
            valeurs = _vers_ligne(art)
            curseur = conn.execute(
                f"INSERT INTO cartes ({_COLONNES}) VALUES ({','.join('?' * len(valeurs))}) "
                "ON CONFLICT (url_article, tire_le) DO NOTHING", valeurs)
            if curseur.rowcount:
                identifiants.append(curseur.lastrowid)
                adresse = art.get("image") if art.get("image") not in (None, "no-image") else art.get("miniature")
                _copier_modele_cadrage(conn, curseur.lastrowid, art.get("url"), adresse)         # la même carte tirée de nouveau : même cadrage
            else:
                identifiants.append(conn.execute(
                    "SELECT id FROM cartes WHERE url_article = ? AND tire_le = ?",
                    (valeurs[8], valeurs[5])).fetchone()[0])
    return identifiants


def _depuis_ligne(ligne):
    """Ligne de la base -> dictionnaire au même format que celui du tirage."""
    return {
        "id": ligne["id"],
        "titre": ligne["titre"],
        "description": ligne["description"] or "no-description",
        "intro": ligne["intro"] or "no-intro",
        "rarete": ligne["rarete"],
        "rarete_nom": config.nom_rang(ligne["rarete"]),
        "rarete_tiree": ligne["rarete_tiree"],
        "tire_le": datetime.fromisoformat(ligne["tire_le"]),
        "vues_moyenne": ligne["vues_moyenne"],
        "vues_total": ligne["vues_total"],
        "url": ligne["url_article"],
        "image": ligne["url_image"] or "no-image",
        "miniature": ligne["url_miniature"] or ligne["url_image"] or "no-image",
        "qr_svg": ligne["qr_svg"] or "",
        "langue": ligne["langue"],
        "favori": bool(ligne["favori"]),
        "categories": [],
        "nb_langues": ligne["nb_langues"],
        "taille_octets": ligne["taille_octets"],
        "nb_revisions": ligne["nb_revisions"],
        "revisions_plafonnees": bool(ligne["revisions_plafonnees"]),
        "nb_liens_entrants": ligne["nb_liens_entrants"],
        "personnalisee": bool(ligne["personnalisee"]),
        "gif_anime": ligne["gif_anime"],
        "surnom": ligne["surnom"] or "",
        "style": theme.style_perso(ligne["style_json"]) if ligne["personnalisee"] else None,
        "supprime_le": (datetime.fromisoformat(ligne["supprime_le"])
                        if ligne["supprime_le"] else None),
    }


def lister_cartes(conn):
    """Toute la collection, des plus récentes aux plus anciennes."""
    lignes = conn.execute("SELECT * FROM cartes WHERE supprime_le IS NULL "
                          "ORDER BY tire_le DESC, id ASC").fetchall()
    return _avec_categories(conn, [_depuis_ligne(ligne) for ligne in lignes])


def cartes_par_identifiants(conn, identifiants):
    """Les cartes demandées (avec leurs catégories), dans l'ordre d'affichage."""
    cartes = []
    identifiants = list(identifiants)
    for debut in range(0, len(identifiants), 500):
        morceau = identifiants[debut:debut + 500]
        lignes = conn.execute(
            f"SELECT * FROM cartes WHERE id IN ({','.join('?' * len(morceau))})", morceau).fetchall()
        cartes.extend(_depuis_ligne(ligne) for ligne in lignes)
    cartes.sort(key=lambda c: (-c["tire_le"].timestamp(), c["id"]))
    return _avec_categories(conn, cartes)


def fullart_des_cartes(conn, identifiants):
    """{id de carte: {"zuul", "gozer", "effets": [codes]}} pour celles qui ont un full-art."""
    resultat = {}
    identifiants = list(identifiants)
    for debut in range(0, len(identifiants), 500):
        morceau = identifiants[debut:debut + 500]
        for ligne in conn.execute(f"SELECT carte_id, zuul, gozer, effets FROM fullart WHERE carte_id IN ({','.join('?' * len(morceau))})",
                                  morceau):
            resultat[ligne["carte_id"]] = {"zuul": ligne["zuul"], "gozer": ligne["gozer"],
                                           "effets": [e for e in ligne["effets"].split(",") if e]}
    return resultat


def fullart_ecrire(conn, carte_id, zuul, gozer, effets):
    """Enregistre le full-art d'une carte de la collection. DÉFINITIF : une carte qui a déjà un full-art ne peut plus en changer (DejaFullArt)."""
    if not (zuul or gozer or effets):
        raise ValueError("choisis au moins un calque ou un effet")
    existe = conn.execute("SELECT 1 FROM cartes WHERE id = ? AND supprime_le IS NULL", (carte_id,)).fetchone()
    if not existe:
        raise ValueError("carte introuvable")
    if fullart_existe(conn, carte_id):
        raise DejaFullArt(carte_id)
    conn.execute("INSERT INTO fullart (carte_id, zuul, gozer, effets) VALUES (?, ?, ?, ?)", (carte_id, zuul, gozer, ",".join(effets)))


def fullart_retirer(conn, carte_id):
    conn.execute("DELETE FROM fullart WHERE carte_id = ?", (carte_id,))


class DejaFullArt(Exception):
    """Cette carte est déjà full-art : c'est DÉFINITIF (on ne peut ni le retirer ni le modifier)."""


def fullart_existe(conn, carte_id):
    return conn.execute("SELECT 1 FROM fullart WHERE carte_id = ?", (carte_id,)).fetchone() is not None


def _signature_carte(titre, rarete, description, intro, surnom, perso, adresse_image, zoom, x, y):
    """Ce qui rend deux cartes IDENTIQUES (donc doublons) : même titre, même RANG, même sous-titre, même description, (même surnom pour une carte créée à la
    main), même FICHIER d'image (peu importe la taille de la miniature) et même cadrage (position et taille de l'image)."""
    cle = cadrage.cle_image(adresse_image) if adresse_image else ""
    reglage = "" if zoom is None else f"{round(float(zoom), 2)}/{round(float(x), 1)}/{round(float(y), 1)}"
    return "\x1f".join([_texte_compare(titre), rarete or "", _texte_compare(description), _texte_compare(intro), _texte_compare(surnom) if perso else "",
                        "1" if perso else "0", cle, reglage])


def _texte_compare(texte):
    """Un texte comparé « comme on le lit » : espaces insécables, traits d'union conditionnels, caractères invisibles et espaces multiples ne comptent pas.
    Une carte rapatriée du Hall est nettoyée ainsi à son arrivée : sans cela, la même carte (texte pris sur Wikipédia chez toi, texte nettoyé chez l'autre)
    ne serait jamais reconnue comme un doublon."""
    return " ".join(web.normaliser_caracteres(texte or "").split())


# Les signatures de toutes les cartes de la collection (hors corbeille), en SQL : (id, sig).
_SQL_SIGNATURES = ("SELECT x.id AS id, x.titre AS titre, x.rarete AS rarete, x.personnalisee AS perso, signature_carte(x.titre, x.rarete, x.description, x.intro, x.surnom, "
                   "x.personnalisee, COALESCE(x.url_image, x.url_miniature), k.zoom, k.x, k.y) AS sig FROM cartes x "
                   "LEFT JOIN cadrage_carte k ON k.carte_id = x.id "
                   "WHERE x.supprime_le IS NULL")


def cadrage_ecrire(conn, url_article, cle, zoom, x, y, ratio=None):
    """Enregistre le cadrage de l'illustration d'un article (le fichier d'image `cle`) ; le cadrage d'origine supprime la ligne."""
    zoom, x, y, ratio = cadrage.valider(zoom, x, y, ratio)
    with transaction(conn):
        if cadrage.est_defaut(zoom, x, y):
            conn.execute("DELETE FROM cadrage_image WHERE url_article = ? AND image = ?", (url_article, cle))
        else:
            conn.execute("INSERT INTO cadrage_image (url_article, image, zoom, x, y, ratio) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (url_article, image) "
                         "DO UPDATE SET zoom = excluded.zoom, x = excluded.x, y = excluded.y, ratio = excluded.ratio", (url_article, cle, zoom, x, y, ratio))


def cadrage_ecrire_carte(conn, carte_id, url_article, cle, zoom, x, y, ratio=None, modele="toujours"):
    """Enregistre le cadrage de l'illustration d'UNE carte (les autres exemplaires de la même carte ne bougent pas : s'ils sont dimensionnés autrement,
    ce ne sont plus des doublons). Le cadrage d'origine supprime la ligne. Il devient aussi le MODÈLE de l'article et de l'image (`modele` : "toujours",
    "si_absent" ou "non") : les NOUVELLES cartes de la même image le reçoivent automatiquement."""
    zoom, x, y, ratio = cadrage.valider(zoom, x, y, ratio)
    defaut = cadrage.est_defaut(zoom, x, y)
    with transaction(conn):
        if defaut:
            conn.execute("DELETE FROM cadrage_carte WHERE carte_id = ?", (int(carte_id),))
        else:
            conn.execute("INSERT INTO cadrage_carte (carte_id, zoom, x, y, ratio) VALUES (?, ?, ?, ?, ?) ON CONFLICT (carte_id) "
                         "DO UPDATE SET zoom = excluded.zoom, x = excluded.x, y = excluded.y, ratio = excluded.ratio", (int(carte_id), zoom, x, y, ratio))
    if modele == "toujours" or (modele == "si_absent" and cadrage_lire(conn, url_article, cle) is None):
        cadrage_ecrire(conn, url_article, cle, zoom, x, y, ratio)


def cadrage_carte_lire(conn, carte_id):
    ligne = conn.execute("SELECT zoom, x, y, ratio FROM cadrage_carte WHERE carte_id = ?", (int(carte_id),)).fetchone()
    return _cadrage_ligne(ligne) if ligne else None


def _copier_modele_cadrage(conn, carte_id, url_article, adresse_image):
    """Une carte qui arrive (ou qui change d'image) reçoit le cadrage modèle de son article et de son image, s'il y en a un : la même carte tirée de
    nouveau (un doublon) est donc cadrée comme les précédentes. À appeler dans une transaction."""
    cle = cadrage.cle_image(adresse_image) if adresse_image and adresse_image != "no-image" else ""
    if cle:
        conn.execute("INSERT OR REPLACE INTO cadrage_carte (carte_id, zoom, x, y, ratio) SELECT ?, zoom, x, y, ratio FROM cadrage_image "
                     "WHERE url_article = ? AND image = ?", (int(carte_id), url_article, cle))


def _cadrage_ligne(ligne):
    c = {"zoom": ligne["zoom"], "x": ligne["x"], "y": ligne["y"]}
    if ligne["ratio"] is not None:
        c["ratio"] = ligne["ratio"]
    return c


def cadrage_lire(conn, url_article, cle):
    ligne = conn.execute("SELECT zoom, x, y, ratio FROM cadrage_image WHERE url_article = ? AND image = ?", (url_article, cle)).fetchone()
    return _cadrage_ligne(ligne) if ligne else None


def _cadrages_des_cartes(conn, cartes):
    """Attache `cadrage` ({zoom, x, y} ou None) à chaque carte : celui de SON article et de SON fichier d'image (les doublons le partagent)."""
    identifiants = [c["id"] for c in cartes if c.get("id") is not None]
    par_carte = {}
    for debut in range(0, len(identifiants), 400):
        morceau = identifiants[debut:debut + 400]
        for ligne in conn.execute(f"SELECT carte_id, zoom, x, y, ratio FROM cadrage_carte WHERE carte_id IN ({','.join('?' * len(morceau))})", morceau):
            par_carte[ligne["carte_id"]] = _cadrage_ligne(ligne)
    for carte in cartes:
        carte["cadrage"] = par_carte.get(carte.get("id"))


def _avec_categories(conn, cartes, doublons=True):
    """Ajoute à chaque carte la liste de ses catégories, et, si `doublons` (et réglage
    DOUBLONS_ACTIFS), le bandeau automatique « Doublon ×N » des cartes au titre identique."""
    fa = fullart_des_cartes(conn, [c["id"] for c in cartes])
    for carte in cartes:
        carte["fullart"] = fa.get(carte["id"])
    _cadrages_des_cartes(conn, cartes)
    par_carte = categories_des_cartes(conn, [c["id"] for c in cartes])
    doubles = trouver_doublons(conn, cartes) if doublons else {}
    for carte in cartes:
        liste = list(par_carte.get(carte["id"], []))
        double = doubles.get(carte["id"])
        if double:
            liste.insert(0, double)                    # le bandeau « Doublon » passe en premier
        position = 1 if double else 0
        if sans_illustration(carte):
            liste.insert(position, bandeau_sans_illustration())
            position += 1
        if animee(carte):
            liste.insert(position, bandeau_animee())
        carte["categories"] = liste
    return cartes


# --------------------------------------------------------- sans illustration (automatique)

def sans_illustration(carte):
    """La carte n'a pas d'illustration (l'article n'a pas d'image sur Wikipédia) ? Seulement si la
    catégorie automatique « Sans illustration » est activée (réglage SANS_ILLUSTRATION_ACTIF)."""
    return bool(config.SANS_ILLUSTRATION_ACTIF
                and (carte.get("miniature") or "no-image") == "no-image"
                and (carte.get("image") or "no-image") == "no-image")


def bandeau_sans_illustration():
    """Le bandeau automatique « Sans illustration », au format d'une catégorie (id -3)."""
    return {"id": -3, "nom": config.NOM_SANS_ILLUSTRATION, "couleur": config.SANS_ILLUSTRATION_COULEUR,
            "automatique": True, "info": "L'article n'a pas d'illustration sur Wikipédia"}


# ----------------------------------------------------------------- animée (automatique)

def est_gif(adresse):
    """L'adresse est celle d'une image GIF (animée) : se termine par .gif, éventuellement avant un « ? »."""
    return isinstance(adresse, str) and adresse.split("?", 1)[0].lower().endswith(".gif")


def animee(carte):
    """L'illustration affichée sur la carte est une VRAIE image animée ? Il faut un fichier .gif ET que le GIF soit réellement animé (plusieurs
    images) : un GIF fixe n'est pas classé « Animée ». `gif_anime` : 1 (animé), 0 (fixe) ou None (pas encore vérifié : pas classé en attendant).
    Seulement si la catégorie automatique « Animée » est activée (réglage ANIMEE_ACTIF). On regarde l'image réellement affichée : la miniature,
    à défaut l'image."""
    if not config.ANIMEE_ACTIF:
        return False
    affichee = carte.get("miniature") or "no-image"
    if affichee == "no-image":
        affichee = carte.get("image") or "no-image"
    return est_gif(affichee) and carte.get("gif_anime") == 1


def bandeau_animee():
    """Le bandeau automatique « Animée », au format d'une catégorie (id -4)."""
    return {"id": -4, "nom": config.NOM_ANIMEE, "couleur": config.ANIMEE_COULEUR, "automatique": True,
            "info": "L'illustration de cette carte est une image animée (GIF)"}


_SQL_GIF = ("(LOWER(COALESCE(c.url_miniature, c.url_image, '')) LIKE '%.gif' "
            "OR LOWER(COALESCE(c.url_miniature, c.url_image, '')) LIKE '%.gif?%')")
_SQL_ANIMEE = "(" + _SQL_GIF + " AND c.gif_anime = 1)"           # un GIF qui est VRAIMENT animé (les GIF fixes ne comptent pas)


def gifs_a_verifier(conn, limite=20):
    """Les cartes dont l'illustration est un .gif et dont on ne sait pas encore s'il est animé : [(id, adresse affichée)], les plus récentes d'abord."""
    lignes = conn.execute("SELECT c.id, COALESCE(c.url_miniature, c.url_image) AS adresse FROM cartes c "
                          f"WHERE c.supprime_le IS NULL AND c.gif_anime IS NULL AND {_SQL_GIF} ORDER BY c.id DESC LIMIT ?", (int(limite),)).fetchall()
    return [(l["id"], l["adresse"]) for l in lignes]


def marquer_gif(conn, identifiant, anime):
    """Enregistre si le GIF d'une carte est animé (True), fixe (False) ; None : à revérifier plus tard."""
    valeur = 1 if anime is True else (0 if anime is False else None)
    with transaction(conn):
        conn.execute("UPDATE cartes SET gif_anime = ? WHERE id = ?", (valeur, int(identifiant)))


def compter_animees(conn):
    """Nombre de cartes de la collection (hors corbeille) dont l'illustration est un GIF."""
    return conn.execute("SELECT COUNT(*) FROM cartes c WHERE c.supprime_le IS NULL AND (" + _SQL_ANIMEE + ")").fetchone()[0]


def compter_sans_illustration(conn):
    """Nombre de cartes de la collection (hors corbeille) sans illustration."""
    return conn.execute("SELECT COUNT(*) FROM cartes WHERE supprime_le IS NULL "
                        "AND url_image IS NULL AND url_miniature IS NULL").fetchone()[0]


# ---------------------------------------------------------------- doublons (automatique)

def singulier(nom):
    """Forme au singulier d'un nom de catégorie (« Doublons » -> « Doublon ») pour le bandeau « Doublon ×2 » : on
    retire un « s » final (sauf « ss »). Un nom sans « s » final est gardé tel quel."""
    return nom[:-1] if len(nom) > 3 and nom.endswith("s") and not nom.endswith("ss") else nom


def _bandeau_doublon(n, info):
    return {"id": 0, "nom": f"{singulier(config.NOM_DOUBLONS)} ×{n}", "couleur": config.DOUBLONS_COULEUR,
            "automatique": True, "info": info}


def trouver_doublons(conn, cartes):
    """Les doublons parmi ces cartes (dictionnaires de la collection, ou titres pour les cartes Wikipédia). La corbeille ne compte pas.
    Deux cartes sont des doublons si elles sont IDENTIQUES : même titre, même RANG, même sous-titre, même description (et même surnom pour une carte créée
    à la main), MÊME IMAGE et même CADRAGE de l'image (position et taille). Si le rang ou l'image d'une des deux est différent, ou si l'image est
    dimensionnée autrement, ce ne sont plus des doublons.
    Renvoie {identifiant de la carte: bandeau} (bandeau au format d'une catégorie, id 0 : automatique) ; si on donne des titres, {titre: bandeau} pour les
    cartes Wikipédia (par titre seulement : on ne connaît pas leur image)."""
    if not config.DOUBLONS_ACTIFS or not cartes:
        return {}
    if isinstance(cartes[0], str):
        resultat = {}
        titres = list(dict.fromkeys(cartes))
        for debut in range(0, len(titres), 500):
            morceau = titres[debut:debut + 500]
            for ligne in conn.execute(
                    "SELECT titre, COUNT(*), GROUP_CONCAT(rarete) FROM cartes WHERE supprime_le IS NULL AND personnalisee = 0 "
                    f"AND titre IN ({','.join('?' * len(morceau))}) GROUP BY titre HAVING COUNT(*) > 1", morceau):
                rangs = [r for r in config.CODES if r in ligne[2].split(",")]
                rangs += sorted(set(ligne[2].split(",")) - set(rangs))
                resultat[ligne[0]] = _bandeau_doublon(ligne[1], f"{ligne[1]} cartes « {ligne[0]} » dans ta collection "
                                                                 f"(rangs : {', '.join(config.symbole(r) for r in rangs)})")
        return resultat
    titres = list(dict.fromkeys(c["titre"] for c in cartes if c.get("id") is not None))
    groupes = {}                                          # signature -> [(id, rang, perso)]
    for debut in range(0, len(titres), 500):
        morceau = titres[debut:debut + 500]
        lignes = conn.execute(f"SELECT id, titre, rarete, perso, sig FROM ({_SQL_SIGNATURES} AND x.titre IN ({','.join('?' * len(morceau))}))", morceau).fetchall()
        for ligne in lignes:
            groupes.setdefault(ligne["sig"], []).append((ligne["id"], ligne["rarete"], bool(ligne["perso"]), ligne["titre"]))
    par_identifiant = {}
    for membres in groupes.values():
        if len(membres) < 2:
            continue
        if membres[0][2]:
            info = (f"{len(membres)} cartes personnalisées « {membres[0][3]} » identiques "
                    "(même titre, sous-titre, description, surnom, image et cadrage)")
        else:
            info = (f"{len(membres)} cartes « {membres[0][3]} » identiques dans ta collection, rang {config.symbole(membres[0][1])} "
                    "(même texte, même image et même cadrage)")
        bandeau = _bandeau_doublon(len(membres), info)
        for membre in membres:
            par_identifiant[membre[0]] = bandeau
    return {c["id"]: par_identifiant[c["id"]] for c in cartes if c.get("id") in par_identifiant}


# Les cartes en double, en SQL (alias « c » de la table cartes) : voir trouver_doublons pour la règle (même signature qu'une autre carte).
_SQL_DOUBLON = (f"(c.id IN (SELECT id FROM (SELECT id, COUNT(*) OVER (PARTITION BY sig) AS n FROM ({_SQL_SIGNATURES})) WHERE n > 1))")


def cartes_meme_titre(conn, titres, exclure=()):
    """Les cartes de la collection qui portent l'un de ces titres (avec leurs catégories et leur
    bandeau « Doublon »), sauf celles de `exclure`. Sert à mettre à jour le bandeau « Doublon »
    des cartes déjà affichées quand un doublon apparaît ou disparaît."""
    titres = list(dict.fromkeys(titres))
    exclure = set(exclure)
    cartes = []
    for debut in range(0, len(titres), 500):
        morceau = titres[debut:debut + 500]
        for ligne in conn.execute(
                "SELECT * FROM cartes WHERE supprime_le IS NULL AND titre IN "
                f"({','.join('?' * len(morceau))})", morceau):
            if ligne["id"] not in exclure:
                cartes.append(_depuis_ligne(ligne))
    return _avec_categories(conn, cartes)


def compter_doublons(conn):
    """Nombre de cartes de la collection qui ont un doublon (cartes identiques : texte, image et cadrage)."""
    return conn.execute(
        f"SELECT COUNT(*) FROM cartes c WHERE c.supprime_le IS NULL AND {_SQL_DOUBLON}"
    ).fetchone()[0]


# ----------------------------------------------- collection : filtres et pagination

def _filtre_sql(filtres):
    """Condition WHERE (et ses paramètres) pour les filtres : rangs, favoris, catégorie."""
    conditions, parametres = ["c.supprime_le IS NULL"], []     # jamais les cartes de la corbeille
    rangs = [r for r in filtres.get("rangs") or [] if isinstance(r, str)]
    if rangs:
        conditions.append(f"c.rarete IN ({','.join('?' * len(rangs))})")
        parametres.extend(rangs)
    if filtres.get("favoris"):
        conditions.append("c.favori = 1")
    if filtres.get("sans_personnalisees"):                 # (le Hall : les cartes créées à la main ne sont pas partagées)
        conditions.append("c.personnalisee = 0")
    for mot in mots_recherche(filtres.get("recherche")):     # recherche : tous les mots, dans le titre...
        motif = "%" + mot.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        champs = filtres.get("champs") or champs_recherche("COLL")        # les champs cochés dans la Configuration
        conditions.append("(" + " OR ".join(f"norm(c.{col}) LIKE ? ESCAPE '\\'" for col in champs) + ")")
        parametres.extend([motif] * len(champs))
    categorie = filtres.get("categorie")
    if categorie == -1:                                   # « sans catégorie »
        conditions.append("NOT EXISTS (SELECT 1 FROM cartes_categories x WHERE x.carte_id = c.id)")
    elif categorie == -3:                                 # « sans illustration » : pas d'image
        conditions.append("c.url_image IS NULL AND c.url_miniature IS NULL")
    elif categorie == -4:                                 # « animée » : l'illustration est un GIF
        conditions.append("(" + _SQL_ANIMEE + ")")
    elif categorie == -2:                                 # « doublons » : cartes identiques (texte, image et cadrage)
        conditions.append(_SQL_DOUBLON)
    elif isinstance(categorie, int) and not isinstance(categorie, bool) and categorie > 0:
        conditions.append("EXISTS (SELECT 1 FROM cartes_categories x "
                          "WHERE x.carte_id = c.id AND x.categorie_id = ?)")
        parametres.append(categorie)
    return (" WHERE " + " AND ".join(conditions)) if conditions else "", parametres


def lister_cartes_page(conn, filtres, page, par_page, tri=TRI_DEFAUT):
    """Une page de la collection, selon les filtres et l'ordre `tri` (voir TRIS ; un code inconnu
    donne l'ordre par défaut : date, des plus récentes aux plus anciennes). Renvoie un dictionnaire :
    cartes (avec leurs catégories), page (corrigée si hors limites), pages, par_page,
    total_filtre (cartes correspondant aux filtres) et total (toute la collection)."""
    par_page = max(1, int(par_page))
    where, parametres = _filtre_sql(filtres)
    total_filtre = conn.execute(f"SELECT COUNT(*) FROM cartes c{where}", parametres).fetchone()[0]
    pages = max(1, -(-total_filtre // par_page))
    page = min(max(1, int(page)), pages)
    lignes = conn.execute(
        f"SELECT c.* FROM cartes c{where} ORDER BY {TRIS.get(tri, TRIS[TRI_DEFAUT])[1]} "
        "LIMIT ? OFFSET ?",
        parametres + [par_page, (page - 1) * par_page]).fetchall()
    return {
        "cartes": _avec_categories(conn, [_depuis_ligne(ligne) for ligne in lignes]),
        "page": page, "pages": pages, "par_page": par_page,
        "total_filtre": total_filtre, "total": compter(conn),
    }


def compter_par_rang(conn):
    """Nombre de cartes de la collection par rang : {code: nombre}."""
    return {ligne[0]: ligne[1] for ligne in conn.execute(
        "SELECT rarete, COUNT(*) FROM cartes WHERE supprime_le IS NULL GROUP BY rarete")}


def compter_par_url(conn, urls):
    """Combien de cartes de la collection portent sur chacun de ces articles : {url: nombre}."""
    resultat = {}
    urls = [u for u in urls if u]
    for debut in range(0, len(urls), 500):
        morceau = urls[debut:debut + 500]
        for ligne in conn.execute(
                "SELECT url_article, COUNT(*) FROM cartes WHERE supprime_le IS NULL "
                f"AND url_article IN ({','.join('?' * len(morceau))}) GROUP BY url_article",
                morceau):
            resultat[ligne[0]] = ligne[1]
    return resultat


def compter_favoris(conn):
    return conn.execute("SELECT COUNT(*) FROM cartes WHERE favori = 1 AND supprime_le IS NULL").fetchone()[0]


# --------------------------------------------------------------------- catégories

def _categorie_depuis_ligne(ligne):
    return {
        "id": ligne["id"], "nom": ligne["nom"], "cle": ligne["cle"], "couleur": ligne["couleur"],
        "metas": [ligne[f"meta{i}"] for i in range(1, cat.NB_METAS + 1)],
        "nb_cartes": ligne["nb_cartes"] if "nb_cartes" in ligne.keys() else 0,
    }


def lister_categories(conn):
    """Toutes les catégories (avec le nombre de cartes de chacune), dans l'ordre de création."""
    lignes = conn.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM cartes_categories x JOIN cartes k ON k.id = x.carte_id "
        "WHERE x.categorie_id = c.id AND k.supprime_le IS NULL) "
        "AS nb_cartes FROM categories c ORDER BY c.position, c.id").fetchall()
    return [_categorie_depuis_ligne(ligne) for ligne in lignes]


def enregistrer_categories(conn, categories, supprimees=()):
    """Applique des catégories DÉJÀ VÉRIFIÉES (voir categories.verifier_categories) :
    supprime celles de `supprimees` (seuls les liens avec les cartes disparaissent), modifie
    celles qui ont un `id`, crée les autres. Une seule transaction : tout ou rien.
    Renvoie les identifiants des catégories de la liste, dans l'ordre."""
    with transaction(conn):
        for identifiant in supprimees:
            conn.execute("DELETE FROM categories WHERE id = ?", (identifiant,))
        modifiees = [c["id"] for c in categories if c["id"]]
        # Échanger deux noms violerait l'unicité à mi-chemin : on libère d'abord les clés.
        for identifiant in modifiees:
            conn.execute("UPDATE categories SET cle = char(1) || id WHERE id = ?", (identifiant,))
        position = conn.execute("SELECT COALESCE(MAX(position), 0) FROM categories").fetchone()[0]
        identifiants = []
        for c in categories:
            champs = (c["nom"], c["cle"], c["couleur"], *c["metas"])
            if c["id"]:
                conn.execute(
                    "UPDATE categories SET nom = ?, cle = ?, couleur = ?, meta1 = ?, meta2 = ?, "
                    "meta3 = ?, meta4 = ?, meta5 = ? WHERE id = ?", (*champs, c["id"]))
                identifiants.append(c["id"])
            else:
                position += 1
                curseur = conn.execute(
                    "INSERT INTO categories (nom, cle, couleur, meta1, meta2, meta3, meta4, meta5, "
                    "position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (*champs, position))
                identifiants.append(curseur.lastrowid)
    return identifiants


def categories_des_cartes(conn, identifiants):
    """Catégories de chaque carte : {id de la carte: [{id, nom, couleur}, ...]}."""
    resultat = {}
    identifiants = list(identifiants)
    for debut in range(0, len(identifiants), 500):
        morceau = identifiants[debut:debut + 500]
        for ligne in conn.execute(
                "SELECT x.carte_id, c.id, c.nom, c.couleur FROM cartes_categories x "
                "JOIN categories c ON c.id = x.categorie_id "
                f"WHERE x.carte_id IN ({','.join('?' * len(morceau))}) ORDER BY c.position, c.id",
                morceau):
            resultat.setdefault(ligne[0], []).append(
                {"id": ligne[1], "nom": ligne[2], "couleur": ligne[3]})
    return resultat


def assigner_categories(conn, identifiants_cartes, identifiants_categories):
    """Classe des cartes dans des catégories. Renvoie le nombre de liens créés (les cartes ou
    catégories inexistantes et les liens déjà présents sont ignorés)."""
    crees = 0
    with transaction(conn):
        for carte in identifiants_cartes:
            for categorie in identifiants_categories:
                crees += conn.execute(
                    "INSERT OR IGNORE INTO cartes_categories (carte_id, categorie_id) "
                    "SELECT ?, ? WHERE EXISTS (SELECT 1 FROM cartes WHERE id = ?) "
                    "AND EXISTS (SELECT 1 FROM categories WHERE id = ?)",
                    (carte, categorie, carte, categorie)).rowcount
    return crees


def retirer_categories(conn, identifiants_cartes, identifiants_categories):
    """Retire des cartes de catégories (les cartes ne sont pas supprimées). Renvoie le nombre
    de liens supprimés."""
    retires = 0
    with transaction(conn):
        for carte in identifiants_cartes:
            for categorie in identifiants_categories:
                retires += conn.execute(
                    "DELETE FROM cartes_categories WHERE carte_id = ? AND categorie_id = ?",
                    (carte, categorie)).rowcount
    return retires


def classer_automatiquement(conn, identifiants_cartes):
    """Classe des cartes selon les « meta » des catégories (cherchées dans la courte description et,
    si META_DANS_INTRO est actif, dans les phrases de l'introduction).
    Renvoie le nombre de liens créés."""
    categories = [c for c in lister_categories(conn) if any(c["metas"])]
    if not categories or not identifiants_cartes:
        return 0
    liens = []
    identifiants_cartes = list(identifiants_cartes)
    for debut in range(0, len(identifiants_cartes), 500):
        morceau = identifiants_cartes[debut:debut + 500]
        for ligne in conn.execute(
                f"SELECT id, description, intro FROM cartes WHERE id IN ({','.join('?' * len(morceau))})",
                morceau):
            for c in categories:
                if cat.metas_trouvees(ligne["description"], c["metas"], intro=ligne["intro"]):
                    liens.append((ligne["id"], c["id"]))
    crees = 0
    with transaction(conn):
        for carte, categorie in liens:
            crees += conn.execute(
                "INSERT OR IGNORE INTO cartes_categories (carte_id, categorie_id) VALUES (?, ?)",
                (carte, categorie)).rowcount
    return crees


def classer_cartes_existantes(conn, identifiant_categorie):
    """Classe dans une catégorie toute la collection qui correspond à ses « meta ».
    Renvoie le nombre de cartes ajoutées."""
    categorie = next((c for c in lister_categories(conn) if c["id"] == identifiant_categorie), None)
    if categorie is None or not any(categorie["metas"]):
        return 0
    trouvees = [ligne["id"] for ligne in conn.execute(
        "SELECT id, description, intro FROM cartes WHERE supprime_le IS NULL "
        "AND (description IS NOT NULL OR intro IS NOT NULL)")
        if cat.metas_trouvees(ligne["description"], categorie["metas"], intro=ligne["intro"])]
    return assigner_categories(conn, trouvees, [identifiant_categorie])


def compter(conn):
    """Nombre de cartes de la collection (sans celles de la corbeille)."""
    return conn.execute("SELECT COUNT(*) FROM cartes WHERE supprime_le IS NULL").fetchone()[0]


def compter_partageables(conn):
    """Nombre de cartes que les autres collectionneurs voient dans la collection partagée : sans la corbeille ET sans les cartes créées à la main."""
    return conn.execute("SELECT COUNT(*) FROM cartes WHERE supprime_le IS NULL AND personnalisee = 0").fetchone()[0]


# ------------------------------------------------------------------ réserve de cartes

def _instant_utc(decalage_secondes=0):
    """Date et heure UTC au format texte de la base (comparables entre elles)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + decalage_secondes))


def reserve_ajouter(conn, articles):
    """Range des cartes préparées dans la réserve. Un article déjà présent est ignoré.
    Renvoie le nombre de cartes ajoutées."""
    ajoutees = 0
    maintenant = _instant_utc()
    with transaction(conn):
        for art in articles:
            image = _ou_none(art.get("image"), "no-image")
            try:
                ajoutees += conn.execute(
                    "INSERT INTO reserve (titre, description, intro, rarete, rarete_tiree, "
                    "vues_moyenne, vues_total, url_article, url_image, url_miniature, langue, "
                    "prepare_le, nb_langues, taille_octets, nb_revisions, revisions_plafonnees, nb_liens_entrants) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT (url_article) DO NOTHING",
                    (str(art["titre"]), _ou_none(art.get("description"), "no-description"),
                     _ou_none(art.get("intro"), "no-intro"), str(art["rarete"]),
                     str(art.get("rarete_tiree") or art["rarete"]), float(art["vues_moyenne"]),
                     int(art["vues_total"]), str(art["url"]), image,
                     _ou_none(art.get("miniature"), "no-image") or image,
                     str(art.get("langue") or config.LANGUE), maintenant,
                     _entier_ou_none(art.get("nb_langues")),
                     _entier_ou_none(art.get("taille_octets")),
                     _entier_ou_none(art.get("nb_revisions")), 1 if art.get("revisions_plafonnees") else 0,
                     _entier_ou_none(art.get("nb_liens_entrants")))).rowcount
            except sqlite3.IntegrityError:
                continue          # carte refusée par les contraintes de la base : on passe à la suivante
    return ajoutees


def _garder_image_vue(conn, url_article, image, miniature):
    """Une image que la carte affichait puis quitte (changée ou retirée) reste dans la liste des images de son article : elle n'en disparaît jamais.
    À appeler dans une transaction."""
    cle = cadrage.cle_image(image)
    if cle and image and url_article:
        conn.execute("INSERT OR IGNORE INTO image_vue (url_article, cle, nom, image, miniature, largeur, hauteur, mineure, ordre) VALUES (?, ?, ?, ?, ?, 0, 0, 0, 1000)",
                     (url_article, cle, (cadrage.nom_fichier(image) or cle)[:200], image, miniature or image))


def images_des_cartes_du_meme_article(conn, url_article):
    """Les images que portent (ou portaient : corbeille comprise) les cartes de cet article dans ta collection : [(image, miniature)]. Une autre carte du même
    article peut avoir gardé une image que l'article ne propose plus."""
    lignes = conn.execute("SELECT DISTINCT url_image, url_miniature FROM cartes WHERE url_article = ? AND url_image IS NOT NULL", (url_article,)).fetchall()
    return [(l["url_image"], l["url_miniature"] or l["url_image"]) for l in lignes]


def mettre_a_jour_image(conn, identifiant, url_image, url_miniature):
    """Enregistre la nouvelle illustration d'une carte (adresses déjà vérifiées par l'appelant). Renvoie True si la carte existe."""
    with transaction(conn):
        avant = conn.execute("SELECT url_image, url_miniature, url_article FROM cartes WHERE id = ? AND supprime_le IS NULL", (int(identifiant),)).fetchone()
        if avant is not None and avant["url_image"] and avant["url_image"] != url_image:
            _garder_image_vue(conn, avant["url_article"], avant["url_image"], avant["url_miniature"])           # l'image qu'on quitte est GARDÉE : c'est l'image d'origine de la carte
            conn.execute("INSERT OR IGNORE INTO image_retiree (carte_id, image, miniature) VALUES (?, ?, ?)",
                         (int(identifiant), avant["url_image"], avant["url_miniature"]))
        existe = conn.execute("UPDATE cartes SET url_image = ?, url_miniature = ?, gif_anime = NULL WHERE id = ? AND supprime_le IS NULL",
                              (url_image, url_miniature, int(identifiant))).rowcount > 0
        if existe:                                                  # le cadrage appartenait à l'ancienne image ; la nouvelle reprend celui qu'on avait réglé pour elle
            conn.execute("DELETE FROM cadrage_carte WHERE carte_id = ?", (int(identifiant),))
            ligne = conn.execute("SELECT url_article FROM cartes WHERE id = ?", (int(identifiant),)).fetchone()
            _copier_modele_cadrage(conn, identifiant, ligne["url_article"], url_image or url_miniature)
        return existe


def retirer_image(conn, identifiant):
    """Enlève l'illustration d'une carte (elle redevient « Sans illustration ») ; on peut en remettre une plus tard. L'image D'ORIGINE de la carte (celle qu'elle
    avait avant tout changement) est gardée de côté (table image_retiree) pour toujours pouvoir être proposée de nouveau. Renvoie True si la carte existe."""
    with transaction(conn):
        ancienne = conn.execute("SELECT url_image, url_miniature, url_article FROM cartes WHERE id = ? AND supprime_le IS NULL", (int(identifiant),)).fetchone()
        if ancienne is not None and ancienne["url_image"]:
            _garder_image_vue(conn, ancienne["url_article"], ancienne["url_image"], ancienne["url_miniature"])
            conn.execute("INSERT OR IGNORE INTO image_retiree (carte_id, image, miniature) VALUES (?, ?, ?)",
                         (int(identifiant), ancienne["url_image"], ancienne["url_miniature"]))        # (l'image d'origine déjà gardée n'est jamais écrasée)
        conn.execute("DELETE FROM cadrage_carte WHERE carte_id = ?", (int(identifiant),))
        return conn.execute("UPDATE cartes SET url_image = NULL, url_miniature = NULL, gif_anime = NULL WHERE id = ? AND supprime_le IS NULL",
                            (int(identifiant),)).rowcount > 0


IMAGES_VUES_MAX = 300


def images_vues_lire(conn, url_article):
    """Les images déjà vues dans la liste de cet article (dans l'ordre où elles sont apparues) : [{nom, image, miniature, largeur, hauteur, mineure}]."""
    lignes = conn.execute("SELECT nom, image, miniature, largeur, hauteur, mineure FROM image_vue WHERE url_article = ? ORDER BY ordre, rowid", (url_article,)).fetchall()
    return [{"nom": l["nom"], "image": l["image"], "miniature": l["miniature"], "largeur": l["largeur"], "hauteur": l["hauteur"], "mineure": bool(l["mineure"])} for l in lignes]


def images_vues_ecrire(conn, url_article, images):
    """Garde les images de la liste d'un article : les nouvelles sont ajoutées, celles qu'on connaissait déjà sont mises à jour. Rien n'est jamais retiré."""
    with transaction(conn):
        for ordre, i in enumerate(images[:IMAGES_VUES_MAX]):
            cle = cadrage.cle_image(i["image"])
            if not cle or i.get("actuelle") or i.get("precedente"):          # (celles de la carte elle-même ont leur propre mémoire)
                continue
            conn.execute("INSERT INTO image_vue (url_article, cle, nom, image, miniature, largeur, hauteur, mineure, ordre) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                         "ON CONFLICT (url_article, cle) DO UPDATE SET nom = excluded.nom, image = excluded.image, miniature = excluded.miniature, "
                         "largeur = excluded.largeur, hauteur = excluded.hauteur, mineure = excluded.mineure, ordre = excluded.ordre",
                         (url_article, cle, str(i.get("nom") or cle)[:200], i["image"], i.get("miniature") or i["image"], int(i.get("largeur") or 0), int(i.get("hauteur") or 0),
                          1 if i.get("mineure") else 0, ordre))


def image_retiree(conn, identifiant):
    """L'image D'ORIGINE d'une carte (gardée la première fois qu'on change ou retire son illustration), à pouvoir remettre : (image, miniature) ou None."""
    ligne = conn.execute("SELECT image, miniature FROM image_retiree WHERE carte_id = ?", (int(identifiant),)).fetchone()
    return (ligne["image"], ligne["miniature"] or ligne["image"]) if ligne else None


def reserve_compter(conn):
    return conn.execute("SELECT COUNT(*) FROM reserve").fetchone()[0]


def reserve_compter_completes(conn, avec_stats=True):
    """Cartes de la réserve prêtes à être ouvertes : toutes, ou (avec_stats) seulement celles qui ont leurs modifications ET
    leurs liens entrants."""
    if not avec_stats:
        return reserve_compter(conn)
    return conn.execute("SELECT COUNT(*) FROM reserve WHERE nb_revisions IS NOT NULL AND nb_liens_entrants IS NOT NULL").fetchone()[0]


def jetons_lire(conn):
    """(jetons, instant de la dernière mise à jour) : le stock de paquets ouvrables, avant le rattrapage du temps écoulé."""
    ligne = conn.execute("SELECT jetons, maj FROM ouverture_jetons WHERE id = 1").fetchone()
    return (float(ligne[0]), float(ligne[1])) if ligne else (1000.0, 0.0)


def jetons_ecrire(conn, jetons, instant):
    with transaction(conn):
        conn.execute("UPDATE ouverture_jetons SET jetons = ?, maj = ? WHERE id = 1", (max(0.0, float(jetons)), float(instant)))


def reserve_urls(conn):
    """Les adresses des articles déjà dans la réserve (pour ne pas les préparer deux fois)."""
    return {ligne[0] for ligne in conn.execute("SELECT url_article FROM reserve")}


def reserve_purger(conn, validite_jours):
    """Jette les cartes préparées depuis plus de `validite_jours` jours. Renvoie leur nombre."""
    limite = _instant_utc(-86400 * int(validite_jours))
    with transaction(conn):
        return conn.execute("DELETE FROM reserve WHERE prepare_le < ?", (limite,)).rowcount


def reserve_prelever(conn, nombre, validite_jours):
    """Retire de la réserve jusqu'à `nombre` cartes (les plus anciennes d'abord, sans celles qui
    sont périmées) et les renvoie au format des articles du tirage. Une seule transaction : deux
    paquets ouverts en même temps ne reçoivent jamais la même carte."""
    if nombre <= 0:
        return []
    limite = _instant_utc(-86400 * int(validite_jours))
    articles = []
    with transaction(conn):
        lignes = conn.execute(
            "SELECT * FROM reserve WHERE prepare_le >= ? "
            "ORDER BY (nb_revisions IS NULL OR nb_liens_entrants IS NULL) ASC, prepare_le ASC, id ASC LIMIT ?",    # complètes d'abord
            (limite, int(nombre))).fetchall()
        for ligne in lignes:
            conn.execute("DELETE FROM reserve WHERE id = ?", (ligne["id"],))
            articles.append({
                "titre": ligne["titre"], "description": ligne["description"] or "no-description",
                "intro": ligne["intro"] or "no-intro", "rarete": ligne["rarete"],
                "rarete_nom": config.nom_rang(ligne["rarete"]),
                "rarete_tiree": ligne["rarete_tiree"], "vues_moyenne": ligne["vues_moyenne"],
                "vues_total": ligne["vues_total"], "url": ligne["url_article"],
                "image": ligne["url_image"] or "no-image",
                "miniature": ligne["url_miniature"] or ligne["url_image"] or "no-image",
                "langue": ligne["langue"], "tire_le": None,
                "nb_langues": ligne["nb_langues"], "taille_octets": ligne["taille_octets"],
                "nb_revisions": ligne["nb_revisions"], "revisions_plafonnees": bool(ligne["revisions_plafonnees"]),
                "nb_liens_entrants": ligne["nb_liens_entrants"]})
    return articles


def reserve_vider(conn):
    """Vide la réserve. Renvoie le nombre de cartes jetées."""
    with transaction(conn):
        return conn.execute("DELETE FROM reserve").rowcount


def reserve_plus_ancienne(conn):
    """Date (UTC) de préparation de la carte la plus ancienne de la réserve, ou None."""
    return conn.execute("SELECT MIN(prepare_le) FROM reserve").fetchone()[0]


def reserve_compter_sans_stats(conn):
    """Nombre de cartes de la réserve qui n'ont pas encore leurs modifications ET leurs liens entrants."""
    return conn.execute("SELECT COUNT(*) FROM reserve WHERE nb_revisions IS NULL OR nb_liens_entrants IS NULL").fetchone()[0]


def reserve_manques_stats(conn):
    """Nombre de valeurs de statistiques manquantes dans la réserve (une requête chacune)."""
    return conn.execute("SELECT COALESCE(SUM((nb_revisions IS NULL) + (nb_liens_entrants IS NULL)), 0) FROM reserve").fetchone()[0]


def reserve_sans_stats(conn, limite=20):
    """Les cartes de la réserve auxquelles il manque des statistiques : [{id, titre, nb_revisions, nb_liens_entrants}]."""
    return [dict(ligne) for ligne in conn.execute(
        "SELECT id, titre, nb_revisions, revisions_plafonnees, nb_liens_entrants FROM reserve "
        "WHERE nb_revisions IS NULL OR nb_liens_entrants IS NULL ORDER BY prepare_le ASC, id ASC LIMIT ?", (int(limite),)).fetchall()]


def reserve_maj_stats(conn, identifiant, nb_revisions, revisions_plafonnees, nb_liens_entrants):
    """Range les statistiques obtenues pour une carte de la réserve (une valeur absente reste à compléter)."""
    with transaction(conn):
        conn.execute("UPDATE reserve SET nb_revisions = COALESCE(?, nb_revisions), "
                     "revisions_plafonnees = CASE WHEN ? IS NULL THEN revisions_plafonnees ELSE ? END, "
                     "nb_liens_entrants = COALESCE(?, nb_liens_entrants) WHERE id = ?",
                     (_entier_ou_none(nb_revisions), _entier_ou_none(nb_revisions), 1 if revisions_plafonnees else 0,
                      _entier_ou_none(nb_liens_entrants), int(identifiant)))


def reserve_instants(conn, secondes=3600, source="reserve"):
    """Les instants (secondes depuis 1970) des requêtes d'arrière-plan de la dernière heure, du plus ancien au plus récent."""
    return [ligne[0] for ligne in conn.execute(
        "SELECT instant FROM reserve_requetes WHERE instant >= ? AND source = ? ORDER BY instant ASC",
        (time.time() - secondes, source))]


def reserve_noter_requete(conn, source="reserve"):
    """Note une requête d'arrière-plan dans le journal (plafond horaire). `source` : « reserve »
    (pré-chargement des cartes) ou « stats » (statistiques des cartes) : chacune a son plafond."""
    with transaction(conn):
        conn.execute("INSERT INTO reserve_requetes (instant, source) VALUES (?, ?)",
                     (time.time(), source))
        conn.execute("DELETE FROM reserve_requetes WHERE instant < ?", (time.time() - 7200,))


def reserve_requetes_recentes(conn, secondes=3600, source="reserve"):
    """(nombre de requêtes d'arrière-plan de cette source dans la dernière heure, instant de la
    plus ancienne ou None) : le plafond horaire se libère quand la plus ancienne sort de la fenêtre."""
    ligne = conn.execute("SELECT COUNT(*), MIN(instant) FROM reserve_requetes "
                         "WHERE instant >= ? AND source = ?",
                         (time.time() - secondes, source)).fetchone()
    return ligne[0], ligne[1]


# ------------------------------------------------------- statistiques des cartes

STATS_ESSAIS_MAX = 3       # une carte dont la page ne répond pas (404...) est abandonnée après 3 essais

_A_COMPLETER = ("personnalisee = 0 AND (nb_langues IS NULL OR taille_octets IS NULL "
                "OR nb_revisions IS NULL OR nb_liens_entrants IS NULL)")


def stats_manquantes(conn):
    """Nombre de cartes de la collection (hors corbeille) dont il manque encore une statistique."""
    return conn.execute(
        f"SELECT COUNT(*) FROM cartes WHERE supprime_le IS NULL AND stats_essais < ? AND {_A_COMPLETER}",
        (STATS_ESSAIS_MAX,)).fetchone()[0]


def prochaine_carte_a_completer(conn):
    """La carte la plus récente à qui il manque une statistique (ou None) : (id, titre, besoins)
    où `besoins` dit ce qui manque : base (langues, taille), revisions, liens."""
    ligne = conn.execute(
        f"SELECT id, titre, nb_langues, taille_octets, nb_revisions, nb_liens_entrants FROM cartes "
        f"WHERE supprime_le IS NULL AND stats_essais < ? AND {_A_COMPLETER} "
        "ORDER BY id DESC LIMIT 1", (STATS_ESSAIS_MAX,)).fetchone()
    if ligne is None:
        return None
    return {"id": ligne["id"], "titre": ligne["titre"],
            "base": ligne["nb_langues"] is None or ligne["taille_octets"] is None,
            "revisions": ligne["nb_revisions"] is None, "liens": ligne["nb_liens_entrants"] is None}


def cartes_sans_base(conn, limite=20):
    """Les cartes les plus récentes dont langues ou taille manquent : [(id, titre)]."""
    return [(ligne["id"], ligne["titre"]) for ligne in conn.execute(
        "SELECT id, titre FROM cartes WHERE supprime_le IS NULL AND stats_essais < ? "
        "AND personnalisee = 0 AND (nb_langues IS NULL OR taille_octets IS NULL) "
        "ORDER BY id DESC LIMIT ?",
        (STATS_ESSAIS_MAX, int(limite)))]


def enregistrer_stats(conn, identifiant, **valeurs):
    """Enregistre des statistiques d'une carte (nb_langues, taille_octets, nb_revisions,
    revisions_plafonnees, nb_liens_entrants) : seules celles fournies sont modifiées."""
    permises = {"nb_langues", "taille_octets", "nb_revisions", "revisions_plafonnees",
                "nb_liens_entrants"}
    champs = {cle: (1 if cle == "revisions_plafonnees" and valeur else
                    0 if cle == "revisions_plafonnees" else _entier_ou_none(valeur))
              for cle, valeur in valeurs.items() if cle in permises}
    if not champs:
        return
    with transaction(conn):
        conn.execute(f"UPDATE cartes SET {', '.join(f'{cle} = ?' for cle in champs)} WHERE id = ?",
                     (*champs.values(), int(identifiant)))


def noter_echec_stats(conn, identifiant):
    """Une carte dont la page ne donne pas ses statistiques : on compte l'essai, et on abandonne
    après STATS_ESSAIS_MAX pour ne pas insister inutilement auprès de Wikipédia."""
    with transaction(conn):
        conn.execute("UPDATE cartes SET stats_essais = stats_essais + 1 WHERE id = ?",
                     (int(identifiant),))


def stats_de_cartes(conn, identifiants):
    """Les cartes demandées (avec leurs statistiques) : [dict]. Sert à rafraîchir le pied des
    cartes déjà affichées pendant que les statistiques arrivent."""
    cartes = []
    identifiants = list(identifiants)[:200]
    for debut in range(0, len(identifiants), 200):
        morceau = identifiants[debut:debut + 200]
        for ligne in conn.execute(
                f"SELECT * FROM cartes WHERE id IN ({','.join('?' * len(morceau))})", morceau):
            cartes.append(_depuis_ligne(ligne))
    return cartes


# ---------------------------------------------- compteurs de la liste des catégories

def compter_sans_categorie(conn):
    """Cartes de la collection (hors corbeille) qui n'ont aucune catégorie."""
    return conn.execute(
        "SELECT COUNT(*) FROM cartes c WHERE c.supprime_le IS NULL AND NOT EXISTS "
        "(SELECT 1 FROM cartes_categories x WHERE x.carte_id = c.id)").fetchone()[0]


def compteurs_categories(conn):
    """Les nombres affichés entre parenthèses dans la liste déroulante des catégories :
    {"": toute la collection, "-1": sans catégorie, "-2": doublons, "<id>": cartes de la catégorie}."""
    compteurs = {"": compter(conn), "-1": compter_sans_categorie(conn), "-2": compter_doublons(conn),
                 "-3": compter_sans_illustration(conn), "-4": compter_animees(conn)}
    for categorie in lister_categories(conn):
        compteurs[str(categorie["id"])] = categorie["nb_cartes"]
    return compteurs


# ------------------------------------------------------------------ page de profil : vitrines

def titres_vitrines(conn):
    """Les titres des vitrines : {position: titre}."""
    return {ligne[0]: ligne[1] for ligne in conn.execute("SELECT position, titre FROM vitrines")}


def definir_titre_vitrine(conn, position, titre):
    """Donne un titre à la vitrine n° `position` (un titre vide l'efface)."""
    with transaction(conn):
        conn.execute("INSERT INTO vitrines (position, titre) VALUES (?, ?) "
                     "ON CONFLICT (position) DO UPDATE SET titre = excluded.titre",
                     (int(position), str(titre)))


def cartes_des_vitrines(conn, nb_vitrines, nb_emplacements):
    """Les cartes exposées : {(vitrine, emplacement): carte}, pour les vitrines et emplacements
    qui existent. Une carte à la corbeille n'apparaît pas (elle revient si on la restaure)."""
    lignes = conn.execute(
        "SELECT v.vitrine, v.emplacement, c.* FROM vitrine_cartes v JOIN cartes c ON c.id = v.carte_id "
        "WHERE c.supprime_le IS NULL AND v.vitrine <= ? AND v.emplacement <= ?",
        (int(nb_vitrines), int(nb_emplacements))).fetchall()
    cartes = _avec_categories(conn, [_depuis_ligne(ligne) for ligne in lignes])
    return {(ligne["vitrine"], ligne["emplacement"]): carte for ligne, carte in zip(lignes, cartes)}


def placer_carte(conn, vitrine, emplacement, carte_id):
    """Expose une COPIE de la carte à cet emplacement (elle reste dans la collection, et peut être
    exposée à plusieurs endroits). Remplace ce qui s'y trouvait. Renvoie [(vitrine, emplacement)],
    ou None si la carte n'existe pas (ou est à la corbeille)."""
    with transaction(conn):
        existe = conn.execute("SELECT 1 FROM cartes WHERE id = ? AND supprime_le IS NULL",
                              (int(carte_id),)).fetchone()
        if existe is None:
            return None
        conn.execute("INSERT INTO vitrine_cartes (vitrine, emplacement, carte_id) VALUES (?, ?, ?) "
                     "ON CONFLICT (vitrine, emplacement) DO UPDATE SET carte_id = excluded.carte_id",
                     (int(vitrine), int(emplacement), int(carte_id)))
    return [(int(vitrine), int(emplacement))]


def retirer_carte_vitrine(conn, vitrine, emplacement):
    """Vide un emplacement de vitrine (la carte reste dans la collection)."""
    with transaction(conn):
        return conn.execute("DELETE FROM vitrine_cartes WHERE vitrine = ? AND emplacement = ?",
                            (int(vitrine), int(emplacement))).rowcount


# Tris proposés dans la fenêtre « Choisir une carte » d'une vitrine (clés de TRIS) ; sans tri choisi, quand on cherche du texte,
# les cartes dont le titre correspond passent d'abord, puis les plus récentes.
TRIS_SELECTEUR = ("date-desc", "date-asc", "titre-asc", "titre-desc")


def champs_recherche(prefixe):
    """Les colonnes où chercher d'après les cases de la Configuration (« COLL » : page Collection, « PROFIL » : choix d'une carte
    du profil) : titre, sous-titre (colonne description), description (colonne intro). Aucune case cochée : le titre."""
    colonnes = tuple(col for suffixe, col in (("TITRE", "titre"), ("SOUS_TITRE", "description"), ("DESCRIPTION", "intro"))
                     if getattr(config, f"RECH_{prefixe}_{suffixe}", False))
    return colonnes or ("titre",)


def cartes_a_exposer(conn, recherche="", page=1, par_page=24, rangs=None, tri=""):
    """Les cartes proposées quand on choisit une carte pour un emplacement : filtrées par TITRE, SOUS-TITRE ou
    DESCRIPTION (chaque mot de la recherche doit se trouver dans l'un des trois), avec « placee » : déjà exposée
    dans une vitrine. Les cartes dont le titre contient tous les mots passent d'abord, puis les plus récentes.
    `rangs` : ne garde que ces rangs (liste de codes). `tri` : « date-desc », « date-asc », « titre-asc » ou « titre-desc »
    (vide : pertinence). Renvoie {"cartes": [dict], "page", "pages", "total"}."""
    ordre_final = TRIS[tri][1] if tri in TRIS_SELECTEUR else "c.tire_le DESC, c.id ASC"
    where, parametres = _filtre_sql({"recherche": recherche, "champs": champs_recherche("PROFIL"), "rangs": rangs})
    ordre_titre, parametres_titre = "", []
    mots = mots_recherche(recherche)
    if tri in TRIS_SELECTEUR:                                # un tri choisi : date ou titre, sans « titre d'abord »
        mots = []
    if mots:                                                 # titre d'abord : « Paris » avant les cartes qui parlent de Paris
        ordre_titre = "CASE WHEN " + " AND ".join("norm(c.titre) LIKE ? ESCAPE '\\'" for _ in mots) + " THEN 0 ELSE 1 END, "
        parametres_titre = ["%" + m.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for m in mots]
    total = conn.execute(f"SELECT COUNT(*) FROM cartes c{where}", parametres).fetchone()[0]
    pages = max(1, -(-total // par_page))
    page = min(max(1, int(page)), pages)
    lignes = conn.execute(
        f"SELECT c.id, c.titre, c.description, c.intro, c.url_article, c.personnalisee, c.rarete, c.url_miniature, c.url_image, "
        f"EXISTS (SELECT 1 FROM vitrine_cartes v WHERE v.carte_id = c.id) AS placee "
        f"FROM cartes c{where} ORDER BY {ordre_titre}{ordre_final} LIMIT ? OFFSET ?",
        parametres + parametres_titre + [par_page, (page - 1) * par_page]).fetchall()
    return {"cartes": [dict(ligne) for ligne in lignes], "page": page, "pages": pages, "total": total}


def compter_carte_exposees(conn):
    """Nombre de cartes DIFFÉRENTES de la collection actuellement exposées dans une vitrine."""
    return conn.execute("SELECT COUNT(DISTINCT v.carte_id) FROM vitrine_cartes v "
                        "JOIN cartes c ON c.id = v.carte_id WHERE c.supprime_le IS NULL").fetchone()[0]


# ------------------------------------------------------------------------- corbeille

def compter_corbeille(conn):
    """Nombre de cartes dans la corbeille."""
    return conn.execute("SELECT COUNT(*) FROM cartes WHERE supprime_le IS NOT NULL").fetchone()[0]


def mettre_a_la_corbeille(conn, identifiants):
    """Déplace des cartes dans la corbeille (rien n'est effacé : elles peuvent être restaurées).
    Renvoie le nombre de cartes déplacées (celles déjà dans la corbeille sont ignorées)."""
    maintenant = datetime.now().astimezone().isoformat(timespec="seconds")
    deplacees = 0
    with transaction(conn):
        for identifiant in identifiants:
            deplacees += conn.execute(
                "UPDATE cartes SET supprime_le = ? WHERE id = ? AND supprime_le IS NULL",
                (maintenant, identifiant)).rowcount
    return deplacees


def restaurer_cartes(conn, identifiants=None):
    """Remet des cartes de la corbeille dans la collection (toutes si `identifiants` est None).
    Renvoie le nombre de cartes restaurées."""
    with transaction(conn):
        if identifiants is None:
            return conn.execute("UPDATE cartes SET supprime_le = NULL "
                                "WHERE supprime_le IS NOT NULL").rowcount
        return sum(conn.execute("UPDATE cartes SET supprime_le = NULL "
                                "WHERE id = ? AND supprime_le IS NOT NULL",
                                (identifiant,)).rowcount for identifiant in identifiants)


def supprimer_cartes_du_paquet(conn, identifiants):
    """Efface pour de bon des cartes qu'on vient d'ouvrir dans un paquet et qu'on ne veut pas garder (elles ne passent pas par
    la corbeille). Les cartes déjà à la corbeille ne sont pas touchées. Renvoie le nombre de cartes effacées."""
    with transaction(conn):
        return sum(conn.execute("DELETE FROM cartes WHERE id = ? AND supprime_le IS NULL", (int(i),)).rowcount
                   for i in identifiants)


def supprimer_definitivement(conn, identifiants=None):
    """Efface pour de bon des cartes DE LA CORBEILLE (toute la corbeille si `identifiants` est
    None) ; leurs liens avec les catégories disparaissent aussi. Une carte qui n'est pas dans la
    corbeille n'est jamais effacée. Renvoie le nombre de cartes effacées."""
    with transaction(conn):
        if identifiants is None:
            return conn.execute("DELETE FROM cartes WHERE supprime_le IS NOT NULL").rowcount
        return sum(conn.execute("DELETE FROM cartes WHERE id = ? AND supprime_le IS NOT NULL",
                                (identifiant,)).rowcount for identifiant in identifiants)


def lister_corbeille_page(conn, page, par_page):
    """Une page des cartes de la corbeille (les dernières supprimées d'abord), au même format
    que lister_cartes_page : cartes, page, pages, par_page, total_filtre, total."""
    par_page = max(1, int(par_page))
    total = compter_corbeille(conn)
    pages = max(1, -(-total // par_page))
    page = min(max(1, int(page)), pages)
    lignes = conn.execute(
        "SELECT * FROM cartes WHERE supprime_le IS NOT NULL "
        "ORDER BY supprime_le DESC, id DESC LIMIT ? OFFSET ?",
        (par_page, (page - 1) * par_page)).fetchall()
    return {"cartes": _avec_categories(conn, [_depuis_ligne(ligne) for ligne in lignes], False),
            "page": page, "pages": pages, "par_page": par_page,
            "total_filtre": total, "total": total}


def definir_favori(conn, identifiant, favori):
    """Marque ou démarque une carte comme favorite. Renvoie False si elle n'existe pas."""
    with transaction(conn):
        curseur = conn.execute("UPDATE cartes SET favori = ? WHERE id = ?",
                               (1 if favori else 0, int(identifiant)))
    return curseur.rowcount == 1


# ------------------------------------------------------------------------- paramètres

def lire_parametre_brut(conn, cle):
    """(valeur JSON, défaut JSON) d'un paramètre, ou None s'il n'existe pas."""
    ligne = conn.execute("SELECT valeur, defaut FROM parametres WHERE cle = ?",
                         (cle,)).fetchone()
    return (ligne["valeur"], ligne["defaut"]) if ligne else None


def ecrire_parametre_brut(conn, cle, valeur_json, defaut_json=None):
    with transaction(conn):
        conn.execute(
            "INSERT INTO parametres (cle, valeur, defaut, maj_le) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (cle) DO UPDATE SET valeur = excluded.valeur, "
            "defaut = excluded.defaut, maj_le = excluded.maj_le",
            (cle, valeur_json, defaut_json, _maintenant()))


def ecrire_parametres_bruts(conn, lignes):
    """Enregistre plusieurs paramètres d'un coup (une transaction : tout ou rien).
    `lignes` : [(clé, valeur JSON, défaut JSON ou None), ...]."""
    maintenant = _maintenant()
    with transaction(conn):
        for cle, valeur_json, defaut_json in lignes:
            conn.execute(
                "INSERT INTO parametres (cle, valeur, defaut, maj_le) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (cle) DO UPDATE SET valeur = excluded.valeur, "
                "defaut = excluded.defaut, maj_le = excluded.maj_le",
                (cle, valeur_json, defaut_json, maintenant))


def lister_parametres(conn):
    """Tous les paramètres : {cle: valeur décodée}."""
    return {ligne["cle"]: json.loads(ligne["valeur"])
            for ligne in conn.execute("SELECT cle, valeur FROM parametres ORDER BY cle")}
