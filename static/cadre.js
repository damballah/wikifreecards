/* Le « lecteur » : la fenêtre du haut qui affiche chaque page du programme dans un cadre. La musique d'ambiance joue dans cette
   fenêtre (voir sons.js) : elle n'est donc jamais interrompue quand on change de page. Ce script garde l'adresse et le titre de
   la fenêtre à jour, envoie les liens externes dans un nouvel onglet et transmet le premier geste de l'utilisateur à la musique. */
(function () {
  "use strict";

  var cadre = document.getElementById("cadre");
  if (!cadre) {
    return;
  }

  function suivre() {
    var fenetre, doc, lieu;
    try {
      fenetre = cadre.contentWindow;
      doc = fenetre.document;
      lieu = fenetre.location;
    } catch (erreur) {
      return;                                          /* page d'un autre site : on ne touche à rien */
    }
    if (!lieu || lieu.origin !== window.location.origin) {
      return;
    }
    try {
      history.replaceState(null, "", lieu.pathname + lieu.search + lieu.hash);       /* l'adresse affichée suit la page */
    } catch (erreur) { /* sans importance */ }
    document.title = doc.title || document.title;
    doc.addEventListener("click", function (evenement) {
      var lien = evenement.target && evenement.target.closest ? evenement.target.closest("a[href]") : null;
      if (lien && !lien.target && /^https?:/i.test(lien.href) && lien.href.indexOf(window.location.origin) !== 0) {
        lien.target = "_blank";                        /* un site extérieur ne s'ouvre jamais dans le cadre */
        lien.rel = "noopener noreferrer";
      }
    }, true);
    ["pointerdown", "keydown", "touchstart"].forEach(function (nom) {
      doc.addEventListener(nom, function () {
        if (window.WikiSons && window.WikiSons.geste) {
          window.WikiSons.geste();                     /* le premier clic dans la page lance la musique en attente */
        }
      }, true);
    });
    if (window.WikiSons && window.WikiSons.placer) {
      window.WikiSons.placer(doc);                     /* le haut-parleur se pose au-dessus de la barre de la Configuration */
    }
    var titre = doc.querySelector("title");
    if (titre && window.MutationObserver) {
      new MutationObserver(function () {
        document.title = doc.title || document.title;
      }).observe(titre, { childList: true });
    }
  }

  cadre.addEventListener("load", suivre);
  setInterval(function () {                            /* (la barre apparaît ou disparaît avec la page : on suit) */
    try {
      if (window.WikiSons && window.WikiSons.placer) {
        window.WikiSons.placer(cadre.contentDocument);
      }
    } catch (erreur) { /* sans importance */ }
  }, 1000);
  window.addEventListener("focus", function () {
    try { cadre.contentWindow.focus(); } catch (erreur) { /* sans importance */ }
  });
})();
