/* Journal d'activité (voir wikicartes/journal.py) : Configuration > Système.
   - la case « Journal activé » (enregistrée tout de suite) : désactivé, RIEN n'est écrit, ni dans le fichier ni dans la fenêtre de commandes ;
   - « Ouvrir le journal » : lecture dans la page, en direct (les nouvelles lignes arrivent toutes seules), avec défilement automatique ;
   - « Ouvrir dans le Bloc-notes » : le fichier s'ouvre avec l'application par défaut ;
   - « Supprimer le journal » : le fichier est effacé ; si le journal est activé, un nouveau recommence tout de suite avec un nouvel en-tête. */
(function () {
  "use strict";

  var bloc = document.getElementById("journal-bloc");
  var jeton = document.body ? document.body.getAttribute("data-jeton") : "";
  if (!bloc || !jeton || (window.location.protocol !== "http:" && window.location.protocol !== "https:")) {
    return;
  }

  var caseActif = document.getElementById("journal-actif");
  var infos = document.getElementById("journal-etat");
  var message = document.getElementById("journal-message");
  var boutonOuvrir = document.getElementById("journal-ouvrir");
  var boutonExterne = document.getElementById("journal-externe");
  var boutonSupprimer = document.getElementById("journal-supprimer");
  var MAX_AFFICHE = 400000;                 /* caractères gardés dans la fenêtre de lecture */
  var fenetre = null;
  var sondage = null;

  function appeler(chemin, donnees) {
    return fetch(chemin, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Jeton": jeton },
      body: JSON.stringify(donnees || {})
    }).catch(function () {
      throw new Error("le programme ne répond pas");
    }).then(function (reponse) {
      return reponse.json().catch(function () { return {}; }).then(function (corps) {
        if (!reponse.ok) {
          throw new Error(corps.erreur || "erreur du programme");
        }
        return corps;
      });
    });
  }

  function taille(octets) {
    if (octets < 1024) {
      return octets + " octets";
    }
    if (octets < 1024 * 1024) {
      return Math.round(octets / 102.4) / 10 + " Ko";
    }
    return Math.round(octets / 104857.6) / 10 + " Mo";
  }

  function afficherEtat(e) {
    caseActif.checked = !!e.actif;
    var morceaux = [e.actif ? "Journal activé" : "Journal désactivé : rien n'est écrit"];
    morceaux.push(e.existe ? "fichier : " + e.chemin + " (" + e.lignes.toLocaleString("fr-FR") + " lignes, " + taille(e.taille) + ")" : "aucun journal pour le moment (" + e.chemin + ")");
    morceaux.push("session démarrée le " + e.session);
    infos.textContent = morceaux.join(" · ");
    boutonOuvrir.disabled = !e.existe;
    boutonExterne.disabled = !e.existe;
    boutonSupprimer.disabled = !e.existe;
  }

  function rafraichir() {
    return appeler("/api/journal/etat").then(afficherEtat).catch(function (erreur) {
      infos.textContent = "Journal : " + erreur.message;
    });
  }

  caseActif.addEventListener("change", function () {
    var voulu = caseActif.checked;
    caseActif.disabled = true;
    message.textContent = "";
    appeler("/api/configuration", { valeurs: { JOURNAL_ACTIF: voulu } }).then(function () {
      message.textContent = voulu ? "Journal activé : tout ce qui se passe est maintenant écrit dans journal.log et dans la fenêtre de commandes." : "Journal désactivé : plus rien n'est écrit.";
      return rafraichir();
    }).catch(function (erreur) {
      caseActif.checked = !voulu;
      message.textContent = "Impossible de changer le réglage : " + erreur.message;
    }).then(function () {
      caseActif.disabled = false;
    });
  });

  boutonExterne.addEventListener("click", function () {
    message.textContent = "";
    appeler("/api/journal/ouvrir").then(function () {
      message.textContent = "Le journal s'ouvre dans l'application par défaut.";
    }).catch(function (erreur) {
      message.textContent = "Impossible d'ouvrir le fichier : " + erreur.message;
    });
  });

  boutonSupprimer.addEventListener("click", function () {
    if (!window.confirm("Supprimer le journal ?\n\nLe fichier journal.log sera effacé définitivement." + (caseActif.checked ? " Un nouveau journal commencera tout de suite, puisque le journal est activé." : ""))) {
      return;
    }
    message.textContent = "";
    appeler("/api/journal/supprimer").then(function (e) {
      afficherEtat(e);
      message.textContent = caseActif.checked ? "Journal supprimé. Un nouveau journal a commencé." : "Journal supprimé.";
      if (fenetre) {
        fermerFenetre();
      }
    }).catch(function (erreur) {
      message.textContent = "Impossible de supprimer le journal : " + erreur.message;
    });
  });

  /* ------------------------------------------------------------------------------------------ la fenêtre de lecture en direct */

  function fermerFenetre() {
    if (sondage) {
      window.clearInterval(sondage);
      sondage = null;
    }
    if (fenetre && fenetre.parentNode) {
      fenetre.parentNode.removeChild(fenetre);
    }
    fenetre = null;
    document.removeEventListener("keydown", surTouche, true);
    boutonOuvrir.focus();
    rafraichir();
  }

  function surTouche(evenement) {
    if (evenement.key === "Escape" && fenetre) {
      evenement.preventDefault();
      fermerFenetre();
    }
  }

  function ouvrirFenetre() {
    if (fenetre) {
      return;
    }
    fenetre = document.createElement("div");
    fenetre.className = "journal-fenetre";
    var boite = document.createElement("div");
    boite.className = "journal-fenetre__boite";
    boite.setAttribute("role", "dialog");
    boite.setAttribute("aria-modal", "true");
    boite.setAttribute("aria-label", "Journal d'activité");
    var titre = document.createElement("h2");
    titre.className = "journal-fenetre__titre";
    titre.textContent = "Journal d'activité";
    var statut = document.createElement("p");
    statut.className = "journal-fenetre__statut";
    var texte = document.createElement("pre");
    texte.className = "journal-fenetre__texte";
    texte.tabIndex = 0;
    texte.setAttribute("aria-label", "Contenu du journal");
    var actions = document.createElement("div");
    actions.className = "journal-fenetre__actions";
    var suivre = document.createElement("label");
    suivre.className = "journal-fenetre__suivre";
    var caseSuivre = document.createElement("input");
    caseSuivre.type = "checkbox";
    caseSuivre.checked = true;
    suivre.appendChild(caseSuivre);
    suivre.appendChild(document.createTextNode(" Suivre en direct (défilement automatique)"));
    var fermerBouton = document.createElement("button");
    fermerBouton.type = "button";
    fermerBouton.className = "bouton-site bouton-site--principal";
    fermerBouton.textContent = "Fermer";
    fermerBouton.addEventListener("click", fermerFenetre);
    actions.appendChild(suivre);
    actions.appendChild(fermerBouton);
    [titre, statut, texte, actions].forEach(function (e) { boite.appendChild(e); });
    fenetre.appendChild(boite);
    document.body.appendChild(fenetre);
    document.addEventListener("keydown", surTouche, true);
    var position = -1;
    var enCours = false;

    function defiler() {
      if (caseSuivre.checked) {
        texte.scrollTop = texte.scrollHeight;
      }
    }
    function lire() {
      if (enCours || !fenetre) {
        return;
      }
      enCours = true;
      appeler("/api/journal/lire", { depuis: position }).then(function (r) {
        if (!fenetre) {
          return;
        }
        if (r.repart) {
          texte.textContent = "";                 /* le journal a été supprimé puis recréé : on repart du début */
        }
        if (r.texte) {
          texte.textContent += r.texte;
          if (texte.textContent.length > MAX_AFFICHE) {
            texte.textContent = texte.textContent.slice(-MAX_AFFICHE);
          }
        }
        position = r.position;
        statut.textContent = (r.actif ? "Journal activé — les nouvelles lignes arrivent toutes seules" : "Journal désactivé — plus rien n'est écrit") + " · " + taille(r.taille);
        if (!texte.textContent) {
          texte.textContent = r.taille ? "" : "(le journal est vide)";
        }
        defiler();
      }).catch(function (erreur) {
        statut.textContent = "Lecture impossible : " + erreur.message;
      }).then(function () {
        enCours = false;
      });
    }
    lire();
    sondage = window.setInterval(lire, 1500);
    fermerBouton.focus();
  }

  boutonOuvrir.addEventListener("click", ouvrirFenetre);
  rafraichir();
})();
