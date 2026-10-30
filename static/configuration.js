/* Page Configuration :
   - aperçu en direct de chaque rang (lettres, motif, couleurs, reflet) ;
   - éditeur de catégories : ajouter, modifier, supprimer (sans supprimer les cartes), meta ;
   - aperçu du booster (style, logo ou texte) et bouton pour tester l'animation d'ouverture ;
   - état de la réserve de cartes (pré-chargement), mis à jour toutes les 5 secondes ;
   - boutons ↺ : retour à la valeur de config.py, par réglage ou par rang ;
   - enregistrement de tous les réglages dans la base, puis rechargement de la page ;
   - remise à zéro de toute la configuration. */
(function () {
  "use strict";

  var TEXTE_FONCE = "#1a1a1f";
  var TEXTE_CLAIR = "#ffffff";

  /* ------------------------------------------------ couleurs d'un rang
     Mêmes formules que wikicartes/theme.py : à modifier ensemble. */

  function hexVersRvb(couleur) {
    return [
      parseInt(couleur.substr(1, 2), 16),
      parseInt(couleur.substr(3, 2), 16),
      parseInt(couleur.substr(5, 2), 16)
    ];
  }

  function lineaire(composante) {
    var v = composante / 255;
    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  }

  function luminance(couleur) {
    var rvb = hexVersRvb(couleur);
    return 0.2126 * lineaire(rvb[0]) + 0.7152 * lineaire(rvb[1]) + 0.0722 * lineaire(rvb[2]);
  }

  function couleurLisible(lum) {
    var contrasteFonce = (lum + 0.05) / (luminance(TEXTE_FONCE) + 0.05);
    var contrasteClair = 1.05 / (lum + 0.05);
    return contrasteFonce >= contrasteClair ? TEXTE_FONCE : TEXTE_CLAIR;
  }

  function rgba(couleur, opacite) {
    var rvb = hexVersRvb(couleur);
    return "rgba(" + rvb[0] + ", " + rvb[1] + ", " + rvb[2] + ", " + opacite + ")";
  }

  /* Variables CSS d'un rang, à partir de ses trois couleurs. */
  function variablesRang(c1, c2, c3) {
    return {
      "--c1": c1,
      "--c2": c2,
      "--c3": c3,
      "--texte": couleurLisible((luminance(c1) + luminance(c2)) / 2),
      "--badge-fond": c3,
      "--badge-texte": couleurLisible(luminance(c3)),
      "--halo": rgba(c3, 0.5),
      "--motif": rgba(c3, 0.34)
    };
  }

  /* --------------------------------------------------------- lecture des champs */

  function champRang(palier, nom) {
    return palier.querySelector('[data-palier-champ="' + nom + '"]');
  }

  function lireChamp(champ) {
    var type = champ.getAttribute("data-type");
    if (type === "bool") {
      return !!champ.checked;
    }
    if (type === "papier") {
      return Array.prototype.map.call(champ.querySelectorAll("[data-papier]"), function (saisie) {
        return nombreOuNull(saisie.value);
      });
    }
    if (type === "entier" || type === "nombre") {
      return nombreOuNull(champ.value);
    }
    return champ.value;
  }

  /* Un champ numérique vide ou illisible est envoyé tel quel (null) : le serveur le refuse. */
  function nombreOuNull(texte) {
    var propre = String(texte).trim();
    if (propre === "") {
      return null;
    }
    var nombre = Number(propre);
    return isNaN(nombre) ? null : nombre;
  }

  function ecrireChamp(champ, valeur) {
    var type = champ.getAttribute("data-type");
    if (type === "bool") {
      champ.checked = !!valeur;
    } else if (type === "papier") {
      var saisies = champ.querySelectorAll("[data-papier]");
      saisies.forEach(function (saisie, i) {
        saisie.value = valeur[i];
      });
    } else {
      champ.value = valeur;
    }
  }

  /* Toutes les valeurs de la page, au format attendu par le serveur. */
  function collecterValeurs(racine) {
    var valeurs = {};
    racine.querySelectorAll("[data-param]").forEach(function (champ) {
      var nom = champ.getAttribute("data-param");
      /* La taille des cartes se règle AUSSI avec le curseur de la page Collection (enregistré à la volée). Ce champ-ci
         n'est donc envoyé que si on l'a modifié ici : sinon il écraserait la taille réglée entre-temps avec la valeur
         qu'il avait au chargement de la page. */
      if (REGLES_PAR_LA_PAGE.indexOf(nom) !== -1 && champ.getAttribute("data-modifie") !== "1") {
        return;
      }
      valeurs[nom] = lireChamp(champ);
    });

    var paliers = [];
    var poids = {};
    var themes = {};
    var symboles = {};
    racine.querySelectorAll(".palier:not(.palier--perso)").forEach(function (palier) {
      var code = palier.getAttribute("data-palier");
      paliers.push([
        code,
        nombreOuNull(champRang(palier, "seuil").value),
        champRang(palier, "nom").value.trim()
      ]);
      poids[code] = nombreOuNull(champRang(palier, "poids").value);
      var champSymbole = champRang(palier, "symbole");
      symboles[code] = champSymbole ? champSymbole.value.trim() : code;
      themes[code] = {
        motif: champRang(palier, "motif").value,
        couleurs: [
          champRang(palier, "c1").value,
          champRang(palier, "c2").value,
          champRang(palier, "c3").value
        ],
        reflet: champRang(palier, "reflet").value
      };
    });
    if (paliers.length > 0) {
      valeurs.PALIERS = paliers;
      valeurs.POIDS = poids;
      valeurs.THEMES_PALIERS = themes;
      valeurs.SYMBOLES_PALIERS = symboles;
    }
    /* Le palier des cartes personnalisées (dernier de la liste) : ni seuil ni probabilité, ses propres réglages */
    var perso = racine.querySelector(".palier--perso");
    if (perso) {
      valeurs.PERSO_THEME = {
        motif: champRang(perso, "motif").value,
        couleurs: [champRang(perso, "c1").value, champRang(perso, "c2").value, champRang(perso, "c3").value],
        reflet: champRang(perso, "reflet").value
      };
      valeurs.PERSO_SYMBOLE = champRang(perso, "symbole").value.trim();
      valeurs.PERSO_NOM = champRang(perso, "nom").value.trim();
    }
    return valeurs;
  }

  /* ----------------------------------------------------------------- catégories */

  var NB_METAS = 5;

  /* Même règle que wikicartes/categories.py (tronquer) : le nom ne dépasse jamais `maximum`
     caractères, « … » compris. */
  function tronquer(nom, maximum) {
    var lettres = Array.from(nom);
    if (lettres.length <= maximum) {
      return nom;
    }
    return lettres.slice(0, Math.max(1, maximum - 1)).join("").replace(/\s+$/, "") + "…";
  }

  function champCategorie(bloc, nom) {
    return bloc.querySelector('[data-categorie-champ="' + nom + '"]');
  }

  function metasCategorie(bloc) {
    return Array.prototype.map.call(
      bloc.querySelectorAll('[data-categorie-champ="meta"]'),
      function (saisie) {
        return saisie.value.trim();
      }
    );
  }

  function longueurCategorieMax(racine) {
    var champ = racine.querySelector('[data-param="CATEGORIE_LONGUEUR_MAX"]');
    var valeur = champ ? Number(champ.value) : 14;
    return valeur > 0 ? valeur : 14;
  }

  /* Petit bandeau d'exemple, tel qu'il apparaîtra sur les cartes (nom coupé, couleur de fond). */
  function mettreAJourApercuCategorie(bloc, racine) {
    var zone = bloc.querySelector("[data-categorie-apercu]");
    if (!zone) {
      return;
    }
    zone.textContent = "";
    var nom = champCategorie(bloc, "nom").value.trim();
    if (nom === "") {
      return;
    }
    var couleur = champCategorie(bloc, "couleur").value;
    var bandeau = document.createElement("span");
    bandeau.className = "carte__categorie";
    bandeau.setAttribute(
      "style",
      "background: " + couleur + "; color: " + couleurLisible(luminance(couleur))
    );
    bandeau.setAttribute("title", nom);
    bandeau.textContent = tronquer(nom, longueurCategorieMax(racine));
    zone.appendChild(bandeau);
  }

  function categorieSupprimee(bloc) {
    return bloc.getAttribute("data-supprimee") === "oui";
  }

  /* Catégories à envoyer : celles qui restent (nouvelles ou modifiées) et les ids à supprimer.
     `blocs` garde l'ordre d'envoi, pour retrouver où afficher les erreurs du serveur. */
  function collecterCategories(racine) {
    var categories = [];
    var supprimees = [];
    var blocs = [];
    racine.querySelectorAll(".categorie").forEach(function (bloc) {
      var identifiant = Number(bloc.getAttribute("data-categorie")) || null;
      if (categorieSupprimee(bloc)) {
        if (identifiant) {
          supprimees.push(identifiant);
        }
        return;
      }
      categories.push({
        id: identifiant,
        nom: champCategorie(bloc, "nom").value.trim(),
        couleur: champCategorie(bloc, "couleur").value,
        metas: metasCategorie(bloc)
      });
      blocs.push(bloc);
    });
    return { categories: categories, supprimees: supprimees, blocs: blocs };
  }

  function basculerSuppressionCategorie(bloc, supprimee) {
    var identifiant = bloc.getAttribute("data-categorie");
    if (supprimee && !identifiant) {
      bloc.remove();                          /* pas encore enregistrée : on l'efface simplement */
      return;
    }
    if (supprimee) {
      bloc.setAttribute("data-supprimee", "oui");
    } else {
      bloc.removeAttribute("data-supprimee");
    }
    bloc.classList.toggle("categorie--supprimee", supprimee);
    var message = bloc.querySelector("[data-categorie-supprimee]");
    if (message) {
      message.hidden = !supprimee;
    }
  }

  function ajouterCategorie(racine) {
    var modele = document.getElementById("modele-categorie");
    var liste = document.getElementById("categories-liste");
    if (!modele || !liste) {
      return null;
    }
    var bloc = modele.content.firstElementChild.cloneNode(true);
    liste.appendChild(bloc);
    var vide = document.getElementById("categories-vide");
    if (vide) {
      vide.hidden = true;
    }
    mettreAJourApercuCategorie(bloc, racine);
    var nom = champCategorie(bloc, "nom");
    if (nom && nom.focus) {
      nom.focus();
    }
    return bloc;
  }

  /* Erreurs de catégories renvoyées par le serveur : {position dans la liste: {champ: texte}}. */
  var LIBELLES_CHAMPS = { nom: "Nom", couleur: "Couleur", metas: "Meta" };

  function afficherErreursCategories(blocs, erreurs) {
    var generales = [];
    Object.keys(erreurs).forEach(function (index) {
      var bloc = blocs[Number(index)];
      var textes = Object.keys(erreurs[index]).map(function (champ) {
        return (LIBELLES_CHAMPS[champ] || champ) + " : " + erreurs[index][champ];
      });
      if (!bloc) {
        generales = generales.concat(textes);
        return;
      }
      var zone = bloc.querySelector("[data-categorie-erreur]");
      if (zone) {
        zone.textContent = textes.join(" ; ");
        zone.hidden = false;
      }
      bloc.classList.add("champ--invalide");
    });
    return generales;
  }

  function effacerErreursCategories(racine) {
    racine.querySelectorAll("[data-categorie-erreur]").forEach(function (zone) {
      zone.hidden = true;
      zone.textContent = "";
    });
    racine.querySelectorAll(".categorie.champ--invalide").forEach(function (bloc) {
      bloc.classList.remove("champ--invalide");
    });
  }

  /* ---------------------------------------------------- aperçu des rangs en direct */

  function appliquerAuPalier(palier) {
    var carte = palier.querySelector(".carte");
    var variables = variablesRang(
      champRang(palier, "c1").value,
      champRang(palier, "c2").value,
      champRang(palier, "c3").value
    );
    Object.keys(variables).forEach(function (nom) {
      palier.style.setProperty(nom, variables[nom]);
      if (carte) {
        carte.style.setProperty(nom, variables[nom]);
      }
    });
    if (carte) {
      carte.setAttribute("data-motif", champRang(palier, "motif").value);
      carte.setAttribute("data-reflet", champRang(palier, "reflet").value);
    }
    var champSymbole = champRang(palier, "symbole");
    if (champSymbole) {                     /* les lettres du rang : pastille et badge de la carte */
      var symbole = champSymbole.value.trim();
      var pastille = palier.querySelector("[data-palier-code]");
      var badge = carte ? carte.querySelector(".carte__badge") : null;
      if (pastille) {
        pastille.textContent = symbole;
      }
      if (badge) {
        badge.textContent = symbole;
      }
    }
  }

  /* Part de chaque rang dans le tirage (probabilités relatives -> pourcentages). */
  function mettreAJourParts(racine) {
    var champs = racine.querySelectorAll('.palier:not(.palier--perso) [data-palier-champ="poids"]');
    var total = 0;
    champs.forEach(function (champ) {
      total += Math.max(0, Number(champ.value) || 0);
    });
    racine.querySelectorAll(".palier:not(.palier--perso)").forEach(function (palier) {
      var sortie = palier.querySelector("[data-palier-part]");
      var poids = Math.max(0, Number(champRang(palier, "poids").value) || 0);
      if (sortie) {
        sortie.textContent = total > 0 ? Math.round((poids / total) * 100) + " %" : "—";
      }
    });
  }

  /* ------------------------------------------------------------------ messages */

  var etat = document.getElementById("config-etat");
  var jeton = document.body ? document.body.getAttribute("data-jeton") : "";

  function afficherEtat(texte, erreur) {
    if (!etat) {
      return;
    }
    etat.textContent = texte;
    etat.className = "barre-config__etat" + (erreur ? " barre-config__etat--erreur" : "");
  }

  function surServeur() {
    return (window.location.protocol === "http:" || window.location.protocol === "https:") && !!jeton;
  }

  function effacerErreurs(racine) {
    racine.querySelectorAll("[data-erreur]").forEach(function (zone) {
      zone.hidden = true;
      zone.textContent = "";
    });
    racine.querySelectorAll(".champ--invalide").forEach(function (champ) {
      champ.classList.remove("champ--invalide");
    });
  }

  /* Affiche, sous chaque réglage refusé, l'explication donnée par le serveur. */
  function afficherErreurs(racine, erreurs) {
    var generales = [];
    Object.keys(erreurs).forEach(function (nom) {
      var zone = racine.querySelector('[data-erreur="' + nom + '"]');
      if (zone) {
        zone.textContent = erreurs[nom];
        zone.hidden = false;
        var champ = racine.querySelector('[data-champ="' + nom + '"]');
        if (champ) {
          champ.classList.add("champ--invalide");
        }
      } else {
        generales.push(nom + " : " + erreurs[nom]);
      }
    });
    return generales;
  }

  /* ------------------------------------------------------- enregistrement */

  function envoyer(corps) {
    return fetch("/api/configuration", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Jeton": jeton },
      body: JSON.stringify(corps)
    })
      .catch(function () {
        throw new Error("le serveur local est injoignable (lance python main.py)");
      })
      .then(function (reponse) {
        return reponse.json().then(function (donnees) {
          return { ok: reponse.ok, donnees: donnees };
        });
      });
  }

  function recharger() {
    setTimeout(function () {
      window.location.reload();
    }, 900);
  }

  /* Réglages que la page peut aussi modifier ailleurs (curseur de taille des cartes, haut-parleur et volume de la musique) :
     ils ne sont envoyés que si on les a modifiés ICI, sinon ils écraseraient ce qui a été réglé entre-temps. */
  var REGLES_PAR_LA_PAGE = ["LARGEUR_CARTE", "MUSIQUE_VOLUME", "MUSIQUE_COUPEE"];

  function enregistrer(racine) {
    if (!surServeur()) {
      afficherEtat(
        "L'enregistrement nécessite le serveur local : lance python main.py, puis utilise la " +
        "page qui s'ouvre.", true
      );
      return Promise.resolve();
    }
    effacerErreurs(racine);
    effacerErreursCategories(racine);
    afficherEtat("Enregistrement…", false);
    var lot = collecterCategories(racine);
    return envoyer({
      valeurs: collecterValeurs(racine),
      categories: lot.categories,
      categories_supprimees: lot.supprimees
    })
      .then(function (resultat) {
        if (!resultat.ok) {
          var generales = afficherErreurs(racine, resultat.donnees.erreurs || {});
          generales = generales.concat(
            afficherErreursCategories(lot.blocs, resultat.donnees.erreurs_categories || {})
          );
          afficherEtat(
            "Certains réglages sont refusés (voir en rouge)" +
              (generales.length ? " : " + generales.join(" ; ") : "."),
            true
          );
          return;
        }
        var relance = resultat.donnees.redemarrage || [];
        if (window.WikiSons) {                       /* sons et musique : pris en compte tout de suite, sans recharger */
          var reglesSons = reglagesSonsDuFormulaire(racine);
          window.WikiSons.appliquer(reglesSons);
          if (reglesSons.musique.actif && window.parent === window) {
            window.location.reload();                /* la musique vient d'être activée : la page s'affiche désormais dans le lecteur */
          }
        }
        afficherEtat(
          "Enregistré ✓" +
            (relance.length ? " — pris en compte au prochain lancement : " + relance.join(", ") : ""),
          false
        );
        recharger();
      })
      .catch(function (erreur) {
        afficherEtat("Échec de l'enregistrement : " + erreur.message, true);
      });
  }

  /* Classe dans la catégorie toute la collection qui correspond à ses meta. */
  function reclasserCategorie(bloc) {
    var identifiant = Number(bloc.getAttribute("data-categorie"));
    if (!identifiant) {
      return Promise.resolve();
    }
    if (!surServeur()) {
      afficherEtat("Le classement nécessite le serveur local (python main.py).", true);
      return Promise.resolve();
    }
    afficherEtat("Classement en cours…", false);
    return fetch("/api/categories/reclasser", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Jeton": jeton },
      body: JSON.stringify({ id: identifiant })
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
      })
      .then(function (donnees) {
        afficherEtat(
          donnees.ajoutees + (donnees.ajoutees > 1 ? " cartes ajoutées" : " carte ajoutée") +
            " à la catégorie. Pense à enregistrer d'abord si tu viens de modifier ses meta.",
          false
        );
      })
      .catch(function (erreur) {
        afficherEtat("Classement impossible : " + erreur.message, true);
      });
  }

  var minuteurConfirmation = null;

  /* Remise à zéro : il faut cliquer deux fois (le bouton demande confirmation). */
  function reinitialiserTout(bouton) {
    if (!surServeur()) {
      afficherEtat("La remise à zéro nécessite le serveur local (python main.py).", true);
      return Promise.resolve();
    }
    if (bouton.getAttribute("data-confirmation") !== "oui") {
      bouton.setAttribute("data-confirmation", "oui");
      bouton.setAttribute("data-libelle", bouton.textContent);
      bouton.textContent = "Cliquer encore pour confirmer";
      minuteurConfirmation = setTimeout(function () {
        bouton.removeAttribute("data-confirmation");
        bouton.textContent = bouton.getAttribute("data-libelle");
      }, 4000);
      return Promise.resolve();
    }
    clearTimeout(minuteurConfirmation);
    bouton.removeAttribute("data-confirmation");
    bouton.textContent = bouton.getAttribute("data-libelle");
    afficherEtat("Remise à zéro…", false);
    return envoyer({ reinitialiser: true })
      .then(function (resultat) {
        if (!resultat.ok) {
          afficherEtat("Remise à zéro impossible : " + (resultat.donnees.erreur || "erreur"), true);
          return;
        }
        afficherEtat("Tout est remis aux valeurs de départ ✓", false);
        recharger();
      })
      .catch(function (erreur) {
        afficherEtat("Échec : " + erreur.message, true);
      });
  }

  /* ----------------------------------------------------- boutons ↺ (valeur de départ) */

  function reinitialiserChamp(racine, nom) {
    var champ = racine.querySelector('[data-param="' + nom + '"]');
    if (!champ) {
      return;
    }
    ecrireChamp(champ, JSON.parse(champ.getAttribute("data-defaut")));
    champ.setAttribute("data-modifie", "1");
  }

  function reinitialiserRang(racine, code) {
    var palier = racine.querySelector('.palier[data-palier="' + code + '"]');
    if (!palier) {
      return;
    }
    var depart = JSON.parse(palier.getAttribute("data-defaut-theme"));
    champRang(palier, "motif").value = depart.motif;
    champRang(palier, "reflet").value = depart.reflet;
    champRang(palier, "c1").value = depart.couleurs[0];
    champRang(palier, "c2").value = depart.couleurs[1];
    champRang(palier, "c3").value = depart.couleurs[2];
    var champSymbole = champRang(palier, "symbole");
    if (champSymbole && palier.hasAttribute("data-defaut-symbole")) {
      champSymbole.value = palier.getAttribute("data-defaut-symbole");
    }
    var champNom = champRang(palier, "nom");
    if (champNom && palier.hasAttribute("data-defaut-nom")) {     /* palier des cartes personnalisées */
      champNom.value = palier.getAttribute("data-defaut-nom");
    }
    appliquerAuPalier(palier);
  }

  /* ------------------------------------------- réserve de cartes (pré-chargement) */

  /* « 45 s », « 12 min », « 3 h 05 » (même règle que reserve.duree_lisible en Python) */
  function dureeLisible(secondes) {
    secondes = Math.max(0, Math.floor(secondes));
    if (secondes < 90) {
      return secondes + " s";
    }
    if (secondes < 5400) {
      return Math.round(secondes / 60) + " min";
    }
    var minutes = Math.round((secondes % 3600) / 60);
    return Math.floor(secondes / 3600) + " h " + (minutes < 10 ? "0" : "") + minutes;
  }

  /* Ce que fait le pré-chargement (même texte que reserve.texte_statut en Python) */
  function texteStatutReserve(e) {
    if (!e.actif) {
      return "Désactivé : les paquets sont tirés à l'ouverture.";
    }
    if (e.en_cours) {
      return "Préparation de cartes en cours…";
    }
    if (e.pause > 0) {
      return "En pause : Wikipédia a ralenti ou n'a pas répondu, reprise dans " +
        dureeLisible(e.pause) + " (échec n° " + e.echecs + ").";
    }
    if (e.budget_attente > 0) {
      return "Plafond horaire atteint : reprise dans " + dureeLisible(e.budget_attente) + ".";
    }
    if (e.pretes >= e.cible) {
      return "Réserve pleine.";
    }
    if (e.pretes >= e.seuil) {
      return "Au repos : la réserve est suffisante (elle sera complétée sous le seuil bas).";
    }
    if (!e.fil_actif) {
      return "Le pré-chargement démarre avec le serveur local (python main.py).";
    }
    return "En attente : un remplissage va démarrer.";
  }

  function texteDe(id, texte) {
    var element = document.getElementById(id);
    if (element) {
      element.textContent = texte;
    }
  }

  /* Met à jour le panneau d'état de la réserve avec ce que renvoie le serveur. */
  function majReserve(e) {
    texteDe("reserve-pretes", String(e.pretes));
    texteDe("reserve-cible", String(e.cible));
    texteDe("reserve-paquets", String(e.paquets_prets));
    texteDe("reserve-statut", texteStatutReserve(e));
    texteDe("reserve-budget", e.budget_utilise + " / " + e.budget_max);
    if (e.stats) {                                    /* statistiques des cartes (langues, liens...) */
      texteDe("stats-restantes", String(e.stats.restantes));
      texteDe("stats-budget", e.stats.budget_utilise + " / " + e.stats.budget_max);
    }
    texteDe("reserve-remplissage", e.dernier_remplissage
      ? new Date(e.dernier_remplissage * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })
      : "jamais");
    var erreur = document.getElementById("reserve-erreur");
    if (erreur) {
      erreur.hidden = !e.derniere_erreur;
      texteDe("reserve-erreur-texte", e.derniere_erreur || "");
    }
    var jauge = document.getElementById("reserve-jauge");
    if (jauge && jauge.style) {
      jauge.style.transform = "scaleX(" + Math.min(1, e.pretes / Math.max(1, e.cible)).toFixed(3) + ")";
    }
    var zone = document.getElementById("reserve-jauge-zone");
    if (zone) {
      zone.setAttribute("aria-valuenow", String(e.pretes));
      zone.setAttribute("aria-valuemax", String(e.cible));
    }
  }

  function demanderReserve(methode, chemin) {
    var options = { method: methode, headers: { "X-Jeton": jeton } };
    return fetch(chemin, options)
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

  function rafraichirReserve() {
    if (!surServeur()) {
      return Promise.resolve();
    }
    return demanderReserve("GET", "/api/reserve")
      .then(majReserve)
      .catch(function () {
        /* le serveur est peut-être arrêté : on réessaiera au prochain tour */
      });
  }

  function actionReserve(chemin) {
    if (!surServeur()) {
      afficherEtat("La réserve nécessite le serveur local (python main.py).", true);
      return Promise.resolve();
    }
    return demanderReserve("POST", chemin)
      .then(function (donnees) {
        majReserve(donnees);
        return donnees;
      })
      .catch(function (erreur) {
        afficherEtat("Réserve : " + erreur.message, true);
      });
  }

  var minuteurViderReserve = null;

  /* « Vider la réserve » : un 1er clic demande confirmation, un 2e clic (4 s) exécute. */
  function viderReserve(bouton) {
    if (minuteurViderReserve === null) {
      bouton.textContent = "Confirmer : vider la réserve ?";
      minuteurViderReserve = setTimeout(function () {
        minuteurViderReserve = null;
        bouton.textContent = "Vider la réserve";
      }, 4000);
      return Promise.resolve();
    }
    clearTimeout(minuteurViderReserve);
    minuteurViderReserve = null;
    bouton.textContent = "Vider la réserve";
    return actionReserve("/api/reserve/vider");
  }

  /* ------------------------------------------------- thème du site : aperçu en direct */

  /* Applique le thème choisi à la page (rien n'est enregistré avant « Enregistrer »). */
  function appliquerThemeSite(valeur) {
    document.documentElement.setAttribute("data-theme", valeur);
    document.querySelectorAll("[data-theme-choix]").forEach(function (bouton) {
      bouton.setAttribute(
        "aria-pressed", bouton.getAttribute("data-theme-choix") === valeur ? "true" : "false"
      );
    });
  }

  function appliquerAccentTheme(actif) {
    document.documentElement.setAttribute("data-accent", actif ? "theme" : "perso");
  }


  /* ----------------------------------- menu « Aller à », section visible et bouton « Remonter » */

  function initialiserNavigation() {
    var nav = document.getElementById("config-nav");
    var liens = nav ? Array.prototype.slice.call(nav.querySelectorAll("a[data-section]")) : [];
    var reduit = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* Les sections s'arrêtent sous le menu collant, quelle que soit sa hauteur (plus il y a de sections, plus il passe de lignes). */
    function mesurerMenu() {
      if (nav) {
        document.documentElement.style.setProperty("--nav-hauteur", (nav.offsetHeight + 24) + "px");
      }
    }
    mesurerMenu();
    window.addEventListener("resize", mesurerMenu);

    function marquer(code) {
      liens.forEach(function (lien) {
        if (lien.getAttribute("data-section") === code) {
          lien.setAttribute("aria-current", "true");
          /* sur téléphone le menu défile de côté : on garde le lien actif visible */
          if (nav.scrollWidth > nav.clientWidth + 2 && lien.scrollIntoView) {
            nav.scrollLeft = Math.max(0, lien.offsetLeft - 40);
          }
        } else {
          lien.removeAttribute("aria-current");
        }
      });
    }

    function suivre() {
      var sections = document.querySelectorAll("#formulaire-config .panneau");
      var courante = null;
      var repere = (nav ? nav.getBoundingClientRect().bottom : 0) + 120;      /* la section dont le titre approche du menu devient la courante */
      Array.prototype.forEach.call(sections, function (section) {
        if (section.getBoundingClientRect().top <= repere) {
          courante = section.id.replace("groupe-", "");
        }
      });
      if (courante === null && sections.length) {
        courante = sections[0].id.replace("groupe-", "");
      }
      marquer(courante);
    }

    var attente = null;
    window.addEventListener("scroll", function () {
      if (attente === null) {
        attente = setTimeout(function () {
          attente = null;
          suivre();
        }, 80);
      }
    }, { passive: true });
    suivre();

    /* Un clic sur un lien : on va à la section et on y place le focus (clavier et lecteurs d'écran) */
    liens.forEach(function (lien) {
      lien.addEventListener("click", function (evenement) {
        var cible = document.getElementById("groupe-" + lien.getAttribute("data-section"));
        if (!cible) {
          return;
        }
        evenement.preventDefault();
        cible.scrollIntoView({ behavior: reduit ? "auto" : "smooth", block: "start" });
        cible.focus({ preventScroll: true });
        marquer(lien.getAttribute("data-section"));
        if (history.replaceState) {
          history.replaceState(null, "", "#" + cible.id);
        }
      });
    });

    var haut = document.getElementById("config-haut");
    if (haut) {
      haut.addEventListener("click", function () {
        window.scrollTo({ top: 0, behavior: reduit ? "auto" : "smooth" });
        var titre = document.querySelector(".page--config h1");
        if (titre) {
          titre.setAttribute("tabindex", "-1");
          titre.focus({ preventScroll: true });
        }
        if (history.replaceState) {
          history.replaceState(null, "", location.pathname + location.search);
        }
      });
    }
  }

  /* ---------------------------------------------------- booster : aperçu en direct */

  /* ----------------------------------------- disposition : maquette et aperçu en direct */

  var ATTRIBUTS_DISPOSITION = {
    MENU_POSITION: "data-menu-pos", MENU_STYLE: "data-menu", BARRE_OUTILS: "data-barre", PAQUET_POSITION: "data-paquet",
    BOOSTER_SURVOL: "data-paquet-survol", BOOSTER_REPOS: "data-paquet-repos",
    LOGO_ALIGNEMENT: "data-logo-align", TITRE_ALIGNEMENT: "data-titre-align", BIO_ALIGNEMENT: "data-bio-align", INFOS_ALIGNEMENT: "data-infos-align"
  };

  function majApercuDisposition(formulaire) {
    var maquette = document.getElementById("dispo-apercu");
    if (!maquette) {
      return;
    }
    Object.keys(ATTRIBUTS_DISPOSITION).forEach(function (nom) {
      var champ = champParam(formulaire, nom);
      if (champ) {
        maquette.setAttribute(ATTRIBUTS_DISPOSITION[nom], champ.value);
      }
    });
  }

  function champParam(racine, nom) {
    return racine.querySelector('[data-param="' + nom + '"]');
  }

  /* Même règle que wikicartes/booster.py (classe_texte) : taille du texte selon sa longueur. */
  function classeTexteBooster(texte) {
    var longueur = Array.from(texte).length;
    if (longueur <= 8) {
      return "booster__texte--xl";
    }
    if (longueur <= 16) {
      return "booster__texte--l";
    }
    return longueur <= 28 ? "booster__texte--m" : "booster__texte--s";
  }

  function afficherTexteBooster(apercu, afficher) {
    var image = apercu.querySelector("[data-booster-logo]");
    var texte = apercu.querySelector("[data-booster-texte]");
    if (image) {
      image.hidden = afficher;
    }
    if (texte) {
      texte.hidden = !afficher;
    }
  }

  /* Style, animation et texte du booster, tels que choisis dans le formulaire. */
  function majApercuBooster(racine) {
    var apercu = document.getElementById("booster-apercu");
    if (!apercu) {
      return;
    }
    var theme = champParam(racine, "BOOSTER_THEME");
    var sachet = apercu.querySelector('.paquet__corps[data-variante="classique"] .booster');
    var classique = apercu.querySelector('.paquet__corps[data-variante="classique"]');
    var personnalise = apercu.querySelector('.paquet__corps[data-variante="image"]');
    var champImage = champParam(racine, "BOOSTER_IMAGE");
    var imageChoisie = theme && theme.value === "image" && champImage && champImage.value !== "";
    if (theme && sachet && theme.value !== "image") {
      sachet.setAttribute("data-booster", theme.value);
    }
    if (classique) {
      classique.hidden = !!imageChoisie;
    }
    if (personnalise) {
      personnalise.hidden = !imageChoisie;
      var forme = champParam(racine, "BOOSTER_FORME");
      var cadrage = champParam(racine, "BOOSTER_AJUSTEMENT");
      var contenu = champParam(racine, "BOOSTER_IMAGE_CONTENU");
      if (forme) {
        personnalise.setAttribute("data-forme", forme.value);
      }
      if (cadrage) {
        personnalise.setAttribute("data-ajustement", cadrage.value);
      }
      var fond = personnalise.querySelector("[data-booster-fond]");
      if (fond && champImage && champImage.value && fond.getAttribute("src") !== champImage.value) {
        fond.setAttribute("src", champImage.value);
      }
      var logoImage = personnalise.querySelector("[data-booster-logo-image]");
      var texteImage = personnalise.querySelector("[data-booster-texte-image]");
      if (logoImage) {
        logoImage.hidden = !(contenu && contenu.value === "logo");
      }
      if (texteImage) {
        texteImage.hidden = !(contenu && contenu.value === "texte");
      }
    }
    var animation = champParam(racine, "BOOSTER_ANIMATION");
    var paquet = document.getElementById("booster-apercu-paquet");
    if (animation && paquet) {
      paquet.setAttribute("data-animation", animation.value);
    }
    var champTexte = champParam(racine, "BOOSTER_TEXTE");
    apercu.querySelectorAll("[data-booster-texte], [data-booster-texte-image]").forEach(function (texte) {
      if (champTexte) {
        var valeur = champTexte.value.trim() || "…";
        texte.textContent = valeur;
        texte.className = "booster__texte " + classeTexteBooster(valeur);
      }
    });
    /* Les réglages « forme, cadrage, contenu » ne servent qu'avec l'image personnalisée */
    ["BOOSTER_FORME", "BOOSTER_AJUSTEMENT", "BOOSTER_IMAGE_CONTENU"].forEach(function (nom) {
      var champ = champParam(racine, nom);
      var ligne = champ && champ.closest ? champ.closest(".champ") : null;
      if (ligne) {
        ligne.classList.toggle("champ--attenue", !(theme && theme.value === "image"));
      }
    });
  }

  /* Téléverser, remplacer ou retirer l'image du paquet : envoyée au serveur (réduite et vérifiée), l'adresse reçue est mise
     dans le champ caché BOOSTER_IMAGE, le style « Image personnalisée » est choisi, et l'aperçu se met à jour. */
  function initialiserTeleversementPaquet(racine) {
    var fichier = document.getElementById("paquet-image-fichier");
    var retirer = document.getElementById("paquet-image-retirer");
    var etat = document.getElementById("paquet-image-etat");
    var champImage = champParam(racine, "BOOSTER_IMAGE");
    var theme = champParam(racine, "BOOSTER_THEME");
    if (!fichier || !champImage) {
      return;
    }
    function dire(texte, erreur) {
      etat.textContent = texte || "";
      etat.classList.toggle("booster-televersement__etat--erreur", !!erreur);
    }
    fichier.addEventListener("change", function () {
      var choisi = fichier.files && fichier.files[0];
      if (!choisi) {
        return;
      }
      if (choisi.type !== "image/png" && choisi.type !== "image/jpeg") {
        dire("Format non accepté : PNG ou JPEG seulement.", true);
        fichier.value = "";
        return;
      }
      if (choisi.size > 5 * 1024 * 1024) {
        dire("Image trop lourde (5 Mo au maximum).", true);
        fichier.value = "";
        return;
      }
      if (!surServeur()) {
        dire("Le téléversement nécessite le serveur local (python main.py).", true);
        return;
      }
      dire("Envoi de l'image…", false);
      fetch("/api/booster/image", {
        method: "POST",
        headers: { "Content-Type": choisi.type, "X-Jeton": document.body.getAttribute("data-jeton") },
        body: choisi
      }).then(function (reponse) {
        return reponse.json().then(function (donnees) {
          if (!reponse.ok) {
            throw new Error(donnees.erreur || "erreur du serveur");
          }
          return donnees;
        });
      }).then(function (donnees) {
        champImage.value = donnees.url;
        var corps = document.querySelector('#booster-apercu .paquet__corps[data-variante="image"]');
        if (corps) {
          corps.style.setProperty("--ratio", String(donnees.ratio));
        }
        if (theme) {
          theme.value = "image";
        }
        if (retirer) {
          retirer.hidden = false;
        }
        majApercuBooster(racine);
        dire("Image prête (" + donnees.largeur + " × " + donnees.hauteur + " px" + (donnees.reduite ? ", réduite" : "") +
          ") : clique sur « Enregistrer » pour la garder.", false);
      }).catch(function (erreur) {
        dire("Image refusée : " + erreur.message, true);
      }).then(function () {
        fichier.value = "";
      });
    });
    if (retirer) {
      retirer.addEventListener("click", function () {
        champImage.value = "";
        if (theme && theme.value === "image") {
          theme.value = "classique";
        }
        retirer.hidden = true;
        majApercuBooster(racine);
        dire("Image retirée : clique sur « Enregistrer » pour confirmer.", false);
      });
    }
  }

  /* Le logo choisi (même avant l'enregistrement) ; sans logo, le texte du booster s'affiche. */
  function majLogoApercu(racine) {
    var apercu = document.getElementById("booster-apercu");
    var champ = champParam(racine, "LOGO_FICHIER");
    var image = apercu ? apercu.querySelector("[data-booster-logo]") : null;
    if (!apercu || !champ || !image) {
      return;
    }
    if (champ.value === "aucun") {
      afficherTexteBooster(apercu, true);
      return;
    }
    image.onload = function () {
      afficherTexteBooster(apercu, false);
    };
    image.onerror = function () {
      afficherTexteBooster(apercu, true);       /* pas de logo : le texte prend la place */
    };
    image.setAttribute("src", "/logo?fichier=" + encodeURIComponent(champ.value));
  }

  /* Joue l'animation choisie sur l'aperçu : attente, sortie, disparition, retour. */
  var testEnCours = false;

  function testerAnimation() {
    var apercu = document.getElementById("booster-apercu");
    var paquet = document.getElementById("booster-apercu-paquet");
    if (!apercu || !paquet || testEnCours) {
      return;
    }
    var table = {};
    try {
      table = JSON.parse(apercu.getAttribute("data-animations") || "{}");
    } catch (erreur) {
      table = {};
    }
    var duree = table[paquet.getAttribute("data-animation")] || {};
    var attente = (Number(duree.attente) || 0) + 300;     /* on laisse voir le mouvement d'attente */
    var sortie = Number(duree.sortie) || 0;
    var retour = Number(duree.retour) || 350;
    testEnCours = true;
    paquet.classList.add("paquet--attente");
    setTimeout(function () {
      paquet.classList.remove("paquet--attente");
      paquet.classList.add("paquet--sortie");
      lancerConfettisApercu(paquet);                  /* confettis, étincelles... de l'animation choisie */
      setTimeout(function () {
        paquet.classList.remove("paquet--sortie");
        paquet.classList.add("paquet--cache");
        setTimeout(function () {
          paquet.classList.remove("paquet--cache");
          paquet.classList.add("paquet--retour");
          setTimeout(function () {
            paquet.classList.remove("paquet--retour");
            testEnCours = false;
          }, retour);
        }, 250);
      }, sortie);
    }, attente);
  }

  /* Les confettis de l'animation d'ouverture, dans l'aperçu : même principe que sur la page de la collection */
  function lancerConfettisApercu(paquet) {
    var couche = paquet.querySelector(".paquet__particules");
    if (!couche || (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) {
      return;
    }
    var corps = Array.prototype.slice.call(paquet.querySelectorAll(".paquet__corps")).filter(function (c) {
      return !c.hidden;
    })[0];
    if (corps) {
      var r = corps.getBoundingClientRect();
      var p = paquet.getBoundingClientRect();
      couche.style.setProperty("--cx", (r.left + r.width / 2 - p.left).toFixed(1) + "px");
      couche.style.setProperty("--cy", (r.top + r.height / 2 - p.top).toFixed(1) + "px");
    }
    paquet.classList.remove("paquet--confettis");
    void paquet.offsetWidth;
    paquet.classList.add("paquet--confettis");
    setTimeout(function () {
      paquet.classList.remove("paquet--confettis");
    }, 1700);
  }

  /* ------------------------------------------------------------ sons et musique */

  function initialiserSons(racine) {
    var zone = document.getElementById("sons");
    if (!zone) {
      return;
    }
    var etat = document.getElementById("sons-etat");
    var liste = document.getElementById("sons-liste");
    var champFichier = document.getElementById("son-fichier");
    var jeton = document.body.getAttribute("data-jeton") || "";
    var enCours = null;                      /* { bouton, audio } : l'essai en train de jouer */

    function dire(texte, erreur) {
      etat.textContent = texte || "";
      etat.classList.toggle("sons__etat--erreur", !!erreur);
    }

    function selectsSons() {
      return Array.prototype.slice.call(racine.querySelectorAll('select[data-type="son"]'));
    }

    function arreterEssai() {
      if (enCours) {
        try { enCours.audio.pause(); } catch (e) { /* sans importance */ }
        enCours.bouton.textContent = "▶";
        enCours.bouton.classList.remove("bouton-son-essai--joue");
        enCours = null;
      }
    }

    function essayer(bouton, nom, volume) {
      var etaitCe = enCours && enCours.bouton === bouton;
      arreterEssai();
      if (etaitCe || !nom || !window.WikiSons) {
        return;
      }
      var audio = window.WikiSons.jouerFichier(nom, volume);
      if (!audio) {
        return;
      }
      enCours = { bouton: bouton, audio: audio };
      bouton.textContent = "■";
      bouton.classList.add("bouton-son-essai--joue");
      audio.addEventListener("ended", function () {
        if (enCours && enCours.audio === audio) {
          arreterEssai();
        }
      });
    }

    function valeurChamp(nom, defaut) {
      var champ = champParam(racine, nom);
      if (!champ) {
        return defaut;
      }
      return champ.getAttribute("data-type") === "bool" ? !!champ.checked : champ.value;
    }

    /* Reconstruit la liste des fichiers et les listes déroulantes de chaque événement (la sélection est conservée). */
    function majListes(noms) {
      selectsSons().forEach(function (sel) {
        var courant = sel.value;
        sel.textContent = "";
        var aucun = document.createElement("option");
        aucun.value = "";
        aucun.textContent = "(aucun son)";
        sel.appendChild(aucun);
        noms.forEach(function (nom) {
          var o = document.createElement("option");
          o.value = nom;
          o.textContent = nom;
          sel.appendChild(o);
        });
        sel.value = noms.indexOf(courant) !== -1 ? courant : "";
      });
      liste.textContent = "";
      if (!noms.length) {
        var vide = document.createElement("li");
        vide.className = "sons__vide";
        vide.textContent = "Aucun fichier son pour l'instant.";
        liste.appendChild(vide);
      }
      noms.forEach(function (nom) {
        var li = document.createElement("li");
        li.className = "sons__ligne";
        li.setAttribute("data-nom", nom);
        var n = document.createElement("span");
        n.className = "sons__nom";
        n.textContent = nom;
        var ecouter = document.createElement("button");
        ecouter.type = "button";
        ecouter.className = "bouton-son-essai";
        ecouter.setAttribute("data-fichier", nom);
        ecouter.setAttribute("aria-label", "Écouter " + nom);
        ecouter.title = "Écouter";
        ecouter.textContent = "▶";
        var sup = document.createElement("button");
        sup.type = "button";
        sup.className = "bouton-site sons__supprimer";
        sup.setAttribute("data-supprimer", nom);
        sup.textContent = "Supprimer";
        li.appendChild(n);
        li.appendChild(ecouter);
        li.appendChild(sup);
        liste.appendChild(li);
      });
    }

    function envoyerFichier(fichier) {
      if (fichier.size > 60 * 1024 * 1024) {
        return Promise.reject(new Error(fichier.name + " : trop lourd (60 Mo au maximum)"));
      }
      return fetch("/api/sons/televerser?nom=" + encodeURIComponent(fichier.name), {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream", "X-Jeton": jeton },
        body: fichier
      }).catch(function () {
        throw new Error("le serveur local est injoignable");
      }).then(function (reponse) {
        return reponse.json().then(function (donnees) {
          if (!reponse.ok) {
            throw new Error(fichier.name + " : " + (donnees.erreur || "refusé"));
          }
          return donnees;
        });
      });
    }

    if (champFichier) {
      champFichier.addEventListener("change", function () {
        var fichiers = Array.prototype.slice.call(champFichier.files || []);
        if (!fichiers.length) {
          return;
        }
        if (!surServeur()) {
          dire("Le téléversement nécessite le serveur local (python main.py).", true);
          return;
        }
        dire("Envoi…", false);
        var recus = [];
        var erreurs = [];
        var suite = Promise.resolve();
        fichiers.forEach(function (fichier) {
          suite = suite.then(function () {
            return envoyerFichier(fichier).then(function (donnees) {
              recus.push(donnees.nom);
              majListes(donnees.sons);
            }).catch(function (erreur) {
              erreurs.push(erreur.message);
            });
          });
        });
        suite.then(function () {
          champFichier.value = "";
          if (erreurs.length) {
            dire((recus.length ? recus.length + " son(s) ajouté(s). " : "") + "Refusé : " + erreurs.join(" ; "), true);
          } else {
            dire(recus.length + (recus.length > 1 ? " sons ajoutés" : " son ajouté") + " : choisis-le pour un événement, puis « Enregistrer ».", false);
          }
        });
      });
    }

    zone.addEventListener("click", function (evenement) {
      var cible = evenement.target;
      var ecouter = cible && cible.closest ? cible.closest("[data-fichier]") : null;
      if (ecouter) {
        essayer(ecouter, ecouter.getAttribute("data-fichier"), valeurChamp("SONS_VOLUME", 70));
        return;
      }
      var supprimer = cible && cible.closest ? cible.closest("[data-supprimer]") : null;
      if (supprimer) {
        var nom = supprimer.getAttribute("data-supprimer");
        fetch("/api/sons/supprimer", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Jeton": jeton },
          body: JSON.stringify({ nom: nom })
        }).then(function (reponse) {
          return reponse.json().then(function (donnees) {
            if (!reponse.ok) {
              throw new Error(donnees.erreur || "refusé");
            }
            return donnees;
          });
        }).then(function (donnees) {
          arreterEssai();
          var servait = selectsSons().some(function (sel) { return sel.value === nom; });
          majListes(donnees.sons);
          dire("« " + nom + " » supprimé." + (servait ? " Il n'est plus choisi : clique sur « Enregistrer »." : ""), false);
        }).catch(function (erreur) {
          dire("Suppression impossible : " + erreur.message, true);
        });
      }
    });

    /* Les boutons ▶ à côté de chaque liste : on écoute le fichier choisi, à son volume */
    racine.addEventListener("click", function (evenement) {
      var cible = evenement.target;
      var bouton = cible && cible.closest ? cible.closest("[data-essai]") : null;
      if (!bouton) {
        return;
      }
      var param = bouton.getAttribute("data-essai");
      var champ = champParam(racine, param);
      var volume = param === "MUSIQUE_FICHIER" ? valeurChamp("MUSIQUE_VOLUME", 40) : valeurChamp("SONS_VOLUME", 70);
      essayer(bouton, champ ? champ.value : "", volume);
    });
  }

  /* Les réglages de sons tels qu'ils sont dans le formulaire (pour les appliquer tout de suite après « Enregistrer ») */
  function reglagesSonsDuFormulaire(racine) {
    function champ(nom) {
      return champParam(racine, nom);
    }
    var EVENEMENTS = {
      SON_EFFET_PAQUET: "effet", SON_OUVERTURE: "ouverture", SON_CARTE_FENETRE: "carte", SON_ARRIVEE: "arrivee",
      SON_CORBEILLE: "corbeille", SON_RESTAURATION: "restauration", SON_SUPPRESSION: "suppression"
    };
    var evenements = {};
    Object.keys(EVENEMENTS).forEach(function (nom) {
      var c = champ(nom);
      if (c && c.value) {
        evenements[EVENEMENTS[nom]] = c.value;
      }
    });
    var actifs = champ("SONS_ACTIFS");
    var volume = champ("SONS_VOLUME");
    var boucleEffet = champ("SON_EFFET_PAQUET_BOUCLE");
    var musiqueActive = champ("MUSIQUE_ACTIVE");
    var fichier = champ("MUSIQUE_FICHIER");
    var volumeMusique = champ("MUSIQUE_VOLUME");
    var coupeeChamp = champ("MUSIQUE_COUPEE");
    var avant = (window.WikiSons && window.WikiSons.reglages().musique) || {};
    /* volume et haut-parleur : la valeur du formulaire seulement si on l'a changée ici (sinon celle de la page en cours) */
    var volumeFinal = volumeMusique && volumeMusique.getAttribute("data-modifie") === "1" ? Number(volumeMusique.value) || 0
      : (typeof avant.volume === "number" ? avant.volume : (volumeMusique ? Number(volumeMusique.value) || 0 : 40));
    var coupeeFinal = coupeeChamp && coupeeChamp.getAttribute("data-modifie") === "1" ? !!coupeeChamp.checked : !!avant.coupee;
    return {
      actifs: actifs ? !!actifs.checked : true,
      volume: volume ? Number(volume.value) || 0 : 70,
      evenements: evenements,
      boucles: { effet: boucleEffet ? !!boucleEffet.checked : false },
      musique: {
        actif: !!(musiqueActive && musiqueActive.checked && fichier && fichier.value),
        fichier: fichier ? fichier.value : "",
        volume: volumeFinal,
        coupee: coupeeFinal
      }
    };
  }

  /* ------------------------------------------------------------ sauvegardes (section Système) */

  function initialiserSauvegardes() {
    var zone = document.getElementById("sauvegardes");
    if (!zone) {
      return;
    }
    var liste = document.getElementById("sauvegardes-liste");
    var etat = document.getElementById("sauvegardes-etat");
    var confirmation = document.getElementById("sauvegarde-confirmation");
    var texteConfirmation = document.getElementById("sauvegarde-confirmation-texte");
    var boutonConfirmer = document.getElementById("sauvegarde-confirmer");
    var boutonAnnuler = document.getElementById("sauvegarde-annuler");
    var boutonCreer = document.getElementById("sauvegarde-creer");
    var champFichier = document.getElementById("sauvegarde-fichier");
    var ligneCle = document.getElementById("sauvegarde-cle-ligne");
    var caseCle = document.getElementById("sauvegarde-cle");
    var jeton = document.body.getAttribute("data-jeton") || "";
    var enAttente = null;                     /* { genre: "restaurer" | "supprimer", sauvegarde } pendant la confirmation */
    var occupe = false;

    var REMPLACE = {
      ultra: "tes paramètres actuels et toute ta collection (les fichiers du programme ne sont PAS écrasés : ils sont " +
        "extraits dans data/restaurations/)",
      complete: "tes paramètres actuels et toute ta collection",
      parametres: "tous tes paramètres actuels",
      collection: "toute ta collection (cartes, catégories, vitrines, corbeille, réserve, annuaire du Hall)"
    };

    function dire(texte, erreur) {
      etat.textContent = texte || "";
      etat.classList.toggle("sauvegardes__etat--erreur", !!erreur);
    }

    function taille(octets) {
      if (octets >= 1024 * 1024 * 1024) { return (octets / 1024 / 1024 / 1024).toFixed(1) + " Go"; }
      if (octets >= 1024 * 1024) { return (octets / 1024 / 1024).toFixed(1) + " Mo"; }
      return Math.max(1, Math.round(octets / 1024)) + " Ko";
    }

    function dateLisible(iso) {
      var d = new Date(iso);
      return isNaN(d.getTime()) ? String(iso || "") : d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
    }

    function appeler(methode, chemin, corps, typeContenu) {
      var entetes = { "X-Jeton": jeton };
      var options = { method: methode, headers: entetes };
      if (corps !== undefined) {
        if (typeContenu) {
          entetes["Content-Type"] = typeContenu;
          options.body = corps;
        } else {
          entetes["Content-Type"] = "application/json";
          options.body = JSON.stringify(corps);
        }
      }
      return fetch(chemin, options).catch(function () {
        throw new Error("le serveur local est injoignable");
      }).then(function (reponse) {
        return reponse.json().then(function (donnees) {
          if (!reponse.ok) {
            throw new Error(donnees.erreur || "erreur du serveur");
          }
          return donnees;
        });
      });
    }

    function occuper(valeur) {
      occupe = valeur;
      boutonCreer.disabled = valeur;
      Array.prototype.forEach.call(zone.querySelectorAll(".sauvegarde button"), function (b) { b.disabled = valeur; });
    }

    function demanderConfirmation(genre, sauvegarde) {
      enAttente = { genre: genre, sauvegarde: sauvegarde };
      var nom = (sauvegarde.libelle || "Sauvegarde") + " du " + dateLisible(sauvegarde.cree_le) +
        (sauvegarde.nb_cartes !== null && sauvegarde.nb_cartes !== undefined ? " (" + sauvegarde.nb_cartes + " cartes)" : "");
      if (genre === "restaurer") {
        texteConfirmation.textContent = "Restaurer « " + nom + " » ? Cela remplace " + (REMPLACE[sauvegarde.type] || "ce que contient la sauvegarde") +
          ". Ton état actuel est d'abord sauvegardé automatiquement (« avant-restauration »).";
        boutonConfirmer.textContent = "Restaurer";
      } else {
        texteConfirmation.textContent = "Supprimer définitivement le fichier « " + sauvegarde.nom + " » ?";
        boutonConfirmer.textContent = "Supprimer";
      }
      confirmation.hidden = false;
      boutonConfirmer.focus();
    }

    function fermerConfirmation() {
      confirmation.hidden = true;
      enAttente = null;
    }

    function ligne(sauvegarde) {
      var li = document.createElement("li");
      li.className = "sauvegarde" + (sauvegarde.invalide ? " sauvegarde--invalide" : "");
      var infos = document.createElement("div");
      infos.className = "sauvegarde__infos";
      var titre = document.createElement("strong");
      titre.textContent = sauvegarde.libelle + (sauvegarde.avant_restauration ? " · avant restauration" : "");
      var detail = document.createElement("small");
      detail.textContent = sauvegarde.invalide
        ? "Illisible : " + (sauvegarde.erreur || "fichier abîmé")
        : dateLisible(sauvegarde.cree_le) + " · " + taille(sauvegarde.taille) +
          (sauvegarde.nb_cartes !== null && sauvegarde.nb_cartes !== undefined ? " · " + sauvegarde.nb_cartes + " cartes" : "") +
          (sauvegarde.cle_identite ? " · contient la clé d'identité" : "");
      var nom = document.createElement("code");
      nom.textContent = sauvegarde.nom;
      infos.appendChild(titre);
      infos.appendChild(detail);
      infos.appendChild(nom);
      var actions = document.createElement("div");
      actions.className = "sauvegarde__actions";
      if (!sauvegarde.invalide) {
        var exporter = document.createElement("a");
        exporter.className = "bouton-site";
        exporter.textContent = "Exporter";
        exporter.href = "/sauvegardes/telecharger?nom=" + encodeURIComponent(sauvegarde.nom) + "&jeton=" + encodeURIComponent(jeton);
        exporter.setAttribute("download", sauvegarde.nom);
        actions.appendChild(exporter);
        var restaurer = document.createElement("button");
        restaurer.type = "button";
        restaurer.className = "bouton-site";
        restaurer.textContent = "Restaurer…";
        restaurer.addEventListener("click", function () { demanderConfirmation("restaurer", sauvegarde); });
        actions.appendChild(restaurer);
      }
      var supprimer = document.createElement("button");
      supprimer.type = "button";
      supprimer.className = "bouton-site";
      supprimer.textContent = "Supprimer…";
      supprimer.addEventListener("click", function () { demanderConfirmation("supprimer", sauvegarde); });
      actions.appendChild(supprimer);
      li.appendChild(infos);
      li.appendChild(actions);
      return li;
    }

    function actualiser() {
      return appeler("GET", "/api/sauvegardes").then(function (donnees) {
        liste.textContent = "";
        if (!donnees.sauvegardes.length) {
          var vide = document.createElement("li");
          vide.className = "sauvegardes__vide";
          vide.textContent = "Aucune sauvegarde pour l'instant.";
          liste.appendChild(vide);
        }
        donnees.sauvegardes.forEach(function (s) { liste.appendChild(ligne(s)); });
      }).catch(function (erreur) {
        liste.textContent = "";
        dire("Liste impossible : " + erreur.message, true);
      });
    }

    function typeChoisi() {
      var coche = zone.querySelector('input[name="sauvegarde-type"]:checked');
      return coche ? coche.value : "complete";
    }

    Array.prototype.forEach.call(zone.querySelectorAll('input[name="sauvegarde-type"]'), function (radio) {
      radio.addEventListener("change", function () {
        ligneCle.hidden = typeChoisi() !== "ultra";             /* la clé n'est proposée que pour l'ultra complète */
        if (ligneCle.hidden) { caseCle.checked = false; }
      });
    });

    boutonCreer.addEventListener("click", function () {
      if (occupe) { return; }
      var type = typeChoisi();
      occuper(true);
      dire(type === "ultra" ? "Création de la sauvegarde… (une ultra complète peut prendre un moment)" : "Création de la sauvegarde…", false);
      appeler("POST", "/api/sauvegardes/creer", { type: type, avec_cle: type === "ultra" && caseCle.checked }).then(function (donnees) {
        var s = donnees.sauvegarde;
        dire("Sauvegarde créée : " + s.libelle + ", " + taille(s.taille) + " (" + s.nom + ").", false);
        caseCle.checked = false;
        return actualiser();
      }).catch(function (erreur) {
        dire("Sauvegarde impossible : " + erreur.message, true);
      }).then(function () { occuper(false); });
    });

    champFichier.addEventListener("change", function () {
      var fichier = champFichier.files && champFichier.files[0];
      if (!fichier || occupe) { return; }
      if (fichier.size > 4 * 1024 * 1024 * 1024) {
        dire("Fichier trop gros (4 Go au maximum).", true);
        champFichier.value = "";
        return;
      }
      occuper(true);
      dire("Envoi et vérification de « " + fichier.name + " » (" + taille(fichier.size) + ")…", false);
      appeler("POST", "/api/sauvegardes/importer", fichier, "application/zip").then(function (donnees) {
        dire("Sauvegarde importée et vérifiée : rien n'est encore changé.", false);
        return actualiser().then(function () { demanderConfirmation("restaurer", donnees.sauvegarde); });
      }).catch(function (erreur) {
        dire("Import refusé : " + erreur.message, true);
      }).then(function () {
        champFichier.value = "";
        occuper(false);
      });
    });

    boutonAnnuler.addEventListener("click", fermerConfirmation);
    boutonConfirmer.addEventListener("click", function () {
      if (!enAttente || occupe) { return; }
      var action = enAttente;
      fermerConfirmation();
      occuper(true);
      if (action.genre === "supprimer") {
        dire("Suppression…", false);
        appeler("POST", "/api/sauvegardes/supprimer", { nom: action.sauvegarde.nom }).then(function () {
          dire("Sauvegarde supprimée.", false);
          return actualiser();
        }).catch(function (erreur) {
          dire("Suppression impossible : " + erreur.message, true);
        }).then(function () { occuper(false); });
        return;
      }
      dire("Restauration en cours… (ne ferme pas la page)", false);
      appeler("POST", "/api/sauvegardes/restaurer", { nom: action.sauvegarde.nom, confirmation: true }).then(function (donnees) {
        var r = donnees.resume;
        var texte = "Restauration terminée (" + r.libelle + ") : " + r.nb_cartes + " cartes";
        if (r.parametres) { texte += ", " + r.parametres + " paramètres appliqués"; }
        if (r.parametres_ignores && r.parametres_ignores.length) { texte += " (ignorés : " + r.parametres_ignores.join(", ") + ")"; }
        texte += ". État d'avant sauvegardé dans « " + r.securite + " ».";
        if (r.programme) { texte += " Fichiers du programme extraits dans " + r.programme + "."; }
        try { sessionStorage.setItem("sauvegardeMessage", texte); } catch (e) { /* sans importance */ }
        window.location.reload();                      /* la page affiche maintenant les paramètres restaurés */
      }).catch(function (erreur) {
        dire("Restauration impossible : " + erreur.message + " (rien n'a été remplacé par cette sauvegarde)", true);
        occuper(false);
      });
    });

    try {
      var message = sessionStorage.getItem("sauvegardeMessage");
      if (message) {
        sessionStorage.removeItem("sauvegardeMessage");
        dire(message, false);
        zone.scrollIntoView({ block: "center" });
      }
    } catch (e) { /* sans importance */ }
    actualiser();
  }

  /* ------------------------------------------------------------ mise en route */

  var formulaire = document.getElementById("formulaire-config");

  if (formulaire) {
    initialiserNavigation();
    initialiserTeleversementPaquet(formulaire);
    initialiserSauvegardes();
    initialiserSons(formulaire);
    majApercuBooster(formulaire);                    /* grise forme, cadrage et contenu tant que le style « image » n'est pas choisi */
    formulaire.querySelectorAll(".palier").forEach(appliquerAuPalier);
    mettreAJourParts(formulaire);

    formulaire.querySelectorAll(".categorie").forEach(function (bloc) {
      mettreAJourApercuCategorie(bloc, formulaire);
    });
    if (document.getElementById("reserve-etat")) {
      setInterval(rafraichirReserve, 5000);              /* l'état de la réserve se met à jour tout seul */
    }

    formulaire.addEventListener("input", function (evenement) {
      var cible = evenement.target;
      var bloc = cible.closest ? cible.closest(".categorie") : null;
      if (bloc) {
        mettreAJourApercuCategorie(bloc, formulaire);
        return;
      }
      if (cible.getAttribute && cible.getAttribute("data-param") === "CATEGORIE_LONGUEUR_MAX") {
        formulaire.querySelectorAll(".categorie").forEach(function (b) {
          mettreAJourApercuCategorie(b, formulaire);
        });
      }
      var nomParam = cible.getAttribute ? cible.getAttribute("data-param") : null;
      if (REGLES_PAR_LA_PAGE.indexOf(nomParam) !== -1) {
        cible.setAttribute("data-modifie", "1");                 /* modifiée ici : elle sera envoyée à l'enregistrement */
      }
      if (nomParam && nomParam.indexOf("BOOSTER_") === 0) {
        majApercuBooster(formulaire);
      }
      var palier = cible.closest ? cible.closest(".palier") : null;
      if (!palier) {
        return;
      }
      appliquerAuPalier(palier);
      if (cible.getAttribute("data-palier-champ") === "poids") {
        mettreAJourParts(formulaire);
      }
    });
    formulaire.addEventListener("change", function (evenement) {
      var nomParam = evenement.target.getAttribute ? evenement.target.getAttribute("data-param") : null;
      if (nomParam === "EFFET_SURVOL") {                /* aperçu en direct : survole une carte de la page */
        document.documentElement.setAttribute("data-survol", evenement.target.value);
      }
      if (nomParam === "ANIMATION_ZOOM") {              /* aperçu en direct : clique sur une carte pour l'agrandir */
        document.documentElement.setAttribute("data-anim-zoom", evenement.target.value);
      }
      if (ATTRIBUTS_DISPOSITION[nomParam]) {            /* aperçu en direct : le menu de cette page change tout de suite */
        document.documentElement.setAttribute(ATTRIBUTS_DISPOSITION[nomParam], evenement.target.value);
        majApercuDisposition(formulaire);
      }
      if (nomParam === "THEME_SITE") {
        appliquerThemeSite(evenement.target.value);
      } else if (nomParam === "ACCENT_DU_THEME") {
        appliquerAccentTheme(!!evenement.target.checked);
      }
      if (nomParam === "LOGO_FICHIER") {
        majLogoApercu(formulaire);
      } else if (nomParam && nomParam.indexOf("BOOSTER_") === 0) {
        majApercuBooster(formulaire);
      }
      var palier = evenement.target.closest ? evenement.target.closest(".palier") : null;
      if (palier) {
        appliquerAuPalier(palier);                  /* listes déroulantes : événement « change » */
      }
    });

    formulaire.addEventListener("click", function (evenement) {
      var bouton = evenement.target.closest ? evenement.target.closest("button") : null;
      if (!bouton) {
        return;
      }
      var blocCategorie = bouton.closest ? bouton.closest(".categorie") : null;
      if (bouton.hasAttribute("data-categorie-supprimer") && blocCategorie) {
        basculerSuppressionCategorie(blocCategorie, true);
      } else if (bouton.hasAttribute("data-categorie-annuler") && blocCategorie) {
        basculerSuppressionCategorie(blocCategorie, false);
      } else if (bouton.hasAttribute("data-categorie-reclasser") && blocCategorie) {
        reclasserCategorie(blocCategorie);
      } else if (bouton.id === "categorie-ajouter") {
        ajouterCategorie(formulaire);
      } else if (bouton.id === "reserve-remplir") {
        actionReserve("/api/reserve/remplir");
      } else if (bouton.id === "reserve-vider") {
        viderReserve(bouton);
      } else if (bouton.hasAttribute("data-theme-choix")) {
        var choixTheme = champParam(formulaire, "THEME_SITE");
        if (choixTheme) {                    /* la pastille choisit le thème dans la liste */
          choixTheme.value = bouton.getAttribute("data-theme-choix");
        }
        appliquerThemeSite(bouton.getAttribute("data-theme-choix"));
      } else if (bouton.id === "booster-tester") {
        testerAnimation();
      } else if (bouton.hasAttribute("data-reinit")) {
        reinitialiserChamp(formulaire, bouton.getAttribute("data-reinit"));
        majApercuBooster(formulaire);
        majLogoApercu(formulaire);
        var themeChamp = champParam(formulaire, "THEME_SITE");
        if (themeChamp) {
          appliquerThemeSite(themeChamp.value);
        }
        var survolChamp = champParam(formulaire, "EFFET_SURVOL");
        if (survolChamp) {
          document.documentElement.setAttribute("data-survol", survolChamp.value);
        }
        var zoomChamp = champParam(formulaire, "ANIMATION_ZOOM");
        if (zoomChamp) {
          document.documentElement.setAttribute("data-anim-zoom", zoomChamp.value);
        }
        Object.keys(ATTRIBUTS_DISPOSITION).forEach(function (nom) {
          var champ = champParam(formulaire, nom);
          if (champ) {
            document.documentElement.setAttribute(ATTRIBUTS_DISPOSITION[nom], champ.value);
          }
        });
        majApercuDisposition(formulaire);
        var accentChamp = champParam(formulaire, "ACCENT_DU_THEME");
        if (accentChamp) {
          appliquerAccentTheme(!!accentChamp.checked);
        }
      } else if (bouton.hasAttribute("data-palier-reinit")) {
        reinitialiserRang(formulaire, bouton.getAttribute("data-palier-reinit"));
      }
    });

    var boutonEnregistrer = document.getElementById("config-enregistrer");
    if (boutonEnregistrer) {
      boutonEnregistrer.addEventListener("click", function () {
        enregistrer(formulaire);
      });
    }
    var boutonReinit = document.getElementById("config-reinitialiser");
    if (boutonReinit) {
      boutonReinit.addEventListener("click", function () {
        reinitialiserTout(boutonReinit);
      });
    }
  }

  /* Pour les tests (Node) : les fonctions pures et la collecte des valeurs. */
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      hexVersRvb: hexVersRvb,
      luminance: luminance,
      couleurLisible: couleurLisible,
      variablesRang: variablesRang,
      collecterValeurs: collecterValeurs,
      classeTexteBooster: classeTexteBooster,
      dureeLisible: dureeLisible,
      texteStatutReserve: texteStatutReserve,
      majReserve: majReserve,
      rafraichirReserve: rafraichirReserve,
      actionReserve: actionReserve,
      viderReserve: viderReserve,
      appliquerThemeSite: appliquerThemeSite,
      appliquerAccentTheme: appliquerAccentTheme,
      majApercuBooster: majApercuBooster,
      majLogoApercu: majLogoApercu,
      testerAnimation: testerAnimation,
      collecterCategories: collecterCategories,
      tronquer: tronquer,
      mettreAJourApercuCategorie: mettreAJourApercuCategorie,
      basculerSuppressionCategorie: basculerSuppressionCategorie,
      ajouterCategorie: ajouterCategorie,
      afficherErreursCategories: afficherErreursCategories,
      reclasserCategorie: reclasserCategorie,
      appliquerAuPalier: appliquerAuPalier,
      mettreAJourParts: mettreAJourParts,
      afficherErreurs: afficherErreurs,
      effacerErreurs: effacerErreurs,
      enregistrer: enregistrer,
      reinitialiserTout: reinitialiserTout,
      reinitialiserChamp: reinitialiserChamp,
      reinitialiserRang: reinitialiserRang
    };
  }
})();
