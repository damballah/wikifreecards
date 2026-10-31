/* Page de profil : les vitrines.
   - titre de chaque vitrine : se modifie directement (lettres, chiffres, emoji) et s'enregistre tout
     seul quand on quitte le champ ou qu'on appuie sur Entrée ;
   - emplacement vide : un clic ouvre la liste de tes cartes pour en choisir une ;
   - « Changer » / « Retirer » sur un emplacement occupé ; une carte n'est exposée qu'une fois (la
     choisir ailleurs la déplace) ;
   - les cartes exposées se comportent comme partout (agrandir, favori, export). */
(function () {
  "use strict";

  var jeton = document.body ? document.body.getAttribute("data-jeton") : "";
  var section = document.getElementById("vitrines");
  var selecteur = document.getElementById("selecteur");
  var liste = document.getElementById("selecteur-liste");
  var etatSelecteur = document.getElementById("selecteur-etat");
  var champRecherche = document.getElementById("selecteur-recherche");
  var boutonPlus = document.getElementById("selecteur-plus");
  var contexte = null;               /* { vitrine, emplacement, declencheur } pendant le choix */
  var recherche = { texte: "", page: 1, pages: 1, minuteur: null, version: 0, rangs: [], tri: "" };
  var boutonsRang = document.getElementById("selecteur-rangs");
  var listeTri = document.getElementById("selecteur-tri");

  function surServeur() {
    return (window.location.protocol === "http:" || window.location.protocol === "https:") && !!jeton;
  }

  function appeler(methode, chemin, corps) {
    var options = { method: methode, headers: { "X-Jeton": jeton } };
    if (corps !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(corps);
    }
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

  /* ----------------------------------------------------------- titres des vitrines */

  function afficherEtatTitre(vitrine, texte, erreur) {
    var zone = vitrine.querySelector(".vitrine__etat");
    if (!zone) {
      return;
    }
    zone.textContent = texte;
    zone.classList.toggle("vitrine__etat--erreur", !!erreur);
    if (!erreur && texte) {
      setTimeout(function () {
        if (zone.textContent === texte) {
          zone.textContent = "";
        }
      }, 2200);
    }
  }

  function enregistrerTitre(champ) {
    var vitrine = champ.closest(".vitrine");
    if (!vitrine) {
      return Promise.resolve();
    }
    if (!surServeur()) {
      afficherEtatTitre(vitrine, "Nécessite le serveur local (python main.py).", true);
      return Promise.resolve();
    }
    return appeler("POST", "/api/profil/titre", {
      vitrine: Number(vitrine.getAttribute("data-vitrine")),
      titre: champ.value
    })
      .then(function (donnees) {
        champ.value = donnees.titre;                       /* le titre nettoyé par le serveur */
        champ.classList.remove("vitrine__titre--erreur");
        afficherEtatTitre(vitrine, "Enregistré ✓", false);
      })
      .catch(function (erreur) {
        champ.classList.add("vitrine__titre--erreur");
        afficherEtatTitre(vitrine, erreur.message, true);
      });
  }

  if (section) {
    section.addEventListener("change", function (evenement) {
      if (evenement.target.classList && evenement.target.classList.contains("vitrine__titre")) {
        enregistrerTitre(evenement.target);
      }
    });
    section.addEventListener("keydown", function (evenement) {
      if (evenement.key === "Enter" && evenement.target.classList &&
          evenement.target.classList.contains("vitrine__titre")) {
        evenement.preventDefault();
        evenement.target.blur();                           /* déclenche l'enregistrement */
      }
    });
  }

  /* ---------------------------------------------------- emplacements : mise à jour */

  function trouverEmplacement(vitrine, emplacement) {
    return section.querySelector(
      '.vitrine__emplacement[data-vitrine="' + vitrine + '"][data-emplacement="' + emplacement + '"]'
    );
  }

  /* Remplace des emplacements par le HTML renvoyé par le serveur ({"1-2": "<div ...>"}). */
  function appliquerEmplacements(emplacements) {
    var nouveaux = [];
    Object.keys(emplacements).forEach(function (cle) {
      var morceaux = cle.split("-");
      var actuel = trouverEmplacement(morceaux[0], morceaux[1]);
      if (!actuel) {
        return;
      }
      actuel.outerHTML = emplacements[cle];
      nouveaux.push(trouverEmplacement(morceaux[0], morceaux[1]));
    });
    nouveaux.forEach(function (emplacement) {
      if (!emplacement) {
        return;
      }
      Array.prototype.forEach.call(emplacement.querySelectorAll(".carte"), function (carte) {
        if (window.WikiCartes && window.WikiCartes.initialiserCarte) {
          window.WikiCartes.initialiserCarte(carte);       /* agrandir, favori, export... */
        }
      });
    });
    return nouveaux;
  }

  function majInfos(donnees) {
    var infos = document.getElementById("infos-profil");
    if (infos && donnees.infos) {
      infos.textContent = donnees.infos;
    }
  }

  function messageEmplacement(emplacement, texte) {
    var zone = emplacement ? emplacement.closest(".vitrine") : null;
    if (zone) {
      afficherEtatTitre(zone, texte, true);
    }
  }

  function retirer(emplacement) {
    var vitrine = Number(emplacement.getAttribute("data-vitrine"));
    var numero = Number(emplacement.getAttribute("data-emplacement"));
    if (!surServeur()) {
      return Promise.resolve();
    }
    return appeler("POST", "/api/profil/carte", { vitrine: vitrine, emplacement: numero, carte_id: null })
      .then(function (donnees) {
        var nouveaux = appliquerEmplacements(donnees.emplacements);
        majInfos(donnees);
        var bouton = nouveaux[0] && nouveaux[0].querySelector("button");
        if (bouton) {
          bouton.focus();
        }
      })
      .catch(function (erreur) {
        messageEmplacement(emplacement, erreur.message);
      });
  }

  /* --------------------------------------------------------------- sélecteur de carte */

  function elementsFocalisables() {
    return Array.prototype.slice.call(
      selecteur.querySelectorAll("button:not([hidden]):not([disabled]), input")
    );
  }

  function ouvrirSelecteur(emplacement, declencheur) {
    if (!selecteur || !surServeur()) {
      if (emplacement) {
        messageEmplacement(emplacement, "Nécessite le serveur local (python main.py).");
      }
      return;
    }
    contexte = {
      vitrine: Number(emplacement.getAttribute("data-vitrine")),
      emplacement: Number(emplacement.getAttribute("data-emplacement")),
      declencheur: declencheur
    };
    document.getElementById("selecteur-titre").textContent =
      "Choisir une carte · vitrine " + contexte.vitrine + ", emplacement " + contexte.emplacement;
    selecteur.hidden = false;
    document.documentElement.classList.add("selecteur-ouvert");
    champRecherche.value = "";
    recherche.texte = "";                                  /* chaque ouverture repart de toute la liste */
    recherche.rangs = [];
    recherche.tri = "";
    if (listeTri) {
      listeTri.value = "";
    }
    if (boutonsRang) {
      Array.prototype.forEach.call(boutonsRang.querySelectorAll("button"), function (b) {
        b.setAttribute("aria-pressed", "false");
      });
    }
    clearTimeout(recherche.minuteur);
    chargerCartes(true);
    champRecherche.focus();
  }

  /* Le même sélecteur sert à choisir l'image de la PHOTO DE PROFIL (static/photo.js) : seules les cartes qui ont une image sont proposées, et le choix est rendu à
     `rappel(carteId)` au lieu de remplir un emplacement de vitrine. */
  function ouvrirSelecteurPhoto(rappel, declencheur) {
    if (!selecteur || !surServeur()) {
      return false;
    }
    contexte = { photo: true, rappel: rappel, declencheur: declencheur || null };
    document.getElementById("selecteur-titre").textContent = "Choisir la carte dont l'image sera ta photo de profil";
    selecteur.hidden = false;
    document.documentElement.classList.add("selecteur-ouvert");
    champRecherche.value = "";
    recherche.texte = "";
    recherche.rangs = [];
    recherche.tri = "";
    if (listeTri) {
      listeTri.value = "";
    }
    if (boutonsRang) {
      Array.prototype.forEach.call(boutonsRang.querySelectorAll("button"), function (b) {
        b.setAttribute("aria-pressed", "false");
      });
    }
    clearTimeout(recherche.minuteur);
    chargerCartes(true);
    champRecherche.focus();
    return true;
  }

  function fermerSelecteur() {
    if (!selecteur || selecteur.hidden) {
      return;
    }
    selecteur.hidden = true;
    document.documentElement.classList.remove("selecteur-ouvert");
    recherche.version += 1;                                /* les réponses en retard sont ignorées */
    if (contexte && contexte.declencheur && contexte.declencheur.focus) {
      contexte.declencheur.focus();
    }
    contexte = null;
  }

  function adresseSure(adresse) {
    return typeof adresse === "string" &&
      (/^https:\/\//.test(adresse) || /^\/image\/[0-9a-f]{32}\.(jpg|png|gif|webp)$/.test(adresse)) ? adresse : "";
  }

  function creerLigne(carte) {
    var item = document.createElement("li");
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "selecteur__carte";
    bouton.setAttribute("data-id", String(carte.id));
    bouton.setAttribute("aria-label", "Choisir la carte " + carte.titre);

    var vignette = document.createElement("span");
    vignette.className = "selecteur__vignette" + (carte.flou ? " selecteur__vignette--floue" : "");
    if (carte.flou) {
      vignette.setAttribute("title", "Image floutée (contenu sensible)");
    }
    var source = adresseSure(carte.image);
    if (source) {
      var image = document.createElement("img");
      image.src = source;
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", function () {
        image.remove();
      });
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
    bouton.appendChild(rang);
    if (carte.placee) {
      var placee = document.createElement("span");
      placee.className = "selecteur__placee";
      placee.textContent = "déjà en vitrine";
      bouton.appendChild(placee);
    }
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
    etatSelecteur.textContent = "Chargement…";
    var chemin = "/api/profil/cartes?page=" + recherche.page +
      "&q=" + encodeURIComponent(recherche.texte) +
      (recherche.rangs.length ? "&rangs=" + encodeURIComponent(recherche.rangs.join(",")) : "") +
      (recherche.tri ? "&tri=" + encodeURIComponent(recherche.tri) : "") +
      (contexte && contexte.photo ? "&avec_image=1" : "");
    return appeler("GET", chemin)
      .then(function (donnees) {
        if (version !== recherche.version) {
          return;
        }
        donnees.cartes.forEach(function (carte) {
          liste.appendChild(creerLigne(carte));
        });
        recherche.pages = donnees.pages;
        boutonPlus.hidden = donnees.page >= donnees.pages;
        etatSelecteur.textContent = donnees.total === 0
          ? (recherche.texte || recherche.rangs.length ? "Aucune carte ne correspond à cette recherche." : "Ta collection est vide.")
          : donnees.total + " carte" + (donnees.total > 1 ? "s" : "") +
            (recherche.texte || recherche.rangs.length ? " trouvée" + (donnees.total > 1 ? "s" : "") : "");
      })
      .catch(function (erreur) {
        if (version === recherche.version) {
          etatSelecteur.textContent = "Impossible de charger les cartes : " + erreur.message;
        }
      });
  }

  function choisir(carteId) {
    if (!contexte) {
      return Promise.resolve();
    }
    if (contexte.photo) {                                  /* la photo de profil : le choix est rendu à photo.js */
      var rappel = contexte.rappel;
      contexte.declencheur = null;
      fermerSelecteur();
      if (typeof rappel === "function") {
        rappel(carteId);
      }
      return Promise.resolve();
    }
    var cible = contexte;
    return appeler("POST", "/api/profil/carte", {
      vitrine: cible.vitrine, emplacement: cible.emplacement, carte_id: carteId
    })
      .then(function (donnees) {
        contexte = null;
        selecteur.hidden = true;
        document.documentElement.classList.remove("selecteur-ouvert");
        var nouveaux = appliquerEmplacements(donnees.emplacements);
        majInfos(donnees);
        var bouton = nouveaux[0] && nouveaux[0].querySelector(".vitrine__changer, button");
        if (bouton) {
          bouton.focus();
        }
      })
      .catch(function (erreur) {
        etatSelecteur.textContent = "Carte non placée : " + erreur.message;
      });
  }

  if (section) {
    section.addEventListener("click", function (evenement) {
      var bouton = evenement.target.closest ? evenement.target.closest("button") : null;
      if (!bouton) {
        return;
      }
      var emplacement = bouton.closest(".vitrine__emplacement");
      if (!emplacement) {
        return;
      }
      if (bouton.classList.contains("vitrine__ajouter") || bouton.classList.contains("vitrine__changer")) {
        ouvrirSelecteur(emplacement, bouton);
      } else if (bouton.classList.contains("vitrine__retirer")) {
        retirer(emplacement);
      }
    });
  }

  if (selecteur) {
    liste.addEventListener("click", function (evenement) {
      var bouton = evenement.target.closest ? evenement.target.closest(".selecteur__carte") : null;
      if (bouton) {
        choisir(Number(bouton.getAttribute("data-id")));
      }
    });
    document.getElementById("selecteur-fermer").addEventListener("click", fermerSelecteur);
    selecteur.addEventListener("click", function (evenement) {
      if (evenement.target === selecteur) {
        fermerSelecteur();                                 /* un clic à côté de la fenêtre ferme */
      }
    });
    boutonPlus.addEventListener("click", function () {
      recherche.page += 1;
      chargerCartes(false);
    });
    if (boutonsRang) {
      boutonsRang.addEventListener("click", function (evenement) {          /* filtre par rang : plusieurs possibles */
        var bouton = evenement.target.closest ? evenement.target.closest("button") : null;
        if (!bouton) {
          return;
        }
        var code = bouton.getAttribute("data-rarete");
        var i = recherche.rangs.indexOf(code);
        if (i === -1) {
          recherche.rangs.push(code);
        } else {
          recherche.rangs.splice(i, 1);
        }
        bouton.setAttribute("aria-pressed", i === -1 ? "true" : "false");
        chargerCartes(true);
      });
    }
    if (listeTri) {
      listeTri.addEventListener("change", function () {
        recherche.tri = listeTri.value;
        chargerCartes(true);
      });
    }
    champRecherche.addEventListener("input", function () {
      clearTimeout(recherche.minuteur);
      recherche.minuteur = setTimeout(function () {
        recherche.texte = champRecherche.value.trim();
        chargerCartes(true);
      }, 300);
    });
    document.addEventListener("keydown", function (evenement) {
      if (selecteur.hidden) {
        return;
      }
      if (evenement.key === "Escape") {
        fermerSelecteur();
      } else if (evenement.key === "Tab") {                /* le focus reste dans la fenêtre */
        var focalisables = elementsFocalisables();
        var premier = focalisables[0];
        var dernier = focalisables[focalisables.length - 1];
        if (evenement.shiftKey && document.activeElement === premier) {
          evenement.preventDefault();
          dernier.focus();
        } else if (!evenement.shiftKey && document.activeElement === dernier) {
          evenement.preventDefault();
          premier.focus();
        }
      }
    });
  }

  window.WikiProfil = { ouvrirSelecteurPhoto: ouvrirSelecteurPhoto, selecteurOuvert: function () { return !!selecteur && !selecteur.hidden; } };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { ouvrirSelecteur: ouvrirSelecteur, fermerSelecteur: fermerSelecteur, choisir: choisir,
      retirer: retirer, enregistrerTitre: enregistrerTitre, appliquerEmplacements: appliquerEmplacements,
      creerLigne: creerLigne, chargerCartes: chargerCartes };
  }
})();
