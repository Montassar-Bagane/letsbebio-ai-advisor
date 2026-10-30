/* Conseiller beauté — conversational interface.
 *
 * Two mounting modes, one implementation:
 *   inline   — the [conseiller_beaute] shortcode, inside a page
 *   floating — a launcher bubble present on every page of the shop
 *
 * The floating mode is the one a shop actually wants: advice should be
 * available while the customer is browsing products, not on a page they have
 * to navigate away to. That makes conversation persistence a requirement
 * rather than a nicety — the customer changes page constantly, and losing the
 * thread each time would make the adviser useless.
 *
 * Product cards are rendered ONLY from the `products` array the server
 * returns, which itself comes only from tool results. The model's prose can
 * never put a product on screen.
 */
(function () {
  "use strict";

  var C = window.RECO_CFG || {};
  var history = [];
  var busy = false;
  var el = {};
  // The key carries a version: after an update, an old thread would restore
// replies produced by the previous prompt and look like a bug.
var STORE = "reco_chat_thread_v2";

  var OPENERS = [
    { label: "🌿 Boutons & Acné", prompt: "J'ai des boutons et des imperfections" },
    { label: "💆‍♀️ Chute de cheveux", prompt: "Cha3ri ytee7 barcha, conseillez-moi pour la chute" },
    { label: "✨ Taches & Teint terne", prompt: "3andi bo9a3 fi wajhi w n7eb éclat" },
    { label: "💧 Peau sèche qui tiraille", prompt: "J'ai la peau sèche qui tiraille" },
    { label: "🌸 Soins anti-âge & rides", prompt: "Je cherche une routine anti-âge naturelle" }
  ];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m];
    });
  }
  function money(v) {
    var n = parseFloat(v);
    return isFinite(n) ? n.toFixed(3).replace(/\.?0+$/, "") + " DT" : "";
  }
  function cartUrl(id) {
    return C.shop ? C.shop + "?add-to-cart=" + encodeURIComponent(id) : null;
  }

  /* ---------- persistence -------------------------------------------------
     sessionStorage, not localStorage: the thread should survive navigation
     within a visit and disappear afterwards. Nothing is sent anywhere. */

  function save() {
    try {
      sessionStorage.setItem(STORE, JSON.stringify({
        history: history.slice(-12),
        html: el.thread ? el.thread.innerHTML : ""
      }));
    } catch (e) { /* private browsing, quota — not worth breaking the widget */ }
  }

  function restore() {
    try {
      var raw = sessionStorage.getItem(STORE);
      if (!raw) return false;
      var d = JSON.parse(raw);
      if (!d || !d.html) return false;
      history = d.history || [];
      el.thread.innerHTML = d.html;
      return true;
    } catch (e) { return false; }
  }

  /* ---------- markup ---------- */

  function productCard(p) {
    var buy = (p.in_stock !== false && cartUrl(p.id))
      ? '<a class="reco-buy" href="' + esc(cartUrl(p.id)) + '">Ajouter au panier</a>'
      : "";
    var title = p.url
      ? '<a href="' + esc(p.url) + '">' + esc(p.name) + "</a>"
      : esc(p.name);

    return '<div class="reco-card">' +
      (p.image_url ? '<img src="' + esc(p.image_url) + '" alt="" loading="lazy">' : "") +
      '<div class="reco-body">' +
        "<h4>" + title + "</h4>" +
        (p.brand ? '<div class="reco-brand">' + esc(p.brand) + "</div>" : "") +
        '<div class="reco-meta">' +
          (p.volume_size
            ? '<span class="reco-tag is-plain">' + esc(p.volume_size) + "</span>" : "") +
          (p.in_stock === false
            ? '<span class="reco-tag is-out">rupture</span>' : "") +
          '<span class="reco-price">' + money(p.price) + "</span>" +
        "</div>" + buy +
      "</div></div>";
  }

  function addBubble(role, text) {
    var d = document.createElement("div");
    d.className = "reco-bubble is-" + role;
    d.innerHTML = "<p>" + esc(text).replace(/\n+/g, "</p><p>") + "</p>";
    el.thread.appendChild(d);
    return d;
  }

  function addProducts(products) {
    if (!products || !products.length) return;
    var d = document.createElement("div");
    d.className = "reco-bubble-products";
    d.innerHTML = products.map(productCard).join("");

    // If 2 or more products, add "Ajouter toute la routine au panier"
    var inStock = products.filter(function (p) {
      return p.in_stock !== false && cartUrl(p.id);
    });

    if (inStock.length >= 2) {
      var total = inStock.reduce(function (sum, p) {
        return sum + (parseFloat(p.prix || p.price) || 0);
      }, 0);

      var bundle = document.createElement("div");
      bundle.className = "reco-bundle-cta";
      bundle.innerHTML =
        '<div class="reco-bundle-info">' +
          '<div class="reco-bundle-title"><strong>Routine complète</strong> (' + inStock.length + ' soins)</div>' +
          '<div class="reco-bundle-price">' + (total > 0 ? Math.round(total) + ' DT' : '') + '</div>' +
        '</div>' +
        '<button type="button" class="reco-buy-all">' +
          '🛒 Ajouter toute la routine au panier' +
        '</button>';

      var btn = bundle.querySelector(".reco-buy-all");
      btn.addEventListener("click", function () {
        btn.disabled = true;
        btn.textContent = "Ajout en cours…";

        var promises = inStock.map(function (p) {
          return fetch(cartUrl(p.id), { credentials: "same-origin" });
        });

        Promise.all(promises).then(function () {
          btn.textContent = "✓ Routine ajoutée ! Voir mon panier →";
          btn.classList.add("is-added");
          btn.disabled = false;
          btn.onclick = function () {
            window.location.href = (C.shop || "/") + "panier/";
          };
        }).catch(function () {
          window.location.href = cartUrl(inStock[0].id);
        });
      });

      d.appendChild(bundle);
    }

    el.thread.appendChild(d);
  }

  function addFollowupQuestions(questions) {
    if (!questions || !questions.length) return;
    var wrapper = document.createElement("div");
    wrapper.className = "reco-followup-card";

    var total = questions.length;
    var selected = {};

    // Header if multiple questions (Form / Stepper mode)
    if (total > 1) {
      var header = document.createElement("div");
      header.className = "reco-followup-header";
      header.innerHTML =
        '<span class="reco-followup-title">Préciser votre besoin</span>' +
        '<span class="reco-followup-counter"><span class="reco-count-val">0</span>/' + total + ' sélectionné</span>';
      wrapper.appendChild(header);
    }

    var groupsContainer = document.createElement("div");
    groupsContainer.className = "reco-followup-groups";

    var submitBtn = null;

    for (var i = 0; i < total; i++) {
      (function (qIndex, q) {
        var group = document.createElement("div");
        group.className = "reco-followup-group";

        var label = document.createElement("div");
        label.className = "reco-followup-label";
        if (total > 1) {
          label.innerHTML = '<span class="reco-step-badge">' + (qIndex + 1) + '</span> ' + esc(q.question);
        } else {
          label.textContent = q.question;
        }
        group.appendChild(label);

        var chips = document.createElement("div");
        chips.className = "reco-followup-options";

        for (var j = 0; j < q.options.length; j++) {
          (function (optText) {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "reco-followup-chip";
            btn.innerHTML =
              '<span class="reco-followup-radio"></span>' +
              '<span class="reco-followup-text">' + esc(optText) + '</span>';

            btn.addEventListener("click", function () {
              // Select in this group
              var siblings = chips.querySelectorAll(".reco-followup-chip");
              for (var k = 0; k < siblings.length; k++) {
                siblings[k].classList.remove("is-selected");
              }
              btn.classList.add("is-selected");
              selected[qIndex] = optText;

              // Single question: immediate auto-send
              if (total === 1) {
                var allChips = wrapper.querySelectorAll(".reco-followup-chip");
                for (var k = 0; k < allChips.length; k++) {
                  allChips[k].disabled = true;
                }
                wrapper.classList.add("is-answered");
                send(optText);
                return;
              }

              // Multiple questions: update progress counter & submit button
              var count = Object.keys(selected).length;
              var counterEl = wrapper.querySelector(".reco-count-val");
              if (counterEl) counterEl.textContent = count;

              if (submitBtn) {
                if (count === total) {
                  submitBtn.disabled = false;
                  submitBtn.classList.add("is-ready");
                  submitBtn.innerHTML = 'Valider mes réponses (' + total + '/' + total + ') &rarr;';
                } else {
                  submitBtn.disabled = true;
                  submitBtn.classList.remove("is-ready");
                  submitBtn.textContent = 'Valider (' + count + '/' + total + ')';
                }
              }
            });

            chips.appendChild(btn);
          })(q.options[j]);
        }

        group.appendChild(chips);
        groupsContainer.appendChild(group);
      })(i, questions[i]);
    }

    wrapper.appendChild(groupsContainer);

    if (total > 1) {
      var footer = document.createElement("div");
      footer.className = "reco-followup-footer";

      submitBtn = document.createElement("button");
      submitBtn.type = "button";
      submitBtn.className = "reco-followup-submit";
      submitBtn.disabled = true;
      submitBtn.textContent = "Valider (0/" + total + ")";

      submitBtn.addEventListener("click", function () {
        if (Object.keys(selected).length < total) return;
        var allChips = wrapper.querySelectorAll(".reco-followup-chip, .reco-followup-submit");
        for (var k = 0; k < allChips.length; k++) {
          allChips[k].disabled = true;
        }
        wrapper.classList.add("is-answered");

        var answers = [];
        for (var k = 0; k < total; k++) {
          if (selected[k]) {
            answers.push(selected[k]);
          }
        }
        send(answers.join(", "));
      });

      footer.appendChild(submitBtn);
      wrapper.appendChild(footer);
    }

    el.thread.appendChild(wrapper);
  }

  function scrollDown() { el.thread.scrollTop = el.thread.scrollHeight; }

  /* ---------- conversation ---------- */

  function send(text) {
    if (busy || !text.trim()) return;
    busy = true;
    el.input.value = "";
    el.send.disabled = true;
    var op = el.thread.querySelector(".reco-openers");
    if (op) op.remove();

    // Disable any active follow-up cards
    var activeCards = el.thread.querySelectorAll(".reco-followup-card:not(.is-answered)");
    for (var i = 0; i < activeCards.length; i++) {
      activeCards[i].classList.add("is-answered");
      var btns = activeCards[i].querySelectorAll("button");
      for (var j = 0; j < btns.length; j++) {
        btns[j].disabled = true;
      }
    }

    addBubble("user", text);

    var thinking = document.createElement("div");
    thinking.className = "reco-bubble is-assistant is-thinking";
    thinking.innerHTML = "<span></span><span></span><span></span>";
    el.thread.appendChild(thinking);
    scrollDown();

    fetch(C.root + "chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-WP-Nonce": C.nonce },
      body: JSON.stringify({ message: text, history: history })
    })
      .then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) throw new Error(j.message || "Erreur");
          return j;
        });
      })
      .then(function (d) {
        thinking.remove();
        addBubble("assistant", d.reply);
        addProducts(d.products);
        addFollowupQuestions(d.followup_questions);
        history = d.history || history;
        scrollDown();
        save();
      })
      .catch(function (e) {
        thinking.remove();
        addBubble("assistant",
          "Le conseiller est momentanément indisponible. Réessayez dans un instant.");
        if (window.console) console.error(e);
        scrollDown();
      })
      .then(function () {
        busy = false;
        el.send.disabled = false;
        el.input.focus();
      });
  }

  /* ---------- construction ---------- */

  function innerHTML() {
    return '' +
      '<div class="reco-thread" data-reco-thread>' +
        '<div class="reco-bubble is-assistant"><p>Bonjour. Dites-moi ce qui ' +
        "vous préoccupe — peau, cheveux, ou bien-être — et je vous conseille " +
        "quelques produits.</p>" +
        "<p><small>Français, عربي ou arabizi.</small></p></div>" +
        '<div class="reco-openers">' +
          OPENERS.map(function (o) {
            return '<button type="button" class="reco-chip" data-prompt="' + esc(o.prompt) + '">' +
                   esc(o.label) + "</button>";
          }).join("") +
        "</div>" +
      "</div>" +
      '<form class="reco-composer" data-reco-composer>' +
        '<label class="reco-sr" for="reco-msg">Votre message</label>' +
        '<input id="reco-msg" type="text" autocomplete="off" ' +
          'placeholder="Écrivez ici…">' +
        '<button type="submit" data-reco-send>Envoyer</button>' +
      "</form>";
  }

  function wire(root) {
    el.thread = root.querySelector("[data-reco-thread]");
    el.input = root.querySelector("#reco-msg");
    el.send = root.querySelector("[data-reco-send]");

    root.querySelector("[data-reco-composer]")
        .addEventListener("submit", function (e) {
          e.preventDefault();
          send(el.input.value);
        });

    el.thread.addEventListener("click", function (e) {
      var b = e.target.closest(".reco-openers button");
      if (b) send(b.getAttribute("data-prompt") || b.textContent);
    });
  }

  /* ---------- mount ---------- */

  document.addEventListener("DOMContentLoaded", function () {
    var inline = document.getElementById("reco-chat");
    var float = document.getElementById("reco-chat-float");

    if (inline) {
      inline.innerHTML = innerHTML();
      wire(inline);
      restore() && scrollDown();
      return;
    }

    if (!float) return;

    /* floating: a launcher that opens a panel */
    float.innerHTML =
      '<button type="button" class="reco-launcher" aria-expanded="false" ' +
        'aria-label="Ouvrir le conseiller beauté">' +
        '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">' +
          '<path fill="currentColor" d="M12 3C7 3 3 6.6 3 11c0 2.2 1 4.2 2.7 5.6' +
          'L5 21l4.3-2.2c.9.2 1.8.3 2.7.3 5 0 9-3.6 9-8s-4-8-9-8z"/></svg>' +
        '<span class="reco-launcher-label">Conseil</span>' +
      "</button>" +
      '<div class="reco-panel" hidden style="display:none">' +
        '<div class="reco-panel-head">' +
          "<div><strong>Conseiller beauté</strong>" +
          "<span>Réponse immédiate</span></div>" +
          '<div class="reco-panel-actions">' +
            '<button type="button" class="reco-panel-reset" ' +
              'title="Nouvelle conversation" ' +
              'aria-label="Nouvelle conversation">&#8634;</button>' +
            '<button type="button" class="reco-panel-close" ' +
              'aria-label="Fermer">&times;</button>' +
          "</div>" +
        "</div>" +
        '<div class="reco-panel-body">' + innerHTML() + "</div>" +
      "</div>";

    var launcher = float.querySelector(".reco-launcher");
    var panel = float.querySelector(".reco-panel");
    wire(float);

    // The launcher is hidden with an inline style rather than a class.
    // WordPress themes style `button` aggressively and late, and a stylesheet
    // rule kept losing the specificity contest; an inline style cannot be
    // overridden by one.
    function open() {
      panel.hidden = false;
      panel.style.display = "";
      launcher.style.display = "none";
      launcher.setAttribute("aria-expanded", "true");
      float.classList.add("is-open");
      document.body.classList.add("reco-chat-open");
      setTimeout(function () { el.input.focus(); scrollDown(); }, 60);
    }
    function close() {
      panel.hidden = true;
      panel.style.display = "none";
      launcher.style.display = "";
      launcher.setAttribute("aria-expanded", "false");
      float.classList.remove("is-open");
      document.body.classList.remove("reco-chat-open");
      launcher.focus();
    }

    launcher.addEventListener("click", function () {
      panel.hidden ? open() : close();
    });

    float.querySelector(".reco-panel-reset").addEventListener("click", function () {
      try { sessionStorage.removeItem(STORE); } catch (e) {}
      history = [];
      el.thread.innerHTML = "";
      float.querySelector(".reco-panel-body").innerHTML = innerHTML();
      wire(float);
      launcher.classList.remove("has-thread");
      el.input.focus();
    });
    float.querySelector(".reco-panel-close").addEventListener("click", close);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !panel.hidden) close();
    });

    // a restored thread means the customer was mid-conversation on the
    // previous page: bring it back rather than making them start again
    if (restore()) {
      launcher.classList.add("has-thread");
    }
  });
})();
