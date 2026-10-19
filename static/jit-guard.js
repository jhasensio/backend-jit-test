// JIT guard: tells a ban from an outage once the firewall starts rejecting this app's traffic.
// Pings /healthz every second. A refusal (REJECT) fails at once and a DROP times out after 2 s; either way the
// portal is asked whether this source IP is banned. Banned -> block the page with an overlay, then go to the portal's ban page. Otherwise show a
// small "unreachable" strip and keep trying.
(function () {
  var portal = (document.currentScript.dataset.portal || "").replace(/\/$/, "");
  if (!portal) return;
  var PING_MS = 1000, TIMEOUT_MS = 2000, LEAVE_MS = 10000, strip = null, leaving = false, overlay = null;

  // Full-screen block shown on the page the user was on, so the ban is seen where it happened.
  function showBan() {
    if (overlay) return;
    showStrip(false);
    overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;z-index:100000;background:rgba(15,15,20,.92);color:#fff;" +
      "display:flex;align-items:center;justify-content:center;text-align:center;font-family:system-ui,sans-serif";
    var box = document.createElement("div");
    box.style.cssText = "max-width:460px;padding:32px";
    var h = document.createElement("h1");
    h.textContent = "\u26D4 Access suspended";
    h.style.cssText = "font-size:28px;margin-bottom:12px;color:#ff6b6b";
    var p = document.createElement("p");
    p.textContent = "The firewall has blocked your access to this application. Nothing on this site is reachable until the ban is lifted.";
    p.style.cssText = "font-size:15px;line-height:1.5;margin-bottom:20px";
    var n = document.createElement("p");
    n.style.cssText = "font-size:13px;opacity:.7;margin-bottom:20px";
    var b = document.createElement("a");
    b.textContent = "Go to the access portal";
    b.href = portal + "/userportal";
    b.style.cssText = "display:inline-block;background:#dc3545;color:#fff;padding:10px 20px;border-radius:4px;" +
      "text-decoration:none;font-size:14px";
    box.appendChild(h); box.appendChild(p); box.appendChild(n); box.appendChild(b);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    var left = LEAVE_MS / 1000;
    (function tick() {
      n.textContent = "Redirecting to the portal in " + left + " s";
      if (left-- <= 0) { location.href = portal + "/userportal"; return; }
      setTimeout(tick, 1000);
    })();
  }

  function withTimeout(url, opts) {
    var ctl = new AbortController();
    var t = setTimeout(function () { ctl.abort(); }, TIMEOUT_MS);
    opts.signal = ctl.signal;
    return fetch(url, opts).finally(function () { clearTimeout(t); });
  }

  function showStrip(on) {
    if (on && !strip) {
      strip = document.createElement("div");
      strip.textContent = "Connection to this application was lost. Retrying…";
      strip.style.cssText = "position:fixed;left:0;right:0;top:0;z-index:99999;padding:8px 12px;" +
        "background:#b45309;color:#fff;font:14px system-ui,sans-serif;text-align:center";
      document.body.appendChild(strip);
    } else if (!on && strip) {
      strip.remove();
      strip = null;
    }
  }

  function check() {
    if (leaving) return;
    withTimeout("/healthz", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("bad"); showStrip(false); })
      .catch(function () {
        return withTimeout(portal + "/api/blocked", { cache: "no-store", mode: "cors" })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (d && d.banned) { leaving = true; showBan(); }
            else showStrip(true);
          })
          .catch(function () { showStrip(true); });   // portal unreachable too: just an outage
      });
  }

  // After a ban every link and form on the page is dead; the overlay already covers them.
  window.jitGuardCheck = check;           // lets a failed fetch on the page ask right away
  check();                                // do not wait a second for the first answer
  setInterval(check, PING_MS);
  // A page restored from the back/forward cache is stale: re-check at once.
  window.addEventListener("pageshow", function (e) { if (e.persisted) check(); });
})();
