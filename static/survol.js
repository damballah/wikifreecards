/* Effet « Suit la souris (3D) » : la carte pivote vers le pointeur. Deux endroits :
   - au survol d'une carte de la page, quand <html data-survol="tilt"> ;
   - sur la carte AGRANDIE (clic), quand <html data-anim-zoom="tilt"> : elle se tourne doucement
     vers le pointeur, d'après sa position dans la fenêtre.
   Les autres effets sont purement CSS (voir cartes.css). Ce script n'agit qu'avec une vraie souris
   et sans préférence « mouvement réduit ». Les angles sont donnés par deux variables CSS (--rx, --ry). */
(function () {
  "use strict";

  var ANGLE_MAX = 18;                         /* degrés d'inclinaison aux bords de la carte */
  var ANGLE_ZOOM = 9;                         /* plus doux sur la carte agrandie (elle se lit) */
  var racine = document.documentElement;
  var trame = 0;

  function actif() {
    return (
      racine.getAttribute("data-survol") === "tilt" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(hover: hover)").matches &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function souris() {
    return (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(hover: hover)").matches &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  /* Carte agrandie : l'inclinaison dépend de la position du pointeur dans la fenêtre. */
  function inclinerZoom(carte, x, y) {
    var px = (x / (window.innerWidth || 1) - 0.5) * 2;
    var py = (y / (window.innerHeight || 1) - 0.5) * 2;
    carte.style.setProperty("--ry", (px * ANGLE_ZOOM).toFixed(1) + "deg");
    carte.style.setProperty("--rx", (-py * ANGLE_ZOOM).toFixed(1) + "deg");
  }

  function carteSous(cible) {
    return cible && cible.closest ? cible.closest(".carte") : null;
  }

  function incliner(carte, x, y) {
    var zone = carte.getBoundingClientRect();
    if (!zone.width || !zone.height) {
      return;
    }
    var px = (x - zone.left) / zone.width - 0.5;
    var py = (y - zone.top) / zone.height - 0.5;
    carte.style.setProperty("--ry", (px * ANGLE_MAX).toFixed(1) + "deg");
    carte.style.setProperty("--rx", (-py * ANGLE_MAX).toFixed(1) + "deg");
  }

  function redresser(carte) {
    carte.style.removeProperty("--rx");
    carte.style.removeProperty("--ry");
  }

  document.addEventListener("pointermove", function (evenement) {
    var carteZoom = document.querySelector(".apercu .carte");
    if (carteZoom) {                          /* une carte est agrandie : seul son effet compte */
      if (racine.getAttribute("data-anim-zoom") === "tilt" && souris() && !trame) {
        var zx = evenement.clientX;
        var zy = evenement.clientY;
        trame = window.requestAnimationFrame(function () {
          trame = 0;
          inclinerZoom(carteZoom, zx, zy);
        });
      }
      return;
    }
    if (!actif()) {
      return;
    }
    var carte = carteSous(evenement.target);
    if (!carte || trame) {
      return;
    }
    var x = evenement.clientX;
    var y = evenement.clientY;
    trame = window.requestAnimationFrame(function () {   /* au plus une mise à jour par image */
      trame = 0;
      incliner(carte, x, y);
    });
  }, { passive: true });

  document.addEventListener("pointerout", function (evenement) {
    var carte = carteSous(evenement.target);
    if (carte && !(evenement.relatedTarget && carte.contains(evenement.relatedTarget))) {
      redresser(carte);                                    /* le pointeur quitte la carte */
    }
  }, { passive: true });

  /* Paquet à ouvrir, effet « Suit la souris (3D) » (réglage « Paquet : effet au passage de la souris ») : le paquet se tourne
     vers le pointeur tant qu'il n'est pas en train de s'ouvrir. */
  var ANGLE_PAQUET = 16;

  function corpsDuPaquet(cible) {
    var paquet = cible && cible.closest ? cible.closest(".paquet") : null;
    if (!paquet || /paquet--(attente|sortie|cache|retour)/.test(paquet.className)) {
      return null;
    }
    var corps = paquet.querySelectorAll(".paquet__corps");
    for (var i = 0; i < corps.length; i++) {
      if (!corps[i].hidden) {
        return corps[i];
      }
    }
    return null;
  }

  document.addEventListener("pointermove", function (evenement) {
    if (racine.getAttribute("data-paquet-survol") !== "tilt" || !souris()) {
      return;
    }
    var corps = corpsDuPaquet(evenement.target);
    if (!corps) {
      return;
    }
    var zone = corps.getBoundingClientRect();
    if (!zone.width || !zone.height) {
      return;
    }
    corps.style.setProperty("--ry", (((evenement.clientX - zone.left) / zone.width - 0.5) * ANGLE_PAQUET).toFixed(1) + "deg");
    corps.style.setProperty("--rx", (-((evenement.clientY - zone.top) / zone.height - 0.5) * ANGLE_PAQUET).toFixed(1) + "deg");
  }, { passive: true });

  document.addEventListener("pointerout", function (evenement) {
    var paquet = evenement.target && evenement.target.closest ? evenement.target.closest(".paquet") : null;
    if (paquet && !(evenement.relatedTarget && paquet.contains(evenement.relatedTarget))) {
      Array.prototype.forEach.call(paquet.querySelectorAll(".paquet__corps"), function (corps) {
        corps.style.removeProperty("--rx");
        corps.style.removeProperty("--ry");
      });
    }
  }, { passive: true });

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { incliner: incliner, redresser: redresser, actif: actif, inclinerZoom: inclinerZoom };
  }
})();
