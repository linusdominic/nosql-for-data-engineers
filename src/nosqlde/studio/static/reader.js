/* NoSQL lesson studio: the guide reader and the read-only file viewer. Vanilla JS.
   The server renders each chapter (nosqlde.studio.reader) with raw HTML escaped; this file
   adds the table of contents, scroll-spy, reading progress, copy buttons, heading links,
   Open in console, search and prev/next. Routes: #/read/NN[/anchor] and #/file/<path>. */
(function () {
  "use strict";

  var S = window.NosqlStudio;
  if (!S) return;
  var h = S.h, clear = S.clear, icon = S.icon;

  var cur = null; // {kind: "chapter", id, data} or {kind: "file", path}
  var scrolls = {}; // chapter id -> scrollTop, for coming back to where you were
  var spyFrame = 0;
  var lastLayout = null;

  function $(id) { return document.getElementById(id); }
  function pane() { return $("reader"); }
  function body() { return $("reader-body"); }
  function narrow() { return window.matchMedia("(max-width: 980px)").matches; }
  // The element that scrolls: the reader pane on wide screens, the page on narrow ones.
  function scroller() { return narrow() ? document.scrollingElement : pane(); }
  function decode(s) { try { return decodeURIComponent(s); } catch (e) { return s; } }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var ta = h("textarea", { "aria-hidden": "true", readonly: true });
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      if (ok) resolve(); else reject(new Error("copy failed"));
    });
  }

  function failed(err) {
    if (err && err.status === 401) { S.gate("The studio token is missing or stale."); return; }
    clear(body()).appendChild(h("div", { class: "doc" }, h("p", { class: "callout bad", role: "alert", text: (err && err.message) || "Something went wrong." })));
  }

  // ------------------------------------------------------------ the bar above the reader
  function renderBar(opts) {
    lastLayout = S.state.readerLayout;
    var bar = clear($("reader-bar"));
    var left = h("div", { class: "rb-left" });
    var from = S.state.readerFrom;
    if (opts.back) left.appendChild(h("a", { class: "btn small ghost back", href: opts.back.href, onclick: opts.back.onclick }, icon("back"), h("span", { class: "ell", text: opts.back.label })));
    else if (from) left.appendChild(h("a", { class: "btn small ghost back", href: from.hash, title: from.label }, icon("back"), h("span", { class: "ell", text: from.label })));
    left.appendChild(h("span", { class: "rb-title", text: opts.title }));
    var right = h("div", { class: "rb-right" });
    if (opts.lesson) right.appendChild(h("a", { class: "btn small ghost", href: opts.lesson.href, title: opts.lesson.title }, h("span", null, "Exercises", h("span", { class: "wide-only", text: " for this chapter" }))));
    var wide = S.state.readerLayout === "wide";
    right.appendChild(h("button", {
      type: "button", class: "btn small", "aria-pressed": String(!wide), id: "layout-toggle",
      title: wide ? "Read next to the console" : "Hide the console and read full width",
      onclick: function () { S.setReaderLayout(S.state.readerLayout === "wide" ? "split" : "wide", true); },
    }, icon(wide ? "split" : "wide"), wide ? "Show console" : "Hide console"));
    bar.appendChild(h("div", { class: "rb-row" }, left, right));
    bar.appendChild(h("div", { class: "read-progress", "aria-hidden": "true" }, h("i", { id: "read-progress" })));
  }

  function lessonLink(chapterId) {
    var from = S.state.readerFrom;
    if (from && from.lesson === "ch" + chapterId) return null; // the back button already goes there
    var l = S.lessonMeta("ch" + chapterId);
    if (!l) return null;
    return { href: "#/" + l.id, title: "Chapter " + chapterId + " as a lesson, with checked exercises" };
  }

  // ------------------------------------------------------------ chapters
  function open(chapterId, anchor) {
    if (!/^\d\d$/.test(chapterId)) chapterId = "00";
    anchor = decode(anchor || "");
    S.state.reading = { chapter: chapterId };
    if (cur && cur.kind === "chapter" && cur.id === chapterId) {
      S.renderNav();
      renderBar(barOpts(cur.data));
      if (anchor) goTo(anchor, true); else scroller().scrollTop = scrolls[chapterId] || 0;
      return;
    }
    saveScroll();
    S.renderNav();
    return S.api("/api/guide/" + chapterId).then(function (data) {
      cur = { kind: "chapter", id: chapterId, data: data };
      S.store.set("last-read", chapterId);
      document.title = "Chapter " + data.id + ": " + data.title + " · NoSQL lesson studio";
      draw(data);
      if (anchor) goTo(anchor, false);
      else scroller().scrollTop = scrolls[chapterId] || 0;
      spy();
    }).catch(failed);
  }

  function barOpts(data) {
    return { title: "Chapter " + data.id + " · " + data.title, lesson: lessonLink(data.id) };
  }

  function saveScroll() {
    if (cur && cur.kind === "chapter") scrolls[cur.id] = scroller().scrollTop;
  }

  function draw(data) {
    renderBar(barOpts(data));
    var root = clear(body());
    root.className = "reader-body";

    var tocList = h("ol", { class: "toc-list" });
    data.toc.forEach(function (t) {
      tocList.appendChild(h("li", { class: "toc-l" + t.level }, h("a", { href: "#/read/" + data.id + "/" + t.id, "data-id": t.id, text: t.text })));
    });
    var toc = h("details", { class: "toc", id: "toc" },
      h("summary", null, h("span", { text: "On this page" }), h("span", { class: "toc-count", text: data.toc.length + " sections" })),
      tocList);

    var article = h("article", { class: "doc", id: "doc" });
    article.appendChild(h("p", { class: "kicker" }, h("span", { class: "dot" }), "Guide · chapter " + data.id + " · " + data.file));
    var content = h("div", { class: "doc-content", html: data.html }); // server-rendered; raw HTML in the Markdown is escaped
    article.appendChild(content);
    var h1 = content.querySelector("h1[id]");
    if (h1) article.setAttribute("aria-labelledby", h1.id);
    else article.removeAttribute("aria-labelledby");

    var nav = h("nav", { class: "chapter-nav", "aria-label": "Previous and next chapter" });
    nav.appendChild(data.prev ? h("a", { class: "cn prev", href: "#/read/" + data.prev.id }, h("span", { class: "cn-k", text: "Previous" }), h("span", { class: "cn-t", text: data.prev.id + ". " + data.prev.title })) : h("span"));
    nav.appendChild(data.next ? h("a", { class: "cn next", href: "#/read/" + data.next.id }, h("span", { class: "cn-k", text: "Next" }), h("span", { class: "cn-t", text: data.next.id + ". " + data.next.title })) : h("span"));
    article.appendChild(nav);

    root.appendChild(toc);
    root.appendChild(article);
    sizeDiagrams(article);
    layoutChanged();
  }

  // Wide diagrams (the capstone's is 2,930 px) keep at least 64% of their size and scroll
  // sideways, so their text stays readable; a click (or Enlarge) shows one at full size.
  function sizeDiagrams(root) {
    root.querySelectorAll("figure.diagram").forEach(function (fig) {
      var imgs = fig.querySelectorAll("img");
      if (!imgs.length) return;
      imgs.forEach(function (im) {
        var w = parseFloat(im.getAttribute("width") || "0");
        if (w) { im.style.setProperty("--nw", String(w)); fig.style.setProperty("--nw", String(w)); }
        im.addEventListener("click", function () { enlarge(im); });
      });
      var links = h("div", { class: "diagram-links" },
        h("button", { type: "button", class: "btn small ghost", onclick: function () {
          var shown = Array.prototype.find.call(imgs, function (im) { return im.offsetParent !== null; }) || imgs[0];
          enlarge(shown);
        } }, "Enlarge"));
      fig.insertBefore(links, fig.querySelector("details"));
    });
  }

  function enlarge(img) {
    var dlg = $("diagram-dialog");
    if (!dlg) {
      dlg = h("dialog", { class: "diagram-dialog", id: "diagram-dialog", "aria-label": "Diagram at full size" });
      dlg.addEventListener("click", function (e) { if (e.target === dlg || e.target.closest("[data-close]")) dlg.close(); });
      document.body.appendChild(dlg);
    }
    clear(dlg).appendChild(h("div", { class: "dd-bar" },
      h("span", { text: "Full size. Scroll to pan; Esc closes." }),
      h("button", { type: "button", class: "btn small", "data-close": "1", text: "Close" })));
    var big = h("img", { src: img.getAttribute("src"), alt: img.getAttribute("alt") || "", width: img.getAttribute("width"), height: img.getAttribute("height") });
    dlg.appendChild(h("div", { class: "dd-body" }, big));
    dlg.showModal();
  }

  function goTo(anchor, smooth) {
    var el = anchor && document.getElementById(anchor);
    if (!el || !body().contains(el)) { scroller().scrollTop = 0; return; }
    el.scrollIntoView({ block: "start", behavior: smooth ? "smooth" : "auto" });
    var old = body().querySelector(".is-target");
    if (old) old.classList.remove("is-target");
    el.classList.add("is-target");
    setTimeout(function () { el.classList.remove("is-target"); }, 1800);
  }

  // A diagram wider than its box starts scrolled to its middle, where flowcharts begin.
  function centreDiagrams() {
    body().querySelectorAll(".diagram-scroll").forEach(function (box) {
      var extra = box.scrollWidth - box.clientWidth;
      if (extra > 0 && !box.dataset.centred) { box.scrollLeft = extra / 2; box.dataset.centred = "1"; }
    });
  }

  function layoutChanged() {
    var toc = $("toc");
    var wide = S.state.readerLayout === "wide" && !narrow();
    if (toc) {
      toc.open = wide;
      toc.classList.toggle("side", wide);
    }
    var root = body();
    if (root) root.classList.toggle("with-toc", wide && !!toc);
    if (cur && lastLayout !== S.state.readerLayout) renderBar(cur.kind === "chapter" ? barOpts(cur.data) : fileBarOpts(cur.path));
    lastLayout = S.state.readerLayout;
    requestAnimationFrame(centreDiagrams);
    spy();
  }

  // ------------------------------------------------------------ scroll-spy and progress
  function spy() {
    if (spyFrame) return;
    spyFrame = requestAnimationFrame(function () {
      spyFrame = 0;
      if (S.state.view !== "reader") return;
      var sc = scroller();
      var bar = $("read-progress");
      var max = sc.scrollHeight - sc.clientHeight;
      var p = max > 0 ? Math.min(1, Math.max(0, sc.scrollTop / max)) : 1;
      if (bar) bar.style.width = (p * 100).toFixed(1) + "%";
      if (cur && cur.kind === "chapter") scrolls[cur.id] = sc.scrollTop;
      var toc = $("toc");
      if (!toc || !cur || cur.kind !== "chapter") return;
      var top = narrow() ? 160 : pane().getBoundingClientRect().top + Math.min(240, pane().clientHeight * 0.3);
      var active = null;
      body().querySelectorAll(".doc-content h2[id], .doc-content h3[id]").forEach(function (hd) {
        if (hd.getBoundingClientRect().top <= top) active = hd.id;
      });
      if (!active) { var first = data0(); active = first; }
      toc.querySelectorAll("a[data-id]").forEach(function (a) {
        var on = a.getAttribute("data-id") === active;
        if (on) a.setAttribute("aria-current", "location"); else a.removeAttribute("aria-current");
        if (on && toc.classList.contains("side")) {
          var r = a.getBoundingClientRect(), tr = toc.getBoundingClientRect();
          if (r.top < tr.top + 40 || r.bottom > tr.bottom - 20) toc.scrollTop += r.top - tr.top - tr.height / 3;
        }
      });
    });
  }
  function data0() { return cur && cur.data && cur.data.toc.length ? cur.data.toc[0].id : null; }
  pane().addEventListener("scroll", spy, { passive: true });
  window.addEventListener("scroll", spy, { passive: true });
  window.addEventListener("resize", function () { layoutChanged(); });

  // ------------------------------------------------------------ clicks inside the reader
  body().addEventListener("click", function (e) {
    var t = e.target.closest ? e.target.closest("button, a") : null;
    if (!t || !body().contains(t)) return;
    var action = t.getAttribute("data-action");
    if (action === "copy" || action === "console") {
      var block = t.closest(".codeblock");
      var code = block ? block.querySelector("pre code").textContent : "";
      if (action === "copy") {
        copyText(code).then(function () {
          t.textContent = "Copied";
          setTimeout(function () { t.textContent = "Copy"; }, 1400);
        }, function () { S.toast("Could not copy: select the text and copy it by hand."); });
      } else {
        S.openInConsole(t.getAttribute("data-console"), code);
      }
      return;
    }
    if (t.classList.contains("h-anchor")) {
      e.preventDefault();
      var href = t.getAttribute("href");
      // the link carries no token: the token stays in this tab's sessionStorage
      var url = location.origin + "/" + href;
      window.history.replaceState(null, "", href);
      S.renderNav();
      goTo(t.getAttribute("data-anchor"), true);
      copyText(url).then(function () { S.toast("Link copied: " + url); }, function () { S.toast(url); });
      return;
    }
    var toc = t.closest(".toc");
    if (toc && !toc.classList.contains("side")) toc.open = false;
    // a link to the section already on screen: scroll there, even if the hash is unchanged
    var hrefAttr = t.getAttribute("href") || "";
    if (cur && cur.kind === "chapter" && hrefAttr === location.hash && hrefAttr.indexOf("#/read/" + cur.id + "/") === 0) {
      e.preventDefault();
      goTo(decode(hrefAttr.split("/").slice(3).join("/")), true);
    }
  });

  // ------------------------------------------------------------ the file viewer
  function fileBarOpts(path) {
    return {
      title: path,
      back: { href: "#/read/" + (S.store.get("last-read", "00")), label: "Back to the guide", onclick: function (e) {
        if (window.history.length > 1) { e.preventDefault(); window.history.back(); }
      } },
    };
  }

  function openFile(path) {
    path = decode(path).replace(/^\/+/, "");
    saveScroll();
    S.state.reading = { file: path };
    cur = { kind: "file", path: path };
    S.renderNav();
    renderBar(fileBarOpts(path));
    clear(body()).appendChild(h("div", { class: "doc file-doc" }, h("p", { class: "muted", text: "Loading " + path + "..." })));
    document.title = path + " · NoSQL lesson studio";
    return S.api("/api/file?path=" + encodeURIComponent(path)).then(function (res) {
      if (!cur || cur.kind !== "file" || cur.path !== path) return;
      drawFile(res);
      scroller().scrollTop = 0;
      spy();
    }).catch(function (err) {
      if (err && err.status === 401) { S.gate("The studio token is missing or stale."); return; }
      clear(body()).appendChild(h("div", { class: "doc file-doc" },
        crumbs(path),
        h("p", { class: "callout bad", role: "alert", text: err.message })));
    });
  }

  function crumbs(path) {
    var parts = path.split("/");
    var nav = h("nav", { class: "crumbs", "aria-label": "Path" });
    parts.forEach(function (p, i) {
      var sub = parts.slice(0, i + 1).join("/");
      if (i) nav.appendChild(h("span", { class: "sep", "aria-hidden": "true", text: "/" }));
      nav.appendChild(i === parts.length - 1 ? h("span", { class: "here", text: p }) : h("a", { href: "#/file/" + sub, text: p }));
    });
    return nav;
  }

  function drawFile(res) {
    var root = clear(body());
    root.className = "reader-body";
    var doc = h("div", { class: "doc file-doc" });
    doc.appendChild(h("p", { class: "kicker" }, h("span", { class: "dot" }), "Repository file · read-only"));
    doc.appendChild(crumbs(res.path));
    if (res.kind === "dir") {
      var list = h("ul", { class: "dir-list" });
      res.entries.forEach(function (e) {
        list.appendChild(h("li", null, h("a", { href: "#/file/" + e.path }, icon(e.kind === "dir" ? "folder" : "file"), h("span", { text: e.name + (e.kind === "dir" ? "/" : "") }))));
      });
      if (!res.entries.length) list.appendChild(h("li", { class: "muted", text: "Nothing to show here." }));
      doc.appendChild(list);
    } else {
      var meta = h("div", { class: "file-meta" },
        h("span", { text: res.lines + " line" + (res.lines === 1 ? "" : "s") + " · " + res.bytes.toLocaleString() + " bytes" }),
        h("button", { type: "button", class: "btn small ghost", onclick: function (e) {
          var b = e.currentTarget;
          copyText(res.text).then(function () { b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy file"; }, 1400); });
        } }, "Copy file"));
      var code = h("code");
      res.text.replace(/\n$/, "").split("\n").forEach(function (line) {
        code.appendChild(h("span", { class: "line", text: line }));
        code.appendChild(document.createTextNode("\n"));
      });
      doc.appendChild(h("div", { class: "codeblock file" }, h("div", { class: "codeblock-head" }, meta), h("pre", { class: "numbered", tabindex: "0" }, code)));
    }
    root.appendChild(doc);
  }

  // ------------------------------------------------------------ search
  var searchSeq = 0, searchTimer = null;
  var pop = $("search"), input = $("search-input"), results = $("search-results");

  function openSearch() {
    pop.hidden = false;
    $("search-open").setAttribute("aria-expanded", "true");
    input.focus();
    input.select();
    if (input.value) runSearch();
  }
  function closeSearch() {
    pop.hidden = true;
    $("search-open").setAttribute("aria-expanded", "false");
  }
  function marked(text, terms) {
    var frag = document.createDocumentFragment();
    if (!terms.length) { frag.appendChild(document.createTextNode(text)); return frag; }
    var re = new RegExp("(" + terms.map(function (t) { return t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }).join("|") + ")", "ig");
    text.split(re).forEach(function (part, i) {
      frag.appendChild(i % 2 ? h("mark", { text: part }) : document.createTextNode(part));
    });
    return frag;
  }
  function runSearch() {
    var q = input.value.trim();
    var seq = ++searchSeq;
    if (q.length < 2) { clear(results); return; }
    S.api("/api/search?q=" + encodeURIComponent(q)).then(function (res) {
      if (seq !== searchSeq) return;
      clear(results);
      var terms = q.toLowerCase().split(/\s+/).filter(Boolean);
      if (!res.results.length) { results.appendChild(h("li", { class: "none", text: "Nothing in the guide matches " + q + "." })); return; }
      res.results.forEach(function (r, i) {
        var a = h("a", { href: "#/read/" + String(r.chapter).padStart(2, "0") + (r.anchor ? "/" + r.anchor : ""), "data-first": i === 0 ? "1" : null, onclick: closeSearch },
          h("span", { class: "sr-where" }, h("span", { class: "num", text: String(r.chapter).padStart(2, "0") }), h("strong", null, marked(r.heading, terms))),
          h("span", { class: "sr-snippet" }, marked(r.snippet, terms)));
        results.appendChild(h("li", null, a));
      });
    }).catch(function (err) {
      if (seq !== searchSeq) return;
      clear(results).appendChild(h("li", { class: "none", text: err.message }));
    });
  }
  $("search-open").addEventListener("click", function () { if (pop.hidden) openSearch(); else closeSearch(); });
  input.addEventListener("input", function () { clearTimeout(searchTimer); searchTimer = setTimeout(runSearch, 140); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.preventDefault(); closeSearch(); $("search-open").focus(); return; }
    if (e.key === "Enter") {
      var first = results.querySelector("a[data-first]");
      if (first) { e.preventDefault(); location.hash = first.getAttribute("href"); closeSearch(); }
    }
    if (e.key === "ArrowDown") { var a = results.querySelector("a"); if (a) { e.preventDefault(); a.focus(); } }
  });
  results.addEventListener("keydown", function (e) {
    var links = Array.prototype.slice.call(results.querySelectorAll("a"));
    var i = links.indexOf(document.activeElement);
    if (e.key === "ArrowDown" && i >= 0 && i < links.length - 1) { e.preventDefault(); links[i + 1].focus(); }
    if (e.key === "ArrowUp" && i >= 0) { e.preventDefault(); if (i === 0) input.focus(); else links[i - 1].focus(); }
    if (e.key === "Escape") { closeSearch(); $("search-open").focus(); }
  });
  document.addEventListener("keydown", function (e) {
    var tag = (e.target && e.target.tagName) || "";
    var typing = tag === "INPUT" || tag === "TEXTAREA" || (e.target && e.target.isContentEditable);
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); openSearch(); }
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); openSearch(); }
  });
  document.addEventListener("click", function (e) {
    if (!pop.hidden && !pop.contains(e.target) && !$("search-open").contains(e.target)) closeSearch();
  });

  S.reader = { open: open, openFile: openFile, layoutChanged: layoutChanged };
})();
