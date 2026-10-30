/* Moteur de recommandation — widget storefront
   Talks to WordPress (/wp-json/reco/v1/), never to the API directly. */
(function () {
  "use strict";

  var C = window.RECO_CFG || {};
  var root = C.root;

  var L_CONCERN = {
    taches_pigmentaires: "Taches & hyperpigmentation", rides_age: "Rides & fermeté",
    deshydratation: "Hydratation & nutrition", imperfections_acne: "Imperfections & acné",
    rougeurs_sensibilite: "Rougeurs & sensibilité", exces_sebum: "Excès de sébum",
    eclat_teint: "Éclat du teint", protection_solaire: "Protection solaire",
    cernes_poches: "Cernes & poches", pores_dilates: "Pores dilatés",
    chute_cheveux: "Chute de cheveux", pellicules: "Pellicules",
    cheveux_abimes: "Cheveux abîmés", minceur_detox: "Minceur & détox",
    digestion: "Digestion & transit", immunite: "Immunité",
    sommeil_stress: "Sommeil & stress", energie_tonus: "Énergie & tonus",
    articulations: "Articulations", memoire_concentration: "Mémoire & concentration",
    glycemie_tension: "Glycémie & tension", fertilite: "Fertilité & libido",
    sport_nutrition: "Sport & nutrition", cheveux_peau_ongles: "Cheveux, peau & ongles",
    hygiene: "Hygiène"
  };
  var L_SKIN = { normale: "Normale", seche: "Sèche", mixte: "Mixte", grasse: "Grasse",
    sensible: "Sensible", acneique: "À tendance acnéique", mature: "Mature" };
  var L_HAIR = { secs: "Secs", gras: "Gras", normaux: "Normaux", abimes: "Abîmés",
    colores: "Colorés", boucles_frises: "Bouclés / frisés", pellicules: "Pellicules",
    chute: "Chute" };
  var L_STEP = { nettoyage: "Nettoyer", tonification: "Tonifier", traitement: "Traiter",
    hydratation: "Hydrater", protection: "Protéger", soin_cible: "Soin ciblé",
    complement_oral: "Complément" };
  var DOMAINS = { visage: "Visage", cheveux: "Cheveux", corps: "Corps",
    interieur: "Bien-être" };

  var S = { domain: "visage", concern: null, type: null, budget: null };
  var OPTS = null, app = null, busy = false;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m];
    });
  }
  function num(v) { var n = parseFloat(v); return isFinite(n) ? n : null; }

  function money(v) {
    var n = num(v);
    return n === null ? "" : n.toFixed(3).replace(/\.?0+$/, "") + " DT";
  }

  /* WooCommerce adds to the basket with a plain link, so no JavaScript
     cart handling is needed and it keeps working if scripts fail. */
  function cartUrl(id) {
    return C.shop ? C.shop + "?add-to-cart=" + encodeURIComponent(id) : null;
  }

  function api(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers["X-WP-Nonce"] = C.nonce;
    if (opts.body) opts.headers["Content-Type"] = "application/json";
    return fetch(root + path, opts).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.message || "Erreur");
        return j;
      });
    });
  }

  /* ---------- rendering ---------- */

  function chips(items, active, onPick, labels) {
    return items.map(function (o) {
      var v = o.value !== undefined ? o.value : o;
      var label = labels ? (labels[v] || v) : v;
      return '<button type="button" class="reco-chip' +
        (v === active ? " is-on" : "") + '" data-v="' + esc(v) + '">' +
        esc(label) + "</button>";
    }).join("");
  }

  function card(item, withBuy) {
    var p = item.product || item;
    var tags = [];

    /* the skin type is badged in rose only when it matched what the shopper
       told us — so the badge always answers "why am I seeing this" */
    var matched = item.match && item.match.skin_type === "explicit";
    (p.skin_type || []).slice(0, 2).forEach(function (t) {
      tags.push('<span class="reco-tag' + (matched && t === S.type ? " is-match" : "") +
        '">' + esc(L_SKIN[t] || t) + "</span>");
    });
    (p.hair_type || []).slice(0, 2).forEach(function (t) {
      tags.push('<span class="reco-tag' + (matched && t === S.type ? " is-match" : "") +
        '">' + esc(L_HAIR[t] || t) + "</span>");
    });
    if (p.volume_size) {
      tags.push('<span class="reco-tag is-plain">' + esc(p.volume_size) + "</span>");
    }
    if (p.in_stock === false) {
      tags.push('<span class="reco-tag is-out">rupture</span>');
    }

    var title = p.url
      ? '<a href="' + esc(p.url) + '">' + esc(p.name) + "</a>"
      : esc(p.name);

    var buy = "";
    if (withBuy && p.in_stock !== false && cartUrl(p.id)) {
      buy = '<a class="reco-buy" href="' + esc(cartUrl(p.id)) + '">Ajouter au panier</a>';
    }

    return '<div class="reco-card">' +
      (p.image_url ? '<img src="' + esc(p.image_url) + '" alt="" loading="lazy">' : "") +
      '<div class="reco-body">' +
        "<h4>" + title + "</h4>" +
        (p.brand ? '<div class="reco-brand">' + esc(p.brand) + "</div>" : "") +
        '<div class="reco-meta">' + tags.join("") +
          '<span class="reco-price">' + money(p.price) + "</span></div>" +
        (item.reason ? '<p class="reco-why">' + esc(item.reason) + " " +
          esc((L_CONCERN[S.concern] || "").toLowerCase()) + "</p>" : "") +
        buy +
      "</div></div>";
  }

  function renderForm() {
    var kind = OPTS.type_kind;
    var labels = kind === "hair" ? L_HAIR : L_SKIN;
    var typeItems = [{ value: null }].concat(OPTS.types);

    var html =
      '<div class="reco-ask">' +
        (C.freeText ?
          '<div class="reco-field reco-free">' +
            '<span class="reco-label">Décrivez votre besoin en une phrase</span>' +
            '<div class="reco-free-row">' +
              '<input id="reco-free" type="text" ' +
                'placeholder="ex : des taches et la peau sensible / 3andi bo9a3, budget 100 DT">' +
              '<button type="button" id="reco-free-go">Analyser</button>' +
            "</div>" +
            '<p class="reco-free-msg" id="reco-free-msg"></p>' +
          "</div>" : "") +

        '<div class="reco-field"><span class="reco-label">Ce que vous cherchez</span>' +
          '<div class="reco-chips" data-group="domain">' +
            chips(Object.keys(DOMAINS).map(function (k) { return { value: k }; }),
                  S.domain, null, DOMAINS) +
          "</div></div>" +

        '<div class="reco-field"><span class="reco-label">Votre préoccupation</span>' +
          '<div class="reco-chips" data-group="concern">' +
            chips(OPTS.concerns, S.concern, null, L_CONCERN) +
          "</div></div>" +

        (kind ?
          '<div class="reco-field"><span class="reco-label">' +
            (kind === "hair" ? "Type de cheveux" : "Type de peau") + "</span>" +
            '<div class="reco-chips" data-group="type">' +
              '<button type="button" class="reco-chip' +
                (S.type === null ? " is-on" : "") + '" data-v="">Indifférent</button>' +
              chips(OPTS.types, S.type, null, labels) +
            "</div></div>" : "") +
      "</div>" +
      '<div class="reco-results" id="reco-results"></div>';

    app.innerHTML = html;
    bind();
  }

  function bind() {
    app.querySelectorAll(".reco-chips").forEach(function (group) {
      group.addEventListener("click", function (e) {
        var b = e.target.closest(".reco-chip");
        if (!b) return;
        var g = group.getAttribute("data-group");
        var v = b.getAttribute("data-v") || null;

        if (g === "domain") {
          if (v === S.domain) return;
          S.domain = v; S.concern = null; S.type = null;
          loadOptions();
          return;
        }
        if (g === "concern") S.concern = v;
        if (g === "type") S.type = v;

        group.querySelectorAll(".reco-chip").forEach(function (x) {
          x.classList.toggle("is-on", x === b);
        });
        run();
      });
    });

    var go = document.getElementById("reco-free-go");
    if (go) {
      var input = document.getElementById("reco-free");
      var msg = document.getElementById("reco-free-msg");
      var submit = function () {
        var text = input.value.trim();
        if (text.length < 3) return;
        go.disabled = true;
        msg.className = "reco-free-msg";
        msg.textContent = "Lecture de votre demande…";
        api("interpret", { method: "POST", body: JSON.stringify({ text: text }) })
          .then(function (p) {
            go.disabled = false;
            if (!p.understood) {
              msg.textContent =
                "Précisez votre besoin, ou choisissez directement ci-dessous.";
              return;
            }
            S.domain = p.domain;
            S.concern = p.concerns[0];
            S.type = p.skin_type || null;
            S.budget = p.budget_max || null;
            msg.className = "reco-free-msg is-set";
            msg.textContent = "Compris : " + (L_CONCERN[S.concern] || S.concern) +
              (S.type ? " · peau " + (L_SKIN[S.type] || S.type).toLowerCase() : "") +
              (S.budget ? " · budget " + S.budget + " DT" : "") +
              ". Ajustez si besoin.";
            loadOptions(true);
          })
          .catch(function () {
            go.disabled = false;
            msg.textContent = "Lecture indisponible — choisissez directement ci-dessous.";
          });
      };
      go.addEventListener("click", submit);
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); submit(); }
      });
    }
  }

  function run() {
    if (busy || !S.concern) return;
    busy = true;
    var out = document.getElementById("reco-results");
    out.innerHTML = '<div class="reco-skel"></div>' +
                    '<div class="reco-skel"></div>' +
                    '<div class="reco-skel"></div>';

    api("recommend", {
      method: "POST",
      body: JSON.stringify({
        domain: S.domain, concerns: [S.concern], skin_type: S.type,
        budget_max: S.budget, in_stock_only: true, limit_alternatives: 8
      })
    }).then(function (d) {
      var h = "";

      if (d.routine.length) {
        var total = 0, priced = 0;
        d.routine.forEach(function (r) {
          var v = num(r.product.price);
          if (v !== null) { total += v; priced++; }
        });

        h += '<section class="reco-sect"><h3>Votre routine</h3>' +
             '<p class="reco-sect-note">Les produits s\'appliquent dans cet ordre.</p>' +
             '<ol class="reco-ribbon">';
        d.routine.forEach(function (r) {
          h += '<li class="reco-step"><span class="reco-label">' +
               esc(L_STEP[r.step] || r.step) + "</span>" + card(r, true) + "</li>";
        });
        h += "</ol>";

        /* the récapitulatif: what a shop assistant says last —
           how many products, and what it comes to */
        if (priced) {
          h += '<div class="reco-total"><div class="reco-total-lines">' +
               '<div class="reco-total-row"><span>Produits</span><span>' +
                 d.routine.length + "</span></div>" +
               (priced < d.routine.length
                 ? '<div class="reco-total-row"><span>Prix disponibles</span><span>' +
                   priced + " / " + d.routine.length + "</span></div>" : "") +
               '<div class="reco-total-row is-sum"><span>Total</span><span>' +
                 money(total) + "</span></div></div>";
          if (d.packs && d.packs.length && d.packs[0].id && cartUrl(d.packs[0].id)) {
            h += '<a class="reco-total-cta" href="' + esc(cartUrl(d.packs[0].id)) +
                 '">Prendre le pack conseillé</a>';
          }
          h += "</div>";
        }
        h += "</section>";
      } else {
        h += '<div class="reco-empty"><strong>Aucun produit pour ce profil ' +
             "pour le moment.</strong><br>Choisissez un autre type de peau, " +
             "ou revenez à « Indifférent » pour voir plus de résultats.</div>";
      }

      if (d.packs && d.packs.length) {
        h += '<section class="reco-sect"><h3>Nos packs</h3>' +
             '<p class="reco-sect-note">Déjà composés pour cette préoccupation.</p>' +
             '<div class="reco-grid">';
        d.packs.forEach(function (p) {
          var items = (p.components || []).map(function (c) {
            return "<li>" + esc(c.name) + "</li>";
          }).join("");
          var packBuy = cartUrl(p.id)
            ? '<a class="reco-buy" href="' + esc(cartUrl(p.id)) + '">Ajouter au panier</a>'
            : "";
          h += '<div class="reco-card reco-pack"><div class="reco-body">' +
               "<h4>" + (p.url ? '<a href="' + esc(p.url) + '">' + esc(p.name) + "</a>"
                               : esc(p.name)) + "</h4>" +
               '<div class="reco-meta"><span class="reco-price">' +
                 money(p.price) + "</span></div>" +
               (items ? "<ul>" + items + "</ul>" : "") +
               packBuy +
               "</div></div>";
        });
        h += "</div></section>";
      }

      if (d.alternatives && d.alternatives.length) {
        h += '<section class="reco-sect"><h3>Autres produits adaptés</h3>' +
             '<p class="reco-sect-note">Classés par pertinence pour votre profil.</p>' +
             '<div class="reco-grid">' +
             d.alternatives.map(function (a) { return card(a, true); }).join("") +
             "</div></section>";
      }

      out.innerHTML = h;
    }).catch(function (e) {
      out.innerHTML = '<div class="reco-empty">' + esc(e.message) + "</div>";
    }).then(function () { busy = false; });
  }

  function loadOptions(keepChoice) {
    return api("options?domain=" + encodeURIComponent(S.domain))
      .then(function (o) {
        OPTS = o;
        var valid = o.concerns.some(function (c) { return c.value === S.concern; });
        if (!keepChoice || !valid) {
          S.concern = o.concerns.length ? o.concerns[0].value : null;
        }
        if (S.type && !o.types.some(function (t) { return t.value === S.type; })) {
          S.type = null;
        }
        renderForm();
        run();
      })
      .catch(function (e) {
        app.innerHTML = '<div class="reco-empty"><strong>Le conseil ' +
          'personnalisé est momentanément indisponible.</strong><br>' +
          "Réessayez dans un instant.</div>";
        if (window.console) console.error(e);
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    app = document.getElementById("reco-app");
    if (app) loadOptions();
  });
})();
