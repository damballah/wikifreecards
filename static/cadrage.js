/* Le moteur d'édition du CADRAGE d'une illustration (position et taille dans le cadre de la carte), partagé par la fenêtre « Redimensionner/Positionner l'image
   actuelle » (collection) et par l'aperçu du Créateur de cartes. Voir cadrage.py pour le modèle : `z` (taille : 1 = l'image remplit tout juste le cadre, de 0,1 à 4 ;
   au-dessous de 1 elle est plus petite que le cadre), `x` et `y` (0 à 100 : où l'image se place dans la marge restante ; 50 / 25 = cadrage d'origine).

   WikiCadrage.monter({ scene, cadre, image, etat, curseur, lecture, surChangement }) pose sur la scène (un élément position:relative qui contient la carte `cadre`) le contour
   en tirets de l'image, la partie grisée qui dépasse du cadre et 8 poignées. L'image est tirée (clic maintenu), redimensionnée (poignées, molette, curseur, clavier).
   Ce qui s'affiche dans le cadre est la VRAIE carte : le moteur ne fait que poser les variables CSS --cz --cx --cy --cr sur son image (même CSS que la collection). */
(function () {
  "use strict";

  var ZMIN = 0.1;
  var ZMAX = 4;
  var DEFAUT = { z: 1, x: 50, y: 25 };

  function limiter(v, mini, maxi) {
    return Math.max(mini, Math.min(maxi, v));
  }

  function nombre(texte) {
    var v = parseFloat(texte);
    return isFinite(v) ? v : null;
  }

  /* Le cadrage actuel d'une image de carte (variables CSS) : {z, x, y}. */
  function lire(image) {
    var etat = { z: DEFAUT.z, x: DEFAUT.x, y: DEFAUT.y };
    if (!image) {
      return etat;
    }
    var s = image.style;
    if (image.hasAttribute("data-cadre")) {
      etat.z = limiter(nombre(s.getPropertyValue("--cz")) || DEFAUT.z, ZMIN, ZMAX);
      var cx = nombre(s.getPropertyValue("--cx")), cy = nombre(s.getPropertyValue("--cy"));
      etat.x = cx === null ? DEFAUT.x : limiter(cx, 0, 100);
      etat.y = cy === null ? DEFAUT.y : limiter(cy, 0, 100);
    } else {                                                          /* ancien réglage : zoom de 1 à 4 et position en % */
      etat.z = limiter(nombre(s.getPropertyValue("--zi")) || DEFAUT.z, 1, ZMAX);
      var xi = nombre(s.getPropertyValue("--xi")), yi = nombre(s.getPropertyValue("--yi"));
      etat.x = xi === null ? DEFAUT.x : limiter(xi, 0, 100);
      etat.y = yi === null ? DEFAUT.y : limiter(yi, 0, 100);
    }
    return etat;
  }

  /* Pose le cadrage sur l'image d'une carte (la taille et la place exactes sont calculées par le CSS à partir du ratio). */
  function appliquer(image, etat, ratio) {
    if (!image || !ratio) {
      return;
    }
    image.setAttribute("data-cadre", "1");
    image.style.removeProperty("--zi");
    image.style.removeProperty("--xi");
    image.style.removeProperty("--yi");
    image.style.setProperty("--cz", String(Math.round(etat.z * 1000) / 1000));
    image.style.setProperty("--cx", String(Math.round(etat.x * 1000) / 1000));
    image.style.setProperty("--cy", String(Math.round(etat.y * 1000) / 1000));
    image.style.setProperty("--cr", String(Math.round(ratio * 10000) / 10000));
  }

  function monter(options) {
    var scene = options.scene;
    var cadre = options.cadre;
    var etat = options.etat || { z: DEFAUT.z, x: DEFAUT.x, y: DEFAUT.y };
    var image = null;
    var nat = { w: 0, h: 0 };
    var F = { l: 0, t: 0, w: 1, h: 1 };
    var geste = null;
    var actif = true;

    var fantome = document.createElement("img");                     /* l'image entière, grisée : montre ce qui dépasse du cadre */
    fantome.className = "cadrage__fantome";
    fantome.alt = "";
    fantome.draggable = false;
    fantome.referrerPolicy = "no-referrer";
    var rectangle = document.createElement("div");                   /* le contour en tirets de l'image */
    rectangle.className = "cadrage__rect";
    var POIGNEES = [[-1, -1, "nw"], [0, -1, "n"], [1, -1, "ne"], [1, 0, "e"], [1, 1, "se"], [0, 1, "s"], [-1, 1, "sw"], [-1, 0, "w"]];
    var poignees = POIGNEES.map(function (d) {
      var p = document.createElement("span");
      p.className = "cadrage__poignee cadrage__poignee--" + d[2];
      p.setAttribute("data-hx", String(d[0]));
      p.setAttribute("data-hy", String(d[1]));
      return p;
    });
    scene.appendChild(fantome);
    scene.appendChild(rectangle);
    poignees.forEach(function (p) { scene.appendChild(p); });

    function ratio() {
      return nat.w && nat.h ? nat.w / nat.h : 0;
    }
    function mesurer() {
      var visuel = cadre.querySelector(".carte__visuel");
      if (!visuel) {
        return;
      }
      var fr = visuel.getBoundingClientRect();
      var sr = scene.getBoundingClientRect();
      F = { l: fr.left - sr.left, t: fr.top - sr.top, w: Math.max(1, fr.width), h: Math.max(1, fr.height) };
    }
    function base() {                                                /* taille de l'image quand elle remplit juste le cadre */
      var a = nat.w / nat.h;
      return a > F.w / F.h ? { w: F.h * a, h: F.h } : { w: F.w, h: F.w / a };
    }
    function rect() {
      var b = base();
      var ox = F.l + F.w * etat.x / 100, oy = F.t + F.h * etat.y / 100;
      var gauche0 = F.l + (F.w - b.w) * etat.x / 100, haut0 = F.t + (F.h - b.h) * etat.y / 100;
      return { l: ox + (gauche0 - ox) * etat.z, t: oy + (haut0 - oy) * etat.z, w: b.w * etat.z, h: b.h * etat.z };
    }
    function depuisRect(l, t, w) {                                   /* le rectangle voulu -> (z, x, y) ; l'image reste dans les limites de taille et de place */
      var b = base();
      var z = limiter(w / b.w, ZMIN, ZMAX);
      var dx = F.w - b.w * z, dy = F.h - b.h * z;
      etat.z = z;
      if (Math.abs(dx) > 0.5) {                                      /* (sans marge de mouvement sur un axe, la position ne change pas) */
        etat.x = limiter(100 * (l - F.l) / dx, 0, 100);
      }
      if (Math.abs(dy) > 0.5) {
        etat.y = limiter(100 * (t - F.t) / dy, 0, 100);
      }
    }
    function dessiner() {
      if (!nat.w || !actif) {
        return;
      }
      appliquer(image, etat, ratio());
      var r = rect();
      fantome.style.cssText = "left:" + r.l + "px;top:" + r.t + "px;width:" + r.w + "px;height:" + r.h + "px;clip-path:polygon(evenodd,0 0," + r.w + "px 0," + r.w + "px " + r.h +
        "px,0 " + r.h + "px,0 0," + (F.l - r.l) + "px " + (F.t - r.t) + "px," + (F.l - r.l) + "px " + (F.t - r.t + F.h) + "px," + (F.l - r.l + F.w) + "px " + (F.t - r.t + F.h) +
        "px," + (F.l - r.l + F.w) + "px " + (F.t - r.t) + "px," + (F.l - r.l) + "px " + (F.t - r.t) + "px)";
      rectangle.style.cssText = "left:" + r.l + "px;top:" + r.t + "px;width:" + r.w + "px;height:" + r.h + "px";
      var ls = scene.clientWidth, hs = scene.clientHeight;
      poignees.forEach(function (p) {                                /* les poignées restent toujours dans la scène, même quand l'image est très grande */
        var hx = Number(p.getAttribute("data-hx")), hy = Number(p.getAttribute("data-hy"));
        var x = r.l + r.w * (hx + 1) / 2, y = r.t + r.h * (hy + 1) / 2;
        p.style.left = limiter(x, 8, ls - 8) + "px";
        p.style.top = limiter(y, 8, hs - 8) + "px";
      });
      if (options.curseur) {
        options.curseur.value = String(etat.z);
      }
      if (options.lecture) {
        options.lecture.textContent = "Agrandissement ×" + etat.z.toFixed(2);
      }
    }
    function change() {
      dessiner();
      if (options.surChangement) {
        options.surChangement({ z: etat.z, x: etat.x, y: etat.y }, ratio());
      }
    }
    function pointeur(evenement) {
      var sr = scene.getBoundingClientRect();
      return { x: evenement.clientX - sr.left, y: evenement.clientY - sr.top };
    }

    function surDebut(evenement) {
      if (!nat.w || !actif || (evenement.pointerType === "mouse" && evenement.button !== 0)) {
        return;
      }
      var cible = evenement.target;
      var poignee = cible.closest ? cible.closest(".cadrage__poignee") : null;
      var p = pointeur(evenement);
      var r = rect();
      if (poignee) {
        geste = { type: "taille", hx: Number(poignee.getAttribute("data-hx")), hy: Number(poignee.getAttribute("data-hy")), depart: r };
      } else {
        geste = { type: "deplace", depart: r, p0: p };                /* clic maintenu au milieu : on déplace */
      }
      scene.setPointerCapture(evenement.pointerId);
      scene.classList.add("cadrage__scene--geste");
      evenement.preventDefault();
    }
    function surMouvement(evenement) {
      if (!geste) {
        return;
      }
      var p = pointeur(evenement);
      var d = geste.depart;
      if (geste.type === "deplace") {
        depuisRect(d.l + p.x - geste.p0.x, d.t + p.y - geste.p0.y, d.w);
      } else {
        var rapport = d.w / d.h;
        var ax = d.l + d.w * (geste.hx === 1 ? 0 : (geste.hx === -1 ? 1 : 0.5));        /* le point opposé reste fixe */
        var ay = d.t + d.h * (geste.hy === 1 ? 0 : (geste.hy === -1 ? 1 : 0.5));
        var w1 = geste.hx !== 0 ? (p.x - ax) * geste.hx : 0;
        var w2 = geste.hy !== 0 ? (p.y - ay) * geste.hy * rapport : 0;
        var w = Math.max(w1, w2, 1);
        var nl = geste.hx === 1 ? ax : (geste.hx === -1 ? ax - w : ax - w / 2);
        var nt = geste.hy === 1 ? ay : (geste.hy === -1 ? ay - w / rapport : ay - w / rapport / 2);
        depuisRect(nl, nt, w);
      }
      change();
    }
    function surFin(evenement) {
      if (geste) {
        geste = null;
        scene.classList.remove("cadrage__scene--geste");
        try { scene.releasePointerCapture(evenement.pointerId); } catch (erreur) { /* déjà relâché */ }
      }
    }
    function surMolette(evenement) {
      if (!nat.w || !actif) {
        return;
      }
      evenement.preventDefault();
      var p = pointeur(evenement), r = rect(), b = base();
      var f = Math.exp(-evenement.deltaY * 0.0015);
      var w = limiter(r.w * f, b.w * ZMIN, b.w * ZMAX);
      var echelle = w / r.w;
      depuisRect(p.x - (p.x - r.l) * echelle, p.y - (p.y - r.t) * echelle, w);     /* le point sous la souris ne bouge pas */
      change();
    }
    function surCurseur() {
      var r = rect(), b = base();
      var w = b.w * limiter(Number(options.curseur.value), ZMIN, ZMAX);
      depuisRect(r.l + r.w / 2 - w / 2, r.t + r.h / 2 - (w * r.h / r.w) / 2, w);     /* le centre de l'image reste en place */
      change();
    }
    function surTouche(evenement) {
      if (!nat.w || !actif) {
        return;
      }
      var r = rect(), pas = Math.max(2, F.w * 0.02), w = r.w;
      var l = r.l, t = r.t;
      if (evenement.key === "ArrowLeft") { l -= pas; }
      else if (evenement.key === "ArrowRight") { l += pas; }
      else if (evenement.key === "ArrowUp") { t -= pas; }
      else if (evenement.key === "ArrowDown") { t += pas; }
      else if (evenement.key === "+" || evenement.key === "=") { w = r.w * 1.05; l = r.l - (w - r.w) / 2; t = r.t - (w * r.h / r.w - r.h) / 2; }
      else if (evenement.key === "-" || evenement.key === "_") { w = Math.max(base().w * ZMIN, r.w / 1.05); l = r.l - (w - r.w) / 2; t = r.t - (w * r.h / r.w - r.h) / 2; }
      else { return; }
      evenement.preventDefault();
      depuisRect(l, t, w);
      change();
    }
    scene.addEventListener("pointerdown", surDebut);
    scene.addEventListener("pointermove", surMouvement);
    scene.addEventListener("pointerup", surFin);
    scene.addEventListener("pointercancel", surFin);
    scene.addEventListener("wheel", surMolette, { passive: false });
    scene.addEventListener("keydown", surTouche);
    if (options.curseur) {
      options.curseur.min = String(ZMIN);
      options.curseur.max = String(ZMAX);
      options.curseur.step = "0.01";
      options.curseur.addEventListener("input", surCurseur);
    }

    /* (Re)prend l'image de la carte (elle peut être remplacée quand l'aperçu est redessiné), la remesure et redessine. */
    function rafraichir() {
      image = typeof options.image === "function" ? options.image() : options.image;
      if (!image) {
        nat = { w: 0, h: 0 };
        fantome.removeAttribute("src");
        return;
      }
      function pret() {
        nat = { w: image.naturalWidth, h: image.naturalHeight };
        if (nat.w && nat.h) {
          fantome.src = image.currentSrc || image.src;
          mesurer();
          dessiner();
          if (options.surPret) {
            options.surPret(ratio());
          }
        } else if (options.surErreur) {
          options.surErreur();
        }
      }
      image.loading = "eager";
      if (image.complete && image.naturalWidth) {
        pret();
      } else {
        image.addEventListener("load", pret, { once: true });
        image.addEventListener("error", pret, { once: true });
      }
    }

    return {
      etat: etat,
      ratio: ratio,
      rafraichir: rafraichir,
      remesurer: function () { mesurer(); dessiner(); },
      reinitialiser: function () {
        etat.z = DEFAUT.z;
        etat.x = DEFAUT.x;
        etat.y = DEFAUT.y;
        change();
      },
      appliquerA: function (nouvelleImage) { appliquer(nouvelleImage, etat, ratio()); },
      afficher: function (visible) {
        actif = visible;
        [fantome, rectangle].concat(poignees).forEach(function (e) { e.hidden = !visible; });
        if (visible) {
          mesurer();
          dessiner();
        }
      },
      detruire: function () {
        actif = false;
        scene.removeEventListener("pointerdown", surDebut);
        scene.removeEventListener("pointermove", surMouvement);
        scene.removeEventListener("pointerup", surFin);
        scene.removeEventListener("pointercancel", surFin);
        scene.removeEventListener("wheel", surMolette);
        scene.removeEventListener("keydown", surTouche);
        if (options.curseur) {
          options.curseur.removeEventListener("input", surCurseur);
        }
        [fantome, rectangle].concat(poignees).forEach(function (e) { if (e.parentNode) { e.parentNode.removeChild(e); } });
      }
    };
  }

  window.WikiCadrage = { ZMIN: ZMIN, ZMAX: ZMAX, DEFAUT: DEFAUT, lire: lire, appliquer: appliquer, monter: monter };
})();
