/* NoSQL lesson studio: lessons (or the guide reader, reader.js) on the left, live consoles
   on the right. Vanilla JS. */
(function () {
  "use strict";

  var TOKEN_KEY = "nosql-studio-token";
  var THEME_KEY = "nosql-studio-theme";
  var ACCENT = { mongo: "acc-mongo", redis: "acc-redis", cql: "acc-cql", dynamodb: "acc-dynamodb", cypher: "acc-cypher", duckdb: "acc-duckdb" };
  var IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  var LAB_LESSONS = { ch02: 1, ch03: 1, ch04: 1, ch05: 1, ch06: 1 };

  var state = {
    meta: null,
    lesson: null,
    stepIndex: 0,
    console: "mongo",
    active: null, // the exercise being worked on
    historyPos: {},
    views: {}, // block view choice (table/json) by console
    status: [],
    jobRunning: false,
    view: "lesson", // "lesson" or "reader"
    readerLayout: "wide", // "wide" (console hidden) or "split" (reader next to the console)
    readerFrom: null, // {hash, label}: the lesson step the reader was opened from
    lessonHash: null, // the lesson route currently rendered in the lesson pane
  };

  // ------------------------------------------------------------ helpers
  function $(id) { return document.getElementById(id); }

  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "html") el.innerHTML = v; // only ever given escaped markup from md()
        else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
        else if (k === "style") {
          // CSSOM, not a style attribute: the CSP forbids inline style attributes
          String(v).split(";").forEach(function (decl) {
            var i = decl.indexOf(":");
            if (i > 0) el.style.setProperty(decl.slice(0, i).trim(), decl.slice(i + 1).trim());
          });
        }
        else el.setAttribute(k, v === true ? "" : String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(el, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { append(el, c); }); return; }
    el.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // A tiny, safe subset of Markdown for lesson prose: `code` and **bold** (escaped first).
  function md(text) {
    var out = escapeHtml(text);
    out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    return out;
  }

  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
  };

  function icon(name) {
    var paths = {
      ext: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
      play: '<path d="M7 5v14l11-7z"/>',
      db: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
      check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
      edit: '<path d="M4 20h4L19 9l-4-4L4 16v4z"/>',
      book: '<path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H11a1 1 0 0 1 1 1v16a1 1 0 0 0-1-1H5.5A1.5 1.5 0 0 1 4 17.5zM20 4.5A1.5 1.5 0 0 0 18.5 3H13a1 1 0 0 0-1 1v16a1 1 0 0 1 1-1h5.5a1.5 1.5 0 0 0 1.5-1.5z"/>',
      back: '<path d="M15 5l-7 7 7 7"/>',
      copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
      file: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/>',
      folder: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/>',
      console: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12.5 15H17"/>',
      split: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
      wide: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h10M7 13h10M7 17h6"/>',
    };
    var svg = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (paths[name] || "") + "</svg>";
    var span = document.createElement("span");
    span.style.display = "inline-flex";
    span.innerHTML = svg; // static markup from this file
    return span.firstChild;
  }

  // ------------------------------------------------------------ token and API
  function readToken() {
    var params = new URLSearchParams(location.search);
    var t = params.get("token");
    if (t) {
      try { sessionStorage.setItem(TOKEN_KEY, t); } catch (e) {}
      params.delete("token");
      var q = params.toString();
      window.history.replaceState(null, "", location.pathname + (q ? "?" + q : "") + location.hash);
      return t;
    }
    try { return sessionStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
  }
  var TOKEN = readToken();

  function api(path, body, raw) {
    var opts = { method: body === undefined ? "GET" : "POST", headers: { "X-Studio-Token": TOKEN || "" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (res) {
      if (raw) return res;
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
        if (!res.ok) {
          var err = new Error((data && data.detail) || res.statusText);
          err.status = res.status;
          throw err;
        }
        return data;
      });
    });
  }

  function gate(message) {
    var studio = $("studio");
    clear(studio).appendChild(
      h("div", { class: "gate" },
        h("h1", { text: "Open the studio from its start URL" }),
        h("p", { class: "lede", text: message }),
        h("p", null, "Run ", h("code", { text: "make studio" }), " in the repository and open the address it prints (it carries a fresh token each start)."))
    );
    studio.style.display = "block";
    studio.style.overflow = "auto";
  }

  // ------------------------------------------------------------ theme
  function currentTheme() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function updateThemeButton() {
    var next = currentTheme() === "dark" ? "light" : "dark";
    $("theme-toggle").setAttribute("aria-label", "Switch to " + next + " theme");
    $("theme-toggle").setAttribute("title", "Switch to " + next + " theme");
  }
  $("theme-toggle").addEventListener("click", function () {
    var next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    store.set(THEME_KEY, next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
    updateThemeButton();
  });

  // ------------------------------------------------------------ values
  function typed(v, consoleId) {
    if (v === null || v === undefined) return { text: "null", cls: "v-null" };
    if (typeof v === "boolean") return { text: String(v), cls: "v-bool" };
    if (typeof v === "number") return { text: String(v), cls: "v-num" };
    if (typeof v === "string") return { text: v, cls: "v-str" };
    if (!Array.isArray(v) && typeof v === "object") {
      var keys = Object.keys(v);
      if (keys.length >= 1 && keys[0].charAt(0) === "$" && keys.length <= 2) {
        var mongo = consoleId === "mongo";
        if ("$date" in v) return { text: mongo ? 'ISODate("' + v.$date + '")' : v.$date, cls: "v-typed" };
        if ("$oid" in v) return { text: 'ObjectId("' + v.$oid + '")', cls: "v-typed" };
        if ("$numberDecimal" in v) return { text: mongo ? 'NumberDecimal("' + v.$numberDecimal + '")' : v.$numberDecimal, cls: "v-num" };
        if ("$numberLong" in v) return { text: mongo ? 'Long("' + v.$numberLong + '")' : v.$numberLong, cls: "v-num" };
        if ("$regex" in v) return { text: "/" + v.$regex + "/" + (v.$options || ""), cls: "v-typed" };
        if ("$uuid" in v) return { text: v.$uuid, cls: "v-typed" };
        if ("$dateOnly" in v) return { text: v.$dateOnly, cls: "v-typed" };
        if ("$binary" in v) return { text: "Binary(" + v.$binary + ")", cls: "v-typed" };
        var k0 = keys[0];
        if (typeof v[k0] !== "object") return { text: String(v[k0]), cls: "v-typed" };
      }
    }
    return { text: compact(v, consoleId), cls: "v-str" };
  }
  function compact(v, consoleId) {
    if (v === null || v === undefined) return "null";
    if (typeof v !== "object") return typeof v === "string" ? JSON.stringify(v) : String(v);
    var t = typed(v, consoleId);
    if (t.cls !== "v-str" || (!Array.isArray(v) && Object.keys(v).length && Object.keys(v)[0].charAt(0) === "$" && Object.keys(v).length <= 2 && typeof v[Object.keys(v)[0]] !== "object")) return t.text;
    if (Array.isArray(v)) return "[" + v.map(function (x) { return compact(x, consoleId); }).join(", ") + "]";
    return "{" + Object.keys(v).map(function (k) { return k + ": " + compact(v[k], consoleId); }).join(", ") + "}";
  }
  function isTyped(v) {
    if (!v || typeof v !== "object" || Array.isArray(v)) return false;
    var keys = Object.keys(v);
    return keys.length >= 1 && keys.length <= 2 && keys[0].charAt(0) === "$" && typeof v[keys[0]] !== "object";
  }

  function tree(value, consoleId) {
    var root = h("div", { class: "tree" });
    function node(key, v, depth) {
      var label = key === null ? null : h("span", { class: "k", text: key + ": " });
      if (v !== null && typeof v === "object" && !isTyped(v)) {
        var isArr = Array.isArray(v);
        var keys = isArr ? v.map(function (_, i) { return i; }) : Object.keys(v);
        var det = h("details", depth < 2 || keys.length <= 4 ? { open: true } : null);
        det.appendChild(h("summary", null, label, h("span", { class: "meta", text: isArr ? "[" + keys.length + "]" : "{" + keys.length + "}" })));
        keys.forEach(function (k) { det.appendChild(node(String(k), v[k], depth + 1)); });
        return det;
      }
      var t = typed(v, consoleId);
      return h("div", { class: "row" }, label, h("span", { class: t.cls, text: typeof v === "string" ? JSON.stringify(v) : t.text }));
    }
    if (Array.isArray(value) && value.length && value.every(function (x) { return x && typeof x === "object" && !Array.isArray(x); })) {
      value.forEach(function (doc, i) { root.appendChild(node(null, doc, i < 20 ? 1 : 3)); });
    } else {
      root.appendChild(node(null, value, 0));
    }
    return root;
  }

  function grid(columns, rows, consoleId) {
    var table = h("table", { class: "grid" });
    var thead = h("thead", null, h("tr", null, columns.map(function (c) { return h("th", { scope: "col", text: c }); })));
    var tbody = h("tbody");
    rows.forEach(function (r) {
      tbody.appendChild(h("tr", null, r.map(function (v) {
        var t = typed(v, consoleId);
        return h("td", { class: t.cls + (typeof v === "number" ? " num" : ""), title: t.text.length > 40 ? t.text : null, text: t.text });
      })));
    });
    table.appendChild(thead);
    table.appendChild(tbody);
    return table;
  }

  // ------------------------------------------------------------ results
  function renderResult(res, consoleId) {
    var box = clear($("results"));
    box.appendChild(h("p", { class: "run-meta", text: res.blocks.length + " statement" + (res.blocks.length === 1 ? "" : "s") + " in " + fmtMs(res.elapsed_ms) }));
    res.blocks.forEach(function (b) { box.appendChild(renderBlock(b, consoleId)); });
  }
  function fmtMs(ms) { return ms < 1 ? ms.toFixed(2) + " ms" : ms < 1000 ? ms.toFixed(1) + " ms" : (ms / 1000).toFixed(2) + " s"; }

  function renderBlock(b, consoleId) {
    var el = h("div", { class: "block" + (b.kind === "error" ? " error" : "") });
    var head = h("div", { class: "block-head" }, h("span", { class: "cmd", title: b.command, text: b.command || "(input)" }));
    var body = h("div", { class: "block-body" });
    var hasTable = (b.kind === "table" || b.kind === "plan") && b.columns && b.columns.length;
    var hasTree = b.value !== undefined && b.value !== null;
    var preferred = state.views[consoleId] || (consoleId === "mongo" ? "json" : "table");
    var view = hasTable && hasTree ? preferred : hasTable ? "table" : "json";
    if (b.kind === "plan") view = state.views["plan"] || "table";

    function draw() {
      clear(body);
      if (b.kind === "error") {
        body.appendChild(h("div", { class: "error-title", text: b.title || "Error" }));
        body.appendChild(h("pre", { text: b.text }));
        if (b.hint) body.appendChild(h("div", { class: "error-hint", html: md(b.hint) }));
        if (hasTree) body.appendChild(tree(b.value, consoleId));
        return;
      }
      if (b.kind === "text") { body.appendChild(h("pre", { text: b.text })); return; }
      if (view === "table" && hasTable) {
        if (!b.rows.length) body.appendChild(h("pre", { class: "muted", text: "(no rows)" }));
        else body.appendChild(grid(b.columns, b.rows, consoleId));
      } else if (hasTree) {
        body.appendChild(tree(b.value, consoleId));
      } else {
        body.appendChild(h("pre", { class: "muted", text: "(nothing returned)" }));
      }
    }
    if (hasTable && hasTree && b.kind !== "error") {
      var seg = h("div", { class: "seg", role: "group", "aria-label": "Result view" });
      ["table", "json"].forEach(function (v) {
        seg.appendChild(h("button", {
          type: "button", "aria-pressed": String(view === v), text: v === "table" ? (b.kind === "plan" ? "Plan" : "Table") : (b.kind === "plan" ? "Raw" : "JSON"),
          onclick: function () {
            view = v;
            state.views[b.kind === "plan" ? "plan" : consoleId] = v;
            Array.prototype.forEach.call(seg.children, function (c) { c.setAttribute("aria-pressed", String(c === this)); }, this);
            draw();
          },
        }));
      });
      head.appendChild(seg);
    }
    var count = b.row_count !== undefined ? b.row_count + (b.truncated ? "+" : "") + " row" + (b.row_count === 1 ? "" : "s") + " · " : "";
    head.appendChild(h("span", { class: "ms", text: count + fmtMs(b.elapsed_ms) }));
    el.appendChild(head);
    draw();
    el.appendChild(body);
    if (b.notes && b.notes.length) {
      el.appendChild(h("ul", { class: "notes" }, b.notes.map(function (n) {
        return h("li", { class: /warning|not reported|WARN/i.test(n) ? "warn" : null, text: n });
      })));
    }
    if (b.truncated) el.appendChild(h("ul", { class: "notes" }, h("li", { text: "Showing the first rows only." })));
    return el;
  }

  // ------------------------------------------------------------ console
  var editor = $("editor");
  var gutter = $("gutter");

  function consoleInfo(id) {
    return (state.meta.consoles || []).find(function (c) { return c.id === id; }) || { id: id, label: id, language: "" };
  }
  function draftKey() { return state.active ? "draft:" + state.active.id : "scratch:" + state.console; }
  function saveDraft() { store.set(draftKey(), editor.value); }
  function setEditor(text) { editor.value = text; editor.scrollTop = 0; editor.scrollLeft = 0; updateGutter(); }
  function updateGutter() {
    var n = editor.value.split("\n").length;
    var out = [];
    for (var i = 1; i <= Math.max(n, 1); i++) out.push(i);
    gutter.textContent = out.join("\n");
    gutter.scrollTop = editor.scrollTop;
  }
  editor.addEventListener("input", function () { updateGutter(); saveDraft(); state.historyPos[state.console] = null; });
  editor.addEventListener("scroll", function () { gutter.scrollTop = editor.scrollTop; });

  function historyList(consoleId) { return store.get("history:" + consoleId, []); }
  function pushHistory(consoleId, text) {
    var list = historyList(consoleId).filter(function (x) { return x !== text; });
    list.push(text);
    store.set("history:" + consoleId, list.slice(-50));
    state.historyPos[consoleId] = null;
  }

  editor.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); runConsole(); return; }
    if (e.key === "Escape") { editor.blur(); return; }
    if (e.key === "Tab" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      var s = editor.selectionStart, en = editor.selectionEnd;
      editor.value = editor.value.slice(0, s) + "  " + editor.value.slice(en);
      editor.selectionStart = editor.selectionEnd = s + 2;
      updateGutter(); saveDraft();
      return;
    }
    if ((e.key === "ArrowUp" || e.key === "ArrowDown") && !e.shiftKey && !e.altKey && editor.selectionStart === editor.selectionEnd) {
      var pos = editor.selectionStart;
      var onFirst = editor.value.lastIndexOf("\n", pos - 1) === -1;
      var onLast = editor.value.indexOf("\n", pos) === -1;
      var list = historyList(state.console);
      if (!list.length) return;
      var cur = state.historyPos[state.console];
      if (e.key === "ArrowUp" && onFirst) {
        e.preventDefault();
        if (cur === null || cur === undefined) { state.pending = editor.value; cur = list.length; }
        cur = Math.max(0, cur - 1);
        state.historyPos[state.console] = cur;
        setEditor(list[cur]);
        editor.selectionStart = editor.selectionEnd = 0;
      } else if (e.key === "ArrowDown" && onLast && cur !== null && cur !== undefined) {
        e.preventDefault();
        cur += 1;
        if (cur >= list.length) { state.historyPos[state.console] = null; setEditor(state.pending || ""); }
        else { state.historyPos[state.console] = cur; setEditor(list[cur]); }
        editor.selectionStart = editor.selectionEnd = editor.value.length;
      }
    }
  });

  function renderTabs() {
    var tabs = clear($("console-tabs"));
    var used = state.lesson ? state.lesson.consoles : [];
    state.meta.consoles.forEach(function (c) {
      var btn = h("button", {
        type: "button", role: "tab", id: "tab-" + c.id, class: ACCENT[c.id] + (used.length && used.indexOf(c.id) < 0 ? " dim" : ""),
        "aria-selected": String(c.id === state.console), tabindex: c.id === state.console ? "0" : "-1",
        onclick: function () { switchConsole(c.id); },
      }, h("span", { class: "dot", "aria-hidden": "true" }), c.label);
      tabs.appendChild(btn);
    });
    tabs.onkeydown = function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      var ids = state.meta.consoles.map(function (c) { return c.id; });
      var i = ids.indexOf(state.console) + (e.key === "ArrowRight" ? 1 : -1);
      i = (i + ids.length) % ids.length;
      switchConsole(ids[i]);
      $("tab-" + ids[i]).focus();
    };
  }

  function switchConsole(id, keepActive) {
    if (state.active && !keepActive && state.active.console !== id) setActive(null);
    if (id !== state.console && !state.active) saveDraft();
    state.console = id;
    store.set("console", id);
    var info = consoleInfo(id);
    $("lang").textContent = info.language;
    editor.setAttribute("placeholder", info.placeholder || "");
    $("subset-help").hidden = id !== "mongo";
    renderTabs();
    if (!state.active) setEditor(store.get(draftKey(), ""));
    var last = state.lastResults && state.lastResults[id];
    if (last) renderResult(last, id);
    else clear($("results")).appendChild(h("p", { class: "empty", text: "Results appear here. Pick an example in the lesson, or type and press " + runKeys() + "." }));
  }

  function runKeys() { return IS_MAC ? "Cmd+Enter" : "Ctrl+Enter"; }

  function runConsole(textOverride) {
    var text = textOverride !== undefined ? textOverride : editor.value;
    if (!text.trim()) return Promise.resolve();
    var btn = $("run-btn");
    btn.disabled = true;
    var original = btn.innerHTML;
    btn.textContent = "";
    btn.appendChild(h("span", { class: "spinner", "aria-hidden": "true" }));
    btn.appendChild(document.createTextNode(" Running"));
    var consoleId = state.console;
    pushHistory(consoleId, text);
    return api("/api/run", { console: consoleId, text: text }).then(function (res) {
      state.lastResults = state.lastResults || {};
      state.lastResults[consoleId] = res;
      if (state.console === consoleId) renderResult(res, consoleId);
      refreshStatusSoon();
    }).catch(function (err) {
      clear($("results")).appendChild(renderBlock({ command: text.split("\n")[0], kind: "error", title: "The studio could not run this", text: err.message, elapsed_ms: 0, notes: [] }, consoleId));
      if (err.status === 401) gate("The studio token is missing or stale.");
    }).finally(function () {
      btn.disabled = false;
      btn.innerHTML = original;
    });
  }
  $("run-btn").addEventListener("click", function () { runConsole(); });
  $("run-keys").textContent = runKeys();
  $("clear-btn").addEventListener("click", function () {
    if (state.lastResults) delete state.lastResults[state.console];
    clear($("results")).appendChild(h("p", { class: "empty", text: "Cleared." }));
  });

  function loadExample(ex, run) {
    if (state.active) setActive(null);
    switchConsole(ex.console, true);
    setEditor(ex.code);
    saveDraft();
    if (run) runConsole(ex.code);
    else editor.focus();
  }

  // ------------------------------------------------------------ exercises
  function setActive(ex) {
    if (state.active) saveDraft();
    state.active = ex;
    var bar = $("working");
    document.querySelectorAll(".exercise.active").forEach(function (n) { n.classList.remove("active"); });
    if (!ex) {
      bar.hidden = true;
      setEditor(store.get(draftKey(), ""));
      return;
    }
    switchConsole(ex.console, true);
    var progress = (state.lesson.progress.drafts || {})[ex.id];
    setEditor(store.get("draft:" + ex.id, null) || progress || ex.starter);
    var card = document.getElementById("ex-" + ex.id);
    if (card) card.classList.add("active");
    clear($("working-what")).appendChild(h("span", null, h("b", { text: ex.number }), ex.title));
    bar.hidden = false;
  }
  $("working-close").addEventListener("click", function () { setActive(null); });
  $("working-check").addEventListener("click", function () { if (state.active) checkExercise(state.active); });

  function exState(id) { return (state.lesson.progress.exercises || {})[id] || {}; }

  function checkExercise(ex) {
    if (!state.active || state.active.id !== ex.id) {
      setActive(ex);
      editor.focus();
      showVerdict(ex, null, "Write your answer in the console (the starter is loaded), then check it.");
      return;
    }
    var answer = editor.value;
    saveDraft();
    var cardBtn = document.querySelector("#ex-" + cssId(ex.id) + " .check-btn");
    [cardBtn, $("working-check")].forEach(function (b) { if (b) { b.disabled = true; b.dataset.label = b.textContent; b.textContent = "Checking..."; } });
    api("/api/check", { exercise_id: ex.id, answer: answer }).then(function (res) {
      state.lesson.progress.exercises[ex.id] = res.progress;
      showVerdict(ex, res);
      updateLessonProgress(res.lesson);
    }).catch(function (err) {
      if (err.status === 409 || err.status === 503) showVerdict(ex, null, err.message, true);
      else showVerdict(ex, { ok: false, message: err.message, details: [] });
    }).finally(function () {
      [cardBtn, $("working-check")].forEach(function (b) { if (b) { b.disabled = false; b.textContent = b.dataset.label || "Check my answer"; } });
      refreshExerciseCard(ex);
    });
  }
  function cssId(id) { return id.replace(/\./g, "\\."); }

  function pretty(v) {
    if (v === null || v === undefined) return "";
    try { return JSON.stringify(v, function (k, x) { return isTyped(x) ? typed(x, "").text : x; }, 2); } catch (e) { return String(v); }
  }

  function showVerdict(ex, res, info, problem) {
    var slot = document.getElementById("verdict-" + ex.id);
    if (!slot) return;
    clear(slot);
    if (info) { slot.appendChild(h("p", { class: "callout small" + (problem ? " bad" : ""), role: problem ? "alert" : null, text: info })); return; }
    var ok = res.ok;
    var v = h("div", { class: "verdict " + (ok ? "pass" : "fail"), role: "status" },
      h("div", { class: "verdict-head" }, h("span", { class: "badge " + (ok ? "pass" : "fail"), text: ok ? "PASS" : "FAIL" }), h("span", { text: res.message })));
    if ((res.expected !== null && res.expected !== undefined) || (res.got !== null && res.got !== undefined)) {
      v.appendChild(h("div", { class: "verdict-grid" },
        h("div", null, h("h4", { text: "Expected" }), h("pre", { text: pretty(res.expected) || "(see the message)" })),
        h("div", null, h("h4", { text: "Got" }), h("pre", { text: pretty(res.got) || "(nothing)" }))));
    }
    if (ok && res.explain) v.appendChild(h("div", { class: "explain", text: res.explain }));
    slot.appendChild(v);
  }

  function refreshExerciseCard(ex) {
    var st = exState(ex.id);
    var badge = document.getElementById("state-" + ex.id);
    if (badge) {
      badge.className = "state" + (st.passed ? " passed" : "");
      badge.textContent = st.passed ? "passed" : st.attempts ? st.attempts + " attempt" + (st.attempts === 1 ? "" : "s") : "not started";
    }
    var sol = document.getElementById("solbtn-" + ex.id);
    if (sol) {
      var can = (st.attempts || 0) > 0;
      sol.disabled = !can;
      sol.title = can ? "" : "Check an answer of your own first";
    }
    renderStepChips();
  }

  function exerciseCard(ex) {
    var hintsShown = store.get("hints:" + ex.id, 0);
    var hintList = h("ol", { class: "hints" });
    var hintBtn = h("button", { type: "button", class: "btn small" });
    function drawHints() {
      clear(hintList);
      ex.hints.slice(0, hintsShown).forEach(function (t, i) { hintList.appendChild(h("li", null, h("b", { text: "Hint " + (i + 1) }), h("span", { html: md(t) }))); });
      hintBtn.textContent = hintsShown >= ex.hints.length ? "No more hints" : "Hint " + (hintsShown + 1) + " of " + ex.hints.length;
      hintBtn.disabled = hintsShown >= ex.hints.length;
    }
    hintBtn.addEventListener("click", function () { hintsShown += 1; store.set("hints:" + ex.id, hintsShown); drawHints(); });
    drawHints();
    var solutionSlot = h("div", { class: "solution" });
    var solBtn = h("button", {
      type: "button", class: "btn small ghost", id: "solbtn-" + ex.id, text: "Show solution",
      onclick: function () {
        api("/api/solution", { exercise_id: ex.id }).then(function (res) {
          clear(solutionSlot).appendChild(h("div", null,
            h("pre", { class: "code", text: res.solution }),
            h("div", { style: "display:flex;gap:6px;margin-top:6px" },
              h("button", { type: "button", class: "btn small", text: "Load into the console", onclick: function () { setActive(ex); setEditor(res.solution); saveDraft(); editor.focus(); } })),
            res.explain ? h("p", { class: "small muted", style: "margin-top:6px", text: res.explain }) : null));
        }).catch(function (err) { clear(solutionSlot).appendChild(h("p", { class: "callout bad small", text: err.message })); });
      },
    });
    var card = h("article", { class: "exercise " + (ACCENT[ex.console] || ""), id: "ex-" + ex.id, "aria-labelledby": "ext-" + ex.id },
      h("div", { class: "exercise-head" },
        h("span", { class: "num", text: "Exercise " + ex.number }),
        h("span", { class: "tag " + (ACCENT[ex.console] || ""), text: consoleInfo(ex.console).label }),
        h("span", { class: "state", id: "state-" + ex.id })),
      h("div", { class: "exercise-body" },
        h("h3", { id: "ext-" + ex.id, text: ex.title, style: "margin:4px 0 6px" }),
        h("p", { class: "task", html: md(ex.task) }),
        h("div", { class: "actions" },
          h("button", { type: "button", class: "btn small", onclick: function () { setActive(ex); editor.focus(); } }, icon("edit"), "Work on this"),
          h("button", { type: "button", class: "btn small primary check-btn", text: "Check my answer", onclick: function () { checkExercise(ex); } }),
          hintBtn, solBtn),
        hintList,
        h("div", { id: "verdict-" + ex.id, "aria-live": "polite" }),
        solutionSlot));
    setTimeout(function () { refreshExerciseCard(ex); }, 0);
    return card;
  }

  // ------------------------------------------------------------ lessons
  function lessonMeta(id) { return state.meta.lessons.find(function (l) { return l.id === id; }); }
  function pct(p) { return p && p.total ? Math.round((100 * p.done) / p.total) : 0; }

  function renderNav() {
    var ol = clear($("chapter-nav"));
    updateModeSwitch();
    requestAnimationFrame(function () {
      var on = ol.querySelector('[aria-current="page"]');
      var nav = ol.parentNode;
      if (!on) return;
      var r = on.getBoundingClientRect(), nr = nav.getBoundingClientRect();
      if (r.left < nr.left || r.right > nr.right) nav.scrollLeft += r.left - nr.left - (nr.width - r.width) / 2;
    });
    if (state.view === "reader") {
      var reading = state.reading || {};
      (state.meta.guide || []).forEach(function (c) {
        ol.appendChild(h("li", null, h("a", { href: "#/read/" + c.id, "aria-current": reading.chapter === c.id ? "page" : null, title: "Chapter " + c.id + ": " + c.title },
          h("span", { class: "num", text: c.id }),
          h("span", { text: guideShort(c) }))));
      });
      return;
    }
    state.meta.lessons.forEach(function (l) {
      var p = pct(l.progress);
      var current = state.lesson && state.lesson.id === l.id;
      ol.appendChild(h("li", null, h("a", { href: "#/" + l.id, "aria-current": current ? "page" : null, title: l.title + " (" + l.progress.done + "/" + l.progress.total + ")" },
        h("span", { class: "ring" + (p === 100 ? " full" : ""), style: "--p:" + p, "aria-hidden": "true" }),
        h("span", { class: "num", text: String(l.number).padStart(2, "0") }),
        h("span", { text: shortTitle(l) }))));
    });
  }
  function guideShort(c) {
    if (c.number === 0) return "Setup";
    var l = lessonMeta("ch" + c.id);
    return l ? shortTitle(l) : c.title;
  }
  function stepAnchor() {
    if (!state.lesson) return "";
    var s = steps()[state.stepIndex];
    return s && s.guide ? s.guide.anchor : "";
  }
  function updateModeSwitch() {
    var lessonA = $("mode-lesson"), readA = $("mode-read");
    var reading = state.view === "reader";
    lessonA.setAttribute("aria-current", reading ? "false" : "page");
    readA.setAttribute("aria-current", reading ? "page" : "false");
    var ch = reading && state.reading ? state.reading.chapter : null;
    if (reading) {
      if (state.readerFrom && ch && state.readerFrom.lesson === "ch" + ch) lessonA.href = state.readerFrom.hash;
      else if (ch && lessonMeta("ch" + ch)) lessonA.href = "#/ch" + ch;
      else lessonA.href = state.lessonHash || "#/";
      readA.href = location.hash || "#/read/00";
    } else {
      lessonA.href = location.hash || "#/";
      if (state.lesson) readA.href = "#/read/" + pad2(state.lesson.number) + (stepAnchor() ? "/" + stepAnchor() : "");
      else readA.href = "#/read/" + store.get("last-read", "00");
    }
  }
  $("mode-read").addEventListener("click", function () {
    if (state.view === "lesson" && state.lesson) rememberLesson(state.lesson.quiz.length ? "Back to the quiz" : "Back to step " + (state.stepIndex + 1) + ": " + steps()[state.stepIndex].title);
  });

  // ------------------------------------------------------------ views: lesson or reader
  function setView(view) {
    var studio = $("studio");
    if (view !== state.view) {
      if (view === "reader") state.lessonScroll = $("lesson").scrollTop;
      state.view = view;
      $("lesson").hidden = view !== "lesson";
      $("reader").hidden = view !== "reader";
      if (view === "lesson") $("lesson").scrollTop = state.lessonScroll || 0;
      var skip = $("skip-main");
      skip.textContent = view === "reader" ? "Skip to the guide" : "Skip to the lesson";
      skip.setAttribute("href", view === "reader" ? "#reader" : "#lesson");
    }
    studio.classList.toggle("reading", view === "reader");
    applyReaderLayout();
  }
  function applyReaderLayout() {
    var studio = $("studio");
    var reading = state.view === "reader";
    var wide = reading && state.readerLayout === "wide";
    studio.classList.toggle("read-wide", wide);
    studio.classList.toggle("read-split", reading && !wide);
    if (Studio.reader) Studio.reader.layoutChanged();
  }
  // `remember`: the learner chose it (the layout button); a split forced by Open in console
  // or by a lesson's Read this section lasts until they leave the reader.
  function setReaderLayout(layout, remember) {
    state.readerLayout = layout === "split" ? "split" : "wide";
    if (remember) store.set("reader-layout", state.readerLayout);
    applyReaderLayout();
  }

  // Load a code block from the guide into a console (never run it: the learner presses Run).
  function openInConsole(consoleId, code) {
    if (!(state.meta.consoles || []).some(function (c) { return c.id === consoleId; })) return;
    if (state.view === "reader" && state.readerLayout === "wide") setReaderLayout("split");
    if (state.active) setActive(null);
    switchConsole(consoleId, true);
    setEditor(code.replace(/\s+$/, ""));
    saveDraft();
    if (window.matchMedia("(max-width: 980px)").matches) $("console-pane").scrollIntoView({ block: "start" });
    editor.focus({ preventScroll: true });
    toast("Loaded into the " + consoleInfo(consoleId).label + " console. Press " + runKeys() + " to run it.");
  }

  var toastTimer = null;
  function toast(text) {
    var t = $("toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 3200);
  }

  function shortTitle(l) {
    return { ch01: "Why NoSQL", ch02: "MongoDB", ch03: "Redis", ch04: "Cassandra", ch05: "DynamoDB", ch06: "Neo4j", ch07: "Capstone", ch08: "Choosing" }[l.id] || l.title;
  }

  function renderHome() {
    if (state.active) setActive(null);
    state.lesson = null;
    renderNav();
    renderTabs();
    renderStatus();
    var inner = clear($("lesson-inner"));
    inner.appendChild(h("div", { class: "lesson-head" },
      h("p", { class: "kicker" }, h("span", { class: "dot", style: "--accent: var(--aqua)" }), "Lesson studio"),
      h("h1", { text: "Learn each database by running it" }),
      h("p", { class: "lede", text: "Every chapter of the guide, step by step, with consoles connected to the real databases on your machine. Run the examples, do the exercises, and check them against the reference solutions." })));
    inner.appendChild(h("div", { class: "panel" },
      h("h3", { text: "How it works" }),
      h("ol", { class: "howto" },
        h("li", { html: md("Start the chapter's database in a terminal: `make up-02` for MongoDB, `make up-capstone up-05` for all of them. The status bar at the bottom shows what is up.") }),
        h("li", { html: md("Open a chapter and press **Prepare data**: it loads that chapter's data with the lab's own code, so your numbers match the guide's.") }),
        h("li", { html: md("Read a step, press **Run this** on an example, then do the exercises in the console on the right and press **Check my answer**.") }),
        h("li", { html: md("Progress is saved in `.studio/progress.json`. `make down` stops the databases when you are done.") }))));
    var cards = h("div", { class: "cards" });
    state.meta.lessons.forEach(function (l) {
      cards.appendChild(h("a", { class: "card " + accentFor(l.id), href: "#/" + l.id },
        h("span", { class: "ch", text: "Chapter " + String(l.number).padStart(2, "0") }),
        h("strong", { text: l.title }),
        h("span", { class: "db", text: l.database }),
        h("span", { class: "prog" }, h("span", { class: "ring" + (pct(l.progress) === 100 ? " full" : ""), style: "--p:" + pct(l.progress), "aria-hidden": "true" }), l.progress.done + " of " + l.progress.total + " done")));
    });
    inner.appendChild(cards);
    var guideList = h("ol", { class: "guide-list" });
    (state.meta.guide || []).forEach(function (c) {
      guideList.appendChild(h("li", null, h("a", { href: "#/read/" + c.id }, h("span", { class: "num", text: c.id }), h("span", { text: c.title }))));
    });
    inner.appendChild(h("div", { class: "panel" },
      h("h3", null, icon("book"), " Prefer to read first?"),
      h("p", { class: "small muted", text: "Every chapter of the guide, rendered here with diagrams, tables and an Open in console button on each database statement. Read is also at the top of the page." }),
      guideList));
    inner.appendChild(h("p", { class: "small muted" }, "The ", h("a", { class: "ext", href: state.meta.explorer, target: "_blank", rel: "noopener noreferrer", text: "explorer" }), " is a companion with simulations of each database (it opens in a new tab)."));
    switchConsole(state.console);
  }

  function accentFor(lessonId) {
    return { ch02: "acc-mongo", ch03: "acc-redis", ch04: "acc-cql", ch05: "acc-dynamodb", ch06: "acc-cypher", ch07: "acc-duckdb" }[lessonId] || "acc-none";
  }

  function openLesson(id, stepId) {
    if (state.lesson && state.lesson.id === id) { showStep(stepId); return Promise.resolve(); }
    return api("/api/lessons/" + id).then(function (lesson) {
      if (state.active) setActive(null);
      state.lesson = lesson;
      store.set("last-lesson", id);
      var target = lesson.consoles.length && lesson.consoles.indexOf(state.console) < 0 ? lesson.consoles[0] : state.console;
      renderNav();
      renderLessonHead();
      showStep(stepId);
      switchConsole(target);
      renderStatus();
    }).catch(function (err) {
      if (err.status === 401) gate("The studio token is missing or stale.");
      else clear($("lesson-inner")).appendChild(h("p", { class: "callout bad", text: err.message }));
    });
  }

  function renderLessonHead() {
    var l = state.lesson;
    var inner = clear($("lesson-inner"));
    inner.className = "lesson-inner " + accentFor(l.id);
    var actions = h("div", { class: "lesson-actions" });
    var prepareOut = h("div", { id: "prepare-out" });
    if (l.has_prepare) {
      var prepBtn = h("button", { type: "button", class: "btn primary", id: "prepare-btn" }, icon("db"), "Prepare data");
      prepBtn.addEventListener("click", function () { prepare(prepBtn, prepareOut); });
      actions.appendChild(prepBtn);
    }
    if (LAB_LESSONS[l.id]) {
      actions.appendChild(h("button", { type: "button", class: "btn", onclick: function () { showJobPanel("lab-" + l.id.slice(2), "Run the whole lab (make lab-" + l.id.slice(2) + ")", []); } }, icon("play"), "Run the whole lab"));
    }
    actions.appendChild(l.guide.chapter === undefined
      ? h("a", { class: "btn ghost", href: String(l.guide.url).split("#")[0], target: "_blank", rel: "noopener noreferrer" }, "Read the chapter", icon("ext"))
      : h("a", { class: "btn ghost", href: "#/read/" + pad2(l.guide.chapter), onclick: function () { rememberLesson("Back to the lesson"); } }, icon("book"), "Read the chapter"));
    var prog = l.progress;
    var head = h("div", { class: "lesson-head" },
      h("p", { class: "kicker" }, h("span", { class: "dot" }), "Chapter " + String(l.number).padStart(2, "0") + " · " + l.database),
      h("h1", { text: l.title }),
      h("p", { class: "lede", text: l.summary }),
      actions,
      l.prepare_note ? h("p", { class: "small muted", id: "prepare-note", text: l.prepare_note + (prog.prepared ? " Last prepared " + new Date(prog.prepared.at).toLocaleString() + "." : " Not prepared yet in this studio.") }) : null,
      prepareOut,
      h("div", { class: "progressline", id: "lesson-progress" }));
    inner.appendChild(head);
    inner.appendChild(h("div", { id: "job-slot" }));
    inner.appendChild(h("ol", { class: "steps", id: "steps", "aria-label": "Steps" }));
    inner.appendChild(h("div", { id: "step" }));
    updateLessonProgress(prog);
  }

  function updateLessonProgress(p) {
    if (!state.lesson) return;
    state.lesson.progress.done = p.done;
    state.lesson.progress.total = p.total;
    var meta = lessonMeta(state.lesson.id);
    if (meta) meta.progress = { done: p.done, total: p.total };
    var el = $("lesson-progress");
    if (el) {
      clear(el).appendChild(h("span", { class: "bar", "aria-hidden": "true" }, h("i", { style: "width:" + pct(p) + "%" })));
      el.appendChild(h("span", { text: p.done + " of " + p.total + (state.lesson.quiz.length ? " questions" : " exercises") + " done" }));
    }
    renderNav();
  }

  function prepare(btn, out) {
    btn.disabled = true;
    var original = btn.innerHTML;
    btn.textContent = "";
    btn.appendChild(h("span", { class: "spinner", "aria-hidden": "true" }));
    btn.appendChild(document.createTextNode(" Preparing..."));
    clear(out);
    api("/api/prepare/" + state.lesson.id, {}).then(function (res) {
      clear(out).appendChild(h("div", { class: "panel tight", role: "status" },
        h("strong", { text: "Prepared in " + res.seconds + " s" }),
        h("ul", { class: "prepare-log" }, res.lines.map(function (line) { return h("li", { text: line }); }))));
      var note = $("prepare-note");
      if (note) note.textContent = state.lesson.prepare_note + " Last prepared just now.";
      state.lesson.progress.prepared = { at: new Date().toISOString(), seconds: res.seconds };
    }).catch(function (err) {
      clear(out).appendChild(h("p", { class: "callout bad", role: "alert", html: md(err.message) }));
    }).finally(function () {
      btn.disabled = false;
      btn.innerHTML = original;
      refreshStatusSoon();
    });
  }

  function steps() {
    var l = state.lesson;
    if (l.quiz.length) return [{ id: "quiz", title: "Quiz" }];
    return l.steps;
  }

  function renderStepChips() {
    var ol = $("steps");
    if (!ol || !state.lesson) return;
    clear(ol);
    var list = steps();
    if (list.length < 2) { ol.hidden = true; return; }
    ol.hidden = false;
    list.forEach(function (s, i) {
      var exs = s.exercises || [];
      var done = exs.length && exs.every(function (x) { return exState(x.id).passed; });
      ol.appendChild(h("li", null, h("button", {
        type: "button", "aria-current": i === state.stepIndex ? "step" : null,
        onclick: function () { location.hash = "#/" + state.lesson.id + "/" + s.id; },
      }, h("span", { class: "n" + (done ? " done" : ""), text: done ? "✓" : String(i + 1) }), s.title)));
    });
  }

  function showStep(stepId) {
    var list = steps();
    var idx = Math.max(0, list.findIndex(function (s) { return s.id === stepId; }));
    state.stepIndex = idx;
    renderStepChips();
    var slot = clear($("step"));
    var l = state.lesson;
    var jobSlot = $("job-slot");
    if (l.jobs.length && !state.jobRunning && jobSlot && !jobSlot.firstChild) {
      l.jobs.forEach(function (j) { showJobPanel(j.id, j.label, j.stages); });
    }
    if (l.quiz.length) { slot.appendChild(renderQuiz()); return; }
    var s = list[idx];
    var body = h("div", { class: "step-body" });
    body.appendChild(h("h2", { text: (idx + 1) + ". " + s.title }));
    body.appendChild(readLink(s.guide, "Read this section: " + s.guide.heading.replace(/`/g, ""), "Back to step " + (idx + 1) + ": " + s.title));
    body.appendChild(h("div", { class: "prose" }, s.prose.map(function (p) { return h("p", { html: md(p) }); })));
    if (s.examples.length) {
      body.appendChild(h("p", { class: "section-label", text: "Run this" }));
      s.examples.forEach(function (ex) {
        body.appendChild(h("div", { class: "example " + (ACCENT[ex.console] || "") },
          h("div", { class: "example-head" },
            h("span", { class: "t" }, h("span", { class: "tag " + (ACCENT[ex.console] || ""), text: consoleInfo(ex.console).label }), h("span", { text: ex.title })),
            h("span", { style: "display:flex;gap:4px" },
              h("button", { type: "button", class: "btn small ghost", text: "Load", "aria-label": "Load into the console: " + ex.title, onclick: function () { loadExample(ex, false); } }),
              h("button", { type: "button", class: "btn small", "aria-label": "Run this: " + ex.title, onclick: function () { loadExample(ex, true); } }, icon("play"), "Run this"))),
          h("pre", { text: ex.code }),
          ex.note ? h("div", { class: "note", html: md(ex.note) }) : null));
      });
    }
    if (s.exercises.length) {
      body.appendChild(h("p", { class: "section-label", text: s.exercises.length === 1 ? "Exercise" : "Exercises" }));
      s.exercises.forEach(function (ex) { body.appendChild(exerciseCard(ex)); });
    }
    var nav = h("div", { class: "step-nav" });
    nav.appendChild(idx > 0 ? h("a", { class: "btn", href: "#/" + l.id + "/" + list[idx - 1].id, text: "← " + list[idx - 1].title }) : h("span"));
    nav.appendChild(idx < list.length - 1 ? h("a", { class: "btn primary", href: "#/" + l.id + "/" + list[idx + 1].id, text: list[idx + 1].title + " →" }) : nextChapterLink());
    body.appendChild(nav);
    slot.appendChild(body);
    var pane = $("lesson");
    if (stepId) { var top = $("steps"); if (top) pane.scrollTop = Math.max(0, top.offsetTop - 16); }
    else pane.scrollTop = 0;
  }

  function pad2(n) { return String(n).padStart(2, "0"); }
  // Remember the lesson step the reader is opened from, so the reader can offer a way back.
  function rememberLesson(label) {
    if (state.view === "lesson" && state.lesson) state.readerFrom = { hash: location.hash || "#/" + state.lesson.id, label: label, lesson: state.lesson.id };
  }
  function readLink(ref, text, backLabel) {
    // A server started before the reader existed sends GitHub URLs only: keep those working.
    if (ref.chapter === undefined) return h("a", { class: "guide-link", href: ref.url, target: "_blank", rel: "noopener noreferrer" }, icon("ext"), text);
    return h("a", {
      class: "guide-link", href: "#/read/" + pad2(ref.chapter) + (ref.anchor ? "/" + ref.anchor : ""),
      onclick: function () { rememberLesson(backLabel); state.readerForceSplit = true; },
    }, icon("book"), text);
  }

  function nextChapterLink() {
    var ids = state.meta.lessons.map(function (l) { return l.id; });
    var i = ids.indexOf(state.lesson.id);
    if (i < 0 || i === ids.length - 1) return h("a", { class: "btn", href: "#/", text: "Back to all chapters" });
    var next = state.meta.lessons[i + 1];
    return h("a", { class: "btn primary", href: "#/" + next.id, text: "Chapter " + next.number + ": " + shortTitle(next) + " →" });
  }

  // ------------------------------------------------------------ quiz
  function renderQuiz() {
    var l = state.lesson;
    var given = l.progress.quiz || {};
    var form = h("form", { class: "quiz", onsubmit: function (e) { e.preventDefault(); submitQuiz(form); } });
    form.appendChild(h("h2", { text: "Quiz" }));
    form.appendChild(readLink(l.guide.chapter === undefined ? { url: String(l.guide.url).split("#")[0] } : { chapter: l.guide.chapter, anchor: "" }, "Read the chapter first: " + l.guide.file, "Back to the quiz"));
    form.appendChild(h("p", { class: "prose", html: md("The same questions as `make check-" + String(l.number).padStart(2, "0") + "`, with the same explanations. No database needed.") }));
    l.quiz.forEach(function (q) {
      var fs = h("fieldset", null, h("legend", null, h("span", { class: "num", text: q.id }), h("span", { text: q.question })));
      q.options.forEach(function (o) {
        var input = h("input", { type: "radio", name: "q-" + q.id, value: o[0], checked: given[q.id] && given[q.id].answer === o[0] ? true : null });
        fs.appendChild(h("label", { class: "quiz-opt" }, input, h("span", { class: "letter", text: o[0] + ")" }), h("span", { text: o[1] })));
      });
      var why = h("div", { class: "quiz-why", id: "why-" + q.id, "aria-live": "polite" });
      if (given[q.id]) drawWhy(why, { answered: true, ok: given[q.id].correct, why: given[q.id].correct ? "" : "" }, true);
      form.appendChild(h("div", { class: "quiz-q" }, fs, why));
    });
    form.appendChild(h("div", { class: "lesson-actions" }, h("button", { type: "submit", class: "btn primary", text: "Check my answers" })));
    return form;
  }
  function drawWhy(slot, r, restored) {
    clear(slot);
    if (!r.answered) { slot.appendChild(h("p", { class: "small muted", text: "Not answered yet." })); return; }
    var v = h("div", { class: "verdict " + (r.ok ? "pass" : "fail") },
      h("div", { class: "verdict-head" }, h("span", { class: "badge " + (r.ok ? "pass" : "fail"), text: r.ok ? "PASS" : "FAIL" }), h("span", { text: r.why || (restored ? (r.ok ? "Answered correctly earlier." : "Answered earlier; not right yet.") : "") })));
    slot.appendChild(v);
  }
  function submitQuiz(form) {
    var answers = {};
    state.lesson.quiz.forEach(function (q) {
      var picked = form.querySelector('input[name="q-' + q.id + '"]:checked');
      if (picked) answers[q.id] = picked.value;
    });
    api("/api/quiz/" + state.lesson.id, { answers: answers }).then(function (res) {
      Object.keys(res.results).forEach(function (qid) { drawWhy(document.getElementById("why-" + qid), res.results[qid]); });
      state.lesson.progress.quiz = res.progress.quiz;
      updateLessonProgress(res.progress);
    }).catch(function (err) { form.appendChild(h("p", { class: "callout bad", role: "alert", text: err.message })); });
  }

  // ------------------------------------------------------------ jobs (capstone, labs)
  function showJobPanel(jobId, label, stages) {
    var slot = $("job-slot");
    if (!slot) return;
    var existing = document.getElementById("job-" + jobId);
    if (existing) { existing.scrollIntoView({ block: "nearest" }); return; }
    var list = h("ol", { class: "stages" });
    stages.forEach(function (s) { list.appendChild(h("li", { "data-marker": s[0], text: s[1] })); });
    var log = h("pre", { class: "log", hidden: true, tabindex: "0", "aria-label": "Job output" });
    var status = h("span", { class: "small muted", text: "" });
    var btn = h("button", { type: "button", class: "btn primary" }, icon("play"), label);
    var panel = h("div", { class: "job", id: "job-" + jobId },
      h("div", { style: "display:flex;align-items:center;gap:10px;flex-wrap:wrap" }, btn, status),
      stages.length ? list : h("ol", { class: "stages" }),
      log);
    btn.addEventListener("click", function () { runJob(jobId, btn, panel.querySelector(".stages"), log, status, !stages.length); });
    slot.appendChild(panel);
  }

  function runJob(jobId, btn, list, log, status, dynamicStages) {
    if (state.jobRunning) return;
    state.jobRunning = true;
    btn.disabled = true;
    log.hidden = false;
    log.textContent = "";
    if (dynamicStages) clear(list);
    Array.prototype.forEach.call(list.children, function (li) { li.className = ""; });
    status.textContent = "running...";
    var started = performance.now();
    var current = null;
    function mark(line) {
      var items = Array.prototype.slice.call(list.children);
      if (dynamicStages) {
        var m = /^--- Step ([\d.]+): (.*) ---$/.exec(line.trim());
        if (m) {
          if (current) current.className = "done";
          current = h("li", { class: "running", text: m[1] + " " + m[2] });
          list.appendChild(current);
        }
        return;
      }
      items.forEach(function (li) {
        if (line.indexOf(li.getAttribute("data-marker")) === 0 || line.trim() === li.getAttribute("data-marker")) {
          if (current && current !== li) current.className = "done";
          li.className = "running";
          current = li;
        }
      });
    }
    api("/api/jobs/" + jobId, {}, true).then(function (res) {
      if (!res.ok) return res.text().then(function (t) { var d; try { d = JSON.parse(t).detail; } catch (e) { d = t; } throw new Error(d); });
      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      function pump() {
        return reader.read().then(function (chunk) {
          if (chunk.done) return;
          buffer += decoder.decode(chunk.value, { stream: true });
          var lines = buffer.split("\n");
          buffer = lines.pop();
          lines.forEach(function (line) {
            mark(line);
            log.textContent += line + "\n";
            var m = /\[exit code (\d+)/.exec(line);
            if (m) {
              if (current) current.className = m[1] === "0" ? "done" : "";
              status.textContent = m[1] === "0" ? "finished: exit code 0" : "failed: exit code " + m[1] + " (read the output)";
            }
          });
          log.scrollTop = log.scrollHeight;
          return pump();
        });
      }
      return pump();
    }).catch(function (err) {
      log.textContent += "\n" + err.message + "\n";
      status.textContent = "could not run";
    }).finally(function () {
      state.jobRunning = false;
      btn.disabled = false;
      if (status.textContent === "running...") status.textContent = "stopped after " + ((performance.now() - started) / 1000).toFixed(1) + " s";
      refreshStatusSoon();
    });
  }

  // ------------------------------------------------------------ status bar
  var statusTimer = null;
  function refreshStatus() {
    if (document.hidden) return Promise.resolve();
    return api("/api/status").then(function (res) { state.status = res.services; renderStatus(); }).catch(function () {});
  }
  function refreshStatusSoon() { clearTimeout(statusTimer); statusTimer = setTimeout(refreshStatus, 400); }
  function renderStatus() {
    var bar = clear($("statusbar"));
    var needed = state.lesson ? state.lesson.services : [];
    state.status.forEach(function (s) {
      var isNeeded = needed.indexOf(s.id) >= 0;
      var text = s.up ? (s.detail ? s.detail : "up") : "down";
      var item = h("span", { class: "svc " + (s.up ? "up" : "down") + (isNeeded ? " needed" : ""), title: s.label + (s.port ? " on port " + s.port : "") + ": " + text + (s.up ? "" : ". Start it with " + s.make) },
        h("span", { class: "led", "aria-hidden": "true" }), h("span", { text: s.label }), h("span", { class: "visually-hidden", text: " is " + text }),
        !s.up ? h("span", { class: "make", text: s.make }) : s.detail ? h("span", { class: "make", text: s.detail }) : null);
      bar.appendChild(item);
    });
    bar.appendChild(h("span", { class: "right", text: "studio " + (state.meta ? state.meta.version : "") + " · 127.0.0.1" }));
  }

  // ------------------------------------------------------------ routing
  function route() {
    var parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
    if (parts[0] === "read" || parts[0] === "file") {
      if (state.view !== "reader") state.readerLayout = state.readerForceSplit ? "split" : store.get("reader-layout", "wide") === "split" ? "split" : "wide";
      state.readerForceSplit = false;
      setView("reader");
      if (parts[0] === "read") Studio.reader.open(parts[1] || "00", parts.slice(2).join("/"));
      else Studio.reader.openFile(parts.slice(1).join("/"));
      return;
    }
    var back = state.view === "reader" && state.lessonHash === location.hash && state.lessonHash !== "#/";
    setView("lesson");
    document.title = "NoSQL lesson studio";
    if (back && state.lesson) { renderNav(); return; } // the lesson is still in the page, as it was left
    state.lessonHash = location.hash || "#/";
    if (!parts.length) { renderHome(); return; }
    if (!lessonMeta(parts[0])) { location.hash = "#/"; return; }
    openLesson(parts[0], parts[1]);
  }
  window.addEventListener("hashchange", route);
  document.querySelectorAll(".skip-link").forEach(function (a) {
    a.addEventListener("click", function (e) {
      var target = document.getElementById(a.getAttribute("href").slice(1));
      if (!target) return;
      e.preventDefault();
      target.focus();
    });
  });

  // ------------------------------------------------------------ shared with reader.js
  var Studio = window.NosqlStudio = window.NosqlStudio || {};
  Studio.h = h;
  Studio.clear = clear;
  Studio.api = api;
  Studio.icon = icon;
  Studio.store = store;
  Studio.state = state;
  Studio.toast = toast;
  Studio.gate = gate;
  Studio.renderNav = renderNav;
  Studio.setReaderLayout = setReaderLayout;
  Studio.openInConsole = openInConsole;
  Studio.consoleInfo = function (id) { return consoleInfo(id); };
  Studio.lessonMeta = lessonMeta;
  Studio.guideShort = guideShort;

  // ------------------------------------------------------------ start
  updateThemeButton();
  if (!TOKEN) {
    gate("This page needs the token from the studio's start URL.");
    return;
  }
  api("/api/meta").then(function (meta) {
    state.meta = meta;
    $("link-explorer").href = meta.explorer;
    state.console = store.get("console", "mongo");
    if (!location.hash) {
      var last = store.get("last-lesson", null);
      if (last && lessonMeta(last)) location.hash = "#/" + last;
    }
    route();
    refreshStatus();
    setInterval(refreshStatus, 5000);
    window.addEventListener("beforeunload", function () { saveDraft(); });
  }).catch(function (err) {
    if (err.status === 401) gate("The studio token is missing or stale: the server makes a new one every time it starts.");
    else gate("The studio server did not answer (" + err.message + "). Is make studio still running?");
  });
})();
