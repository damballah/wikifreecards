/* Cartes à contenu sensible, sur TOUTES les pages (collection, recherche, profil, collections visitées, corbeille) :
   l'icône +18 d'une carte montre l'image floutée, ou la floute de nouveau (le flou est le réglage par défaut). */
(function () {
  "use strict";

  /* Garde sur le serveur l'état « image montrée » de la carte (clé : l'adresse de son article), pour qu'il survive à la fermeture
     du programme. Sans effet pour une carte sans adresse d'article ou hors serveur. */
  function garderEtat(carte, montree) {
    var lien = carte.querySelector(".carte__lien");
    var jeton = document.body ? document.body.getAttribute("data-jeton") : null;
    var adresse = lien ? lien.getAttribute("href") : "";
    if (!jeton || !adresse || !/^https?:/i.test(adresse) || typeof fetch !== "function") {
      return;
    }
    try {
      fetch("/api/flou", {
        method: "POST", keepalive: true,
        headers: { "Content-Type": "application/json", "X-Jeton": jeton },
        body: JSON.stringify({ url: adresse, revele: !!montree })
      }).catch(function () { /* sans importance : l'état reste valable pour cette page */ });
    } catch (erreur) { /* sans importance */ }
  }

  document.addEventListener("click", function (evenement) {
    var cible = evenement.target;
    var bouton = cible && cible.closest ? cible.closest(".carte__sensible") : null;
    if (!bouton || bouton.closest(".apercu")) {
      return;                                       /* (dans la carte agrandie, l'aperçu relaie le clic vers la vraie carte) */
    }
    evenement.preventDefault();
    evenement.stopPropagation();
    var carte = bouton.closest(".carte");
    if (!carte) {
      return;
    }
    var floue = carte.getAttribute("data-flou") === "1";
    carte.setAttribute("data-flou", floue ? "0" : "1");
    garderEtat(carte, floue);                       /* l'état est gardé : au prochain lancement, l'image reste montrée (ou floutée) */
    bouton.setAttribute("aria-pressed", floue ? "true" : "false");
    bouton.setAttribute("aria-label", floue ? "Flouter de nouveau l'image" : "Montrer l'image (contenu sensible)");
  }, true);
})();
