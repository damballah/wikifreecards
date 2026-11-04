/* Les rangs des cartes quand les SEUILS de rareté changent (page Configuration ; voir wikicartes/raretes.py).
   - confirmer(donnees) : la fenêtre de confirmation, avec ce qui change et ce que ça fait aux cartes. Renvoie une promesse : true (confirmé) ou false (annulé).
   - suivre() : la fenêtre de progression (barre de progression) pendant le recalcul ; renvoie une promesse résolue quand l'utilisateur ferme la fenêtre, une fois le travail fini.
   Si la page est rechargée pendant un recalcul, la fenêtre de progression revient toute seule. */
(function () {
  "use strict";

  var jeton = document.body ? document.body.getAttribute("data-jeton") : "";
  if (!jeton || (window.location.protocol !== "http:" && window.location.protocol !== "https:")) {
    return;
  }

  var fenetre = null;
  var ecouteur = null;

  function nombre(n) {
    return Number(n).toLocaleString("fr-FR");
  }

  function creer(balise, classe, texte) {
    var e = document.createElement(balise);
    if (classe) {
      e.className = classe;
    }
    if (texte !== undefined) {
      e.textContent = texte;
    }
    return e;
  }

  function bouton(texte, classe, action) {
    var b = creer("button", "bouton-site" + (classe ? " " + classe : ""), texte);
    b.type = "button";
    b.addEventListener("click", action);
    return b;
  }

  function ouvrir(titre, surEchap) {
    fermer();
    fenetre = creer("div", "raretes-fenetre");
    var boite = creer("div", "raretes-fenetre__boite");
    boite.setAttribute("role", "dialog");
    boite.setAttribute("aria-modal", "true");
    boite.setAttribute("aria-labelledby", "raretes-titre");
    var h = creer("h2", "raretes-fenetre__titre", titre);
    h.id = "raretes-titre";
    var contenu = creer("div", "raretes-fenetre__contenu");
    boite.appendChild(h);
    boite.appendChild(contenu);
    fenetre.appendChild(boite);
    document.body.appendChild(fenetre);
    document.documentElement.classList.add("raretes-ouvertes");
    ecouteur = function (evenement) {
      if (evenement.key === "Escape") {
        evenement.preventDefault();
        evenement.stopImmediatePropagation();
        if (surEchap) {
          surEchap();
        }
      }
    };
    document.addEventListener("keydown", ecouteur, true);
    return contenu;
  }

  function fermer() {
    if (ecouteur) {
      document.removeEventListener("keydown", ecouteur, true);
      ecouteur = null;
    }
    if (fenetre && fenetre.parentNode) {
      fenetre.parentNode.removeChild(fenetre);
    }
    fenetre = null;
    document.documentElement.classList.remove("raretes-ouvertes");
  }

  /* ---------------------------------------------------------------------------------------------------- la confirmation */

  function ligneChangement(c) {
    var nom = c.nom ? c.nom + (c.code ? " (" + c.code + ")" : "") : (c.code || "");
    if (c.genre === "modifie") {
      return nom + " : " + nombre(c.avant) + " → " + nombre(c.apres) + " vues par jour";
    }
    if (c.genre === "ajoute") {
      return "Nouveau rang " + nom + " : à partir de " + nombre(c.apres) + " vues par jour";
    }
    if (c.genre === "supprime") {
      return "Rang " + nom + " supprimé (il était à partir de " + nombre(c.avant) + " vues par jour)";
    }
    return "L'ordre des rangs change";
  }

  function confirmer(donnees) {
    return new Promise(function (resoudre) {
      function repondre(oui) {
        fermer();
        resoudre(oui);
      }
      var contenu = ouvrir("Les rangs vont changer", function () { repondre(false); });
      contenu.appendChild(creer("p", "raretes-fenetre__texte",
        "Un ou plusieurs rangs de rareté ont été modifiés. Pour que ta collection reste cohérente, le rang de toutes tes cartes doit être recalculé d'après leurs vues et ces nouveaux seuils : " +
        "une confirmation est nécessaire, car des cartes vont changer de rang."));
      var liste = creer("ul", "raretes-fenetre__liste");
      (donnees.changements || []).forEach(function (c) {
        liste.appendChild(creer("li", "", ligneChangement(c)));
      });
      contenu.appendChild(liste);
      var s = donnees.simulation || {};
      if (typeof s.cartes === "number") {
        var texte = s.changent > 0
          ? "Environ " + nombre(s.changent) + " carte" + (s.changent > 1 ? "s" : "") + " sur " + nombre(s.cartes) + " changeront de rang (" + nombre(s.montent) + " monteront, " + nombre(s.descendent) + " descendront)."
          : "Aucune de tes " + nombre(s.cartes) + " cartes ne changera de rang avec ces seuils.";
        contenu.appendChild(creer("p", "raretes-fenetre__texte raretes-fenetre__texte--fort", texte));
      }
      contenu.appendChild(creer("p", "raretes-fenetre__discret",
        "Les cartes créées à la main et les cartes full-art ne sont pas touchées. Rien n'est enregistré tant que tu n'as pas confirmé."));
      var actions = creer("div", "raretes-fenetre__actions");
      var annuler = bouton("Annuler (rien n'est enregistré)", "", function () { repondre(false); });
      var confirmerBouton = bouton("Confirmer et recalculer les rangs", "bouton-site--principal", function () { repondre(true); });
      actions.appendChild(annuler);
      actions.appendChild(confirmerBouton);
      contenu.appendChild(actions);
      annuler.focus();
    });
  }

  /* ---------------------------------------------------------------------------------------------------- la progression */

  function suivre() {
    return new Promise(function (resoudre) {
      var contenu = ouvrir("Mise à jour des rangs", null);
      contenu.appendChild(creer("p", "raretes-fenetre__texte", "Le rang de tes cartes est recalculé d'après leurs vues et les nouveaux seuils. Les cartes créées à la main et les full-art ne sont pas touchées."));
      var barre = creer("div", "raretes-fenetre__barre");
      barre.setAttribute("role", "progressbar");
      barre.setAttribute("aria-valuemin", "0");
      barre.setAttribute("aria-valuemax", "100");
      barre.setAttribute("aria-label", "Progression du recalcul des rangs");
      var remplissage = creer("i", "raretes-fenetre__remplissage");
      barre.appendChild(remplissage);
      var detail = creer("p", "raretes-fenetre__texte raretes-fenetre__texte--fort", "Préparation…");
      detail.setAttribute("role", "status");
      detail.setAttribute("aria-live", "polite");
      var compteurs = creer("p", "raretes-fenetre__discret", "");
      var actions = creer("div", "raretes-fenetre__actions");
      var fermerBouton = bouton("Fermer", "bouton-site--principal", function () {
        fermer();
        resoudre();
      });
      fermerBouton.disabled = true;
      actions.appendChild(fermerBouton);
      [barre, detail, compteurs, actions].forEach(function (e) { contenu.appendChild(e); });
      var echecs = 0;

      function tour() {
        fetch("/api/raretes/etat", { headers: { "X-Jeton": jeton } })
          .then(function (reponse) {
            return reponse.ok ? reponse.json() : Promise.reject(new Error("réponse " + reponse.status));
          })
          .then(function (e) {
            echecs = 0;
            var pourcent = Math.max(0, Math.min(100, e.pourcentage || 0));
            remplissage.style.width = pourcent + "%";
            barre.setAttribute("aria-valuenow", String(pourcent));
            if (!e.termine) {
              detail.textContent = e.total
                ? nombre(e.faits) + " / " + nombre(e.total) + " cartes (" + pourcent + " %)"
                : "Comptage des cartes…";
              compteurs.textContent = e.changees ? nombre(e.changees) + " carte" + (e.changees > 1 ? "s" : "") + " ont déjà changé de rang (⬆ " + nombre(e.montees) + " · ⬇ " + nombre(e.descendues) + ")" : "";
              setTimeout(tour, 250);
              return;
            }
            remplissage.style.width = "100%";
            barre.setAttribute("aria-valuenow", "100");
            if (e.erreur) {
              detail.textContent = "Le recalcul s'est arrêté : " + e.erreur;
              detail.classList.add("raretes-fenetre__texte--erreur");
              compteurs.textContent = "Les cartes déjà traitées ont leur nouveau rang. Enregistre de nouveau les réglages pour relancer le recalcul.";
            } else {
              detail.textContent = "Terminé ✓ — " + (e.changees
                ? nombre(e.changees) + " carte" + (e.changees > 1 ? "s ont" : " a") + " changé de rang sur " + nombre(e.total)
                : "aucune carte n'a changé de rang (" + nombre(e.total) + " vérifiées)");
              compteurs.textContent = (e.changees ? "⬆ " + nombre(e.montees) + " montent · ⬇ " + nombre(e.descendues) + " descendent" : "") +
                (e.reserve ? (e.changees ? " · " : "") + nombre(e.reserve) + " carte" + (e.reserve > 1 ? "s" : "") + " de la réserve mise" + (e.reserve > 1 ? "s" : "") + " à jour" : "");
            }
            fermerBouton.disabled = false;
            fermerBouton.focus();
          })
          .catch(function () {
            echecs += 1;
            if (echecs > 8) {
              detail.textContent = "Le programme ne répond plus : le recalcul continue peut-être en arrière-plan.";
              fermerBouton.disabled = false;
            } else {
              setTimeout(tour, 600);
            }
          });
      }
      tour();
    });
  }

  window.WikiRaretes = { confirmer: confirmer, suivre: suivre };

  /* Page rechargée pendant un recalcul : la fenêtre de progression revient */
  fetch("/api/raretes/etat", { headers: { "X-Jeton": jeton } })
    .then(function (reponse) { return reponse.ok ? reponse.json() : null; })
    .then(function (e) {
      if (e && e.actif && !fenetre) {
        suivre().then(function () { window.location.reload(); });
      }
    })
    .catch(function () { /* sans importance */ });
})();
