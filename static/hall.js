/* Hall des collections : mon partage (pseudo, nœud, pastilles P et C), recherche et liste des collectionneurs.
   Tout texte venu du réseau (pseudos, noms de collection) est affiché avec textContent : jamais interprété. */
(function () {
  "use strict";

  var racine = document.getElementById("hall-moi");
  if (!racine) {
    return;
  }
  var jeton = document.body.getAttribute("data-jeton");
  var etat = null;
  var page = 1;

  function $(id) {
    return document.getElementById(id);
  }

  function appeler(chemin, corps) {
    return fetch(chemin, {
      method: "POST",
      headers: { "X-Jeton": jeton, "Content-Type": "application/json" },
      body: JSON.stringify(corps || {})
    }).catch(function () {
      throw new Error("le serveur local est injoignable (lance python main.py)");
    }).then(function (reponse) {
      return reponse.json().catch(function () {
        return {};
      }).then(function (donnees) {
        if (!reponse.ok && reponse.status !== 202) {
          var erreur = new Error(donnees.erreur || "erreur du serveur");
          erreur.statut = reponse.status;
          throw erreur;
        }
        return donnees;
      });
    });
  }

  /* Copie un texte : presse-papiers si le navigateur l'autorise ; sinon on SÉLECTIONNE le texte et on dit d'appuyer sur
     Ctrl+C (jamais d'échec silencieux). `noeud` : l'élément qui contient le texte ; `bouton` : celui sur lequel on a cliqué. */
  function copierTexte(texte, noeud, bouton) {
    function repli() {
      var copie = false;
      try {
        if (noeud.select) {
          noeud.select();
        } else {
          var plage = document.createRange();
          plage.selectNodeContents(noeud);
          var selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(plage);
        }
        copie = document.execCommand && document.execCommand("copy");
      } catch (erreur) {
        copie = false;
      }
      bouton.textContent = copie ? "Copié ✓" : "Texte sélectionné : appuie sur Ctrl+C";
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(texte).then(function () {
        bouton.textContent = "Copié ✓";
      }).catch(repli);
    } else {
      repli();
    }
  }

  function el(balise, classe, texte) {
    var e = document.createElement(balise);
    if (classe) {
      e.className = classe;
    }
    if (texte !== undefined && texte !== null) {
      e.textContent = texte;
    }
    return e;
  }

  function message(zone, texte, genre) {
    zone.textContent = texte || "";
    zone.classList.toggle("createur__etat--erreur", genre === "erreur");
    zone.classList.toggle("createur__etat--ok", genre === "ok");
  }

  /* ------------------------------------------------------------------------ mon partage */

  var MODES = { tor: "Tor", direct: "Direct", local: "Local" };

  function casePartage(texte, aide, coche, cle, desactive) {
    var etiquette = el("label", "hall__interrupteur");
    var saisie = document.createElement("input");
    saisie.type = "checkbox";
    saisie.checked = !!coche;
    saisie.disabled = !!desactive;
    saisie.setAttribute("data-partage", cle);
    saisie.addEventListener("change", function () {
      var corps = {};
      corps[cle] = saisie.checked;
      saisie.disabled = true;
      appeler("/api/hall/partage", corps).then(function (donnees) {
        etat = donnees;
        rendreMoi();
        surveillerPret();
        if (cle === "actif" && saisie.checked) {
          return surveillerDemarrage(12);
        }
      }).catch(function (erreur) {
        saisie.checked = !saisie.checked;
        saisie.disabled = false;
        message($("hall-contact-etat"), erreur.message, "erreur");
      });
    });
    etiquette.appendChild(saisie);
    var corps = el("span", "hall__interrupteur-texte");
    corps.appendChild(el("strong", null, texte));
    corps.appendChild(el("small", null, aide));
    etiquette.appendChild(corps);
    return etiquette;
  }

  function rendreMoi() {
    var zone = $("hall-moi-corps");
    zone.textContent = "";
    if (!etat.disponible) {
      zone.appendChild(el("p", "createur__etat createur__etat--erreur",
        "Le partage demande la bibliothèque « cryptography » : lance « pip install cryptography », puis relance le programme."));
      return;
    }
    var haut = el("div", "hall__moi-ligne");
    if (etat.pseudo) {
      var p = el("p", "hall__pseudo");
      p.appendChild(document.createTextNode("Ton pseudo : "));
      p.appendChild(el("strong", null, etat.etiquette));
      haut.appendChild(p);
      var changer = el("button", "bouton-site", "Changer");
      changer.type = "button";
      changer.addEventListener("click", ouvrirPseudo);
      var supprimer = el("button", "bouton-site", "Supprimer mon pseudo");
      supprimer.type = "button";
      supprimer.addEventListener("click", function () {
        if (!window.confirm("Supprimer ton pseudo ? Tu ne seras plus trouvable dans le Hall (tu pourras en créer un autre).")) {
          return;
        }
        appeler("/api/hall/pseudo/supprimer").then(function (d) {
          etat = d;
          rendreMoi();
          chargerListe();
        }).catch(function (e) {
          message($("hall-contact-etat"), e.message, "erreur");
        });
      });
      haut.appendChild(changer);
      haut.appendChild(supprimer);
    } else {
      haut.appendChild(el("p", "hall__pseudo", "Tu n'as pas encore de pseudo : sans lui, personne ne peut te trouver dans le Hall."));
      var creer = el("button", "bouton-site bouton-site--principal", "Créer mon pseudo");
      creer.type = "button";
      creer.addEventListener("click", ouvrirPseudo);
      haut.appendChild(creer);
    }
    zone.appendChild(haut);

    var interrupteurs = el("div", "hall__interrupteurs");
    interrupteurs.appendChild(casePartage("Activer mon nœud",
      "Les autres collectionneurs peuvent te trouver. Désactivé : tu peux toujours visiter les autres.", etat.actif, "actif", false));
    interrupteurs.appendChild(casePartage("Profil visible (pastille P verte)",
      "Titre, biographie, résumé et vitrines, en lecture seule.", etat.profil, "profil", false));
    interrupteurs.appendChild(casePartage("Collection visible (pastille C verte)",
      "Tes cartes, en lecture seule : on peut en rapatrier des copies. Jamais tes favoris, ta corbeille ni tes réglages.",
      etat.collection, "collection", false));
    zone.appendChild(interrupteurs);

    var tor = etat.tor || {};
    if (tor.requis && !tor.detecte) {
      var alerte = el("div", "hall__tor-alerte");
      alerte.setAttribute("role", "alert");
      alerte.appendChild(el("strong", null, "Tor n'est pas détecté sur cet ordinateur."));
      alerte.appendChild(el("span", null, " Sans lui, personne ne peut te joindre et tu ne peux pas visiter les collectionneurs qui passent par Tor."));
      var aide = el("button", "bouton-site bouton-site--principal", "Que faire ?");
      aide.type = "button";
      aide.addEventListener("click", ouvrirTor);
      var lancer = el("button", "bouton-site", "Lancer Tor");
      lancer.type = "button";
      lancer.addEventListener("click", function () {
        ouvrirTor();
        lancerTor();
      });
      alerte.appendChild(aide);
      alerte.appendChild(lancer);
      zone.appendChild(alerte);
    } else if (tor.requis && tor.detecte) {
      zone.appendChild(el("p", "hall__aide", "Tor détecté ✓" + (tor.navigateur ? " (navigateur Tor)" : "") +
        (tor.lance_par_nous ? " · lancé par ce programme" : "")));
    }

    var service = etat.service || {};
    if (etat.actif && !service.pret && service.etat !== "erreur" && service.etat !== "erreur_tor" && service.etat !== "arrete") {
      var patience = el("div", "hall__patience");
      patience.setAttribute("role", "status");
      patience.appendChild(el("strong", null, "⏳ Ton nœud démarre : patiente une à deux minutes avant de tester."));
      patience.appendChild(el("span", null, " Il faut le temps que tout soit pleinement lancé (Tor se connecte au réseau, puis ton service est publié " +
        "et devient visible des autres). Si tu testes trop tôt, tu peux voir « collectionneur injoignable »."));
      if (service.attente) {
        patience.appendChild(el("em", null, " État : " + service.attente));
      }
      zone.appendChild(patience);
    }
    var ligne = el("p", "hall__aide");
    ligne.appendChild(document.createTextNode("Mode : " + (MODES[etat.mode] || etat.mode) + " · nœud : "));
    ligne.appendChild(el("strong", service.etat === "erreur" || service.etat === "erreur_tor" ? "hall__erreur" : null,
      etat.actif ? (service.message || "démarrage…") : "désactivé"));
    ligne.appendChild(document.createTextNode(" · "));
    var lien = el("a", null, "réglages du partage");
    lien.href = "/configuration";
    ligne.appendChild(lien);
    zone.appendChild(ligne);
    if (etat.avertissement) {
      zone.appendChild(el("p", "hall__aide hall__erreur", etat.avertissement));
    }

    if (etat.invitation) {
      var inv = el("div", "hall__invitation");
      inv.appendChild(el("span", null, "Ton invitation (à donner pour qu'on te trouve) :"));
      var champ = document.createElement("input");
      champ.type = "text";
      champ.readOnly = true;
      champ.value = etat.invitation;
      champ.setAttribute("aria-label", "Ton invitation");
      champ.addEventListener("focus", function () {
        champ.select();
      });
      var copier = el("button", "bouton-site", "Copier");
      copier.type = "button";
      copier.addEventListener("click", function () {
        copierTexte(etat.invitation, champ, copier);
      });
      inv.appendChild(champ);
      inv.appendChild(copier);
      zone.appendChild(inv);
    }
  }

  var minuteurPret = null;

  /* Tant que le nœud n'est pas pleinement lancé, on rafraîchit son état toutes les 5 secondes (le message d'attente
     disparaît tout seul quand il est prêt). */
  function surveillerPret() {
    clearTimeout(minuteurPret);
    var s = (etat && etat.service) || {};
    if (!etat || !etat.actif || s.pret || s.etat === "erreur" || s.etat === "erreur_tor" || s.etat === "arrete") {
      return;
    }
    minuteurPret = setTimeout(function () {
      chargerEtat();
    }, 5000);
  }

  function chargerEtat() {
    return appeler("/api/hall/etat").then(function (donnees) {
      etat = donnees;
      rendreMoi();
      surveillerPret();
      return donnees;
    }).catch(function (erreur) {
      $("hall-moi-corps").textContent = "";
      $("hall-moi-corps").appendChild(el("p", "createur__etat createur__etat--erreur", erreur.message));
    });
  }

  /* ----------------------------------------------------------------------------- Tor */

  var fenetreTor = $("hall-tor-fenetre");
  var dejaOuverteTor = false;

  function majFenetreTor() {
    var tor = (etat && etat.tor) || {};
    var ligne = $("hall-tor-etat-detection");
    ligne.textContent = "";
    var etatTexte = tor.detecte
      ? "✓ Tor est détecté" + (tor.navigateur ? " (navigateur Tor)" : "") + " : tout est prêt."
      : "✗ Tor n'est pas détecté (adresses testées : " + (tor.ports_testes || "") + ").";
    ligne.appendChild(el("strong", tor.detecte ? "hall__tor-ok" : "hall__erreur", etatTexte));
    ligne.appendChild(document.createTextNode(tor.executable
      ? "  tor.exe trouvé : " + tor.executable
      : (tor.detecte ? "" : "  Aucun tor.exe trouvé sur cet ordinateur pour l'instant.")));
    $("hall-torrc").textContent = tor.torrc || "";
    $("hall-tor-auto").checked = !!tor.auto;
    if (tor.erreur) {
      message($("hall-tor-etat"), tor.erreur, "erreur");
    }
  }

  function ouvrirTor() {
    majFenetreTor();
    fenetreTor.hidden = false;
    document.documentElement.classList.add("confirmation-ouverte");
    $("hall-tor-lancer").focus();
  }

  function fermerTor() {
    fenetreTor.hidden = true;
    document.documentElement.classList.remove("confirmation-ouverte");
  }

  function lancerTor() {
    var bouton = $("hall-tor-lancer");
    bouton.disabled = true;
    message($("hall-tor-etat"), "Lancement de Tor… (jusqu'à 25 secondes)");
    return appeler("/api/hall/tor/lancer").then(function (d) {
      if (etat) {
        etat.tor = d.tor;
      }
      majFenetreTor();
      message($("hall-tor-etat"), "Tor est lancé ✓ Il met 1 à 2 minutes à se connecter au réseau la première fois.", "ok");
      return chargerEtat();
    }).catch(function (erreur) {
      message($("hall-tor-etat"), erreur.message, "erreur");
    }).then(function () {
      bouton.disabled = false;
    });
  }

  function verifierTor() {
    message($("hall-tor-etat"), "Vérification…");
    return appeler("/api/hall/tor").then(function (tor) {
      if (etat) {
        etat.tor = tor;
      }
      majFenetreTor();
      message($("hall-tor-etat"), tor.detecte ? "Tor détecté ✓ Réactive ton nœud si besoin." : "Tor n'est toujours pas détecté : suis une des deux façons ci-dessus, puis réessaie.",
        tor.detecte ? "ok" : "erreur");
      return chargerEtat();
    }).catch(function (erreur) {
      message($("hall-tor-etat"), erreur.message, "erreur");
    });
  }

  $("hall-tor-lancer").addEventListener("click", lancerTor);
  $("hall-tor-verifier").addEventListener("click", verifierTor);
  $("hall-tor-fermer").addEventListener("click", fermerTor);
  $("hall-tor-auto").addEventListener("change", function () {
    var case_ = $("hall-tor-auto");
    appeler("/api/hall/tor/auto", { auto: case_.checked }).then(function (d) {
      if (etat) {
        etat.tor = d.tor;
      }
      message($("hall-tor-etat"), case_.checked ? "Tor sera lancé automatiquement au prochain démarrage du programme." : "Lancement automatique désactivé.", "ok");
    }).catch(function (erreur) {
      case_.checked = !case_.checked;
      message($("hall-tor-etat"), erreur.message, "erreur");
    });
  });
  $("hall-torrc-copier").addEventListener("click", function () {
    copierTexte($("hall-torrc").textContent, $("hall-torrc"), $("hall-torrc-copier"));
  });
  fenetreTor.addEventListener("click", function (evenement) {
    if (evenement.target === fenetreTor) {
      fermerTor();
    }
  });

  /* Après avoir activé le nœud : on attend le résultat du démarrage ; si Tor manque, l'aide s'ouvre toute seule. */
  function surveillerDemarrage(essais) {
    return appeler("/api/hall/etat").then(function (donnees) {
      etat = donnees;
      rendreMoi();
      var etatNoeud = (donnees.service || {}).etat;
      if (etatNoeud === "erreur_tor" || (donnees.tor && donnees.tor.requis && !donnees.tor.detecte && donnees.actif && etatNoeud !== "demarrage" && etatNoeud !== "serveur")) {
        ouvrirTor();
      } else if ((etatNoeud === "demarrage" || etatNoeud === "serveur") && essais > 0) {
        return new Promise(function (resolu) {
          setTimeout(resolu, 1000);
        }).then(function () {
          return surveillerDemarrage(essais - 1);
        });
      }
    });
  }

  /* --------------------------------------------------------------------------- pseudo */

  var fenetre = $("hall-pseudo-fenetre");

  function ouvrirPseudo() {
    message($("hall-pseudo-etat"), "");
    $("hall-pseudo-champ").value = etat && etat.pseudo ? etat.pseudo : "";
    fenetre.hidden = false;
    document.documentElement.classList.add("confirmation-ouverte");
    $("hall-pseudo-champ").focus();
  }

  function fermerPseudo() {
    fenetre.hidden = true;
    document.documentElement.classList.remove("confirmation-ouverte");
  }

  function validerPseudo() {
    var bouton = $("hall-pseudo-valider");
    bouton.disabled = true;
    message($("hall-pseudo-etat"), "Création…");
    appeler("/api/hall/pseudo", { pseudo: $("hall-pseudo-champ").value }).then(function (donnees) {
      etat = donnees;
      fermerPseudo();
      rendreMoi();
      chargerListe();
    }).catch(function (erreur) {
      message($("hall-pseudo-etat"), erreur.message, "erreur");
    }).then(function () {
      bouton.disabled = false;
    });
  }

  $("hall-pseudo-valider").addEventListener("click", validerPseudo);
  $("hall-pseudo-champ").addEventListener("keydown", function (evenement) {
    if (evenement.key === "Enter") {
      evenement.preventDefault();
      validerPseudo();
    }
  });
  $("hall-pseudo-plus-tard").addEventListener("click", fermerPseudo);
  document.addEventListener("keydown", function (evenement) {
    if (evenement.key === "Escape") {
      if (!fenetre.hidden) {
        fermerPseudo();
      } else if (!fenetreTor.hidden) {
        fermerTor();
      }
    }
  });

  /* ------------------------------------------------------------------------------ liste */

  var TITRES = {
    vert: ["accessible", "Accessible : le collectionneur accepte, et il est en ligne"],
    rouge: ["refusé", "Non accessible : le collectionneur ne l'autorise pas"],
    gris: ["inconnu", "Autorisé, mais le collectionneur est hors ligne ou pas encore vu"]
  };

  function pastille(lettre, couleur, quoi) {
    var s = el("span", "pastille-p pastille-p--" + couleur, lettre);
    s.title = quoi + " : " + TITRES[couleur][1];
    s.setAttribute("aria-label", quoi + " " + TITRES[couleur][0]);
    return s;
  }

  function lien(texte, adresse, classe) {
    var a = el("a", classe, texte);
    a.href = adresse;
    return a;
  }

  function ligneListe(p) {
    var tr = document.createElement("tr");
    var td = el("td", "hall__collection");
    td.appendChild(lien(p.collection || "(sans nom)", "/hall/collection?pair=" + encodeURIComponent(p.id), "hall__lien"));
    tr.appendChild(td);
    td = el("td", "hall__pseudo-cellule");
    td.appendChild(lien(p.pseudo, "/hall/profil?pair=" + encodeURIComponent(p.id), "hall__lien"));
    td.appendChild(el("span", "hall__repere", "·" + p.repere));
    if (p.moi) {
      td.appendChild(el("span", "hall__badge", "toi"));
    }
    if (p.conflit) {
      var c = el("span", "hall__badge hall__badge--alerte", "pseudo contesté");
      c.title = "Un autre collectionneur a revendiqué ce pseudo avant lui : le repère de la clé les distingue.";
      td.appendChild(c);
    }
    if (!p.en_ligne) {
      td.appendChild(el("span", "hall__badge hall__badge--gris", "hors ligne"));
    }
    tr.appendChild(td);
    td = el("td", "hall__num", String(p.cartes));
    tr.appendChild(td);
    td = el("td", "hall__pastille");
    td.appendChild(pastille("P", p.p, "Profil"));
    tr.appendChild(td);
    td = el("td", "hall__pastille");
    td.appendChild(pastille("C", p.c, "Collection"));
    tr.appendChild(td);
    return tr;
  }

  function filtres() {
    return {
      q: $("hall-q").value, p: $("hall-f-p").checked, c: $("hall-f-c").checked, en_ligne: $("hall-f-ligne").checked,
      min_cartes: Number($("hall-f-min").value) || 0, tri: $("hall-tri").value, page: page
    };
  }

  function chargerListe() {
    message($("hall-etat"), "Chargement…");
    return appeler("/api/hall/liste", filtres()).then(function (donnees) {
      var corps = $("hall-lignes");
      corps.textContent = "";
      donnees.pairs.forEach(function (p) {
        corps.appendChild(ligneListe(p));
      });
      page = donnees.page;
      $("hall-pages").hidden = donnees.pages <= 1;
      $("hall-page-texte").textContent = "Page " + donnees.page + " sur " + donnees.pages;
      $("hall-precedent").disabled = donnees.page <= 1;
      $("hall-suivant").disabled = donnees.page >= donnees.pages;
      message($("hall-etat"), donnees.total === 0
        ? "Aucun collectionneur trouvé. Ajoute une invitation plus bas, ou active ton nœud pour que les autres te trouvent."
        : donnees.total + " collectionneur" + (donnees.total > 1 ? "s" : ""));
    }).catch(function (erreur) {
      message($("hall-etat"), erreur.message, "erreur");
    });
  }

  $("hall-recherche").addEventListener("submit", function (evenement) {
    evenement.preventDefault();
    page = 1;
    chargerListe();
  });
  ["hall-f-p", "hall-f-c", "hall-f-ligne", "hall-tri"].forEach(function (id) {
    $(id).addEventListener("change", function () {
      page = 1;
      chargerListe();
    });
  });
  $("hall-f-min").addEventListener("change", function () {
    page = 1;
    chargerListe();
  });
  /* Changer de page : la liste repart de son début (le bouton est en bas, la page suivante s'affiche depuis le haut de la liste). */
  function changerDePage() {
    if (window.WikiDefilement) {
      window.WikiDefilement.versLeHaut($("hall-recherche"), chargerListe);
    } else {
      chargerListe();
    }
  }
  $("hall-precedent").addEventListener("click", function () {
    page = Math.max(1, page - 1);
    changerDePage();
  });
  $("hall-suivant").addEventListener("click", function () {
    page += 1;
    changerDePage();
  });

  /* ---------------------------------------------------------------------- contacts */

  $("hall-ajouter").addEventListener("click", function () {
    var bouton = $("hall-ajouter");
    var zone = $("hall-contact-etat");
    bouton.disabled = true;
    message(zone, "Contact en cours…");
    appeler("/api/hall/contact", { invitation: $("hall-invitation").value.trim() }).then(function (d) {
      message(zone, "Ajouté : " + (d.pseudo || "collectionneur sans pseudo") + (d.collection ? " (" + d.collection + ")" : ""), "ok");
      $("hall-invitation").value = "";
      chargerListe();
    }).catch(function (erreur) {
      message(zone, erreur.message, "erreur");
    }).then(function () {
      bouton.disabled = false;
    });
  });

  $("hall-actualiser").addEventListener("click", function () {
    message($("hall-contact-etat"), "Actualisation du réseau en cours (quelques secondes)…");
    appeler("/api/hall/actualiser").then(function () {
      [3000, 9000].forEach(function (delai) {
        setTimeout(function () {
          chargerListe();
          chargerEtat();
        }, delai);
      });
      setTimeout(function () {
        message($("hall-contact-etat"), "Réseau actualisé.", "ok");
      }, 9100);
    }).catch(function (erreur) {
      message($("hall-contact-etat"), erreur.message, "erreur");
    });
  });

  chargerEtat().then(function (donnees) {
    if (donnees && donnees.disponible && !donnees.pseudo) {
      ouvrirPseudo();                      /* première visite sans pseudo : on l'explique et on propose d'en créer un */
    } else if (donnees && donnees.tor && donnees.tor.requis && !donnees.tor.detecte && donnees.actif && !dejaOuverteTor) {
      dejaOuverteTor = true;
      ouvrirTor();                         /* nœud activé mais Tor absent : on explique quoi faire */
    }
  });
  chargerListe();
})();
