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
    started: false,
    inspectorTab: "overview",
    focusedWs: null
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
    if (state.config) {
      setText("header-project", state.config.project);
      setText("header-path", state.config.base_path || ".");
    }
    if (state.status && state.status.summary) {
      var alerts = state.status.summary.alerts;
      setText("header-alerts", String(alerts));
      var bell = $("header-alerts-btn");
      if (bell) bell.setAttribute("aria-label", "Alert notifications: " + alerts + " active");
    }
    tickUpdated();
  }

  function tickUpdated() {
    if (!state.lastFetch) return;
    var secs = Math.round((Date.now() - state.lastFetch) / 1000);
    setText("header-updated", secs <= 1 ? "Updated just now" : "Updated " + secs + "s ago");
  }

  // -- shared bits -----------------------------------------------------------

  function gitBadge(git) {
    var cls, glyph;
    if (git === "clean") {
      cls = "bg-success/15 text-success";
      glyph = "■";
    } else if (git === "dirty") {
      cls = "bg-warning/15 text-warning";
      glyph = "▲";
    } else {
      cls = "bg-surface-highest text-on-surface-variant";
      glyph = "□";
    }
    var label = !git || git === "unknown" ? "UNKNOWN" : git.toUpperCase();
    return (
      '<span class="inline-block px-2 py-0.5 border border-border font-mono text-xs ' + cls + '">' +
      glyph + " " + esc(label) + "</span>"
    );
  }

  function typeColors(t) {
    if (t === "failed" || t === "error") return { chip: "bg-danger/15 text-danger", dot: "bg-danger" };
    if (t === "completed" || t === "done") return { chip: "bg-success/15 text-success", dot: "bg-success" };
    if (t === "progress") return { chip: "bg-warning/15 text-warning", dot: "bg-warning" };
    if (t === "started") return { chip: "bg-secondary/15 text-secondary", dot: "bg-secondary" };
    return { chip: "bg-surface-highest text-on-surface-variant", dot: "bg-caption" };
  }

  function timeOf(ts) {
    return ts ? String(ts).slice(11, 19) : "";
  }

  function statusById(id) {
    var s = state.status;
    if (!s) return null;
    var match = s.statuses.filter(function (st) {
      return st.id === id;
    })[0];
    return match || null;
  }

  function focusedStatus() {
    var s = state.status;
    if (!s || !s.statuses.length) return null;
    return (state.focusedWs != null && statusById(state.focusedWs)) || s.statuses[0];
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

    renderMonitorTable(s);
    renderInspector(s);
    renderActivityRail(s);
    renderAlertsRail(s);
  }

  function renderMonitorTable(s) {
    var tbody = $("monitor-tbody");
    if (!tbody) return;
    if (!s.statuses.length) {
      tbody.innerHTML =
        '<tr><td colspan="6" class="p-3 text-on-surface-variant">No workstreams configured - run <span class="code-stream">workstreams init</span>.</td></tr>';
      return;
    }
    tbody.innerHTML = s.statuses
      .map(function (st) {
        var worker = (st.pane || "—") + (st.pid ? " / " + st.pid : "");
        var activity = st.last_commit || st.last_activity || "—";
        var focused = state.focusedWs === st.id || (state.focusedWs == null && st.id === s.statuses[0].id);
        return (
          '<tr data-ws-id="' + st.id + '" class="border-b border-border cursor-pointer transition-colors hover:bg-surface-high' +
          (focused ? " bg-surface-high" : "") + '">' +
          '<td class="p-2 font-mono text-primary border-l-2 ' + (focused ? "border-primary-fixed" : "border-transparent") + '">#' +
          String(st.id).padStart(2, "0") + "</td>" +
          '<td class="p-2">' + esc(st.name) +
          '<div class="text-xs text-on-surface-variant font-mono">' + esc(st.path) + "</div></td>" +
          '<td class="p-2 font-mono">' + esc(st.branch) + "</td>" +
          '<td class="p-2 font-mono">' + esc(worker) + "</td>" +
          '<td class="p-2">' + gitBadge(st.git_status) + "</td>" +
          '<td class="p-2 text-on-surface-variant">' + esc(activity) + "</td>" +
          "</tr>"
        );
      })
      .join("");
  }

  function renderInspector(s) {
    var tabs = document.querySelectorAll("[data-inspect-tab]");
    Array.prototype.forEach.call(tabs, function (t) {
      var isActive = t.getAttribute("data-inspect-tab") === state.inspectorTab;
      t.classList.toggle("active", isActive);
      t.setAttribute("aria-selected", isActive ? "true" : "false");
    });

    var body = $("inspector-body");
    if (!body) return;
    var st = focusedStatus();

    if (state.inspectorTab === "overview") {
      if (!st) {
        body.innerHTML = '<p class="text-on-surface-variant">No workstreams configured.</p>';
        return;
      }
      var cells = [
        ["FOCUSED", "#" + String(st.id).padStart(2, "0") + " " + st.name],
        ["PATH", st.path],
        ["BRANCH", st.branch],
        ["WORKER", (st.pane || "—") + (st.pid ? " / PID " + st.pid : "")],
        ["GIT STATE", (st.git_status || "unknown").toUpperCase()],
        ["LAST ACTIVITY", st.last_commit || st.last_activity || "—"],
        ["ALERTS", String((st.alerts || []).length)]
      ];
      body.innerHTML =
        '<div class="grid grid-cols-2 lg:grid-cols-4 gap-3">' +
        cells
          .map(function (c) {
            return (
              '<div class="border border-border bg-surface p-2">' +
              '<div class="label-md text-caption mb-1">' + esc(c[0]) + "</div>" +
              '<div class="code-stream text-on-surface break-all">' + esc(c[1]) + "</div></div>"
            );
          })
          .join("") +
        "</div>";
      return;
    }

    if (state.inspectorTab === "terminal") {
      var tails = [];
      if (st) {
        (st.log_tail || []).forEach(function (line) {
          tails.push(line);
        });
      } else {
        s.statuses.forEach(function (x) {
          (x.log_tail || []).forEach(function (line) {
            tails.push(line);
          });
        });
      }
      body.innerHTML = tails.length
        ? '<div class="bg-surface-lowest border border-border p-3 space-y-1 code-stream text-primary max-h-56 overflow-y-auto">' +
          tails.slice(-40).map(function (l) { return "<div>" + esc(l) + "</div>"; }).join("") +
          "</div>"
        : '<p class="text-on-surface-variant">No log output yet.</p>';
      return;
    }

    if (state.inspectorTab === "diff") {
      body.innerHTML = st
        ? '<div class="space-y-2">' +
          '<p class="text-on-surface-variant">Git diff is not exposed by <span class="code-stream">/api/status</span> - run ' +
          '<span class="code-stream text-primary">workstreams diff</span> in the CLI for a full patch.</p>' +
          '<div class="border border-border bg-surface p-2 flex flex-wrap items-center gap-3">' +
          '<span class="label-md text-caption">FOCUSED</span>' +
          '<span class="code-stream text-on-surface">' + esc(st.name) + "</span>" +
          '<span class="code-stream text-on-surface-variant">' + esc(st.branch) + "</span>" +
          gitBadge(st.git_status) +
          "</div></div>"
        : '<p class="text-on-surface-variant">No workstreams configured.</p>';
      return;
    }

    // worker log
    var alerts = [];
    s.statuses.forEach(function (x) {
      (x.alerts || []).forEach(function (a) {
        alerts.push(x.name + ": " + a);
      });
    });
    body.innerHTML = alerts.length
      ? '<div class="space-y-1">' +
        alerts.slice(-20).map(function (a) { return '<div class="code-stream text-danger">▲ ' + esc(a) + "</div>"; }).join("") +
        "</div>"
      : '<p class="text-on-surface-variant">No alerts.</p>';
  }

  function renderActivityRail(s) {
    var rail = $("activity-rail");
    if (!rail) return;
    var events = s.events || [];
    if (!events.length) {
      rail.innerHTML = '<p class="text-on-surface-variant">No subagent activity in the last 10 minutes.</p>';
      return;
    }
    rail.innerHTML = events
      .slice(-8)
      .reverse()
      .map(function (ev) {
        var c = typeColors(ev.event_type);
        return (
          '<div class="flex items-start gap-2">' +
          '<span class="w-2 h-2 mt-1 shrink-0 ' + c.dot + (ev.event_type === "progress" || ev.event_type === "started" ? " animate-pulse" : "") + '"></span><div class="min-w-0">' +
          '<div class="font-mono text-caption text-xs">' + esc(timeOf(ev.timestamp)) + " · " + esc(String(ev.event_type).toUpperCase()) + "</div>" +
          '<p class="text-primary line-clamp-1">' + esc(ev.subagent) + " " + esc(ev.message) + "</p></div></div>"
        );
      })
      .join("");
  }

  function renderAlertsRail(s) {
    var rail = $("alerts-rail");
    if (!rail) return;
    var rows = [];
    s.statuses.forEach(function (st) {
      (st.alerts || []).forEach(function (a) {
        rows.push({ name: st.name, text: a });
      });
    });
    rail.innerHTML = rows.length
      ? rows
          .map(function (r) {
            return (
              '<div class="border-l-2 border-danger pl-2">' +
              '<div class="label-md text-caption">' + esc(r.name) + "</div>" +
              '<div class="code-stream text-danger break-all">' + esc(r.text) + "</div></div>"
            );
          })
          .join("")
      : '<p class="text-on-surface-variant">No recent alerts.</p>';
  }

  // -- events ----------------------------------------------------------------

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
    setText("ev-last", events.length ? timeOf(events[0].timestamp) : "—");
    setText("ev-badge", s.summary.active + "/" + s.summary.total + " ACTIVE");

    renderTopology();
    renderSignalControl(events);
    renderCommitTrace(s);

    var list = $("events-list");
    if (!list) return;
    if (!events.length) {
      list.innerHTML =
        '<p class="text-on-surface-variant p-3">No events in the last 10 minutes. Dispatch a subagent to see activity here.</p>';
      return;
    }
    list.innerHTML = events
      .map(function (ev) {
        var c = typeColors(ev.event_type);
        return (
          '<div class="flex items-start gap-3 border-b border-border px-3 py-2">' +
          '<span class="shrink-0 px-2 py-0.5 border border-border font-mono text-xs ' + c.chip + '">' + esc(String(ev.event_type).toUpperCase()) + "</span>" +
          '<div class="flex-1 min-w-0">' +
          '<div class="font-mono text-xs text-primary">' + esc(ev.subagent) + (ev.issue ? " · #" + ev.issue : "") + "</div>" +
          '<div class="text-on-surface break-all">' + esc(ev.message) + "</div></div>" +
          '<span class="font-mono text-xs text-caption shrink-0">' + esc(timeOf(ev.timestamp)) + "</span>" +
          "</div>"
        );
      })
      .join("");
  }

  function renderTopology() {
    var el = $("events-topology");
    if (!el) return;
    var cfg = state.config;
    var s = state.status;
    var wss = (cfg && cfg.workstreams) || [];
    if (!wss.length) {
      el.innerHTML = '<p class="text-on-surface-variant text-xs">No workstreams configured - run <span class="code-stream">workstreams init</span>.</p>';
      return;
    }
    var byId = {};
    (s.statuses || []).forEach(function (st) {
      byId[st.id] = st;
    });

    var rowH = 60;
    var padY = 16;
    var W = 720;
    var H = Math.max(200, wss.length * rowH + padY * 2);
    var oy = Math.round(H / 2);
    var parts = [];

    // orchestrator core
    parts.push('<rect x="24" y="' + (oy - 26) + '" width="176" height="52" fill="#1d2024" stroke="#b1f73f" stroke-width="1"/>');
    parts.push('<text x="112" y="' + (oy - 4) + '" text-anchor="middle" fill="#e1e2e8" font-family="Space Mono, monospace" font-size="11" font-weight="700">ORCHESTRATOR</text>');
    parts.push('<text x="112" y="' + (oy + 14) + '" text-anchor="middle" fill="#c2cab0" font-family="Space Mono, monospace" font-size="9">IC-01 // IPC BUS</text>');

    wss.forEach(function (ws, i) {
      var st = byId[ws.id] || {};
      var active = st.pid != null;
      var cy = padY + i * rowH + rowH / 2;
      var stroke = active ? "#b1f73f" : "#2a333e";
      var wire =
        '<path d="M 200 ' + oy + " L 316 " + oy + " L 316 " + cy + " L 448 " + cy +
        '" fill="none" stroke="' + stroke + '" stroke-width="' + (active ? 1.5 : 1) + '"/>';
      parts.push(wire);
      if (active) {
        parts.push('<rect x="313" y="' + (cy - 3) + '" width="6" height="6" fill="#b1f73f"/>');
      }
      parts.push('<rect x="448" y="' + (cy - 22) + '" width="248" height="44" fill="#191c20" stroke="' + stroke + '" stroke-width="1"/>');
      parts.push(
        '<text x="462" y="' + (cy - 5) + '" fill="#e1e2e8" font-family="Space Mono, monospace" font-size="11" font-weight="700">' +
        esc(ws.name) + "</text>"
      );
      var sub = ws.branch + (st.pid ? " · PID " + st.pid : "");
      parts.push(
        '<text x="462" y="' + (cy + 13) + '" fill="#c2cab0" font-family="Space Mono, monospace" font-size="9">' +
        esc(sub) + "</text>"
      );
      parts.push(
        '<rect x="674" y="' + (cy - 5) + '" width="10" height="10" fill="' + (active ? "#b1f73f" : "#414e5e") + '"/>'
      );
    });

    el.innerHTML =
      '<svg viewBox="0 0 ' + W + " " + H + '" class="w-full h-auto" role="img" aria-label="Workstream bus topology">' +
      parts.join("") +
      "</svg>";
  }

  function renderSignalControl(events) {
    var el = $("signal-control");
    if (!el) return;
    if (!events.length) {
      el.innerHTML = '<p class="text-on-surface-variant">No signals in the last 10 minutes.</p>';
      return;
    }
    var counts = {};
    events.forEach(function (e) {
      counts[e.event_type] = (counts[e.event_type] || 0) + 1;
    });
    el.innerHTML =
      '<div class="space-y-2">' +
      Object.keys(counts)
        .map(function (t) {
          var c = typeColors(t);
          return (
            '<div class="flex items-center justify-between gap-3">' +
            '<span class="flex items-center gap-2"><span class="w-2.5 h-2.5 ' + c.dot + '"></span>' +
            '<span class="label-md text-on-surface-variant">' + esc(t) + "</span></span>" +
            '<span class="code-stream text-on-surface">' + counts[t] + "</span></div>"
          );
        })
        .join("") +
      '<p class="text-caption pt-1 border-t border-border">packet states from <span class="code-stream">/api/status</span> events</p>' +
      "</div>";
  }

  function renderCommitTrace(s) {
    var el = $("commit-trace");
    if (!el) return;
    if (!s.statuses.length) {
      el.innerHTML = '<p class="text-on-surface-variant">No workstreams configured.</p>';
      return;
    }
    el.innerHTML = s.statuses
      .map(function (st) {
        var activity = st.last_commit || st.last_activity || "no activity";
        return (
          '<div class="border-l-2 pl-2 ' + (st.git_status === "dirty" ? "border-warning" : "border-border-strong") + '">' +
          '<div class="label-md text-caption">#' + String(st.id).padStart(2, "0") + " " + esc(st.name) + "</div>" +
          '<div class="code-stream text-on-surface line-clamp-1 break-all">' + esc(activity) + "</div></div>"
        );
      })
      .join("");
  }

  // -- workstreams -----------------------------------------------------------

  function renderWorkstreams() {
    var cfg = state.config;
    var s = state.status;
    if (!cfg || !s) return;

    var byId = {};
    s.statuses.forEach(function (st) {
      byId[st.id] = st;
    });
    setText("ws-running", s.summary.active + " RUNNING");

    var grid = $("workstreams-grid");
    if (grid) {
      if (!cfg.workstreams.length) {
        grid.innerHTML =
          '<p class="text-on-surface-variant text-sm col-span-full">No workstreams configured - run <span class="code-stream">workstreams init</span>.</p>';
      } else {
        grid.innerHTML = cfg.workstreams
          .map(function (ws) {
            var st = byId[ws.id] || {};
            var active = st.pid != null;
            var badge = active
              ? '<span class="text-xs font-mono font-bold bg-success/15 text-success border border-border px-2 py-0.5">■ RUNNING</span>'
              : '<span class="text-xs font-mono font-bold bg-surface-highest text-on-surface-variant border border-border px-2 py-0.5">□ IDLE</span>';
            var alertCount = (st.alerts || []).length;
            return (
              '<div class="panel p-4">' +
              '<div class="flex items-center justify-between mb-2 gap-2"><div class="min-w-0">' +
              '<h3 class="font-mono text-sm font-bold text-on-surface truncate">' + esc(ws.name) + "</h3>" +
              '<p class="code-stream text-on-surface-variant truncate">' + esc(ws.branch) + "</p></div>" + badge + "</div>" +
              '<p class="code-stream text-on-surface-variant mb-3 truncate">' + esc(ws.path) + "</p>" +
              '<div class="flex items-center gap-2 text-xs mb-2 flex-wrap">' + gitBadge(st.git_status) +
              '<span class="text-on-surface-variant font-mono">pane ' + esc(st.pane || "—") +
              (st.pid ? " / PID " + esc(st.pid) : "") + "</span></div>" +
              '<p class="text-xs text-on-surface-variant">' + esc(st.last_commit || st.last_activity || "no activity") + "</p>" +
              (alertCount ? '<p class="text-xs text-danger mt-1 font-mono">▲ ' + alertCount + " alert(s)</p>" : "") +
              "</div>"
            );
          })
          .join("");
      }
    }

    // conflict radar (real git state counts)
    var radar = $("conflict-radar");
    if (radar) {
      var counts = { clean: 0, dirty: 0, other: 0 };
      s.statuses.forEach(function (st) {
        if (st.git_status === "clean") counts.clean++;
        else if (st.git_status === "dirty") counts.dirty++;
        else counts.other++;
      });
      var total = s.statuses.length || 1;
      radar.innerHTML =
        '<div class="flex h-1.5 w-full bg-surface-lowest mb-2">' +
        '<div class="bg-success" style="width:' + Math.round((counts.clean / total) * 100) + '%"></div>' +
        '<div class="bg-warning" style="width:' + Math.round((counts.dirty / total) * 100) + '%"></div>' +
        '<div class="bg-surface-highest" style="width:' + Math.round((counts.other / total) * 100) + '%"></div>' +
        "</div>" +
        '<div class="flex flex-wrap gap-x-4 gap-y-1">' +
        '<span class="label-md text-success">■ ' + counts.clean + " CLEAN</span>" +
        '<span class="label-md text-warning">▲ ' + counts.dirty + " DIRTY</span>" +
        '<span class="label-md text-caption">□ ' + counts.other + " UNKNOWN</span>" +
        "</div>";
    }

    // dispatch timeline (commit stream from statuses)
    var timeline = $("dispatch-timeline");
    if (timeline) {
      timeline.innerHTML = s.statuses.length
        ? s.statuses
            .map(function (st) {
              var activity = st.last_commit || st.last_activity || "no activity";
              return (
                '<div class="flex items-start gap-2 border-b border-border pb-1">' +
                '<span class="font-mono text-primary shrink-0">#' + String(st.id).padStart(2, "0") + "</span>" +
                '<div class="min-w-0"><span class="text-on-surface">' + esc(st.name) + "</span>" +
                '<div class="code-stream text-on-surface-variant line-clamp-1 break-all">' + esc(activity) + "</div></div>" +
                "</div>"
              );
            })
            .join("")
        : '<p class="text-on-surface-variant">No workstreams configured.</p>';
    }

    // inter-agent IPC feed (real events)
    var ipc = $("ipc-stream");
    if (ipc) {
      var events = (s.events || []).slice().reverse().slice(0, 12);
      ipc.innerHTML = events.length
        ? events
            .map(function (ev) {
              var c = typeColors(ev.event_type);
              return (
                '<div class="flex items-start gap-2">' +
                '<span class="shrink-0 px-1.5 py-0.5 border border-border font-mono text-[10px] ' + c.chip + '">' + esc(String(ev.event_type).toUpperCase()) + "</span>" +
                '<div class="min-w-0 flex-1"><span class="font-mono text-primary">' + esc(ev.subagent) + "</span> " +
                '<span class="text-on-surface-variant">' + esc(ev.message) + "</span></div>" +
                '<span class="font-mono text-[10px] text-caption shrink-0">' + esc(timeOf(ev.timestamp)) + "</span>" +
                "</div>"
              );
            })
            .join("")
        : '<p class="text-on-surface-variant">No IPC traffic in the last 10 minutes.</p>';
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

  // -- settings --------------------------------------------------------------

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

    var list = $("#cfg-workstreams".replace("#", "")) || $("cfg-workstreams");
    if (list) {
      list.innerHTML = (cfg.workstreams || []).length
        ? cfg.workstreams
            .map(function (ws) {
              return (
                '<li class="flex flex-wrap justify-between gap-2 border-b border-border py-2 text-sm">' +
                "<span class=\"text-on-surface\">" + esc(ws.name) + ' <span class="text-caption font-mono">#' + ws.id + "</span></span>" +
                '<span class="font-mono text-on-surface-variant">' + esc(ws.branch) + " → " + esc(ws.path) + "</span></li>"
              );
            })
            .join("")
        : '<li class="text-on-surface-variant py-2">No workstreams.</li>';
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
        resultEl.className = "text-xs text-danger mt-2";
        resultEl.textContent = "Subagent name is required.";
        return;
      }
      if (!body.prompt && !body.issue) {
        resultEl.className = "text-xs text-danger mt-2";
        resultEl.textContent = "Provide a prompt or an issue number.";
        return;
      }
      submit.disabled = true;
      resultEl.className = "text-xs text-on-surface-variant mt-2";
      resultEl.textContent = "Dispatching…";

      api("/api/dispatch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      })
        .then(function (data) {
          resultEl.className = "text-xs mt-2 " + (data.warnings.length ? "text-warning" : "text-success");
          resultEl.textContent =
            data.message + (data.warnings.length ? " — " + data.warnings.join("; ") : "");
          refresh();
        })
        .catch(function (err) {
          resultEl.className = "text-xs text-danger mt-2";
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
    state: state,
    setInspectorTab: function (tab) {
      state.inspectorTab = tab;
      renderScreen();
    },
    focusWorkstream: function (id) {
      state.focusedWs = id;
      renderScreen();
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
