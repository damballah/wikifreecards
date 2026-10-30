/* Créateur de cartes : saisie manuelle, ou lecture d'une page web ; aperçu de la carte à la volée ;
   validation finale (ajout à la collection).
   - L'aperçu est fabriqué par le serveur (même gabarit que les cartes de la collection) : il est
     redemandé 0,2 s après la dernière modification ; une réponse en retard est ignorée.
   - Une image téléversée ou récupérée sur le web est rangée par le serveur dans data/images/ : la page
     ne manipule que son adresse locale (/image/<empreinte>.<ext>). */
(function () {
  "use strict";

  var racine = document.getElementById("createur");
  if (!racine) {
    return;
  }
  var jeton = document.body.getAttribute("data-jeton");
  var limites = {
    description: Number(racine.getAttribute("data-description-max")) || 600,
    titre: Number(racine.getAttribute("data-titre-max")) || 80,
    sousTitre: Number(racine.getAttribute("data-sous-titre-max")) || 120,
    surnom: Number(racine.getAttribute("data-surnom-max")) || 30,
    imageMo: Number(racine.getAttribute("data-image-max-mo")) || 5
  };
  var DELAI_APERCU = 200;
  var TYPES_IMAGE = ["image/jpeg", "image/png", "image/gif", "image/webp"];

  function $(id) {
    return document.getElementById(id);
  }

  var champs = {
    titre: $("champ-titre"), sousTitre: $("champ-sous-titre"), description: $("champ-description"),
    surnom: $("champ-surnom"), theme: $("champ-theme")
  };
  var emplacement = $("createur-apercu");
  var etatApercu = $("etat-apercu");
  var etatFinal = $("etat-final");
  var etatImage = $("etat-image");
  var etatWeb = $("etat-web");
  var boutonValider = $("bouton-valider");
  var confirmation = $("confirmation");
  var boutonCharger = $("bouton-charger");
  var boutonRetirerImage = $("bouton-retirer-image");
  var memoire = { image: null, source: null, version: 0, minuteur: null, cadrage: { z: 1, x: 50, y: 25 }, ratio: null, editeur: null };

  function surServeur() {
    return (window.location.protocol === "http:" || window.location.protocol === "https:") && !!jeton;
  }

  function message(zone, texte, genre) {
    if (!zone) {
      return;
    }
    zone.textContent = texte || "";
    zone.classList.toggle("createur__etat--erreur", genre === "erreur");
    zone.classList.toggle("createur__etat--ok", genre === "ok");
  }

  function appeler(chemin, corps, options) {
    var parametres = { method: "POST", headers: { "X-Jeton": jeton } };
    if (options && options.brut) {
      parametres.headers["Content-Type"] = options.type || "application/octet-stream";
      parametres.body = corps;
    } else {
      parametres.headers["Content-Type"] = "application/json";
      parametres.body = JSON.stringify(corps);
    }
    return fetch(chemin, parametres)
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

  /* ------------------------------------------------------------------ la carte */

  function lireCarte() {
    return {
      titre: champs.titre.value,
      sous_titre: champs.sousTitre.value,
      description: champs.description.value,
      surnom: champs.surnom.value,
      theme_rang: champs.theme.value,
      image: memoire.image,
      source: memoire.source,
      cadrage: cadrageSortant()
    };
  }

  /* Le cadrage de l'illustration réglé dans l'aperçu : envoyé avec la carte (aperçu et validation), ou null s'il n'y a rien de particulier. */
  function cadrageSortant() {
    var c = memoire.cadrage;
    if (!memoire.image || !memoire.ratio || (Math.abs(c.z - 1) < 0.005 && Math.abs(c.x - 50) < 0.05 && Math.abs(c.y - 25) < 0.05)) {
      return null;
    }
    return { zoom: Math.round(c.z * 1000) / 1000, x: Math.round(c.x * 1000) / 1000, y: Math.round(c.y * 1000) / 1000, ratio: Math.round(memoire.ratio * 10000) / 10000 };
  }

  function majCompteurs() {
    [["compteur-titre", champs.titre, limites.titre], ["compteur-sous-titre", champs.sousTitre, limites.sousTitre],
     ["compteur-description", champs.description, limites.description],
     ["compteur-surnom", champs.surnom, limites.surnom]].forEach(function (ligne) {
      var zone = $(ligne[0]);
      if (zone) {
        zone.textContent = ligne[1].value.length + " / " + ligne[2];
      }
    });
  }

  function demanderApercu() {
    memoire.version += 1;
    var version = memoire.version;
    if (!surServeur()) {
      message(etatApercu, "L'aperçu nécessite le serveur local (python main.py).", "erreur");
      return Promise.resolve();
    }
    return appeler("/api/createur/apercu", lireCarte())
      .then(function (donnees) {
        if (version === memoire.version) {
          emplacement.innerHTML = donnees.html;
          message(etatApercu, "");
          majCadrage();                                   /* l'aperçu a été redessiné : l'éditeur reprend sa nouvelle image */
        }
      })
      .catch(function (erreur) {
        if (version === memoire.version) {
          message(etatApercu, "Aperçu indisponible : " + erreur.message, "erreur");
        }
      });
  }

  function planifierApercu() {
    majCompteurs();
    clearTimeout(memoire.minuteur);
    memoire.minuteur = setTimeout(demanderApercu, DELAI_APERCU);
  }

  Object.keys(champs).forEach(function (cle) {
    var champ = champs[cle];
    champ.addEventListener("input", planifierApercu);
    champ.addEventListener("change", planifierApercu);
  });

  /* ---------------------------------------------------------- manuel ou depuis le web */

  var modeManuel = $("mode-manuel");
  var modeWeb = $("mode-web");
  var blocWeb = $("bloc-web");

  function choisirMode(web) {
    modeWeb.setAttribute("aria-selected", web ? "true" : "false");
    modeManuel.setAttribute("aria-selected", web ? "false" : "true");
    blocWeb.hidden = !web;
    if (web) {
      $("champ-url").focus();
    } else {
      memoire.source = null;               /* une carte saisie à la main n'est liée à aucune page */
      planifierApercu();
    }
  }

  modeManuel.addEventListener("click", function () {
    choisirMode(false);
  });
  modeWeb.addEventListener("click", function () {
    choisirMode(true);
  });
  [modeManuel, modeWeb].forEach(function (onglet) {
    onglet.addEventListener("keydown", function (evenement) {
      if (evenement.key === "ArrowRight" || evenement.key === "ArrowLeft") {
        var vers = onglet === modeManuel ? modeWeb : modeManuel;
        vers.focus();
        vers.click();
      }
    });
  });

  function remplir(champ, valeur) {
    champ.value = valeur || "";
  }

  function afficherImage(adresse) {
    var change = (adresse || null) !== memoire.image;
    memoire.image = adresse || null;
    boutonRetirerImage.hidden = !memoire.image;
    if (change) {                                         /* une autre image : son cadrage repart de l'origine */
      memoire.cadrage.z = 1;
      memoire.cadrage.x = 50;
      memoire.cadrage.y = 25;
      memoire.ratio = null;
    }
    majCadrage();
  }

  /* ------------------------------------------------------------------------ position et taille de l'illustration, directement dans l'aperçu */
  var sceneCadrage = $("createur-scene");
  var boutonCadrage = $("cadrage-bascule");

  function imageDeLApercu() {
    return emplacement.querySelector(".carte__image");
  }

  function majCadrage() {
    var possible = !!memoire.image && !!window.WikiCadrage;
    boutonCadrage.disabled = !possible;
    if (!possible && memoire.editeur) {
      basculerCadrage(false);
    } else if (memoire.editeur) {
      memoire.editeur.rafraichir();                      /* (la nouvelle image de l'aperçu) */
    }
  }

  function basculerCadrage(actif) {
    boutonCadrage.setAttribute("aria-pressed", actif ? "true" : "false");
    $("cadrage-commandes").hidden = !actif;
    $("cadrage-aide").hidden = !actif;
    sceneCadrage.classList.toggle("createur__scene--actif", actif);
    if (actif && !memoire.editeur) {
      sceneCadrage.setAttribute("tabindex", "0");
      memoire.editeur = window.WikiCadrage.monter({
        scene: sceneCadrage, cadre: emplacement, image: imageDeLApercu, etat: memoire.cadrage,
        curseur: $("cadrage-curseur"), lecture: $("cadrage-lecture"),
        surPret: function (ratio) { memoire.ratio = ratio; },
        surChangement: function (etat, ratio) { memoire.ratio = ratio || memoire.ratio; }
      });
      memoire.editeur.rafraichir();
    } else if (!actif && memoire.editeur) {
      memoire.editeur.detruire();
      memoire.editeur = null;
      sceneCadrage.removeAttribute("tabindex");
    }
  }

  boutonCadrage.addEventListener("click", function () {
    basculerCadrage(!memoire.editeur);
  });
  $("cadrage-reinit").addEventListener("click", function () {
    if (memoire.editeur) {
      memoire.editeur.reinitialiser();
    }
  });
  if (typeof window.addEventListener === "function") {
    window.addEventListener("resize", function () {
      if (memoire.editeur) {
        memoire.editeur.remesurer();
      }
    });
  }

  function charger() {
    var adresse = $("champ-url").value.trim();
    if (!adresse) {
      message(etatWeb, "Saisis l'adresse d'une page web.", "erreur");
      return Promise.resolve();
    }
    if (!surServeur()) {
      message(etatWeb, "Le chargement nécessite le serveur local (python main.py).", "erreur");
      return Promise.resolve();
    }
    boutonCharger.disabled = true;
    message(etatWeb, "Chargement de la page…");
    return appeler("/api/createur/charger", { url: adresse })
      .then(function (infos) {
        remplir(champs.titre, infos.titre);
        remplir(champs.sousTitre, infos.sous_titre);
        remplir(champs.description, infos.description);
        afficherImage(infos.image);
        memoire.source = infos.url;
        var notes = infos.avertissements || [];
        message(etatWeb, "Informations chargées" + (notes.length ? " — " + notes.join(" ; ") : "") +
          ". Tu peux tout modifier.", notes.length ? "" : "ok");
        majCompteurs();
        return demanderApercu();
      })
      .catch(function (erreur) {
        message(etatWeb, "Chargement impossible : " + erreur.message, "erreur");
      })
      .then(function () {
        boutonCharger.disabled = false;
      });
  }

  boutonCharger.addEventListener("click", charger);
  $("champ-url").addEventListener("keydown", function (evenement) {
    if (evenement.key === "Enter") {
      evenement.preventDefault();
      charger();
    }
  });

  /* -------------------------------------------------------------------------- image */

  function televerser(fichier) {
    if (!fichier) {
      return Promise.resolve();
    }
    if (TYPES_IMAGE.indexOf(fichier.type) === -1 && !/\.(jpe?g|png|gif|webp)$/i.test(fichier.name || "")) {
      message(etatImage, "Format non accepté (JPEG, PNG, GIF ou WebP).", "erreur");
      return Promise.resolve();
    }
    if (fichier.size > limites.imageMo * 1024 * 1024) {
      message(etatImage, "Image trop lourde (" + limites.imageMo + " Mo au maximum).", "erreur");
      return Promise.resolve();
    }
    if (!surServeur()) {
      message(etatImage, "Le téléversement nécessite le serveur local (python main.py).", "erreur");
      return Promise.resolve();
    }
    message(etatImage, "Envoi de l'image…");
    return appeler("/api/createur/image", fichier, { brut: true, type: fichier.type })
      .then(function (donnees) {
        afficherImage(donnees.url);
        message(etatImage, "Image ajoutée.", "ok");
        return demanderApercu();
      })
      .catch(function (erreur) {
        message(etatImage, "Image refusée : " + erreur.message, "erreur");
      });
  }

  $("champ-image").addEventListener("change", function (evenement) {
    var fichier = evenement.target.files && evenement.target.files[0];
    televerser(fichier).then(function () {
      evenement.target.value = "";                 /* permet de rechoisir le même fichier */
    });
  });

  boutonRetirerImage.addEventListener("click", function () {
    afficherImage(null);
    message(etatImage, "Image retirée.");
    planifierApercu();
  });

  /* ------------------------------------------------------------------------ validation */

  function remettreAZero() {
    ["titre", "sousTitre", "description", "surnom"].forEach(function (cle) {
      champs[cle].value = "";
    });
    champs.theme.value = "";                            /* palier « Personnalisée » (thème de base) */
    afficherImage(null);
    basculerCadrage(false);
    memoire.source = null;
    $("champ-url").value = "";
    message(etatWeb, "");
    message(etatImage, "");
    majCompteurs();
  }

  /* Confirmation à l'écran : une fenêtre au milieu avec la carte validée et deux choix. */
  function ouvrirConfirmation(donnees, carteHtml) {
    $("confirmation-texte").textContent =
      donnees.message + " Ta collection compte maintenant " + donnees.total +
      " carte" + (donnees.total > 1 ? "s" : "") + ".";
    $("confirmation-carte").innerHTML = carteHtml;        /* HTML fabriqué par notre serveur (carte) */
    $("confirmation-collection").textContent = "Voir la collection (" + donnees.total + ")";
    confirmation.hidden = false;
    document.documentElement.classList.add("confirmation-ouverte");
    $("confirmation-collection").focus();
  }

  function fermerConfirmation() {
    if (confirmation.hidden) {
      return;
    }
    confirmation.hidden = true;
    document.documentElement.classList.remove("confirmation-ouverte");
    $("confirmation-carte").innerHTML = "";
    champs.titre.focus();                                 /* prêt pour la carte suivante */
  }

  $("confirmation-autre").addEventListener("click", fermerConfirmation);
  confirmation.addEventListener("click", function (evenement) {
    if (evenement.target === confirmation) {
      fermerConfirmation();                               /* un clic à côté de la fenêtre ferme */
    }
  });
  document.addEventListener("keydown", function (evenement) {
    if (confirmation.hidden) {
      return;
    }
    if (evenement.key === "Escape") {
      fermerConfirmation();
    } else if (evenement.key === "Tab") {                 /* le focus reste dans la fenêtre */
      var focalisables = [$("confirmation-collection"), $("confirmation-autre")];
      var indice = focalisables.indexOf(document.activeElement);
      var suivant = evenement.shiftKey ? indice - 1 : indice + 1;
      evenement.preventDefault();
      focalisables[(suivant + focalisables.length) % focalisables.length].focus();
    }
  });

  function valider() {
    if (!surServeur()) {
      message(etatFinal, "La validation nécessite le serveur local (python main.py).", "erreur");
      return Promise.resolve();
    }
    if (champs.titre.value.trim() === "") {
      message(etatFinal, "Donne un titre à ta carte avant de la valider.", "erreur");
      champs.titre.focus();
      return Promise.resolve();
    }
    boutonValider.disabled = true;
    message(etatFinal, "Enregistrement…");
    var carteValidee = emplacement.innerHTML;             /* la carte telle qu'elle vient d'être validée */
    return appeler("/api/createur/valider", lireCarte())
      .then(function (donnees) {
        message(etatFinal, "");
        ouvrirConfirmation(donnees, carteValidee);
        remettreAZero();
        return demanderApercu();
      })
      .catch(function (erreur) {
        message(etatFinal, "Carte non ajoutée : " + erreur.message, "erreur");
      })
      .then(function () {
        boutonValider.disabled = false;
      });
  }

  boutonValider.addEventListener("click", valider);
  majCompteurs();

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { lireCarte: lireCarte, charger: charger, televerser: televerser, valider: valider,
      fermerConfirmation: fermerConfirmation,
      demanderApercu: demanderApercu, choisirMode: choisirMode, remettreAZero: remettreAZero,
      memoire: memoire };
  }
})();
