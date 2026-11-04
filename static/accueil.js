/* Message de bienvenue : affiché UNE FOIS à chaque lancement du programme (et par fenêtre de navigateur), à la première page qui s'affiche.
   Il propose, en bas à gauche, de ne plus l'afficher au démarrage (réglage ACCUEIL_AFFICHER, enregistré dans la base). Le logo, en haut à gauche, a une
   taille FIXE (elle ne suit pas le réglage de taille du logo de la Configuration). */
(function () {
  "use strict";

  var html = document.documentElement;
  var corps = document.body;
  if (!corps || html.getAttribute("data-accueil") !== "1") {
    return;
  }
  var jeton = corps.getAttribute("data-jeton");
  var demarrage = html.getAttribute("data-demarrage") || "";
  if (!jeton || !demarrage || (window.location.protocol !== "http:" && window.location.protocol !== "https:")) {
    return;                                              /* une page d'aperçu ouverte sans le programme : pas de message */
  }
  var CLE = "wikicartes-accueil";
  try {
    if (window.sessionStorage.getItem(CLE) === demarrage) {
      return;                                            /* déjà montré depuis ce lancement, dans cette fenêtre */
    }
    window.sessionStorage.setItem(CLE, demarrage);
  } catch (erreur) { /* stockage indisponible : on montre le message à chaque page */ }

  var URL_PROJET = "https://github.com/damballah/wikifreecards";

  function paragraphe(contenu) {
    var p = document.createElement("p");
    p.className = "accueil__texte";
    contenu.forEach(function (morceau) {
      p.appendChild(typeof morceau === "string" ? document.createTextNode(morceau) : morceau);
    });
    return p;
  }

  function construire() {
    var precedent = document.activeElement;
    var fond = document.createElement("div");
    fond.className = "accueil";
    fond.setAttribute("role", "dialog");
    fond.setAttribute("aria-modal", "true");
    fond.setAttribute("aria-label", "Bienvenue sur WikiFreeCards");
    var boite = document.createElement("div");
    boite.className = "accueil__boite";

    var entete = document.createElement("div");
    entete.className = "accueil__entete";
    var logo = html.getAttribute("data-logo-accueil");
    if (logo) {
      var image = document.createElement("img");
      image.className = "accueil__logo";
      image.src = logo;
      image.alt = "Logo WikiFreeCards";
      image.width = 72;
      image.height = 72;
      entete.appendChild(image);
    }
    boite.appendChild(entete);

    var lien = document.createElement("a");              /* le lien du projet : en gras, dans une nouvelle fenêtre */
    lien.href = URL_PROJET;
    lien.target = "_blank";
    lien.rel = "noopener noreferrer";
    var gras = document.createElement("strong");
    gras.textContent = URL_PROJET;
    lien.appendChild(gras);

    boite.appendChild(paragraphe(["Bonjour et bienvenue sur votre logiciel de gestion de collection WikiFreeCards,", document.createElement("br"),
      "nous sommes heureux de vous accueillir et espérons que vous allez passer un agréable moment à créer et gérer vos cartes de collection."]));
    boite.appendChild(paragraphe(["Ce logiciel est sous licence MIT, cela veut dire que vous êtes totalement libre de l'utiliser, de le modifier et de le partager, " +
      "à condition de conserver la mention d'auteur d'origine (en bas de page)."]));
    boite.appendChild(paragraphe(["Il a été conceptualisé dans le but de procurer plaisir et détente. Si vous souhaitez de plus amples informations, " +
      "n'hésitez pas à visiter la page GitHub du projet : ", lien]));
    boite.appendChild(paragraphe(["Bon amusement à vous."]));

    var pied = document.createElement("div");
    pied.className = "accueil__pied";
    var etiquette = document.createElement("label");
    etiquette.className = "accueil__case";
    var caseACocher = document.createElement("input");
    caseACocher.type = "checkbox";
    caseACocher.id = "accueil-ne-plus";
    etiquette.appendChild(caseACocher);
    etiquette.appendChild(document.createTextNode("Ne plus afficher ce message au démarrage"));
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "bouton-site bouton-site--principal";
    bouton.textContent = "Commencer";
    pied.appendChild(etiquette);
    pied.appendChild(bouton);
    boite.appendChild(pied);
    var etat = document.createElement("p");
    etat.className = "accueil__etat";
    etat.setAttribute("role", "status");
    boite.appendChild(etat);
    fond.appendChild(boite);
    document.body.appendChild(fond);
    html.classList.add("accueil-ouvert");

    var occupe = false;
    function fermer() {
      document.removeEventListener("keydown", clavier, true);
      html.classList.remove("accueil-ouvert");
      if (fond.parentNode) {
        fond.parentNode.removeChild(fond);
      }
      if (precedent && precedent.focus) {
        try { precedent.focus({ preventScroll: true }); } catch (erreur) { /* sans importance */ }
      }
    }
    function valider() {
      if (occupe) {
        return;
      }
      if (!caseACocher.checked) {
        fermer();                                        /* sans cocher : il reviendra au prochain lancement */
        return;
      }
      occupe = true;
      etat.textContent = "Enregistrement…";
      fetch("/api/configuration", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Jeton": jeton },
        body: JSON.stringify({ valeurs: { ACCUEIL_AFFICHER: false } })
      }).then(function (reponse) {
        if (!reponse.ok) {
          throw new Error("refusé");
        }
        html.setAttribute("data-accueil", "0");
        fermer();
      }).catch(function () {
        occupe = false;
        etat.textContent = "Ce choix n'a pas pu être enregistré. Réessaie, ou décoche la case pour fermer.";
      });
    }
    function clavier(evenement) {
      if (evenement.key === "Escape") {
        evenement.preventDefault();
        evenement.stopPropagation();
        fermer();                                        /* Échap : on ferme sans rien décider */
      } else if (evenement.key === "Tab") {
        var cibles = [lien, caseACocher, bouton];
        var i = cibles.indexOf(document.activeElement);
        var suivant = evenement.shiftKey ? i - 1 : i + 1;
        if (i === -1 || suivant < 0 || suivant >= cibles.length) {
          evenement.preventDefault();
          cibles[(suivant + cibles.length) % cibles.length].focus();
        }
      }
    }
    bouton.addEventListener("click", valider);
    document.addEventListener("keydown", clavier, true);
    bouton.focus({ preventScroll: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", construire);
  } else {
    construire();
  }
})();
