/* Voice Agent admin panel — vanilla JS, no CDN, no framework.
 * Talks to the same admin API as curl: GET /, GET/POST /api/leads, POST /api/mode.
 */
(function () {
  "use strict";

  var KEY_STORAGE = "voiceAgentAdminKey";
  var $ = function (sel) { return document.querySelector(sel); };

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function getKey() { return localStorage.getItem(KEY_STORAGE) || ""; }

  function api(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    var k = getKey();
    if (k) opts.headers["X-API-Key"] = k;
    return fetch(path, opts).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          var err = new Error(b.detail || b.error || ("HTTP " + r.status));
          err.status = r.status;
          throw err;
        });
      }
      return r.json();
    });
  }

  var toastTimer = null;
  function toast(msg, ok) {
    var t = $("#toast");
    t.textContent = msg;
    t.className = "toast show " + (ok ? "ok" : "err");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.className = "toast"; }, 3500);
  }

  /* ─── Status ─── */
  function badge(el, text, cls) {
    el.className = "badge " + cls;
    el.innerHTML = '<span class="dot"></span>' + esc(text);
  }

  function loadStatus() {
    return fetch("/").then(function (r) { return r.json(); }).then(function (s) {
      badge($("#server-badge"), "online", "badge-ok");
      $("#stat-server").textContent = "running";
      $("#stat-mode").textContent = s.mode || "—";
      $("#stat-bt").textContent = s.bluetooth ? "connected" : "not connected";
      $("#stat-adb").textContent = s.adb ? "connected" : "not connected";
      highlightMode(s.mode);
    }).catch(function () {
      badge($("#server-badge"), "offline", "badge-bad");
      $("#stat-server").textContent = "offline";
    });
  }

  function highlightMode(mode) {
    $("#btn-sales").className = "btn" + (mode === "sales" ? " active" : "");
    $("#btn-interview").className = "btn" + (mode === "interview" ? " active" : "");
  }

  /* ─── Mode switch ─── */
  function setMode(mode) {
    api("/api/mode?mode=" + encodeURIComponent(mode), { method: "POST" })
      .then(function (r) { toast("Mode set to " + r.mode, true); loadStatus(); })
      .catch(function (e) {
        toast(e.status === 401 ? "Invalid API key" :
              e.status === 501 ? "ADMIN_API_KEY not configured on server" :
              "Mode switch failed: " + e.message, false);
      });
  }

  /* ─── Leads ─── */
  function skeleton() {
    return '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
  }

  function emptyState() {
    return '<div class="empty">' +
      '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>' +
      "<p>No leads captured yet. Leads appear here after calls or <span class=\"mono\">POST /api/leads</span>.</p>" +
      '<button class="btn" onclick="void 0" id="empty-refresh">Refresh</button></div>';
  }

  function errorState(msg) {
    return '<div class="error-box">' +
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>' +
      "<span>" + esc(msg) + "</span>" +
      '<button class="btn" id="retry-leads" style="margin-left:auto">Try again</button></div>';
  }

  function renderLeads(leads) {
    $("#lead-count").textContent = leads.length ? "(" + leads.length + ")" : "";
    if (!leads.length) {
      $("#leads-body").innerHTML = emptyState();
      var er = $("#empty-refresh");
      if (er) er.addEventListener("click", loadLeads);
      return;
    }
    var rows = leads.map(function (l) {
      return "<tr><td>" + esc(l.name) + "</td><td class=\"mono\">" + esc(l.phone) +
        "</td><td>" + esc(l.company || "—") + "</td><td>" + esc(l.interest || "—") +
        "</td><td class=\"muted\">" + esc(l.created || "") + "</td></tr>";
    }).join("");
    $("#leads-body").innerHTML =
      "<table><thead><tr><th>Name</th><th>Phone</th><th>Company</th><th>Interest</th><th>Created</th></tr></thead><tbody>" +
      rows + "</tbody></table>";
  }

  function loadLeads() {
    $("#leads-body").innerHTML = skeleton();
    $("#lead-count").textContent = "";
    api("/api/leads").then(function (d) {
      renderLeads(d.leads || []);
    }).catch(function (e) {
      var msg = e.status === 401 ? "Invalid or missing API key — set it above."
        : e.status === 501 ? "ADMIN_API_KEY is not configured on the server."
        : "Could not load leads: " + e.message;
      $("#leads-body").innerHTML = errorState(msg);
      var btn = $("#retry-leads");
      if (btn) btn.addEventListener("click", loadLeads);
    });
  }

  /* ─── Wire up ─── */
  $("#api-key").value = getKey();
  $("#save-key").addEventListener("click", function () {
    var v = $("#api-key").value.trim();
    if (v) localStorage.setItem(KEY_STORAGE, v);
    else localStorage.removeItem(KEY_STORAGE);
    toast("API key saved", true);
    loadLeads();
  });
  $("#btn-sales").addEventListener("click", function () { setMode("sales"); });
  $("#btn-interview").addEventListener("click", function () { setMode("interview"); });
  $("#refresh-leads").addEventListener("click", loadLeads);
  $("#refresh-all").addEventListener("click", function () { loadStatus(); loadLeads(); });

  loadStatus();
  loadLeads();
  setInterval(loadStatus, 15000);
})();
