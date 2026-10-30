/* Importation de cartes en lot depuis un fichier .txt (voir wikicartes/lot.py).
   - Page Configuration, section Système : le bouton « Importer des cartes depuis un fichier .txt » ouvre une fenêtre : choix du fichier, analyse (titres, déjà possédés, requêtes et
     durée estimées, SANS rien demander à Wikipédia), puis lancement.
   - Pendant que l'importation travaille, TOUTES les pages du programme sont verrouillées par une fenêtre qui montre le compteur de cartes restantes, une barre de progression et le temps
     restant estimé. L'importation tourne dans le programme (pas dans le navigateur) : actualiser la page, ou même la fermer, ne l'arrête pas. Seul « Interrompre » l'arrête (elle
     pourra être reprise là où elle s'est arrêtée). */
(function () {
  "use strict";

  var html = document.documentElement;
  var corps = document.body;
  var jeton = corps ? corps.getAttribute("data-jeton") : "";
  if (!corps || !jeton || (window.location.protocol !== "http:" && window.location.protocol !== "https:")) {
    return;
  }

  var TAILLE_MAX = 5 * 1000 * 1000;
  var fenetre = null;                       /* la fenêtre ouverte (une seule à la fois) */
  var sondage = null;                       /* l'intervalle qui lit l'état de l'importation */
  var compte = null;                        /* l'intervalle qui fait descendre le temps restant entre deux lectures */
  var verrouillee = false;
  var precedent = null;
  var ecouteurEchap = null;                 /* Échap ferme la fenêtre de CHOIX du fichier (jamais celle de la progression) */

  function appeler(chemin, donnees) {
    return fetch(chemin, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Jeton": jeton },
      body: JSON.stringify(donnees || {})
    }).catch(function () {
      throw new Error("le programme ne répond pas");
    }).then(function (reponse) {
      return reponse.json().catch(function () { return {}; }).then(function (corpsReponse) {
        if (!reponse.ok) {
          throw new Error(corpsReponse.erreur || "erreur du programme");
        }
        return corpsReponse;
      });
    });
  }

  function nombre(n) {
    return Number(n || 0).toLocaleString("fr-FR");
  }

  function duree(secondes) {
    var s = Math.max(0, Math.round(Number(secondes) || 0));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    if (h) {
      return h + " h " + (m < 10 ? "0" : "") + m + " min";
    }
    if (m) {
      return m + " min " + (r < 10 ? "0" : "") + r + " s";
    }
    return r + " s";
  }

  function creer(nomBalise, classe, texte) {
    var e = document.createElement(nomBalise);
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

  /* ----------------------------------------------------------------------------------------------------------- la fenêtre */

  function verrouillerPage(oui) {
    verrouillee = oui;
    Array.prototype.forEach.call(corps.children, function (enfant) {
      if (enfant !== fenetre) {
        if (oui) {
          enfant.setAttribute("inert", "");
        } else {
          enfant.removeAttribute("inert");
        }
      }
    });
    html.classList.toggle("lot-ouvert", oui);
  }

  function ouvrir(titre) {
    fermer();
    precedent = document.activeElement;
    fenetre = creer("div", "lot-fenetre");
    fenetre.setAttribute("role", "dialog");
    fenetre.setAttribute("aria-modal", "true");
    fenetre.setAttribute("aria-labelledby", "lot-titre");
    var boite = creer("div", "lot-fenetre__boite");
    var h = creer("h2", "lot-fenetre__titre", titre);
    h.id = "lot-titre";
    boite.appendChild(h);
    var contenu = creer("div", "lot-fenetre__contenu");
    boite.appendChild(contenu);
    fenetre.appendChild(boite);
    corps.appendChild(fenetre);
    verrouillerPage(true);
    return contenu;
  }

  function fermer() {
    if (ecouteurEchap) {
      document.removeEventListener("keydown", ecouteurEchap, true);
      ecouteurEchap = null;
    }
    if (sondage) {
      window.clearInterval(sondage);
      sondage = null;
    }
    if (compte) {
      window.clearInterval(compte);
      compte = null;
    }
    if (fenetre && fenetre.parentNode) {
      fenetre.parentNode.removeChild(fenetre);
    }
    fenetre = null;
    verrouillerPage(false);
    if (precedent && precedent.focus && document.body.contains(precedent)) {
      try { precedent.focus({ preventScroll: true }); } catch (erreur) { /* sans importance */ }
    }
  }

  /* ----------------------------------------------------------------------------------------------------------- 1. choisir un fichier */

  function etapeChoix() {
    var contenu = ouvrir("Importer des cartes depuis un fichier .txt");
    contenu.appendChild(creer("p", "lot-fenetre__aide", "Le fichier contient un titre d'article Wikipédia par ligne (les adresses d'articles Wikipédia sont acceptées aussi). " +
      "Les cartes sont créées doucement : 20 titres par requête, une requête à la fois, avec une pause entre deux requêtes. Wikipédia n'est jamais surchargée."));
    var entree = creer("input");
    entree.type = "file";
    entree.accept = ".txt,text/plain";
    entree.hidden = true;
    entree.id = "lot-fichier";
    var zone = creer("button", "lot-zone");
    zone.type = "button";
    zone.textContent = "Choisir un fichier .txt… (ou le déposer ici)";
    var nomFichier = creer("p", "lot-fenetre__fichier", "");
    var resume = creer("div", "lot-resume");
    resume.hidden = true;
    var option = creer("label", "lot-option");
    var caseOption = creer("input");
    caseOption.type = "checkbox";
    caseOption.checked = true;
    option.appendChild(caseOption);
    option.appendChild(document.createTextNode(" Ignorer les articles déjà présents dans ma collection (recommandé)"));
    option.hidden = true;
    var avertissement = creer("p", "lot-fenetre__avertissement", "Une fois lancée, l'importation verrouille tout le programme jusqu'à sa fin (ou jusqu'à ce que tu l'interrompes). " +
      "Elle continue même si tu fermes cette page ; seul le programme doit rester ouvert.");
    avertissement.hidden = true;
    var message = creer("p", "lot-fenetre__message");
    message.setAttribute("role", "status");
    var actions = creer("div", "lot-fenetre__actions");
    var annuler = bouton("Annuler", "", fermer);
    var lancer = bouton("Lancer l'importation", "bouton-site--principal", function () { demarrer(); });
    lancer.disabled = true;
    actions.appendChild(annuler);
    actions.appendChild(lancer);
    [entree, zone, nomFichier, resume, option, avertissement, message, actions].forEach(function (e) { contenu.appendChild(e); });

    var texte = null;
    var nom = "";
    function analyser() {
      message.textContent = "Analyse du fichier…";
      lancer.disabled = true;
      appeler("/api/lot/analyser", { texte: texte, ignorer_possedes: caseOption.checked }).then(function (a) {
        message.textContent = "";
        resume.hidden = false;
        resume.textContent = "";
        var liste = creer("ul", "lot-resume__liste");
        function ligne(txt, fort) {
          var li = creer("li", fort ? "lot-resume__fort" : "", txt);
          liste.appendChild(li);
        }
        ligne(nombre(a.lignes) + " ligne" + (a.lignes > 1 ? "s" : "") + " lue" + (a.lignes > 1 ? "s" : "") + " → " + nombre(a.titres) + " titre" + (a.titres > 1 ? "s" : "") + " distinct" + (a.titres > 1 ? "s" : "") +
          (a.doublons ? " (" + nombre(a.doublons) + " doublon" + (a.doublons > 1 ? "s" : "") + " dans le fichier)" : "") + (a.invalides ? ", " + nombre(a.invalides) + " ligne" + (a.invalides > 1 ? "s" : "") + " invalide" + (a.invalides > 1 ? "s" : "") + " ignorée" + (a.invalides > 1 ? "s" : "") : ""));
        if (a.deja_possedes) {
          ligne(nombre(a.deja_possedes) + " déjà dans ta collection" + (caseOption.checked ? " (écartés, sans aucune requête)" : " (seront importés une 2e fois)"));
        }
        ligne(nombre(a.a_importer) + " carte" + (a.a_importer > 1 ? "s" : "") + " à importer", true);
        if (a.a_importer > 0) {
          ligne("≈ " + nombre(a.requetes) + " requête" + (a.requetes > 1 ? "s" : "") + " à Wikipédia (" + a.taille_lot + " titres chacune, pause de " + String(a.pause).replace(".", ",") + " s) → durée estimée : " + duree(a.secondes), true);
          if (a.exemples && a.exemples.length) {
            ligne("Exemples : " + a.exemples.join(", ") + (a.titres > a.exemples.length ? "…" : ""));
          }
        }
        resume.appendChild(liste);
        option.hidden = false;
        avertissement.hidden = a.a_importer <= 0;
        lancer.disabled = a.a_importer <= 0;
        if (a.a_importer <= 0) {
          message.textContent = "Rien à importer : tous les articles de ce fichier sont déjà dans ta collection (ou le fichier est vide).";
        }
      }).catch(function (erreur) {
        resume.hidden = true;
        option.hidden = true;
        avertissement.hidden = true;
        message.textContent = "Fichier refusé : " + erreur.message;
      });
    }
    function lire(fichier) {
      if (!fichier) {
        return;
      }
      if (!/\.txt$/i.test(fichier.name) && fichier.type && fichier.type.indexOf("text") !== 0) {
        message.textContent = "Ce n'est pas un fichier texte (.txt).";
        return;
      }
      if (fichier.size > TAILLE_MAX) {
        message.textContent = "Ce fichier est trop gros (plus de 5 Mo).";
        return;
      }
      nom = fichier.name;
      nomFichier.textContent = "Fichier : " + nom + " (" + nombre(Math.round(fichier.size / 1024)) + " Ko)";
      var lecteur = new FileReader();
      lecteur.onload = function () {
        texte = String(lecteur.result || "");
        analyser();
      };
      lecteur.onerror = function () {
        message.textContent = "Impossible de lire ce fichier.";
      };
      lecteur.readAsText(fichier, "utf-8");
    }
    zone.addEventListener("click", function () { entree.click(); });
    entree.addEventListener("change", function () { lire(entree.files && entree.files[0]); });
    ["dragenter", "dragover"].forEach(function (nomEvt) {
      zone.addEventListener(nomEvt, function (evenement) { evenement.preventDefault(); zone.classList.add("lot-zone--survol"); });
    });
    ["dragleave", "drop"].forEach(function (nomEvt) {
      zone.addEventListener(nomEvt, function (evenement) { evenement.preventDefault(); zone.classList.remove("lot-zone--survol"); });
    });
    zone.addEventListener("drop", function (evenement) {
      lire(evenement.dataTransfer && evenement.dataTransfer.files && evenement.dataTransfer.files[0]);
    });
    caseOption.addEventListener("change", function () { if (texte !== null) { analyser(); } });
    function demarrer() {
      lancer.disabled = true;
      message.textContent = "Démarrage…";
      appeler("/api/lot/demarrer", { texte: texte, nom: nom, ignorer_possedes: caseOption.checked }).then(function (etat) {
        etapeProgression(etat);
      }).catch(function (erreur) {
        message.textContent = "Impossible de démarrer : " + erreur.message;
        lancer.disabled = false;
      });
    }
    ecouteurEchap = function (evenement) {
      if (evenement.key === "Escape" && fenetre) {
        evenement.preventDefault();
        fermer();
      }
    };
    document.addEventListener("keydown", ecouteurEchap, true);
    zone.focus();
  }

  /* ----------------------------------------------------------------------------------------------------------- 2. la progression (verrouille tout) */

  var etatCourant = null;
  var instantEtat = 0;

  function etapeProgression(etatInitial) {
    var contenu = ouvrir("Importation de cartes");
    etatCourant = etatInitial;
    instantEtat = Date.now();
    var fichier = creer("p", "lot-fenetre__fichier", "");
    var grand = creer("p", "lot-grand");
    var chiffre = creer("span", "lot-grand__chiffre", "…");
    var libelle = creer("span", "lot-grand__libelle", " cartes restantes à générer");
    grand.appendChild(chiffre);
    grand.appendChild(libelle);
    var barre = creer("div", "lot-barre");
    barre.setAttribute("role", "progressbar");
    barre.setAttribute("aria-valuemin", "0");
    barre.setAttribute("aria-valuemax", "100");
    var remplissage = creer("div", "lot-barre__remplissage");
    var pourcent = creer("span", "lot-barre__texte", "0 %");
    barre.appendChild(remplissage);
    barre.appendChild(pourcent);
    var temps = creer("p", "lot-temps", "");
    var details = creer("p", "lot-details", "");
    var statut = creer("p", "lot-statut", "");
    statut.setAttribute("role", "status");
    statut.setAttribute("aria-live", "polite");
    var actions = creer("div", "lot-fenetre__actions");
    var confirmation = creer("div", "lot-confirmation");
    confirmation.hidden = true;
    [fichier, grand, barre, temps, details, statut, confirmation, actions].forEach(function (e) { contenu.appendChild(e); });

    function bandeauFin(e) {
      /* terminée ou interrompue : on remplace les boutons */
      actions.textContent = "";
      confirmation.hidden = true;
      if (e.etat === "termine") {
        statut.textContent = "Importation terminée. Les statistiques secondaires (modifications, liens) arrivent peu à peu, en arrière-plan.";
        actions.appendChild(bouton("Terminer", "bouton-site--principal", function () { fermer(); window.location.reload(); }));
      } else {
        statut.textContent = e.message || "Importation interrompue.";
        actions.appendChild(bouton("Reprendre l'importation", "bouton-site--principal", function () {
          appeler("/api/lot/reprendre").then(function (nouveau) { etapeProgression(nouveau); }).catch(function (erreur) { statut.textContent = "Impossible de reprendre : " + erreur.message; });
        }));
        actions.appendChild(bouton("Fermer", "", function () { fermer(); window.location.reload(); }));
        actions.appendChild(bouton("Abandonner l'importation", "lot-danger", function () {
          confirmation.hidden = false;
          confirmation.textContent = "";
          confirmation.appendChild(creer("p", "", "Abandonner efface ce qui reste à importer (les cartes déjà créées restent dans ta collection). Continuer ?"));
          var ligne = creer("div", "lot-fenetre__actions");
          ligne.appendChild(bouton("Oui, abandonner", "lot-danger", function () {
            appeler("/api/lot/abandonner").then(function () { fermer(); window.location.reload(); }).catch(function (erreur) { statut.textContent = erreur.message; });
          }));
          ligne.appendChild(bouton("Non", "", function () { confirmation.hidden = true; }));
          confirmation.appendChild(ligne);
        }));
      }
    }

    function afficher(e) {
      etatCourant = e;
      instantEtat = Date.now();
      fichier.textContent = e.nom ? "Fichier : " + e.nom : "";
      chiffre.textContent = nombre(e.restantes);
      libelle.textContent = e.restantes > 1 ? " cartes restantes à générer" : " carte restante à générer";
      remplissage.style.width = Math.max(0, Math.min(100, e.pourcentage)) + "%";
      barre.setAttribute("aria-valuenow", String(Math.round(e.pourcentage)));
      pourcent.textContent = String(e.pourcentage).replace(".", ",") + " %";
      var morceaux = [nombre(e.importes) + " importée" + (e.importes > 1 ? "s" : ""), nombre(e.possedes) + " déjà possédée" + (e.possedes > 1 ? "s" : "")];
      if (e.introuvables) {
        morceaux.push(nombre(e.introuvables) + " introuvable" + (e.introuvables > 1 ? "s" : ""));
      }
      if (e.ignores) {
        morceaux.push(nombre(e.ignores) + " ignorée" + (e.ignores > 1 ? "s" : "") + " (homonymie, hors articles)");
      }
      if (e.sans_vues) {
        morceaux.push(nombre(e.sans_vues) + " sans vues connues (rang C)");
      }
      details.textContent = morceaux.join(" · ");
      if (e.etat === "en_cours" && e.actif) {
        statut.textContent = e.message || "";
        if (!actions.firstChild || actions.firstChild.textContent !== "Interrompre") {
          actions.textContent = "";
          actions.appendChild(bouton("Interrompre", "", function () {
            confirmation.hidden = false;
            confirmation.textContent = "";
            confirmation.appendChild(creer("p", "", "Interrompre l'importation ? Ce qui est déjà fait est gardé, et tu pourras la reprendre plus tard."));
            var ligne = creer("div", "lot-fenetre__actions");
            ligne.appendChild(bouton("Oui, interrompre", "", function () {
              confirmation.hidden = true;
              statut.textContent = "Interruption en cours : la requête en cours se termine d'abord…";
              appeler("/api/lot/interrompre").catch(function (erreur) { statut.textContent = erreur.message; });
            }));
            ligne.appendChild(bouton("Non, continuer", "", function () { confirmation.hidden = true; }));
            confirmation.appendChild(ligne);
          }));
        }
        temps.textContent = e.eta_s === null ? "" : "Temps restant estimé : " + duree(e.eta_s) + "  ·  " + nombre(e.requetes_restantes) + " requête" + (e.requetes_restantes > 1 ? "s" : "") + " à faire (pause de " + String(e.pause).replace(".", ",") + " s)";
      } else {
        temps.textContent = e.etat === "termine" ? "Durée totale : " + duree(e.duree_s) + " · " + nombre(e.requetes) + " requêtes" + (e.moyenne_requete_s ? " (" + String(e.moyenne_requete_s).replace(".", ",") + " s en moyenne)" : "") +
          (e.ralentissements ? " · Wikipédia a demandé de ralentir " + e.ralentissements + " fois" : "") : "";
        bandeauFin(e);
        if (sondage) {
          window.clearInterval(sondage);
          sondage = null;
        }
        if (compte) {
          window.clearInterval(compte);
          compte = null;
        }
      }
    }

    afficher(etatInitial);
    function lire() {
      appeler("/api/lot/etat").then(function (e) {
        if (!e.presente) {
          fermer();
          window.location.reload();
          return;
        }
        if (fenetre) {
          afficher(e);
        }
      }).catch(function () {
        if (fenetre) {
          statut.textContent = "Le programme ne répond plus… (l'importation reprendra si le programme est relancé et que tu la reprends)";
        }
      });
    }
    sondage = window.setInterval(lire, 1000);
    compte = window.setInterval(function () {       /* le temps restant descend seconde après seconde entre deux lectures */
      if (etatCourant && etatCourant.etat === "en_cours" && etatCourant.actif && etatCourant.eta_s !== null) {
        var reste = Math.max(0, etatCourant.eta_s - (Date.now() - instantEtat) / 1000);
        temps.textContent = "Temps restant estimé : " + duree(reste) + "  ·  " + nombre(etatCourant.requetes_restantes) + " requête" + (etatCourant.requetes_restantes > 1 ? "s" : "") + " à faire (pause de " + String(etatCourant.pause).replace(".", ",") + " s)";
      }
    }, 500);
  }

  /* l'importation travaille : on prévient avant de quitter la page (elle continuerait quand même, mais on ne la verrait plus) */
  window.addEventListener("beforeunload", function (evenement) {
    if (etatCourant && etatCourant.etat === "en_cours" && etatCourant.actif && fenetre) {
      evenement.preventDefault();
      evenement.returnValue = "";
    }
  });

  /* ----------------------------------------------------------------------------------------------------------- démarrage de la page */

  function bloc() {
    var ouvrirBouton = document.getElementById("lot-ouvrir");
    var infos = document.getElementById("lot-bloc-etat");
    if (!ouvrirBouton) {
      return;
    }
    function majBloc(e) {
      if (e && e.presente && e.etat === "interrompu" && e.restantes > 0) {
        ouvrirBouton.textContent = "▶ Reprendre l'importation interrompue";
        if (infos) {
          infos.textContent = "Une importation est en pause : " + nombre(e.restantes) + " carte" + (e.restantes > 1 ? "s" : "") + " restante" + (e.restantes > 1 ? "s" : "") + " sur " + nombre(e.total) + ".";
        }
      }
    }
    ouvrirBouton.addEventListener("click", function () {
      appeler("/api/lot/etat").then(function (e) {
        if (e.presente && e.etat === "interrompu" && e.restantes > 0) {
          etapeProgression(e);
        } else if (e.presente && e.etat === "en_cours" && e.actif) {
          etapeProgression(e);
        } else {
          etapeChoix();
        }
      }).catch(function () { etapeChoix(); });
    });
    appeler("/api/lot/etat").then(majBloc).catch(function () { /* sans importance */ });
  }

  function demarrage() {
    bloc();
    if (html.getAttribute("data-lot") === "1") {         /* une importation travaille : cette page est verrouillée aussi */
      appeler("/api/lot/etat").then(function (e) {
        if (e.presente && e.etat === "en_cours" && e.actif) {
          etapeProgression(e);
        }
      }).catch(function () { /* sans importance */ });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", demarrage);
  } else {
    demarrage();
  }
})();
