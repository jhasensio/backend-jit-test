// Inline SQL injection result for the Attack tab: runs the payload through /api/search and shows the raw SQL,
// the verdict and the rows in the card, so the page the audience is watching stays put. Without JS the buttons
// still follow their href to /search.
(function () {
  var COLORS = { success: "#dc3545", error: "#b45309", none: "#6b7280", blocked: "#111827" };

  function el(tag, text, css) {
    var e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (css) e.style.cssText = css;
    return e;
  }

  function box(btn) {
    var card = btn.closest(".lab-card");
    var b = card.querySelector(".sqli-result");
    if (!b) {
      b = el("div", null, "margin-top:14px;font-size:13px");
      b.className = "sqli-result";
      var exp = card.querySelector(".expected");
      card.insertBefore(b, exp);
    }
    b.textContent = "";
    return b;
  }

  function show(b, level, text) {
    b.appendChild(el("div", text, "padding:10px 14px;border-radius:6px;color:#fff;font-weight:600;background:" + COLORS[level]));
  }

  function run(btn, payload) {
    var b = box(btn);
    b.appendChild(el("div", "Running…", "color:#6b7280"));
    fetch("/api/search?q=" + encodeURIComponent(payload), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then(function (d) {
        b.textContent = "";
        show(b, d.verdict.level, d.verdict.text);
        b.appendChild(el("code", d.sql, "display:block;margin-top:8px;white-space:pre-wrap;word-break:break-all"));
        if (d.rows.length) {
          var t = el("table", null, "width:100%;margin-top:8px;border-collapse:collapse;font-size:12px");
          d.rows.forEach(function (r) {
            var tr = document.createElement("tr");
            ["id", "name", "department", "role", "salary"].forEach(function (k) {
              tr.appendChild(el("td", r[k], "padding:3px 8px;border-bottom:1px solid #ddd"));
            });
            t.appendChild(tr);
          });
          b.appendChild(t);
        }
      })
      .catch(function () {
        b.textContent = "";
        show(b, "blocked", "Request blocked before it reached the server (firewall ban or outage).");
        if (window.jitGuardCheck) window.jitGuardCheck();   // do not wait for the next heartbeat
      });
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-sqli]");
    if (!btn) return;
    e.preventDefault();
    run(btn, btn.getAttribute("data-sqli"));
  });
})();
