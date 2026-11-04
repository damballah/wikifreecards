/* Carte agrandie (collection, profil et recherche) : une copie de la carte au milieu de l'écran.

   - Les icônes de la carte (favori, enregistrement PNG / PDF / Word, lien vers l'article) sont
     AFFICHÉES aussi sur la carte agrandie, et elles fonctionnent : un clic sur l'une d'elles déclenche
     l'action de la vraie carte (qui reste dans la page) ; leur état (favori coché, export en cours)
     est recopié sur la copie. Les icônes ne sont jamais incluses dans les images, PDF et Word exportés
     (l'export part de la vraie carte, dont il retire les boutons).
   - Un clic ailleurs, ou Échap, ferme l'aperçu ; Tab reste dans l'aperçu.
   - La zone d'agrandissement et la case de sélection ne sont pas recopiées.
   - Les animations (flottement, balancement...) et l'effet « suit la souris » viennent du CSS et de
     survol.js, comme pour toutes les cartes agrandies. */
(function () {
  "use strict";

  var ACTIONS = [".carte__favori", ".carte__sauver", ".carte__pdf", ".carte__word", ".carte__sensible"];
  var LIEN = ".carte__lien";
  var NON_RECOPIES = ".carte__zoom, .carte__selection";
  var ATTRIBUTS_SUIVIS = ["aria-pressed", "aria-label", "aria-busy", "title", "disabled"];

  var apercu = null;          /* fenêtre actuellement ouverte (ou null) */
  var declencheur = null;     /* élément qui l'a ouverte, pour lui rendre le focus */
  var observateurs = [];
  var courant = null;         /* la carte et les options de la fenêtre ouverte (pour la mettre à jour quand la carte change) */

  function retirer(element) {
    element.remove();
  }

  function selecteurDe(cible, gardes) {
    for (var i = 0; i < gardes.length; i += 1) {
      if (cible.closest(gardes[i])) {
        return gardes[i];
      }
    }
    return null;
  }

  /* `options.controles` : les icônes à garder (par défaut : toutes). */
  function ouvrir(carte, bouton, options) {
    fermer();

    var gardes = (options && options.controles) || ACTIONS.concat([LIEN]);
    var cadre = carte.closest(".carte-cadre") || carte.parentNode;
    var copie = cadre.cloneNode(true);
    copie.querySelectorAll(NON_RECOPIES).forEach(retirer);
    ACTIONS.concat([LIEN]).forEach(function (selecteur) {
      if (gardes.indexOf(selecteur) === -1) {
        copie.querySelectorAll(selecteur).forEach(retirer);
      }
    });

    var fermerBouton = document.createElement("button");
    fermerBouton.type = "button";
    fermerBouton.className = "apercu__fermer";
    fermerBouton.setAttribute("aria-label", "Fermer l'aperçu");
    fermerBouton.textContent = "\u00d7";

    apercu = document.createElement("div");
    apercu.className = "apercu";
    apercu.setAttribute("role", "dialog");
    apercu.setAttribute("aria-modal", "true");
    apercu.setAttribute("aria-label", "Aperçu de la carte : " + carte.getAttribute("data-titre"));
    apercu.appendChild(fermerBouton);
    apercu.appendChild(copie);

    /* Un clic sur une icône agit sur la vraie carte ; un clic ailleurs ferme. */
    apercu.addEventListener("click", function (evenement) {
      var cible = evenement.target;
      if (cible && cible.closest && cible.closest(".carte__pied") && carte.getAttribute("data-maj-stats") === "1" && window.WikiCartes && window.WikiCartes.demanderMajStats) {
        evenement.stopPropagation();           /* clic sur la bande du bas de la carte agrandie : mise à jour des statistiques (l'aperçu reste ouvert) */
        window.WikiCartes.demanderMajStats(carte);
        return;
      }
      var selecteur = cible && cible.closest ? selecteurDe(cible, gardes) : null;
      if (!selecteur) {
        fermer();
        return;
      }
      if (selecteur === LIEN) {
        evenement.stopPropagation();           /* le lien s'ouvre (nouvel onglet) ; l'aperçu reste */
        return;
      }
      evenement.stopPropagation();
      evenement.preventDefault();
      var original = carte.querySelector(selecteur);
      if (original && !original.disabled) {
        original.click();
      }
    });

    /* Le flou d'une carte à contenu sensible suit la vraie carte (l'icône +18 de la copie agit sur l'original). */
    if (typeof MutationObserver === "function" && carte.hasAttribute("data-flou")) {
      var flou = new MutationObserver(function () {
        var doubleCarte = copie.querySelector(".carte");
        if (doubleCarte) {
          doubleCarte.setAttribute("data-flou", carte.getAttribute("data-flou"));
        }
      });
      flou.observe(carte, { attributes: true, attributeFilter: ["data-flou"] });
      observateurs.push(flou);
    }

    /* L'état de chaque icône de la vraie carte est recopié sur la copie (favori, export en cours...). */
    if (typeof MutationObserver === "function") {
      gardes.forEach(function (selecteur) {
        var original = carte.querySelector(selecteur);
        var double = copie.querySelector(selecteur);
        if (!original || !double) {
          return;
        }
        var observateur = new MutationObserver(function () {
          ATTRIBUTS_SUIVIS.forEach(function (nom) {
            if (original.hasAttribute(nom)) {
              double.setAttribute(nom, original.getAttribute(nom));
            } else {
              double.removeAttribute(nom);
            }
          });
        });
        observateur.observe(original, { attributes: true, attributeFilter: ATTRIBUTS_SUIVIS });
        observateurs.push(observateur);
      });
    }

    declencheur = bouton || null;
    courant = { carte: carte, options: options };
    document.body.appendChild(apercu);
    document.documentElement.classList.add("apercu-ouvert");
    fermerBouton.focus();
  }

  function fermer() {
    if (!apercu) {
      return;
    }
    observateurs.forEach(function (observateur) {
      observateur.disconnect();
    });
    observateurs = [];
    apercu.remove();
    apercu = null;
    courant = null;
    document.documentElement.classList.remove("apercu-ouvert");
    if (declencheur) {
      declencheur.focus();
      declencheur = null;
    }
  }

  /* Échap ferme ; Tab fait le tour des éléments de l'aperçu (fermer, icônes) sans en sortir. */
  document.addEventListener("keydown", function (evenement) {
    if (!apercu) {
      return;
    }
    if (evenement.key === "Escape") {
      fermer();
    } else if (evenement.key === "Tab") {
      evenement.preventDefault();
      var elements = Array.prototype.slice.call(apercu.querySelectorAll("button, a[href]"));
      if (!elements.length) {
        return;
      }
      var indice = elements.indexOf(document.activeElement);
      var suivant = evenement.shiftKey ? indice - 1 : indice + 1;
      elements[(suivant + elements.length) % elements.length].focus();
    }
  });

  /* La vraie carte vient d'être remplacée (nouvelle illustration...) : si sa version agrandie est ouverte, elle est refaite à partir de la nouvelle
     carte, sans la fermer aux yeux de l'utilisateur. */
  function actualiser(identifiant, nouvelleCarte) {
    if (!apercu || !courant || !nouvelleCarte || String(courant.carte.getAttribute("data-id")) !== String(identifiant)) {
      return false;
    }
    var options = courant.options;
    var bouton = declencheur;
    ouvrir(nouvelleCarte, null, options);
    declencheur = bouton && document.body.contains(bouton) ? bouton : null;
    return true;
  }

  window.WikiApercu = { ouvrir: ouvrir, fermer: fermer, actualiser: actualiser, estOuvert: function () { return !!apercu; } };
})();
