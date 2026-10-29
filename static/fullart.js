/* Créateur de cartes → onglet « Full-art » : choisir une carte, un Zuul, un Gozer et des effets, voir l'aperçu, appliquer ou retirer.
   Les listes viennent des dossiers « zuul » et « gozer » (fichiers .png) ; le choix de la carte reprend la recherche de la page Profil
   (sans la mention « déjà en vitrine »). */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  var onglet = $("mode-fullart");
  var bloc = $("bloc-fullart");
  if (!onglet || !bloc) {
    return;
  }
  var jeton = document.body.getAttribute("data-jeton");
  var plan = $("createur-plan");
  var blocWeb = $("bloc-web");
  var valider = document.querySelector(".createur__valider");
  var onglets = [$("mode-manuel"), $("mode-web"), onglet];

  var etat = { carte: null, zuul: "", gozer: "", effets: [], effetsMax: 3, listesChargees: false, minuteur: null, version: 0 };
  var recherche = { texte: "", rangs: [], tri: "", page: 1, pages: 1, version: 0 };

  function appeler(methode, chemin, corps) {
    var options = { method: methode, headers: { "X-Jeton": jeton } };
    if (corps !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(corps);
    }
    return fetch(chemin, options).catch(function () {
      throw new Error("le serveur local est injoignable (lance python main.py)");
    }).then(function (reponse) {
      return reponse.json().then(function (donnees) {
        if (!reponse.ok) {
          throw new Error(donnees.erreur || "erreur du serveur");
        }
        return donnees;
      });
    });
  }

  function message(texte, erreur) {
    var zone = $("fa-etat");
    zone.textContent = texte || "";
    zone.classList.toggle("createur__etat--erreur", !!erreur);
  }

  /* ------------------------------------------------------------------ onglets */
  function montrer(actif) {
    onglets.forEach(function (o) { o.setAttribute("aria-selected", o === onglet ? (actif ? "true" : "false") : o.getAttribute("aria-selected")); });
    bloc.hidden = !actif;
    if (actif) {
      onglets.forEach(function (o) { if (o !== onglet) { o.setAttribute("aria-selected", "false"); } });
      plan.hidden = true;
      blocWeb.hidden = true;
      valider.hidden = true;
      charger();
    } else {
      plan.hidden = false;
      valider.hidden = false;
    }
  }
  onglet.addEventListener("click", function () { montrer(true); });
  [$("mode-manuel"), $("mode-web")].forEach(function (autre) {
    autre.addEventListener("click", function () { if (!bloc.hidden) { montrer(false); } });
  });

  /* ------------------------------------------------------------------ listes Zuul / Gozer / effets */
  function remplirListe(selecteur, noms, valeur) {
    selecteur.textContent = "";
    var aucun = document.createElement("option");
    aucun.value = "";
    aucun.textContent = "(aucun)";
    selecteur.appendChild(aucun);
    noms.forEach(function (nom) {
      var option = document.createElement("option");
      option.value = nom;
      option.textContent = nom;
      selecteur.appendChild(option);
    });
    selecteur.value = noms.indexOf(valeur) !== -1 ? valeur : "";
  }

  function charger() {
    return appeler("GET", "/api/fullart/listes").then(function (donnees) {
      etat.effetsMax = donnees.effets_max || 3;
      remplirListe($("fa-zuul"), donnees.zuul, etat.zuul);
      remplirListe($("fa-gozer"), donnees.gozer, etat.gozer);
      etat.zuul = $("fa-zuul").value;
      etat.gozer = $("fa-gozer").value;
      $("fa-dossiers-info").textContent = donnees.zuul.length + " Zuul dans le dossier « zuul », " + donnees.gozer.length +
        " Gozer dans le dossier « gozer »" + (donnees.zuul.length + donnees.gozer.length === 0 ? " : dépose des fichiers .png dans ces dossiers puis clique sur « Relire les dossiers »." : ".");
      if (!etat.listesChargees) {
        var ul = $("fa-effets");
        donnees.effets.forEach(function (effet) {
          var li = document.createElement("li");
          var label = document.createElement("label");
          var case_ = document.createElement("input");
          case_.type = "checkbox";
          case_.value = effet.code;
          case_.addEventListener("change", surEffet);
          label.appendChild(case_);
          label.appendChild(document.createTextNode(effet.nom));
          li.appendChild(label);
          ul.appendChild(li);
        });
        etat.listesChargees = true;
        chargerCartes(true);
      }
      planifierApercu();
    }).catch(function (erreur) { message(erreur.message, true); });
  }

  function surEffet(evenement) {
    var coches = Array.prototype.slice.call($("fa-effets").querySelectorAll("input:checked"));
    if (coches.length > etat.effetsMax) {
      evenement.target.checked = false;
      message(etat.effetsMax + " effets au plus.", true);
      return;
    }
    etat.effets = coches.map(function (c) { return c.value; });
    message("");
    planifierApercu();
  }

  $("fa-zuul").addEventListener("change", function () { etat.zuul = this.value; planifierApercu(); });
  $("fa-gozer").addEventListener("change", function () { etat.gozer = this.value; planifierApercu(); });
  $("fa-relire").addEventListener("click", function () { charger(); });

  /* ------------------------------------------------------------------ aperçu */
  function planifierApercu() {
    $("fa-appliquer").disabled = !etat.carte || etat.carte.fullart || !(etat.zuul || etat.gozer || etat.effets.length);
    if (!etat.carte) {
      return;
    }
    clearTimeout(etat.minuteur);
    etat.minuteur = setTimeout(montrerApercu, 120);
  }

  function montrerApercu() {
    etat.version += 1;
    var version = etat.version;
    var existant = !!(etat.carte && etat.carte.fullart);              /* une carte déjà full-art : on la montre telle qu'elle est */
    appeler("POST", "/api/fullart/apercu", { id: etat.carte.id, zuul: existant ? "" : etat.zuul, gozer: existant ? "" : etat.gozer, effets: existant ? [] : etat.effets, existant: existant }).then(function (donnees) {
      if (version !== etat.version) {
        return;
      }
      var zone = $("fa-apercu");
      zone.innerHTML = donnees.html;
      Array.prototype.slice.call(zone.querySelectorAll(".carte-cadre")).forEach(function (cadre) { cadre.setAttribute("inert", ""); });
    }).catch(function (erreur) { message(erreur.message, true); });
  }

  /* Appliquer est DÉFINITIF : une fenêtre de confirmation explique que la carte ne pourra plus revenir à son état d'origine. */
  function confirmer(carte, resume) {
    return new Promise(function (resoudre) {
      var precedent = document.activeElement;
      var fond = document.createElement("div");
      fond.className = "fa-confirmation";
      fond.setAttribute("role", "alertdialog");
      fond.setAttribute("aria-modal", "true");
      fond.setAttribute("aria-labelledby", "fa-confirmation-titre");
      fond.setAttribute("aria-describedby", "fa-confirmation-texte");
      var boite = document.createElement("div");
      boite.className = "fa-confirmation__boite";
      var titre = document.createElement("h2");
      titre.id = "fa-confirmation-titre";
      titre.className = "fa-confirmation__titre";
      titre.textContent = "⚠ Opération irréversible";
      var texte = document.createElement("p");
      texte.id = "fa-confirmation-texte";
      texte.className = "fa-confirmation__texte";
      texte.textContent = "La carte « " + carte.titre + " » va devenir une carte full-art (" + resume + "). Cette opération est IRRÉVERSIBLE : la carte ne pourra " +
        "plus jamais revenir à son état d'origine, et son full-art ne pourra ni être retiré ni être modifié. Veux-tu vraiment l'appliquer ?";
      var boutons = document.createElement("div");
      boutons.className = "fa-confirmation__boutons";
      var non = document.createElement("button");
      non.type = "button";
      non.className = "bouton-site";
      non.textContent = "Annuler";
      var oui = document.createElement("button");
      oui.type = "button";
      oui.className = "bouton-site bouton-site--danger";
      oui.textContent = "Oui, appliquer définitivement";
      boutons.appendChild(non);
      boutons.appendChild(oui);
      boite.appendChild(titre);
      boite.appendChild(texte);
      boite.appendChild(boutons);
      fond.appendChild(boite);
      document.body.appendChild(fond);
      function fin(reponse) {
        document.removeEventListener("keydown", clavier, true);
        fond.remove();
        if (precedent && precedent.focus) {
          try { precedent.focus({ preventScroll: true }); } catch (erreur) { /* sans importance */ }
        }
        resoudre(reponse);
      }
      function clavier(evenement) {
        if (evenement.key === "Escape") {
          evenement.preventDefault();
          fin(false);
        } else if (evenement.key === "Tab") {
          var premier = non, dernier = oui;
          if (evenement.shiftKey && document.activeElement === premier) {
            evenement.preventDefault();
            dernier.focus();
          } else if (!evenement.shiftKey && document.activeElement === dernier) {
            evenement.preventDefault();
            premier.focus();
          }
        }
      }
      non.addEventListener("click", function () { fin(false); });
      oui.addEventListener("click", function () { fin(true); });
      document.addEventListener("keydown", clavier, true);
      non.focus({ preventScroll: true });                /* le bouton par défaut est « Annuler » */
    });
  }

  $("fa-appliquer").addEventListener("click", function () {
    if (!etat.carte || etat.carte.fullart) { return; }
    var morceaux = [];
    if (etat.zuul) { morceaux.push("Zuul « " + etat.zuul + " »"); }
    if (etat.gozer) { morceaux.push("Gozer « " + etat.gozer + " »"); }
    if (etat.effets.length) { morceaux.push(etat.effets.length + " effet" + (etat.effets.length > 1 ? "s" : "")); }
    confirmer(etat.carte, morceaux.join(", ")).then(function (oui) {
      if (!oui) {
        message("Full-art non appliqué : la carte reste inchangée.");
        return null;
      }
      return appeler("POST", "/api/fullart/appliquer", { id: etat.carte.id, zuul: etat.zuul, gozer: etat.gozer, effets: etat.effets, confirme: true }).then(function (donnees) {
        $("fa-apercu").innerHTML = donnees.html;
        Array.prototype.slice.call($("fa-apercu").querySelectorAll(".carte-cadre")).forEach(function (cadre) { cadre.setAttribute("inert", ""); });
        etat.carte.fullart = true;
        message("Full-art appliqué à « " + etat.carte.titre + " » : elle est maintenant unique, et définitivement full-art.");
        planifierApercu();
        chargerCartes(true);
      });
    }).catch(function (erreur) { message(erreur.message, true); });
  });

  /* ------------------------------------------------------------------ choix de la carte (même recherche que la page Profil) */
  var liste = $("fa-liste");

  function adresseSure(adresse) {
    return typeof adresse === "string" &&
      (/^https:\/\//.test(adresse) || /^\/image\/[0-9a-f]{32}\.(jpg|png|gif|webp)$/.test(adresse)) ? adresse : "";
  }

  function creerLigne(carte) {
    var item = document.createElement("li");
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "selecteur__carte" + (etat.carte && etat.carte.id === carte.id ? " selecteur__carte--choisie" : "");
    bouton.setAttribute("data-id", String(carte.id));
    bouton.setAttribute("aria-pressed", etat.carte && etat.carte.id === carte.id ? "true" : "false");
    bouton.setAttribute("aria-label", "Choisir la carte " + carte.titre);
    var vignette = document.createElement("span");
    vignette.className = "selecteur__vignette" + (carte.flou ? " selecteur__vignette--floue" : "");
    var source = adresseSure(carte.image);
    if (source) {
      var image = document.createElement("img");
      image.src = source; image.alt = ""; image.loading = "lazy";
      image.addEventListener("error", function () { image.remove(); });
      vignette.appendChild(image);
    }
    var initiale = document.createElement("span");
    initiale.className = "selecteur__initiale";
    initiale.textContent = (carte.titre || "?").charAt(0).toUpperCase();
    vignette.appendChild(initiale);
    var texte = document.createElement("span");
    texte.className = "selecteur__texte";
    var titre = document.createElement("b");
    titre.textContent = carte.titre;
    var description = document.createElement("small");
    description.textContent = carte.description || "";
    texte.appendChild(titre);
    texte.appendChild(description);
    var rang = document.createElement("span");
    rang.className = "selecteur__rang";
    rang.setAttribute("data-rarete", carte.rarete);
    rang.textContent = carte.symbole;
    bouton.appendChild(vignette);
    bouton.appendChild(texte);
    if (carte.fullart) {
      var marque = document.createElement("span");
      marque.className = "selecteur__placee";
      marque.textContent = "✨ full-art";
      bouton.appendChild(marque);
    }
    bouton.appendChild(rang);
    bouton.addEventListener("click", function () {
      etat.carte = { id: carte.id, titre: carte.titre, fullart: !!carte.fullart };
      Array.prototype.slice.call(liste.querySelectorAll(".selecteur__carte")).forEach(function (b) {
        var choisie = b === bouton;
        b.classList.toggle("selecteur__carte--choisie", choisie);
        b.setAttribute("aria-pressed", choisie ? "true" : "false");
      });
      message(carte.fullart ? "« " + carte.titre + " » est déjà une carte full-art : c'est définitif, elle ne peut plus changer." : "Carte choisie : « " + carte.titre + " ».");
      planifierApercu();
    });
    item.appendChild(bouton);
    return item;
  }

  function chargerCartes(depart) {
    if (depart) {
      recherche.page = 1;
      liste.textContent = "";
    }
    recherche.version += 1;
    var version = recherche.version;
    $("fa-etat-liste").textContent = "Chargement…";
    var chemin = "/api/profil/cartes?page=" + recherche.page + "&q=" + encodeURIComponent(recherche.texte) +
      (recherche.rangs.length ? "&rangs=" + encodeURIComponent(recherche.rangs.join(",")) : "") +
      (recherche.tri ? "&tri=" + encodeURIComponent(recherche.tri) : "");
    return appeler("GET", chemin).then(function (donnees) {
      if (version !== recherche.version) { return; }
      donnees.cartes.forEach(function (carte) { liste.appendChild(creerLigne(carte)); });
      recherche.pages = donnees.pages;
      $("fa-plus").hidden = donnees.page >= donnees.pages;
      $("fa-etat-liste").textContent = donnees.total === 0
        ? (recherche.texte || recherche.rangs.length ? "Aucune carte ne correspond à cette recherche." : "Ta collection est vide.")
        : donnees.total + " carte" + (donnees.total > 1 ? "s" : "");
    }).catch(function (erreur) { $("fa-etat-liste").textContent = erreur.message; });
  }

  var minuteurRecherche = null;
  $("fa-recherche").addEventListener("input", function () {
    recherche.texte = this.value.trim();
    clearTimeout(minuteurRecherche);
    minuteurRecherche = setTimeout(function () { chargerCartes(true); }, 250);
  });
  $("fa-tri").addEventListener("change", function () { recherche.tri = this.value; chargerCartes(true); });
  Array.prototype.slice.call($("fa-rangs").querySelectorAll(".selecteur__filtre")).forEach(function (b) {
    b.addEventListener("click", function () {
      var actif = b.getAttribute("aria-pressed") !== "true";
      b.setAttribute("aria-pressed", actif ? "true" : "false");
      var code = b.getAttribute("data-rarete");
      recherche.rangs = recherche.rangs.filter(function (r) { return r !== code; });
      if (actif) { recherche.rangs.push(code); }
      chargerCartes(true);
    });
  });
  $("fa-plus").addEventListener("click", function () { recherche.page += 1; chargerCartes(false); });
})();
