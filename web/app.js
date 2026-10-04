/**
 * Workstreams web console - wired to the dashboard.py HTTP API.
 *
 * Endpoints (served by `workstreams web`):
 *   GET  /api/config   - .workstreams.yaml as JSON
 *   GET  /api/status   - summary + workstream statuses + recent events
 *   GET  /api/events   - recent subagent events
 *   POST /api/dispatch - dispatch a subagent (same core as the CLI)
 */
(function () {
  "use strict";

  var POLL_MS = 2000;

  var state = {
    config: null,
    status: null,
    screen: null,
    lastFetch: null,
    started: false
  };

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function $(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    var el = $(id);
    if (el) el.textContent = value;
  }

  function api(path, opts) {
    return fetch(path, opts).then(function (res) {
      return res.json().catch(function () {
        return null;
      }).then(function (data) {
        if (!res.ok) {
          var msg = (data && (data.message || data.error)) || res.statusText;
          var err = new Error(res.status + " " + msg);
          err.code = data && data.code;
          throw err;
        }
        return data;
      });
    });
  }

  // -- data refresh ----------------------------------------------------------

  function refresh() {
    return Promise.all([api("/api/config"), api("/api/status")])
      .then(function (results) {
        state.config = results[0];
        state.status = results[1];
        state.lastFetch = Date.now();
        renderHeader();
        renderScreen();
      })
      .catch(function (err) {
        setText("header-updated", "API error: " + err.message);
      });
  }

  function renderHeader() {
    if (state.config) setText("header-project", state.config.project);
    tickUpdated();
  }

  function tickUpdated() {
    if (!state.lastFetch) return;
    var secs = Math.round((Date.now() - state.lastFetch) / 1000);
    setText("header-updated", secs <= 1 ? "Updated just now" : "Updated " + secs + "s ago");
  }

  // -- shared bits -----------------------------------------------------------

  function gitBadge(git) {
    var cls =
      git === "clean"
        ? "bg-emerald-500/15 text-emerald-500"
        : git === "dirty"
          ? "bg-amber-500/15 text-amber-500"
          : "bg-surface-container/50 text-on-surface-container/50";
    var label = !git || git === "unknown" ? "UNKNOWN" : git.toUpperCase();
    return '<span class="px-2 py-0.5 rounded text-xs font-mono ' + cls + '">' + esc(label) + "</span>";
  }

  function timeOf(ts) {
    return ts ? String(ts).slice(11, 19) : "";
  }

  // -- screen renderers ------------------------------------------------------

  function renderScreen() {
    if (!state.screen) return;
    if (state.screen === "monitor") renderMonitor();
    else if (state.screen === "events") renderEvents();
    else if (state.screen === "workstreams") renderWorkstreams();
    else if (state.screen === "settings") renderSettings();
  }

  function renderMonitor() {
    var s = state.status;
    if (!s) return;
    var sum = s.summary;
    setText("total-workstreams", sum.total);
    setText("active-workstreams", sum.active);
    setText("clean-workstreams", sum.clean);
    setText("dirty-workstreams", sum.dirty);
    setText("alerts", sum.alerts);

    var tbody = $("monitor-tbody");
    if (tbody) {
      if (!s.statuses.length) {
        tbody.innerHTML =
          '<tr><td colspan="6" class="p-2 text-on-surface/60">No workstreams configured - run <code>workstreams init</code>.</td></tr>';
      } else {
        tbody.innerHTML = s.statuses
          .map(function (st) {
            var worker = (st.pane || "—") + (st.pid ? " / " + st.pid : "");
            var activity = st.last_commit || st.last_activity || "—";
            return (
              '<tr class="border-b border-border hover:bg-surface-container/50">' +
              '<td class="p-2 font-mono text-primary">#' + String(st.id).padStart(2, "0") + "</td>" +
              '<td class="p-2">' + esc(st.name) +
              '<div class="text-xs text-on-surface/50 font-mono">' + esc(st.path) + "</div></td>" +
              '<td class="p-2 font-mono">' + esc(st.branch) + "</td>" +
              '<td class="p-2 font-mono">' + esc(worker) + "</td>" +
              '<td class="p-2">' + gitBadge(st.git_status) + "</td>" +
              '<td class="p-2 text-on-surface/60">' + esc(activity) + "</td>" +
              "</tr>"
            );
          })
          .join("");
      }
    }

    var rail = $("activity-rail");
    if (rail) {
      var events = s.events || [];
      if (!events.length) {
        rail.innerHTML = '<p class="text-on-surface/60 text-xs">No subagent activity in the last 10 minutes.</p>';
      } else {
        rail.innerHTML = events
          .slice(-8)
          .reverse()
          .map(function (ev) {
            var dot =
              ev.event_type === "failed" || ev.event_type === "error"
                ? "bg-rose-500"
                : ev.event_type === "completed" || ev.event_type === "done"
                  ? "bg-emerald-500"
                  : ev.event_type === "progress"
                    ? "bg-yellow-500 animate-pulse"
                    : "bg-cyan-500 animate-pulse";
            return (
              '<div class="flex items-start gap-2">' +
              '<span class="w-2 h-2 mt-1 rounded-full ' + dot + '"></span><div>' +
              '<div class="font-mono text-on-surface/60 text-xs">' + esc(timeOf(ev.timestamp)) + "</div>" +
              '<p class="text-primary line-clamp-1">' + esc(ev.subagent) + " [" + esc(ev.event_type) + "] " +
              esc(ev.message) + "</p></div></div>"
            );
          })
          .join("");
      }
    }

    var pty = $("pty-log");
    if (pty) {
      var tails = [];
      s.statuses.forEach(function (st) {
        (st.log_tail || []).forEach(function (line) {
          tails.push(line);
        });
      });
      pty.innerHTML = tails.length
        ? tails.slice(-12).map(function (l) { return '<div class="text-primary">' + esc(l) + "</div>"; }).join("")
        : '<div class="text-on-surface/60">No log output yet.</div>';
    }

    var wlog = $("worker-log");
    if (wlog) {
      var alerts = [];
      s.statuses.forEach(function (st) {
        (st.alerts || []).forEach(function (a) {
          alerts.push(st.name + ": " + a);
        });
      });
      wlog.innerHTML = alerts.length
        ? alerts.slice(-10).map(function (a) { return '<div class="text-rose-500">' + esc(a) + "</div>"; }).join("")
        : '<div class="text-on-surface/60">No alerts.</div>';
    }
  }

  function renderEvents() {
    var s = state.status;
    if (!s) return;
    var events = (s.events || []).slice().reverse();

    setText("ev-total", String(events.length));
    var channels = {};
    events.forEach(function (e) {
      channels[e.subagent] = 1;
    });
    setText("ev-channels", String(Object.keys(channels).length));
    var fails = events.filter(function (e) {
      return e.event_type === "failed" || e.event_type === "error";
    }).length;
    setText("ev-fails", String(fails));

    var list = $("events-list");
    if (!list) return;
    if (!events.length) {
      list.innerHTML =
        '<p class="text-on-surface/60 text-xs">No events in the last 10 minutes. Dispatch a subagent to see activity here.</p>';
      return;
    }
    var cls = {
      started: "bg-cyan-500/15 text-cyan-500",
      progress: "bg-yellow-500/15 text-yellow-500",
      completed: "bg-emerald-500/15 text-emerald-500",
      done: "bg-emerald-500/15 text-emerald-500",
      failed: "bg-rose-500/15 text-rose-500",
      error: "bg-rose-500/15 text-rose-500"
    };
    list.innerHTML = events
      .map(function (ev) {
        var kind = cls[ev.event_type] || "bg-surface-container/50 text-on-surface";
        return (
          '<div class="flex items-start gap-3 border-b border-border py-2">' +
          '<span class="px-2 py-0.5 rounded text-xs font-mono ' + kind + '">' + esc(String(ev.event_type).toUpperCase()) + "</span>" +
          '<div class="flex-1">' +
          '<div class="text-xs font-mono text-primary">' + esc(ev.subagent) + (ev.issue ? " · #" + ev.issue : "") + "</div>" +
          '<div class="text-sm">' + esc(ev.message) + "</div></div>" +
          '<span class="font-mono text-xs text-on-surface/50">' + esc(timeOf(ev.timestamp)) + "</span>" +
          "</div>"
        );
      })
      .join("");
  }

  function renderWorkstreams() {
    var cfg = state.config;
    var s = state.status;
    if (!cfg || !s) return;

    var byId = {};
    s.statuses.forEach(function (st) {
      byId[st.id] = st;
    });
    setText("ws-running", s.summary.active + " running");

    var grid = $("workstreams-grid");
    if (grid) {
      if (!cfg.workstreams.length) {
        grid.innerHTML =
          '<p class="text-on-surface/60 text-sm">No workstreams configured - run <code>workstreams init</code>.</p>';
      } else {
        grid.innerHTML = cfg.workstreams
          .map(function (ws) {
            var st = byId[ws.id] || {};
            var active = st.pid != null;
            var badge = active
              ? '<span class="text-xs font-medium bg-emerald-500/10 text-emerald-500 rounded px-2 py-0.5">RUNNING</span>'
              : '<span class="text-xs font-medium bg-surface-container/50 text-on-surface-container/50 rounded px-2 py-0.5">IDLE</span>';
            var alertCount = (st.alerts || []).length;
            return (
              '<div class="rounded border border-border p-3">' +
              '<div class="flex items-center justify-between mb-2"><div>' +
              '<h3 class="font-medium">' + esc(ws.name) + "</h3>" +
              '<p class="text-xs text-on-surface/60 font-mono">' + esc(ws.branch) + "</p></div>" + badge + "</div>" +
              '<p class="text-xs text-on-surface/60 mb-2 font-mono">' + esc(ws.path) + "</p>" +
              '<div class="flex items-center gap-2 text-xs mb-2">' + gitBadge(st.git_status) +
              '<span class="text-on-surface/60">pane ' + esc(st.pane || "—") + "</span></div>" +
              '<p class="text-xs text-on-surface/60">' + esc(st.last_commit || st.last_activity || "no activity") + "</p>" +
              (alertCount ? '<p class="text-xs text-rose-500 mt-1">' + alertCount + " alert(s)</p>" : "") +
              "</div>"
            );
          })
          .join("");
      }
    }

    var sel = $("dispatch-ws");
    if (sel && sel.dataset.loaded !== "1") {
      sel.innerHTML = cfg.workstreams
        .map(function (ws) {
          return '<option value="' + ws.id + '">' + esc(ws.id + " - " + ws.name) + "</option>";
        })
        .join("");
      sel.dataset.loaded = "1";
    }
  }

  function renderSettings() {
    var cfg = state.config;
    if (!cfg) return;
    setText("cfg-project", cfg.project);
    setText("cfg-multiplexer", cfg.multiplexer);
    setText("cfg-layout", cfg.layout);
    setText("cfg-base-branch", cfg.base_branch);
    setText("cfg-mode", cfg.mode);
    setText("cfg-agent", cfg.agent);
    setText("cfg-shared-deps", (cfg.shared_deps || []).join(", ") || "none");
    setText("cfg-base-path", cfg.base_path || ".");
    setText("cfg-workstream-count", String((cfg.workstreams || []).length));

    var list = $("cfg-workstreams");
    if (list) {
      list.innerHTML = (cfg.workstreams || []).length
        ? cfg.workstreams
            .map(function (ws) {
              return (
                '<li class="flex flex-wrap justify-between gap-2 border-b border-border py-1 text-sm">' +
                "<span>" + esc(ws.name) + ' <span class="text-on-surface/50 font-mono">#' + ws.id + "</span></span>" +
                '<span class="font-mono text-on-surface/60">' + esc(ws.branch) + " → " + esc(ws.path) + "</span></li>"
              );
            })
            .join("")
        : '<li class="text-on-surface/60 text-sm">No workstreams.</li>';
    }
  }

  // -- dispatch form ---------------------------------------------------------

  function setupDispatchForm() {
    var open = $("dispatch-open");
    var form = $("dispatch-form");
    var submit = $("dispatch-submit");
    if (!open || !form || !submit) return;

    open.addEventListener("click", function () {
      form.classList.toggle("hidden");
      var first = $("dispatch-subagent");
      if (first && !form.classList.contains("hidden")) first.focus();
    });

    submit.addEventListener("click", function () {
      var body = {
        workstream: parseInt($("dispatch-ws").value, 10) || 0,
        subagent: $("dispatch-subagent").value.trim(),
        prompt: $("dispatch-prompt").value.trim(),
        issue: parseInt($("dispatch-issue").value, 10) || 0,
        agent: $("dispatch-agent").value.trim()
      };
      var resultEl = $("dispatch-result");
      if (!body.subagent) {
        resultEl.className = "text-xs text-rose-500 mt-2";
        resultEl.textContent = "Subagent name is required.";
        return;
      }
      if (!body.prompt && !body.issue) {
        resultEl.className = "text-xs text-rose-500 mt-2";
        resultEl.textContent = "Provide a prompt or an issue number.";
        return;
      }
      submit.disabled = true;
      resultEl.className = "text-xs text-on-surface/60 mt-2";
      resultEl.textContent = "Dispatching…";

      api("/api/dispatch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      })
        .then(function (data) {
          resultEl.className = "text-xs mt-2 " + (data.warnings.length ? "text-amber-500" : "text-emerald-500");
          resultEl.textContent =
            data.message + (data.warnings.length ? " — " + data.warnings.join("; ") : "");
          refresh();
        })
        .catch(function (err) {
          resultEl.className = "text-xs text-rose-500 mt-2";
          resultEl.textContent = "Dispatch failed: " + err.message;
        })
        .then(function () {
          submit.disabled = false;
        });
    });
  }

  // -- lifecycle -------------------------------------------------------------

  function onScreenLoaded(name) {
    state.screen = name;
    // Screen-specific setup runs every time the screen HTML is (re)injected
    setupDispatchForm();
    renderScreen();
  }

  function start() {
    if (state.started) {
      refresh();
      return;
    }
    state.started = true;
    refresh();
    setInterval(refresh, POLL_MS);
    setInterval(tickUpdated, 1000);
  }

  window.WorkstreamsWeb = {
    onScreenLoaded: onScreenLoaded,
    start: start,
    refresh: refresh,
    state: state
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
