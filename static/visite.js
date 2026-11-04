/* Page d'un autre collectionneur (Hall des collections) : profil (vitrines) ou collection (filtres, tri, recherche,
   sélection et rapatriement). Lecture seule : rien de ce qui s'affiche ne peut être modifié ni supprimé.
   Les cartes arrivent déjà vérifiées et mises en HTML par le serveur local ; les textes de l'interface (catégories,
   rangs, titres) sont posés avec textContent. */
(function () {
  "use strict";

  var corps = document.body;
  if (corps.getAttribute("data-page") !== "hall-visite") {
    return;
  }
  var jeton = corps.getAttribute("data-jeton");
  var pair = corps.getAttribute("data-pair");
  var mode = corps.getAttribute("data-mode");
  var parPage = Number(corps.getAttribute("data-par-page")) || 24;
  var etatZone = document.getElementById("visite-etat");
  var enCours = 0;

  function $(id) {
    return document.getElementById(id);
  }

  function appeler(chemin, donnees) {
    return fetch(chemin, {
      method: "POST",
      headers: { "X-Jeton": jeton, "Content-Type": "application/json" },
      body: JSON.stringify(donnees)
    }).catch(function () {
      throw new Error("le serveur local est injoignable (lance python main.py)");
    }).then(function (reponse) {
      return reponse.json().catch(function () {
        return {};
      }).then(function (d) {
        if (!reponse.ok) {
          var erreur = new Error(d.erreur || "erreur du serveur");
          erreur.refus = d.refus;
          throw erreur;
        }
        return d;
      });
    });
  }

  function el(balise, classe, texte) {
    var e = document.createElement(balise);
    if (classe) {
      e.className = classe;
    }
    if (texte !== undefined) {
      e.textContent = texte;
    }
    return e;
  }

  function dire(texte, erreur) {
    etatZone.textContent = texte || "";
    etatZone.classList.toggle("createur__etat--erreur", !!erreur);
  }

  function entete(donnees) {
    if (donnees.titre) {
      $("visite-titre").textContent = donnees.titre;
    }
    var photo = $("visite-photo");
    if (photo) {                                                /* sa photo de profil : le carré qu'il partage, relayé par TON nœud (le navigateur ne contacte jamais le pair) */
      if (donnees.photo_url) {
        $("visite-photo-image").src = donnees.photo_url;
        photo.hidden = false;
      } else {
        photo.hidden = true;
      }
    }
    $("visite-bio").textContent = donnees.bio || "";
    $("style-apparence").textContent = donnees.css || "";       /* couleurs de SES rangs : valeurs vérifiées, CSS généré ici */
    if (donnees.bilan_html) {                                   /* le résumé n'existe que dans le PROFIL (la collection a déjà */
      $("visite-bilan").innerHTML = donnees.bilan_html;         /* ses rangs et catégories dans la barre de filtres) */
    }
  }

  function refus(erreur) {
    $("visite-bilan").textContent = "";
    ["visite-outils", "visite-selection", "visite-pages"].forEach(function (id) {
      var zone = $(id);
      if (zone) {
        zone.hidden = true;
      }
    });
    var cartes = $("visite-cartes") || $("visite-vitrines");
    if (cartes) {
      cartes.textContent = "";
    }
    dire(erreur.message, true);
  }

  /* ----------------------------------------------------------------------------- profil */

  if (mode === "profil") {
    appeler("/api/hall/profil", { pair: pair }).then(function (donnees) {
      entete(donnees);
      $("visite-vitrines").innerHTML = donnees.vitrines_html;
      dire(donnees.total + " carte" + (donnees.total > 1 ? "s" : "") + " dans sa collection · profil en lecture seule");
    }).catch(refus);
    $("visite-vitrines").addEventListener("click", function (evenement) {
      /* un clic N'IMPORTE OÙ sur la carte (image, titre, texte, pied) l'agrandit ; les liens et boutons gardent leur rôle */
      var cible = evenement.target;
      var carte = cible.closest ? cible.closest(".carte") : null;
      /* les liens, cases et boutons gardent leur rôle ; le bouton d'agrandissement de l'image, lui, ouvre l'aperçu */
      if (!carte || (cible.closest && cible.closest("a, label, input, button:not(.carte__zoom)"))) {
        return;
      }
      var zoom = carte.querySelector(".carte__zoom");
      if (zoom && window.WikiApercu) {
        window.WikiApercu.ouvrir(carte, zoom, { controles: [".carte__lien", ".carte__sensible"] });
      }
    });
    return;
  }

  /* -------------------------------------------------------------------------- collection */

  var filtre = { rangs: [], categorie: "", q: "", tri: "", page: 1 };
  var choisies = {};                       /* identifiants distants cochés (gardés d'une page à l'autre) */
  var construit = false;

  function nombreChoisies() {
    return Object.keys(choisies).length;
  }

  function majSelection() {
    var n = nombreChoisies();
    $("visite-compte").textContent = n === 0 ? "Aucune carte sélectionnée"
      : n + " carte" + (n > 1 ? "s" : "") + " sélectionnée" + (n > 1 ? "s" : "");
    $("visite-rapatrier").disabled = n === 0;
    $("visite-rapatrier").textContent = n > 0 ? "Rapatrier (" + n + ")" : "Rapatrier";
  }

  function cocher(carte, etat) {
    var identifiant = carte.getAttribute("data-id");
    var saisie = carte.querySelector(".carte__case");
    if (saisie) {
      saisie.checked = etat;
    }
    carte.classList.toggle("carte--selectionnee", etat);
    if (etat) {
      choisies[identifiant] = true;
    } else {
      delete choisies[identifiant];
    }
  }

  function majCartes() {
    Array.prototype.forEach.call($("visite-cartes").querySelectorAll(".carte"), function (carte) {
      if (choisies[carte.getAttribute("data-id")]) {
        cocher(carte, true);
      }
    });
    majSelection();
  }

  function construireOutils(donnees) {
    var cat = $("visite-categorie");
    cat.textContent = "";
    var toutes = el("option", null, "Toutes les catégories (" + donnees.resume.total + ")");
    toutes.value = "";
    cat.appendChild(toutes);
    var sans = el("option", null, "Sans catégorie (" + donnees.resume.sans_categorie + ")");
    sans.value = "@sans";
    cat.appendChild(sans);
    donnees.resume.categories.forEach(function (c) {
      var o = el("option", null, c.nom + " (" + c.n + ")");
      o.value = c.nom;
      cat.appendChild(o);
    });
    cat.value = filtre.categorie;
    if (!construit) {
      var tri = $("visite-tri");
      Object.keys(donnees.tris).forEach(function (cle) {
        var o = el("option", null, donnees.tris[cle]);
        o.value = cle;
        tri.appendChild(o);
      });
      filtre.tri = tri.value;
    }
    var rangs = $("visite-rangs");
    rangs.textContent = "";
    donnees.resume.rangs.forEach(function (r) {
      var li = el("li");
      var b = el("button", "pastille pastille--filtre" + (r.n ? "" : " pastille--zero"));
      b.type = "button";
      b.setAttribute("data-rarete", r.code);
      b.setAttribute("aria-pressed", filtre.rangs.indexOf(r.code) !== -1 ? "true" : "false");
      b.title = r.nom;
      b.appendChild(el("span", "pastille__code", r.symbole));
      b.appendChild(el("b", null, String(r.n)));
      b.addEventListener("click", function () {
        var i = filtre.rangs.indexOf(r.code);
        if (i === -1) {
          filtre.rangs.push(r.code);
        } else {
          filtre.rangs.splice(i, 1);
        }
        filtre.page = 1;
        charger();
      });
      li.appendChild(b);
      rangs.appendChild(li);
    });
    construit = true;
    $("visite-outils").hidden = false;
    $("visite-selection").hidden = false;
  }

  /* Les boutons de pagination sont en haut ET en bas de la liste : on les tient à jour ensemble. */
  function majPages(donnees) {
    ["", "-haut"].forEach(function (suffixe) {
      $("visite-pages" + suffixe).hidden = donnees.pages <= 1;
      $("visite-page-texte" + suffixe).textContent = "Page " + donnees.page + " sur " + donnees.pages;
      $("visite-precedent" + suffixe).disabled = donnees.page <= 1;
      $("visite-suivant" + suffixe).disabled = donnees.page >= donnees.pages;
    });
  }

  /* Pagination du HAUT comme du BAS : la page suivante ou précédente s'affiche depuis le début de la liste. */
  function aller(delta, suffixe) {
    filtre.page = Math.max(1, filtre.page + delta);
    var haut = $("visite-outils");
    if (window.WikiDefilement) {
      window.WikiDefilement.versLeHaut(haut, charger);
      return;
    }
    charger().then(function () {
      if (haut && haut.scrollIntoView) {
        haut.scrollIntoView({ block: "start" });
      }
    });
  }

  function charger() {
    var numero = ++enCours;
    dire("Chargement depuis le collectionneur… (via Tor, la première connexion peut prendre jusqu'à une minute)");
    return appeler("/api/hall/collection", {
      pair: pair, rangs: filtre.rangs, categorie: filtre.categorie, q: filtre.q, tri: filtre.tri,
      page: filtre.page, par_page: parPage
    }).then(function (donnees) {
      if (numero !== enCours) {
        return;                             /* une réponse plus récente est arrivée */
      }
      entete(donnees);
      construireOutils(donnees);
      $("visite-cartes").innerHTML = donnees.cartes_html;
      filtre.page = donnees.page;
      majPages(donnees);
      majCartes();
      dire(donnees.total_filtre + " carte" + (donnees.total_filtre > 1 ? "s" : "") +
        (donnees.total_filtre !== donnees.total ? " sur " + donnees.total : "") +
        (donnees.ecartees ? " · " + donnees.ecartees + " carte(s) écartée(s) car invalides" : "") +
        " · collection en lecture seule");
    }).catch(function (erreur) {
      if (numero === enCours) {
        refus(erreur);
      }
    });
  }

  var minuterie = null;
  $("visite-q").addEventListener("input", function () {
    clearTimeout(minuterie);
    minuterie = setTimeout(function () {
      filtre.q = $("visite-q").value;
      filtre.page = 1;
      charger();
    }, 400);
  });
  $("visite-categorie").addEventListener("change", function () {
    filtre.categorie = $("visite-categorie").value;
    filtre.page = 1;
    charger();
  });
  $("visite-tri").addEventListener("change", function () {
    filtre.tri = $("visite-tri").value;
    filtre.page = 1;
    charger();
  });
  ["", "-haut"].forEach(function (suffixe) {
    $("visite-precedent" + suffixe).addEventListener("click", function () {
      aller(-1, suffixe);
    });
    $("visite-suivant" + suffixe).addEventListener("click", function () {
      aller(1, suffixe);
    });
  });

  /* Un clic sur l'IMAGE agrandit la carte ; un clic ailleurs la coche ou la décoche. */
  $("visite-cartes").addEventListener("click", function (evenement) {
    var cible = evenement.target;
    var carte = cible.closest ? cible.closest(".carte") : null;
    if (!carte) {
      return;
    }
    var zoom = cible.closest(".carte__zoom");
    if (zoom) {
      if (window.WikiApercu) {
        window.WikiApercu.ouvrir(carte, zoom, { controles: [".carte__lien", ".carte__sensible"] });
      }
      return;
    }
    if (cible.closest("a, label, input")) {
      return;
    }
    cocher(carte, !choisies[carte.getAttribute("data-id")]);
    majSelection();
  });
  $("visite-cartes").addEventListener("change", function (evenement) {
    if (evenement.target.classList && evenement.target.classList.contains("carte__case")) {
      cocher(evenement.target.closest(".carte"), evenement.target.checked);
      majSelection();
    }
  });
  $("visite-tout").addEventListener("click", function () {
    Array.prototype.forEach.call($("visite-cartes").querySelectorAll(".carte"), function (carte) {
      cocher(carte, true);
    });
    majSelection();
  });
  $("visite-rien").addEventListener("click", function () {
    choisies = {};
    Array.prototype.forEach.call($("visite-cartes").querySelectorAll(".carte"), function (carte) {
      cocher(carte, false);
    });
    majSelection();
  });

  $("visite-rapatrier").addEventListener("click", function () {
    var ids = Object.keys(choisies).map(Number);
    if (!ids.length) {
      return;
    }
    var bouton = $("visite-rapatrier");
    bouton.disabled = true;
    dire("Rapatriement de " + ids.length + " carte" + (ids.length > 1 ? "s" : "") + "… (aucune requête vers Wikipédia)");
    appeler("/api/hall/rapatrier", { pair: pair, ids: ids }).then(function (r) {
      choisies = {};
      var texte = r.importes + " carte" + (r.importes > 1 ? "s ajoutées" : " ajoutée") + " à ta collection (" + r.total + " au total)" + (r.fullart ? ", dont " + r.fullart + " en full-art" : "");
      if (r.deja) {
        texte += " · " + r.deja + " article(s) étai(en)t déjà dans ta collection";
      }
      if (r.ignorees) {
        texte += " · " + r.ignorees + " carte(s) ignorée(s) car invalides";
      }
      return charger().then(function () {
        dire(texte + ".");
      });
    }).catch(function (erreur) {
      dire("Rapatriement impossible : " + erreur.message, true);
      bouton.disabled = false;
    });
  });

  majSelection();
  charger();
})();
