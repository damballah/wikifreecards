/* Pied des cartes : TOUJOURS sur une seule ligne : vues par jour à gauche, statistiques au milieu,
   date et heure à droite. Jamais de seconde ligne.

   Si tout ne tient pas à la largeur de la carte (police large, carte étroite), le pied se COMPACTE par
   étapes, dans cet ordre, jusqu'à ce que ça tienne :
     1. le « /jour » après les vues disparaît ;      2. l'horloge devant l'heure disparaît ;
     3. les statistiques se resserrent ;              4. la date (jour/mois) disparaît, l'heure reste ;
     5. en tout dernier recours, les statistiques sont masquées.
   Les statistiques sont exactement au centre de la carte quand les deux côtés sont assez étroits ;
   sinon elles se placent au milieu de la place restante entre les vues et la date (classe « --libre »).

   La mesure se fait séparément pour chaque contexte : les cartes de la page (même niveau pour toutes,
   donc des pieds tous construits de la même façon), la carte agrandie (sa propre taille) et la copie
   fabriquée pour l'export (à la taille de l'image exportée, mesurée hors écran). Elle se refait quand des
   cartes apparaissent, quand leur taille change (curseur, fenêtre) et quand les polices sont chargées. */
(function () {
  "use strict";

  var NIVEAU_MAX = 5;
  var CLASSE_LIBRE = "carte__pied--libre";
  var trame = 0;

  function classeNiveau(n) {
    return "carte__pied--n" + n;
  }

  function reinitialiser(pied) {
    pied.classList.remove(CLASSE_LIBRE);
    for (var n = 1; n <= NIVEAU_MAX; n += 1) {
      pied.classList.remove(classeNiveau(n));
    }
  }

  function appliquerNiveau(pieds, niveau) {
    pieds.forEach(function (pied) {
      for (var n = 1; n <= NIVEAU_MAX; n += 1) {
        if (n <= niveau) {
          pied.classList.add(classeNiveau(n));
        } else {
          pied.classList.remove(classeNiveau(n));
        }
      }
    });
  }

  function tient(pied) {
    return !(pied.clientWidth > 0 && pied.scrollWidth > pied.clientWidth + 1);
  }

  /* Ajuste un groupe de pieds (même contexte, même taille de carte) : un seul niveau pour tout le groupe. */
  function ajusterGroupe(pieds) {
    pieds = pieds.filter(function (pied) {
      return !pied.classList.contains("carte__pied--perso") &&   /* cartes personnalisées : surnom et date */
        !pied.classList.contains("carte__pied--vues");           /* résultats de recherche : les vues seulement */
    });
    if (!pieds.length) {
      return 0;
    }
    pieds.forEach(reinitialiser);
    /* 1. On cherche le premier niveau où tout tient sur une ligne, avec la disposition « libre » (la plus
       économe : les côtés n'ont pas besoin d'avoir la même largeur). */
    var niveau = 0;
    for (; niveau <= NIVEAU_MAX; niveau += 1) {
      appliquerNiveau(pieds, niveau);
      pieds.forEach(function (pied) {
        pied.classList.add(CLASSE_LIBRE);
      });
      if (pieds.every(tient)) {
        break;
      }
    }
    niveau = Math.min(niveau, NIVEAU_MAX);
    appliquerNiveau(pieds, niveau);
    /* 2. À ce niveau, chaque pied reprend si possible la disposition centrée (statistiques exactement au
       milieu de la carte). */
    pieds.forEach(function (pied) {
      pied.classList.remove(CLASSE_LIBRE);
      if (!tient(pied)) {
        pied.classList.add(CLASSE_LIBRE);
      }
    });
    return niveau;
  }

  function tousLesPieds() {
    return Array.prototype.slice.call(document.querySelectorAll(".carte__pied"));
  }

  function ajuster() {
    var pieds = tousLesPieds();
    var dansApercu = [];
    var page = [];
    pieds.forEach(function (pied) {
      (pied.closest && pied.closest(".apercu") ? dansApercu : page).push(pied);
    });
    ajusterGroupe(page);
    ajusterGroupe(dansApercu);          /* la carte agrandie a sa propre taille, donc son propre niveau */
  }

  /* Copie fabriquée pour l'export : on la monte un instant hors de l'écran, à sa taille, pour mesurer ses pieds. */
  function ajusterCopie(copie) {
    var pieds = Array.prototype.slice.call(copie.querySelectorAll(".carte__pied"));
    pieds.forEach(reinitialiser);
    if (!pieds.length || !document.body || !document.createElement) {
      return 0;
    }
    var support = document.createElement("div");
    support.setAttribute("data-mesure", "1");                /* repère : cette copie n'est pas une carte de la page */
    support.setAttribute("style", "position:fixed;left:-20000px;top:0;visibility:hidden;pointer-events:none");
    support.appendChild(copie);
    document.body.appendChild(support);
    var niveau = 0;
    try {
      niveau = ajusterGroupe(pieds);
    } finally {
      support.removeChild(copie);
      document.body.removeChild(support);
    }
    return niveau;
  }

  function planifier() {
    if (trame || typeof window.requestAnimationFrame !== "function") {
      return;
    }
    trame = window.requestAnimationFrame(function () {   /* une seule mesure par image */
      trame = 0;
      ajuster();
    });
  }

  var observateurTaille = typeof ResizeObserver === "function" ? new ResizeObserver(planifier) : null;

  function observer(racine) {
    if (!observateurTaille || !racine.querySelectorAll) {
      return;
    }
    var cartes = racine.matches && racine.matches(".carte") ? [racine] : [];
    cartes = cartes.concat(Array.prototype.slice.call(racine.querySelectorAll(".carte")));
    cartes.forEach(function (carte) {
      observateurTaille.observe(carte);
    });
  }

  if (typeof MutationObserver === "function" && document.body) {
    new MutationObserver(function (mutations) {
      var nouvelles = false;
      mutations.forEach(function (mutation) {
        Array.prototype.forEach.call(mutation.addedNodes, function (noeud) {
          if (noeud.nodeType === 1 && noeud.hasAttribute && noeud.hasAttribute("data-mesure")) {
            return;                                  /* copie montée un instant pour mesurer un export */
          }
          if (noeud.nodeType === 1 && (noeud.matches(".carte") || noeud.querySelector(".carte"))) {
            nouvelles = true;
            observer(noeud);
          }
        });
      });
      if (nouvelles) {
        planifier();
      }
    }).observe(document.body, { childList: true, subtree: true });
  }

  window.addEventListener("resize", planifier);
  window.addEventListener("load", planifier);
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(planifier);
  }
  if (document.fonts && document.fonts.addEventListener) {
    document.fonts.addEventListener("loadingdone", planifier);     /* une police chargée plus tard change les largeurs */
  }
  if (document.body) {
    observer(document.body);
  }
  planifier();

  window.WikiPied = { ajuster: ajuster, ajusterGroupe: ajusterGroupe, ajusterCopie: ajusterCopie,
    NIVEAU_MAX: NIVEAU_MAX };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { ajuster: ajuster, ajusterGroupe: ajusterGroupe, ajusterCopie: ajusterCopie,
      NIVEAU_MAX: NIVEAU_MAX, CLASSE_LIBRE: CLASSE_LIBRE };
  }
})();
