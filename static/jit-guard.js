// JIT guard: tells a ban from an outage once the firewall starts rejecting this app's traffic.
// Pings /healthz every second. A refusal (REJECT) fails at once and a DROP times out after 2 s; either way the
// portal is asked whether this source IP is banned. Banned -> go to the portal's ban page. Otherwise show a
// small "unreachable" strip and keep trying.
(function () {
  var portal = (document.currentScript.dataset.portal || "").replace(/\/$/, "");
  if (!portal) return;
  var PING_MS = 1000, TIMEOUT_MS = 2000, strip = null, leaving = false;

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
            if (d && d.banned) { leaving = true; location.href = portal + "/userportal"; }
            else showStrip(true);
          })
          .catch(function () { showStrip(true); });   // portal unreachable too: just an outage
      });
  }

  setInterval(check, PING_MS);
})();
