/* Page « Corbeille » : les cartes mises à la corbeille, avec une case à cocher chacune.
   On peut en restaurer (elles retournent dans la collection), en supprimer définitivement
   (confirmation par un 2e clic) ou les laisser dans la corbeille. */
(function () {
  /* Joue le son d'un événement (réglé dans Configuration → Sons et musique) ; sans effet si aucun son n'est choisi. */
  function jouerSon(evenement) {
    try {
      if (typeof window !== "undefined" && window.WikiSons) {
        window.WikiSons.jouer(evenement);
      }
    } catch (erreur) { /* un son qui ne joue pas ne doit jamais gêner */ }
  }

  "use strict";

  var DELAI_CONFIRMATION = 4000;
  var grille = document.getElementById("corbeille-grille");
  var compte = document.getElementById("corbeille-compte");
  var boutonTout = document.getElementById("corbeille-tout");
  var boutonRestaurer = document.getElementById("corbeille-restaurer-selection");
  var boutonSupprimer = document.getElementById("corbeille-supprimer-selection");
  var etat = document.getElementById("corbeille-page-etat");
  var contenu = document.getElementById("corbeille-contenu");
  var vide = document.getElementById("corbeille-page-vide");
  var intro = document.getElementById("corbeille-page-intro");
  var occupe = false;
  var minuteurConfirmation = null;

  function pluriel(n, mot) {
    return n + " " + mot + (n > 1 ? "s" : "");
  }

  function afficherEtat(texte, erreur) {
    if (etat) {
      etat.textContent = texte;
      etat.className = "recherche__etat" + (erreur ? " recherche__etat--erreur" : "");
    }
  }

  function cartes() {
    return grille ? Array.prototype.slice.call(grille.querySelectorAll(".carte")) : [];
  }

  function caseDe(carte) {
    return carte.querySelector(".carte__case");
  }

  function cochees() {
    return cartes().filter(function (carte) {
      var casee = caseDe(carte);
      return !!casee && casee.checked;
    });
  }

  function annulerConfirmation() {
    if (minuteurConfirmation !== null) {
      clearTimeout(minuteurConfirmation);
      minuteurConfirmation = null;
    }
    if (boutonSupprimer) {
      boutonSupprimer.classList.remove("corbeille__supprimer--confirme");
    }
  }

  /* Textes et état des boutons selon les cartes cochées */
  function majSelection() {
    var toutes = cartes();
    var choisies = cochees();
    var n = choisies.length;
    if (compte) {
      compte.textContent =
        n === 0 ? "Aucune carte sélectionnée"
                : pluriel(n, "carte") + (n > 1 ? " sélectionnées" : " sélectionnée") + " sur " + toutes.length;
    }
    if (boutonTout) {
      boutonTout.textContent = toutes.length > 0 && n === toutes.length ? "Tout désélectionner" : "Tout sélectionner";
      boutonTout.disabled = toutes.length === 0;
    }
    if (boutonRestaurer) {
      boutonRestaurer.disabled = n === 0 || occupe;
      boutonRestaurer.textContent = n === 0 ? "Restaurer la sélection" : "Restaurer la sélection (" + n + ")";
    }
    if (boutonSupprimer) {
      boutonSupprimer.disabled = n === 0 || occupe;
      if (minuteurConfirmation === null) {
        boutonSupprimer.textContent =
          n === 0 ? "Supprimer définitivement la sélection" : "Supprimer définitivement la sélection (" + n + ")";
      } else {
        boutonSupprimer.textContent = "Confirmer : supprimer définitivement " + pluriel(n, "carte") + " ?";
      }
    }
    toutes.forEach(function (carte) {
      var casee = caseDe(carte);
      carte.classList.toggle("carte--selectionnee", !!casee && casee.checked);
    });
  }

  function basculerTout() {
    var toutes = cartes();
    var cocher = cochees().length !== toutes.length;
    toutes.forEach(function (carte) {
      var casee = caseDe(carte);
      if (casee) {
        casee.checked = cocher;
      }
    });
    annulerConfirmation();
    majSelection();
  }

  function demander(url, corps) {
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Jeton": document.body.getAttribute("data-jeton")
      },
      body: JSON.stringify(corps)
    })
      .catch(function () {
        throw new Error("le serveur local est injoignable (lance python main.py)");
      })
      .then(function (reponse) {
        return reponse.json().then(function (donnees) {
          if (!reponse.ok) {
            throw new Error(donnees.erreur || "erreur du serveur");
          }
          return donnees;
        });
      });
  }

  /* Retire les cartes traitées de la page, met à jour le compteur et affiche le message. */
  function appliquer(traitees, donnees, message) {
    traitees.forEach(function (carte) {
      var cadre = carte.parentNode;
      if (cadre && cadre.remove) {
        cadre.remove();
      }
    });
    if (window.WikiCorbeille) {
      window.WikiCorbeille.definir(donnees.corbeille);
    }
    afficherEtat(message, false);
    if (intro) {
      intro.textContent = (donnees.corbeille === 0 ? "La corbeille est vide." :
        pluriel(donnees.corbeille, "carte") + " dans la corbeille.") +
        " Coche des cartes pour les restaurer ou les supprimer définitivement ; les autres restent dans la corbeille.";
    }
    if (cartes().length === 0) {
      if (donnees.corbeille > 0) {
        setTimeout(function () { window.location.reload(); }, 700);   /* la page suivante prend le relais */
      } else {
        if (contenu) { contenu.hidden = true; }
        if (vide) { vide.hidden = false; }
      }
    }
  }

  function agir(url, ids, traitees, message) {
    occupe = true;
    majSelection();
    return demander(url, { ids: ids })
      .then(function (donnees) {
        occupe = false;
        appliquer(traitees, donnees, message(donnees));
      })
      .catch(function (erreur) {
        afficherEtat("Action impossible : " + erreur.message, true);
      })
      .then(function () {
        occupe = false;
        majSelection();
      });
  }

  function identifiants(liste) {
    return liste.map(function (carte) {
      return Number(carte.getAttribute("data-id"));
    }).filter(function (id) {
      return id > 0;
    });
  }

  function restaurerSelection() {
    var choisies = cochees();
    if (occupe || choisies.length === 0) {
      return Promise.resolve();
    }
    annulerConfirmation();
    return agir("/api/corbeille/restaurer", identifiants(choisies), choisies, function (donnees) {
      jouerSon("restauration");
      return pluriel(donnees.restaurees, "carte") + (donnees.restaurees > 1 ? " restaurées" : " restaurée") +
        " dans ta collection.";
    });
  }

  /* 1er clic : demande de confirmation ; 2e clic (dans les 4 secondes) : suppression définitive. */
  function supprimerSelection() {
    var choisies = cochees();
    if (occupe || choisies.length === 0) {
      return Promise.resolve();
    }
    if (minuteurConfirmation === null) {
      boutonSupprimer.classList.add("corbeille__supprimer--confirme");
      minuteurConfirmation = setTimeout(function () {
        minuteurConfirmation = null;
        annulerConfirmation();
        majSelection();
      }, DELAI_CONFIRMATION);
      majSelection();
      return Promise.resolve();
    }
    annulerConfirmation();
    return agir("/api/corbeille/supprimer", identifiants(choisies), choisies, function (donnees) {
      jouerSon("suppression");
      return pluriel(donnees.supprimees, "carte") + (donnees.supprimees > 1 ? " supprimées" : " supprimée") +
        " définitivement.";
    });
  }

  if (boutonTout) {
    boutonTout.addEventListener("click", basculerTout);
  }
  if (boutonRestaurer) {
    boutonRestaurer.addEventListener("click", restaurerSelection);
  }
  if (boutonSupprimer) {
    boutonSupprimer.addEventListener("click", supprimerSelection);
  }
  if (grille) {
    grille.addEventListener("click", function (evenement) {
      var cible = evenement.target;
      if (!cible || !cible.closest) {
        return;
      }
      var carte = cible.closest(".carte");
      if (!carte || cible.closest("a, label, input")) {
        return;
      }
      var casee = caseDe(carte);
      if (casee) {
        casee.checked = !casee.checked;
        annulerConfirmation();
        majSelection();
      }
    });
    grille.addEventListener("change", function (evenement) {
      if (evenement.target && evenement.target.classList &&
          evenement.target.classList.contains("carte__case")) {
        annulerConfirmation();
        majSelection();
      }
    });
  }
  majSelection();

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { majSelection: majSelection, basculerTout: basculerTout,
      restaurerSelection: restaurerSelection, supprimerSelection: supprimerSelection };
  }
})();
