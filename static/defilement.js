/* Quand on change de page avec les boutons de pagination (numéros, « Suivant », « Précédent »), la nouvelle page s'affiche TOUJOURS depuis son début :
   que le clic vienne de la pagination du HAUT ou de celle du BAS de la liste, on se retrouve en haut.
   - Pages qui se rechargent (collection, corbeille) : le lien charge la page suivante, qui s'ouvre en haut ; on le garantit même si le navigateur
     voulait restaurer l'ancienne position.
   - Pages qui changent leur contenu sans se recharger (visite d'une collection du Hall, recherche) : WikiDefilement.versLeHaut(debut, changer)
     change le contenu puis ramène l'écran au début de la liste. */
(function () {
  "use strict";

  var CLE = "wikicartes.defilement";

  function sansAnimation() {
    return !window.matchMedia || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  /* Ramène l'écran au début de la liste : le haut de l'élément `debut` (la barre de pagination du haut, par exemple), ou le haut de la page. */
  function enHaut(debut) {
    if (debut && debut.scrollIntoView) {
      debut.scrollIntoView({ block: "start", behavior: sansAnimation() ? "auto" : "smooth" });
    } else {
      window.scrollTo(0, 0);
    }
  }

  /* Exécute `changer` (qui renvoie une promesse ou rien) puis ramène l'écran au début de la liste. */
  function versLeHaut(debut, changer) {
    return Promise.resolve(changer()).then(function () {
      enHaut(debut);
    });
  }

  /* Pagination « classique » : un lien recharge la page. On note le clic (haut ou bas) pour repartir d'en haut à l'arrivée. */
  document.addEventListener("click", function (evenement) {
    var lien = evenement.target && evenement.target.closest ? evenement.target.closest("nav.pagination a.pagination__lien") : null;
    if (!lien) {
      return;
    }
    try {
      sessionStorage.setItem(CLE, JSON.stringify({ chemin: window.location.pathname, ts: Date.now() }));
    } catch (erreur) { /* stockage indisponible : la page s'ouvre en haut de toute façon */ }
  }, true);

  function restaurer() {
    var etat;
    try {
      etat = JSON.parse(sessionStorage.getItem(CLE) || "null");
      sessionStorage.removeItem(CLE);
    } catch (erreur) {
      return;
    }
    if (!etat || etat.chemin !== window.location.pathname || Date.now() - etat.ts > 15000) {
      return;
    }
    if ("scrollRestoration" in history) {
      history.scrollRestoration = "manual";
    }
    window.scrollTo(0, 0);                              /* la page suivante ou précédente commence en haut */
  }

  window.WikiDefilement = { versLeHaut: versLeHaut, enHaut: enHaut, garder: function (zone, changer) { return versLeHaut(null, changer); } };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", restaurer);
  } else {
    restaurer();
  }
})();
