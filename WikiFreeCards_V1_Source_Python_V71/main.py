"""Point d'entrée : lance le site en local.

Tout se fait ensuite depuis la page web : ouvrir des paquets de cartes, parcourir ta
collection, régler la configuration, exporter les cartes. Les cartes et les réglages sont
enregistrés dans la base de données locale et retrouvés à chaque lancement.

Utilisation : python main.py        (Ctrl+C pour arrêter le serveur local)
"""

import secrets
import webbrowser

from wikicartes import base, config, export, favicon, parametres, rendu, serveur


def main():
    export.preparer_dossiers()      # Export/ (sous-dossiers L, UR, SR, R, PC, C) et logo/
    logo = export.trouver_logo()
    if logo:
        print(f"Logo : {logo.parent.name}/{logo.name} (en-tête, booster et verso des cartes)")
    else:
        print("Pas de logo : dépose une image nommée « logo » (logo.png, logo.jpg...) dans le "
              "dossier logo/ (ou choisis un autre fichier dans la page Configuration).")

    print(favicon.diagnostic())

    try:
        with base.connexion() as conn:
            repris = parametres.synchroniser(conn)      # paramètres : config.py + base
            sauvegarde = base.sauvegarder(conn)         # copie de sécurité du jour
            total = base.compter(conn)
    except base.BaseTropRecente as erreur:
        print(f"Impossible d'ouvrir la base de données : {erreur}")
        return

    print(f"Base de données : {config.FICHIER_BASE}")
    print(f"Collection : {total} carte{'s' if total > 1 else ''}.")
    if repris:
        print("Réglages repris de la base : " + ", ".join(repris))
    if sauvegarde:
        print(f"Sauvegarde automatique : {sauvegarde.name}")

    jeton = secrets.token_urlsafe(16)   # code secret partagé entre la page et le serveur
    page = rendu.ecrire_page_collection(jeton)

    if config.SERVEUR_LOCAL:
        serveur.servir(jeton)           # bloque jusqu'à Ctrl+C
    else:
        print(f"\nServeur local désactivé : page de la collection (lecture seule) : {page}")
        print("Pour ouvrir des paquets et changer la configuration, mets SERVEUR_LOCAL = True "
              "dans config.py.")
        if config.OUVRIR_NAVIGATEUR:
            webbrowser.open(page.as_uri())


if __name__ == "__main__":
    main()
