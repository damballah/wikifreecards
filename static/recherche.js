/* Page « Recherche » : le formulaire interroge Wikipédia (via le serveur local), les cartes
   trouvées s'affichent avec une case à cocher, et la sélection est rapatriée dans la collection.

   - un clic sur l'IMAGE d'une carte l'agrandit (comme dans la collection, avec les mêmes animations) ;
   - un clic ailleurs sur une carte (ou sur sa case) la coche ou la décoche ;
   - « Tout sélectionner » / « Tout désélectionner » : un seul bouton qui bascule ;
   - « Rapatrier la sélection » : enregistre les cartes cochées (palier d'après les vues, puis
     catégories automatiques, comme pour un paquet). Elles restent affichées, avec la pastille
     « Dans ta collection ». */
(function () {
  "use strict";

  var formulaire = document.getElementById("formulaire-recherche");
  var champ = document.getElementById("recherche-texte");
  var boutonRecherche = document.getElementById("recherche-bouton");
  var etat = document.getElementById("recherche-etat");
  var grille = document.getElementById("resultats");
  var barre = document.getElementById("barre-recherche");
  var compte = document.getElementById("recherche-compte");
  var boutonTout = document.getElementById("recherche-tout");
  var boutonRapatrier = document.getElementById("recherche-rapatrier");
  var outils = document.getElementById("recherche-outils");
  var selecteurTri = document.getElementById("recherche-tri");
  var zonePlus = document.getElementById("recherche-plus-zone");
  var boutonPlus = document.getElementById("recherche-plus");
  var occupe = false;

  /* Les résultats déjà chargés (par lots : « Voir plus de résultats » en charge autant de plus), leur tri, leur page. */
  var resultats = {
    texte: "", tous: [], titres: {}, page: 1, decalage: 0, suite: false, lot: 20,
    parPage: Number(grille && grille.getAttribute("data-par-page")) || 20, tri: "pertinence"
  };
  var TOTAL_MAX = 200;                          /* on ne charge pas plus de 200 résultats */

  function afficherEtat(texte, erreur) {
    if (!etat) {
      return;
    }
    etat.textContent = texte;
    etat.className = "recherche__etat" + (erreur ? " recherche__etat--erreur" : "");
  }

  function cartes() {                           /* TOUS les résultats chargés (même ceux d'une autre page) */
    return resultats.tous.slice();
  }

  function cartesAffichees() {                  /* ceux de la page affichée */
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

  function pluriel(nombre, mot) {
    return nombre + " " + mot + (nombre > 1 ? "s" : "");
  }

  /* Texte de la barre, libellé du bouton « tout », bouton « Rapatrier », contour des cartes. */
  function majSelection() {
    var toutes = cartes();
    var choisies = cochees();
    if (compte) {
      compte.textContent =
        choisies.length === 0
          ? "Aucune carte sélectionnée"
          : pluriel(choisies.length, "carte") + (choisies.length > 1 ? " sélectionnées" : " sélectionnée") +
            " sur " + toutes.length;
    }
    if (boutonTout) {
      var affichees = cartesAffichees();
      var toutesCochees = affichees.length > 0 && affichees.every(function (carte) {
        var casee = caseDe(carte);
        return !!casee && casee.checked;
      });
      boutonTout.textContent = toutesCochees ? "Tout désélectionner" : "Tout sélectionner";
      boutonTout.title = "Concerne les cartes de la page affichée";
      boutonTout.disabled = affichees.length === 0;
    }
    if (boutonRapatrier) {
      boutonRapatrier.disabled = choisies.length === 0 || occupe;
      boutonRapatrier.textContent =
        choisies.length === 0 ? "Rapatrier la sélection" : "Rapatrier la sélection (" + choisies.length + ")";
    }
    toutes.forEach(function (carte) {
      var casee = caseDe(carte);
      carte.classList.toggle("carte--selectionnee", !!casee && casee.checked);
    });
  }

  /* Un seul bouton : s'il reste des cartes à cocher sur la page affichée il les coche toutes, sinon il les décoche. */
  function basculerTout() {
    var toutes = cartesAffichees();
    var cocher = !toutes.every(function (carte) {
      var casee = caseDe(carte);
      return !!casee && casee.checked;
    });
    toutes.forEach(function (carte) {
      var casee = caseDe(carte);
      if (casee) {
        casee.checked = cocher;
      }
    });
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

  function surServeur() {
    return window.location.protocol === "http:" || window.location.protocol === "https:";
  }

  function definirOccupe(valeur) {
    occupe = valeur;
    if (boutonRecherche) {
      boutonRecherche.disabled = valeur;
      boutonRecherche.setAttribute("aria-busy", valeur ? "true" : "false");
    }
    majSelection();
  }

  /* ------------------------------------------------ tri, pages, « Voir plus de résultats » */

  function vuesDe(carte) {
    return Number(carte.getAttribute("data-vues")) || 0;
  }

  function pertinenceDe(carte) {
    return Number(carte.getAttribute("data-pertinence")) || 0;
  }

  /* Les résultats dans l'ordre choisi : par PERTINENCE (par défaut : l'ordre calculé par le serveur), les plus vues d'abord, ou par titre. */
  function triees() {
    var liste = resultats.tous.slice();
    if (resultats.tri === "pertinence") {
      liste.sort(function (a, b) {
        return pertinenceDe(a) - pertinenceDe(b);
      });
    } else if (resultats.tri === "titre") {
      liste.sort(function (a, b) {
        return (a.getAttribute("data-titre") || "").localeCompare(b.getAttribute("data-titre") || "", "fr", { sensitivity: "base" });
      });
    } else {
      liste.sort(function (a, b) {
        return vuesDe(b) - vuesDe(a) || pertinenceDe(a) - pertinenceDe(b);   /* à vues égales : l'ordre de Wikipédia */
      });
    }
    return liste;
  }

  /* La carte est dans un cadre (.carte-cadre) : c'est le cadre qu'on range dans la grille. */
  function conteneur(carte) {
    return (carte.closest && carte.closest(".carte-cadre")) || carte.parentNode || carte;
  }

  function nombreDePages() {
    return Math.max(1, Math.ceil(resultats.tous.length / resultats.parPage));
  }

  /* « ‹ 1 2 [3] … 12 › » : même présentation que la pagination de la collection. */
  function dessinerPagination(zone) {
    if (!zone) {
      return;
    }
    zone.textContent = "";
    var pages = nombreDePages();
    if (pages <= 1) {
      return;
    }
    var nav = document.createElement("nav");
    nav.className = "pagination";
    nav.setAttribute("aria-label", "Pagination des résultats");
    function element(n, texte, libelle, courant, inactif) {
      var e = document.createElement(inactif ? "span" : "a");
      e.className = "pagination__lien" + (inactif ? " pagination__lien--inactif" : "");
      e.textContent = texte;
      if (inactif) {
        e.setAttribute("aria-hidden", "true");
      } else {
        e.href = "#page-" + n;
        e.setAttribute("aria-label", libelle);
        e.setAttribute("data-page", String(n));
        if (courant) {
          e.setAttribute("aria-current", "page");
        }
      }
      return e;
    }
    var numeros = [];
    for (var n = 1; n <= pages; n++) {
      if (n === 1 || n === pages || Math.abs(n - resultats.page) <= 2) {
        numeros.push(n);
      }
    }
    nav.appendChild(element(resultats.page - 1, "‹", "Page précédente", false, resultats.page === 1));
    var precedent = 0;
    numeros.forEach(function (numero) {
      if (numero - precedent > 1) {
        var points = document.createElement("span");
        points.className = "pagination__points";
        points.setAttribute("aria-hidden", "true");
        points.textContent = "…";
        nav.appendChild(points);
      }
      nav.appendChild(element(numero, String(numero), "Page " + numero, numero === resultats.page, false));
      precedent = numero;
    });
    nav.appendChild(element(resultats.page + 1, "›", "Page suivante", false, resultats.page === pages));
    zone.appendChild(nav);
  }

  /* Affiche la page courante des résultats triés (les cartes gardent leur case cochée : ce sont les mêmes éléments). */
  function afficher() {
    if (!grille) {
      return;
    }
    var pages = nombreDePages();
    resultats.page = Math.max(1, Math.min(resultats.page, pages));
    var debut = (resultats.page - 1) * resultats.parPage;
    grille.textContent = "";
    triees().slice(debut, debut + resultats.parPage).forEach(function (carte) {
      grille.appendChild(conteneur(carte));
    });
    dessinerPagination(document.getElementById("pagination-recherche-haut"));
    dessinerPagination(document.getElementById("pagination-recherche-bas"));
    if (outils) {
      outils.hidden = resultats.tous.length === 0;
    }
    if (zonePlus) {
      zonePlus.hidden = !(resultats.suite && resultats.tous.length > 0 && resultats.tous.length < TOTAL_MAX);
    }
    if (boutonPlus) {
      boutonPlus.textContent = "Voir " + resultats.lot + " résultats de plus";
    }
    if (barre) {
      barre.hidden = resultats.tous.length === 0;
    }
    majSelection();
  }

  /* Changer de page (par la pagination du haut OU du bas) ramène toujours au début de la liste. */
  /* Des résultats de Wikipédia peuvent être écartés parce que les mots ne sont pas dans les champs choisis (Configuration → Recherche). */
  function noteMasques(donnees) {
    var n = donnees && donnees.masques ? Number(donnees.masques) : 0;
    return n > 0 ? " (" + n + " résultat" + (n > 1 ? "s" : "") + " masqué" + (n > 1 ? "s" : "") +
      " : les mots ne sont pas dans les champs de recherche choisis — réglage Configuration → Recherche)" : "";
  }

  function allerALaPage(numero, bas) {
    resultats.page = numero;
    var haut = document.getElementById("pagination-recherche-haut");      /* que le clic vienne du haut ou du bas : on repart du début de la liste */
    if (window.WikiDefilement) {
      window.WikiDefilement.versLeHaut(haut, function () {
        afficher();
      });
      return;
    }
    afficher();
    if (haut && haut.scrollIntoView) {
      haut.scrollIntoView({ block: "start" });
    }
  }

  /* Range un lot de cartes reçu du serveur ; un article déjà chargé n'est pas ajouté deux fois. */
  function ajouterLot(html) {
    var modele = document.createElement("template");
    modele.innerHTML = html;
    var nouvelles = 0;
    var trouvees = modele.content.querySelectorAll ? modele.content.querySelectorAll(".carte") : modele.content.children;
    Array.prototype.slice.call(trouvees).forEach(function (carte) {
      var titre = carte.getAttribute("data-titre");
      if (titre === null || resultats.titres[titre]) {
        return;
      }
      resultats.titres[titre] = true;
      resultats.tous.push(carte);
      nouvelles += 1;
    });
    return nouvelles;
  }

  function charger(texte, decalage) {
    return demander("/api/recherche", { q: texte, decalage: decalage });
  }

  function chercher(texte) {
    texte = (texte || "").trim();
    if (occupe) {
      return Promise.resolve();
    }
    if (texte === "") {
      afficherEtat("Écris ce que tu cherches.", true);
      return Promise.resolve();
    }
    if (!surServeur()) {
      afficherEtat("La recherche nécessite le serveur local : lance python main.py, puis utilise la page qui s'ouvre.", true);
      return Promise.resolve();
    }
    definirOccupe(true);
    afficherEtat("Recherche sur Wikipédia…", false);
    return charger(texte, 0)
      .then(function (donnees) {
        resultats.texte = texte;
        resultats.tous = [];
        resultats.titres = {};
        resultats.page = 1;
        resultats.lot = donnees.limite || resultats.lot;
        resultats.decalage = donnees.limite || donnees.nombre;
        resultats.suite = !!donnees.suite;
        ajouterLot(donnees.html);
        afficher();
        afficherEtat(
          (donnees.nombre === 0
            ? "Aucun article trouvé pour « " + texte + " »."
            : pluriel(resultats.tous.length, "carte") + " trouvée" + (resultats.tous.length > 1 ? "s" : "") +
              " pour « " + texte + " », " + (resultats.tri === "vues" ? "les plus vues d'abord" : (resultats.tri === "titre" ? "de A à Z" : "les plus pertinentes d'abord")) +
              ". Coche celles que tu veux rapatrier.") + noteMasques(donnees),
          donnees.nombre === 0
        );
      })
      .catch(function (erreur) {
        afficherEtat("Recherche impossible : " + erreur.message, true);
      })
      .then(function () {
        definirOccupe(false);
      });
  }

  /* « Voir plus de résultats » : le lot suivant de Wikipédia s'ajoute aux résultats (et se range avec eux). */
  function voirPlus() {
    if (occupe || !resultats.suite || !resultats.texte) {
      return Promise.resolve();
    }
    definirOccupe(true);
    afficherEtat("Chargement de " + resultats.lot + " résultats de plus…", false);
    return charger(resultats.texte, resultats.decalage)
      .then(function (donnees) {
        var avant = resultats.tous.length;
        resultats.decalage += donnees.limite || resultats.lot;
        resultats.suite = !!donnees.suite;
        ajouterLot(donnees.html);
        afficher();
        var ajoutees = resultats.tous.length - avant;
        afficherEtat(
          ajoutees === 0
            ? "Plus aucun résultat pour « " + resultats.texte + " »." + noteMasques(donnees)
            : ajoutees + " résultat" + (ajoutees > 1 ? "s" : "") + " de plus, rangés avec les autres (" +
              pluriel(resultats.tous.length, "carte") + " en tout)." + noteMasques(donnees),
          false
        );
      })
      .catch(function (erreur) {
        afficherEtat("Impossible de charger la suite : " + erreur.message, true);
      })
      .then(function () {
        definirOccupe(false);
      });
  }

  /* Pastille « Dans ta collection ×N » sur une carte. */
  function marquerPossede(carte, nombre) {
    var pastille = carte.querySelector(".carte__possede");
    if (!pastille) {
      pastille = document.createElement("div");
      pastille.className = "carte__possede";
      var visuel = carte.querySelector(".carte__visuel");
      if (visuel) {
        visuel.appendChild(pastille);
      }
    }
    pastille.textContent = "✓ Dans ta collection" + (nombre > 1 ? " ×" + nombre : "");
    pastille.setAttribute("title", "Cet article est dans ta collection (" + pluriel(nombre, "carte") + ")");
  }

  function rapatrier() {
    var choisies = cochees();
    if (occupe || choisies.length === 0) {
      return Promise.resolve();
    }
    var titres = choisies.map(function (carte) {
      return carte.getAttribute("data-titre");
    });
    definirOccupe(true);
    afficherEtat("Rapatriement de " + pluriel(titres.length, "carte") + "…", false);
    return demander("/api/recherche/importer", { titres: titres })
      .then(function (donnees) {
        var importes = donnees.importes || {};
        var nombre = Object.keys(importes).length;
        cartes().forEach(function (carte) {
          var titre = carte.getAttribute("data-titre");
          if (Object.prototype.hasOwnProperty.call(importes, titre)) {
            marquerPossede(carte, importes[titre]);
            var casee = caseDe(carte);
            if (casee) {
              casee.checked = false;
            }
          }
        });
        var texte = pluriel(nombre, "carte") + (nombre > 1 ? " rapatriées" : " rapatriée") +
          " dans ta collection (" + pluriel(donnees.total, "carte") + " au total), classée" +
          (nombre > 1 ? "s" : "") + " par rang et par catégorie.";
        if ((donnees.introuvables || []).length > 0) {
          texte += " Introuvable : " + donnees.introuvables.join(", ") + ".";
        }
        afficherEtat(texte, false);
      })
      .catch(function (erreur) {
        afficherEtat("Rapatriement impossible : " + erreur.message, true);
      })
      .then(function () {
        definirOccupe(false);
      });
  }

  /* ------------------------------------------------------------------ mise en route */

  if (formulaire) {
    formulaire.addEventListener("submit", function (evenement) {
      evenement.preventDefault();
      chercher(champ ? champ.value : "");
    });
  }
  if (boutonTout) {
    boutonTout.addEventListener("click", basculerTout);
  }
  if (boutonPlus) {
    boutonPlus.addEventListener("click", voirPlus);
  }
  if (selecteurTri) {
    selecteurTri.addEventListener("change", function () {
      resultats.tri = selecteurTri.value;
      resultats.page = 1;
      afficher();
    });
  }
  [document.getElementById("pagination-recherche-haut"), document.getElementById("pagination-recherche-bas")].forEach(function (zone) {
    if (zone) {
      zone.addEventListener("click", function (evenement) {
        var lien = evenement.target && evenement.target.closest ? evenement.target.closest("a[data-page]") : null;
        if (lien) {
          evenement.preventDefault();
          allerALaPage(Number(lien.getAttribute("data-page")), zone.id === "pagination-recherche-bas");
        }
      });
    }
  });
  if (boutonRapatrier) {
    boutonRapatrier.addEventListener("click", rapatrier);
  }
  if (grille) {
    /* Un clic sur une carte la coche ou la décoche (sauf sur le lien vers l'article) */
    grille.addEventListener("click", function (evenement) {
      var cible = evenement.target;
      if (!cible || !cible.closest) {
        return;
      }
      var carte = cible.closest(".carte");
      if (!carte) {
        return;
      }
      var zoom = cible.closest(".carte__zoom");
      if (zoom) {                              /* clic sur l'image : carte agrandie (lien Wikipédia gardé) */
        if (window.WikiApercu) {
          window.WikiApercu.ouvrir(carte, zoom, { controles: [".carte__lien", ".carte__sensible"] });
        }
        return;
      }
      var controle = cible.closest("a, label, input");
      if (controle) {
        return;                                /* le lien s'ouvre ; la case réagit d'elle-même */
      }
      var casee = caseDe(carte);
      if (casee) {
        casee.checked = !casee.checked;
        majSelection();
      }
    });
    grille.addEventListener("change", function (evenement) {
      if (evenement.target && evenement.target.classList &&
          evenement.target.classList.contains("carte__case")) {
        majSelection();
      }
    });
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      chercher: chercher,
      voirPlus: voirPlus,
      afficher: afficher,
      resultats: resultats,
      rapatrier: rapatrier,
      basculerTout: basculerTout,
      majSelection: majSelection,
      marquerPossede: marquerPossede
    };
  }
})();
