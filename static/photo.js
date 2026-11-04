/* La photo de profil (page de profil) : image ronde, prise sur une carte de la collection ou envoyée depuis l'ordinateur, avec positionnement.
   Le serveur (wikicartes/photo.py) range le fichier dans le dossier profil/ sous le nom « profile.<extension> ». Une image de carte est TÉLÉCHARGÉE : elle reste
   même si la carte est supprimée. Pendant le choix l'image est seulement mise de côté ; rien n'est remplacé avant « Enregistrer ».
   Les calculs de positionnement (zoom de 1 à 4, x et y de 0 à 100) sont les mêmes que dans photo.py. */
(function () {
  "use strict";

  var jeton = document.body ? document.body.getAttribute("data-jeton") : "";
  if (!jeton || !document.getElementById("profil-photo") || (window.location.protocol !== "http:" && window.location.protocol !== "https:")) {
    return;
  }

  var ZOOM_MIN = 1, ZOOM_MAX = 4;
  var TAILLE_MAX = 15 * 1024 * 1024;
  var fenetre = null;
  var precedent = null;
  var ecouteurClavier = null;

  function appeler(chemin, corps) {
    return fetch(chemin, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Jeton": jeton },
      body: JSON.stringify(corps || {})
    }).catch(function () {
      throw new Error("le programme ne répond pas");
    }).then(function (reponse) {
      return reponse.json().catch(function () { return {}; }).then(function (donnees) {
        if (!reponse.ok) {
          throw new Error(donnees.erreur || "erreur du programme");
        }
        return donnees;
      });
    });
  }

  function televerser(fichier) {
    return fetch("/api/profil/photo/televerser", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Jeton": jeton },
      body: fichier
    }).catch(function () {
      throw new Error("le programme ne répond pas");
    }).then(function (reponse) {
      return reponse.json().catch(function () { return {}; }).then(function (donnees) {
        if (!reponse.ok) {
          throw new Error(donnees.erreur || "erreur du programme");
        }
        return donnees;
      });
    });
  }

  function creer(balise, classe, texte) {
    var e = document.createElement(balise);
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

  function borner(v, mini, maxi) {
    return Math.max(mini, Math.min(maxi, v));
  }

  /* ---------------------------------------------------------------------------------------------------- la géométrie (comme photo.py) */

  function geometrie(zoom, x, y, ratio) {
    var r = ratio > 0.05 && ratio < 20 ? ratio : 1;
    var largeur = (r >= 1 ? r : 1) * zoom * 100;
    var hauteur = (r >= 1 ? 1 : 1 / r) * zoom * 100;
    return { largeur: largeur, hauteur: hauteur, gauche: (100 - largeur) * x / 100, haut: (100 - hauteur) * y / 100 };
  }

  function appliquer(image, e) {
    var g = geometrie(e.zoom, e.x, e.y, e.ratio);
    image.style.width = g.largeur.toFixed(3) + "%";
    image.style.height = g.hauteur.toFixed(3) + "%";
    image.style.left = g.gauche.toFixed(3) + "%";
    image.style.top = g.haut.toFixed(3) + "%";
  }

  /* ---------------------------------------------------------------------------------------------------- la version partagée avec le Hall */

  /* Les visiteurs du Hall ne reçoivent JAMAIS l'image d'origine (parfois lourde, parfois recadrée volontairement) : seulement le carré de 320 × 320 pixels visible dans le cercle,
     fabriqué ici, dans le navigateur, avec le même positionnement que ce que tu vois. Le serveur le garde à côté de la photo et ne le sert que si ton profil est public. */
  var COTE_PARTAGE = 320;

  function fabriquerCarre(url, e) {
    return new Promise(function (resolve, reject) {
      var image = new Image();
      image.onload = function () {
        var ratio = image.naturalWidth > 0 && image.naturalHeight > 0 ? image.naturalWidth / image.naturalHeight : e.ratio;
        var g = geometrie(e.zoom, e.x, e.y, ratio);
        var toile = document.createElement("canvas");
        toile.width = COTE_PARTAGE;
        toile.height = COTE_PARTAGE;
        var contexte = toile.getContext("2d");
        function dessiner(fond) {
          contexte.clearRect(0, 0, COTE_PARTAGE, COTE_PARTAGE);
          if (fond) {
            contexte.fillStyle = fond;
            contexte.fillRect(0, 0, COTE_PARTAGE, COTE_PARTAGE);
          }
          contexte.drawImage(image, g.gauche * COTE_PARTAGE / 100, g.haut * COTE_PARTAGE / 100, g.largeur * COTE_PARTAGE / 100, g.hauteur * COTE_PARTAGE / 100);
        }
        dessiner(null);
        toile.toBlob(function (png) {
          if (png && png.size <= 380 * 1024) {
            resolve(png);
            return;
          }
          dessiner("#ffffff");                                            /* trop lourd en png (photo) : jpeg, sur fond blanc */
          toile.toBlob(function (jpeg) { return jpeg ? resolve(jpeg) : reject(new Error("image non fabriquée")); }, "image/jpeg", 0.88);
        }, "image/png");
      };
      image.onerror = function () { reject(new Error("image illisible")); };
      image.src = url;
    });
  }

  function partager(e) {
    return fabriquerCarre("/profil-photo?v=" + e.version, e).then(function (blob) {
      return fetch("/api/profil/photo/partage", { method: "POST", headers: { "Content-Type": "application/octet-stream", "X-Jeton": jeton }, body: blob });
    }).then(function (reponse) {
      if (!reponse.ok) {
        throw new Error("version partagée refusée");
      }
      var r = document.getElementById("profil-photo");
      if (r) {
        r.setAttribute("data-partage", "1");
      }
    });
  }

  /* ---------------------------------------------------------------------------------------------------- la fenêtre */

  function fermer() {
    if (ecouteurClavier) {
      document.removeEventListener("keydown", ecouteurClavier, true);
      ecouteurClavier = null;
    }
    if (fenetre && fenetre.parentNode) {
      fenetre.parentNode.removeChild(fenetre);
    }
    fenetre = null;
    document.documentElement.classList.remove("photo-ouverte");
    var b = document.getElementById("profil-photo-modifier");
    if (b) {
      b.focus();
    } else if (precedent && precedent.focus) {
      precedent.focus();
    }
  }

  function boite(titre, surEchap) {
    var avant = fenetre;
    if (avant && avant.parentNode) {
      avant.parentNode.removeChild(avant);
    }
    fenetre = creer("div", "photo-fenetre");
    var b = creer("div", "photo-fenetre__boite");
    b.setAttribute("role", "dialog");
    b.setAttribute("aria-modal", "true");
    b.setAttribute("aria-labelledby", "photo-titre");
    var h = creer("h2", "photo-fenetre__titre", titre);
    h.id = "photo-titre";
    var contenu = creer("div", "photo-fenetre__contenu");
    b.appendChild(h);
    b.appendChild(contenu);
    fenetre.appendChild(b);
    document.body.appendChild(fenetre);
    document.documentElement.classList.add("photo-ouverte");
    if (ecouteurClavier) {
      document.removeEventListener("keydown", ecouteurClavier, true);
    }
    ecouteurClavier = function (evenement) {
      if (evenement.key === "Escape" && fenetre) {
        evenement.preventDefault();
        evenement.stopImmediatePropagation();
        surEchap();
      }
    };
    document.addEventListener("keydown", ecouteurClavier, true);
    return contenu;
  }

  function etatCourant() {
    var r = document.getElementById("profil-photo");
    return {
      existe: r.getAttribute("data-existe") === "1",
      zoom: Number(r.getAttribute("data-zoom")) || 1,
      x: Number(r.getAttribute("data-x")),
      y: Number(r.getAttribute("data-y")),
      ratio: Number(r.getAttribute("data-ratio")) || 1,
      version: r.getAttribute("data-version")
    };
  }

  function remplacerAvatar(html) {
    var r = document.getElementById("profil-photo");
    if (r && html) {
      r.outerHTML = html;
    }
  }

  /* ---------------------------------------------------------------------------------------------------- 1. choisir l'image */

  function etapeChoix() {
    var contenu = boite("Photo de profil", fermer);
    var courant = etatCourant();
    contenu.appendChild(creer("p", "photo-fenetre__aide", "Choisis l'image de ta photo de profil. Elle sera ronde ; tu la positionneras à l'étape suivante. " +
      "Une image de carte est téléchargée dans le dossier profil/ : elle reste ta photo même si la carte est supprimée plus tard."));
    var message = creer("p", "photo-fenetre__message");
    message.setAttribute("role", "status");
    message.setAttribute("aria-live", "polite");
    var choix = creer("div", "photo-choix");
    var depuisCarte = bouton("🖼 Une image de ma collection", "photo-choix__bouton", function () {
      if (!window.WikiProfil || !window.WikiProfil.ouvrirSelecteurPhoto) {
        message.textContent = "Le choix d'une carte n'est pas disponible ici.";
        return;
      }
      fermer();
      window.WikiProfil.ouvrirSelecteurPhoto(function (carteId) { prendreCarte(carteId); }, document.getElementById("profil-photo-modifier"));
    });
    var entree = creer("input");
    entree.type = "file";
    entree.accept = "image/*,.bmp,.avif,.svg,.ico,.webp";
    entree.hidden = true;
    var depuisOrdi = bouton("💻 Une image de mon ordinateur", "photo-choix__bouton", function () { entree.click(); });
    choix.appendChild(depuisCarte);
    choix.appendChild(depuisOrdi);
    var zone = creer("div", "photo-zone", "… ou dépose un fichier image ici");
    ["dragenter", "dragover"].forEach(function (n) {
      zone.addEventListener(n, function (e) { e.preventDefault(); zone.classList.add("photo-zone--survol"); });
    });
    ["dragleave", "drop"].forEach(function (n) {
      zone.addEventListener(n, function (e) { e.preventDefault(); zone.classList.remove("photo-zone--survol"); });
    });
    zone.addEventListener("drop", function (e) {
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) {
        envoyer(f);
      }
    });
    function envoyer(fichier) {
      if (fichier.size > TAILLE_MAX) {
        message.textContent = "Cette image est trop lourde (15 Mo au maximum).";
        return;
      }
      message.textContent = "Envoi de l'image…";
      televerser(fichier).then(function (d) { editer({ url: d.apercu.url, ratio: d.apercu.ratio, zoom: 1, x: 50, y: 50, nouvelle: true }); }).catch(function (erreur) {
        message.textContent = "Image refusée : " + erreur.message;
      });
    }
    entree.addEventListener("change", function () {
      if (entree.files && entree.files[0]) {
        envoyer(entree.files[0]);
      }
    });
    var actions = creer("div", "photo-fenetre__actions");
    if (courant.existe) {
      actions.appendChild(bouton("Revenir à ma photo", "", function () { editer({ url: "/profil-photo?v=" + courant.version, ratio: courant.ratio, zoom: courant.zoom, x: courant.x, y: courant.y, nouvelle: false }); }));
    }
    actions.appendChild(bouton("Annuler", "", fermer));
    [choix, zone, entree, message, actions].forEach(function (e) { contenu.appendChild(e); });
    depuisCarte.focus();
  }

  function prendreCarte(carteId) {
    var contenu = boite("Photo de profil", fermer);
    var message = creer("p", "photo-fenetre__message", "Téléchargement de l'image de la carte… (quelques secondes)");
    message.setAttribute("role", "status");
    contenu.appendChild(message);
    appeler("/api/profil/photo/carte", { id: carteId }).then(function (d) {
      editer({ url: d.apercu.url, ratio: d.apercu.ratio, zoom: 1, x: 50, y: 50, nouvelle: true });
    }).catch(function (erreur) {
      message.textContent = "Impossible de prendre l'image de cette carte : " + erreur.message;
      var actions = creer("div", "photo-fenetre__actions");
      actions.appendChild(bouton("Choisir autre chose", "", etapeChoix));
      actions.appendChild(bouton("Fermer", "", fermer));
      contenu.appendChild(actions);
    });
  }

  /* ---------------------------------------------------------------------------------------------------- 2. positionner dans le cercle */

  function editer(e) {
    var contenu = boite("Positionne ta photo", function () { annuler(e); });
    var etat = { zoom: borner(e.zoom, ZOOM_MIN, ZOOM_MAX), x: borner(e.x, 0, 100), y: borner(e.y, 0, 100), ratio: e.ratio || 1 };
    var cercle = creer("div", "photo-editeur__cercle");
    cercle.tabIndex = 0;
    cercle.setAttribute("role", "img");
    cercle.setAttribute("aria-label", "Aperçu rond de la photo : glisse pour la déplacer, molette ou curseur pour zoomer, flèches pour affiner");
    var image = creer("img", "photo-editeur__image");
    image.alt = "";
    image.draggable = false;
    cercle.appendChild(image);
    var curseurZoom = creer("input", "photo-editeur__zoom");
    curseurZoom.type = "range";
    curseurZoom.min = String(ZOOM_MIN);
    curseurZoom.max = String(ZOOM_MAX);
    curseurZoom.step = "0.01";
    curseurZoom.value = String(etat.zoom);
    curseurZoom.setAttribute("aria-label", "Zoom");
    var etiquetteZoom = creer("label", "photo-editeur__etiquette");
    etiquetteZoom.appendChild(document.createTextNode("Zoom "));
    etiquetteZoom.appendChild(curseurZoom);
    var valeurZoom = creer("span", "photo-editeur__valeur", "");
    etiquetteZoom.appendChild(valeurZoom);
    var aide = creer("p", "photo-fenetre__aide", "Glisse l'image pour la positionner · molette ou curseur pour zoomer · flèches pour affiner. L'image n'est jamais recadrée : tu pourras la repositionner quand tu veux.");
    var message = creer("p", "photo-fenetre__message");
    message.setAttribute("role", "status");
    message.setAttribute("aria-live", "polite");
    var actions = creer("div", "photo-fenetre__actions");
    var enregistrer = bouton("Enregistrer la photo", "bouton-site--principal", function () { sauver(); });
    enregistrer.disabled = true;
    var recentrer = bouton("Recentrer", "", function () { etat.zoom = 1; etat.x = 50; etat.y = 50; rendre(); });
    actions.appendChild(recentrer);
    actions.appendChild(bouton("Choisir une autre image", "", etapeChoix));
    if (!e.nouvelle) {
      actions.appendChild(bouton("🗑 Supprimer la photo", "photo-danger", function () { supprimer(); }));
    }
    actions.appendChild(bouton("Annuler", "", function () { annuler(e); }));
    actions.appendChild(enregistrer);
    [cercle, etiquetteZoom, aide, message, actions].forEach(function (x) { contenu.appendChild(x); });

    function rendre() {
      appliquer(image, etat);
      curseurZoom.value = String(etat.zoom);
      valeurZoom.textContent = " × " + etat.zoom.toFixed(2).replace(".", ",");
    }
    image.addEventListener("load", function () {
      if (!e.ratio && image.naturalWidth > 0 && image.naturalHeight > 0) {
        etat.ratio = image.naturalWidth / image.naturalHeight;     /* le serveur n'a pas pu lire les dimensions : on prend celles du navigateur */
      }
      enregistrer.disabled = false;
      rendre();
    });
    image.addEventListener("error", function () {
      message.textContent = "Ton navigateur n'a pas pu afficher cette image : choisis-en une autre.";
      enregistrer.disabled = true;
    });
    image.src = e.url;
    rendre();

    /* zoom en gardant le centre de la vue */
    function changerZoom(z) {
      var S = cercle.clientWidth || 280;
      var avant = geometrie(etat.zoom, etat.x, etat.y, etat.ratio);
      var u = (S / 2 - avant.gauche * S / 100) / (avant.largeur * S / 100);
      var v = (S / 2 - avant.haut * S / 100) / (avant.hauteur * S / 100);
      etat.zoom = borner(z, ZOOM_MIN, ZOOM_MAX);
      var apres = geometrie(etat.zoom, 50, 50, etat.ratio);
      var w = apres.largeur * S / 100, h = apres.hauteur * S / 100;
      if (Math.abs(S - w) > 0.5) {
        etat.x = borner((S / 2 - u * w) / (S - w) * 100, 0, 100);
      }
      if (Math.abs(S - h) > 0.5) {
        etat.y = borner((S / 2 - v * h) / (S - h) * 100, 0, 100);
      }
      rendre();
    }
    curseurZoom.addEventListener("input", function () { changerZoom(Number(curseurZoom.value)); });
    cercle.addEventListener("wheel", function (ev) {
      ev.preventDefault();
      var delta = ev.deltaY * (ev.deltaMode === 1 ? 16 : 1);            /* (une molette de souris : quelques crans ; un pavé tactile : beaucoup de petits pas) */
      changerZoom(etat.zoom * Math.exp(-delta * 0.0015));
    }, { passive: false });

    /* glisser pour déplacer */
    var glisse = null;
    function deplacer(dx, dy) {
      var S = cercle.clientWidth || 280;
      var g = geometrie(etat.zoom, etat.x, etat.y, etat.ratio);
      var w = g.largeur * S / 100, h = g.hauteur * S / 100;
      if (Math.abs(S - w) > 0.5) {
        etat.x = borner(etat.x + dx / (S - w) * 100, 0, 100);
      }
      if (Math.abs(S - h) > 0.5) {
        etat.y = borner(etat.y + dy / (S - h) * 100, 0, 100);
      }
      rendre();
    }
    cercle.addEventListener("pointerdown", function (ev) {
      glisse = { x: ev.clientX, y: ev.clientY };
      cercle.classList.add("photo-editeur__cercle--glisse");
      try { cercle.setPointerCapture(ev.pointerId); } catch (erreur) { /* sans importance */ }
      ev.preventDefault();
    });
    cercle.addEventListener("pointermove", function (ev) {
      if (!glisse) {
        return;
      }
      deplacer(ev.clientX - glisse.x, ev.clientY - glisse.y);
      glisse = { x: ev.clientX, y: ev.clientY };
    });
    function lacher() {
      glisse = null;
      cercle.classList.remove("photo-editeur__cercle--glisse");
    }
    cercle.addEventListener("pointerup", lacher);
    cercle.addEventListener("pointercancel", lacher);
    cercle.addEventListener("keydown", function (ev) {
      var pas = ev.shiftKey ? 24 : 6;
      var S = cercle.clientWidth || 280;
      if (ev.key === "ArrowLeft") { deplacer(-pas * S / 280, 0); }
      else if (ev.key === "ArrowRight") { deplacer(pas * S / 280, 0); }
      else if (ev.key === "ArrowUp") { deplacer(0, -pas * S / 280); }
      else if (ev.key === "ArrowDown") { deplacer(0, pas * S / 280); }
      else if (ev.key === "+" || ev.key === "=") { changerZoom(etat.zoom * 1.1); }
      else if (ev.key === "-") { changerZoom(etat.zoom / 1.1); }
      else { return; }
      ev.preventDefault();
    });

    function sauver() {
      enregistrer.disabled = true;
      message.textContent = "Enregistrement…";
      var corps = { zoom: Number(etat.zoom.toFixed(3)), x: Number(etat.x.toFixed(2)), y: Number(etat.y.toFixed(2)), ratio: Number(etat.ratio.toFixed(5)) };
      appeler(e.nouvelle ? "/api/profil/photo/enregistrer" : "/api/profil/photo/recadrer", corps).then(function (d) {
        remplacerAvatar(d.html);
        fermer();
        partager({ version: d.version, zoom: d.zoom, x: d.x, y: d.y, ratio: d.ratio }).catch(function () { /* les visiteurs du Hall verront la photo dès qu'elle pourra être fabriquée */ });
      }).catch(function (erreur) {
        enregistrer.disabled = false;
        message.textContent = "Impossible d'enregistrer : " + erreur.message;
      });
    }
    function supprimer() {
      if (!window.confirm("Supprimer la photo de profil ?\n\nLe fichier du dossier profil/ sera effacé.")) {
        return;
      }
      appeler("/api/profil/photo/supprimer").then(function (d) {
        remplacerAvatar(d.html);
        fermer();
      }).catch(function (erreur) {
        message.textContent = "Impossible de supprimer : " + erreur.message;
      });
    }
    cercle.focus();
  }

  function annuler(e) {
    if (e && e.nouvelle) {
      appeler("/api/profil/photo/abandonner").catch(function () { /* l'image mise de côté sera effacée plus tard */ });
    }
    fermer();
  }

  /* ---------------------------------------------------------------------------------------------------- la version partagée est-elle à jour ? */

  (function () {                                                          /* photo déposée à la main dans le dossier, ou enregistrée avant le partage : on la prépare tout seul */
    var r = document.getElementById("profil-photo");
    if (r && r.getAttribute("data-existe") === "1" && r.getAttribute("data-partage") === "0") {
      var c = etatCourant();
      partager(c).catch(function () { /* sans importance : on réessaiera à la prochaine visite */ });
    }
  })();

  /* ---------------------------------------------------------------------------------------------------- le clic sur le rond de la page */

  document.addEventListener("click", function (ev) {
    var b = ev.target.closest ? ev.target.closest("#profil-photo-modifier") : null;
    if (!b || fenetre) {
      return;
    }
    precedent = b;
    var courant = etatCourant();
    if (courant.existe) {
      editer({ url: "/profil-photo?v=" + courant.version, ratio: courant.ratio, zoom: courant.zoom, x: courant.x, y: courant.y, nouvelle: false });
    } else {
      etapeChoix();
    }
  });
})();
