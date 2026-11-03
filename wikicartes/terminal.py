"""Affichage dans le terminal (les cartes se tirent maintenant depuis la page web)."""

from collections import Counter

from . import config


def afficher(articles):
    for i, art in enumerate(articles, start=1):
        print(f"\n--- Article {i} ---")
        print(f"Titre       : {art['titre']}")
        print(f"Tiré le     : {art['tire_le']:%d/%m/%Y à %H:%M:%S}")
        rarete = f"{art['rarete']} ({art['rarete_nom']})"
        if art["rarete_tiree"] != art["rarete"]:
            rarete += f"  [rang tiré : {art['rarete_tiree']}]"
        print(f"Rareté      : {rarete}")
        print(f"Vues        : {art['vues_moyenne']:.0f}/jour en moyenne "
              f"({art['vues_total']} sur {config.JOURS_VUES} jours)")
        print(f"Description : {art['description']}")
        print(f"Intro       : {art['intro']}")
        print(f"Image       : {art['image']}")
        print(f"Lien        : {art['url']}")


def afficher_resume(articles):
    compte = Counter(art["rarete"] for art in articles)
    resume = ", ".join(f"{compte[c]} {config.symbole(c)}" for c in config.CODES if compte[c])
    print(f"\nRésumé du tirage : {resume}")
