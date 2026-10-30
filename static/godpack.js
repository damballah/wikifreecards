/* GOD PACK : un paquet dont TOUTES les cartes sont légendaires (une chance sur 10 000, réglable dans Configuration → Paquets).
   Annonce : feu d'artifice sur tout l'écran, fanfare de trompettes (synthétisée, aucun fichier), message « GOD PACK !!! » sans cadre qui
   zoome et dézoome. Un clic sur le message le fait disparaître : l'ouverture du paquet se poursuit comme d'habitude.
   WikiGodPack.jouer() renvoie une promesse résolue quand le message a été cliqué (le bouton d'essai de la Configuration l'utilise aussi). */
(function () {
  "use strict";

  var enCours = null;

  function reglagesSons() {
    try {
      return JSON.parse(document.documentElement.getAttribute("data-sons") || "{}") || {};
    } catch (erreur) {
      return {};
    }
  }

  function reduit() {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  /* ------------------------------------------------------------------ le son : fanfare de trompettes + explosions du feu d'artifice (tout est synthétisé) */
  function creerSon() {
    var reglages = reglagesSons();
    var Contexte = window.AudioContext || window.webkitAudioContext;
    if (reglages.actifs === false || !Contexte) {
      return null;
    }
    var ctx;
    try {
      ctx = new Contexte();
    } catch (erreur) {
      return null;
    }
    if (ctx.state === "suspended" && ctx.resume) {
      ctx.resume();
    }
    var volume = typeof reglages.volume === "number" ? Math.max(0, Math.min(100, reglages.volume)) / 100 : 0.7;
    var maitre = ctx.createGain();
    maitre.gain.value = 0.55 * volume;
    var compresseur = ctx.createDynamicsCompressor();
    maitre.connect(compresseur);
    compresseur.connect(ctx.destination);
    var t0 = ctx.currentTime + 0.05;

    /* une note de trompette : deux dents de scie légèrement désaccordées, filtre qui s'ouvre à l'attaque, vibrato léger */
    function note(frequence, debut, duree, force) {
      var gain = ctx.createGain();
      var filtre = ctx.createBiquadFilter();
      filtre.type = "lowpass";
      filtre.Q.value = 4;
      filtre.frequency.setValueAtTime(frequence * 1.6, t0 + debut);
      filtre.frequency.linearRampToValueAtTime(frequence * 6, t0 + debut + 0.07);
      filtre.frequency.linearRampToValueAtTime(frequence * 3.2, t0 + debut + duree);
      gain.gain.setValueAtTime(0.0001, t0 + debut);
      gain.gain.linearRampToValueAtTime(force, t0 + debut + 0.035);
      gain.gain.setValueAtTime(force * 0.82, t0 + debut + Math.max(0.05, duree - 0.08));
      gain.gain.linearRampToValueAtTime(0.0001, t0 + debut + duree);
      var vibrato = ctx.createOscillator();
      var profondeur = ctx.createGain();
      vibrato.frequency.value = 5.6;
      profondeur.gain.value = frequence * 0.006;
      vibrato.connect(profondeur);
      [0, 6].forEach(function (cents) {
        var o = ctx.createOscillator();
        o.type = "sawtooth";
        o.frequency.value = frequence;
        o.detune.value = cents;
        profondeur.connect(o.frequency);
        o.connect(filtre);
        o.start(t0 + debut);
        o.stop(t0 + debut + duree + 0.05);
      });
      vibrato.start(t0 + debut);
      vibrato.stop(t0 + debut + duree + 0.05);
      filtre.connect(gain);
      gain.connect(maitre);
    }

    /* « ta-ta-ta-TAAA ta-ta-ta-TAAAAA » : deux voix de trompettes, puis l'accord final */
    var G4 = 392, C5 = 523.25, E5 = 659.25, G5 = 783.99, C6 = 1046.5;
    [[G4, 0, 0.14], [G4, 0.17, 0.14], [G4, 0.34, 0.14], [C5, 0.52, 0.62],
     [G4, 1.22, 0.14], [C5, 1.42, 0.18], [E5, 1.64, 0.2], [G5, 1.86, 0.2]].forEach(function (n) {
      note(n[0], n[1], n[2], 0.55);
      note(n[0] * 1.2599, n[1], n[2], 0.28);           /* une tierce au-dessus : le côté cuivres */
    });
    [C5, E5, G5, C6].forEach(function (f) { note(f, 2.12, 1.9, 0.5); });
    /* une explosion de feu d'artifice : un « boum » grave, un souffle de bruit qui s'éteint et des crépitements, placés au hasard dans le stéréo */
    var bruitBlanc = ctx.createBuffer(1, Math.floor(ctx.sampleRate * 1.6), ctx.sampleRate);
    var donnees = bruitBlanc.getChannelData(0);
    for (var i = 0; i < donnees.length; i += 1) {
      donnees[i] = Math.random() * 2 - 1;
    }
    var recentes = [];

    function explosion() {
      var maintenant = ctx.currentTime;
      recentes = recentes.filter(function (t) { return maintenant - t < 0.35; });
      if (recentes.length >= 5) {
        return;                                              /* pas plus de 5 explosions en même temps */
      }
      recentes.push(maintenant);
      var sortie = maitre;
      if (ctx.createStereoPanner) {
        var pan = ctx.createStereoPanner();
        pan.pan.value = Math.random() * 1.6 - 0.8;
        pan.connect(maitre);
        sortie = pan;
      }
      var force = 0.5 + Math.random() * 0.5;
      var boum = ctx.createOscillator();                      /* le « boum » : une sinusoïde qui plonge */
      var gb = ctx.createGain();
      boum.type = "sine";
      boum.frequency.setValueAtTime(150 + Math.random() * 60, maintenant);
      boum.frequency.exponentialRampToValueAtTime(34, maintenant + 0.5);
      gb.gain.setValueAtTime(0.0001, maintenant);
      gb.gain.linearRampToValueAtTime(0.9 * force, maintenant + 0.012);
      gb.gain.exponentialRampToValueAtTime(0.0001, maintenant + 0.62);
      boum.connect(gb);
      gb.connect(sortie);
      boum.start(maintenant);
      boum.stop(maintenant + 0.7);
      var souffle = ctx.createBufferSource();                 /* le souffle : du bruit dont le filtre se ferme */
      var fs = ctx.createBiquadFilter();
      var gs = ctx.createGain();
      souffle.buffer = bruitBlanc;
      souffle.playbackRate.value = 0.8 + Math.random() * 0.5;
      fs.type = "lowpass";
      fs.frequency.setValueAtTime(5200, maintenant);
      fs.frequency.exponentialRampToValueAtTime(260, maintenant + 0.9);
      gs.gain.setValueAtTime(0.0001, maintenant);
      gs.gain.linearRampToValueAtTime(0.55 * force, maintenant + 0.01);
      gs.gain.exponentialRampToValueAtTime(0.0001, maintenant + 1.0);
      souffle.connect(fs);
      fs.connect(gs);
      gs.connect(sortie);
      souffle.start(maintenant, Math.random() * 0.4);
      souffle.stop(maintenant + 1.1);
      var crepitements = 7 + Math.floor(Math.random() * 9);   /* les crépitements : de petits claquements aigus, de moins en moins forts */
      for (var k = 0; k < crepitements; k += 1) {
        var debut = maintenant + 0.08 + Math.random() * 0.95;
        var src = ctx.createBufferSource();
        var hp = ctx.createBiquadFilter();
        var gc = ctx.createGain();
        src.buffer = bruitBlanc;
        hp.type = "highpass";
        hp.frequency.value = 2200 + Math.random() * 3200;
        var vol = 0.32 * force * (1 - (debut - maintenant) / 1.15) * (0.5 + Math.random() * 0.5);
        gc.gain.setValueAtTime(0.0001, debut);
        gc.gain.linearRampToValueAtTime(Math.max(0.01, vol), debut + 0.002);
        gc.gain.exponentialRampToValueAtTime(0.0001, debut + 0.03 + Math.random() * 0.04);
        src.connect(hp);
        hp.connect(gc);
        gc.connect(sortie);
        src.start(debut, Math.random());
        src.stop(debut + 0.1);
      }
    }

    return {
      explosion: explosion,
      arreter: function () {
        try {
          maitre.gain.cancelScheduledValues(ctx.currentTime);
          maitre.gain.setValueAtTime(maitre.gain.value, ctx.currentTime);
          maitre.gain.linearRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
          setTimeout(function () { try { ctx.close(); } catch (erreur) { /* déjà fermé */ } }, 400);
        } catch (erreur) { /* sans importance */ }
      }
    };
  }

  /* ------------------------------------------------------------------ le feu d'artifice (canevas sur tout l'écran) */
  function feuxArtifice(canevas, surGerbe) {
    var ctx = canevas.getContext("2d");
    var particules = [];
    var actif = true;
    var dernier = 0;
    var prochaine = 0;
    var echelle = Math.min(window.devicePixelRatio || 1, 1.5);

    function ajuster() {
      canevas.width = Math.floor(window.innerWidth * echelle);
      canevas.height = Math.floor(window.innerHeight * echelle);
      canevas.style.width = window.innerWidth + "px";
      canevas.style.height = window.innerHeight + "px";
    }
    ajuster();
    window.addEventListener("resize", ajuster);

    function gerbe(x, y) {
      if (surGerbe) {
        surGerbe();                                         /* le son de l'explosion, au même instant */
      }
      var teinte = Math.random() * 360;
      var nombre = 70 + Math.floor(Math.random() * 40);
      var bicolore = Math.random() < 0.4;
      for (var i = 0; i < nombre && particules.length < 1100; i += 1) {
        var angle = (Math.PI * 2 * i) / nombre + Math.random() * 0.12;
        var vitesse = (1.2 + Math.random() * 4.6) * echelle * (Math.random() < 0.3 ? 0.55 : 1);
        particules.push({
          x: x, y: y, vx: Math.cos(angle) * vitesse, vy: Math.sin(angle) * vitesse,
          vie: 1, usure: 0.008 + Math.random() * 0.012,
          teinte: bicolore && i % 2 ? (teinte + 180) % 360 : teinte, taille: (1.4 + Math.random() * 1.8) * echelle
        });
      }
    }

    function image(maintenant) {
      if (!actif) {
        return;
      }
      var dt = Math.min(48, maintenant - (dernier || maintenant)) / 16.67;
      dernier = maintenant;
      ctx.globalCompositeOperation = "destination-out";            /* les traînées s'effacent doucement, le fond reste transparent */
      ctx.fillStyle = "rgba(0, 0, 0, " + Math.min(0.5, 0.2 * dt) + ")";
      ctx.fillRect(0, 0, canevas.width, canevas.height);
      ctx.globalCompositeOperation = "lighter";
      if (maintenant >= prochaine) {
        gerbe(canevas.width * (0.1 + Math.random() * 0.8), canevas.height * (0.1 + Math.random() * 0.55));
        prochaine = maintenant + (reduit() ? 1400 : 260 + Math.random() * 420);
      }
      for (var i = particules.length - 1; i >= 0; i -= 1) {
        var p = particules[i];
        p.vy += 0.045 * echelle * dt;
        p.vx *= 0.992;
        p.vy *= 0.992;
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        p.vie -= p.usure * dt;
        if (p.vie <= 0) {
          particules.splice(i, 1);
          continue;
        }
        ctx.beginPath();
        ctx.fillStyle = "hsla(" + p.teinte + ", 100%, " + (55 + 25 * p.vie) + "%, " + Math.min(1, p.vie * 1.4) + ")";
        ctx.arc(p.x, p.y, p.taille * (0.5 + p.vie * 0.6), 0, Math.PI * 2);
        ctx.fill();
      }
      window.requestAnimationFrame(image);
    }
    gerbe(canevas.width * 0.5, canevas.height * 0.35);
    window.requestAnimationFrame(image);
    return function arreter() {
      actif = false;
      window.removeEventListener("resize", ajuster);
    };
  }

  /* ------------------------------------------------------------------ l'annonce */
  function jouer() {
    if (enCours) {
      return enCours;
    }
    enCours = new Promise(function (resoudre) {
      var racine = document.createElement("div");
      racine.id = "godpack";
      racine.className = "godpack";
      racine.setAttribute("role", "dialog");
      racine.setAttribute("aria-modal", "true");
      racine.setAttribute("aria-label", "GOD PACK !!! Un paquet de cartes toutes légendaires");
      var canevas = document.createElement("canvas");
      canevas.className = "godpack__feux";
      canevas.setAttribute("aria-hidden", "true");
      var message = document.createElement("div");
      message.className = "godpack__message";
      message.setAttribute("role", "button");
      message.setAttribute("tabindex", "0");
      message.setAttribute("aria-label", "GOD PACK ! Clique pour ouvrir le paquet");
      var titre = document.createElement("span");
      titre.className = "godpack__titre";
      titre.textContent = "GOD PACK !!!";
      var aide = document.createElement("span");
      aide.className = "godpack__aide";
      aide.textContent = "Clique pour ouvrir le paquet";
      message.appendChild(titre);
      message.appendChild(aide);
      racine.appendChild(canevas);
      racine.appendChild(message);
      document.body.appendChild(racine);
      var precedent = document.activeElement;
      var son = creerSon();
      var arretFeux = feuxArtifice(canevas, son ? son.explosion : null);
      var fini = false;
      message.focus({ preventScroll: true });

      function terminer() {
        if (fini) {
          return;
        }
        fini = true;
        message.removeEventListener("click", terminer);
        document.removeEventListener("keydown", clavier, true);
        if (son) {
          son.arreter();                                    /* la fanfare s'arrête avec le message */
        }
        racine.classList.add("godpack--part");
        setTimeout(function () {
          arretFeux();
          if (racine.parentNode) {
            racine.parentNode.removeChild(racine);
          }
          if (precedent && precedent.focus) {
            try { precedent.focus({ preventScroll: true }); } catch (erreur) { /* sans importance */ }
          }
          enCours = null;
          resoudre();
        }, reduit() ? 0 : 260);
      }

      function clavier(evenement) {
        if (evenement.key === "Enter" || evenement.key === " " || evenement.key === "Escape") {
          evenement.preventDefault();
          evenement.stopPropagation();
          terminer();
        }
      }
      message.addEventListener("click", terminer);
      document.addEventListener("keydown", clavier, true);
    });
    return enCours;
  }

  window.WikiGodPack = { jouer: jouer };

  /* bouton d'essai de la page Configuration (section Paquets) */
  document.addEventListener("click", function (evenement) {
    var cible = evenement.target;
    if (cible && cible.closest && cible.closest("#godpack-essai")) {
      evenement.preventDefault();
      jouer();
    }
  });
})();
