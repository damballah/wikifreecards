/* Sons des événements et musique d'ambiance.
   Les réglages arrivent dans l'attribut data-sons de <html> (JSON : interrupteur, volume, fichier de chaque événement,
   musique). Les fichiers sont servis par /son?fichier=<nom> (dossier sons/). Rien n'est joué sans fichier choisi.
   - Les EFFETS (jouer) fonctionnent sur toutes les pages, y compris dans le cadre du « lecteur ».
   - La MUSIQUE vit dans la fenêtre du HAUT (le « lecteur » : voir cadre.js, qui affiche les pages dans un cadre) : elle ne
     s'interrompt donc plus quand on change de page. Une page ouverte seule (sans lecteur) la joue elle-même.
   window.WikiSons : jouer(evenement), jouerFichier(nom, volume), appliquer(reglages), reglages(), adresse(nom),
   geste() (un geste de l'utilisateur dans un cadre : lance la musique en attente). */
(function () {
  "use strict";

  var racine = document.documentElement;
  var CLE_MUSIQUE = "wikicartes.musique";
  var enCadre = false;
  try {
    enCadre = window.parent !== window;
  } catch (erreur) {
    enCadre = false;
  }
  var prets = {};                          /* un son par événement, préchargé : les lectures successives en sont des copies */
  var boucles = {};                        /* les sons joués en boucle (événement -> audio) et leur minuteur de sécurité */
  var DUREE_BOUCLE_MAX = 120000;           /* un son en boucle s'arrête de toute façon au bout de 2 minutes */
  var musique = { audio: null, commande: null, bouton: null, curseur: null, fichier: "", attente: false, minuteur: null,
                  envoi: null };

  function reglages() {
    try {
      return JSON.parse(racine.getAttribute("data-sons") || "{}") || {};
    } catch (erreur) {
      return {};
    }
  }

  function adresse(nom) {
    return "/son?fichier=" + encodeURIComponent(nom);
  }

  function fraction(pourcent) {
    var n = Number(pourcent);
    return isNaN(n) ? 0 : Math.max(0, Math.min(1, n / 100));
  }

  function lire(audio) {
    try {
      var promesse = audio.play();
      if (promesse && promesse.catch) {
        promesse.catch(function () { /* le navigateur attend un geste de l'utilisateur : rien à faire */ });
      }
    } catch (erreur) { /* sans importance */ }
  }

  /* Un son d'événement : une COPIE du son préchargé, pour que plusieurs lectures puissent se chevaucher (une par carte). */
  function jouer(evenement) {
    var r = reglages();
    if (!r.actifs || !r.evenements || !r.evenements[evenement]) {
      return null;
    }
    var nom = r.evenements[evenement];
    var base = prets[evenement];
    if (!base || base.nomSon !== nom) {
      base = new Audio(adresse(nom));
      base.preload = "auto";
      base.nomSon = nom;
      prets[evenement] = base;
    }
    var audio = typeof base.cloneNode === "function" ? base.cloneNode(true) : new Audio(adresse(nom));
    audio.volume = fraction(r.volume);
    if (r.boucles && r.boucles[evenement] === true) {      /* ce son-là (l'effet du paquet) recommence jusqu'à ce qu'on l'arrête */
      arreter(evenement);
      audio.loop = true;
      boucles[evenement] = audio;
      boucles[evenement + ":minuteur"] = window.setTimeout(function () { arreter(evenement); }, DUREE_BOUCLE_MAX);
    }
    lire(audio);
    return audio;
  }

  /* Arrête le son d'un événement joué en boucle (sans effet s'il n'y en a pas). */
  function arreter(evenement) {
    var audio = boucles[evenement];
    var minuteur = boucles[evenement + ":minuteur"];
    if (minuteur) {
      window.clearTimeout(minuteur);
    }
    delete boucles[evenement];
    delete boucles[evenement + ":minuteur"];
    if (audio) {
      try {
        audio.loop = false;
        audio.pause();
        audio.currentTime = 0;
      } catch (erreur) { /* sans importance */ }
    }
  }

  /* Écouter un fichier précis (boutons ▶ de la Configuration), au volume demandé. */
  function jouerFichier(nom, volume) {
    if (!nom) {
      return null;
    }
    var audio = new Audio(adresse(nom));
    audio.volume = fraction(volume === undefined ? (reglages().volume || 70) : volume);
    lire(audio);
    return audio;
  }

  function prechargerTout() {
    var r = reglages();
    if (!r.actifs || !r.evenements) {
      return;
    }
    Object.keys(r.evenements).forEach(function (cle) {
      var nom = r.evenements[cle];
      if (!prets[cle] || prets[cle].nomSon !== nom) {
        var audio = new Audio(adresse(nom));
        audio.preload = "auto";
        audio.nomSon = nom;
        prets[cle] = audio;
      }
    });
  }

  /* ------------------------------------------------------------------ musique d'ambiance */

  function etatSauve() {
    try {
      return JSON.parse(localStorage.getItem(CLE_MUSIQUE) || "{}") || {};
    } catch (erreur) {
      return {};
    }
  }

  function sauver(etat) {
    try {
      localStorage.setItem(CLE_MUSIQUE, JSON.stringify(etat));
    } catch (erreur) { /* stockage indisponible : la musique repart simplement du début */ }
  }

  /* Le choix (haut-parleur barré ou non) et le volume sont gardés SUR LE SERVEUR : ils survivent à la fermeture du programme,
     du navigateur et même à un changement de navigateur. */
  function envoyerPreference(corps) {
    var jeton = document.body ? document.body.getAttribute("data-jeton") : null;
    if (!jeton || typeof fetch !== "function") {
      return;
    }
    try {
      fetch("/api/preferences", {
        method: "POST", keepalive: true,
        headers: { "Content-Type": "application/json", "X-Jeton": jeton },
        body: JSON.stringify(corps)
      }).catch(function () { /* sans importance : le choix reste valable pour cette session */ });
    } catch (erreur) { /* sans importance */ }
  }

  function coupee() {
    var m = reglages().musique;
    return !!(m && m.coupee);
  }

  function definirCoupee(valeur) {
    var r = reglages();
    if (r.musique) {
      r.musique.coupee = valeur;
      racine.setAttribute("data-sons", JSON.stringify(r));
    }
    envoyerPreference({ MUSIQUE_COUPEE: valeur });
  }

  /* Le haut-parleur : 🔊 la musique joue ; 🔇 barré = coupée par choix ; 🔊 qui pulse = prête, elle démarrera au premier clic
     (le navigateur l'exige). Le curseur de volume n'est visible que si la musique n'est pas coupée. */
  function majCommande() {
    var bouton = musique.bouton;
    if (!bouton || !musique.audio) {
      return;
    }
    var barre = coupee();
    var enAttente = !barre && musique.audio.paused;
    bouton.textContent = barre ? "🔇" : "🔊";
    bouton.setAttribute("aria-pressed", barre ? "false" : "true");
    bouton.classList.toggle("musique-bouton--attente", enAttente);
    bouton.setAttribute("aria-label", barre ? "Relancer la musique" : "Couper la musique");
    bouton.title = barre ? "Relancer la musique d'ambiance"
      : (enAttente ? "La musique démarre dès ton premier clic (clique n'importe où)" : "Couper la musique d'ambiance");
    if (musique.curseur) {
      musique.curseur.hidden = barre;
    }
  }

  function memoriserPosition() {
    if (musique.audio) {
      var etat = etatSauve();
      etat.fichier = musique.fichier;
      etat.t = musique.audio.currentTime || 0;
      etat.ts = Date.now();
      etat.joue = !musique.audio.paused;
      sauver(etat);
    }
  }

  function lancerMusique() {
    if (!musique.audio || coupee()) {
      return;
    }
    var promesse;
    try {
      promesse = musique.audio.play();
    } catch (erreur) {
      promesse = null;
    }
    if (promesse && promesse.then) {
      promesse.then(majCommande).catch(attendreGeste);
    }
  }

  /* Les navigateurs interdisent de lancer un son avant un premier geste : on attend le premier clic ou la première touche,
     sur cette page ou (dans le lecteur) dans le cadre qui affiche les pages. */
  function geste() {
    if (!musique.attente) {
      return;
    }
    musique.attente = false;
    ["pointerdown", "keydown", "touchstart"].forEach(function (nom) {
      document.removeEventListener(nom, geste, true);
    });
    lancerMusique();
  }

  function attendreGeste() {
    majCommande();
    if (musique.attente) {
      return;
    }
    musique.attente = true;
    ["pointerdown", "keydown", "touchstart"].forEach(function (nom) {
      document.addEventListener(nom, geste, true);
    });
  }

  function arreterMusique() {
    if (musique.minuteur) {
      clearInterval(musique.minuteur);
      musique.minuteur = null;
    }
    if (musique.audio) {
      try { musique.audio.pause(); } catch (erreur) { /* sans importance */ }
      musique.audio = null;
    }
    if (musique.commande && musique.commande.parentNode) {
      musique.commande.parentNode.removeChild(musique.commande);
    }
    musique.commande = null;
    musique.bouton = null;
    musique.curseur = null;
    musique.fichier = "";
    musique.attente = false;
  }

  /* Le haut-parleur se pose au-dessus de la barre « Enregistrer » de la Configuration quand elle est en bas de l'écran. */
  function placer(doc) {
    if (!musique.commande) {
      return;
    }
    var bas = 14;
    try {
      var barre = (doc || document).querySelector(".barre-config");
      if (barre) {
        var rect = barre.getBoundingClientRect();
        if (rect.height > 0 && rect.height < 200) {
          bas = Math.round(rect.height + 14);
        }
      }
    } catch (erreur) { /* page d'un autre site ou non accessible : position par défaut */ }
    musique.commande.style.bottom = bas + "px";
  }

  function creerCommande(volume) {
    var commande = document.createElement("div");
    commande.id = "musique-commande";
    commande.className = "musique-commande";
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.id = "musique-bouton";
    bouton.className = "musique-bouton";
    bouton.addEventListener("click", function () {
      if (!musique.audio) {
        return;
      }
      if (coupee()) {                                    /* relancer : le choix est gardé pour les prochains lancements */
        definirCoupee(false);
        lancerMusique();
      } else {                                           /* couper : haut-parleur barré, volume masqué, choix gardé */
        definirCoupee(true);
        musique.audio.pause();
      }
      majCommande();
    });
    var curseur = document.createElement("input");
    curseur.type = "range";
    curseur.id = "musique-volume";
    curseur.className = "musique-volume";
    curseur.min = "0";
    curseur.max = "100";
    curseur.step = "1";
    curseur.value = String(Math.round(Number(volume) || 0));
    curseur.setAttribute("aria-label", "Volume de la musique d'ambiance");
    curseur.title = "Volume de la musique";
    curseur.addEventListener("input", function () {
      var v = Number(curseur.value);
      if (musique.audio) {
        musique.audio.volume = fraction(v);
      }
      var r = reglages();
      if (r.musique) {
        r.musique.volume = v;
        racine.setAttribute("data-sons", JSON.stringify(r));
      }
      clearTimeout(musique.envoi);                       /* on garde la valeur quand on arrête de bouger le curseur */
      musique.envoi = setTimeout(function () {
        envoyerPreference({ MUSIQUE_VOLUME: v });
      }, 400);
    });
    commande.appendChild(bouton);
    commande.appendChild(curseur);
    musique.commande = commande;
    musique.bouton = bouton;
    musique.curseur = curseur;
    (document.body || racine).appendChild(commande);
    placer(document);
  }

  /* (Re)démarre la musique d'après les réglages : elle reprend là où la page précédente l'a laissée (le temps écoulé depuis est
     rattrapé). Les pages affichées dans le lecteur ne la jouent jamais elles-mêmes. */
  function demarrerMusique() {
    if (enCadre) {
      return;
    }
    var m = reglages().musique;
    if (!m || !m.actif || !m.fichier) {
      arreterMusique();
      return;
    }
    if (musique.audio && musique.fichier === m.fichier) {
      musique.audio.volume = fraction(m.volume);
      if (musique.curseur) {
        musique.curseur.value = String(Math.round(Number(m.volume) || 0));
      }
      majCommande();
      return;
    }
    arreterMusique();
    var etat = etatSauve();
    var audio = new Audio(adresse(m.fichier));
    audio.loop = true;
    audio.preload = "auto";
    audio.volume = fraction(m.volume);
    musique.audio = audio;
    musique.fichier = m.fichier;
    if (etat.fichier === m.fichier && etat.t > 0) {
      var ecoule = etat.joue && etat.ts ? Math.max(0, Math.min(10, (Date.now() - etat.ts) / 1000)) : 0;
      var reprendre = function () {
        try {
          var duree = audio.duration;
          var position = etat.t + ecoule;
          audio.currentTime = duree && isFinite(duree) ? position % duree : position;
        } catch (erreur) { /* position non disponible : on repart du début */ }
      };
      audio.addEventListener("loadedmetadata", reprendre, { once: true });
    }
    creerCommande(m.volume);
    audio.addEventListener("play", majCommande);
    audio.addEventListener("pause", majCommande);
    majCommande();
    lancerMusique();
    musique.minuteur = setInterval(memoriserPosition, 500);
  }

  /* Prend de nouveaux réglages (la Configuration vient d'être enregistrée) sans recharger la page. Dans un cadre, c'est le
     lecteur (la fenêtre du haut) qui les applique à la musique. */
  function appliquer(nouveaux) {
    racine.setAttribute("data-sons", JSON.stringify(nouveaux || {}));
    prechargerTout();
    if (enCadre) {
      try {
        if (window.parent.WikiSons && window.parent.WikiSons !== window.WikiSons) {
          window.parent.WikiSons.appliquer(nouveaux);
        }
      } catch (erreur) { /* le lecteur n'est pas accessible : rien à faire */ }
      return;
    }
    demarrerMusique();
  }

  window.WikiSons = { jouer: jouer, arreter: arreter, jouerFichier: jouerFichier, appliquer: appliquer, reglages: reglages, adresse: adresse,
                      geste: geste, placer: placer };

  window.addEventListener("pagehide", memoriserPosition);
  window.addEventListener("beforeunload", memoriserPosition);
  prechargerTout();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", demarrerMusique);
  } else {
    demarrerMusique();
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { jouer: jouer, jouerFichier: jouerFichier, appliquer: appliquer, adresse: adresse };
  }
})();
