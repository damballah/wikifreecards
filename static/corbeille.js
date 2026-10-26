/* Icône « corbeille » en haut à droite de chaque page, et sa petite fenêtre d'information.

   - grise avec « (0) » quand la corbeille est vide, rouge avec « (N) » sinon ;
   - un clic ouvre la fenêtre : contenu de la corbeille, « Restaurer tout », lien vers la page
     de la corbeille et, s'il y a des cartes, le bouton rouge « Supprimer définitivement » ;
   - « Supprimer définitivement » demande une confirmation (un 2e clic dans les 4 secondes), puis
     une courte animation et le message « La corbeille est vide ! » confirment le vidage ;
   - window.WikiCorbeille.definir(n) met à jour l'icône (utilisé par les autres scripts). */
(function () {
  /* La page se recharge après une restauration : si un son de restauration est choisi, on lui laisse le temps de se jouer. */
  function delaiRechargement() {
    try {
      var r = window.WikiSons && window.WikiSons.reglages();
      return r && r.actifs && r.evenements && r.evenements.restauration ? 2500 : 700;
    } catch (erreur) {
      return 700;
    }
  }

  /* Joue le son d'un événement (réglé dans Configuration → Sons et musique) ; sans effet si aucun son n'est choisi. */
  function jouerSon(evenement) {
    try {
      if (typeof window !== "undefined" && window.WikiSons) {
        window.WikiSons.jouer(evenement);
      }
    } catch (erreur) { /* un son qui ne joue pas ne doit jamais gêner */ }
  }

  "use strict";

  var DELAI_CONFIRMATION = 4000;    /* ms pour confirmer la suppression définitive */
  var DUREE_SUCCES = 2200;          /* ms d'affichage du message « corbeille vide » */

  var zone = document.getElementById("corbeille-zone");
  if (!zone) {
    window.WikiCorbeille = { definir: function () {}, nombre: function () { return 0; } };
    return;
  }
  var bouton = document.getElementById("corbeille-bouton");
  var nombreEl = document.getElementById("corbeille-nombre");
  var info = document.getElementById("corbeille-info");
  var etatEl = document.getElementById("corbeille-etat");
  var actions = document.getElementById("corbeille-actions");
  var boutonVider = document.getElementById("corbeille-vider");
  var boutonRestaurer = document.getElementById("corbeille-restaurer");
  var succes = document.getElementById("corbeille-succes");
  var succesTexte = document.getElementById("corbeille-succes-texte");
  var erreurEl = document.getElementById("corbeille-erreur");
  var minuteurConfirmation = null;
  var minuteurSucces = null;
  var occupe = false;

  function nombre() {
    return Number(zone.getAttribute("data-nombre")) || 0;
  }

  function pluriel(n, mot) {
    return n + " " + mot + (n > 1 ? "s" : "");
  }

  function texteEtat(n) {
    return n === 0 ? "La corbeille est vide." : pluriel(n, "carte") + " dans la corbeille.";
  }

  /* Texte d'origine du bouton rouge, après une confirmation annulée ou terminée */
  function annulerConfirmation() {
    if (minuteurConfirmation !== null) {
      clearTimeout(minuteurConfirmation);
      minuteurConfirmation = null;
    }
    if (boutonVider) {
      boutonVider.textContent = "Supprimer définitivement";
      boutonVider.classList.remove("corbeille__supprimer--confirme");
    }
  }

  /* Met à jour l'icône (gris / rouge), le nombre et le contenu de la fenêtre. */
  function definir(n) {
    n = Math.max(0, Math.floor(Number(n) || 0));
    zone.setAttribute("data-nombre", String(n));
    zone.classList.toggle("corbeille--pleine", n > 0);
    zone.classList.toggle("corbeille--vide", n === 0);
    nombreEl.textContent = "(" + n + ")";
    bouton.setAttribute("aria-label", n === 0 ? "Corbeille : vide" : "Corbeille : " + pluriel(n, "carte"));
    etatEl.textContent = texteEtat(n);
    actions.hidden = n === 0;
    if (n === 0) {
      annulerConfirmation();
    }
  }

  function ouvrir() {
    info.hidden = false;
    bouton.setAttribute("aria-expanded", "true");
  }

  function fermer() {
    info.hidden = true;
    bouton.setAttribute("aria-expanded", "false");
    annulerConfirmation();
  }

  function afficherErreur(texte) {
    erreurEl.textContent = texte;
    erreurEl.hidden = !texte;
  }

  function surServeur() {
    return window.location.protocol === "http:" || window.location.protocol === "https:";
  }

  function demander(url, corps) {
    if (!surServeur()) {
      return Promise.reject(new Error("lance python main.py, puis utilise la page qui s'ouvre"));
    }
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

  function recharger() {
    window.location.reload();
  }

  /* Petite animation de confirmation : une coche se dessine et « La corbeille est vide ! »
     apparaît, puis la fenêtre revient à son état normal. */
  function afficherSucces(texte, pageARecharger) {
    if (minuteurSucces !== null) {
      clearTimeout(minuteurSucces);
    }
    succesTexte.textContent = texte;
    succes.hidden = false;
    zone.classList.add("corbeille--videe");
    etatEl.hidden = true;
    actions.hidden = true;
    minuteurSucces = setTimeout(function () {
      minuteurSucces = null;
      succes.hidden = true;
      zone.classList.remove("corbeille--videe");
      etatEl.hidden = false;
      actions.hidden = nombre() === 0;
      if (pageARecharger) {
        recharger();
      }
    }, DUREE_SUCCES);
  }

  /* « Supprimer définitivement » : un 1er clic demande confirmation, un 2e clic exécute. */
  function viderDefinitivement() {
    if (occupe || nombre() === 0) {
      return Promise.resolve();
    }
    if (minuteurConfirmation === null) {
      boutonVider.textContent = "Confirmer : supprimer " + pluriel(nombre(), "carte") + " ?";
      boutonVider.classList.add("corbeille__supprimer--confirme");
      minuteurConfirmation = setTimeout(annulerConfirmation, DELAI_CONFIRMATION);
      return Promise.resolve();
    }
    annulerConfirmation();
    occupe = true;
    afficherErreur("");
    return demander("/api/corbeille/supprimer", { tout: true })
      .then(function (donnees) {
        jouerSon("suppression");                      /* suppression définitive */
        definir(donnees.corbeille);
        afficherSucces("La corbeille est vide !", zone.getAttribute("data-recharge-vidage") === "1");
      })
      .catch(function (erreur) {
        afficherErreur("Suppression impossible : " + erreur.message);
      })
      .then(function () {
        occupe = false;
      });
  }

  function restaurerTout() {
    if (occupe || nombre() === 0) {
      return Promise.resolve();
    }
    occupe = true;
    afficherErreur("");
    return demander("/api/corbeille/restaurer", { tout: true })
      .then(function (donnees) {
        jouerSon("restauration");                     /* cartes restaurées */
        definir(donnees.corbeille);
        etatEl.textContent = pluriel(donnees.restaurees, "carte") +
          (donnees.restaurees > 1 ? " restaurées" : " restaurée") + " dans ta collection.";
        if (zone.getAttribute("data-recharge-restauration") === "1") {
          setTimeout(recharger, delaiRechargement());
        }
      })
      .catch(function (erreur) {
        afficherErreur("Restauration impossible : " + erreur.message);
      })
      .then(function () {
        occupe = false;
      });
  }

  bouton.addEventListener("click", function () {
    if (info.hidden) {
      ouvrir();
    } else {
      fermer();
    }
  });
  if (boutonVider) {
    boutonVider.addEventListener("click", viderDefinitivement);
  }
  if (boutonRestaurer) {
    boutonRestaurer.addEventListener("click", restaurerTout);
  }
  document.addEventListener("click", function (evenement) {     /* un clic ailleurs ferme la fenêtre */
    if (!info.hidden && evenement.target && evenement.target.closest &&
        !evenement.target.closest("#corbeille-zone")) {
      fermer();
    }
  });
  document.addEventListener("keydown", function (evenement) {
    if (evenement.key === "Escape" && !info.hidden) {
      fermer();
      bouton.focus();
    }
  });

  window.WikiCorbeille = { definir: definir, nombre: nombre, ouvrir: ouvrir, fermer: fermer };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { definir: definir, ouvrir: ouvrir, fermer: fermer, viderDefinitivement: viderDefinitivement,
      restaurerTout: restaurerTout, nombre: nombre };
  }
})();
