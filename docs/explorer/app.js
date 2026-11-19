/* NoSQL explorer. Vanilla JS, no modules, no network: works from file:// and GitHub Pages.
 * Data comes from data.js (window.EXPLORER_DATA), built by tools/build_explorer_data.py. */
(function () {
  "use strict";

  var D = window.EXPLORER_DATA;
  if (!D) {
    document.getElementById("main").insertAdjacentHTML(
      "afterbegin",
      '<p class="wrap">data.js did not load. Run <code>make explorer-data</code> and reload.</p>'
    );
    return;
  }

  // ------------------------------------------------------------------ helpers
  var REC = {};
  D.recorded.forEach(function (r) { REC[r.id] = r; });
  function rv(id, name) {
    var r = REC[id];
    if (!r) throw new Error("no recorded value " + id);
    return r.values[name || "value"];
  }
  function rn(id, name) { return Number(String(rv(id, name)).replace(/,/g, "")); }
  function fmt(n) { return Number(n).toLocaleString("en-US"); }
  function fmt1(n) { return Number(n).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }); }
  function pct(x, digits) { return (x * 100).toFixed(digits == null ? 1 : digits) + "%"; }
  function ts(iso) { return String(iso).replace("T", " ").replace(/\+00:00$/, ""); }
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v == null || v === false) return;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "style") el.setAttribute("style", v);
        else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
        else if (v === true) el.setAttribute(k, "");
        else el.setAttribute(k, v);
      });
    }
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(el, kid) {
    if (kid == null || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (k) { append(el, k); }); return; }
    el.appendChild(typeof kid === "object" ? kid : document.createTextNode(String(kid)));
  }
  var SVGNS = "http://www.w3.org/2000/svg";
  function s(tag, attrs) {
    var el = document.createElementNS(SVGNS, tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v == null) return;
      if (k === "text") el.textContent = v;
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v);
    });
    for (var i = 2; i < arguments.length; i++) if (arguments[i]) el.appendChild(arguments[i]);
    return el;
  }
  function $(id) { return document.getElementById(id); }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function code(t) { return h("code", null, t); }
  function animateIn(el) {
    if (reduceMotion) return;
    el.classList.remove("panel-enter");
    void el.offsetWidth;
    el.classList.add("panel-enter");
  }
  function extLink(key, text) {
    return h("a", { href: D.links[key], target: "_blank", rel: "noopener" }, text);
  }
  function fnv(str) {
    var x = 0x811c9dc5;
    for (var i = 0; i < str.length; i++) {
      x ^= str.charCodeAt(i);
      x = Math.imul(x, 0x01000193) >>> 0;
    }
    return x >>> 0;
  }
  // A radio group of buttons with roving focus and arrow-key support.
  function radioGroup(container, options, current, onChange) {
    clear(container);
    var buttons = options.map(function (o) {
      var b = h("button", { type: "button", role: "radio", "aria-checked": String(o.value === current), tabindex: o.value === current ? "0" : "-1" }, o.label);
      b.addEventListener("click", function () { select(o.value, true); });
      container.appendChild(b);
      return b;
    });
    function select(value, fire) {
      options.forEach(function (o, i) {
        var on = o.value === value;
        buttons[i].setAttribute("aria-checked", String(on));
        buttons[i].setAttribute("tabindex", on ? "0" : "-1");
      });
      if (fire) onChange(value);
    }
    container.addEventListener("keydown", function (e) {
      var idx = buttons.indexOf(document.activeElement);
      if (idx < 0) return;
      var next = null;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") next = (idx + 1) % buttons.length;
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = (idx - 1 + buttons.length) % buttons.length;
      if (next == null) return;
      e.preventDefault();
      buttons[next].focus();
      select(options[next].value, true);
    });
    return { set: function (v) { select(v, false); } };
  }

  // ------------------------------------------------------------------ links, theme, nav
  document.querySelectorAll("[data-link]").forEach(function (a) {
    a.href = D.links[a.getAttribute("data-link")];
    a.target = "_blank";
    a.rel = "noopener";
  });
  $("cta-start").href = D.links.setup;
  $("cta-repo").href = D.links.repo;
  $("foot-repo").href = D.links.repo;
  [$("cta-start"), $("cta-repo"), $("foot-repo")].forEach(function (a) { a.target = "_blank"; a.rel = "noopener"; });

  var SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6"/></svg>';
  var MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7Z"/></svg>';
  function currentTheme() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  function paintToggle() {
    var t = currentTheme();
    var btn = $("theme-toggle");
    btn.innerHTML = t === "dark" ? SUN : MOON;
    btn.setAttribute("aria-label", t === "dark" ? "Switch to light theme" : "Switch to dark theme");
  }
  $("theme-toggle").addEventListener("click", function () {
    var next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("nosql-explorer-theme", next); } catch (e) { /* storage may be blocked */ }
    paintToggle();
  });
  paintToggle();

  (function navSpy() {
    var links = Array.prototype.slice.call(document.querySelectorAll(".nav a"));
    if (!("IntersectionObserver" in window)) return;
    var byId = {};
    links.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        links.forEach(function (a) { a.removeAttribute("aria-current"); });
        var a = byId[en.target.id];
        if (a) {
          a.setAttribute("aria-current", "true");
          var nav = a.closest(".nav");
          if (nav && nav.scrollWidth > nav.clientWidth) nav.scrollTo({ left: a.offsetLeft - 24, behavior: reduceMotion ? "auto" : "smooth" });
        }
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    Object.keys(byId).forEach(function (id) { var el = $(id); if (el) obs.observe(el); });
  })();

  // ------------------------------------------------------------------ tooltip
  var tip = $("tooltip");
  function showTip(target, content, evt) {
    clear(tip);
    append(tip, content);
    tip.classList.add("show");
    var x, y;
    if (evt && evt.clientX != null && evt.type.indexOf("mouse") === 0) { x = evt.clientX; y = evt.clientY; }
    else { var r = target.getBoundingClientRect(); x = r.left + r.width / 2; y = r.top; }
    var tw = tip.offsetWidth, th = tip.offsetHeight;
    var left = Math.min(Math.max(8, x - tw / 2), window.innerWidth - tw - 8);
    var top = y - th - 12;
    if (top < 8) top = y + 18;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  function hideTip() { tip.classList.remove("show"); }
  function withTip(el, contentFn) {
    el.addEventListener("mouseenter", function (e) { showTip(el, contentFn(), e); });
    el.addEventListener("mousemove", function (e) { showTip(el, contentFn(), e); });
    el.addEventListener("mouseleave", hideTip);
    el.addEventListener("focus", function () { showTip(el, contentFn()); });
    el.addEventListener("blur", hideTip);
  }
  window.addEventListener("scroll", hideTip, { passive: true });

  // ------------------------------------------------------------------ charts
  // Horizontal bars. groups: [{label, bars: [{series, value, display, tip}]}].
  // series: [{key, label, color}]. One series: no legend (the title names it).
  function barChart(target, opt) {
    clear(target);
    var series = opt.series;
    var byKey = {};
    series.forEach(function (sr) { byKey[sr.key] = sr; });
    var max = opt.max || 0;
    opt.groups.forEach(function (g) { g.bars.forEach(function (b) { max = Math.max(max, b.value); }); });
    if (max <= 0) max = 1;
    var root = h("figure", { class: "chart", style: "margin:0" });
    if (opt.title) root.appendChild(h("p", { class: "chart-title" }, opt.title));
    if (opt.sub) root.appendChild(h("p", { class: "chart-sub" }, opt.sub));
    if (series.length > 1) {
      root.appendChild(h("ul", { class: "chart-legend", "aria-label": "Legend" },
        series.map(function (sr) { return h("li", null, h("span", { class: "sw", style: "--series:" + sr.color }), sr.label); })));
    }
    var list = h("div", { class: "bars", role: "list", "aria-label": opt.ariaLabel || opt.title || "Bar chart" });
    opt.groups.forEach(function (g) {
      g.bars.forEach(function (b, i) {
        var sr = byKey[b.series];
        var label = i === 0 ? g.label : "";
        var aria = g.label + (series.length > 1 ? ", " + sr.label : "") + ": " + b.display;
        var row = h("div", { class: "bar-row", role: "listitem", tabindex: "0", "aria-label": aria },
          h("span", { class: "bar-label", title: g.label, "aria-hidden": "true" }, label),
          h("span", { class: "bar-track", "aria-hidden": "true" },
            h("span", { class: "bar", style: "--series:" + sr.color + ";width:calc((100% - 96px) * " + (b.value / max).toFixed(5) + ")" }),
            h("span", { class: "bar-val" }, b.display)));
        if (i > 0) row.style.marginTop = "-6px";
        withTip(row, function () {
          return [h("b", null, g.label), series.length > 1 ? h("div", null, sr.label + ": " + b.display) : h("div", null, b.display), b.tip ? h("div", null, b.tip) : null];
        });
        list.appendChild(row);
      });
    });
    root.appendChild(list);
    if (opt.caption) root.appendChild(h("figcaption", { class: "small muted", style: "margin-top:8px" }, opt.caption));
    target.appendChild(root);
    // Text equivalent.
    var head = ["", ].concat(series.map(function (sr) { return sr.label; }));
    head[0] = opt.tableFirst || "";
    if (opt.extraCols) head = head.concat(opt.extraCols.map(function (c) { return c.label; }));
    var rows = opt.groups.map(function (g) {
      var cells = [g.label];
      series.forEach(function (sr) {
        var b = g.bars.filter(function (x) { return x.series === sr.key; })[0];
        cells.push(b ? b.display : "");
      });
      if (opt.extraCols) opt.extraCols.forEach(function (c) { cells.push(c.get(g)); });
      return cells;
    });
    target.appendChild(tableDetails(head, rows));
  }
  function tableDetails(head, rows) {
    var t = h("table", { class: "data" },
      h("thead", null, h("tr", null, head.map(function (c, i) { return h("th", { scope: "col", class: i ? "num" : null }, c); }))),
      h("tbody", null, rows.map(function (r) {
        return h("tr", null, r.map(function (c, i) { return i ? h("td", { class: "num" }, c) : h("th", { scope: "row", style: "font-weight:500" }, c); }));
      })));
    return h("details", { class: "as-table" }, h("summary", null, "Show as a table"), h("div", { class: "table-scroll" }, t));
  }
  var C = { blue: "var(--blue)", orange: "var(--orange)", aqua: "var(--aqua)", violet: "var(--violet)" };
  var READ_VS = [{ key: "read", label: "read", color: C.blue }, { key: "returned", label: "returned", color: C.orange }];

  // ------------------------------------------------------------------ hero
  (function hero() {
    var dbs = [
      { name: "MongoDB", fam: "document", ch: 2, accent: "--mongo" },
      { name: "Redis", fam: "key-value, in memory", ch: 3, accent: "--redis" },
      { name: "Cassandra", fam: "wide-column", ch: 4, accent: "--cass" },
      { name: "DynamoDB", fam: "key-value, managed", ch: 5, accent: "--dynamo" },
      { name: "Neo4j", fam: "graph", ch: 6, accent: "--neo" }
    ];
    var row = $("db-row");
    dbs.forEach(function (d) {
      row.appendChild(h("a", { class: "db-card", href: D.links["ch" + d.ch], target: "_blank", rel: "noopener", style: "--accent: var(" + d.accent + ")" },
        h("span", { class: "ch" }, "Chapter " + d.ch),
        h("strong", null, d.name),
        h("span", { class: "fam" }, d.fam)));
    });
    var st = $("hero-stats");
    [[fmt(D.summary.applications), "applications"], [fmt(D.summary.payment_events), "payment events"],
     [String(D.summary.fraud_rings), "planted fraud rings"], [rv("rc_summary", "ok"), "reconciliations OK"]]
      .forEach(function (p) { st.appendChild(h("div", null, h("b", null, p[0]), h("span", null, p[1]))); });
  })();

  // ------------------------------------------------------------------ shapes
  var S = D.sample;
  function cell(v) {
    if (v === null || v === undefined) return h("span", { class: "muted" }, "NULL");
    if (typeof v === "boolean") return String(v);
    if (typeof v === "number") return String(v);
    if (/^\d{4}-\d\d-\d\dT/.test(v)) return ts(v);
    return String(v);
  }
  function dataTable(columns, rows, opts) {
    opts = opts || {};
    var t = h("table", { class: "data" },
      h("thead", null, h("tr", null, columns.map(function (c) {
        var cls = (opts.pk && opts.pk.indexOf(c) > -1) ? "col-pk" : (opts.ck && opts.ck.indexOf(c) > -1) ? "col-ck" : null;
        return h("th", { scope: "col", class: cls }, c, opts.chips && opts.chips[c] ? h("span", { class: "key-chip" }, opts.chips[c]) : null);
      }))),
      h("tbody", null, rows.length ? rows.map(function (r) {
        var tr = h("tr", { class: opts.highlight && opts.highlight(r) ? "row-hl" : null });
        columns.forEach(function (c) {
          var cls = (opts.pk && opts.pk.indexOf(c) > -1) ? "col-pk" : (opts.ck && opts.ck.indexOf(c) > -1) ? "col-ck" : "";
          var v = opts.format && opts.format[c] ? opts.format[c](r[c]) : cell(r[c]);
          tr.appendChild(h("td", { class: (cls + (typeof r[c] === "number" ? " num" : "")).trim() || null }, v));
        });
        return tr;
      }) : h("tr", { class: "empty-row" }, h("td", { colspan: String(columns.length) }, "0 rows: an approved application has no decline reasons"))));
    return t;
  }

  function renderSql(stage) {
    var grid = h("div", { class: "sql-grid" });
    S.sql.forEach(function (tb) {
      var wide = tb.name === "payments" || tb.name === "applications" || tb.name === "loans";
      var chips = {};
      Object.keys(tb.keys).forEach(function (k) { chips[k] = tb.keys[k]; });
      var scroll = h("div", { class: "table-scroll" + (tb.name === "payments" ? " tall" : "") }, dataTable(tb.columns, tb.rows, { chips: chips }));
      grid.appendChild(h("section", { class: "tbl-card" + (wide ? " wide" : ""), "aria-label": "Table " + tb.name },
        h("header", null, tb.name, h("span", null, tb.rows.length + (tb.rows.length === 1 ? " row" : " rows"))), scroll));
    });
    stage.appendChild(grid);
  }

  function jsonNode(key, value, depth, isLast) {
    var li = h("li");
    var keyEl = key != null ? [h("span", { class: "jk" }, typeof key === "number" ? "" : '"' + key + '"'), typeof key === "number" ? "" : ": "] : null;
    var comma = isLast ? "" : ",";
    if (value !== null && typeof value === "object") {
      var isArr = Array.isArray(value);
      var entries = isArr ? value.map(function (v, i) { return [i, v]; }) : Object.keys(value).map(function (k) { return [k, value[k]]; });
      var open = isArr ? "[" : "{", close = isArr ? "]" : "}";
      var btn = h("button", { class: "jt", type: "button", "aria-expanded": "true", "aria-label": (key != null && typeof key !== "number" ? key : "item") + ", collapse" }, "▾");
      var ul = h("ul");
      entries.forEach(function (e, i) { ul.appendChild(jsonNode(isArr ? i : e[0], e[1], depth + 1, i === entries.length - 1)); });
      var summary = h("span", { class: "jsum", hidden: true }, " " + (isArr ? entries.length + (entries.length === 1 ? " item " : " items ") : entries.length + " fields ") + close + comma);
      var tail = h("div", null, close + comma);
      btn.addEventListener("click", function () {
        var exp = btn.getAttribute("aria-expanded") === "true";
        setJson(btn, ul, summary, tail, !exp);
      });
      btn._set = function (on) { setJson(btn, ul, summary, tail, on); };
      li.appendChild(h("span", null, btn, keyEl, open, isArr ? h("span", { class: "jtype" }, "array") : null, summary));
      li.appendChild(ul);
      li.appendChild(tail);
      if (entries.length === 0) { ul.hidden = true; }
      return li;
    }
    var cls = value === null ? "jnull" : typeof value === "string" ? "js" : typeof value === "number" ? "jn" : "jb";
    var text = value === null ? "null" : typeof value === "string" ? '"' + value + '"' : String(value);
    li.appendChild(h("span", { style: "padding-left:16px" }, keyEl, h("span", { class: cls }, text), comma));
    return li;
  }
  function setJson(btn, ul, summary, tail, on) {
    btn.setAttribute("aria-expanded", String(on));
    btn.textContent = on ? "▾" : "▸";
    btn.setAttribute("aria-label", btn.getAttribute("aria-label").replace(/, (collapse|expand)$/, on ? ", collapse" : ", expand"));
    ul.hidden = !on;
    tail.hidden = !on;
    summary.hidden = on;
  }
  function renderMongo(stage) {
    var box = h("div", { class: "json", role: "group", "aria-label": "MongoDB document " + S.application_id });
    var root = h("ul");
    root.appendChild(jsonNode(null, S.document, 0, true));
    box.appendChild(root);
    function all(on) { box.querySelectorAll("button.jt").forEach(function (b, i) { if (i > 0 || on) b._set(on); }); }
    stage.appendChild(h("div", { class: "json-tools" },
      h("button", { class: "btn small", type: "button", onclick: function () { all(true); } }, "Expand all"),
      h("button", { class: "btn small", type: "button", onclick: function () { all(false); } }, "Collapse nested"),
      h("span", { class: "small muted", style: "align-self:center" }, "collection ", code("applications"), ", one document, " + Object.keys(S.document).length + " top-level fields")));
    stage.appendChild(box);
  }

  function renderRedis(stage) {
    var list = h("div", { class: "keys" });
    S.redis.forEach(function (k) {
      var body;
      if (k.type === "string") body = h("div", null, '"' + k.value + '"');
      else if (k.type === "hash") body = h("div", null, Object.keys(k.value).map(function (f) { return h("div", null, f + "  ", h("b", null, '"' + k.value[f] + '"')); }));
      else if (k.type === "sorted set") body = h("div", null, k.value.map(function (m) { return h("div", null, m[0] + "  score " + m[1] + "  ", h("span", { class: "muted" }, "(one member of many)")); }));
      else body = h("div", null, k.value.map(function (e) {
        return h("div", null, h("span", { class: "muted" }, "<ms>-<seq>  "), Object.keys(e).map(function (f) { return f + " " + e[f] + "  "; }));
      }), h("div", { class: "muted" }, "(the last 3 deliveries for this loan; ids are timestamps)"));
      var ttl = k.ttl === -1 ? "TTL -1: never expires" : "TTL " + fmt(k.ttl) + " s (" + Math.round(k.ttl / 86400) + " days)";
      list.appendChild(h("article", { class: "keycard" },
        h("header", null, h("code", { class: "key" }, k.key), h("span", { class: "ctl" }, h("span", { class: "badge" }, k.type), h("span", { class: "small muted mono" }, ttl))),
        h("div", { class: "body" }, body),
        h("div", { class: "cmd" }, "> " + k.command)));
    });
    stage.appendChild(list);
  }

  function renderCassandra(stage) {
    var c = S.cassandra;
    var fmtRow = { event_time: function (v) { return ts(v); }, amount_cents: function (v) { return fmt(v); } };
    [c.by_loan, c.by_day].forEach(function (p) {
      var pk = p.partition_key, ck = ["event_time", "event_id"];
      var isDay = p.table === "payments_by_day";
      var header = h("header", null,
        h("b", null, p.table),
        h("span", { class: "small muted" }, "partition ", code(pk[0] + " = '" + p.partition + "'"), ", " + (isDay ? p.rows_total : p.rows.length) + " rows, clustered by " + p.clustering.join(", ")));
      var cols = pk.concat(ck, c.columns.filter(function (x) { return pk.indexOf(x) < 0 && ck.indexOf(x) < 0; }));
      var t = dataTable(cols, p.rows, {
        pk: pk, ck: ck, format: fmtRow,
        chips: (function () { var o = {}; o[pk[0]] = "partition"; o.event_time = "clustering"; o.event_id = "clustering"; return o; })(),
        highlight: isDay ? function (r) { return r.loan_id === S.loan_id; } : null
      });
      stage.appendChild(h("section", { class: "partition", "aria-label": p.table },
        header, h("div", { class: "table-scroll" + (isDay ? " tall" : "") }, t)));
    });
    stage.appendChild(h("ul", { class: "legend", style: "--accent: var(--cass)" },
      h("li", null, h("span", { class: "sw pk" }), "partition key: decides the nodes"),
      h("li", null, h("span", { class: "sw ck" }), "clustering key: sorts rows inside the partition"),
      h("li", null, h("span", { class: "sw", style: "border:1px solid var(--text)" }), "the same payment, stored in both tables")));
  }

  var ddbSel = "AP2";
  function renderDynamo(stage, side) {
    var items = S.dynamodb.items.slice().sort(function (a, b) {
      if (a.PK !== b.PK) return a.PK < b.PK ? -1 : 1;
      return a.SK < b.SK ? -1 : a.SK > b.SK ? 1 : 0;
    });
    var pat = {
      AP2: { label: "AP2: a borrower's applications and loans", hit: function (i) { return i.PK === "BORROWER#" + S.borrower_id; }, rec: "dd_ap2",
        code: 'table.query(\n    KeyConditionExpression=\n        Key("PK").eq("BORROWER#' + S.borrower_id + '"),\n)' },
      AP3: { label: "AP3: a loan's payments, March to June", hit: function (i) { return i.PK === "LOAN#" + S.loan_id && i.SK >= "PAYMENT#2025-03" && i.SK <= "PAYMENT#2025-07"; }, rec: "dd_ap3",
        code: 'table.query(\n    KeyConditionExpression=\n        Key("PK").eq("LOAN#' + S.loan_id + '")\n        & Key("SK").between(\n            "PAYMENT#2025-03",\n            "PAYMENT#2025-07"),\n)' }
    };
    var segWrap = h("div", { class: "seg", role: "radiogroup", "aria-label": "Access pattern", style: "margin-bottom:12px" });
    var tableWrap = h("div", { class: "table-scroll" });
    var countEl = h("p", { class: "small muted", style: "margin:10px 0 0" });
    function draw() {
      var p = pat[ddbSel];
      var hits = items.filter(p.hit).length;
      var tbody = h("tbody");
      var lastPk = null;
      items.forEach(function (it) {
        var attrs = Object.keys(it).filter(function (k) { return k !== "PK" && k !== "SK"; });
        var tr = h("tr", { class: (it.PK !== lastPk ? "grp-start " : "") + (p.hit(it) ? "row-hl" : "") });
        tr.appendChild(h("td", { class: "mono col-pk pkcell" }, it.PK !== lastPk ? it.PK : ""));
        tr.appendChild(h("td", { class: "mono col-ck skcell" }, it.SK));
        tr.appendChild(h("td", { class: "attrs" }, attrs.map(function (k) {
          return h("span", null, h("b", null, k + " "), String(it[k]), k === "GSI1PK" ? h("span", { class: "key-chip" }, "GSI1") : null);
        })));
        tbody.appendChild(tr);
        lastPk = it.PK;
      });
      clear(tableWrap).appendChild(h("table", { class: "data ddb-grid", style: "--accent: var(--dynamo)" },
        h("thead", null, h("tr", null, h("th", { class: "col-pk", scope: "col" }, "PK", h("span", { class: "key-chip" }, "partition")),
          h("th", { class: "col-ck", scope: "col" }, "SK", h("span", { class: "key-chip" }, "sort")), h("th", { scope: "col" }, "attributes"))),
        tbody));
      countEl.textContent = "This Query returns the " + hits + " highlighted items. The lab measured Count " + rv(p.rec, "count") + ", " + rv(p.rec, "rcu") + " RCU (step 5.3).";
      if (side) { clear(side.query).appendChild(document.createTextNode(p.code)); }
    }
    radioGroup(segWrap, [{ value: "AP2", label: pat.AP2.label }, { value: "AP3", label: pat.AP3.label }], ddbSel, function (v) { ddbSel = v; draw(); });
    stage.appendChild(segWrap);
    stage.appendChild(tableWrap);
    stage.appendChild(countEl);
    stage.appendChild(h("p", { class: "small muted", style: "margin-top:6px" }, "Items in an item collection are sorted by SK as strings, which is why ISO timestamps in the key make a date range a BETWEEN."));
    draw();
  }

  // Graph view: deterministic force layout, then SVG.
  var graphMode = "ring", showPath = false;
  function layoutGraph(nodes, edges, W, H) {
    var n = nodes.length, idx = {};
    nodes.forEach(function (nd, i) {
      idx[nd.id] = i;
      var a = (i / n) * Math.PI * 2;
      var r = Math.min(W, H) * (nd.label === "Application" ? 0.22 : 0.38);
      nd.x = W / 2 + Math.cos(a) * r;
      nd.y = H / 2 + Math.sin(a) * r;
    });
    var k = Math.sqrt((W * H) / n) * 0.85;
    for (var it = 0; it < 600; it++) {
      var temp = Math.max(0.5, (W / 10) * (1 - it / 600));
      var dx = new Float64Array(n), dy = new Float64Array(n);
      for (var i = 0; i < n; i++) for (var j = i + 1; j < n; j++) {
        var ex = nodes[i].x - nodes[j].x, ey = nodes[i].y - nodes[j].y;
        var d = Math.max(Math.sqrt(ex * ex + ey * ey), 0.01), f = (k * k) / d;
        dx[i] += (ex / d) * f; dy[i] += (ey / d) * f; dx[j] -= (ex / d) * f; dy[j] -= (ey / d) * f;
      }
      edges.forEach(function (e) {
        var a = idx[e.from], b = idx[e.to];
        var ex = nodes[a].x - nodes[b].x, ey = nodes[a].y - nodes[b].y;
        var d = Math.max(Math.sqrt(ex * ex + ey * ey), 0.01), f = (d * d) / k;
        dx[a] -= (ex / d) * f; dy[a] -= (ey / d) * f; dx[b] += (ex / d) * f; dy[b] += (ey / d) * f;
      });
      for (i = 0; i < n; i++) {
        dx[i] += (W / 2 - nodes[i].x) * 0.04 * k / 10;
        dy[i] += (H / 2 - nodes[i].y) * 0.04 * k / 10;
        var len = Math.max(Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]), 0.01);
        nodes[i].x += (dx[i] / len) * Math.min(len, temp);
        nodes[i].y += (dy[i] / len) * Math.min(len, temp);
      }
    }
    // Fit into the box.
    var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach(function (nd) { minX = Math.min(minX, nd.x); maxX = Math.max(maxX, nd.x); minY = Math.min(minY, nd.y); maxY = Math.max(maxY, nd.y); });
    var pad = 44;
    var sx = (W - 2 * pad) / Math.max(maxX - minX, 1), sy = (H - 2 * pad) / Math.max(maxY - minY, 1);
    nodes.forEach(function (nd) { nd.x = pad + (nd.x - minX) * sx; nd.y = pad + (nd.y - minY) * sy; });
    // Collision pass in screen space, so labels do not sit on other nodes.
    function room(nd) { return nd.label === "Application" ? 34 : nd.label === "Person" ? 22 : 18; }
    for (var pass = 0; pass < 120; pass++) {
      for (var a = 0; a < n; a++) for (var b = a + 1; b < n; b++) {
        var p = nodes[a], q = nodes[b];
        var ux = q.x - p.x, uy = q.y - p.y, dist = Math.sqrt(ux * ux + uy * uy) || 0.01, min = room(p) + room(q);
        if (dist < min) {
          var push = (min - dist) / 2;
          p.x -= (ux / dist) * push; p.y -= (uy / dist) * push; q.x += (ux / dist) * push; q.y += (uy / dist) * push;
        }
      }
      nodes.forEach(function (nd) { nd.x = Math.max(pad, Math.min(W - pad, nd.x)); nd.y = Math.max(pad - 16, Math.min(H - pad, nd.y)); });
    }
  }
  var EXTRA = {};
  ["gr_extra_185", "gr_extra_1493", "gr_extra_2134"].forEach(function (id) { EXTRA[rv(id, "id")] = REC[id].context; });

  function renderGraph(stage, side) {
    var g = D.graph[graphMode];
    var controls = h("div", { class: "ctl", style: "margin-bottom:12px" });
    var seg = h("div", { class: "seg", role: "radiogroup", "aria-label": "Which neighbourhood" });
    radioGroup(seg, [{ value: "ring", label: "Ring around A0000030" }, { value: "sample", label: "A0000006, this loan" }], graphMode, function (v) {
      graphMode = v; showPath = false; renderShape("neo4j", true); refocus('[aria-label="Which neighbourhood"] [aria-checked="true"]');
    });
    controls.appendChild(seg);
    var pathBtn = null;
    if (graphMode === "ring") {
      pathBtn = h("button", { class: "btn small", type: "button", "aria-pressed": String(showPath) }, showPath ? "Hide the shortest path" : "Shortest path to " + g.target);
      pathBtn.addEventListener("click", function () { showPath = !showPath; renderShape("neo4j", true); refocus("[aria-pressed]"); });
      controls.appendChild(pathBtn);
    }
    stage.appendChild(controls);
    var narrow = stage.clientWidth < 520;
    var W = narrow ? 360 : 680, H = narrow ? 520 : 440;
    var nodes = g.nodes.map(function (n) { return Object.assign({}, n); });
    layoutGraph(nodes, g.edges, W, H);
    var pos = {};
    nodes.forEach(function (n) { pos[n.id] = n; });
    var onPath = {};
    if (showPath && g.path) for (var i = 0; i < g.path.length - 1; i++) { onPath[g.path[i] + ">" + g.path[i + 1]] = true; onPath[g.path[i + 1] + ">" + g.path[i]] = true; }
    var pathNodes = {};
    if (showPath && g.path) g.path.forEach(function (p) { pathNodes[p] = true; });
    var svg = s("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": graphMode === "ring"
      ? "Graph of the 8 applications reachable from A0000030 through shared phones, devices and addresses, with the people who submitted them."
      : "Graph of A0000006: its borrower, a second application by the same borrower, and the phone, device and address they share." });
    var eg = s("g");
    g.edges.forEach(function (e) {
      var a = pos[e.from], b = pos[e.to];
      var cls = "edge" + (e.type === "SUBMITTED" ? " submitted" : " ident") + (e.shared ? " shared" : "") + (onPath[e.from + ">" + e.to] ? " onpath" : "") + (showPath && !onPath[e.from + ">" + e.to] ? " dim" : "");
      eg.appendChild(s("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: cls }));
    });
    svg.appendChild(eg);
    var info = side.info;
    function describe(n) {
      var parts = [];
      if (n.label === "Application") {
        parts.push(h("p", { style: "margin:0 0 4px" }, h("b", null, "Application " + n.id), " · " + n.status + ", " + n.product));
        parts.push(h("p", { class: "small", style: "margin:0" }, "Submitted by " + n.borrower_id + ". " +
          (graphMode !== "ring" ? "" : n.role === "ring" ? "A member of the planted ring (ground truth from the generator)." : (EXTRA[n.id] ? EXTRA[n.id] + "." : "Not in the planted ring."))));
      } else if (n.label === "Person") {
        parts.push(h("p", { style: "margin:0" }, h("b", null, "Person " + n.id), " · " + n.name));
      } else {
        var users = g.edges.filter(function (e) { return e.to === n.id; }).map(function (e) { return e.from; });
        parts.push(h("p", { style: "margin:0 0 4px" }, h("b", null, n.label), " · ", code(n.value)));
        parts.push(h("p", { class: "small", style: "margin:0" }, "Used by " + users.join(", ")));
      }
      return parts;
    }
    var ng = s("g");
    nodes.forEach(function (n) {
      var dim = showPath && !pathNodes[n.id];
      var gEl = s("g", { class: "node" + (dim ? " dim" : ""), transform: "translate(" + n.x.toFixed(1) + "," + n.y.toFixed(1) + ")" });
      var shape;
      if (n.label === "Application") {
        shape = s("circle", { r: 13, class: "shape", fill: n.role === "ring" && graphMode === "ring" ? "var(--orange)" : "var(--blue)" });
      } else if (n.label === "Person") {
        shape = s("rect", { x: -8, y: -8, width: 16, height: 16, rx: 4, class: "shape", fill: "var(--grey)" });
      } else {
        shape = s("path", { d: "M0,-11 L11,0 L0,11 L-11,0 Z", class: "shape", fill: "var(--violet)" });
      }
      gEl.appendChild(shape);
      if (n.label !== "Application" && n.label !== "Person") gEl.appendChild(s("text", { class: "glyph", text: n.label[0] }));
      if (n.label === "Application") gEl.appendChild(s("text", { class: "lbl", x: 0, y: 27, "text-anchor": "middle", text: n.id }));
      if (n.label === "Person") gEl.appendChild(s("text", { class: "lbl", x: 0, y: 22, "text-anchor": "middle", style: "font-size:10px;fill:var(--muted)", text: n.id }));
      if (n.label === "Application" || n.label === "Person") {
        gEl.setAttribute("tabindex", "0");
        gEl.setAttribute("role", "button");
        gEl.setAttribute("aria-label", n.label + " " + n.id + (n.role === "ring" && graphMode === "ring" ? ", planted ring member" : ""));
      }
      function act() {
        ng.querySelectorAll(".node.active").forEach(function (x) { x.classList.remove("active"); });
        gEl.classList.add("active");
        clear(info);
        append(info, describe(n));
      }
      gEl.addEventListener("mouseenter", act);
      gEl.addEventListener("focus", act);
      gEl.addEventListener("click", act);
      ng.appendChild(gEl);
    });
    svg.appendChild(ng);
    stage.appendChild(h("div", { class: "graph-box", style: "--accent: var(--neo)" }, svg));
    stage.appendChild(h("ul", { class: "legend" },
      graphMode === "ring" ? h("li", null, h("span", { class: "sw", style: "background:var(--orange);border-radius:50%" }), "application in the planted ring") : null,
      h("li", null, h("span", { class: "sw", style: "background:var(--blue);border-radius:50%" }), graphMode === "ring" ? "application reached, not planted" : "application"),
      h("li", null, h("span", { class: "sw", style: "background:var(--grey)" }), "Person"),
      h("li", null, h("span", { class: "sw", style: "background:var(--violet);transform:rotate(45deg) scale(.8)" }), "Phone (P), Device (D), Address (A)"),
      h("li", null, h("span", { class: "sw line", style: "background:var(--violet)" }), "shared identifier"),
      showPath ? h("li", null, h("span", { class: "sw line", style: "background:var(--orange)" }), "shortest path") : null));
    // Text equivalent.
    var byLabel = {};
    g.nodes.forEach(function (n) { byLabel[n.id] = n.label === "Application" || n.label === "Person" ? n.id : n.label + " " + n.value; });
    stage.appendChild(h("details", { class: "as-table" }, h("summary", null, "Relationships as a list (" + g.edges.length + ")"),
      h("ul", { class: "small", style: "margin:8px 0 0;padding-left:18px" }, g.edges.map(function (e) {
        return h("li", null, byLabel[e.from] + " " + e.type + " " + byLabel[e.to]);
      }))));
    clear(info);
    if (graphMode === "ring") {
      append(info, showPath
        ? [h("p", { style: "margin:0 0 4px" }, h("b", null, rv("gr_path", "hops") + " relationships"), " (lab step 6.5)"), h("p", { class: "small mono", style: "margin:0" }, rv("gr_path_nodes", "path"))]
        : [h("p", { style: "margin:0 0 4px" }, h("b", null, "8 applications reached, 5 planted")), h("p", { class: "small", style: "margin:0" }, "No single identifier links the whole ring: phone, then device, then address. Only a multi-hop traversal finds it, and it also reaches three innocent-looking neighbours. Hover or focus a node.")]);
    } else {
      append(info, [h("p", { style: "margin:0 0 4px" }, h("b", null, "A component of 2 applications")), h("p", { class: "small", style: "margin:0" }, "B001532 applied twice from the same phone, device and address. One person, two applications: a link, but not a ring, which is why chapter 6 flags only components with 3 or more distinct borrowers.")]);
    }
  }

  var SHAPES = [
    { id: "sql", tab: "SQL tables", accent: "--sql", ch: "documents", chLabel: "Chapter 2: documents versus rows",
      query: "SELECT a.application_id, b.full_name,\n       e.employer, d.score, l.principal\nFROM applications a\nJOIN borrowers b USING (borrower_id)\nLEFT JOIN employment e USING (borrower_id)\nLEFT JOIN decisions d USING (application_id)\nLEFT JOIN loans l USING (application_id)\nWHERE a.application_id = 'A0000006';\n-- documents and decline_reasons:\n-- one more query each",
      notice: "In a relational schema this one application is rows in seven tables, plus one row per payment. Any question can be asked later, with joins.",
      pain: "None for analytics: this is the shape the pipeline rebuilds in the lake. The cost sits with the application, which joins seven tables to draw one screen.",
      render: renderSql },
    { id: "mongo", tab: "MongoDB", accent: "--mongo", ch: "documents", chLabel: "Chapter 2: documents versus rows",
      query: 'db.applications.findOne({ _id: "A0000006" })',
      notice: "The application screen reads everything with one lookup by _id. date_of_birth is a string (BSON has no date-only type) and money is a double.",
      pain: "Schema drift, and deletes that a watermark cannot see.",
      render: renderMongo },
    { id: "redis", tab: "Redis", accent: "--redis", ch: "redis_structures", chLabel: "Chapter 3: data structures",
      query: "GET ch03:loan:L0000006:status\nHGETALL ch03:borrower:B001532\nSET ops:dedup:<event_id> 1 NX EX 2592000",
      notice: "There are no tables and no queries by value: key naming is your schema. Redis stores strings, so 'income' comes back as text.",
      pain: "Volatility and eviction: with the image's defaults AOF is off, and an allkeys-* policy can evict dedup keys.",
      render: renderRedis },
    { id: "cassandra", tab: "Cassandra", accent: "--cass", ch: "cassandra_model", chLabel: "Chapter 4: query-first modeling",
      query: "SELECT event_time, instalment_no, amount_cents\nFROM payments_by_loan\nWHERE loan_id = 'L0000006'\nLIMIT 3;",
      notice: "One table per query: the same payment lives in payments_by_loan and payments_by_day. The latest 3 come back already sorted, newest first, from one partition.",
      pain: "Full scans, tombstones and no ad-hoc queries: a filter on a non-key column is refused.",
      render: renderCassandra },
    { id: "dynamodb", tab: "DynamoDB", accent: "--dynamo", ch: "single_table", chLabel: "Chapter 5: single-table design",
      query: null,
      notice: "One table for every entity. Items that are read together share a partition key, so one Query returns a borrower's profile, applications and loan references at once.",
      pain: "Scan cost, 1 MB pages, and a single-table design that is hard to read for anyone who did not design it.",
      render: renderDynamo },
    { id: "neo4j", tab: "Neo4j", accent: "--neo", ch: "rings", chLabel: "Chapter 6: fraud rings",
      query: "MATCH (start:Application\n        {application_id: $id})\n  -[:USES_PHONE|USES_DEVICE|AT_ADDRESS*1..10]-\n  (other:Application)\nRETURN DISTINCT other.application_id AS id",
      notice: "Relationships are stored, not computed: following one costs the same however big the graph is, so a ten-hop question is practical.",
      pain: "Getting graph results into tables: export the edges and finish the job in the lake.",
      render: renderGraph }
  ];
  var shapeTabs = $("shape-tabs"), shapePanel = $("shape-panel"), currentShape = "sql";
  SHAPES.forEach(function (sh, i) {
    var b = h("button", { class: "tab", role: "tab", id: "tab-" + sh.id, type: "button", "aria-controls": "shape-panel", style: "--accent: var(" + sh.accent + ")" }, sh.tab);
    b.addEventListener("click", function () { renderShape(sh.id); });
    b.addEventListener("keydown", function (e) {
      var d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (e.key === "Home") d = -i; if (e.key === "End") d = SHAPES.length - 1 - i;
      if (!d) return;
      e.preventDefault();
      var nxt = SHAPES[(i + d + SHAPES.length) % SHAPES.length];
      $("tab-" + nxt.id).focus();
      renderShape(nxt.id);
    });
    shapeTabs.appendChild(b);
  });
  function refocus(sel) { var el = shapePanel.querySelector(sel); if (el) el.focus(); }
  function renderShape(id, keepAnim) {
    currentShape = id;
    var sh = SHAPES.filter(function (x) { return x.id === id; })[0];
    SHAPES.forEach(function (x) {
      var b = $("tab-" + x.id);
      b.setAttribute("aria-selected", String(x.id === id));
      b.setAttribute("tabindex", x.id === id ? "0" : "-1");
    });
    shapePanel.setAttribute("aria-labelledby", "tab-" + id);
    clear(shapePanel);
    shapePanel.style.setProperty("--accent", "var(" + sh.accent + ")");
    var stage = h("div", { class: "card shape-stage" });
    var queryPre = h("pre", { class: "code" }, sh.query || "");
    var info = h("div", { class: "graph-info small" });
    var side = h("div", { class: "shape-side" },
      sh.id === "neo4j" ? h("div", { class: "card flat graph-info" }, info) : null,
      h("div", null, h("h4", null, "The query"), queryPre),
      h("div", null, h("h4", null, "What to notice"), h("p", { class: "small", style: "margin:0" }, sh.notice)),
      h("div", null, h("h4", null, "Data engineering pain"), h("p", { class: "note small" }, sh.pain)),
      h("div", null, extLink(sh.ch, sh.chLabel + " ↗")));
    shapePanel.appendChild(h("div", { class: "shape-wrap" }, stage, side));
    sh.render(stage, { query: queryPre, info: info });
    if (!keepAnim) animateIn(shapePanel);
  }
  renderShape("sql");
  var lastNarrow = null;
  window.addEventListener("resize", function () {
    if (currentShape !== "neo4j") return;
    var narrow = shapePanel.querySelector(".shape-stage").clientWidth < 520;
    if (lastNarrow !== null && narrow !== lastNarrow) renderShape("neo4j", true);
    lastNarrow = narrow;
  });

  // ------------------------------------------------------------------ MongoDB: watermark vs change stream
  (function watermark() {
    var W = D.watermark;
    var n1 = rn("wm_run1", "docs"), ins = rn("wm_changes", "inserted"), upd = rn("wm_changes", "updated"), n2 = rn("wm_run2", "docs");
    var victims = W.victims;
    var wm1 = rv("wm_run1", "watermark"), wm2 = rv("wm_run2", "watermark");
    var steps = [
      { short: "Run 1", title: "30 April: the first run", source: n1,
        what: "Full extract of everything the source holds.",
        wm: { read: n1, note: "Reads every document, then keeps the highest updated_at it saw.", query: "find({})", mark: wm1, lake: n1 },
        cs: { read: n1, note: "Same initial snapshot, then open the change stream and save its resume token.", lake: n1 },
        sample: { label: "Last documents read (the watermark is the newest)", rows: W.sample_run1 } },
      { short: "May", title: "May: the source changes", source: n1 + ins,
        what: ins + " applications inserted and " + upd + " updated. Nothing is extracted yet, so both copies are behind by design.",
        wm: { read: null, note: "Waiting for the next run.", query: null, mark: wm1, lake: n1, behind: true },
        cs: { read: null, note: "The writes wait in the oplog: one event per write, " + ins + " insert and " + upd + " replace.", lake: n1, behind: true, derived: true } },
      { short: "Run 2", title: "31 May: the incremental run", source: n1 + ins,
        what: "Each method reads only what changed.",
        wm: { read: n2, note: n2 + " = " + ins + " new + " + upd + " changed. The watermark moves forward.", query: "find({updated_at: {$gt: " + wm1 + "}})", mark: wm2, lake: n1 + ins },
        cs: { read: n2, note: n2 + " events, resumed from the token; save the new token after the data is durable.", lake: n1 + ins, derived: true },
        sample: { label: "First documents of run 2", rows: W.sample_run2 } },
      { short: "Run 3", title: "Run 3: nothing changed", source: n1 + ins,
        what: "A re-run with no source changes.",
        wm: { read: rn("wm_run3", "docs"), note: "Nothing is newer than the watermark.", query: "find({updated_at: {$gt: " + wm2 + "}})", mark: wm2, lake: n1 + ins },
        cs: { read: 0, note: "No new events.", lake: n1 + ins } },
      { short: "Run 4", title: "Three hard deletes, then run 4", source: n1 + ins - victims.length,
        what: "Erased in the source: " + victims.join(", ") + ".",
        wm: { read: rn("wm_run4", "docs"), note: "A deleted document has no updated_at to compare: the query cannot see it. The lake keeps all three.", query: "find({updated_at: {$gt: " + wm2 + "}})", mark: wm2, lake: n1 + ins },
        cs: { read: victims.length, note: "Three delete events, each with the document key.", lake: n1 + ins - victims.length, derived: true },
        sample: { label: "Documents the lake still holds", rows: W.sample_run2.map(function (r) { return [r[0], "deleted in the source", r[2]]; }) } }
    ];
    var cur = 0;
    var ol = $("wm-steps");
    var stepBtns = steps.map(function (st, i) {
      var b = h("button", { type: "button", onclick: function () { go(i); } }, h("b", null, st.short), st.title.split(": ")[1] || st.title);
      ol.appendChild(h("li", null, b));
      return b;
    });
    function col(name, x, source) {
      var match = x.behind ? null : x.lake === source;
      return h("div", { class: "card flat", style: "box-shadow:none" },
        h("div", { class: "card-head" }, h("h3", null, name),
          match === null ? h("span", { class: "verdict" }, "behind until the next run")
            : match ? h("span", { class: "verdict ok" }, "✓ lake matches source") : h("span", { class: "verdict bad" }, "✗ lake has " + (x.lake - source) + " too many")),
        h("div", { class: "big-num" }, x.read == null ? "·" : fmt(x.read)),
        h("p", { class: "small muted", style: "margin:2px 0 10px" }, x.read == null ? "nothing read yet" : name === "Watermark query" ? "documents read this run" : "events read this run"),
        x.query ? h("pre", { class: "code wrap", style: "margin-bottom:10px;font-size:12px" }, "applications." + x.query) : null,
        h("p", { class: "small", style: "margin:0 0 10px" }, x.note, x.derived ? h("span", { class: "muted" }, " (derived: one event per write the lab made)") : null),
        h("dl", { class: "kv" },
          x.mark ? [h("dt", null, "watermark"), h("dd", { class: "mono" }, x.mark)] : null,
          h("dt", null, "ids in the lake"), h("dd", null, fmt(x.lake))));
    }
    function go(i) {
      cur = Math.max(0, Math.min(steps.length - 1, i));
      var st = steps[cur];
      stepBtns.forEach(function (b, j) {
        if (j === cur) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
        b.classList.toggle("done", j < cur);
      });
      var body = $("wm-body");
      clear(body);
      body.appendChild(h("div", { class: "card-head" },
        h("div", null, h("h3", null, st.title), h("p", { class: "small muted", style: "margin:0" }, st.what)),
        h("div", { class: "result-box", style: "padding:8px 14px" }, h("span", { class: "small muted" }, "documents in the source"), h("div", { class: "res", style: "font-size:20px" }, fmt(st.source)))));
      body.appendChild(h("div", { class: "grid-2" }, col("Watermark query", st.wm, st.source), col("Change stream", st.cs, st.source)));
      if (st.sample) {
        body.appendChild(h("div", { style: "margin-top:14px" }, h("h4", null, st.sample.label),
          h("div", { class: "table-scroll" }, dataTable(["_id", "status", "updated_at"], st.sample.rows.map(function (r) { return { _id: r[0], status: r[1], updated_at: r[2] }; })))));
      }
      if (cur === steps.length - 1) {
        body.appendChild(h("p", { class: "note small", style: "margin-top:14px" }, h("strong", null, "The fix: "),
          "soft deletes, a periodic comparison of the set of keys (the capstone does this), or change streams. ", extLink("changestreams", "Change streams and resume tokens")));
      }
      $("wm-prev").disabled = cur === 0;
      $("wm-next").disabled = cur === steps.length - 1;
      animateIn(body);
    }
    $("wm-prev").addEventListener("click", function () { go(cur - 1); });
    $("wm-next").addEventListener("click", function () { go(cur + 1); });
    go(0);
  })();

  (function resumeTokens() {
    var items = [
      { who: "consumer 1", rec: "cs_c1_1" }, { who: "consumer 1", rec: "cs_c1_2" }, { who: "consumer 1", rec: "cs_c1_3" },
      { who: "consumer 1", rec: "cs_c1_4" }, { who: "consumer 1", rec: "cs_c1_5" },
      { who: "token", text: "resume token saved; consumer 1 stops" },
      { who: "no consumer", text: "insert _id=X3", missed: true }, { who: "no consumer", text: "update _id=X1", missed: true }, { who: "no consumer", text: "delete _id=X1", missed: true },
      { who: "consumer 2", rec: "cs_resumed_insert" }, { who: "consumer 2", rec: "cs_resumed_update" }, { who: "consumer 2", rec: "cs_resumed_delete" }
    ];
    var captions = [
      "Consumer 1 watches the collection and receives every insert, update and delete in order.",
      "", "", "", "Five events, including the delete of X2: this is what a watermark cannot do.",
      "It saves the resume token of the last event it processed, then stops.",
      "While no consumer is running, the application keeps writing.", "", "Three changes, nobody listening.",
      "Consumer 2 starts with resume_after=<saved token>: the stream continues right after the last processed event.",
      "fullDocument=None: updateLookup reads the document when the event is read, and X1 had been deleted by then. Use pre- and post-images if you need the document as it was.",
      "Nothing was lost while the consumer was down. A token is only good while the oplog still holds it."
    ];
    var shown = 0;
    var ul = $("cs-events");
    function draw() {
      clear(ul);
      items.forEach(function (it, i) {
        var text = it.rec ? REC[it.rec].context : it.text;
        var parts = text.split(/\s+/);
        var li = h("li", { class: (i >= shown ? "future" : "") + (it.missed ? " missed" : "") },
          h("span", { class: "small muted" }, it.who),
          h("span", null, it.who === "token" ? h("span", { class: "op" }, text) : [h("span", { class: "op" }, parts[0] + " "), code(parts.slice(1).join("  "))]));
        if (i >= shown) li.setAttribute("aria-hidden", "true");
        ul.appendChild(li);
      });
      var cap = "";
      for (var j = Math.min(shown, captions.length) - 1; j >= 0; j--) if (captions[j]) { cap = captions[j]; break; }
      $("cs-caption").textContent = shown === 0 ? "Press Next event to start." : cap;
      $("cs-step").disabled = shown >= items.length;
    }
    $("cs-step").addEventListener("click", function () { shown = Math.min(items.length, shown + 1); draw(); });
    $("cs-reset").addEventListener("click", function () { shown = 0; draw(); });
    draw();
  })();

  barChart($("explain-chart"), {
    title: "Documents examined and returned", ariaLabel: "Documents examined and returned, without and with the index",
    series: READ_VS, tableFirst: "plan",
    groups: [
      { label: "No index", bars: [
        { series: "read", value: rn("explain_docs", "collscan"), display: fmt(rn("explain_docs", "collscan")), tip: "totalDocsExamined; plan " + rv("explain_stages", "collscan") },
        { series: "returned", value: rn("explain_returned", "collscan"), display: fmt(rn("explain_returned", "collscan")), tip: "nReturned, sorted in memory" }] },
      { label: "Compound index", bars: [
        { series: "read", value: rn("explain_docs", "ixscan"), display: fmt(rn("explain_docs", "ixscan")), tip: "totalDocsExamined; " + rv("explain_keys", "ixscan") + " index keys; plan " + rv("explain_stages", "ixscan") },
        { series: "returned", value: rn("explain_returned", "ixscan"), display: fmt(rn("explain_returned", "ixscan")), tip: "nReturned, no sort needed" }] }
    ]
  });

  // ------------------------------------------------------------------ Redis Streams simulator
  (function streams() {
    var MIN_IDLE = 1000, MAX_DELIVERIES = 3;
    var st;
    var busy = false;
    var NAMES = { a: "worker-a", b: "worker-b" };
    function reset() {
      st = { clock: 1795094114907, seq: 0, lastMs: 0, entries: [], next: 0, pel: {}, up: { a: true, b: true }, dead: [], entriesRead: 0, log: [], n: 0 };
    }
    function tick(ms) { st.clock += ms; }
    function newId() {
      if (st.clock === st.lastMs) st.seq += 1; else { st.seq = 0; st.lastMs = st.clock; }
      return st.clock + "-" + st.seq;
    }
    function log(cmd, result, cls) { st.log.push({ cmd: cmd, result: result, cls: cls || "" }); }
    function xadd(n, poison) {
      var ids = [];
      for (var i = 0; i < n; i++) {
        st.n += 1;
        var e = { id: newId(), name: poison ? "poison" : "e" + String(st.n).padStart(2, "0"), poison: !!poison, acked: false, dead: false };
        st.entries.push(e);
        ids.push(e.id);
        if (i % 2 === 1) tick(1);
      }
      log("XADD ch03:payments * event_id " + (poison ? "poison amount_cents not-a-number" : "..."), n === 1 ? ids[0] : n + " entries, " + ids[0] + " to " + ids[ids.length - 1]);
    }
    function read(c, count) {
      var cmd = "XREADGROUP GROUP loader " + NAMES[c] + " COUNT " + count + " STREAMS ch03:payments >";
      if (!st.up[c]) { log(cmd, NAMES[c] + " has crashed: it cannot read", "err"); return 0; }
      var got = [];
      while (st.next < st.entries.length && got.length < count) {
        var e = st.entries[st.next++];
        st.pel[e.id] = { owner: c, deliveries: 1, last: st.clock, fresh: true };
        got.push(e.id);
      }
      st.entriesRead += got.length;
      tick(2);
      log(cmd, got.length ? got.length + " entries delivered, now pending for " + NAMES[c] : "(nil): no entry that the group has not seen");
      return got.length;
    }
    function entryById(id) { return st.entries.filter(function (e) { return e.id === id; })[0]; }
    function process(c) {
      if (!st.up[c]) { log("process " + NAMES[c], NAMES[c] + " has crashed", "err"); return; }
      var mine = Object.keys(st.pel).filter(function (id) { return st.pel[id].owner === c && st.pel[id].fresh; }).sort(cmpId);
      if (!mine.length) { log("process " + NAMES[c], "nothing new delivered to " + NAMES[c], "note"); return; }
      var acked = 0;
      mine.forEach(function (id) {
        var p = st.pel[id], e = entryById(id);
        p.fresh = false;
        if (e.poison) {
          if (p.deliveries >= MAX_DELIVERIES) {
            st.dead.push(e.id);
            e.dead = true;
            delete st.pel[id];
            log("XADD ch03:payments:dead_letter * ... reason \"failed 3 times\"", "then XACK " + id + ": delivered " + p.deliveries + " times, moved to the dead letter", "ok");
          } else {
            log("process " + id, "failed (amount_cents is not a number); no XACK, still pending, delivered " + p.deliveries + (p.deliveries === 1 ? " time" : " times"), "err");
          }
        } else {
          e.acked = true;
          delete st.pel[id];
          acked++;
        }
      });
      if (acked) log("XACK ch03:payments loader ...", acked + " acknowledged by " + NAMES[c], "ok");
    }
    function crash(c) {
      st.up[c] = false;
      var n = Object.keys(st.pel).filter(function (id) { return st.pel[id].owner === c; }).length;
      log(NAMES[c] + " crashes", "its " + n + " pending entries stay in the PEL; Redis will not redeliver them", "err");
    }
    function claim() {
      var cmd = "XAUTOCLAIM ch03:payments loader worker-b " + MIN_IDLE + " 0-0";
      if (!st.up.b) { log(cmd, "worker-b has crashed", "err"); return 0; }
      var ids = Object.keys(st.pel).filter(function (id) { return st.clock - st.pel[id].last >= MIN_IDLE; }).sort(cmpId);
      ids.forEach(function (id) {
        var p = st.pel[id];
        p.owner = "b"; p.deliveries += 1; p.last = st.clock; p.fresh = true;
      });
      log(cmd, ids.length ? ids.length + " entries claimed by worker-b, delivery count +1" : "0 entries: none idle for " + MIN_IDLE + " ms yet", ids.length ? "" : "note");
      return ids.length;
    }
    function cmpId(a, b) {
      var x = a.split("-").map(Number), y = b.split("-").map(Number);
      return x[0] - y[0] || x[1] - y[1];
    }
    function pendingSummary() {
      var per = {};
      Object.keys(st.pel).forEach(function (id) { var o = st.pel[id].owner; per[o] = (per[o] || 0) + 1; });
      var ids = Object.keys(st.pel);
      return { total: ids.length, per: per };
    }
    function draw() {
      $("st-clock").textContent = "clock " + st.clock + " ms";
      var lane = clear($("st-lane"));
      if (!st.entries.length) lane.appendChild(h("span", { class: "small muted" }, "Empty stream. Add entries to start, or replay the lab."));
      st.entries.forEach(function (e) {
        var p = st.pel[e.id];
        var cls = "entry" + (p ? " pending-" + p.owner : "") + (e.acked ? " acked" : "") + (e.dead ? " dead" : "") + (e.poison ? " poison" : "");
        var state = p ? "pending for " + NAMES[p.owner] + ", delivered " + p.deliveries : e.acked ? "acknowledged" : e.dead ? "moved to the dead letter" : "not delivered yet";
        lane.appendChild(h("span", { class: cls, role: "img", "aria-label": "Entry " + e.id + " " + e.name + ": " + state },
          h("b", null, e.name), h("span", { class: "dc" }, p ? "×" + p.deliveries : e.acked ? "ack" : e.dead ? "dlq" : "new")));
      });
      var cons = clear($("st-consumers"));
      ["a", "b"].forEach(function (c) {
        var holds = Object.keys(st.pel).filter(function (id) { return st.pel[id].owner === c; }).length;
        var fresh = Object.keys(st.pel).filter(function (id) { return st.pel[id].owner === c && st.pel[id].fresh; }).length;
        cons.appendChild(h("div", { class: "consumer" + (st.up[c] ? "" : " down"), style: "--c: var(" + (c === "a" ? "--blue" : "--aqua") + ")" },
          h("header", null, h("b", null, NAMES[c]), h("span", { class: "state" + (st.up[c] ? "" : " down") }, st.up[c] ? "running, " + holds + " pending" : "crashed, " + holds + " pending")),
          h("div", { class: "ctl" },
            h("button", { class: "btn small", type: "button", disabled: busy || !st.up[c], onclick: function () { read(c, 5); draw(); } }, "Read 5"),
            h("button", { class: "btn small", type: "button", disabled: busy || !st.up[c] || !fresh, onclick: function () { process(c); draw(); } }, "Process and XACK"),
            h("button", { class: "btn small", type: "button", disabled: busy || !st.up[c], onclick: function () { crash(c); draw(); } }, "Crash"))));
      });
      var ids = Object.keys(st.pel).sort(cmpId);
      var tbl = clear($("st-pel"));
      tbl.appendChild(h("thead", null, h("tr", null, h("th", { scope: "col" }, "entry id"), h("th", { scope: "col" }, "owner"), h("th", { scope: "col", class: "num" }, "idle ms"), h("th", { scope: "col", class: "num" }, "times_delivered"))));
      tbl.appendChild(h("tbody", null, ids.length ? ids.map(function (id) {
        var p = st.pel[id];
        return h("tr", null, h("td", { class: "mono" }, id + (entryById(id).poison ? " (poison)" : "")), h("td", { class: "mono" }, NAMES[p.owner]), h("td", { class: "num" }, fmt(st.clock - p.last)), h("td", { class: "num" }, String(p.deliveries)));
      }) : h("tr", { class: "empty-row" }, h("td", { colspan: "4" }, "0 pending"))));
      var sum = pendingSummary();
      $("st-info").textContent = "XINFO GROUPS: entries-read=" + st.entriesRead + ", lag=" + (st.entries.length - st.entriesRead) + ", pending=" + sum.total +
        ". Dead letter ch03:payments:dead_letter: " + st.dead.length + (st.dead.length === 1 ? " entry." : " entries.");
      var lg = clear($("st-log"));
      st.log.slice(-80).forEach(function (l) {
        lg.appendChild(h("li", { class: l.cls }, h("span", { class: "cmd" }, "> " + l.cmd), h("br"), "  " + l.result));
      });
      lg.scrollTop = lg.scrollHeight;
      ["st-add", "st-poison", "st-wait", "st-claim", "st-replay", "st-reset"].forEach(function (id) { $(id).disabled = busy && id !== "st-reset"; });
    }
    $("st-add").addEventListener("click", function () { xadd(5); draw(); });
    $("st-poison").addEventListener("click", function () { xadd(1, true); draw(); });
    $("st-wait").addEventListener("click", function () { tick(1100); log("wait 1.1 s", "every pending entry is now 1,100 ms more idle", "note"); draw(); });
    $("st-claim").addEventListener("click", function () { claim(); draw(); });
    var timer = null;
    $("st-reset").addEventListener("click", function () { if (timer) clearTimeout(timer); busy = false; reset(); draw(); });
    $("st-replay").addEventListener("click", function () {
      reset();
      busy = true;
      var acked = 0;
      var script = [
        function () { for (var i = 0; i < 20; i++) xadd(1); st.log = []; log("XADD x 20, then XADD a poison entry", "21 entries; XGROUP CREATE ch03:payments loader 0"); xadd(1, true); st.log.pop(); },
        function () { read("a", 5); },
        function () { crash("a"); },
        function () { while (read("b", 10)) { var before = st.entries.filter(function (e) { return e.acked; }).length; process("b"); acked += st.entries.filter(function (e) { return e.acked; }).length - before; } },
        function () { var s2 = pendingSummary(); log("XPENDING ch03:payments loader", s2.total + " pending: worker-a " + (s2.per.a || 0) + ", worker-b " + (s2.per.b || 0) + " (acknowledged " + acked + ")"); },
        function () { tick(1100); log("wait 1.1 s", "worker-a's entries are now idle for more than 1,000 ms", "note"); },
        function () { claim(); },
        function () { process("b"); },
        function () { tick(1100); claim(); },
        function () { process("b"); },
        function () {
          var s3 = pendingSummary();
          var ok = st.entries.length === rn("st_xadd", "entries") && acked === rn("st_pending", "acked") && s3.total === rn("st_dead", "pending") &&
            st.dead.length === rn("st_dead", "dead_letter") && st.entriesRead === rn("st_groups", "entries_read");
          log("XINFO GROUPS ch03:payments", "entries-read=" + st.entriesRead + ", lag=" + (st.entries.length - st.entriesRead) + ", pending=" + s3.total, ok ? "ok" : "err");
          log("compare with lab step 3.8", ok ? "same as the lab: " + rv("st_groups", "entries_read") + " read, " + rv("st_pending", "acked") + " acked by worker-b, 6 claimed, poison dead-lettered after " + rv("st_dead", "deliveries") + " deliveries" : "differs from the lab", ok ? "ok" : "err");
        }
      ];
      var i = 0;
      (function next() {
        if (i >= script.length) { busy = false; draw(); return; }
        script[i++]();
        draw();
        timer = setTimeout(next, reduceMotion ? 0 : 650);
      })();
    });
    reset();
    draw();
  })();

  // ------------------------------------------------------------------ Cassandra
  var P = D.partitions;
  // Simplified token ring: 16 virtual nodes per node, replicas on the next distinct nodes clockwise.
  function ringFor(nNodes) {
    var v = [];
    for (var i = 0; i < nNodes; i++) for (var j = 0; j < 16; j++) v.push({ t: fnv("node-" + i + "#" + j), node: i });
    v.sort(function (a, b) { return a.t - b.t; });
    return v;
  }
  function replicas(ring, key, rf, nNodes) {
    var t = fnv(key), lo = 0, hi = ring.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (ring[mid].t < t) lo = mid + 1; else hi = mid; }
    var out = [];
    for (var k = 0; k < ring.length && out.length < Math.min(rf, nNodes); k++) {
      var nd = ring[(lo + k) % ring.length].node;
      if (out.indexOf(nd) < 0) out.push(nd);
    }
    return out;
  }
  (function partitionDesigner() {
    var designs = [
      { value: "method", label: "method", rec: "hp_method" },
      { value: "method_month", label: "(method, month)" },
      { value: "event_day", label: "event_day", rec: "hp_day" },
      { value: "loan_id", label: "loan_id", rec: "hp_loan" }
    ];
    var cur = "method", nodes = 6;
    function draw() {
      var d = P.designs[cur], meta = designs.filter(function (x) { return x.value === cur; })[0];
      var parts = d.partitions, total = P.total_rows, largest = parts[0][1];
      var share = meta.rec ? rv(meta.rec, "share") : pct(largest / total, 1);
      $("pk-ddl").textContent = "CREATE TABLE " + d.table + " (... PRIMARY KEY " + d.primary_key + ")";
      var stats = clear($("pk-stats"));
      [[fmt(parts.length), "partitions"], [fmt(largest), "rows in the largest"], [share, "share of all rows"]].forEach(function (x) {
        stats.appendChild(h("div", { class: "stat" }, h("b", null, x[0]), h("span", null, x[1])));
      });
      var top = parts.slice(0, 8);
      barChart($("pk-chart"), {
        title: "Largest partitions", sub: parts.length > top.length ? "Top " + top.length + " of " + fmt(parts.length) + " partitions" : "All " + parts.length + " partitions",
        series: [{ key: "rows", label: "rows", color: C.blue }], max: P.designs.method.partitions[0][1], tableFirst: "partition",
        caption: meta.rec ? "Matches lab step 4.4: " + fmt(rn(meta.rec, "partitions")) + " partitions, " + fmt(rn(meta.rec, "largest")) + " rows in the largest, " + rv(meta.rec, "share") + "." : "Not in the lab: the bucketing fix chapter 4 suggests for a query that really is by method.",
        groups: top.map(function (p) { return { label: p[0], bars: [{ series: "rows", value: p[1], display: fmt(p[1]), tip: pct(p[1] / total, 2) + " of all rows" }] }; })
      });
      // Node load.
      var ring = ringFor(nodes), load = new Array(nodes).fill(0);
      parts.forEach(function (p) { replicas(ring, d.table + ":" + p[0], 3, nodes).forEach(function (n) { load[n] += p[1]; }); });
      var maxL = Math.max.apply(null, load), minL = Math.min.apply(null, load);
      barChart($("node-chart"), {
        title: "Replica rows per node", sub: "Each row is stored 3 times. Busiest node: " + fmt(maxL) + ", quietest: " + fmt(minL) + ".",
        series: [{ key: "rows", label: "rows", color: C.blue }], max: total * 3 / Math.min(nodes, 3), tableFirst: "node",
        groups: load.map(function (l, i) { return { label: "node " + (i + 1), bars: [{ series: "rows", value: l, display: fmt(l), tip: pct(l / (total * 3), 1) + " of all replica rows" }] }; })
      });
      $("nodes-out").textContent = String(nodes);
      $("nodes-minus").disabled = nodes <= 3;
      $("nodes-plus").disabled = nodes >= 12;
    }
    radioGroup($("pk-choice"), designs, cur, function (v) { cur = v; draw(); });
    $("nodes-minus").addEventListener("click", function () { nodes = Math.max(3, nodes - 1); draw(); });
    $("nodes-plus").addEventListener("click", function () { nodes = Math.min(12, nodes + 1); draw(); });
    draw();
  })();

  (function consistency() {
    var st = { n: 1, rf: 3, down: {}, w: "QUORUM", r: "QUORUM" };
    var LEVELS = ["ONE", "QUORUM", "ALL"];
    function need(cl, rf) { return cl === "ONE" ? 1 : cl === "QUORUM" ? Math.floor(rf / 2) + 1 : rf; }
    function reps() {
      var start = fnv("L0000006") % st.n, out = [];
      for (var i = 0; i < Math.min(st.rf, st.n); i++) out.push((start + i) % st.n);
      return out;
    }
    var wSeg = radioGroup($("wcl"), LEVELS.map(function (l) { return { value: l, label: l }; }), st.w, function (v) { st.w = v; draw(); });
    var rSeg = radioGroup($("rcl"), LEVELS.map(function (l) { return { value: l, label: l }; }), st.r, function (v) { st.r = v; draw(); });
    function result(op, cl) {
      var rs = reps(), alive = rs.filter(function (n) { return !st.down[n]; }).length, req = need(cl, st.rf);
      var ok = alive >= req;
      var text = ok ? "ok" : "Unavailable: needs " + req + " replicas, " + alive + " alive";
      return { ok: ok, text: text, req: req, alive: alive, op: op, cl: cl };
    }
    function labMatch(res) {
      if (st.n !== 1 || res.op !== "write" || Object.keys(st.down).length) return null;
      var id = "cl_rf" + st.rf + "_" + res.cl.toLowerCase();
      return REC[id] ? rv(id, "result") : null;
    }
    function box(el, res) {
      clear(el);
      var lab = labMatch(res);
      append(el, [h("span", { class: "small muted" }, res.op + " at " + res.cl + " (needs " + res.req + ", " + res.alive + " replica" + (res.alive === 1 ? "" : "s") + " alive)"),
        h("div", { class: "res " + (res.ok ? "ok" : "bad") }, res.text),
        lab != null ? h("div", { class: "small", style: "margin-top:4px" }, lab === res.text ? "✓ the lab printed the same (step 4.6)" : "lab printed: " + lab) : null]);
    }
    function drawRing() {
      var svg = clear($("cl-ring")), cx = 160, cy = 160, R = 112, rs = reps();
      svg.appendChild(s("circle", { cx: cx, cy: cy, r: R, fill: "none", stroke: "var(--border-strong)", "stroke-width": 1.5, "stroke-dasharray": "2 5" }));
      svg.appendChild(s("text", { x: cx, y: cy - 8, text: "partition", style: "fill:var(--muted)" }));
      svg.appendChild(s("text", { x: cx, y: cy + 10, text: "L0000006" }));
      for (var i = 0; i < st.n; i++) {
        (function (i) {
          var a = -Math.PI / 2 + (i / st.n) * Math.PI * 2;
          var x = st.n === 1 ? cx : cx + Math.cos(a) * R, y = st.n === 1 ? cy - R : cy + Math.sin(a) * R;
          var isRep = rs.indexOf(i) > -1, down = !!st.down[i];
          var g = s("g", { class: "node-c", tabindex: "0", role: "button", "aria-pressed": String(down),
            "aria-label": "Node " + (i + 1) + (isRep ? ", replica" : "") + (down ? ", down. Activate to bring it back." : ", up. Activate to take it down.") });
          g.appendChild(s("circle", { class: "outer", cx: x, cy: y, r: 25, fill: down ? "var(--surface)" : isRep ? "var(--cass)" : "var(--surface-3)", style: down ? "stroke:var(--bad);stroke-dasharray:4 3" + (isRep ? ";fill:color-mix(in srgb, var(--cass) 22%, var(--surface))" : "") : null }));
          g.appendChild(s("text", { x: x, y: y - (down ? 5 : 0), text: "n" + (i + 1), style: !down && isRep ? "fill:#fff;font-weight:700" : "" }));
          if (down) g.appendChild(s("text", { x: x, y: y + 9, text: "down", style: "fill:var(--bad);font-size:10px" }));
          function toggle() { if (st.down[i]) delete st.down[i]; else st.down[i] = true; draw(); var el = $("cl-ring").querySelectorAll(".node-c")[i]; if (el) el.focus(); }
          g.addEventListener("click", toggle);
          g.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
          svg.appendChild(g);
        })(i);
      }
    }
    function draw() {
      Object.keys(st.down).forEach(function (k) { if (Number(k) >= st.n) delete st.down[k]; });
      $("cn-out").textContent = String(st.n);
      $("rf-out").textContent = String(st.rf);
      $("cn-minus").disabled = st.n <= 1; $("cn-plus").disabled = st.n >= 6;
      $("rf-minus").disabled = st.rf <= 1; $("rf-plus").disabled = st.rf >= 5;
      var w = result("write", st.w), r = result("read", st.r);
      box($("cl-write"), w);
      box($("cl-read"), r);
      var R = need(st.r, st.rf), Wn = need(st.w, st.rf);
      var msg = [];
      if (st.rf > st.n) msg.push("RF " + st.rf + " on " + st.n + (st.n === 1 ? " node" : " nodes") + ": only " + st.n + (st.n === 1 ? " replica exists" : " replicas exist") + ", but the levels are computed from RF. ");
      if (w.ok && r.ok) msg.push(R + Wn > st.rf ? "R + W = " + R + " + " + Wn + " > RF " + st.rf + ": every read overlaps the latest write." : "R + W = " + R + " + " + Wn + " ≤ RF " + st.rf + ": a read may miss the latest write (eventually consistent).");
      else msg.push("A request that cannot reach enough replicas fails fast; it is not queued.");
      $("cl-overlap").textContent = msg.join("");
      drawRing();
    }
    $("cn-minus").addEventListener("click", function () { st.n--; draw(); });
    $("cn-plus").addEventListener("click", function () { st.n++; draw(); });
    $("rf-minus").addEventListener("click", function () { st.rf--; draw(); });
    $("rf-plus").addEventListener("click", function () { st.rf++; draw(); });
    $("cl-lab").addEventListener("click", function () { st = { n: 1, rf: 3, down: {}, w: "QUORUM", r: "ONE" }; wSeg.set("QUORUM"); rSeg.set("ONE"); draw(); });
    $("cl-healthy").addEventListener("click", function () { st = { n: 6, rf: 3, down: {}, w: "QUORUM", r: "QUORUM" }; wSeg.set("QUORUM"); rSeg.set("QUORUM"); draw(); });
    draw();
  })();

  barChart($("af-chart"), {
    title: "Rows read and returned, from the query trace", ariaLabel: "Rows read and returned by two Cassandra queries",
    series: READ_VS, tableFirst: "query",
    groups: [
      { label: "WHERE loan_id = 'L0000006'", bars: [
        { series: "read", value: rn("af_key", "read"), display: rv("af_key", "read"), tip: "one partition" },
        { series: "returned", value: rn("af_key", "read"), display: rv("af_key", "read") }] },
      { label: "amount_cents > 215000 ALLOW FILTERING", bars: [
        { series: "read", value: rn("af_filter_read", "read"), display: fmt(rn("af_filter_read", "read")), tip: "every token range" },
        { series: "returned", value: rn("af_filter", "returned"), display: rv("af_filter", "returned") }] }
    ]
  });

  // ------------------------------------------------------------------ DynamoDB calculator
  (function dynamo() {
    var Z = S.dynamodb.sizes;
    var lab = { items: rn("dd_items", "items"), size: Math.round(Z.table_bytes / Z.table_items), match: rn("dd_gsi", "count"), msize: Math.round(Z.match_bytes / Z.match_items) };
    $("ddb-size-hint").textContent = "From the generator: " + fmt(Z.table_bytes) + " bytes over " + fmt(Z.table_items) + " items";
    $("ddb-msize-hint").textContent = "From the generator: " + fmt(Z.match_bytes) + " bytes over " + Z.match_items + " items";
    function set(v) { $("ddb-items").value = v.items; $("ddb-size").value = v.size; $("ddb-match").value = v.match; $("ddb-msize").value = v.msize; draw(); }
    function val(id, min) { var x = Math.floor(Number($(id).value)); return isFinite(x) ? Math.max(min, x) : min; }
    function pagesOf(bytes) {
      var pages = [], MB = 1048576;
      while (bytes > MB) { pages.push(MB); bytes -= MB; }
      pages.push(bytes);
      return pages;
    }
    function draw() {
      var items = val("ddb-items", 1), size = val("ddb-size", 1), match = Math.min(val("ddb-match", 0), items), msize = val("ddb-msize", 1), runs = val("ddb-runs", 1);
      var strong = $("ddb-cons").value === "strong";
      var f = strong ? 1 : 0.5;
      var scanPages = pagesOf(items * size);
      var scanUnits = scanPages.reduce(function (a, p) { return a + Math.ceil(p / 4096); }, 0);
      var scan = scanUnits * f;
      var qPages = pagesOf(match * msize);
      var qUnits = qPages.reduce(function (a, p) { return a + Math.ceil(p / 4096); }, 0);
      var gsi = qUnits * 0.5;
      var ratio = gsi > 0 ? scan / gsi : Infinity;
      barChart($("ddb-chart"), {
        title: "Read capacity per run", sub: "The same " + fmt(match) + " items either way" + (isFinite(ratio) ? ": the scan costs " + fmt(Math.round(ratio)) + " times as much" : ""),
        series: [{ key: "rcu", label: "RCU", color: C.blue }], tableFirst: "request",
        extraCols: [{ label: "ScannedCount", get: function (g) { return g.scanned; } }, { label: "pages", get: function (g) { return g.pages; } }, { label: "RCU per day", get: function (g) { return g.day; } }],
        groups: [
          { label: "Scan + filter", scanned: fmt(items), pages: String(scanPages.length), day: fmt1(scan * runs),
            bars: [{ series: "rcu", value: scan, display: fmt1(scan) + " RCU", tip: "ScannedCount " + fmt(items) + ", Count " + fmt(match) + ", " + scanPages.length + (scanPages.length === 1 ? " page" : " pages") + "; " + fmt1(scan * runs) + " RCU per day" }] },
          { label: "Query on GSI1", scanned: fmt(match), pages: String(qPages.length), day: fmt1(gsi * runs),
            bars: [{ series: "rcu", value: gsi, display: fmt1(gsi) + " RCU", tip: "ScannedCount " + fmt(match) + ", Count " + fmt(match) + "; " + fmt1(gsi * runs) + " RCU per day" + (strong ? "; ConsistentRead is not allowed on a GSI" : "") }] }
        ]
      });
      var fl = clear($("ddb-formula"));
      append(fl, [
        "scan:  " + fmt(items) + " items × " + size + " B = " + fmt(items * size) + " B in " + scanPages.length + (scanPages.length === 1 ? " page" : " pages") + " of at most 1 MB", h("br"),
        "       " + scanPages.map(function (p) { return "⌈" + fmt(p) + " / 4096⌉"; }).join(" + ") + " = " + fmt(scanUnits) + " units × " + f + " = " + fmt1(scan) + " RCU", h("br"),
        "query: " + fmt(match) + " items × " + msize + " B = " + fmt(match * msize) + " B; ⌈" + fmt(match * msize) + " / 4096⌉ = " + qUnits + " units × 0.5 = " + fmt1(gsi) + " RCU", h("br"),
        "per day (" + runs + " runs): scan " + fmt1(scan * runs) + " RCU, query " + fmt1(gsi * runs) + " RCU"
      ]);
    }
    ["ddb-items", "ddb-size", "ddb-match", "ddb-msize", "ddb-runs", "ddb-cons"].forEach(function (id) { $(id).addEventListener("input", draw); $(id).addEventListener("change", draw); });
    $("ddb-preset").addEventListener("click", function () { $("ddb-cons").value = "eventual"; set(lab); });
    $("ddb-x100").addEventListener("click", function () { set({ items: lab.items * 100, size: lab.size, match: lab.match * 100, msize: lab.msize }); });
    var vs = $("ddb-lab");
    vs.appendChild(h("div", { class: "stat" }, h("b", null, rv("dd_scan", "rcu")), h("span", null, "RCU, Scan + filter: ScannedCount " + fmt(rn("dd_scan", "scanned")) + ", Count " + rv("dd_scan", "count") + ", " + rv("dd_scan", "pages") + " pages")));
    vs.appendChild(h("div", { class: "stat" }, h("b", null, rv("dd_gsi", "rcu")), h("span", null, "RCU, Query on GSI1: ScannedCount " + rv("dd_gsi", "scanned") + ", Count " + rv("dd_gsi", "count"))));
    $("ddb-compare").textContent = "With the generator's real item sizes and the documented rules, the calculator gives " + fmt1(Z.scan_rcu_estimate) + " RCU for the scan and " +
      fmt1(Z.gsi_rcu_estimate) + " for the query. DynamoDB Local reported " + rv("dd_scan", "rcu") + " and " + rv("dd_gsi", "rcu") + ": the size formula is an approximation, and the gap is under 1%.";
    set(lab);
  })();

  // ------------------------------------------------------------------ Capstone
  (function capstone() {
    var runs = [
      { value: "run1", label: "Run 1 · 20 June" },
      { value: "run2", label: "Run 2 · 31 Dec" },
      { value: "run3", label: "Re-run" },
      { value: "backfill", label: "March backfill" },
      { value: "final", label: "Model and reconcile" }
    ];
    var cur = "final", sel = "raw_cass";
    var b1 = REC.cp_before1.values, b2 = REC.cp_before2.values, r1 = REC.cp_run1.values, r2 = REC.cp_run2.values, r3 = REC.cp_run3.values;
    function n(x) { return fmt(Number(x)); }
    var notModel = "built once, after the backfill";
    var NODES = {
      redis: { col: 0, name: "Redis stream and dedup keys", accent: "--redis", ch: 3,
        ct: { run1: n(b1.deliveries) + " deliveries", run2: n(b2.deliveries) + " deliveries", run3: "no new deliveries", backfill: "no new deliveries", final: n(rv("rc_dedup", "source")) + " dedup keys" },
        detail: "The payment gateway XADDs every payment, about 3% of them twice (at least once). worker-1 reads 200 entries and crashes; worker-2 processes the rest and XAUTOCLAIMs them. Before run 1: " + n(b1.deliveries) + " deliveries, " + b1.redelivered + " redelivered, " + b1.dups + " duplicates skipped, " + n(b1.written) + " events written. Before run 2: " + n(b2.deliveries) + ", " + b2.redelivered + ", " + b2.dups + ", " + n(b2.written) + "." },
      mongo: { col: 0, name: "MongoDB applications", accent: "--mongo", ch: 2,
        ct: { run1: n(b1.apps_new) + " applications", run2: "+" + b2.apps_new + " new, " + b2.apps_changed + " changed, " + b2.erased + " erased", run3: "no changes", backfill: "no changes", final: n(rv("rc_apps", "source")) + " applications" },
        detail: "Application documents with the loan embedded once funded. Between the runs " + b2.apps_new + " are new, " + b2.apps_changed + " changed and " + b2.erased + " hard-deleted after erasure requests: " + rv("cp_erased", "ids") + "." },
      cass: { col: 0, name: "Cassandra payment events", accent: "--cass", ch: 4,
        ct: { run1: n(b1.written) + " events written", run2: n(b2.written) + " events written", run3: "no changes", backfill: "no changes", final: n(rv("rc_events", "source")) + " events, " + rv("rc_counters", "source") + " daily counters" },
        detail: "payment_events_by_day and _by_loan, plus a per-day counter table. Counters are not idempotent (events + 1 twice is 2), which is why the dedup keys matter: " + n(b1.written) + " + " + n(b2.written) + " = " + n(rv("rc_events", "source")) + " events." },
      neo: { col: 0, name: "Neo4j identity graph", accent: "--neo", ch: 6,
        ct: { run1: n(r1.edges) + " edges", run2: n(r2.edges) + " edges", run3: n(r3.edges) + " edges", backfill: n(r3.edges) + " edges", final: n(rv("rc_edges", "source")) + " edges" },
        detail: "Applications linked by phone, device and address, synced from MongoDB." },
      x_mongo: { col: 1, name: "Watermark + key scan", accent: "--mongo", ch: 7,
        ct: { run1: n(r1.mongo) + " rows read", run2: r2.mongo + " rows, " + r2.deletes + " deletes found", run3: r3.mongo + " rows read", backfill: "not part of the backfill", final: "window (previous watermark, source max]" },
        detail: "Reads (previous watermark, source max updated_at] with a projection, so names, dates of birth, emails and phones never leave the source. The file is named after the window, so a re-run overwrites it. Then it compares the set of _ids: " + rv("cp_erased", "detected") + " erasures detected, because a watermark can never see a hard delete." },
      x_cass: { col: 1, name: "Day partitions + 3-day lookback", accent: "--cass", ch: 4,
        ct: { run1: r1.partitions + " partitions, " + n(r1.payments) + " rows", run2: r2.partitions + " partitions, " + n(r2.payments) + " rows", run3: r3.partitions + " partitions, " + r3.payments + " rows", backfill: rv("cp_backfill", "partitions") + " partitions, " + rv("cp_backfill", "rows") + " rows", final: "one Parquet file per day" },
        detail: "Reads whole day partitions from 3 days before the last extracted day and overwrites one file per day. Run 1: " + r1.days + "; run 2: " + r2.days + "; re-run: " + r3.days + ". The lookback picked up " + rv("cp_late", "late") + " late events paid before 20 June that arrived after run 1." },
      x_neo: { col: 1, name: "Snapshot", accent: "--neo", ch: 6,
        ct: { run1: n(r1.edges) + " edges", run2: n(r2.edges) + " edges", run3: n(r3.edges) + " edges", backfill: "not part of the backfill", final: "latest snapshot wins" },
        detail: "The graph is small, so each run exports every edge to snapshot=<date>/. Re-running on the same date overwrites the same snapshot." },
      raw_mongo: { col: 2, name: "raw/mongo/applications", accent: "--mongo", ch: 7,
        ct: { run1: n(r1.mongo) + " rows", run2: n(rv("cp_raw_mongo", "rows")) + " rows", run3: n(rv("cp_raw_mongo", "rows")) + " rows, unchanged", backfill: n(rv("cp_raw_mongo", "rows")) + " rows, unchanged", final: n(rv("cp_raw_mongo", "rows")) + " rows" },
        detail: "Every version extracted, on purpose: " + n(r1.mongo) + " + " + r2.mongo + " = " + n(rv("cp_raw_mongo", "rows")) + " rows for " + fmt(D.summary.applications) + " applications. Checksum before and after the re-run and the backfill: " + rv("cp_raw_mongo", "checksum") + ". Deletes go to raw/mongo/applications_deleted/." },
      raw_cass: { col: 2, name: "raw/cassandra/payment_events", accent: "--cass", ch: 7,
        ct: { run1: n(r1.payments) + " rows", run2: n(rv("cp_raw_cass", "rows")) + " rows", run3: n(rv("cp_raw_cass", "rows")) + " rows, unchanged", backfill: n(rv("cp_raw_cass", "rows")) + " rows, unchanged", final: n(rv("cp_raw_cass", "rows")) + " rows" },
        detail: "event_day=YYYY-MM-DD/part-0.parquet. Extracting a day twice produces the same file at the same path, so the re-run and the March backfill (" + rv("cp_backfill", "partitions") + " days, " + rv("cp_backfill", "rows") + " rows) leave " + n(rv("cp_raw_cass", "rows")) + " rows, checksum " + rv("cp_raw_cass", "checksum") + "." },
      raw_neo: { col: 2, name: "raw/neo4j/identity_edges", accent: "--neo", ch: 7,
        ct: { run1: n(r1.edges) + " edges", run2: n(r2.edges) + " edges", run3: n(r3.edges) + " edges", backfill: n(r3.edges) + " edges", final: n(rv("rc_edges", "lake")) + " edges" },
        detail: "One snapshot per run date. The model uses the latest." },
      m_apps: { col: 3, name: "applications_current, loans", accent: "--grey", ch: 7,
        ct: { run1: notModel, run2: notModel, run3: notModel, backfill: notModel, final: n(rv("rc_apps", "lake")) + " applications, " + n(rv("rc_loans", "lake")) + " loans" },
        detail: "The latest version of each application (row_number() over updated_at), minus detected deletes: " + fmt(D.summary.applications) + " generated minus the " + rv("cp_erased", "detected") + " erased. loans holds the flattened loan__* columns." },
      m_events: { col: 3, name: "payment_events, identity_groups", accent: "--grey", ch: 7,
        ct: { run1: notModel, run2: notModel, run3: notModel, backfill: notModel, final: n(rv("rc_events", "lake")) + " events" },
        detail: "All day partitions, deduplicated on event_id as a guard; " + n(rv("rc_events", "lake")) + " events, not " + fmt(D.summary.payment_events) + ": two paid on 30 and 31 December had not reached the lender yet. identity_groups are connected components of the edges." },
      m_marts: { col: 3, name: "fct_loan, mart_delinquency", accent: "--grey", ch: 7,
        ct: { run1: notModel, run2: notModel, run3: notModel, backfill: notModel, final: n(rv("rc_loans", "lake")) + " loans, with DPD and ring_flag" },
        detail: "One row per loan as of 31 December 2025: instalments due and paid, arrears, days past due and its bucket, and a ring_flag for loans in an identity group of 3 or more borrowers. The lake afterwards: " + rv("cp_lake", "files") + " Parquet files, " + rv("cp_lake", "size") + "." }
    };
    var COLS = ["Operational systems", "Extract", "Raw lake (Parquet)", "DuckDB model and marts"];
    var buttons = {};
    function draw() {
      var pipe = clear($("cap-pipe"));
      COLS.forEach(function (title, ci) {
        var col = h("div", { class: "pipe-col" }, h("h4", null, title));
        Object.keys(NODES).forEach(function (k) {
          var nd = NODES[k];
          if (nd.col !== ci) return;
          var b = h("button", { class: "pnode", type: "button", "aria-pressed": String(k === sel), style: "--accent: var(" + nd.accent + ")" },
            h("span", { class: "nm" }, nd.name), h("span", { class: "ct" }, nd.ct[cur]));
          b.addEventListener("click", function () {
            sel = k; draw(); buttons[k].focus();
            if (window.innerWidth < 860) $("cap-detail").scrollIntoView({ block: "nearest", behavior: reduceMotion ? "auto" : "smooth" });
          });
          buttons[k] = b;
          col.appendChild(b);
        });
        pipe.appendChild(col);
      });
      var nd = NODES[sel];
      var det = clear($("cap-detail"));
      append(det, [h("div", { class: "card-head", style: "margin-bottom:6px" }, h("h3", null, nd.name), h("span", { class: "small mono muted" }, nd.ct[cur])),
        h("p", { class: "small", style: "margin:0 0 8px" }, nd.detail),
        h("a", { class: "small", href: D.links["ch" + nd.ch], target: "_blank", rel: "noopener" }, "Chapter " + nd.ch + " ↗")]);
    }
    radioGroup($("cap-runs"), runs, cur, function (v) { cur = v; draw(); animateIn($("cap-pipe")); });
    draw();

    var recon = $("recon-list");
    ["rc_apps", "rc_loans", "rc_events", "rc_counters", "rc_edges", "rc_dedup"].forEach(function (id) {
      var r = REC[id];
      recon.appendChild(h("li", null, h("span", { class: "okb" }, "OK"), h("span", null, r.label),
        h("span", { class: "n" }, "source " + fmt(Number(r.values.source)) + " · lake " + fmt(Number(r.values.lake)) + " · checksum match")));
    });
    $("recon-verdict").textContent = "✓ " + rv("rc_summary", "ok") + " OK";

    var buckets = [["current", "dpd_current"], ["1-29", "dpd_1_29"], ["30-59", "dpd_30_59"], ["60-89", "dpd_60_89"], ["90+", "dpd_90"]];
    barChart($("dpd-chart"), {
      title: "Loans by days past due", sub: fmt(rn("rc_loans", "lake")) + " loans in fct_loan", tableFirst: "bucket",
      series: [{ key: "loans", label: "loans", color: C.blue }],
      extraCols: [{ label: "arrears", get: function (g) { return g.arrears; } }],
      groups: buckets.map(function (b) {
        var v = REC[b[1]].values;
        return { label: b[0] + (b[0] === "current" ? "" : " days"), arrears: Number(v.arrears).toLocaleString("en-US", { minimumFractionDigits: 2 }),
          bars: [{ series: "loans", value: Number(v.loans), display: fmt(Number(v.loans)), tip: "arrears " + Number(v.arrears).toLocaleString("en-US", { minimumFractionDigits: 2 }) }] };
      })
    });
    var rt = REC.ring_true.values, rf = REC.ring_false.values;
    barChart($("ring-chart"), {
      title: "Share 30+ days past due, by ring flag", sub: rt.loans + " ring-flagged loans, " + fmt(Number(rf.loans)) + " others", tableFirst: "loans", max: 1,
      series: [{ key: "ring", label: "ring-flagged", color: C.orange }, { key: "rest", label: "not flagged", color: C.blue }],
      groups: [
        { label: "Ring-flagged", bars: [{ series: "ring", value: Number(rt.share), display: pct(Number(rt.share), 1), tip: "share " + rt.share + " of " + rt.loans + " loans" }] },
        { label: "Not flagged", bars: [{ series: "rest", value: Number(rf.share), display: pct(Number(rf.share), 1), tip: "share " + rf.share + " of " + fmt(Number(rf.loans)) + " loans" }] }
      ]
    });
  })();

  // ------------------------------------------------------------------ Which database?
  (function wizard() {
    var Q = {
      q1: { text: "Will people ask new questions that join many entities?", choices: [
        { label: "Yes, finance, risk or regulators will ask things nobody planned", to: "pg" },
        { label: "No, the queries are known", to: "q2" }] },
      q2: { text: "What is the main read?", choices: [
        { label: "One value by key, sub-millisecond, may expire", to: "redis" },
        { label: "A whole nested object, plus a few secondary filters", to: "mongo" },
        { label: "A key range in a huge, write-heavy, multi-region dataset", to: "q3" },
        { label: "Paths and neighbourhoods, many hops deep", to: "neo" },
        { label: "Free text with relevance", to: "search" },
        { label: "Metrics over time windows", to: "ts" }] },
      q3: { text: "Run it yourself?", choices: [
        { label: "Yes", to: "cass" },
        { label: "No, on AWS", to: "ddb" }] }
    };
    var A = {
      pg: { name: "Relational database", sub: "Keep it; feed a warehouse.", accent: "--grey", ch: "ch1",
        why: "A normalised schema plus SQL answers questions nobody planned. A key-designed store answers only the questions its keys were designed for.",
        pain: "Choosing NoSQL for scale you do not have: a single PostgreSQL server handles a great deal.", section: null },
      redis: { name: "Redis / Valkey", sub: "Cache, dedup, rate limits, small queues.", accent: "--redis", ch: "ch3",
        why: "Every value lives under a key, in memory, served by single atomic commands.",
        pain: "Volatility and eviction. With default persistence AOF is off, and an allkeys-* policy evicts dedup keys as readily as cache entries.", section: "#redis" },
      mongo: { name: "MongoDB", sub: "Whole nested objects, read by several fields.", accent: "--mongo", ch: "ch2",
        why: "Embed what is read together; secondary indexes serve the few other filters.",
        pain: "Schema drift, and deletes that a watermark cannot see. Plan an index on the watermark field, or change streams, before go-live.", section: "#mongodb" },
      cass: { name: "Cassandra", sub: "Key ranges in huge, write-heavy data, self-managed.", accent: "--cass", ch: "ch4",
        why: "Query-first tables: each query reads one partition and a range of clustering keys.",
        pain: "Full scans, tombstones and no ad-hoc queries. A low-cardinality partition key makes a hot partition.", section: "#cassandra" },
      ddb: { name: "DynamoDB", sub: "The same model, managed on AWS.", accent: "--dynamo", ch: "ch5",
        why: "Partition key plus sort key, one GetItem or Query per access pattern, GSIs for the rest.",
        pain: "Scan cost, 1 MB pages and single-table design. A bad key design shows up directly on the bill.", section: "#dynamodb" },
      neo: { name: "Neo4j", sub: "Paths and neighbourhoods, many hops deep.", accent: "--neo", ch: "ch6",
        why: "Relationships are stored, so following one costs the same however big the graph is.",
        pain: "Getting graph results into tables. For one-off analysis, exporting edges and using a recursive CTE or union-find in the warehouse is often enough.", section: "#shapes" },
      search: { name: "Search engine", sub: "OpenSearch, Elasticsearch: free text with relevance.", accent: "--grey", ch: "ch8",
        why: "An inverted index from terms to documents gives fast full-text search and ranking.",
        pain: "It is a derived store: idempotent indexing by source id, deletes, and full reindexing behind an alias when mappings change.", section: null },
      ts: { name: "Time-series database", sub: "Or a columnar warehouse.", accent: "--grey", ch: "ch8",
        why: "Optimised for appends, time-range queries, roll-ups and retention that drops whole chunks.",
        pain: "For business events a columnar warehouse or Parquet partitioned by day, as in the capstone, is often enough.", section: null }
    };
    var trail = [];
    var node = "q1";
    var CHECKS = ["Can I write down the primary key of every query?", "What happens to a write during a failure?",
      "How will the data get to analytics?", "Who operates it at 3 a.m.?"];
    function draw(focus) {
      var qEl = clear($("wiz-q")), aEl = clear($("wiz-a"));
      if (trail.length) qEl.appendChild(h("ul", { class: "trail", "aria-label": "Your answers" }, trail.map(function (t) { return h("li", null, t); })));
      if (Q[node]) {
        var q = Q[node];
        qEl.appendChild(h("p", { class: "small muted", style: "margin:0 0 4px" }, "Question " + (trail.length + 1)));
        var title = h("p", { class: "q-title", tabindex: "-1" }, q.text);
        qEl.appendChild(title);
        qEl.appendChild(h("div", { class: "choices" }, q.choices.map(function (c) {
          return h("button", { class: "choice", type: "button", onclick: function () { trail.push(c.label); node = c.to; draw(true); } },
            h("span", null, c.label), h("span", { class: "arrow", "aria-hidden": "true" }, "→"));
        })));
        if (focus) title.focus();
        aEl.appendChild(h("h3", null, "Then sanity-check the choice"));
        aEl.appendChild(h("ol", { class: "checklist" }, CHECKS.map(function (c) { return h("li", null, c); })));
        aEl.appendChild(h("p", { class: "small muted" }, "A useful rule from chapter 1: choose NoSQL for a specific access pattern that a relational database serves badly, not as a general replacement."));
      } else {
        var a = A[node];
        qEl.appendChild(h("p", { class: "small muted", style: "margin:0 0 4px" }, "Done in " + trail.length + (trail.length === 1 ? " question" : " questions")));
        qEl.appendChild(h("div", { class: "ctl" },
          h("button", { class: "btn small", type: "button", onclick: function () { trail.pop(); node = back(); draw(true); } }, "Back"),
          h("button", { class: "btn small", type: "button", onclick: function () { trail = []; node = "q1"; draw(true); } }, "Start again")));
        var res = h("div", { class: "answer", style: "--accent: var(" + a.accent + ")" },
          h("span", { class: "pill" }, "the decision guide points to"),
          h("h3", { tabindex: "-1" }, a.name),
          h("p", { class: "muted" }, a.sub),
          h("p", null, a.why),
          h("p", { class: "note small" }, h("strong", null, "Typical data engineering pain: "), a.pain),
          h("div", { class: "ctl", style: "margin-top:12px" },
            h("a", { class: "btn small primary", href: D.links[a.ch], target: "_blank", rel: "noopener" }, "Read chapter " + a.ch.slice(2) + " ↗"),
            a.section ? h("a", { class: "btn small", href: a.section }, "Try it above") : null,
            h("a", { class: "btn small", href: D.links.comparison, target: "_blank", rel: "noopener" }, "Comparison table ↗")));
        aEl.appendChild(res);
        aEl.appendChild(h("h4", { style: "margin-top:18px" }, "Before committing, answer these"));
        aEl.appendChild(h("ol", { class: "checklist" }, CHECKS.map(function (c) { return h("li", null, c); })));
        if (focus) res.querySelector("h3").focus();
        animateIn(aEl);
      }
    }
    function back() {
      var n = "q1";
      trail.forEach(function (label) {
        var q = Q[n];
        if (!q) return;
        var c = q.choices.filter(function (x) { return x.label === label; })[0];
        if (c) n = c.to;
      });
      return n;
    }
    draw(false);
  })();

  // ------------------------------------------------------------------ provenance
  (function provenance() {
    var t = $("prov-table");
    t.appendChild(h("thead", null, h("tr", null, ["chapter", "step", "result", "line quoted in the guide"].map(function (c) { return h("th", { scope: "col" }, c); }))));
    var tb = h("tbody");
    D.recorded.forEach(function (r) {
      var ch = r.chapter.slice(0, 2);
      tb.appendChild(h("tr", null,
        h("td", null, h("a", { href: D.links["ch" + Number(ch)], target: "_blank", rel: "noopener" }, "ch. " + Number(ch))),
        h("td", { class: "mono" }, r.step),
        h("td", null, r.label),
        h("td", { class: "ctx" }, r.context)));
    });
    t.appendChild(tb);
    $("prov-summary").textContent = "Every recorded result (" + D.recorded.length + "), with the line it comes from";
  })();

  // Sections are drawn by this script, so a link such as #capstone could not scroll
  // before they existed. Jump once everything above has rendered.
  if (location.hash.length > 1) {
    var target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (target) target.scrollIntoView();
  }
})();
