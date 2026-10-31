/* Menu en colonne à gauche avec le logo AU-DESSUS : le menu se place sous le logo, quelle que soit la hauteur du logo (réglage
   « hauteur du logo », image plus ou moins haute). On mesure le logo et on règle --menu-haut ; sans cette mesure, le menu reste à
   sa place d'origine (96 px). Refait quand l'image est chargée, quand la fenêtre change et quand les réglages de disposition changent. */
(function () {
  "use strict";

  var racine = document.documentElement;
  var ECART = 14;

  function ajuster() {
    var logo = document.querySelector(".entete__logo");
    var actif = logo && racine.getAttribute("data-logo-align") === "menu" && racine.getAttribute("data-menu-pos") === "lateral" &&
      window.innerWidth >= 1100;
    if (!actif) {
      racine.style.removeProperty("--menu-haut");
      return;
    }
    var bas = logo.getBoundingClientRect().bottom;
    racine.style.setProperty("--menu-haut", Math.max(96, Math.ceil(bas + ECART)) + "px");
  }

  function surveiller() {
    var logo = document.querySelector(".entete__logo");
    ajuster();
    if (!logo) {
      return;
    }
    var image = logo.querySelector("img");
    if (image && !image.complete) {
      image.addEventListener("load", ajuster);
    }
    if (typeof ResizeObserver === "function") {
      new ResizeObserver(ajuster).observe(logo);
    }
  }

  window.addEventListener("resize", ajuster);
  window.addEventListener("load", ajuster);
  if (typeof MutationObserver === "function") {
    new MutationObserver(ajuster).observe(racine, { attributes: true, attributeFilter: ["data-logo-align", "data-menu-pos", "data-menu"] });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", surveiller);
  } else {
    surveiller();
  }
})();
