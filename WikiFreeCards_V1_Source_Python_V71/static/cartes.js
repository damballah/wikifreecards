/* Comportements de la page de cartes :
   - clic sur une carte (hors boutons) : aperçu agrandi au milieu de l'écran ;
   - disquette : enregistrement de la carte en image PNG (Export/<rang>/) ;
   - boutons PDF et Word : document recto verso prêt à imprimer (Export/<rang>/) ;
   - paquet de cartes : tremble au clic puis éclate, et les nouvelles cartes apparaissent ;
   - étoile : favoris (enregistrés dans la base de données par le serveur local) ;
   - boutons de rareté, « Favoris » et liste des catégories : filtrent la collection (la page
     est alors rechargée, car le filtre et la pagination se font côté serveur) ;
   - bouton « Sélection » : cases à cocher sur les cartes pour les classer dans des catégories ;
   - curseur : taille des cartes ;
   - images en erreur. */
(function () {
  "use strict";

  var CLE_STOCKAGE = "wikicartes:favoris";
  /* Boutons et liens retirés de la copie de la carte (aperçu agrandi, image exportée) */
  var CONTROLES =
    ".carte__favori, .carte__sauver, .carte__pdf, .carte__word, .carte__sensible, .carte__rafraichir, .carte__lien, .carte__zoom, " +
    ".carte__selection";

  var notification = null;  /* message affiché en bas de l'écran (ou null) */
  var minuteur = null;

  /* ------------------------------------------------------------- favoris */

  function lireFavoris() {
    try {
      return JSON.parse(localStorage.getItem(CLE_STOCKAGE)) || [];
    } catch (erreur) {
      return [];
    }
  }

  function ecrireFavoris(liste) {
    try {
      localStorage.setItem(CLE_STOCKAGE, JSON.stringify(liste));
    } catch (erreur) {
      /* stockage indisponible : les favoris ne seront pas conservés */
    }
  }

  function definirEtat(bouton, actif) {
    bouton.setAttribute("aria-pressed", actif ? "true" : "false");
    bouton.setAttribute(
      "aria-label",
      actif ? "Retirer des favoris" : "Ajouter aux favoris"
    );
  }

  /* --------------------------------------- dialogue avec le serveur local (base) */

  function surServeur() {
    return (window.location.protocol === "http:" || window.location.protocol === "https:") && !!document.body.getAttribute("data-jeton");
  }

  function enregistrerFavori(identifiant, actif) {
    return fetch(
      "/api/favori?id=" + encodeURIComponent(identifiant) + "&valeur=" + (actif ? "1" : "0"),
      { method: "POST", headers: { "X-Jeton": document.body.getAttribute("data-jeton") } }
    ).then(function (reponse) {
      return reponse.json().then(function (donnees) {
        if (!reponse.ok) {
          throw new Error(donnees.erreur || "erreur du serveur");
        }
        return donnees;
      });
    });
  }

  /* Réglages de la page (taille des cartes, filtres) : enregistrés dans la base.
     Sans le serveur local (page ouverte en double-clic), rien n'est enregistré. */
  function enregistrerPreferences(reglages) {
    if (!surServeur()) {
      return Promise.resolve(null);
    }
    return fetch("/api/preferences", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Jeton": document.body.getAttribute("data-jeton")
      },
      body: JSON.stringify(reglages)
    }).then(function (reponse) {
      return reponse.json().then(function (donnees) {
        if (!reponse.ok) {
          throw new Error(donnees.erreur || "erreur du serveur");
        }
        return donnees;
      });
    });
  }

  /* ------------------------------------------------------ filtres de la collection */

  /* Lit l'état des boutons de filtre : { rangs: [...], favoris: bool }. */
  function lireFiltres() {
    var filtres = { rangs: [], favoris: false };
    document.querySelectorAll(".pastille").forEach(function (bouton) {
      if (bouton.getAttribute("aria-pressed") !== "true") {
        return;
      }
      var cle = bouton.getAttribute("data-filtre");
      if (cle === "favoris") {
        filtres.favoris = true;
      } else {
        filtres.rangs.push(cle);
      }
    });
    return filtres;
  }

  /* Remet à jour le nombre de favoris affiché. */
  function mettreAJourFavoris() {
    var nombre = 0;
    document.querySelectorAll(".carte__favori").forEach(function (etoile) {
      if (etoile.getAttribute("aria-pressed") === "true") {
        nombre += 1;
      }
    });
    var compteur = document.getElementById("nb-favoris");
    if (compteur) {
      compteur.textContent = String(nombre);
    }
  }

  /* Un filtre est-il actif (rang, favoris ou catégorie) ? */
  function filtreActif() {
    var filtres = lireFiltres();
    var categorie = document.getElementById("filtre-categorie");
    var tri = document.getElementById("tri-collection");
    var rechercheCollection = document.getElementById("recherche-collection");
    if (document.body.getAttribute("data-mode") === "paquets") {
      return false;                       /* page Paquets : pas de filtres, les cartes ajoutées s'y rangent sur place */
    }
    return (
      filtres.rangs.length > 0 ||
      (!!rechercheCollection && rechercheCollection.value.trim() !== "") ||
      filtres.favoris ||
      (!!categorie && categorie.value !== "") ||
      (!!tri && tri.value !== "date-desc")      /* un autre ordre : les nouvelles cartes ne seraient pas en tête */
    );
  }

  /* Enregistre les filtres choisis puis recharge la collection (page 1) : le serveur
     filtre et pagine. */
  function appliquerFiltresEtRecharger(reglages) {
    return enregistrerPreferences(reglages)
      .then(function () {
        window.location.href = "/";
      })
      .catch(function (erreur) {
        notifier("Filtre non appliqué : " + erreur.message, true);
      });
  }

  /* ------------------------------------------------------ images en erreur */

  /* Si l'image ne charge pas, on affiche le visuel "no-image" à la place. */
  function afficherSansImage(image) {
    var visuel = image.closest(".carte__visuel");
    var vide = visuel && visuel.querySelector(".carte__sans-image");
    image.hidden = true;
    if (vide) {
      vide.hidden = false;
    }
  }

  /* ------------------------------------------------------ aperçu agrandi */

  /* La carte agrandie est dans apercu.js (partagé avec la page Recherche) : ses icônes (étoile, disquette,
     PDF, Word, lien) y sont affichées et agissent sur la vraie carte. */
  function ouvrirApercu(carte, bouton) {
    window.WikiApercu.ouvrir(carte, bouton);
  }

  function texteSelectionne() {
    if (typeof window === "undefined" || !window.getSelection) {
      return false;
    }
    return String(window.getSelection()).length > 0;
  }

  /* Clic n'importe où sur la carte : aperçu, sauf sur l'étoile, la disquette et
     le lien (qui ont leur propre action) ou quand on sélectionne du texte. */
  function surClicCarte(evenement, carte, zoom) {
    var cible = evenement.target;
    var controle = cible && cible.closest ? cible.closest("button, a, label, input") : null;
    if (controle && controle !== zoom) {
      return;
    }
    if (modeSelection()) {                  /* en mode Sélection, un clic coche / décoche la carte */
      var casee = carte.querySelector(".carte__case");
      if (casee) {
        casee.checked = !casee.checked;
        mettreAJourSelection();
      }
      return;
    }
    if (texteSelectionne()) {
      return;
    }
    ouvrirApercu(carte, zoom);
  }

  /* --------------------------------------------------------- notification */

  function notifier(message, erreur) {
    if (notification) {
      notification.remove();
    }
    clearTimeout(minuteur);

    notification = document.createElement("div");
    notification.className = "notification" + (erreur ? " notification--erreur" : "");
    notification.setAttribute("role", erreur ? "alert" : "status");
    notification.textContent = message;
    document.body.appendChild(notification);

    minuteur = setTimeout(function () {
      if (notification) {
        notification.remove();
        notification = null;
      }
    }, erreur ? 7000 : 4500);
  }

  /* ------------------------------------------- enregistrement en image (PNG) */

  function blobEnDataUrl(blob) {
    return new Promise(function (resoudre, rejeter) {
      var lecteur = new FileReader();
      lecteur.onload = function () {
        resoudre(lecteur.result);
      };
      lecteur.onerror = function () {
        rejeter(lecteur.error);
      };
      lecteur.readAsDataURL(blob);
    });
  }

  /* Une image externe ne peut pas être dessinée dans l'export : on la télécharge
     et on l'intègre à la copie sous forme de données. Renvoie true si réussi. */
  function integrerImage(image) {
    var source = image.getAttribute("src") || "";
    if (source.indexOf("data:") === 0) {
      return Promise.resolve(true);
    }
    return fetch(source, { mode: "cors" })
      .then(function (reponse) {
        if (!reponse.ok) {
          throw new Error("HTTP " + reponse.status);
        }
        return reponse.blob();
      })
      .then(blobEnDataUrl)
      .then(function (url) {
        image.setAttribute("src", url);
        image.removeAttribute("loading");
        return true;
      })
      .catch(function () {
        return false;
      });
  }

  /* Dessine la copie de la carte (HTML + CSS) sur un canevas, via une image SVG
     contenant le HTML. Le canevas garde la transparence des coins arrondis. */
  function rendreEnToile(copie, largeur, hauteur) {
    var css = document.getElementById("styles-cartes").textContent;
    var police = window
      .getComputedStyle(document.body)
      .fontFamily.replace(/"/g, "'");
    var xhtml = new XMLSerializer().serializeToString(copie);
    var svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="' + largeur +
      '" height="' + hauteur + '">' +
      '<foreignObject x="0" y="0" width="' + largeur + '" height="' + hauteur + '">' +
      '<div xmlns="http://www.w3.org/1999/xhtml" style="width:' + largeur +
      "px;height:" + hauteur + "px;font-family:" + police + '">' +
      "<style><![CDATA[" + css + "]]></style>" + xhtml +
      "</div></foreignObject></svg>";

    return new Promise(function (resoudre, rejeter) {
      var image = new Image();
      image.onload = function () {
        try {
          var toile = document.createElement("canvas");
          toile.width = largeur;
          toile.height = hauteur;
          toile.getContext("2d").drawImage(image, 0, 0, largeur, hauteur);
          resoudre(toile);
        } catch (erreur) {
          rejeter(erreur);
        }
      };
      image.onerror = function () {
        rejeter(new Error("rendu de la carte impossible"));
      };
      image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    });
  }

  function versBlob(toile, type, qualite) {
    return new Promise(function (resoudre, rejeter) {
      try {
        toile.toBlob(function (blob) {
          if (blob) {
            resoudre(blob);
          } else {
            rejeter(new Error("création de l'image impossible"));
          }
        }, type, qualite);
      } catch (erreur) {
        rejeter(erreur);
      }
    });
  }

  /* Couleurs propres à une carte personnalisée (Créateur de cartes) : elles sont écrites dans son
     attribut style (--c1, --c2, --c3...). Les cartes des rangs n'en ont pas : leurs couleurs viennent
     du CSS du rang. On ne reprend QUE ces variables de couleur (jamais l'inclinaison du survol...),
     pour que l'image, le PDF et le Word gardent le thème choisi à la création, recto et verso. */
  var VARIABLES_DE_COULEUR = ["--c1", "--c2", "--c3", "--texte", "--badge-fond", "--badge-texte",
    "--halo", "--motif"];

  function variablesDeCouleur(carte) {
    var style = (carte.getAttribute && carte.getAttribute("style")) || "";
    return style.split(";").map(function (declaration) {
      return declaration.trim();
    }).filter(function (declaration) {
      var nom = declaration.split(":")[0].trim();
      return VARIABLES_DE_COULEUR.indexOf(nom) !== -1 && /^--[a-z0-9-]+\s*:\s*[#a-z0-9(),.% -]+$/i.test(declaration);
    }).join("; ");
  }

  /* Copie de la carte "telle quelle" (sans boutons), à la taille voulue. */
  function copierPourExport(carte, largeur) {
    var copie = carte.cloneNode(true);
    copie.querySelectorAll(CONTROLES).forEach(function (element) {
      element.remove();
    });
    if (document.body.getAttribute("data-export-categories") === "0") {
      copie.querySelectorAll(".carte__categories").forEach(function (element) {
        element.remove();                   /* réglage « Catégories sur les images exportées » */
      });
    }
    copie.querySelectorAll(".fa__effet").forEach(function (effet) {
      effet.remove();                        /* full-art : les calques PNG sont exportés, pas les effets animés */
    });
    copie.classList.add("carte--export");
    var couleurs = variablesDeCouleur(carte);
    copie.setAttribute("style", (couleurs ? couleurs + "; " : "") + "--u: " + largeur / 300 +
      "px; width: " + largeur + "px;");
    /* Le pied de l'image exportée est mesuré À SA TAILLE (pas celle de la carte de la page) : une seule
       ligne, avec tout ce qui peut tenir (vues, « /jour », statistiques, date et heure). */
    if (window.WikiPied && typeof window.WikiPied.ajusterCopie === "function") {
      try {
        window.WikiPied.ajusterCopie(copie);
      } catch (erreur) {
        /* mesure impossible : on exporte avec la mise en page de base */
      }
    }
    return copie;
  }

  /* Recto : la carte avec son image intégrée. Résultat : { copie, imageIncluse }. */
  function preparerRecto(carte, largeur) {
    var copie = copierPourExport(carte, largeur);
    var image = copie.querySelector(".carte__image");
    var utiliseImage = image && !image.hidden;
    var pret = utiliseImage ? integrerImage(image) : Promise.resolve(true);
    var calques = Promise.all(Array.prototype.slice.call(copie.querySelectorAll(".fa__calque")).map(function (calque) {
      return integrerImage(calque).then(function (reussi) {
        if (!reussi) {
          calque.remove();                   /* un calque illisible n'empêche pas l'export */
        }
      });
    }));

    return Promise.all([pret, calques]).then(function (resultats) {
      var imageIncluse = resultats[0];
      if (!imageIncluse) {
        image.hidden = true;                 /* repli : visuel "no-image" */
        var vide = copie.querySelector(".carte__sans-image");
        if (vide) {
          vide.hidden = false;
        }
      }
      return { copie: copie, imageIncluse: imageIncluse };
    });
  }

  /* Verso : le thème (dégradé et motif) du rang de la carte, avec le logo du jeu au
     milieu (si le dossier logo/ en contient un) et le QR code vers l'article en bas.
     Ils n'apparaissent que sur ce verso. `logo` : image du logo (données) ou null. */
  function preparerVerso(carte, largeur, reglages, logo, recto) {
    var dos = document.createElement("article");
    dos.className = "carte carte--export carte--dos" + (logo ? "" : " carte--dos-sans-logo");
    dos.setAttribute("data-rarete", carte.getAttribute("data-rarete"));
    dos.setAttribute("data-motif", carte.getAttribute("data-motif") || "vagues");
    var couleursDos = variablesDeCouleur(carte);        /* le verso a le thème de la carte, lui aussi */
    dos.setAttribute("style", (couleursDos ? couleursDos + "; " : "") + "--u: " + largeur / 300 +
      "px; width: " + largeur + "px;");

    if (logo) {
      var zone = document.createElement("div");
      zone.className = "carte__logo";
      var image = document.createElement("img");
      image.setAttribute("src", logo);
      image.setAttribute("alt", "");
      zone.appendChild(image);
      dos.appendChild(zone);
    }

    var calquesFA = recto && recto.querySelector ? recto.querySelector(".carte__fullart") : null;
    if (calquesFA) {                       /* full-art : les mêmes calques au dos, sous le logo et le QR code */
      dos.insertBefore(calquesFA.cloneNode(true), dos.firstChild);
    }

    var dessin = carte.getAttribute("data-qr");
    if (dessin) {
      var cote = Math.round((reglages.qr_mm * reglages.dpi) / 25.4);   /* mm -> pixels */
      var qr = document.createElement("span");
      qr.className = "carte__qr";
      qr.setAttribute("style", "width: " + cote + "px; height: " + cote + "px;");
      qr.innerHTML = dessin;
      dos.appendChild(qr);
    }
    return dos;
  }

  /* Image PNG de la carte (disquette). Résultat : { blob, imageIncluse }. */
  function creerImage(carte) {
    var largeur = Number(document.body.getAttribute("data-largeur-export")) || 600;
    var hauteur = Math.round((largeur * 430) / 300);   /* proportions de la carte */

    return preparerRecto(carte, largeur).then(function (recto) {
      return rendreEnToile(recto.copie, largeur, hauteur)
        .then(function (toile) {
          return versBlob(toile, "image/png");
        })
        .then(function (blob) {
          return { blob: blob, imageIncluse: recto.imageIncluse };
        });
    });
  }

  /* Repli : téléchargement classique du navigateur (pas de choix du dossier). */
  function telecharger(blob, fichier) {
    var lien = document.createElement("a");
    var url = URL.createObjectURL(blob);
    lien.href = url;
    lien.download = fichier + ".png";
    document.body.appendChild(lien);
    lien.click();
    lien.remove();
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 10000);
  }

  /* Envoie l'image au serveur local, qui l'écrit dans Export/<rang>/.
     Renvoie le message à afficher. */
  function enregistrer(blob, code, fichier) {
    var jeton = document.body.getAttribute("data-jeton");
    var surServeur =
      (window.location.protocol === "http:" || window.location.protocol === "https:") && jeton;

    if (!surServeur) {
      telecharger(blob, fichier);
      return Promise.resolve(
        "Image téléchargée : " + fichier + ".png (dossier de téléchargement du " +
        "navigateur). Pour l'enregistrer dans Export/, ouvre la page avec python main.py."
      );
    }

    var url =
      "/export?rarete=" + encodeURIComponent(code) +
      "&fichier=" + encodeURIComponent(fichier);
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "image/png", "X-Jeton": jeton },
      body: blob
    })
      .then(function (reponse) {
        return reponse.json().then(function (donnees) {
          return { ok: reponse.ok, donnees: donnees };
        });
      })
      .then(function (resultat) {
        if (!resultat.ok) {
          throw new Error(resultat.donnees.erreur || "erreur du serveur");
        }
        return "Carte enregistrée : " + resultat.donnees.fichier;
      })
      .catch(function (erreur) {
        telecharger(blob, fichier);
        return (
          "Enregistrement dans Export/ impossible (" + erreur.message +
          "). Image téléchargée à la place : " + fichier + ".png"
        );
      });
  }

  function exporterCarte(carte, bouton) {
    if (bouton.getAttribute("aria-busy") === "true") {
      return;
    }
    bouton.setAttribute("aria-busy", "true");

    var code = carte.getAttribute("data-rarete");
    var fichier = carte.getAttribute("data-fichier");
    var imageIncluse = true;

    creerImage(carte)
      .then(function (resultat) {
        imageIncluse = resultat.imageIncluse;
        return enregistrer(resultat.blob, code, fichier);
      })
      .then(function (message) {
        notifier(
          message +
            (imageIncluse
              ? ""
              : " (l'image de l'article n'a pas pu être incluse : accès refusé)")
        );
      })
      .catch(function (erreur) {
        notifier("Échec de l'enregistrement : " + erreur.message, true);
      })
      .then(function () {
        bouton.setAttribute("aria-busy", "false");
      });
  }

  /* ------------------------------------------ documents PDF / Word recto verso */

  function reglagesImpression() {
    try {
      return JSON.parse(document.body.getAttribute("data-impression"));
    } catch (erreur) {
      return { largeur_mm: 63, dpi: 300, marge_mm: 5, reperes: true, qr_mm: 26 };
    }
  }

  /* Petits repères aux quatre coins de la carte, dans la marge, pour la découper. */
  function dessinerReperes(ctx, marge, largeur, hauteur, mm) {
    var decalage = Math.round(1 * mm);
    var longueur = Math.round(3 * mm);
    if (marge < decalage + longueur) {
      return;                                /* marge trop étroite : pas de repères */
    }
    var x0 = marge;
    var y0 = marge;
    var x1 = marge + largeur;
    var y1 = marge + hauteur;

    ctx.strokeStyle = "#444444";
    ctx.lineWidth = Math.max(1, Math.round(0.2 * mm));
    ctx.beginPath();
    [[x0, y0, -1, -1], [x1, y0, 1, -1], [x0, y1, -1, 1], [x1, y1, 1, 1]].forEach(
      function (coin) {
        var x = coin[0];
        var y = coin[1];
        ctx.moveTo(x + coin[2] * decalage, y);
        ctx.lineTo(x + coin[2] * (decalage + longueur), y);
        ctx.moveTo(x, y + coin[3] * decalage);
        ctx.lineTo(x, y + coin[3] * (decalage + longueur));
      }
    );
    ctx.stroke();
  }

  /* Carte + marge blanche + repères de coupe : l'image qui sera placée au centre
     de la feuille. Même taille au recto et au verso, donc même position. */
  function composerPlanche(toileCarte, reglages) {
    var mm = reglages.dpi / 25.4;
    var marge = Math.round(reglages.marge_mm * mm);
    var toile = document.createElement("canvas");
    toile.width = toileCarte.width + 2 * marge;
    toile.height = toileCarte.height + 2 * marge;

    var ctx = toile.getContext("2d");
    ctx.fillStyle = "#ffffff";               /* fond blanc : un JPEG n'a pas de transparence */
    ctx.fillRect(0, 0, toile.width, toile.height);
    ctx.drawImage(toileCarte, marge, marge);
    if (reglages.reperes) {
      dessinerReperes(ctx, marge, toileCarte.width, toileCarte.height, mm);
    }
    return toile;
  }

  function creerPlanche(copie, largeur, hauteur, reglages) {
    return rendreEnToile(copie, largeur, hauteur).then(function (toileCarte) {
      return versBlob(composerPlanche(toileCarte, reglages), "image/jpeg", 0.95);
    });
  }

  /* Envoie recto et verso au serveur local, qui crée le document dans Export/<rang>/.
     Corps de la requête : 4 octets (taille du recto), puis le recto, puis le verso. */
  function envoyerDocument(format, code, fichier, recto, verso) {
    var jeton = document.body.getAttribute("data-jeton");
    var taille = new Uint8Array(4);
    new DataView(taille.buffer).setUint32(0, recto.size);
    var corps = new Blob([taille, recto, verso], { type: "application/octet-stream" });

    var url =
      "/export-document?format=" + encodeURIComponent(format) +
      "&rarete=" + encodeURIComponent(code) +
      "&fichier=" + encodeURIComponent(fichier);
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Jeton": jeton },
      body: corps
    })
      .catch(function () {
        throw new Error("le serveur local est injoignable (lance python main.py)");
      })
      .then(function (reponse) {
        return reponse.json().then(function (donnees) {
          return { ok: reponse.ok, donnees: donnees };
        });
      })
      .then(function (resultat) {
        if (!resultat.ok) {
          throw new Error(resultat.donnees.erreur || "erreur du serveur");
        }
        return "Document enregistré : " + resultat.donnees.fichier;
      });
  }

  /* Lit le logo du dossier logo/ (via le serveur local) et le réduit si besoin : un
     très grand logo alourdirait inutilement la création du document.
     Résultat : { donnees: image PNG (données) ou null, illisible: true si un logo existe
     mais n'a pas pu être lu }. Pas de logo = { donnees: null, illisible: false }. */
  var LOGO_COTE_MAX = 1200;   /* pixels : largement suffisant pour une impression nette */

  function chargerLogo() {
    return fetch("/logo")
      .then(function (reponse) {
        return reponse.ok ? reponse.blob() : null;
      })
      .then(function (blob) {
        if (!blob) {
          return { donnees: null, illisible: false };
        }
        return new Promise(function (resoudre) {
          var url = URL.createObjectURL(blob);
          var image = new Image();
          image.onload = function () {
            try {
              var largeur = image.naturalWidth || 1000;     /* un SVG sans dimensions : 1000 px */
              var hauteur = image.naturalHeight || 1000;
              var echelle = Math.min(1, LOGO_COTE_MAX / Math.max(largeur, hauteur));
              var toile = document.createElement("canvas");
              toile.width = Math.max(1, Math.round(largeur * echelle));
              toile.height = Math.max(1, Math.round(hauteur * echelle));
              toile.getContext("2d").drawImage(image, 0, 0, toile.width, toile.height);
              URL.revokeObjectURL(url);
              resoudre({ donnees: toile.toDataURL("image/png"), illisible: false });
            } catch (erreur) {
              resoudre({ donnees: null, illisible: true });
            }
          };
          image.onerror = function () {
            URL.revokeObjectURL(url);
            resoudre({ donnees: null, illisible: true });
          };
          image.src = url;
        });
      })
      .catch(function () {
        return { donnees: null, illisible: false };   /* serveur muet : pas de logo */
      });
  }

  /* Boutons PDF et Word : crée le document recto verso. Il passe par le serveur local
     (le navigateur ne sait pas fabriquer ces fichiers ni écrire dans un dossier). */
  function exporterDocument(carte, bouton, format) {
    if (bouton.getAttribute("aria-busy") === "true") {
      return;
    }
    var jeton = document.body.getAttribute("data-jeton");
    if ((window.location.protocol !== "http:" && window.location.protocol !== "https:") || !jeton) {
      notifier(
        "Les documents PDF et Word sont créés par le serveur local : lance " +
        "l'application avec python main.py, puis utilise la page qui s'ouvre.",
        true
      );
      return;
    }
    bouton.setAttribute("aria-busy", "true");

    var code = carte.getAttribute("data-rarete");
    var fichier = carte.getAttribute("data-fichier");
    var reglages = reglagesImpression();
    var largeur = Math.round((reglages.largeur_mm * reglages.dpi) / 25.4);
    var hauteur = Math.round((largeur * 430) / 300);
    var imageIncluse = true;
    var logoIllisible = false;

    preparerRecto(carte, largeur)
      .then(function (recto) {
        imageIncluse = recto.imageIncluse;
        return chargerLogo().then(function (logo) {
          logoIllisible = logo.illisible;
          return Promise.all([
            creerPlanche(recto.copie, largeur, hauteur, reglages),
            creerPlanche(
              preparerVerso(carte, largeur, reglages, logo.donnees, recto.copie),
              largeur, hauteur, reglages
            )
          ]);
        });
      })
      .then(function (planches) {
        return envoyerDocument(format, code, fichier, planches[0], planches[1]);
      })
      .then(function (message) {
        notifier(
          message +
            (imageIncluse
              ? ""
              : " (l'image de l'article n'a pas pu être incluse : accès refusé)") +
            (logoIllisible
              ? " (le logo du dossier logo/ n'a pas pu être lu : verso créé sans logo)"
              : "")
        );
      })
      .catch(function (erreur) {
        notifier("Échec de l'enregistrement : " + erreur.message, true);
      })
      .then(function () {
        bouton.setAttribute("aria-busy", "false");
      });
  }

  /* ------------------------------------------------------- mise en route */

  var favoris = lireFavoris();

  /* Branche les boutons et les comportements d'UNE carte : au chargement de la page, puis
     pour chaque carte ajoutée en ouvrant un paquet. */
  function initialiserCarte(carte) {
    var titre = carte.getAttribute("data-titre");
    var image = carte.querySelector(".carte__image");
    var etoile = carte.querySelector(".carte__favori");
    var disquette = carte.querySelector(".carte__sauver");
    var boutonPdf = carte.querySelector(".carte__pdf");
    var boutonWord = carte.querySelector(".carte__word");
    var zoom = carte.querySelector(".carte__zoom");

    carte.addEventListener("click", function (evenement) {
      surClicCarte(evenement, carte, zoom);
    });

    var caseSelection = carte.querySelector(".carte__case");
    if (caseSelection) {
      caseSelection.addEventListener("change", mettreAJourSelection);
    }

    if (disquette) {
      disquette.addEventListener("click", function () {
        exporterCarte(carte, disquette);
      });
    }

    if (boutonPdf) {
      boutonPdf.addEventListener("click", function () {
        exporterDocument(carte, boutonPdf, "pdf");
      });
    }

    if (boutonWord) {
      boutonWord.addEventListener("click", function () {
        exporterDocument(carte, boutonWord, "docx");
      });
    }

    if (image) {
      if (image.complete && image.naturalWidth === 0) {
        afficherSansImage(image);
      } else {
        image.addEventListener("error", function () {
          afficherSansImage(image);
        });
      }
    }

    if (etoile) {
      var identifiant = carte.getAttribute("data-id");
      var dansLaBase = surServeur() && !!identifiant;
      if (!dansLaBase) {
        /* Page sans serveur local : favoris gardés dans le navigateur (moins durable) */
        definirEtat(etoile, favoris.indexOf(titre) !== -1);
      }

      etoile.addEventListener("click", function () {
        var nouvelEtat = etoile.getAttribute("aria-pressed") !== "true";
        definirEtat(etoile, nouvelEtat);
        mettreAJourFavoris();

        if (dansLaBase) {
          enregistrerFavori(identifiant, nouvelEtat).catch(function (erreur) {
            definirEtat(etoile, !nouvelEtat);       /* échec : on revient en arrière */
            mettreAJourFavoris();
            notifier("Favori non enregistré : " + erreur.message, true);
          });
          return;
        }
        favoris = favoris.filter(function (t) {
          return t !== titre;
        });
        if (nouvelEtat) {
          favoris.push(titre);
        }
        ecrireFavoris(favoris);
      });
    }
  }

  document.querySelectorAll(".carte").forEach(initialiserCarte);

  /* Boutons de filtre : un clic active / désactive, la sélection est enregistrée.
     Rappelée après l'ouverture d'un paquet, qui renouvelle ces boutons. */
  function brancherPastilles() {
    document.querySelectorAll(".pastille").forEach(function (bouton) {
      bouton.addEventListener("click", function () {
        bouton.setAttribute(
          "aria-pressed",
          bouton.getAttribute("aria-pressed") === "true" ? "false" : "true"
        );
        var filtres = lireFiltres();
        appliquerFiltresEtRecharger({
          "ui.filtre_rangs": filtres.rangs,
          "ui.favoris_seulement": filtres.favoris
        });
      });
    });
  }
  brancherPastilles();

  /* Liste déroulante des catégories : filtre la collection (rechargement de la page 1). */
  var filtreCategorie = document.getElementById("filtre-categorie");
  if (filtreCategorie) {
    filtreCategorie.addEventListener("change", function () {
      appliquerFiltresEtRecharger({
        "ui.filtre_categorie": filtreCategorie.value === "" ? null : Number(filtreCategorie.value)
      });
    });
  }

  /* Liste déroulante « Trier » : l'ordre d'affichage de la collection (rechargement de la page 1). */
  /* Recherche d'une ou plusieurs cartes par leur titre (plusieurs mots : tous doivent y figurer ;
     accents et majuscules ignorés). La page est rechargée avec le résultat, comme pour les filtres. */
  var CLE_FOCUS_RECHERCHE = "wikicartes:recherche-focus";
  var champRecherche = document.getElementById("recherche-collection");
  var boutonEffacerRecherche = document.getElementById("recherche-effacer");
  var minuteurRecherche = null;

  function lancerRecherche() {
    clearTimeout(minuteurRecherche);
    minuteurRecherche = null;
    try {
      sessionStorage.setItem(CLE_FOCUS_RECHERCHE, "1");          /* on redonne le focus au rechargement */
    } catch (erreur) {
      /* stockage indisponible : le focus ne sera pas rendu */
    }
    appliquerFiltresEtRecharger({ "ui.recherche": champRecherche.value.trim() });
  }

  if (champRecherche) {
    champRecherche.addEventListener("input", function () {
      if (boutonEffacerRecherche) {
        boutonEffacerRecherche.hidden = champRecherche.value === "";
      }
      clearTimeout(minuteurRecherche);
      minuteurRecherche = setTimeout(lancerRecherche, 500);       /* on attend la fin de la frappe */
    });
    champRecherche.addEventListener("keydown", function (evenement) {
      if (evenement.key === "Enter") {
        evenement.preventDefault();
        lancerRecherche();
      } else if (evenement.key === "Escape" && champRecherche.value !== "") {
        champRecherche.value = "";
        lancerRecherche();
      }
    });
    if (boutonEffacerRecherche) {
      boutonEffacerRecherche.addEventListener("click", function () {
        champRecherche.value = "";
        lancerRecherche();
      });
    }
    try {
      if (sessionStorage.getItem(CLE_FOCUS_RECHERCHE) === "1") {
        sessionStorage.removeItem(CLE_FOCUS_RECHERCHE);
        champRecherche.focus();
        var fin = champRecherche.value.length;
        if (champRecherche.setSelectionRange) {
          champRecherche.setSelectionRange(fin, fin);
        }
      }
    } catch (erreur) {
      /* stockage indisponible */
    }
  }

  var triCollection = document.getElementById("tri-collection");
  if (triCollection) {
    triCollection.addEventListener("change", function () {
      appliquerFiltresEtRecharger({ "ui.tri": triCollection.value });
    });
  }

  /* ----------------------------------------- mode Sélection : classer par catégories */

  function modeSelection() {
    return document.body.classList.contains("mode-selection");
  }

  function cartesSelectionnees() {
    return Array.prototype.filter.call(document.querySelectorAll(".carte"), function (carte) {
      var casee = carte.querySelector(".carte__case");
      return !!casee && casee.checked;
    });
  }

  function categoriesChoisies() {
    return Array.prototype.filter
      .call(document.querySelectorAll("[data-selection-categorie]"), function (casee) {
        return casee.checked;
      })
      .map(function (casee) {
        return Number(casee.value);
      });
  }

  /* Texte de la barre, boutons « Ajouter » / « Retirer » et contour des cartes cochées. */
  function mettreAJourSelection() {
    var cochees = cartesSelectionnees();
    var categories = categoriesChoisies();
    var compte = document.getElementById("selection-compte");
    if (compte) {
      compte.textContent =
        cochees.length === 0
          ? "Aucune carte sélectionnée"
          : cochees.length + (cochees.length > 1 ? " cartes sélectionnées" : " carte sélectionnée");
    }
    var nombreCategories = document.getElementById("selection-nb-categories");
    if (nombreCategories) {
      nombreCategories.textContent = "(" + categories.length + ")";
    }
    var possible = cochees.length > 0 && categories.length > 0;
    ["selection-ajouter", "selection-retirer"].forEach(function (id) {
      var bouton = document.getElementById(id);
      if (bouton) {
        bouton.disabled = !possible;
      }
    });
    var boutonSupprimer = document.getElementById("selection-supprimer");
    if (boutonSupprimer) {                          /* supprimer ne demande aucune catégorie */
      boutonSupprimer.disabled = cochees.length === 0;
    }
    document.querySelectorAll(".carte").forEach(function (carte) {
      var casee = carte.querySelector(".carte__case");
      carte.classList.toggle("carte--selectionnee", !!casee && casee.checked);
    });
  }

  function basculerModeSelection(actif) {
    document.body.classList.toggle("mode-selection", actif);
    var bouton = document.getElementById("bouton-selection");
    if (bouton) {
      bouton.setAttribute("aria-pressed", actif ? "true" : "false");
    }
    var barre = document.getElementById("barre-selection");
    if (barre) {
      barre.hidden = !actif;
    }
    if (!actif) {
      cocherToutes(false);
    }
    mettreAJourSelection();
  }

  function cocherToutes(coche) {
    document.querySelectorAll(".carte").forEach(function (carte) {
      var casee = carte.querySelector(".carte__case");
      if (casee) {
        casee.checked = coche;
      }
    });
    mettreAJourSelection();
  }

  /* Envoie le classement au serveur, puis met à jour les bandeaux des cartes concernées. */
  function classerSelection(action) {
    if (!surServeur()) {
      notifier(
        "Le classement nécessite le serveur local : lance python main.py, puis utilise la " +
        "page qui s'ouvre.", true
      );
      return Promise.resolve();
    }
    var cartes = cartesSelectionnees().filter(function (carte) {
      return !!carte.getAttribute("data-id");
    });
    var categories = categoriesChoisies();
    if (cartes.length === 0 || categories.length === 0) {
      return Promise.resolve();
    }
    return fetch("/api/categories/assigner", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Jeton": document.body.getAttribute("data-jeton")
      },
      body: JSON.stringify({
        ids: cartes.map(function (carte) {
          return Number(carte.getAttribute("data-id"));
        }),
        categories: categories,
        action: action
      })
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
        cartes.forEach(function (carte) {
          var zone = carte.querySelector(".carte__categories");
          var html = donnees.bandeaux[carte.getAttribute("data-id")];
          if (zone && html !== undefined) {
            zone.innerHTML = html;
          }
        });
        notifier(
          (action === "ajouter" ? "Catégories ajoutées" : "Catégories retirées") +
            " pour " + cartes.length + (cartes.length > 1 ? " cartes." : " carte.")
        );
      })
      .catch(function (erreur) {
        notifier("Classement impossible : " + erreur.message, true);
      });
  }

  /* Met les cartes cochées dans la corbeille (suppression réversible : voir « Corbeille »),
     puis les retire de la page et met à jour boutons de filtre, compteurs et pagination. */
  function supprimerSelection() {
    if (!surServeur()) {
      notifier(
        "La suppression nécessite le serveur local : lance python main.py, puis utilise la " +
        "page qui s'ouvre.", true
      );
      return Promise.resolve();
    }
    var cartes = cartesSelectionnees().filter(function (carte) {
      return !!carte.getAttribute("data-id");
    });
    if (cartes.length === 0) {
      return Promise.resolve();
    }
    return fetch("/api/corbeille/mettre", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Jeton": document.body.getAttribute("data-jeton")
      },
      body: JSON.stringify({
        ids: cartes.map(function (carte) {
          return Number(carte.getAttribute("data-id"));
        }),
        page: Number(document.body.getAttribute("data-page")) || 1
      })
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
        jouerSon("corbeille");                        /* des cartes vont à la corbeille */
        cartes.forEach(function (carte) {
          var cadre = carte.parentNode;
          if (cadre && cadre.remove) {
            cadre.remove();
          }
        });
        var resume = document.querySelector(".resume");
        if (resume && donnees.resume !== undefined) {
          resume.innerHTML = donnees.resume;
          brancherPastilles();
        }
        var infos = document.getElementById("infos-collection");
        if (infos && donnees.infos !== undefined) {
          infos.textContent = donnees.infos;
        }
        majDoublons(donnees.doublons);
        majCompteurs(donnees.compteurs);
        majBandeaux(donnees.bandeaux);
        ["pagination-haut", "pagination-bas"].forEach(function (id) {
          var zone = document.getElementById(id);
          if (zone && donnees.pagination !== undefined) {
            zone.innerHTML = donnees.pagination;
          }
        });
        if (window.WikiCorbeille) {
          window.WikiCorbeille.definir(donnees.corbeille);
        }
        mettreAJourSelection();
        notifier(
          donnees.deplacees + (donnees.deplacees > 1 ? " cartes déplacées" : " carte déplacée") +
            " dans la corbeille (restauration possible)."
        );
        var restantes = document.querySelectorAll(".carte").length;
        if (restantes === 0 && donnees.total > 0) {
          setTimeout(function () { window.location.reload(); }, 800);   /* page suivante */
        } else if (restantes === 0) {
          var vide = document.getElementById("collection-vide");
          if (vide) {
            vide.hidden = false;
          }
        }
      })
      .catch(function (erreur) {
        notifier("Suppression impossible : " + erreur.message, true);
      });
  }

  var boutonSelection = document.getElementById("bouton-selection");
  if (boutonSelection) {
    boutonSelection.addEventListener("click", function () {
      basculerModeSelection(!modeSelection());
    });
  }
  [["selection-tout", true], ["selection-aucun", false]].forEach(function (reglage) {
    var bouton = document.getElementById(reglage[0]);
    if (bouton) {
      bouton.addEventListener("click", function () {
        cocherToutes(reglage[1]);
      });
    }
  });
  var boutonSupprimerSel = document.getElementById("selection-supprimer");
  if (boutonSupprimerSel) {
    boutonSupprimerSel.addEventListener("click", supprimerSelection);
  }
  [["selection-ajouter", "ajouter"], ["selection-retirer", "retirer"]].forEach(function (reglage) {
    var bouton = document.getElementById(reglage[0]);
    if (bouton) {
      bouton.addEventListener("click", function () {
        classerSelection(reglage[1]);
      });
    }
  });
  document.querySelectorAll("[data-selection-categorie]").forEach(function (casee) {
    casee.addEventListener("change", mettreAJourSelection);
  });

  /* Curseur de taille des cartes : effet immédiat ET enregistrement À LA VOLÉE (dès qu'on bouge le curseur, sans attendre
     qu'on le lâche) ; les envois sont espacés de 250 ms au plus et le dernier est toujours envoyé. AUCUN message : tout
     se passe sans rien écrire à l'écran. */
  var curseur = document.getElementById("taille-cartes");
  var affichage = document.getElementById("taille-valeur");
  var reinitialiser = document.getElementById("taille-reinitialiser");

  if (curseur) {
    var envoiTaille = { minuteur: null, derniere: null, enregistree: Number(curseur.value) };
    var envoyerTaille = function () {
      clearTimeout(envoiTaille.minuteur);
      envoiTaille.minuteur = null;
      var largeur = Number(curseur.value);
      if (largeur === envoiTaille.enregistree) {
        return Promise.resolve();
      }
      envoiTaille.derniere = largeur;
      return enregistrerPreferences({ LARGEUR_CARTE: largeur }).then(function (reponse) {
        if (reponse === null) {                                    /* page ouverte sans le serveur local */
          return;
        }
        envoiTaille.enregistree = largeur;
      }).catch(function () {
        /* silencieux : au prochain mouvement du curseur, l'envoi est retenté */
      });
    };

    curseur.addEventListener("input", function () {
      var largeur = Number(curseur.value);
      document.body.style.setProperty("--largeur-carte", largeur + "px");
      if (affichage) {
        affichage.textContent = largeur + " px";
      }
      if (envoiTaille.minuteur === null) {
        envoiTaille.minuteur = setTimeout(envoyerTaille, 250);     /* en route pendant qu'on bouge, pas un envoi par pixel */
      }
    });
    curseur.addEventListener("change", envoyerTaille);
    curseur.addEventListener("pointerup", envoyerTaille);
    if (window.addEventListener) window.addEventListener("pagehide", function () {   /* on quitte la page avec un envoi en attente : on l'envoie */
      var largeur = Number(curseur.value);
      if (largeur !== envoiTaille.enregistree && surServeur()) {
        try {
          fetch("/api/preferences", {
            method: "POST", keepalive: true,
            headers: { "Content-Type": "application/json", "X-Jeton": document.body.getAttribute("data-jeton") },
            body: JSON.stringify({ LARGEUR_CARTE: largeur })
          });
        } catch (erreur) { /* rien à faire : la page se ferme */ }
      }
    });
  }

  if (reinitialiser) {
    reinitialiser.addEventListener("click", function () {
      if (!surServeur()) {
        notifier(
          "La taille n'est enregistrée que si la page est ouverte avec le serveur local " +
          "(python main.py).", true
        );
        return;
      }
      enregistrerPreferences({ LARGEUR_CARTE: null })
        .then(function () {
          window.location.reload();                 /* la page revient à la taille de config.py */
        })
        .catch(function (erreur) {
          notifier("Réinitialisation impossible : " + erreur.message, true);
        });
    });
  }

  /* ------------------------------------------------------ paquet de cartes */
  /* Clic sur le booster : son animation d'attente tourne pendant que le serveur tire les cartes
     (au moins `attente` ms), puis il s'ouvre et disparaît (`sortie` ms) et les cartes
     apparaissent en fondu, l'une après l'autre. Le choix de l'animation (réglage
     BOOSTER_ANIMATION) et ses durées viennent de la page (data-animation, data-animations) ;
     les mouvements sont dans le CSS (classes paquet--attente, paquet--sortie...). */

  /* Halo doré autour des cartes révélées (même HTML que HALO_HTML dans wikicartes/rendu.py) */
  var HALO_HTML =
    '<span class="halo" aria-hidden="true"><span class="halo__lueur"></span>' +
    '<span class="halo__anneau"><span class="halo__tour"></span></span></span>';

  function dureeHalo() {
    return Number(document.body.getAttribute("data-halo")) || 0;     /* secondes ; 0 : pas de halo */
  }

  /* Retire les halos du DOM quand leur animation est finie (ils sont alors invisibles). */
  function nettoyerHalosApres(halos, delaiMs) {
    if (halos.length === 0) {
      return;
    }
    setTimeout(function () {
      halos.forEach(function (halo) {
        if (halo.remove) {
          halo.remove();
        }
      });
    }, dureeHalo() * 1000 + delaiMs + 600);
  }

  var DUREE_RETOUR_DEFAUT = 350;    /* ms : le booster revient en fondu */
  var PAUSE_ENTREE = 55;            /* ms entre deux cartes qui apparaissent */
  var paquetOuvert = false;         /* vrai pendant qu'un paquet s'ouvre */

  function attendre(duree) {
    return new Promise(function (resoudre) {
      setTimeout(resoudre, duree);
    });
  }

  function mouvementReduit() {
    return (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  /* Durées de l'animation choisie : { attente, sortie, retour } en ms (0 = pas d'animation). */
  function reglagesAnimation(paquet) {
    var nom = paquet.getAttribute("data-animation") || "aucune";
    var table = {};
    try {
      table = JSON.parse(paquet.getAttribute("data-animations") || "{}");
    } catch (erreur) {
      table = {};
    }
    var duree = table[nom];
    if (!duree) {                                  /* animation inconnue : on ouvre sans animation */
      return { attente: 0, sortie: 0, retour: 0 };
    }
    return {
      attente: Number(duree.attente) || 0,
      sortie: Number(duree.sortie) || 0,
      retour: duree.retour === undefined ? DUREE_RETOUR_DEFAUT : Number(duree.retour) || 0
    };
  }

  /* ------------------------------------------------ décompte avant l'ouverture */

  /* Le serveur envoie, en direct, l'avancement du tirage : le temps restant avant l'ouverture,
     CALCULÉ d'après les réglages (pause entre requêtes, durée mesurée d'une requête). Le décompte
     le suit : quand il arrive à 0, le tirage est terminé et c'est là que le paquet s'ouvre. */

  function creerDecompte(paquet) {
    var zone = document.getElementById("paquet-decompte");
    var actif = !!zone && paquet.getAttribute("data-decompte") === "1";
    var nombre = document.getElementById("paquet-decompte-nombre");
    var libelle = document.getElementById("paquet-decompte-libelle");
    var progres = document.getElementById("paquet-decompte-progres");
    var section = zone ? zone.parentNode : null;
    var etat = { echeance: 0, debut: 0, minuteur: null, termine: false };

    function reste() {
      return Math.max(0, (etat.echeance - Date.now()) / 1000);
    }

    function afficher() {
      var secondes = reste();
      var ecoule = (Date.now() - etat.debut) / 1000;
      var total = ecoule + secondes;
      nombre.textContent = etat.termine ? "0" : secondes > 0 ? String(Math.ceil(secondes)) : "…";
      if (progres) {
        var ratio = etat.termine ? 1 : total > 0 ? Math.min(1, ecoule / total) : 0;
        progres.style.transform = "scaleX(" + ratio.toFixed(3) + ")";
      }
    }

    function montrer() {
      zone.hidden = false;
      if (section && section.classList) {
        section.classList.add("zone-paquet--decompte");
      }
      if (etat.minuteur === null) {
        etat.minuteur = setInterval(afficher, 100);
      }
    }

    return {
      /* plan | etape | ralentissement : { duree (s), delai (s, pour un ralentissement) } */
      evenement: function (evt) {
        if (!actif) {
          return;
        }
        var duree = Number(evt.duree) || 0;
        if (etat.debut === 0) {
          etat.debut = Date.now();
        }
        etat.echeance = Date.now() + duree * 1000;
        etat.termine = false;
        libelle.textContent =
          evt.type === "ralentissement"
            ? "Wikipédia demande de patienter · ouverture dans"
            : "Ouverture dans";
        if (duree >= 1 || !zone.hidden) {          /* un tirage très court ne montre pas de décompte */
          montrer();
          afficher();
        }
      },
      /* Le tirage est terminé : le décompte tombe à 0 (le paquet s'ouvre aussitôt). */
      terminer: function () {
        if (!actif || zone.hidden) {
          return;
        }
        etat.termine = true;
        afficher();
      },
      masquer: function () {
        if (etat.minuteur !== null) {
          clearInterval(etat.minuteur);
          etat.minuteur = null;
        }
        if (zone) {
          zone.hidden = true;
        }
        if (section && section.classList) {
          section.classList.remove("zone-paquet--decompte");
        }
      }
    };
  }

  /* Lit le flux d'avancement (une ligne JSON par événement). Renvoie les données du paquet. */
  function lireFlux(reponse, surEvenement) {
    var final = null;
    var erreur = null;

    function traiter(ligne) {
      if (ligne.trim() === "") {
        return;
      }
      var evt;
      try {
        evt = JSON.parse(ligne);
      } catch (e) {
        return;
      }
      if (evt.type === "fin") {
        final = evt.donnees;
      } else if (evt.type === "erreur") {
        erreur = new Error(evt.message || "erreur du serveur");
      } else {
        surEvenement(evt);
      }
    }

    function conclure() {
      if (erreur) {
        throw erreur;
      }
      if (!final) {
        throw new Error("la réponse du serveur est incomplète");
      }
      return final;
    }

    if (reponse.body && reponse.body.getReader && typeof TextDecoder !== "undefined") {
      var lecteur = reponse.body.getReader();
      var decodeur = new TextDecoder("utf-8");
      var reste = "";
      var boucle = function () {
        return lecteur.read().then(function (morceau) {
          if (morceau.done) {
            traiter(reste);
            return conclure();
          }
          reste += decodeur.decode(morceau.value, { stream: true });
          var lignes = reste.split("\n");
          reste = lignes.pop();
          lignes.forEach(traiter);
          return boucle();
        });
      };
      return boucle();
    }
    return reponse.text().then(function (texte) {      /* navigateur sans lecture progressive */
      texte.split("\n").forEach(traiter);
      return conclure();
    });
  }

  function demanderPaquetEnFlux(surEvenement) {
    return fetch("/api/paquet/flux", {
      method: "POST",
      headers: { "X-Jeton": document.body.getAttribute("data-jeton") }
    })
      .catch(function () {
        throw new Error("le serveur local est injoignable (lance python main.py)");
      })
      .then(function (reponse) {
        if (!reponse.ok) {
          return reponse.json().then(function (donnees) {
            throw new Error(donnees.erreur || "erreur du serveur");
          });
        }
        return lireFlux(reponse, surEvenement);
      });
  }

  function demanderPaquet() {
    return fetch("/api/paquet", {
      method: "POST",
      headers: { "X-Jeton": document.body.getAttribute("data-jeton") }
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

  /* Met à jour les nombres entre parenthèses de la liste des catégories : « Sport (4) », « Sans
     catégorie (12) », « Doublons (3) »... `compteurs` : {"": toute la collection, "-1": sans
     catégorie, "-2": doublons, "<id>": cartes de la catégorie}. */
  function majCompteurs(compteurs) {
    var liste = document.getElementById("filtre-categorie");
    if (!liste || !compteurs || !liste.querySelectorAll) {
      return;
    }
    Array.prototype.forEach.call(liste.querySelectorAll("option"), function (option) {
      var nom = option.getAttribute("data-nom");
      if (nom !== null && Object.prototype.hasOwnProperty.call(compteurs, option.value)) {
        option.textContent = nom + " (" + compteurs[option.value] + ")";
      }
    });
  }

  /* ---------------------- statistiques des cartes : elles arrivent après, en arrière-plan */

  /* Modifications et liens entrants demandent une requête par carte : le serveur les récupère
     poliment après l'ouverture du paquet. Tant qu'il manque quelque chose (data-stats="incomplet"),
     la page demande les chiffres à jour toutes les quelques secondes (au plus ~25 minutes). */
  var suiviStats = { minuteur: null, tours: 0, enCours: false };

  function cartesIncompletes() {
    return Array.prototype.slice.call(document.querySelectorAll('.carte[data-stats="incomplet"]'))
      .filter(function (carte) {
        return !!carte.getAttribute("data-id");
      });
  }

  function rafraichirStats() {
    var cartes = cartesIncompletes().slice(0, 100);
    if (cartes.length === 0 || !surServeur()) {
      return Promise.resolve(false);
    }
    var ids = cartes.map(function (carte) {
      return carte.getAttribute("data-id");
    }).join(",");
    return fetch("/api/cartes/stats?ids=" + ids, {
      headers: { "X-Jeton": document.body.getAttribute("data-jeton") }
    })
      .then(function (reponse) {
        return reponse.ok ? reponse.json() : null;
      })
      .then(function (donnees) {
        if (!donnees || !donnees.cartes) {
          return false;
        }
        cartes.forEach(function (carte) {
          var info = donnees.cartes[carte.getAttribute("data-id")];
          var zone = info ? carte.querySelector(".carte__stats") : null;
          if (zone) {
            zone.innerHTML = info.html;
            carte.setAttribute("data-stats", info.complet ? "complet" : "incomplet");
          }
        });
        return true;
      })
      .catch(function () {
        return false;                         /* le serveur est peut-être arrêté : on réessaiera */
      });
  }

  function planifierStats() {
    if (!surServeur() || cartesIncompletes().length === 0) {
      return;
    }
    suiviStats.tours = 0;                               /* de nouvelles cartes : on repart pour un tour */
    if (suiviStats.minuteur !== null || suiviStats.enCours) {
      return;                                           /* une seule série de demandes à la fois */
    }
    var tour = function () {
      suiviStats.minuteur = null;
      if (cartesIncompletes().length === 0 || suiviStats.tours >= 90) {
        return;
      }
      suiviStats.tours += 1;
      suiviStats.enCours = true;
      rafraichirStats().then(function () {
        suiviStats.enCours = false;
        suiviStats.minuteur = setTimeout(tour, suiviStats.tours < 20 ? 7000 : 20000);
      });
    };
    suiviStats.minuteur = setTimeout(tour, 5000);
  }

  /* Met à jour le nombre affiché dans « Doublons (N) » de la liste des catégories. */
  function majDoublons(nombre) {
    var liste = document.getElementById("filtre-categorie");
    if (!liste || nombre === undefined || !liste.querySelectorAll) {
      return;
    }
    Array.prototype.forEach.call(liste.querySelectorAll("option"), function (option) {
      if (option.value === "-2") {
        option.textContent = (option.getAttribute("data-nom") || "Doublons") + " (" + nombre + ")";
      }
    });
  }

  /* Met à jour les bandeaux de cartes déjà affichées : {identifiant: HTML}. Utile pour le
     bandeau « Doublon », qui apparaît ou disparaît quand une carte du même titre arrive ou part. */
  function majBandeaux(bandeaux) {
    if (!bandeaux) {
      return;
    }
    document.querySelectorAll(".carte").forEach(function (carte) {
      var html = bandeaux[carte.getAttribute("data-id")];
      var zone = html === undefined ? null : carte.querySelector(".carte__categories");
      if (zone) {
        zone.innerHTML = html;
      }
    });
  }

  /* Les nouvelles cartes se placent en tête de la collection et apparaissent en fondu ;
     les boutons de filtre, le compteur et la pagination sont mis à jour. Si l'on regarde une
     autre page ou une collection filtrée, on revient à la page 1 sans filtre, où les nouvelles
     cartes apparaissent en fondu (?nouveau=N). */
  function afficherNouvellesCartes(donnees) {
    if (surServeur() && (document.body.getAttribute("data-page") !== "1" || filtreActif())) {
      return enregistrerPreferences({
        "ui.filtre_rangs": [],
        "ui.favoris_seulement": false,
        "ui.filtre_categorie": null,
        "ui.recherche": "",
        "ui.tri": (document.getElementById("tri-collection") &&
          document.getElementById("tri-collection").getAttribute("data-defaut")) || "date-desc"
      })
        .catch(function () {})
        .then(function () {
          window.location.href = "/?nouveau=" + donnees.nombre;
        });
    }

    if (donnees.nombre > 0 && !donnees.son_arrivee_fait) {
      jouerSon("arrivee");                            /* les cartes arrivent dans la collection (déjà joué carte par carte sur téléphone) */

    }
    var resume = document.querySelector(".resume");
    if (resume) {
      resume.innerHTML = donnees.resume;
      brancherPastilles();
    }
    var infos = document.getElementById("infos-collection");
    if (infos) {
      infos.textContent = donnees.infos;
    }
    majDoublons(donnees.doublons);
    majCompteurs(donnees.compteurs);
    majBandeaux(donnees.bandeaux);
    if (donnees.avertissement) {                      /* ex. Wikipédia n'a pas répondu : paquet incomplet */
      notifier(donnees.avertissement, true);
    }
    var vide = document.getElementById("collection-vide");
    if (vide) {
      vide.hidden = true;
    }
    if (document.body.getAttribute("data-mode") === "paquets") {
      return;                          /* page Paquets : les cartes sont déjà dans la collection, on ne les montre pas ici */
    }
    ["pagination-haut", "pagination-bas"].forEach(function (id) {
      var zone = document.getElementById(id);
      if (zone && donnees.pagination !== undefined) {
        zone.innerHTML = donnees.pagination;
      }
    });

    var grille = document.getElementById("grille");
    grille.insertAdjacentHTML("afterbegin", donnees.cartes);
    var cadres = Array.prototype.slice.call(grille.children, 0, donnees.nombre);
    var halos = [];
    cadres.forEach(function (cadre, i) {
      cadre.classList.add("carte-cadre--entree");
      cadre.setAttribute("style", "--delai: " + i * PAUSE_ENTREE + "ms");
      initialiserCarte(cadre.querySelector(".carte"));
      if (dureeHalo() > 0 && cadre.insertAdjacentHTML) {          /* le halo fait le tour de la carte */
        cadre.insertAdjacentHTML("afterbegin", HALO_HTML);
        var halo = cadre.querySelector ? cadre.querySelector(".halo") : null;
        if (halo) {
          halos.push(halo);
        }
      }
    });
    nettoyerHalosApres(halos, cadres.length * PAUSE_ENTREE);
    planifierStats();                                 /* les statistiques des nouvelles cartes arrivent */

    /* La page ne garde que « cartes par page » cartes : les plus anciennes passent à la page 2. */
    var parPage = Number(document.body.getAttribute("data-par-page")) || donnees.par_page;
    Array.prototype.slice.call(grille.children, parPage).forEach(function (cadre) {
      cadre.remove();
    });

    if (typeof grille.scrollIntoView === "function" && grille.getBoundingClientRect) {
      if (grille.getBoundingClientRect().top > window.innerHeight * 0.55) {
        grille.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
    return Promise.resolve();
  }

  /* Fichier d'aperçu ouvert sans serveur : cartes d'exemple pour voir l'animation du paquet. */
  function donneesDemo() {
    var element = document.getElementById("donnees-demo");
    if (!element) {
      return null;
    }
    try {
      return JSON.parse(element.textContent);
    } catch (erreur) {
      return null;
    }
  }

  /* Page ouverte sans serveur (aperçu) : on joue un décompte de 3 secondes pour le montrer. */
  function simulerTirage(demo, decompte, reduit) {
    var secondes = reduit ? 0 : 3;
    decompte.evenement({ type: "plan", duree: secondes });
    return attendre(secondes * 1000 || 300).then(function () {
      return demo;
    });
  }

  /* ------------------------------------------------ paquet bloqué : décompte en minutes tant que la réserve n'est pas complète */

  /* Joue le son d'un événement (réglé dans Configuration → Sons et musique) ; sans effet si aucun son n'est choisi. */
  function arreterSon(evenement) {
    try {
      if (typeof window !== "undefined" && window.WikiSons && window.WikiSons.arreter) {
        window.WikiSons.arreter(evenement);
      }
    } catch (erreur) { /* sans importance */ }
  }

  function jouerSon(evenement) {
    try {
      if (typeof window !== "undefined" && window.WikiSons) {
        window.WikiSons.jouer(evenement);
      }
    } catch (erreur) { /* un son qui ne joue pas ne doit jamais gêner */ }
  }

  var minuteurAttente = null;
  var minuteurSecondes = null;
  var finAttente = 0;                      /* instant (ms) où le prochain paquet sera prêt, d'après la dernière estimation */

  function deuxChiffres(n) {
    return (n < 10 ? "0" : "") + n;
  }

  /* Affiche le temps restant en minutes ET secondes ; à zéro, on redemande tout de suite l'état au serveur. */
  function dessinerAttente() {
    var restant = Math.max(0, Math.ceil((finAttente - Date.now()) / 1000));
    var minutes = document.getElementById("paquet-attente-minutes");
    var secondes = document.getElementById("paquet-attente-secondes");
    if (minutes) {
      minutes.textContent = String(Math.floor(restant / 60));
    }
    if (secondes) {
      secondes.textContent = deuxChiffres(restant % 60);
    }
    if (restant === 0 && finAttente > 0) {
      finAttente = 0;
      rafraichirStatutOuverture();
    }
  }

  function appliquerStatutOuverture(statut) {
    var paquet = document.getElementById("paquet");
    if (!paquet || !statut) {
      return;
    }
    var bloque = !!statut.bloque;
    var secondes = Math.max(0, Number(statut.secondes) || 0);
    paquet.setAttribute("data-bloque", bloque ? "1" : "0");
    if (bloque) {
      paquet.setAttribute("aria-disabled", "true");
      paquet.setAttribute("aria-label", "Paquet indisponible : prochain paquet dans " + statut.minutes + " minutes et " +
        statut.reste + " secondes");
    } else {
      paquet.removeAttribute("aria-disabled");
      paquet.setAttribute("aria-label", paquet.getAttribute("data-libelle") || "Ouvrir un paquet");
    }
    /* « Ouvrir un paquet · 5 cartes · 1 paquet prêt sur 10 » : le stock reste affiché, même à 0 */
    var prets = document.getElementById("paquet-prets");
    if (prets) {
      var n = typeof statut.prets === "number" ? statut.prets : null;
      prets.textContent = n === null ? "" : " · " + n + " paquet" + (n > 1 ? "s" : "") + " prêt" + (n > 1 ? "s" : "") +
        " sur " + (statut.capacite || "");
    }
    var zone = document.getElementById("paquet-attente");
    if (zone) {
      zone.hidden = secondes <= 0;                   /* le décompte vers le prochain paquet : tant que le stock n'est pas plein */
      var detail = document.getElementById("paquet-attente-detail");
      if (detail) {
        detail.textContent = statut.raison || "";
      }
      if (secondes > 0) {
        finAttente = Date.now() + secondes * 1000;
        dessinerAttente();
      } else {
        finAttente = 0;
      }
    }
  }

  function rafraichirStatutOuverture() {
    var paquet = document.getElementById("paquet");
    if (!paquet || paquet.getAttribute("data-bloque-actif") !== "1" || !surServeur()) {
      return Promise.resolve();
    }
    return fetch("/api/reserve/ouverture", { headers: { "X-Jeton": document.body.getAttribute("data-jeton") } })
      .then(function (reponse) {
        return reponse.ok ? reponse.json() : null;
      })
      .then(function (statut) {
        appliquerStatutOuverture(statut);
      })
      .catch(function () { /* le serveur ne répond pas : on garde l'état affiché */ });
  }

  function surveillerOuverture() {
    var paquet = document.getElementById("paquet");
    if (!paquet || paquet.getAttribute("data-bloque-actif") !== "1" || minuteurAttente !== null) {
      return;
    }
    var zone = document.getElementById("paquet-attente");
    if (zone && !zone.hidden) {
      finAttente = Date.now() + Math.max(0, Number(zone.getAttribute("data-secondes")) || 0) * 1000;
    }
    minuteurSecondes = setInterval(function () {      /* les secondes défilent chaque seconde */
      var z = document.getElementById("paquet-attente");
      if (z && !z.hidden && finAttente > 0) {
        dessinerAttente();
      }
    }, 1000);
    minuteurAttente = setInterval(rafraichirStatutOuverture, 8000);       /* recalage sur le serveur toutes les ~8 s */
    rafraichirStatutOuverture();
  }

  /* ------------------------------------------------ fenêtre des cartes du paquet : apparition une à une, retrait, ajout */

  var LARGEUR_BASE = 220;                  /* les cartes de la fenêtre sont des cartes normales (220 px) réduites ou agrandies */

  /* Les cartes de la pré-sélection se REGARDENT : tout est inerte (étoile, exports, zoom, case...) SAUF deux boutons qui aident à choisir :
     le lien ↗ vers l'article sur Wikipédia et, pour une carte à contenu sensible, l'icône +18 (montrer ou flouter l'image). */
  var UTILES_FENETRE = ".carte__lien, .carte__sensible";

  function neutraliserCarte(cadre) {
    Array.prototype.slice.call(cadre.querySelectorAll("a, button, input, label, select, textarea, [tabindex]")).forEach(function (element) {
      if (!element.matches(UTILES_FENETRE)) {
        element.setAttribute("inert", "");
      }
    });
  }

  /* La meilleure disposition de n cartes dans la place disponible : le plus de colonnes possible sans que les cartes ne
     deviennent plus petites que nécessaire. Renvoie { largeur, colonnes } (largeur d'une carte en px). */
  function disposerCartes(n, largeurDispo, hauteurDispo, ratio, ecart) {
    var meilleure = { largeur: 56, colonnes: Math.max(1, Math.min(n, 5)) };
    for (var colonnes = 1; colonnes <= n; colonnes++) {
      var lignes = Math.ceil(n / colonnes);
      var parLargeur = (largeurDispo - (colonnes - 1) * ecart) / colonnes;
      var parHauteur = ((hauteurDispo - (lignes - 1) * ecart) / lignes) / ratio;
      var largeur = Math.min(parLargeur, parHauteur, 250);
      if (largeur > meilleure.largeur + 0.5 || (Math.abs(largeur - meilleure.largeur) <= 0.5 && colonnes > meilleure.colonnes)) {
        meilleure = { largeur: Math.max(56, largeur), colonnes: colonnes };
      }
    }
    return { largeur: Math.floor(meilleure.largeur), colonnes: meilleure.colonnes };
  }

  function montrerFenetrePaquet(donnees) {
    var fenetre = document.getElementById("fenetre-paquet");
    if (!fenetre || !donnees || !donnees.nombre) {
      return Promise.resolve(donnees);
    }
    if (document.documentElement.getAttribute("data-mobile-actif") === "1") {
      return montrerPile(donnees);                     /* téléphone : une pile de cartes à découvrir (swipe), pas une grille */
    }
    var grille = document.getElementById("fenetre-paquet-grille");
    var boite = document.getElementById("fenetre-paquet-boite");
    var titre = document.getElementById("fenetre-paquet-titre");
    var etat = document.getElementById("fenetre-paquet-etat");
    var boutonAjouter = document.getElementById("fenetre-paquet-ajouter");
    var precedent = document.activeElement;
    var reduit = mouvementReduit();
    var courant = donnees;                 /* les données à jour (après chaque retrait, le serveur renvoie les cartes restantes) */
    var occupe = false;
    var gabarit = document.createElement("template");
    gabarit.innerHTML = donnees.cartes;
    var cadres = Array.prototype.slice.call(gabarit.content.querySelectorAll(".carte-cadre"));
    if (!cadres.length) {
      return Promise.resolve(donnees);
    }

    grille.textContent = "";
    etat.textContent = "";
    var items = cadres.map(function (cadre, i) {
      var item = document.createElement("div");
      item.className = "fenetre-paquet__item";
      item.style.setProperty("--i", String(i));
      var carte = cadre.querySelector(".carte");
      item.setAttribute("data-id", carte ? carte.getAttribute("data-id") || "" : "");
      neutraliserCarte(cadre);                          /* on regarde les cartes : le ✕, le bouton du bas, le lien ↗ et l'icône +18 agissent */
      var retirer = document.createElement("button");
      retirer.type = "button";
      retirer.className = "fenetre-paquet__retirer";
      retirer.textContent = "✕";
      var nom = carte ? carte.getAttribute("data-titre") || "" : "";
      retirer.setAttribute("aria-label", "Retirer la carte « " + nom + " » : elle est supprimée tout de suite");
      retirer.title = "Retirer cette carte (supprimée tout de suite)";
      item.appendChild(cadre);
      item.appendChild(retirer);
      grille.appendChild(item);
      return item;
    });
    items.forEach(function (item) {
      var carte = item.querySelector(".carte");
      if (carte && window.WikiCartes) {
        window.WikiCartes.initialiserCarte(carte);        /* pied de carte compacté, etc. */
      }
    });

    function ajuster() {
      var restants = Array.prototype.slice.call(grille.querySelectorAll(".fenetre-paquet__item:not(.fenetre-paquet__item--part)"));
      var n = Math.max(1, restants.length);
      var hauteurBase = 0;
      restants.forEach(function (item) {
        var cadre = item.querySelector(".carte-cadre");
        hauteurBase = Math.max(hauteurBase, cadre ? cadre.offsetHeight : 0);
      });
      var ratio = (hauteurBase || LARGEUR_BASE * 1.45) / LARGEUR_BASE;
      var ecart = n > 12 ? 8 : 12;
      var cadreBoite = boite.offsetHeight - grille.offsetHeight;          /* titre, aide, bouton et marges */
      if (!(cadreBoite > 0 && cadreBoite < window.innerHeight)) {
        cadreBoite = 230;
      }
      var largeurDispo = Math.min(window.innerWidth * 0.94, 1500) - 56;
      var hauteurDispo = window.innerHeight * 0.94 - cadreBoite - 8;
      var d = disposerCartes(n, largeurDispo, hauteurDispo, ratio, ecart);
      grille.style.setProperty("--fp-ecart", ecart + "px");
      grille.style.maxWidth = (d.colonnes * d.largeur + (d.colonnes - 1) * ecart + 2) + "px";
      items.forEach(function (item) {
        item.style.setProperty("--w", String(d.largeur));
        item.style.setProperty("--h", String(Math.ceil(d.largeur * ratio)));
      });
      return d;
    }

    function majTitre() {
      var n = grille.querySelectorAll(".fenetre-paquet__item:not(.fenetre-paquet__item--part)").length;
      titre.textContent = n === 0 ? "Plus aucune carte" : (n > 1 ? "Ton paquet : " + n + " cartes" : "Ton paquet : 1 carte");
      boutonAjouter.textContent = n === 0 ? "Fermer" : (n > 1 ? "Ajouter " + n + " cartes à la collection" : "Ajouter la carte à la collection");
    }

    var pas = Math.max(40, Math.min(110, Math.floor(1500 / items.length)));       /* ~ 1,5 s en tout, même à 20 cartes */
    var sonsCartes = items.map(function (item, i) {                                /* un son pour CHAQUE carte qui apparaît */
      return setTimeout(function () {
        jouerSon("carte");
      }, i * pas + 80);
    });
    grille.style.setProperty("--pas", reduit ? "0" : String(pas));
    grille.classList.toggle("fenetre-paquet__grille--fixe", reduit);
    document.documentElement.classList.add("fenetre-paquet-ouverte");
    fenetre.hidden = false;
    majTitre();
    ajuster();
    ajuster();                                          /* 2e passe : la hauteur du titre et du bouton est alors connue */
    boutonAjouter.focus({ preventScroll: true });

    return new Promise(function (resoudre) {
      function fermer() {
        sonsCartes.forEach(function (minuteur) { clearTimeout(minuteur); });      /* (fermée avant la fin des apparitions) */
        document.removeEventListener("keydown", clavier, true);
        window.removeEventListener("resize", surRedimension);
        fenetre.hidden = true;
        document.documentElement.classList.remove("fenetre-paquet-ouverte");
        grille.textContent = "";
        if (precedent && precedent.focus) {
          try { precedent.focus({ preventScroll: true }); } catch (e) { /* sans importance */ }
        }
        resoudre(courant);
      }

      function surRedimension() {
        ajuster();
      }

      function clavier(evenement) {
        if (evenement.key === "Escape") {
          evenement.preventDefault();
          if (!occupe) {
            fermer();                                   /* échap = ajouter ce qui reste : les cartes sont déjà enregistrées */
          }
        } else if (evenement.key === "Tab") {
          var focalisables = Array.prototype.slice.call(
            fenetre.querySelectorAll(".fenetre-paquet__retirer:not([disabled]), #fenetre-paquet-ajouter:not([disabled]), .fenetre-paquet__item .carte__lien, .fenetre-paquet__item .carte__sensible"));
          if (!focalisables.length) {
            return;
          }
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
      }

      function retirer(item) {
        if (occupe || !item || item.classList.contains("fenetre-paquet__item--part")) {
          return;
        }
        var identifiant = Number(item.getAttribute("data-id"));
        occupe = true;
        etat.textContent = "";
        var bouton = item.querySelector(".fenetre-paquet__retirer");
        if (bouton) {
          bouton.disabled = true;
        }
        var suite = surServeur() && identifiant
          ? fetch("/api/paquet/retirer", {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-Jeton": document.body.getAttribute("data-jeton") },
              body: JSON.stringify({ ids: [identifiant] })
            }).catch(function () {
              throw new Error("le serveur local est injoignable");
            }).then(function (reponse) {
              return reponse.json().then(function (corps) {
                if (!reponse.ok) {
                  throw new Error(corps.erreur || "erreur du serveur");
                }
                return corps;
              });
            })
          : Promise.resolve(null);
        suite.then(function (corps) {
          if (corps) {
            courant = Object.assign({}, corps, { avertissement: donnees.avertissement, depuis_reserve: donnees.depuis_reserve });
          }
          jouerSon("retrait");                                   /* la petite croix : le son de la carte retirée */
          item.classList.add("fenetre-paquet__item--part");       /* la carte rétrécit et disparaît, les autres s'agrandissent */
          majTitre();
          ajuster();
          setTimeout(function () {
            if (item.parentNode) {
              item.parentNode.removeChild(item);
            }
            items = items.filter(function (x) { return x !== item; });
            if (!items.length) {
              boutonAjouter.focus();
            }
          }, reduit ? 0 : 320);
        }).catch(function (erreur) {
          etat.textContent = "Impossible de retirer cette carte : " + erreur.message;
          if (bouton) {
            bouton.disabled = false;
          }
        }).then(function () {
          occupe = false;
        });
      }

      grille.onclick = function (evenement) {
        var cible = evenement.target && evenement.target.closest ? evenement.target.closest(".fenetre-paquet__retirer") : null;
        if (cible) {
          retirer(cible.closest(".fenetre-paquet__item"));
        }
      };
      boutonAjouter.onclick = function () {
        if (!occupe) {
          fermer();
        }
      };
      document.addEventListener("keydown", clavier, true);
      window.addEventListener("resize", surRedimension);
    });
  }

  /* ------------------------------------------------ TÉLÉPHONE : la pile de cartes du paquet (swipe comme sur Tinder)
     Les cartes sont posées en pile, plus ou moins droites. On découvre celle du dessus : glisser à DROITE (ou le bouton rond
     « collection ») la garde, glisser à GAUCHE (ou le bouton rond « suppression ») la supprime. La carte qui part à droite
     devient verte lumineuse, celle qui part à gauche devient rouge lumineuse. Sons : « carte dans la collection » (garder) et
     « carte retirée » (supprimer). Les cartes sont déjà enregistrées à l'ouverture : seule la suppression appelle le serveur. */
  var SVG_POUBELLE = '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>';

  /* ------------------------------------------------ ANIMATIONS DE LA PILE : préparées AVANT l'ouverture, supprimées APRÈS
     Dès le clic sur le paquet (téléphone), deux « fantômes » invisibles — un pour l'envol vert (garder), un pour l'envol rouge
     (supprimer) — sont posés dans la page et joués une fois : le navigateur prépare alors à l'avance leurs calques lumineux
     (rasterisation, accélération graphique), si bien que le premier geste n'attend plus rien. Quand le choix des cartes est fini,
     ils sont retirés de la page et libérés. */
  var prechauffage = null;

  function precharger() {
    var racineHtml = document.documentElement;
    if (prechauffage || !racineHtml || typeof racineHtml.getAttribute !== "function" || racineHtml.getAttribute("data-mobile-actif") !== "1" ||
        !document.getElementById("fenetre-paquet")) {
      return;
    }
    var racine = document.createElement("div");
    racine.id = "pile-prechauffage";
    racine.setAttribute("aria-hidden", "true");
    ["vert", "rouge"].forEach(function (couleur) {
      var fantome = document.createElement("div");
      fantome.className = "pile__fantome pile__fantome--" + couleur;
      fantome.innerHTML = '<i class="pile__lueur pile__lueur--vert"></i><i class="pile__lueur pile__lueur--rouge"></i>';
      racine.appendChild(fantome);
    });
    document.body.appendChild(racine);
    prechauffage = racine;
    window.requestAnimationFrame(function () {
      if (!prechauffage || mouvementReduit()) {
        return;
      }
      Array.prototype.slice.call(racine.querySelectorAll(".pile__fantome")).forEach(function (fantome, i) {
        fantome.style.setProperty(i === 0 ? "--vert" : "--rouge", "1");
        fantome.classList.add("pile__fantome--joue", i === 0 ? "pile__fantome--droite" : "pile__fantome--gauche");
      });
    });
  }

  function libererAnimationsPile() {
    if (prechauffage && prechauffage.parentNode) {
      prechauffage.parentNode.removeChild(prechauffage);
    }
    prechauffage = null;
  }

  /* Le petit haut-parleur du lecteur (page parente) recouvre le bas de l'écran : on le cache pendant le choix des cartes. */
  function masquerHautParleur(masquer) {
    [document, window.parent && window.parent !== window ? window.parent.document : null].forEach(function (doc) {
      try {
        var commande = doc && doc.querySelector(".musique-commande");
        if (commande) {
          commande.style.display = masquer ? "none" : "";
        }
      } catch (erreur) { /* page parente d'un autre site : on laisse le haut-parleur */ }
    });
  }

  function montrerPile(donnees) {
    var fenetre = document.getElementById("fenetre-paquet");
    var grille = document.getElementById("fenetre-paquet-grille");
    var boite = document.getElementById("fenetre-paquet-boite");
    var titre = document.getElementById("fenetre-paquet-titre");
    var etat = document.getElementById("fenetre-paquet-etat");
    var precedent = document.activeElement;
    var reduit = mouvementReduit();
    var courant = donnees;
    var occupe = false;
    var gabarit = document.createElement("template");
    gabarit.innerHTML = donnees.cartes;
    var cadres = Array.prototype.slice.call(gabarit.content.querySelectorAll(".carte-cadre"));
    if (!cadres.length) {
      return Promise.resolve(donnees);
    }

    grille.textContent = "";
    etat.textContent = "";
    var items = cadres.map(function (cadre, i) {
      var item = document.createElement("div");
      item.className = "fenetre-paquet__item pile__carte";
      item.setAttribute("data-id", (cadre.querySelector(".carte") || cadre).getAttribute("data-id") || "");
      item.style.setProperty("--i", String(i));
      item.style.setProperty("--rot", (Math.random() * 6 - 3).toFixed(1));             /* posées presque droites : 3° au plus de chaque côté */
      item.style.setProperty("--dx", (Math.random() * 8 - 4).toFixed(1));
      item.style.setProperty("--dy", (Math.random() * 6 - 3).toFixed(1));
      neutraliserCarte(cadre);                                  /* le lien ↗ et l'icône +18 restent utilisables pour choisir */
      item.appendChild(cadre);
      item.insertAdjacentHTML("beforeend", '<i class="pile__lueur pile__lueur--vert"></i><i class="pile__lueur pile__lueur--rouge"></i>');   /* dessinés d'avance */
      grille.appendChild(item);
      return item;
    });
    items.forEach(function (item) {
      var carte = item.querySelector(".carte");
      if (carte && window.WikiCartes) {
        window.WikiCartes.initialiserCarte(carte);
      }
    });
    masquerHautParleur(true);                 /* le petit haut-parleur du lecteur ne recouvre plus les boutons */

    /* les deux boutons ronds et l'indication, sous la pile */
    var actions = document.createElement("div");
    actions.className = "pile__actions";
    var boutonSuppr = document.createElement("button");
    boutonSuppr.type = "button";
    boutonSuppr.className = "pile__bouton pile__bouton--supprimer";
    boutonSuppr.innerHTML = SVG_POUBELLE;
    boutonSuppr.setAttribute("aria-label", "Supprimer cette carte (elle est supprimée tout de suite)");
    var indication = document.createElement("p");
    indication.className = "pile__indication";
    indication.textContent = "← supprimer · garder →";
    var boutonGarder = document.createElement("button");
    boutonGarder.type = "button";
    boutonGarder.className = "pile__bouton pile__bouton--garder";
    boutonGarder.innerHTML = '<span aria-hidden="true">▦</span>';
    boutonGarder.setAttribute("aria-label", "Garder cette carte dans la collection");
    actions.appendChild(boutonSuppr);
    actions.appendChild(indication);
    actions.appendChild(boutonGarder);
    boite.appendChild(actions);

    function restantes() {
      return items.filter(function (item) { return !item.classList.contains("pile__carte--part"); });
    }

    function placer() {                       /* le rang de chaque carte dans la pile : 0 = celle du dessus */
      var liste = restantes();
      liste.forEach(function (item, d) {
        item.style.setProperty("--d", String(Math.min(d, 4)));
        item.style.zIndex = String(100 - d);
        item.classList.toggle("pile__carte--haut", d === 0);
        item.classList.toggle("pile__carte--cachee", d > 3);
      });
      var n = liste.length;
      titre.textContent = n === 0 ? "Plus aucune carte" : (n > 1 ? "Ton paquet : " + n + " cartes à découvrir" : "Dernière carte du paquet");
    }

    function ajuster() {
      var hauteurVue = Math.floor(window.visualViewport ? window.visualViewport.height : window.innerHeight);
      fenetre.style.height = hauteurVue + "px";                 /* la hauteur VISIBLE (barres du navigateur déduites), pas 100vh */
      boite.style.height = hauteurVue + "px";
      boite.style.maxHeight = hauteurVue + "px";
      var hauteurBase = 0;
      items.forEach(function (item) {
        var cadre = item.querySelector(".carte-cadre");
        hauteurBase = Math.max(hauteurBase, cadre ? cadre.offsetHeight : 0);
      });
      var ratio = (hauteurBase || LARGEUR_BASE * 1.45) / LARGEUR_BASE;
      var haut = titre.offsetHeight + 24, bas = actions.offsetHeight + 56;
      var dispoH = hauteurVue - haut - bas - 30, dispoL = window.innerWidth - 36;
      var largeur = Math.floor(Math.max(120, Math.min(dispoL, dispoH / ratio, 330)));
      items.forEach(function (item) {
        item.style.setProperty("--w", String(largeur));
        item.style.setProperty("--h", String(Math.ceil(largeur * ratio)));
      });
      grille.style.setProperty("--pile-h", Math.ceil(largeur * ratio) + 30 + "px");
    }

    var pas = Math.max(60, Math.min(120, Math.floor(1100 / items.length)));
    var sonsCartes = items.map(function (item, i) {
      return setTimeout(function () { jouerSon("carte"); }, i * pas + 80);
    });
    grille.style.setProperty("--pas", reduit ? "0" : String(pas));
    fenetre.classList.add("fenetre-paquet--pile");
    document.documentElement.classList.add("fenetre-paquet-ouverte");
    fenetre.hidden = false;
    placer();
    ajuster();
    ajuster();

    return new Promise(function (resoudre) {
      function fermer() {
        sonsCartes.forEach(function (minuteur) { clearTimeout(minuteur); });
        document.removeEventListener("keydown", clavier, true);
        window.removeEventListener("resize", ajuster);
        if (window.visualViewport) {
          window.visualViewport.removeEventListener("resize", ajuster);
        }
        fenetre.style.height = "";
        boite.style.height = "";
        boite.style.maxHeight = "";
        masquerHautParleur(false);
        libererAnimationsPile();                          /* l'animation préparée en mémoire est supprimée dès que le choix est fini */
        grille.removeEventListener("pointerdown", surDebut);        /* (la grille sert à chaque ouverture : on ne laisse rien derrière) */
        grille.removeEventListener("pointermove", surMouvement);
        grille.removeEventListener("pointerup", lacher);
        grille.removeEventListener("pointercancel", lacher);
        fenetre.hidden = true;
        fenetre.classList.remove("fenetre-paquet--pile");
        document.documentElement.classList.remove("fenetre-paquet-ouverte");
        grille.textContent = "";
        if (actions.parentNode) {
          actions.parentNode.removeChild(actions);
        }
        if (precedent && precedent.focus) {
          try { precedent.focus({ preventScroll: true }); } catch (e) { /* sans importance */ }
        }
        fileSuppressions.then(function () {                                    /* (les dernières suppressions sont terminées) */
          resoudre(Object.assign({}, courant, { son_arrivee_fait: true }));    /* (le son d'arrivée est déjà joué carte par carte) */
        });
      }

      function partir(item, cote) {              /* la carte s'envole : verte et lumineuse à droite, rouge et lumineuse à gauche */
        var distance = Math.max(window.innerWidth, 360) * 1.1;
        item.classList.add("pile__carte--part", cote === "droite" ? "pile__carte--vert" : "pile__carte--rouge");
        item.style.setProperty("--vert", cote === "droite" ? "1" : "0");
        item.style.setProperty("--rouge", cote === "droite" ? "0" : "1");
        item.style.setProperty("--tx", (cote === "droite" ? distance : -distance) + "px");
        item.style.setProperty("--ty", "-30px");
        item.style.setProperty("--rz", (cote === "droite" ? 24 : -24) + "deg");
      }

      var DUREE_VOL = 210;                                   /* ms : le vol de la carte (rapide) */
      var fileSuppressions = Promise.resolve();               /* les suppressions partent au serveur l'une après l'autre, en arrière-plan */

      function terminer(item) {
        setTimeout(function () {
          if (item.parentNode) {
            item.parentNode.removeChild(item);
          }
          items = items.filter(function (x) { return x !== item; });
          placer();
          occupe = false;                                      /* la carte suivante peut être glissée tout de suite */
          if (!items.length) {
            setTimeout(fermer, reduit ? 0 : 60);
          }
        }, reduit ? 0 : DUREE_VOL);
      }

      function supprimerSurServeur(identifiant) {
        fileSuppressions = fileSuppressions.then(function () {
          if (!(surServeur() && identifiant)) {
            return null;
          }
          return fetch("/api/paquet/retirer", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Jeton": document.body.getAttribute("data-jeton") },
            body: JSON.stringify({ ids: [identifiant] })
          }).catch(function () {
            throw new Error("le serveur local est injoignable");
          }).then(function (reponse) {
            return reponse.json().then(function (corps) {
              if (!reponse.ok) {
                throw new Error(corps.erreur || "erreur du serveur");
              }
              return corps;
            });
          }).then(function (corps) {
            courant = Object.assign({}, corps, { avertissement: donnees.avertissement, depuis_reserve: donnees.depuis_reserve });
          });
        }).catch(function (erreur) {
          etat.textContent = "Une carte n'a pas pu être supprimée : " + erreur.message;
        });
        return fileSuppressions;
      }

      function decider(cote) {
        var liste = restantes();
        if (occupe || !liste.length) {
          return;
        }
        var item = liste[0];
        occupe = true;
        etat.textContent = "";
        if (cote === "droite") {
          jouerSon("arrivee");                                 /* « carte dans la collection » */
          partir(item, "droite");
          terminer(item);
          return;
        }
        jouerSon("retrait");                                   /* « carte retirée » */
        partir(item, "gauche");
        supprimerSurServeur(Number(item.getAttribute("data-id")));
        terminer(item);
      }

      /* glisser la carte du dessus */
      var geste = null;
      function surDebut(evenement) {
        var haut = restantes()[0];
        if (occupe || !haut || !haut.contains(evenement.target) || (evenement.pointerType === "mouse" && evenement.button !== 0)) {
          return;
        }
        if (evenement.target.closest && evenement.target.closest(UTILES_FENETRE)) {
          return;                                            /* lien ↗ ou icône +18 : un simple appui, pas un glissement */
        }
        geste = { item: haut, x: evenement.clientX, y: evenement.clientY, t: Date.now(), dx: 0, id: evenement.pointerId };
        haut.classList.add("pile__carte--glisse");
        try { haut.setPointerCapture(evenement.pointerId); } catch (e) { /* sans importance */ }
      }
      function surMouvement(evenement) {
        if (!geste || evenement.pointerId !== geste.id) {
          return;
        }
        geste.dx = evenement.clientX - geste.x;
        var dy = (evenement.clientY - geste.y) * 0.25;
        var force = Math.min(1, Math.abs(geste.dx) / 110);
        geste.item.style.setProperty("--tx", geste.dx + "px");
        geste.item.style.setProperty("--ty", dy + "px");
        geste.item.style.setProperty("--rz", (geste.dx / 16).toFixed(1) + "deg");
        geste.item.style.setProperty("--vert", geste.dx > 0 ? force.toFixed(2) : "0");
        geste.item.style.setProperty("--rouge", geste.dx < 0 ? force.toFixed(2) : "0");
      }
      function lacher(evenement) {
        if (!geste || (evenement && evenement.pointerId !== geste.id)) {
          return;
        }
        var item = geste.item, dx = geste.dx, duree = Math.max(1, Date.now() - geste.t);
        geste = null;
        item.classList.remove("pile__carte--glisse");
        var seuil = Math.min(110, window.innerWidth * 0.28);
        if (Math.abs(dx) > seuil || (Math.abs(dx) > 40 && Math.abs(dx) / duree > 0.6)) {
          decider(dx > 0 ? "droite" : "gauche");
        } else {                                                     /* pas assez loin : la carte revient */
          ["--tx", "--ty", "--rz", "--vert", "--rouge"].forEach(function (nom) { item.style.removeProperty(nom); });
        }
      }
      grille.addEventListener("pointerdown", surDebut);
      grille.addEventListener("pointermove", surMouvement);
      grille.addEventListener("pointerup", lacher);
      grille.addEventListener("pointercancel", lacher);

      boutonSuppr.onclick = function () { decider("gauche"); };
      boutonGarder.onclick = function () { decider("droite"); };

      function clavier(evenement) {
        if (evenement.key === "Escape") {
          evenement.preventDefault();
          if (!occupe) {
            fermer();                                              /* échap : on garde ce qui reste */
          }
        } else if (evenement.key === "ArrowRight") {
          evenement.preventDefault();
          decider("droite");
        } else if (evenement.key === "ArrowLeft") {
          evenement.preventDefault();
          decider("gauche");
        }
      }
      document.addEventListener("keydown", clavier, true);
      window.addEventListener("resize", ajuster);
      if (window.visualViewport) {
        window.visualViewport.addEventListener("resize", ajuster);
      }
      boutonGarder.focus({ preventScroll: true });
    });
  }


  function ouvrirPaquet() {
    var paquet = document.getElementById("paquet");
    if (!paquet || paquetOuvert) {
      return;
    }
    if (paquet.getAttribute("data-bloque") === "1") {
      return;                                          /* réserve incomplète : le paquet reste visible mais ne s'ouvre pas */
    }
    var demo = surServeur() ? null : donneesDemo();
    if (!surServeur() && !demo) {
      notifier(
        "Pour ouvrir un paquet, lance le programme avec python main.py, puis utilise la page " +
        "qui s'ouvre.", true
      );
      return;
    }
    paquetOuvert = true;
    precharger();                                      /* téléphone : les animations de la pile se préparent pendant l'attente de Wikipédia */
    paquet.setAttribute("aria-busy", "true");
    var reduit = mouvementReduit();
    var duree = reglagesAnimation(paquet);
    var classes = ["paquet--attente", "paquet--sortie", "paquet--cache"];

    var decompte = creerDecompte(paquet);
    paquet.classList.add("paquet--attente");     /* tourne tant que Wikipédia n'a pas répondu */
    jouerSon("effet");                           /* le son qui accompagne l'animation du paquet */
    var tirage = demo
      ? simulerTirage(demo, decompte, reduit)
      : demanderPaquetEnFlux(decompte.evenement);
    Promise.all([tirage, attendre(reduit ? 0 : duree.attente)])
      .then(function (resultats) {
        decompte.terminer();               /* le décompte tombe à 0 : c'est là que le paquet s'ouvre */
        paquet.classList.remove("paquet--attente");
        arreterSon("effet");               /* (si le son d'effet jouait en boucle : le paquet s'ouvre, il s'arrête) */
        jouerSon("ouverture");             /* le son du paquet qui disparaît */
        if (!reduit && duree.sortie > 0) {
          paquet.classList.add("paquet--sortie");
          lancerConfettis(paquet);           /* confettis, étincelles... selon l'animation, au moment où le paquet disparaît */
        }
        return attendre(reduit ? 0 : duree.sortie).then(function () {
          return resultats[0];
        });
      })
      .then(function (donnees) {
        decompte.masquer();
        paquet.classList.remove("paquet--sortie");
        paquet.classList.add("paquet--cache");
        var annonce = donnees && donnees.godpack && window.WikiGodPack ? window.WikiGodPack.jouer() : Promise.resolve();   /* GOD PACK : feu d'artifice et message */
        return annonce.then(function () {
          return paquet.getAttribute("data-fenetre") === "1" ? montrerFenetrePaquet(donnees) : donnees;
        })
          .then(function (finales) {
            return afficherNouvellesCartes(finales);          /* la fenêtre est fermée : les cartes gardées entrent dans la collection */
          }).then(function () {
            return attendre(reduit || duree.sortie === 0 ? 0 : 300);
          });
      })
      .then(function () {
        paquet.classList.remove("paquet--cache");
        paquet.classList.add("paquet--retour");
        return attendre(reduit ? 0 : duree.retour);
      })
      .catch(function (erreur) {
        arreterSon("effet");                             /* un son en boucle ne doit jamais continuer après un échec */
        decompte.masquer();
        classes.forEach(function (classe) {
          paquet.classList.remove(classe);
        });
        notifier("Paquet impossible : " + erreur.message, true);
        rafraichirStatutOuverture();                     /* (ex. 409 : la réserve n'est plus complète) */
      })
      .then(function () {
        rafraichirStatutOuverture();                     /* la réserve vient d'être entamée : le décompte reprend si besoin */
        paquet.classList.remove("paquet--retour");
        paquet.setAttribute("aria-busy", "false");
        paquetOuvert = false;
        libererAnimationsPile();                       /* (sans effet si la pile l'a déjà fait ; couvre aussi l'échec ou l'absence de fenêtre) */
      });
  }

  /* Confettis, étincelles, poussière ou cœurs au moment où le paquet disparaît ou explose : la couche de particules est
     centrée sur le paquet (quelle que soit sa forme ou sa taille), puis la classe « paquet--confettis » déclenche l'animation
     choisie dans le CSS (elle dépend de l'animation d'ouverture : data-animation). */
  function lancerConfettis(paquet) {
    var couche = paquet.querySelector(".paquet__particules");
    if (!couche || mouvementReduit()) {
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
    void paquet.offsetWidth;                 /* relance l'animation si elle jouait déjà */
    paquet.classList.add("paquet--confettis");
    setTimeout(function () {
      paquet.classList.remove("paquet--confettis");
    }, 1700);
  }

  window.lancerConfettisPaquet = lancerConfettis;

  /* Les autres scripts de la page (profil : vitrines) ajoutent des cartes et les rendent actives */
  window.WikiCartes = { initialiserCarte: initialiserCarte };

  /* Page rechargée après l'ouverture d'un paquet (?nouveau=N) : le son d'arrivée (la page se rechargeait avant de le jouer) */
  if (typeof window !== "undefined" && window.location && /[?&]nouveau=[1-9]/.test(window.location.search || "")) {
    jouerSon("arrivee");
  }

  /* Page rechargée après l'ouverture d'un paquet (?nouveau=N) : le serveur a déjà mis les halos */
  nettoyerHalosApres(Array.prototype.slice.call(document.querySelectorAll(".halo")), 600);

  planifierStats();                                    /* cartes dont il manque des statistiques */

  /* ------------------------------------------------ cartes à contenu sensible et rafraîchissement de l'image */

  /* La carte mise à jour (renvoyée par le serveur) prend la place de l'ancienne dans la page. */
  function remplacerCarte(carte, donnees) {
    /* La carte est retrouvée par son identifiant : la page a pu être redessinée entre-temps (statistiques qui arrivent, tri...), et l'élément
       gardé en mémoire n'est alors plus celui qui s'affiche : l'image doit apparaître tout de suite sur la carte VISIBLE. */
    var identifiantCarte = carte && carte.getAttribute ? carte.getAttribute("data-id") : null;
    var visible = identifiantCarte ? document.querySelector('.carte[data-id="' + identifiantCarte + '"]') : null;
    var cadre = (visible || carte).closest(".carte-cadre");
    var gabarit = document.createElement("template");
    gabarit.innerHTML = donnees.carte;
    var nouveau = gabarit.content.querySelector(".carte-cadre");
    var neuve = null;
    if (cadre && nouveau && cadre.parentNode) {
      cadre.parentNode.replaceChild(nouveau, cadre);
      neuve = nouveau.querySelector(".carte");
      if (neuve && window.WikiCartes) {
        window.WikiCartes.initialiserCarte(neuve);
      }
    }
    if (neuve && identifiantCarte && window.WikiApercu && window.WikiApercu.actualiser) {
      window.WikiApercu.actualiser(identifiantCarte, neuve);       /* la carte AGRANDIE (si elle est ouverte) montre tout de suite la nouvelle image */
    }
    if (donnees.bandeaux) {
      majBandeaux(donnees.bandeaux);                  /* (le bandeau « Doublon » des autres cartes du même titre) */
    }
    if (donnees.doublons !== undefined) {
      majDoublons(donnees.doublons);
    }
    if (donnees.compteurs) {
      majCompteurs(donnees.compteurs);
    }
  }

  /* L'illustration d'une carte : TOUTES les images de l'article en vignettes (celle de la carte, l'image principale de Wikipédia, les autres). On touche
     une vignette, puis on valide ; si la carte a déjà une illustration, un bouton permet aussi de la RETIRER (on pourra en remettre une plus tard).
     La grille s'adapte au nombre d'images et à l'écran ; au-delà d'une page, on tourne les pages. Les icônes et pictogrammes de l'article sont listés
     aussi, mais cachés tant qu'on ne les demande pas. Seule une adresse Wikimedia est affichée ; le serveur revérifie le choix. */
  function proposerImages(carte, boutonOrigine, identifiant, titre, candidats, aDejaUneImage, infos) {
    infos = infos || {};
    var toutes = (candidats || []).filter(function (c) {
      if (!c || typeof c.miniature !== "string" || typeof c.image !== "string") {
        return false;
      }
      if (c.actuelle) {                                  /* l'image que la carte porte déjà est toujours listée (elle s'affiche déjà sur la carte) */
        return /^(https:\/\/|\/image\/)/.test(c.miniature);
      }
      return /^https:\/\/[a-z0-9.-]+\.(wikimedia|wikipedia)\.org\//i.test(c.miniature) && /^https:\/\/[a-z0-9.-]+\.(wikimedia|wikipedia)\.org\//i.test(c.image);      /* (le serveur n'envoie que des adresses Wikimedia ; ceci en est la 2e barrière) */
    });
    var nbRecues = (candidats || []).length;
    var ecartees = (candidats || []).filter(function (c) { return toutes.indexOf(c) === -1; }).slice(0, 4).map(function (c) {
      return (c && c.nom ? String(c.nom).slice(0, 22) : "?") + " → " + (c && typeof c.image === "string" ? c.image.slice(0, 40) : typeof (c && c.image));
    });
    if (!toutes.length && !aDejaUneImage) {
      notifier("Cet article n'a aucune image.", false);
      return;
    }
    var seulementCadrage = !!infos.perso;                       /* carte créée à la main : pas d'article, donc pas de liste d'images : on ne peut que recadrer son illustration */
    var precedent = document.activeElement;
    var fond = document.createElement("div");
    fond.className = "choix-image";
    fond.setAttribute("role", "dialog");
    fond.setAttribute("aria-modal", "true");
    fond.setAttribute("aria-labelledby", "choix-image-titre");
    var boite = document.createElement("div");
    boite.className = "choix-image__boite";
    var h = document.createElement("h2");
    h.id = "choix-image-titre";
    h.className = "choix-image__titre";
    h.textContent = (aDejaUneImage ? "Illustration de « " : "Choisis l'illustration de « ") + titre + " »";
    if (seulementCadrage) {
      h.textContent = "Illustration de « " + titre + " » (carte créée à la main)";
    }
    var aide = document.createElement("p");
    aide.className = "choix-image__aide";
    var reste = toutes.filter(function (c) { return !c.actuelle; }).length;
    var origine = infos.sources && infos.sources.total ? " (page : " + infos.sources.page + ", fichiers de l'article : " + infos.sources.fichiers + ")" : "";
    var nbEcartees = infos.sources && infos.sources.nb_ecartees ? Number(infos.sources.nb_ecartees) : 0;
    if (nbEcartees) {                                    /* des fichiers de l'article n'ont pas pu être listés : on le dit, avec la raison (survol) */
      origine += " — " + nbEcartees + " fichier" + (nbEcartees > 1 ? "s" : "") + " ignoré" + (nbEcartees > 1 ? "s" : "");
    }
    if (nbEcartees && infos.sources.ecartees) {
      aide.title = infos.sources.ecartees.slice(0, 15).map(function (e) { return e[0] + " : " + e[1]; }).join("\n");
    }
    aide.textContent = (toutes.length ? (reste ? reste + " image" + (reste > 1 ? "s" : "") + " dans l'article" + origine : "Aucune autre image dans l'article") : "Aucune image dans l'article") +
      (aDejaUneImage ? " (l'image actuelle de la carte est repérée « Actuelle »). Touche une image puis valide ton choix, ou retire l'illustration de la carte."
        : ". Touche l'image voulue, puis valide ton choix.");
    var grille = document.createElement("ul");
    grille.className = "choix-image__grille";
    var sectionCadrage = document.createElement("section");           /* « Redimensionner/Positionner l'image actuelle » : seulement si la carte a une illustration */
    sectionCadrage.className = "choix-image__section";
    sectionCadrage.hidden = !aDejaUneImage;
    var titreCadrage = document.createElement("h3");
    titreCadrage.className = "choix-image__soustitre";
    titreCadrage.textContent = "Redimensionner/Positionner l'image actuelle";
    var texteCadrage = document.createElement("p");
    texteCadrage.className = "choix-image__aide";
    texteCadrage.textContent = "Recadre l'illustration et déplace-la dans le cadre de la carte, avec la carte en gros plan. Le réglage est gardé : les prochains exemplaires de cette carte le reçoivent aussi.";
    var boutonCadrage = document.createElement("button");
    boutonCadrage.type = "button";
    boutonCadrage.className = "bouton-site choix-image__cadrer";
    boutonCadrage.textContent = "✥ Ouvrir l'éditeur";
    sectionCadrage.appendChild(titreCadrage);
    sectionCadrage.appendChild(texteCadrage);
    sectionCadrage.appendChild(boutonCadrage);
    var pied = document.createElement("div");
    pied.className = "choix-image__pied";
    var avant = document.createElement("button");
    avant.type = "button";
    avant.className = "bouton-site";
    avant.textContent = "‹ Précédentes";
    var page = document.createElement("span");
    page.className = "choix-image__page";
    var apres = document.createElement("button");
    apres.type = "button";
    apres.className = "bouton-site";
    apres.textContent = "Suivantes ›";
    var retirer = document.createElement("button");
    retirer.type = "button";
    retirer.className = "bouton-site choix-image__retirer";
    retirer.textContent = "🚫 Retirer l'illustration";
    retirer.hidden = !aDejaUneImage;
    var annuler = document.createElement("button");
    annuler.type = "button";
    annuler.className = "bouton-site";
    annuler.textContent = "Annuler";
    var valider = document.createElement("button");
    valider.type = "button";
    valider.className = "bouton-site bouton-site--principal choix-image__valider";
    valider.textContent = "✓ Valider ce choix";
    valider.disabled = true;
    var choisie = null;                                  /* l'image touchée, pas encore validée */
    var etat = document.createElement("p");
    etat.className = "choix-image__etat";
    etat.setAttribute("role", "status");
    etat.textContent = infos.avertissement || "";
    var diagnostic = document.createElement("p");                /* d'où viennent les images (pour comprendre quand il en manque une) et la version du programme */
    diagnostic.className = "choix-image__diag";
    diagnostic.textContent = (infos.diagnostic || "") + (infos.diagnostic ? " · reçues par la page : " + nbRecues + " · affichées : " + toutes.length + (ecartees.length ? " (écartées : " + ecartees.join(" ; ") + ")" : "") : "");
    diagnostic.id = "choix-image-diag";
    diagnostic.hidden = true;                                    /* masquée par défaut : un petit bouton la montre (utile seulement quand une image manque) */
    var boutonDiag = document.createElement("button");
    boutonDiag.type = "button";
    boutonDiag.className = "choix-image__diag-bouton";
    boutonDiag.textContent = "ⓘ Diagnostic";
    boutonDiag.setAttribute("aria-expanded", "false");
    boutonDiag.setAttribute("aria-controls", "choix-image-diag");
    boutonDiag.hidden = !infos.diagnostic;
    boutonDiag.addEventListener("click", function () {
      diagnostic.hidden = !diagnostic.hidden;
      boutonDiag.setAttribute("aria-expanded", diagnostic.hidden ? "false" : "true");
      boutonDiag.textContent = diagnostic.hidden ? "ⓘ Diagnostic" : "ⓘ Masquer le diagnostic";
    });
    var rangee = document.createElement("div");
    rangee.className = "choix-image__actions";
    rangee.appendChild(retirer);
    rangee.appendChild(annuler);
    rangee.appendChild(valider);
    pied.appendChild(avant);
    pied.appendChild(page);
    pied.appendChild(apres);
    boite.appendChild(h);
    boite.appendChild(aide);
    boite.appendChild(grille);
    boite.appendChild(pied);
    boite.appendChild(sectionCadrage);
    boite.appendChild(rangee);
    boite.appendChild(etat);
    boite.appendChild(boutonDiag);
    boite.appendChild(diagnostic);
    if (seulementCadrage) {                                     /* (pas de liste, de pages, de choix ni de retrait pour une carte créée à la main) */
      aide.textContent = "Cette carte a été créée à la main : tu peux régler la position et la taille de son illustration.";
      [grille, pied, retirer, valider].forEach(function (e) { e.hidden = true; });
    }
    fond.appendChild(boite);
    document.body.appendChild(fond);
    document.documentElement.classList.add("choix-image-ouvert");

    var numero = 0;
    var occupe = false;
    function liste() {
      return toutes;                                      /* TOUTES les images de l'article (les icônes en dernier) */
    }
    function parPage() {                     /* autant de vignettes qu'il en tient SANS défiler dans la boîte (largeur et hauteur de l'écran) */
      var l = window.innerWidth, hauteur = window.innerHeight;
      var largeurBoite = Math.min(980, l * 0.94) - 44;
      var colonnes = Math.max(2, Math.floor(largeurBoite / (l < 520 ? 150 : 160)));
      var hauteurCellule = Math.min(130, Math.max(70, hauteur * 0.14)) + 70;
      var reserve = aDejaUneImage ? (l < 520 ? 60 : 124) : 0;          /* la place de la section « Redimensionner/Positionner l'image actuelle » */
      var lignes = Math.max(1, Math.floor((hauteur * 0.94 - 230 - reserve) / hauteurCellule));
      return Math.max(2, Math.min(liste().length || 2, colonnes * lignes));
    }
    function fermer() {
      document.removeEventListener("keydown", clavier, true);
      window.removeEventListener("resize", afficher);
      document.documentElement.classList.remove("choix-image-ouvert");
      if (fond.parentNode) {
        fond.parentNode.removeChild(fond);
      }
      var retour = boutonOrigine && document.body.contains(boutonOrigine) ? boutonOrigine : precedent;
      if (retour && retour.focus) {
        try { retour.focus({ preventScroll: true }); } catch (erreur) { /* sans importance */ }
      }
    }
    function afficher() {
      var visibles = liste();
      var n = parPage();
      var pages = Math.max(1, Math.ceil(visibles.length / n));
      numero = Math.min(numero, pages - 1);
      grille.textContent = "";
      grille.classList.toggle("choix-image__grille--peu", visibles.length <= 3);     /* peu d'images : de grandes vignettes */
      if (!visibles.length) {
        var vide = document.createElement("li");
        vide.className = "choix-image__vide";
        vide.textContent = "Aucune image à proposer.";
        grille.appendChild(vide);
      }
      visibles.slice(numero * n, numero * n + n).forEach(function (c) {
        var li = document.createElement("li");
        var b = document.createElement("button");
        b.type = "button";
        b.className = "choix-image__vignette" + (choisie === c ? " choix-image__vignette--choisie" : "") + (c.actuelle ? " choix-image__vignette--actuelle" : "");
        b.setAttribute("aria-pressed", choisie === c ? "true" : "false");
        b.setAttribute("aria-label", (c.actuelle ? "Image actuelle de la carte : " : "Sélectionner l'image ") + c.nom);
        if (c.actuelle) {
          b.setAttribute("aria-disabled", "true");
        }
        var img = document.createElement("img");
        img.src = c.miniature;
        img.alt = "";
        img.loading = "lazy";
        img.addEventListener("error", function () { img.style.visibility = "hidden"; });
        var legende = document.createElement("span");
        legende.textContent = c.nom.replace(/\.[A-Za-z0-9]+$/, "").replace(/_/g, " ");
        b.appendChild(img);
        b.appendChild(legende);
        if (c.actuelle || c.principale || c.precedente || c.mineure) {
          var badge = document.createElement("strong");
          badge.className = "choix-image__badge" + (c.actuelle ? " choix-image__badge--actuelle" : (c.precedente ? " choix-image__badge--precedente" : (!c.principale ? " choix-image__badge--icone" : "")));
          var etiquettes = [];                                 /* tous les statuts de l'image, ensemble : une image peut être à la fois actuelle, principale de Wikipédia et d'origine */
          if (c.actuelle) { etiquettes.push("Actuelle"); }
          if (c.principale) { etiquettes.push("Principale"); }
          if (c.precedente) { etiquettes.push("D'origine"); }
          if (c.mineure && !c.principale) { etiquettes.push("Icône"); }
          badge.textContent = etiquettes.join(" · ");
          b.appendChild(badge);
        }
        b.addEventListener("click", function () {         /* un appui SÉLECTIONNE ; c'est « Valider ce choix » qui enregistre */
          if (c.actuelle) {
            etat.textContent = "C'est déjà l'illustration de cette carte : choisis une autre image, ou retire l'illustration.";
            return;
          }
          choisie = c;
          Array.prototype.slice.call(grille.querySelectorAll(".choix-image__vignette")).forEach(function (autre) {
            autre.classList.remove("choix-image__vignette--choisie");
            autre.setAttribute("aria-pressed", "false");
          });
          b.classList.add("choix-image__vignette--choisie");
          b.setAttribute("aria-pressed", "true");
          valider.disabled = false;
          etat.textContent = "Image sélectionnée : " + c.nom + ". Clique sur « Valider ce choix » pour l'enregistrer.";
        });
        li.appendChild(b);
        grille.appendChild(li);
      });
      page.textContent = pages > 1 ? "Page " + (numero + 1) + " / " + pages : visibles.length + " image" + (visibles.length > 1 ? "s" : "");
      avant.hidden = apres.hidden = pages <= 1;
      avant.disabled = numero === 0;
      apres.disabled = numero >= pages - 1;
    }
    function envoyer(chemin, corps, fini) {
      if (occupe) {
        return;
      }
      occupe = true;
      etat.textContent = "Enregistrement…";
      fetch(chemin, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Jeton": document.body.getAttribute("data-jeton") },
        body: JSON.stringify(corps)
      }).catch(function () {
        throw new Error("le serveur local est injoignable");
      }).then(function (reponse) {
        return reponse.json().then(function (donnees) {
          if (!reponse.ok) {
            throw new Error(donnees.erreur || "erreur du serveur");
          }
          return donnees;
        });
      }).then(function (donnees) {
        fermer();
        remplacerCarte(carte, donnees);
        notifier(fini, false);
      }).catch(function (erreur) {
        occupe = false;
        etat.textContent = "Impossible d'enregistrer : " + erreur.message;
      });
    }
    function clavier(evenement) {
      if (evenement.key === "Escape" || evenement.key === "Tab") {
        evenement.stopPropagation();                      /* (la carte agrandie, derrière, ne doit pas réagir : elle resterait ouverte ou volerait le focus) */
      }
      if (evenement.key === "Escape") {
        evenement.preventDefault();
        fermer();
      } else if (evenement.key === "Tab") {
        var focalisables = Array.prototype.slice.call(boite.querySelectorAll("button:not([disabled]):not([hidden]), input:not([disabled])"))
          .filter(function (e) { return !e.closest("[hidden]"); });
        if (!focalisables.length) {
          return;
        }
        var premier = focalisables[0], dernier = focalisables[focalisables.length - 1];
        if (evenement.shiftKey && document.activeElement === premier) {
          evenement.preventDefault();
          dernier.focus();
        } else if (!evenement.shiftKey && document.activeElement === dernier) {
          evenement.preventDefault();
          premier.focus();
        }
      }
    }
    avant.addEventListener("click", function () { numero = Math.max(0, numero - 1); afficher(); });
    apres.addEventListener("click", function () { numero += 1; afficher(); });
    annuler.addEventListener("click", fermer);
    boutonCadrage.addEventListener("click", function () {
      fermer();
      ouvrirCadrage(carte, boutonOrigine, identifiant, titre);
    });
    retirer.addEventListener("click", function () {
      envoyer("/api/cartes/image/retirer", { id: identifiant }, "Illustration retirée : tu peux en remettre une quand tu veux avec l'icône ⟳.");
    });
    valider.addEventListener("click", function () {
      if (choisie) {
        envoyer("/api/cartes/image/choisir", { id: identifiant, image: choisie.image }, "Image choisie : la carte a maintenant cette illustration.");
      }
    });
    fond.addEventListener("mousedown", function (evenement) { if (evenement.target === fond) { fermer(); } });
    document.addEventListener("keydown", clavier, true);
    window.addEventListener("resize", afficher);
    afficher();
    var premier = grille.querySelector("button") || annuler;
    premier.focus({ preventScroll: true });
  }

  /* « Redimensionner/Positionner l'image actuelle » : la carte en GROS PLAN, l'illustration entourée de tirets (la partie qui dépasse du cadre est grisée). On la
     déplace en la tirant (clic maintenu au milieu), on la redimensionne (plus grande OU plus petite que le cadre) avec les poignées, la molette ou le curseur. Ce qu'on voit
     dans le cadre est la vraie carte, rendue par le même CSS. Le moteur d'édition est dans cadrage.js (partagé avec l'aperçu du Créateur de cartes). Le réglage est enregistré
     pour l'article et le fichier d'image : les prochains exemplaires de la carte le reçoivent automatiquement. */
  function ouvrirCadrage(carte, boutonOrigine, identifiant, titre) {
    var visible = document.querySelector('.carte[data-id="' + identifiant + '"]') || carte;
    var cadreOrigine = visible && visible.closest ? visible.closest(".carte-cadre") : null;
    var imageOrigine = visible ? visible.querySelector(".carte__image") : null;
    if (!cadreOrigine || !imageOrigine || !window.WikiCadrage) {
      notifier("Cette carte n'a pas d'illustration à cadrer.", true);
      return;
    }
    var etat = window.WikiCadrage.lire(imageOrigine);
    var precedent = document.activeElement;
    var fond = document.createElement("div");
    fond.className = "cadrage";
    fond.setAttribute("role", "dialog");
    fond.setAttribute("aria-modal", "true");
    fond.setAttribute("aria-labelledby", "cadrage-titre");
    var boite = document.createElement("div");
    boite.className = "cadrage__boite";
    var h = document.createElement("h2");
    h.id = "cadrage-titre";
    h.className = "cadrage__titre";
    h.textContent = "Redimensionner/Positionner l'image actuelle — « " + titre + " »";
    var aide = document.createElement("p");
    aide.className = "choix-image__aide";
    aide.textContent = "Tire l'image (clic maintenu au milieu) pour la déplacer ; tire les poignées, tourne la molette ou utilise le curseur pour la redimensionner (plus grande ou " +
      "plus petite que le cadre). Au clavier : flèches pour déplacer, + et − pour redimensionner. La partie grisée dépasse du cadre : elle ne sera pas visible sur la carte.";
    var scene = document.createElement("div");
    scene.className = "cadrage__scene";
    scene.setAttribute("tabindex", "0");
    scene.setAttribute("aria-label", "Zone de réglage de l'image : flèches pour déplacer, plus et moins pour redimensionner");
    var cadre = cadreOrigine.cloneNode(true);
    cadre.classList.remove("carte-cadre--entree");
    cadre.setAttribute("inert", "");
    cadre.classList.add("cadrage__carte");
    var imageCarte = cadre.querySelector(".carte__image");
    scene.appendChild(cadre);
    var commandes = document.createElement("div");
    commandes.className = "cadrage__commandes";
    var etiquette = document.createElement("label");
    etiquette.className = "cadrage__zoom";
    var lecture = document.createElement("span");
    var curseur = document.createElement("input");
    curseur.type = "range";
    curseur.setAttribute("aria-label", "Agrandissement de l'image");
    etiquette.appendChild(lecture);
    etiquette.appendChild(curseur);
    var reinitialiser = document.createElement("button");
    reinitialiser.type = "button";
    reinitialiser.className = "bouton-site";
    reinitialiser.textContent = "↺ Réinitialiser";
    var annuler = document.createElement("button");
    annuler.type = "button";
    annuler.className = "bouton-site";
    annuler.textContent = "Annuler";
    var enregistrer = document.createElement("button");
    enregistrer.type = "button";
    enregistrer.className = "bouton-site bouton-site--principal";
    enregistrer.textContent = "✓ Enregistrer";
    enregistrer.disabled = true;
    var message = document.createElement("p");
    message.className = "choix-image__etat";
    message.setAttribute("role", "status");
    commandes.appendChild(etiquette);
    commandes.appendChild(reinitialiser);
    commandes.appendChild(annuler);
    commandes.appendChild(enregistrer);
    boite.appendChild(h);
    boite.appendChild(aide);
    boite.appendChild(scene);
    boite.appendChild(commandes);
    boite.appendChild(message);
    fond.appendChild(boite);
    document.body.appendChild(fond);
    document.documentElement.classList.add("choix-image-ouvert");

    var occupe = false;
    function mesurer() {                                              /* la carte en gros plan, au milieu de la scène */
      var largeur = Math.max(160, Math.min(window.innerWidth * 0.5, (window.innerHeight - 330) * 300 / 430, 460));
      cadre.style.width = largeur + "px";
      cadre.style.maxWidth = "none";
      scene.style.width = Math.round(largeur * 1.7) + "px";
      scene.style.height = Math.round(largeur * 430 / 300 * 1.12) + "px";
      cadre.style.left = Math.round(largeur * 0.35) + "px";
      cadre.style.top = Math.round(largeur * 430 / 300 * 0.06) + "px";
    }
    mesurer();
    var moteur = window.WikiCadrage.monter({
      scene: scene, cadre: cadre, image: imageCarte, etat: etat, curseur: curseur, lecture: lecture,
      surPret: function () { enregistrer.disabled = false; },
      surErreur: function () {
        message.textContent = "L'image ne peut pas être chargée pour le moment : réessaie dans un instant.";
        enregistrer.disabled = true;
      }
    });
    function fermer() {
      document.removeEventListener("keydown", clavier, true);
      window.removeEventListener("resize", surRedimension);
      moteur.detruire();
      document.documentElement.classList.remove("choix-image-ouvert");
      if (fond.parentNode) {
        fond.parentNode.removeChild(fond);
      }
      var retour = boutonOrigine && document.body.contains(boutonOrigine) ? boutonOrigine : precedent;
      if (retour && retour.focus) {
        try { retour.focus({ preventScroll: true }); } catch (erreur) { /* sans importance */ }
      }
    }
    function surRedimension() {
      mesurer();
      moteur.remesurer();
    }
    function clavier(evenement) {
      if (evenement.key === "Escape" || evenement.key === "Tab") {
        evenement.stopPropagation();                                 /* (la carte agrandie, derrière, ne doit pas réagir) */
      }
      if (evenement.key === "Escape") {
        evenement.preventDefault();
        fermer();
      } else if (evenement.key === "Tab") {
        var cibles = Array.prototype.slice.call(boite.querySelectorAll("button:not([disabled]), input:not([disabled]), [tabindex=\"0\"]"));
        if (!cibles.length) {
          return;
        }
        var premier = cibles[0], dernier = cibles[cibles.length - 1];
        if (evenement.shiftKey && document.activeElement === premier) {
          evenement.preventDefault();
          dernier.focus();
        } else if (!evenement.shiftKey && document.activeElement === dernier) {
          evenement.preventDefault();
          premier.focus();
        }
      }
    }
    reinitialiser.addEventListener("click", function () {
      moteur.reinitialiser();
      message.textContent = "Cadrage d'origine rétabli : clique sur « Enregistrer » pour le garder.";
    });
    annuler.addEventListener("click", fermer);
    enregistrer.addEventListener("click", function () {
      if (occupe || !moteur.ratio()) {
        return;
      }
      occupe = true;
      message.textContent = "Enregistrement…";
      fetch("/api/cartes/image/cadrage", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Jeton": document.body.getAttribute("data-jeton") },
        body: JSON.stringify({ id: identifiant, zoom: Math.round(etat.z * 1000) / 1000, x: Math.round(etat.x * 1000) / 1000, y: Math.round(etat.y * 1000) / 1000,
                               ratio: Math.round(moteur.ratio() * 10000) / 10000 })
      }).catch(function () {
        throw new Error("le serveur local est injoignable");
      }).then(function (reponse) {
        return reponse.json().then(function (donnees) {
          if (!reponse.ok) {
            throw new Error(donnees.erreur || "erreur du serveur");
          }
          return donnees;
        });
      }).then(function (donnees) {
        fermer();
        remplacerCarte(visible, donnees);
        notifier("Position de l'image enregistrée : elle s'applique aussi aux prochains exemplaires de cette carte.", false);
      }).catch(function (erreur) {
        occupe = false;
        message.textContent = "Impossible d'enregistrer : " + erreur.message;
      });
    });
    document.addEventListener("keydown", clavier, true);
    window.addEventListener("resize", surRedimension);
    moteur.rafraichir();
    scene.focus({ preventScroll: true });
  }

  /* L'icône ⟳ : liste toutes les images de l'article pour choisir l'illustration de la carte (ou la retirer). */
  document.addEventListener("click", function (evenement) {
    var cible = evenement.target;
    var bouton = cible && cible.closest ? cible.closest(".carte__rafraichir") : null;
    if (!bouton || bouton.getAttribute("aria-busy") === "true") {
      return;
    }
    evenement.preventDefault();
    evenement.stopPropagation();
    var carte = bouton.closest(".carte");
    var identifiant = carte ? Number(carte.getAttribute("data-id")) : 0;
    if (!identifiant || !surServeur()) {
      return;
    }
    bouton.setAttribute("aria-busy", "true");
    fetch("/api/cartes/image", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Jeton": document.body.getAttribute("data-jeton") },
      body: JSON.stringify({ id: identifiant })
    }).catch(function () {
      throw new Error("le serveur local est injoignable");
    }).then(function (reponse) {
      return reponse.json().then(function (donnees) {
        if (!reponse.ok) {
          throw new Error(donnees.erreur || "erreur du serveur");
        }
        return donnees;
      });
    }).then(function (donnees) {
      bouton.removeAttribute("aria-busy");
      if (donnees.candidats && (donnees.candidats.length || donnees.actuelle)) {         /* toutes les images de l'article : on les propose (et on peut retirer l'illustration) */
        proposerImages(carte, bouton, identifiant, donnees.titre, donnees.candidats, !!donnees.actuelle, donnees);
        return;
      }
      if (!donnees.change) {                         /* pas de nouvelle image : rien ne change, ce n'est pas grave */
        bouton.classList.add("carte__rafraichir--rien");
        setTimeout(function () { bouton.classList.remove("carte__rafraichir--rien"); }, 700);
        notifier(donnees.message || "Pas de nouvelle image pour cet article.", false);
        return;
      }
      remplacerCarte(carte, donnees);
      notifier("Image mise à jour sur la carte.", false);
    }).catch(function (erreur) {
      bouton.removeAttribute("aria-busy");
      notifier("Images de l'article indisponibles : " + erreur.message, true);
    });
  }, true);

  var boutonPaquet = document.getElementById("paquet");
  if (boutonPaquet) {
    boutonPaquet.addEventListener("click", ouvrirPaquet);
    surveillerOuverture();
  }
})();
