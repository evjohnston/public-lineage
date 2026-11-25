/* Lineage Explorer: sociology advisor -> student network.
   Data: data/lineage.json, built by scripts/export_explorer.py. */
(() => {
  "use strict";

  const F = { OUTSIDE: 1, ISOLATED: 2, NO_ADVISOR: 4, MULTI_ADVISOR: 8, EDUC: 16, SMALL: 32, PROF_INST: 64, EDU_AREA: 128, DUP: 256, EXTERNAL: 512 };
  const SRC = { AFT: 1, NSF: 2, WIKIDATA: 4, DISS: 8 };
  const SRC_LABEL = { nsf_ddrig: "NSF dissertation grant", wikidata: "Wikidata", "theses.fr": "theses.fr" };
  const srcLabel = (s) => SRC_LABEL[s] || (s.startsWith("oai:") ? `Dissertation repository (${s.slice(4)})` : s);
  const PROFDOC = F.EDUC | F.PROF_INST | F.EDU_AREA;
  const INK = "#161616", RED = "#c8102e", FAINT = "#c9c6be", PAPER = "#ffffff", INK3 = "#6a6a67";
  const NODE_CAP = 450;
  // Colored pencils for "color by": validated all-pairs together with the reserved red and blue
  // pencils (CVD ΔE ≥ 9.1, normal ≥ 19.4). Max three categories; the rest fold into "Other".
  const CAT = ["#1baf7a", "#9b59b6", "#eda100"];
  // PhD cohort: one hue, light to dark, by decade (sequential; never a rainbow)
  const COHORT = [["≤1940", 0, 1949, "#f4ecd6"], ["1950s", 1950, 1959, "#eadbb0"], ["1960s", 1960, 1969, "#dcc387"], ["1970s", 1970, 1979, "#cba762"],
    ["1980s", 1980, 1989, "#b48942"], ["1990s", 1990, 1999, "#966c2b"], ["2000s", 2000, 2009, "#74511d"], ["2010s+", 2010, 9999, "#523812"]];
  const cohortOf = (y) => (y ? COHORT.findIndex(([, lo, hi]) => y >= lo && y <= hi) : -1);
  const YEAR_BASIS = { 1: "recorded", 2: "dissertation or grant record", 3: "from birth year", 4: "from first paper", 5: "estimated from advisors/students" };
  const OTHER_FILL = "#e9e6df";

  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fmt = (n) => (n ?? 0).toLocaleString("en-US");
  const norm = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
  const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many || one + "s"}`;

  const els = { stage: $("#stage"), cy: $("#cy"), map: $("#map"), sheet: $("#sheet"), toolbar: $("#toolbar"), panel: $("#panel"), legend: $("#legend"), colorkey: $("#colorkey"), credit: $("#credit") };

  /* ---------------------------------------------------------------- data */
  const P = new Map();       // pid -> person
  const kids = new Map();    // mentor -> [trainee]
  const parents = new Map(); // trainee -> [mentor]
  const relOf = new Map();   // "m>t" -> relation code
  const srcOf = new Map();   // "m>t" -> source bits
  const yearsOf = new Map(); // "m>t" -> [start, stop]
  let EVIDENCE = {};         // "m>t" -> [[source, year, url, institution]]
  const CO = new Map();      // pid -> [[other, n_works, first_year, last_year, flag]] (OpenAlex co-authorship)
  const SERVED = new Map(), COMMITTEE = new Map(); // member -> [[student, year, url]], student -> [[member, year, url]]
  const NAMED_IN = new Map(), NAMES = new Map();      // dissertation text: named -> [[student, sec, y, url, snip]], student -> [[named, ...]]
  const TEXT_SEC = ["named as advisor", "on the jury / committee page", "thanked in the acknowledgments"];
  let CO_META = null, CO_DEG = {};
  let CAREERS = {};          // pid -> [orcid, basis, [[kind, org, dept, role, start, end], ...]]
  const CAREER_BASIS = { aft: "listed on their Academic Family Tree record", wikidata: "listed on Wikidata", openalex: "listed on their OpenAlex profile", name: "matched by name and institution (check before relying on it)" };
  function loadCoauthors(d) {
    CO_META = d.meta; CO_DEG = d.degree || {};
    for (const [a, b, n, y0, y1, flag] of d.edges) {
      if (!CO.has(a)) CO.set(a, []);
      if (!CO.has(b)) CO.set(b, []);
      CO.get(a).push([b, n, y0, y1, flag === 1 ? "student" : flag === 2 ? "advisor" : ""]);
      CO.get(b).push([a, n, y0, y1, flag === 2 ? "student" : flag === 1 ? "advisor" : ""]);
    }
    for (const l of CO.values()) l.sort((x, y) => y[1] - x[1]);
  }
  let META = {};
  let index = [];            // search index
  let cy = null;
  // context: schools, communities, subfields, institutions (data/context.json, optional)
  let CTX = null;
  const PC = new Map();      // pid -> { phd, fac, school, comm, sf[] }
  const INST = new Map();    // locid -> institution
  const flowsOut = new Map(), flowsIn = new Map(); // locid -> [[locid, n]]

  function loadContext(ctx) {
    CTX = ctx;
    for (const [pid, [phd, fac, school, comm, sf, tp, oa]] of Object.entries(ctx.person)) PC.set(+pid, { phd, fac, school, comm, sf, tp: tp || [], oa });
    for (const [loc, v] of Object.entries(ctx.institutions)) INST.set(+loc, { id: +loc, ...v });
    setFlowSource(ctx.hiring_flows?.length ? "census" : "tree");
  }
  // Placement flows come from one of two sources: the faculty hiring census (Wapman et al. 2022,
  // US sociology faculty 2011-20) or the Academic Family Tree (where people later advised).
  let FLOW_SRC = "tree";
  const selfHires = new Map();
  function setFlowSource(src) {
    FLOW_SRC = src;
    flowsOut.clear(); flowsIn.clear(); selfHires.clear();
    const list = src === "census" ? CTX.hiring_flows : CTX.placements;
    for (const [a, b, n] of list) {
      if (a === b) { selfHires.set(a, (selfHires.get(a) || 0) + n); continue; }
      if (!flowsOut.has(a)) flowsOut.set(a, []);
      if (!flowsIn.has(b)) flowsIn.set(b, []);
      flowsOut.get(a).push([b, n]); flowsIn.get(b).push([a, n]);
    }
    if (src === "tree") for (const i of INST.values()) if (i.self_hired) selfHires.set(i.id, i.self_hired);
    for (const m of [flowsOut, flowsIn]) for (const l of m.values()) l.sort((x, y) => y[1] - x[1]);
  }
  const sum = (l) => (l || []).reduce((s, [, n]) => s + n, 0);
  const tot = (loc) => ({ out: sum(flowsOut.get(loc)), in: sum(flowsIn.get(loc)), self: selfHires.get(loc) || 0 });
  const FLOW_NAME = { census: "Faculty hiring census, 2011–20", tree: "Academic Family Tree" };
  const shortInst = (name) => {
    if (!name) return "";
    let s = name.replace(/^University of California,\s*/, "UC ").replace(/^The /, "");
    if (!s.startsWith("UC ")) s = s.replace(/^University of /, "").replace(/ University$/, "").split(",")[0];
    return s;
  };
  const instLink = (loc) => INST.has(loc) ? `<a href="#/i/${loc}">${esc(INST.get(loc).name)}</a>` : `<span class="muted">Not recorded</span>`;

  // "color by" modes
  const CB = {
    school: { label: "School of thought", key: (pid) => PC.get(pid)?.school, name: (k) => CTX.schools[k]?.name, href: (k) => `#/schools/curated/${k}` },
    phd: { label: "PhD institution", key: (pid) => PC.get(pid)?.phd, name: (k) => INST.get(k)?.name, href: (k) => `#/i/${k}` },
    community: { label: "Detected community", key: (pid) => PC.get(pid)?.comm, name: (k) => CTX.communities[k]?.label, href: (k) => `#/schools/detected/${k}` },
    cohort: { label: "PhD cohort", seq: true },
    topic: { label: "Publication topic", key: (pid) => PC.get(pid)?.tp?.[0], name: (k) => CTX.topics?.[k]?.name, href: (k) => `#/schools/topics/${k}` },
    subfield: { label: "Subfield", key: (pid) => PC.get(pid)?.sf?.[0], name: (k) => CTX.subfields[k]?.name, href: (k) => `#/schools/subfields/${k}` },
  };
  let pins = {};
  try { pins = JSON.parse(localStorage.getItem("lineage:pins") || "{}"); } catch { pins = {}; }
  const savePins = () => { try { localStorage.setItem("lineage:pins", JSON.stringify(pins)); } catch { /* storage unavailable */ } };

  function load(data) {
    META = data.meta;
    for (const r of data.people) {
      const [id, name, inst, f, ns, nd, na, dep, cs, h, oa, dup, phd, yr, yb] = r;
      P.set(id, { id, name: name || "(unnamed)", inst: inst || "", f, ns, nd, na, dep, cs, h, oa, phd, yr, yb: yb || 0, dup: dup || [], key: norm(name || "") });
    }
    let dangling = 0;
    EVIDENCE = data.evidence || {};
    for (const [n, st, sec, y, url, snip] of data.text_ties || []) {
      if (!NAMED_IN.has(n)) NAMED_IN.set(n, []);
      if (!NAMES.has(st)) NAMES.set(st, []);
      NAMED_IN.get(n).push([st, sec, y, url, snip]); NAMES.get(st).push([n, sec, y, url, snip]);
    }
    for (const l of [...NAMED_IN.values(), ...NAMES.values()]) l.sort((x, y) => x[1] - y[1]);
    for (const [m, st, y, url] of data.committees || []) {
      if (!SERVED.has(m)) SERVED.set(m, []);
      if (!COMMITTEE.has(st)) COMMITTEE.set(st, []);
      SERVED.get(m).push([st, y, url]); COMMITTEE.get(st).push([m, y, url]);
    }
    for (const [m, t, rel, src = 1, y0 = null, y1 = null] of data.edges) {
      if (!P.has(m) || !P.has(t)) { dangling++; continue; }
      if (!kids.has(m)) kids.set(m, []);
      if (!parents.has(t)) parents.set(t, []);
      kids.get(m).push(t);
      parents.get(t).push(m);
      relOf.set(m + ">" + t, rel);
      srcOf.set(m + ">" + t, src);
      if (y0 || y1) yearsOf.set(m + ">" + t, [y0, y1]);
    }
    META.dangling = dangling;
    if (dangling) console.warn(`${dangling} advisor links point to people missing from the export; skipped.`);
    const byDesc = (a, b) => P.get(b).nd - P.get(a).nd || P.get(b).ns - P.get(a).ns;
    for (const list of kids.values()) list.sort(byDesc);
    for (const list of parents.values()) list.sort(byDesc);
    index = [...P.values()].sort((a, b) => ((a.f & F.OUTSIDE) - (b.f & F.OUTSIDE)) || b.nd - a.nd || b.ns - a.ns);
  }

  const isOut = (p) => (p.f & F.OUTSIDE) !== 0;
  const findByName = (name) => index.find((p) => p.key === norm(name));

  /* ---------------------------------------------------------------- search */
  function searchPeople(q, limit = 12) {
    const toks = norm(q).split(" ").filter(Boolean);
    if (!toks.length) return [];
    const out = [];
    for (const p of index) {
      if (toks.every((t) => p.key.includes(t))) {
        out.push(p);
        if (out.length >= limit) break;
      }
    }
    return out;
  }

  function attachSearch(input, list, onPick) {
    let items = [], active = -1;
    const wrap = input.closest("[role=combobox]") || input.parentElement;
    const close = () => { list.hidden = true; wrap.setAttribute("aria-expanded", "false"); active = -1; input.removeAttribute("aria-activedescendant"); };
    const paint = () => {
      [...list.children].forEach((li, i) => li.setAttribute("aria-selected", String(i === active)));
      if (active >= 0) input.setAttribute("aria-activedescendant", list.children[active].id);
    };
    const render = () => {
      const q = input.value;
      if (!q.trim()) { close(); return; }
      items = searchPeople(q);
      list.innerHTML = items.length
        ? items.map((p, i) => `<li role="option" id="${list.id}-o${i}" data-id="${p.id}"><span class="nm">${esc(p.name)}</span><span class="inst">${esc(p.inst || "No institution recorded")}${isOut(p) ? " · outside the field" : ""}</span><span class="ct">${p.nd ? fmt(p.nd) + " desc." : p.na ? "" : "no links"}</span></li>`).join("")
        : `<li class="none" role="option" aria-disabled="true">No one matches “${esc(q)}”. Try a surname only.</li>`;
      list.hidden = false; wrap.setAttribute("aria-expanded", "true");
      active = items.length ? 0 : -1; paint();
    };
    input.addEventListener("input", render);
    input.addEventListener("focus", () => input.value.trim() && render());
    input.addEventListener("keydown", (e) => {
      if (list.hidden && e.key !== "Enter") return;
      if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(items.length - 1, active + 1); paint(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); paint(); }
      else if (e.key === "Enter") { if (items[active]) { e.preventDefault(); pick(items[active]); } }
      else if (e.key === "Escape") { close(); }
    });
    list.addEventListener("mousedown", (e) => {
      const li = e.target.closest("li[data-id]");
      if (li) { e.preventDefault(); pick(P.get(+li.dataset.id)); }
    });
    input.addEventListener("blur", () => setTimeout(close, 120));
    function pick(p) { close(); onPick(p, input); }
  }

  /* ---------------------------------------------------------------- routing */
  function parseHash() {
    const raw = location.hash.replace(/^#\/?/, "");
    const [path, qs] = raw.split("?");
    const parts = path.split("/").filter(Boolean);
    const params = new URLSearchParams(qs || "");
    return { view: parts[0] || "", parts: parts.slice(1), params };
  }
  const go = (h) => { if (location.hash !== h) location.hash = h; else route(); };
  const lineageHash = (id, params) => {
    const q = new URLSearchParams();
    for (const k of ["d", "out", "c", "t", "co", "cm", "tx"]) { const v = params?.get?.(k); if (v) q.set(k, v); }
    const s = q.toString();
    return `#/p/${id}${s ? "?" + s : ""}`;
  };
  let state = { view: "lineage", focus: null, params: new URLSearchParams() };

  function setTab(view) {
    document.querySelectorAll(".tabs a").forEach((a) => {
      if (a.dataset.view === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }

  function route() {
    const { view, parts, params } = parseHash();
    state.params = params;
    if (view === "p" && P.has(+parts[0])) return showLineage(+parts[0], params);
    if (view === "kin") return showKin(parts[0] ? +parts[0] : null, params);
    if (view === "co") return showCoauthors(parts[0] ? +parts[0] : null, params);
    if (view === "connect") return showConnect(parts[0] ? +parts[0] : null, parts[1] ? +parts[1] : null);
    if (view === "schools") return showSchools(parts[0] || "curated", parts[1] != null ? +parts[1] : null);
    if (view === "institutions") return showInstitutions(null, params);
    if (view === "i") return showInstitutions(+parts[0], params);
    if (view === "dynasties") return showDynasties(params);
    if (view === "gaps") return showGaps(parts[0] || null, params);
    return showLineage(null, params);
  }

  /* ---------------------------------------------------------------- graph canvas */
  function initCy() {
    cytoscape.use(cytoscapeDagre);
    cy = cytoscape({
      container: els.cy, minZoom: 0.15, maxZoom: 2.5, wheelSensitivity: 0.25, boxSelectionEnabled: false, autoungrabify: true,
      style: [
        { selector: "node", style: {
          shape: "ellipse", width: "data(size)", height: "data(size)",
          "background-color": PAPER, "border-width": 1.5, "border-color": INK,
          label: "data(label)", "font-family": '"Source Sans 3", system-ui, sans-serif', "font-size": 13, "font-weight": 600,
          color: INK, "text-valign": "bottom", "text-halign": "center", "text-margin-y": 5,
          "text-wrap": "wrap", "text-max-width": 104, "text-background-color": PAPER, "text-background-opacity": 0.85, "text-background-padding": 1,
          "transition-property": "opacity, border-color, border-width", "transition-duration": 200,
        } },
        { selector: "node.out", style: { "border-style": "dashed", color: "#4a4a48", "font-weight": 400 } },
        { selector: "node.focus", style: { "background-color": INK, "border-color": INK, "font-size": 15, "font-weight": 700 } },
        { selector: "node.more", style: { shape: "rectangle", width: 72, height: 22, "border-width": 1, "border-style": "dotted", "border-color": INK3, color: INK3, "font-weight": 400, "font-style": "italic", "font-size": 12, "text-valign": "center", "text-margin-y": 0, "text-background-opacity": 0 } },
        { selector: "node.hover", style: { "border-color": RED, "border-width": 2.5 } },
        { selector: "edge", style: {
          width: 1.3, "line-color": INK, "target-arrow-color": INK, "target-arrow-shape": "triangle", "arrow-scale": 0.9,
          "curve-style": "straight", opacity: 0.85,
          "transition-property": "opacity, line-color, width", "transition-duration": 200,
        } },
        { selector: "edge.postdoc", style: { "line-style": "dashed" } },
        { selector: "edge.ext", style: { "line-style": "dotted", width: 1.8 } },
        // co-authorship: curved, no arrow, width by shared papers; drawn over the tree, never laid out with it
        { selector: "edge.co", style: { "curve-style": "unbundled-bezier", "control-point-distances": 40, "control-point-weights": 0.5,
          "line-color": "#8f8b82", "target-arrow-shape": "none", width: "data(w)", opacity: 0.75, "z-index": 1 } },
        { selector: "edge.co.faint", style: { opacity: 0.25 } },
        { selector: "edge.tx", style: { "curve-style": "unbundled-bezier", "control-point-distances": 28, "control-point-weights": 0.5,
          "line-color": INK3, "line-style": "dotted", "target-arrow-shape": "none", width: 1.4, opacity: 0.7 } },
        { selector: "edge.tx.strong", style: { width: 2, opacity: 0.95 } },
        { selector: "edge.cm", style: { "curve-style": "unbundled-bezier", "control-point-distances": -36, "control-point-weights": 0.5,
          "line-color": INK3, "line-style": "dashed", "line-dash-pattern": [5, 4], "target-arrow-shape": "none", width: 1.2, opacity: 0.8 } },
        { selector: "edge.co.ego", style: { "curve-style": "straight" } },
        // faint context: marks drop to light ink, labels stay readable (ink-3 ≈ 5.3:1)
        { selector: "edge.faint", style: { opacity: 0.35 } },
        { selector: "node.faint", style: { "border-color": FAINT, color: INK3, "font-weight": 400 } },
        { selector: "node.path", style: { "border-color": RED, "border-width": 3 } },
        { selector: "node.path.end", style: { "background-color": RED, "border-color": RED } },
        { selector: "node.path.focus", style: { "background-color": RED } },
        { selector: "edge.path", style: { width: 3.6, "line-color": RED, "target-arrow-color": RED, opacity: 1, "arrow-scale": 1.1, "z-index": 10 } },
        // color by: colored-pencil fills, ink border kept
        ...CAT.map((c, i) => ({ selector: `node.c${i}`, style: { "background-color": c } })),
        { selector: "node.cx", style: { "background-color": OTHER_FILL } },
        ...COHORT.map(([, , , c], i) => ({ selector: `node.y${i}`, style: { "background-color": c } })),
        { selector: "node.focus.y0, node.focus.y1, node.focus.y2, node.focus.y3, node.focus.y4, node.focus.y5, node.focus.y6, node.focus.y7", style: { "border-width": 4, "border-color": INK, "background-color": "data(fill)" } },
        { selector: "node.tick", style: { shape: "rectangle", width: 1, height: 1, "background-opacity": 0, "border-width": 0, label: "data(label)", color: INK3, "font-size": 12, "font-weight": 600, "text-valign": "center", "text-halign": "left", "text-margin-x": -6, "text-background-opacity": 0, events: "no" } },
        { selector: "edge.grid", style: { width: 1, "line-color": "#e9e6df", "target-arrow-shape": "none", "curve-style": "straight", opacity: 1, "z-index": 0, events: "no" } },
        { selector: "node.focus.c0, node.focus.c1, node.focus.c2, node.focus.cx", style: { "border-width": 4 } },
        ...CAT.map((c, i) => ({ selector: `node.focus.c${i}`, style: { "background-color": INK, "border-color": c } })),
        { selector: "node.focus.cx", style: { "background-color": INK, "border-color": INK3 } },
        // institution placement network
        { selector: "node.inst", style: { "font-size": 13, "font-weight": 600, "text-max-width": 110 } },
        { selector: "edge.flow", style: { width: "data(w)", "curve-style": "bezier", opacity: 0.45, "arrow-scale": 0.8 } },
        { selector: "node.inst.sel", style: { "background-color": RED, "border-color": RED } },
        { selector: "edge.flow.sel", style: { "line-color": RED, "target-arrow-color": RED, opacity: 1, "z-index": 10 } },
        { selector: "edge.flow.selin", style: { "line-style": "dashed", opacity: 0.9 } },
      ],
    });
    cy.on("mouseover", "node", (e) => { e.target.addClass("hover"); els.cy.style.cursor = "pointer"; });
    cy.on("mouseout", "node", (e) => { e.target.removeClass("hover"); els.cy.style.cursor = ""; });
    cy.on("tap", "node", (e) => {
      const d = e.target.data();
      if (d.more) return go(lineageHash(d.more, state.params));
      if (d.loc) return go(`#/i/${d.loc}?v=network`);
      const id = +d.id;
      if (state.view === "connect") return renderPanel(id, { inConnect: true });
      if (state.view === "co") return go(`#/co/${id}`);
      go(lineageHash(id, state.params));
    });
  }

  const sizeFor = (p) => Math.round(20 + 6 * Math.log10(1 + (p?.nd || 0)));

  function nodeEl(p, cls = "") {
    const c = [cls, isOut(p) ? "out" : ""].filter(Boolean).join(" ");
    // second line carries the dynasty size, as in the sketch; leaves stay one line
    const label = p.nd ? `${p.name}\n${fmt(p.nd)} desc.` : p.name;
    return { group: "nodes", data: { id: String(p.id), label, size: sizeFor(p) }, classes: c };
  }
  function edgeEl(m, t, cls = "") {
    const rel = relOf.get(m + ">" + t);
    const outside = !((srcOf.get(m + ">" + t) ?? 1) & SRC.AFT);
    return { group: "edges", data: { id: `e${m}-${t}`, source: String(m), target: String(t) }, classes: [cls, rel === 2 ? "postdoc" : "", outside ? "ext" : ""].filter(Boolean).join(" ") };
  }

  function draw(elements, { fitTo, layoutOpts, after } = {}) {
    els.cy.classList.add("fading");
    requestAnimationFrame(() => {
      cy.batch(() => { cy.elements().remove(); cy.add(elements); });
      const layout = cy.elements().not(".overlay").layout(layoutOpts || { name: "dagre", rankDir: "TB", nodeSep: 18, rankSep: 64, edgeSep: 8, ranker: "network-simplex", nodeDimensionsIncludeLabels: true, animate: false });
      layout.run();
      if (after) after();
      // The usable area starts under the toolbar band (on narrow screens the toolbar sits above the canvas instead).
      const top = getComputedStyle(els.toolbar).position === "absolute" ? els.toolbar.offsetHeight : 0;
      const bottom = els.legend.hidden ? 16 : 44;
      const W = cy.width(), H = cy.height() - top - bottom;
      const bb = cy.elements().boundingBox();
      const pad = 36;
      let z = Math.min((W - 2 * pad) / Math.max(bb.w, 1), (H - 2 * pad) / Math.max(bb.h, 1));
      z = Math.min(z, 1.25);
      const anchor = fitTo ? cy.$(fitTo) : null;
      if (z >= 0.85 || !anchor || !anchor.length) {
        // everything fits legibly: centre the whole drawing in the usable area
        cy.zoom(Math.max(z, cy.minZoom()));
        cy.pan({ x: W / 2 - (bb.x1 + bb.w / 2) * cy.zoom(), y: top + bottom / 4 + H / 2 - (bb.y1 + bb.h / 2) * cy.zoom() });
      } else {
        // hold a readable zoom on the focus; the rest pans
        // too wide to fit legibly: hold a readable zoom centred on the focus; the sides pan.
        // Vertically, keep the whole drawing under the toolbar when its height fits.
        const zr = Math.max(0.75, Math.min(0.85, (H - 2 * pad) / Math.max(bb.h, 1)));
        cy.zoom(zr);
        const p = anchor.position();
        const fitsTall = bb.h * zr <= H - 2 * pad;
        const y = fitsTall ? top + pad + (H - 2 * pad - bb.h * zr) / 2 - bb.y1 * zr : top + H * 0.42 - p.y * zr;
        cy.pan({ x: W / 2 - p.x * zr, y });
      }
      els.cy.classList.remove("fading");
    });
  }

  function showCanvas(on, { map = false } = {}) {
    els.cy.hidden = !on || map;
    els.map.hidden = !map;
    els.legend.hidden = !on || map;
    els.sheet.hidden = on || map;
    if (!on || map) setColorKey(null);
    if (on && !map && cy) requestAnimationFrame(() => cy.resize());
  }
  function notice(html, cls = "") {
    clearNotice();
    const n = document.createElement("div");
    n.className = "notice " + cls; n.id = "notice"; n.innerHTML = html;
    els.stage.appendChild(n);
    return n;
  }
  const clearNotice = () => $("#notice")?.remove();

  /* ---------------------------------------------------------------- lineage view */
  function lineageElements(pid, depth, showOut) {
    const nodes = new Map(), edges = [];
    const focus = P.get(pid);
    nodes.set(pid, nodeEl(focus, "focus"));
    const keep = (p) => showOut || !isOut(p);

    // ancestors: everyone above, up to 8 generations
    let frontier = [pid];
    for (let g = 0; g < 8 && frontier.length; g++) {
      const next = [];
      for (const t of frontier) for (const m of parents.get(t) || []) {
        const p = P.get(m);
        if (!keep(p)) continue;
        if (!nodes.has(m)) { nodes.set(m, nodeEl(p)); next.push(m); }
        edges.push(edgeEl(m, t));
      }
      frontier = next;
    }

    // descendants: by generation, capped per parent past the first
    frontier = [pid];
    for (let g = 1; g <= depth && frontier.length; g++) {
      // children are pre-sorted by descendants, so the largest lines always make the cut
      const perParent = g === 1 ? 8 : depth >= 3 ? 2 : 3;
      const next = [];
      for (const m of frontier) {
        const ch = (kids.get(m) || []).filter((c) => keep(P.get(c)));
        let shown = 0;
        for (const c of ch) {
          if (shown >= perParent || nodes.size >= NODE_CAP) break;
          if (!nodes.has(c)) { nodes.set(c, nodeEl(P.get(c))); next.push(c); }
          edges.push(edgeEl(m, c)); shown++;
        }
        const hidden = ch.length - shown;
        if (hidden > 0) {
          const id = `more-${m}`;
          nodes.set(id, { group: "nodes", data: { id, label: `+${fmt(hidden)} more`, more: m, size: 22 }, classes: "more" });
          edges.push({ group: "edges", data: { id: `e${m}-${id}`, source: String(m), target: id }, classes: "faint" });
        }
      }
      frontier = next;
    }
    const seen = new Set();
    return [...nodes.values(), ...edges.filter((e) => !seen.has(e.data.id) && seen.add(e.data.id))];
  }

  function lineageToolbar(p, depth, showOut) {
    const nAnc = countAncestors(p.id);
    els.toolbar.innerHTML = `
      <span class="title">${esc(p.name)}</span>
      <span class="sub">${esc(p.inst || "No institution recorded")} · ${plural(nAnc, "ancestor")} · ${plural(p.nd, "descendant")}</span>
      <span class="seg-label">Generations below</span>
      <span class="seg" role="group" aria-label="Generations below">${[1, 2, 3, 4].map((d) => `<button type="button" data-d="${d}" aria-pressed="${d === depth}">${d}</button>`).join("")}</span>
      <label class="check"><input type="checkbox" id="showOut" ${showOut ? "checked" : ""}> Show people outside the field</label>
      <a class="btn" href="#/kin/${p.id}">Relatives</a>
      <label class="check"><input type="checkbox" id="byYear" ${state.params.get("t") === "1" ? "checked" : ""}> Arrange by year</label>
      ${NAMES.size ? `<label class="check"><input type="checkbox" id="showTx" ${state.params.get("tx") === "1" ? "checked" : ""}> Named in dissertations</label>` : ""}
      ${COMMITTEE.size ? `<label class="check"><input type="checkbox" id="showCm" ${state.params.get("cm") === "1" ? "checked" : ""}> Committee links</label>` : ""}
      ${CO.size ? `<label class="check"><input type="checkbox" id="showCo" ${state.params.get("co") === "1" ? "checked" : ""}> Co-author links</label>` : ""}
      ${CTX ? `<label class="selectlbl">Color by <select id="colorBy"><option value="">Nothing</option>${Object.entries(CB).map(([k, v]) => `<option value="${k}" ${state.params.get("c") === k ? "selected" : ""}>${v.label}</option>`).join("")}</select></label>` : ""}`;
    $("#colorBy")?.addEventListener("change", (e) => {
      const q = new URLSearchParams(state.params); if (e.target.value) q.set("c", e.target.value); else q.delete("c"); go(`#/p/${p.id}${q.toString() ? "?" + q : ""}`);
    });
    els.toolbar.querySelectorAll("[data-d]").forEach((b) => b.addEventListener("click", () => {
      const q = new URLSearchParams(state.params); q.set("d", b.dataset.d); go(`#/p/${p.id}?${q}`);
    }));
    $("#byYear").addEventListener("change", (e) => {
      const q = new URLSearchParams(state.params); if (e.target.checked) q.set("t", "1"); else q.delete("t"); go(`#/p/${p.id}${q.toString() ? "?" + q : ""}`);
    });
    $("#showTx")?.addEventListener("change", (e) => {
      const q = new URLSearchParams(state.params); if (e.target.checked) q.set("tx", "1"); else q.delete("tx"); go(`#/p/${p.id}${q.toString() ? "?" + q : ""}`);
    });
    $("#showCm")?.addEventListener("change", (e) => {
      const q = new URLSearchParams(state.params); if (e.target.checked) q.set("cm", "1"); else q.delete("cm"); go(`#/p/${p.id}${q.toString() ? "?" + q : ""}`);
    });
    $("#showCo")?.addEventListener("change", (e) => {
      const q = new URLSearchParams(state.params); if (e.target.checked) q.set("co", "1"); else q.delete("co"); go(`#/p/${p.id}${q.toString() ? "?" + q : ""}`);
    });
    $("#showOut").addEventListener("change", (e) => {
      const q = new URLSearchParams(state.params); if (e.target.checked) q.delete("out"); else q.set("out", "0"); go(`#/p/${p.id}${q.toString() ? "?" + q : ""}`);
    });
  }

  function countAncestors(pid) {
    const seen = new Set(); const st = [pid];
    while (st.length) for (const m of parents.get(st.pop()) || []) if (!seen.has(m)) { seen.add(m); st.push(m); }
    return seen.size;
  }

  function startChips() {
    const names = ["Talcott Parsons", "Robert K. Merton", "Charles Tilly", "Robert M. Hauser", "Pitirim Sorokin", "Erik Olin Wright", "Arlie Russell Hochschild", "Michael Burawoy"];
    return names.map(findByName).filter(Boolean)
      .map((p) => `<a class="chip" href="#/p/${p.id}">${esc(p.name)}<small>${fmt(p.nd)}</small></a>`).join("");
  }

  function showLineage(pid, params) {
    state.view = "lineage"; setTab("lineage"); showCanvas(true);
    if (pid == null) {
      // Return to the last lineage viewed; the starter screen is only for a first visit.
      let last = null;
      try { last = +localStorage.getItem("lineage:last"); } catch { /* storage unavailable */ }
      if (last && P.has(last)) { location.replace(lineageHash(last, params)); return; }
      state.focus = null;
      els.toolbar.innerHTML = "";
      cy.elements().remove();
      notice(`<h2>Start from a person</h2><p>Search any of ${fmt(META.people)} people above, or open one of these lineages. Numbers are descendants on record.</p><div class="starts">${startChips()}</div>`);
      renderPanelIntro();
      return;
    }
    clearNotice();
    state.focus = pid;
    try { localStorage.setItem("lineage:last", String(pid)); } catch { /* storage unavailable */ }
    const depth = Math.min(4, Math.max(1, +(params.get("d") || 1)));
    const showOut = params.get("out") !== "0";
    const p = P.get(pid);
    lineageToolbar(p, depth, showOut);
    const elements = lineageElements(pid, depth, showOut);
    if (elements.length === 1) {
      notice(`<h2>${esc(p.name)} has no recorded advisor or students</h2><p class="note">No mentorship links on record. The Academic Family Tree lists this person under sociology, but nobody has connected them yet.</p>`, "lonely");
    }
    const mode = CTX && CB[params.get("c")] ? params.get("c") : null;
    if (mode) colorize(elements, mode); else setColorKey(null);
    if (params.get("co") === "1") elements.push(...coauthorOverlay(elements));
    if (params.get("cm") === "1") elements.push(...committeeOverlay(elements));
    if (params.get("tx") === "1") elements.push(...textOverlay(elements));
    const byYear = params.get("t") === "1";
    if (byYear && !mode) colorizeCohort(elements);  // the year layout reads best with cohort colour
    draw(elements, { fitTo: `node[id="${pid}"]`, after: byYear ? () => timelineLayout(pid) : null });
    renderPanel(pid);
  }

  /* ---------------------------------------------------------------- color by */
  // Up to three categories get a colored pencil: pinned ones first (they keep their color as you
  // move around), then the most common in the current drawing. Everything else is "Other".
  function colorize(elements, mode) {
    const cb = CB[mode];
    if (cb.seq) return colorizeCohort(elements);
    const counts = new Map();
    for (const e of elements) {
      if (e.group !== "nodes" || e.data.more || e.data.loc) continue;
      const k = cb.key(+e.data.id);
      if (k != null) counts.set(k, (counts.get(k) || 0) + 1);
    }
    const pinned = (pins[mode] || []).filter((k) => cb.name(k));
    const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k).filter((k) => !pinned.includes(k));
    const slots = [...pinned, ...top.filter((k) => cb.name(k))].slice(0, CAT.length);
    for (const e of elements) {
      if (e.group !== "nodes" || e.data.more) continue;
      const k = cb.key(+e.data.id);
      if (k == null) continue;
      const i = slots.indexOf(k);
      e.classes = [e.classes, i >= 0 ? `c${i}` : "cx"].filter(Boolean).join(" ");
    }
    setColorKey({ mode, slots, counts, pinned });
  }

  function colorizeCohort(elements) {
    const counts = new Array(COHORT.length).fill(0);
    let est = 0;
    for (const e of elements) {
      if (e.group !== "nodes" || e.data.more || e.data.loc) continue;
      const p = P.get(+e.data.id);
      const i = cohortOf(p?.yr);
      if (i < 0) continue;
      counts[i]++;
      if (p.yb >= 3) est++;
      e.classes = [e.classes, `y${i}`].filter(Boolean).join(" ");
      e.data.fill = COHORT[i][3];
      e.data.label = `${p.name}\n${p.yb >= 3 ? "≈" : ""}${p.yr}`;
    }
    els.colorkey.innerHTML = `<b>PhD cohort</b>` + COHORT.map(([lab, , , c], i) => counts[i] ? `<span class="ck"><i style="background:${c}"></i>${lab}<span class="muted">${fmt(counts[i])}</span></span>` : "").join("")
      + (est ? `<span class="ck muted">≈ estimated year (${fmt(est)})</span>` : "");
    els.colorkey.hidden = false;
  }

  // Arrange by year: keep the tree's left-right order, move each person to their PhD year
  const YEAR_PX = 9;
  function timelineLayout(pid) {
    const nodes = cy.nodes().not(".tick");
    const dated = nodes.filter((n) => P.get(+n.id())?.yr);
    if (dated.length < 2) return;
    const ys = dated.map((n) => P.get(+n.id()).yr);
    const lo = Math.floor(Math.min(...ys) / 10) * 10, hi = Math.ceil((Math.max(...ys) + 1) / 10) * 10;
    cy.batch(() => {
      dated.forEach((n) => n.position("y", (P.get(+n.id()).yr - lo) * YEAR_PX));
      // undated people and "+N more" boxes sit just below their advisor
      nodes.difference(dated).forEach((n) => {
        const up = n.incomers("node").filter((m) => P.get(+m.id())?.yr);
        n.position("y", up.length ? up[0].position("y") + 24 * YEAR_PX : (hi - lo) * YEAR_PX);  // one typical generation gap
      });
      const bb = nodes.boundingBox();
      const grid = [];
      for (let y = lo; y <= hi; y += 10) {
        grid.push({ group: "nodes", data: { id: `t${y}`, label: String(y) }, position: { x: bb.x1 - 40, y: (y - lo) * YEAR_PX }, classes: "tick" });
        grid.push({ group: "nodes", data: { id: `t${y}r`, label: "" }, position: { x: bb.x2 + 40, y: (y - lo) * YEAR_PX }, classes: "tick" });
        grid.push({ group: "edges", data: { id: `g${y}`, source: `t${y}`, target: `t${y}r` }, classes: "grid" });
      }
      cy.add(grid);
    });
  }

  function setColorKey(spec) {
    if (!spec) { els.colorkey.hidden = true; els.colorkey.innerHTML = ""; return; }
    const { mode, slots, counts, pinned } = spec;
    const cb = CB[mode];
    const other = [...counts.entries()].filter(([k]) => !slots.includes(k)).reduce((s, [, n]) => s + n, 0);
    els.colorkey.innerHTML = `<b>${esc(cb.label)}</b>` + slots.map((k, i) => `
      <span class="ck"><i style="background:${CAT[i]}"></i><a href="${cb.href(k)}">${esc(cb.name(k))}</a><span class="muted">${fmt(counts.get(k) || 0)}</span>
      <button type="button" class="pin" data-k="${k}" aria-pressed="${pinned.includes(k)}" title="${pinned.includes(k) ? "Unpin: let this color go to whatever is most common" : "Pin: keep this color as you move around"}">${pinned.includes(k) ? "Pinned" : "Pin"}</button></span>`).join("")
      + (other ? `<span class="ck"><i style="background:${OTHER_FILL}"></i>Other<span class="muted">${fmt(other)}</span></span>` : "");
    els.colorkey.hidden = false;
    els.colorkey.querySelectorAll(".pin").forEach((b) => b.addEventListener("click", () => {
      const k = isNaN(+b.dataset.k) ? b.dataset.k : +b.dataset.k;
      const list = pins[mode] || [];
      pins[mode] = list.includes(k) ? list.filter((x) => x !== k) : [...list, k].slice(-CAT.length);
      savePins(); route();
    }));
  }
  function pinAndColor(mode, key, pid) {
    const list = (pins[mode] || []).filter((x) => x !== key);
    pins[mode] = [key, ...list].slice(0, CAT.length);
    savePins();
    const q = new URLSearchParams(state.params); q.set("c", mode);
    go(`#/p/${pid}?${q}`);
  }

  /* ---------------------------------------------------------------- person panel */
  function flagNotes(p) {
    const n = [];
    if (p.f & F.ISOLATED) n.push("No advisor or student links on record.");
    else if (p.f & F.NO_ADVISOR) n.push("No advisor recorded. The lineage stops here, either at a founder or at a missing link.");
    if (p.f & F.MULTI_ADVISOR) n.push(`Co-advised: ${p.na} advisors on record.`);
    if (p.f & F.OUTSIDE) n.push("Outside sociology. Kept because they advised or trained a sociologist.");
    if (p.f & F.EXTERNAL) n.push("Not in the Academic Family Tree. Known only from an outside source; see the evidence below.");
    if (p.f & PROFDOC) {
      if (p.f & F.PROF_INST) n.push("Practitioner-doctorate institution: likely an Ed.D.-style or professional doctorate.");
      const why = [p.f & F.EDU_AREA && "the research area is an education subject", p.f & F.EDUC && "they are also listed in the education tree"].filter(Boolean);
      if (why.length) n.push(`Education research area: ${why.join("; ")}. A weaker signal.`);
    }
    if (p.f & F.SMALL) n.push(`Part of a small cluster (${plural(p.cs, "person", "people")}) cut off from the main tree.`);
    let html = n.map((t) => `<p class="note">${esc(t)}</p>`).join("");
    if (p.dup.length) html += `<p class="note">Possible duplicate of ${p.dup.map((d) => `<a href="${lineageHash(d, state.params)}">${esc(P.get(d)?.name || d)}</a>`).join(", ")}: same or compatible name, ${p.dup.some((d) => P.get(d)?.key === p.key) ? "identical spelling" : "sharing an advisor or student"}.</p>`;
    return html;
  }

  function personList(ids, { limit = 12, showCount = true } = {}) {
    if (!ids.length) return `<p class="muted">None on record.</p>`;
    const row = (id) => {
      const q = P.get(id);
      const mark = `<svg class="mk${isOut(q) ? " dash" : ""}" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.5"/></svg>`;
      const title = esc(q.inst || "No institution recorded") + (isOut(q) ? " · outside the field" : "");
      return `<li><a href="${lineageHash(id, state.params)}" class="${isOut(q) ? "out" : ""}" title="${title}">${mark}<span class="nm">${esc(q.name)}</span></a>${showCount ? `<span class="ct">${fmt(q.nd)} desc.</span>` : ""}</li>`;
    };
    const head = ids.slice(0, limit).map(row).join("");
    return `<ul class="plist">${head}</ul>${ids.length > limit ? `<button type="button" class="more-btn" data-expand>Show all ${fmt(ids.length)}</button><ul class="plist" hidden data-rest>${ids.slice(limit).map(row).join("")}</ul>` : ""}`;
  }

  function renderPanel(pid, { inConnect = false } = {}) {
    const p = P.get(pid);
    const adv = parents.get(pid) || [];
    const stu = kids.get(pid) || [];
    const onLineage = state.view === "lineage" && state.focus === pid;
    els.panel.innerHTML = `
      <h2>${esc(p.name)}</h2>
      <p class="inst">${esc(p.inst || "No institution recorded")}</p>
      ${flagNotes(p)}
      <div class="stats">
        <div class="stat"><span>Students</span>${stu.length ? `<button type="button" data-jump="students">${fmt(p.ns)}</button>` : "<b>0</b>"}</div>
        <div class="stat"><span>Descendants</span><b>${fmt(p.nd)}</b></div>
        <div class="stat"><span>Advisors</span>${adv.length ? `<button type="button" data-jump="advisors">${fmt(p.na)}</button>` : "<b>0</b>"}</div>
        <div class="stat"><span>Generations below</span><b>${fmt(p.dep)}</b></div>
        ${p.yr ? `<div class="stat"><span>PhD year <span class="muted">· ${esc(YEAR_BASIS[p.yb])}</span></span><b>${p.yb >= 3 ? "≈" : ""}${p.yr}</b></div>` : ""}
        <div class="stat"><span>Cluster size</span><b>${fmt(p.cs)}</b></div>
        ${p.h != null ? `<div class="stat"><span>h-index (Academic Tree)</span><b>${fmt(p.h)}</b></div>` : ""}
      </div>
      ${contextRows(pid)}
      <h3 id="advisors">Advisors</h3>${personList(adv)}
      <h3 id="students">Students</h3>${personList(stu)}
      ${careerBlock(pid)}
      ${kinSummary(pid)}
      ${dissertationBlock(pid)}
      ${committeeLists(pid)}
      ${textTies(pid)}
      ${coauthorList(pid)}
      ${evidenceList(pid, adv, stu)}
      <div class="actions">
        ${onLineage ? "" : `<a class="btn primary" href="${lineageHash(pid, state.params)}">Open lineage</a>`}
        <a class="btn" href="#/connect/${pid}">${inConnect ? "Start a new connection here" : "Connect to someone"}</a>
        ${p.oa ? `<a class="btn" href="https://openalex.org/${esc(p.oa)}" target="_blank" rel="noopener">OpenAlex<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h7v7M13 3L5 11"/></svg></a>` : ""}
        ${pid < 900000000 ? `<a class="btn" href="https://academictree.org/sociology/peopleinfo.php?pid=${pid}" target="_blank" rel="noopener">Academic Tree<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h7v7M13 3L5 11"/></svg></a>` : ""}
      </div>`;
    els.panel.querySelectorAll("[data-expand]").forEach((b) => b.addEventListener("click", () => {
      b.nextElementSibling.hidden = false; b.remove();
    }));
    els.panel.querySelectorAll("[data-jump]").forEach((b) => b.addEventListener("click", () => {
      $("#" + b.dataset.jump, els.panel).scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    els.panel.scrollTop = 0;
  }

  function evidenceList(pid, adv, stu) {
    const rows = [];
    for (const m of adv) for (const e of EVIDENCE[m + ">" + pid] || []) rows.push([m, pid, e]);
    for (const t of stu) for (const e of EVIDENCE[pid + ">" + t] || []) rows.push([pid, t, e]);
    if (!rows.length) return "";
    return `<h3>Evidence from outside sources</h3><ul class="plist ev">${rows.slice(0, 40).map(([m, t, [src, yr, url, inst]]) => {
      const other = m === pid ? t : m;
      const inAft = (srcOf.get(m + ">" + t) || 0) & SRC.AFT;
      return `<li><span><a href="${lineageHash(other, state.params)}">${esc(P.get(other)?.name || "")}</a> <span class="muted">${m === pid ? "student" : "advisor"}</span><span class="rel">${esc(srcLabel(src))}${yr ? " · " + yr : ""}${inst ? " · " + esc(inst) : ""} · ${inAft ? "confirms the tree" : "new link"}</span></span>${url ? `<a class="ct" href="${esc(url)}" target="_blank" rel="noopener">Source</a>` : ""}</li>`;
    }).join("")}</ul>`;
  }

  function contextRows(pid) {
    const c = CTX && PC.get(pid);
    if (!c) return "";
    const sch = c.school != null ? CTX.schools[c.school] : null;
    const com = c.comm != null ? CTX.communities[c.comm] : null;
    const sfs = (c.sf || []).map((i) => `<a href="#/schools/subfields/${i}">${esc(CTX.subfields[i].name)}</a>`).join(", ");
    return `<h3>Schools and institutions</h3><div class="kv">
      <div><span>PhD institution</span>${c.phd != null ? instLink(c.phd) : `<span class="muted">Not recorded</span>`}</div>
      <div><span>Advised at</span>${c.fac != null ? instLink(c.fac) : `<span class="muted">No students or affiliation on record</span>`}</div>
      <div><span>School of thought</span>${sch ? `<a href="#/schools/curated/${c.school}">${esc(sch.name)}</a>` : `<span class="muted">None of the curated schools</span>`}</div>
      <div><span>Community</span>${com ? `<a href="#/schools/detected/${c.comm}">${esc(com.label)}</a>` : `<span class="muted">Not in a detected community</span>`}</div>
      ${sfs ? `<div><span>Subfields</span><span>${sfs}</span></div>` : ""}
      ${c.tp?.length && CTX.topics ? `<div><span>Publication topics</span><span>${c.tp.map((i) => `<a href="#/schools/topics/${i}">${esc(CTX.topics[i].name)}</a>`).join(", ")}</span></div>` : ""}
      ${c.oa ? `<div><span>OpenAlex</span><span>${fmt(c.oa[0])} works · ${fmt(c.oa[1])} citations · h-index ${fmt(c.oa[2])}</span></div>` : ""}
    </div>`;
  }

  function renderPanelIntro() {
    const soc = index.filter((p) => !isOut(p)).length;
    els.panel.innerHTML = `
      <h2>The sociology tree</h2>
      <p class="inst">${esc(META.source)}</p>
      <div class="stats">
        <div class="stat"><span>People</span><b>${fmt(META.people)}</b></div>
        <div class="stat"><span>Tagged sociology</span><b>${fmt(soc)}</b></div>
        <div class="stat"><span>Advisor links</span><b>${fmt(META.edges)}</b></div>
        <div class="stat"><span>Separate clusters</span><b>${fmt(META.clusters)}</b></div>
        <div class="stat"><span>Largest cluster</span><b>${fmt(META.largest_cluster)}</b></div>
        <div class="stat"><span>Matched to OpenAlex</span><b>${fmt(META.openalex_matched)}</b></div>
      </div>
      ${META.openalex_matched ? "" : `<p class="note">OpenAlex matching is still running. Publication and citation data will appear here once it lands.</p>`}
      <div class="panel-empty"><h3>How to read the diagram</h3>
      <p>Arrows run from advisor to student. Advisors sit above, students below. Larger circles have more descendants.</p>
      <p>Click any person to recenter on them. In Connect, the path between two people is traced in red.</p></div>`;
  }

  /* ---------------------------------------------------------------- connect view */
  function bfsUp(pid) {
    const dist = new Map([[pid, 0]]), prev = new Map(); const q = [pid];
    for (let i = 0; i < q.length; i++) {
      const t = q[i];
      for (const m of parents.get(t) || []) if (!dist.has(m)) { dist.set(m, dist.get(t) + 1); prev.set(m, t); q.push(m); }
    }
    return { dist, prev };
  }
  function shortestPath(a, b) {
    const prev = new Map([[a, null]]); const q = [a];
    for (let i = 0; i < q.length; i++) {
      const n = q[i];
      if (n === b) break;
      for (const x of [...(parents.get(n) || []), ...(kids.get(n) || [])]) if (!prev.has(x)) { prev.set(x, n); q.push(x); }
    }
    if (!prev.has(b)) return null;
    const path = []; for (let n = b; n != null; n = prev.get(n)) path.push(n);
    return path.reverse();
  }
  function chainDown(prev, from, to) { // walk prev pointers from ancestor `from` down to `to`
    const out = [from]; let n = from;
    while (n !== to) { n = prev.get(n); out.push(n); }
    return out;
  }

  function connectToolbar(a, b) {
    els.toolbar.innerHTML = `
      <div class="pickers">
        <div class="picker" role="combobox" aria-expanded="false" aria-haspopup="listbox"><input id="pickA" type="search" placeholder="First person" aria-label="First person" autocomplete="off" value="${a ? esc(P.get(a).name) : ""}"><ul id="resA" class="results" role="listbox" hidden></ul></div>
        <span class="to">to</span>
        <div class="picker" role="combobox" aria-expanded="false" aria-haspopup="listbox"><input id="pickB" type="search" placeholder="Second person" aria-label="Second person" autocomplete="off" value="${b ? esc(P.get(b).name) : ""}"><ul id="resB" class="results" role="listbox" hidden></ul></div>
        ${a && b ? `<button type="button" class="btn" id="swap">Swap</button>` : ""}
      </div>`;
    attachSearch($("#pickA"), $("#resA"), (p) => go(`#/connect/${p.id}${b ? "/" + b : ""}`));
    attachSearch($("#pickB"), $("#resB"), (p) => go(`#/connect/${a ? a : p.id}${a ? "/" + p.id : ""}`));
    $("#swap")?.addEventListener("click", () => go(`#/connect/${b}/${a}`));
    if (!a) $("#pickA").focus(); else if (!b) $("#pickB").focus();
  }

  function showConnect(a, b) {
    state.view = "connect"; setTab("connect"); showCanvas(true);
    if (a && !P.has(a)) a = null; if (b && !P.has(b)) b = null;
    connectToolbar(a, b);
    if (!a || !b) {
      cy.elements().remove();
      const ex = [["Talcott Parsons", "Erik Olin Wright"], ["Pitirim Sorokin", "Robert M. Hauser"], ["Robert K. Merton", "Michael Burawoy"]]
        .map(([x, y]) => [findByName(x), findByName(y)]).filter(([x, y]) => x && y)
        .map(([x, y]) => `<a class="chip" href="#/connect/${x.id}/${y.id}">${esc(x.name)} → ${esc(y.name)}</a>`).join("");
      notice(`<h2>Trace how two sociologists are connected</h2><p>Pick two people. The shortest lineage path between them is drawn in red, along with their nearest shared academic ancestor.</p><div class="starts">${ex}</div>`);
      if (a) renderPanel(a, { inConnect: true }); else renderPanelIntro();
      return;
    }
    clearNotice();
    const path = a === b ? [a] : shortestPath(a, b);
    const A = P.get(a), B = P.get(b);
    if (!path) {
      cy.elements().remove();
      notice(`<h2>No recorded lineage connects them</h2><p>${esc(A.name)} is in a cluster of ${plural(A.cs, "person", "people")}; ${esc(B.name)} is in a cluster of ${plural(B.cs, "person", "people")}.</p><p class="note">The Academic Family Tree has no chain of advisor links between these clusters. A missing link is as likely as a true separation.</p>`);
      renderConnectPanel(A, B, null, null);
      return;
    }
    // nearest shared ancestor
    const ua = bfsUp(a), ub = bfsUp(b);
    let lca = null, best = Infinity;
    for (const [n, da] of ua.dist) if (ub.dist.has(n)) { const s = Math.max(da, ub.dist.get(n)) * 1000 + da + ub.dist.get(n); if (s < best) { best = s; lca = n; } }

    const nodes = new Map(), edges = new Map();
    const addN = (id, cls) => { const p = P.get(id); const e = nodes.get(id) || nodeEl(p); e.classes = [e.classes, cls].filter(Boolean).join(" "); nodes.set(id, e); };
    const addE = (m, t, cls) => { const k = `e${m}-${t}`; const e = edges.get(k) || edgeEl(m, t); if (cls) e.classes = [e.classes, cls].filter(Boolean).join(" "); edges.set(k, e); };
    const linkDir = (x, y) => (kids.get(x) || []).includes(y) ? [x, y] : [y, x];
    // context: both lines up to the shared ancestor, in light ink
    if (lca != null) {
      for (const [prev, from] of [[ua.prev, a], [ub.prev, b]]) {
        const chain = chainDown(prev, lca, from);
        chain.forEach((n) => addN(n, "faint"));
        for (let i = 0; i < chain.length - 1; i++) addE(chain[i], chain[i + 1], "faint");
      }
    }
    // sibling context in light ink: each path node's advisors and a few other students,
    // so the red pencil traces through a tree rather than floating on blank paper
    const onPath = new Set(path);
    for (const n of path) {
      for (const m of (parents.get(n) || []).slice(0, 3)) if (!onPath.has(m)) { addN(m, "faint"); addE(m, n, "faint"); }
      let extra = 0;
      for (const c of kids.get(n) || []) {
        if (onPath.has(c)) continue;
        if (extra++ >= 3) break;
        addN(c, "faint"); addE(n, c, "faint");
      }
    }
    // the traced path, red pencil
    path.forEach((n) => { addN(n, "path"); const e = nodes.get(n); e.classes = e.classes.replace(/\bfaint\b/g, "").trim(); });
    for (let i = 0; i < path.length - 1; i++) { const [m, t] = linkDir(path[i], path[i + 1]); const e = edges.get(`e${m}-${t}`); if (e) e.classes = e.classes.replace(/\bfaint\b/g, ""); addE(m, t, "path"); }
    for (const id of [a, b]) { const e = nodes.get(id); e.classes += " end"; }
    draw([...nodes.values(), ...edges.values()]);
    // blue-pencil note on the canvas, as in the sketch
    const kin = lca != null ? kinTerm(ua.dist.get(lca), ub.dist.get(lca)) : null;
    const noteText = kin ? `${P.get(b).name} is ${P.get(a).name}'s academic ${kin}` : `linked through shared students or co-advising`;
    els.toolbar.insertAdjacentHTML("beforeend", `<span class="cnote">${esc(noteText)}</span>`);
    renderConnectPanel(A, B, path, lca != null ? { id: lca, da: ua.dist.get(lca), db: ub.dist.get(lca) } : null);
  }

  function renderConnectPanel(A, B, path, lca) {
    let verdict;
    if (!path) verdict = `No recorded path between <b>${esc(A.name)}</b> and <b>${esc(B.name)}</b>.`;
    else if (A.id === B.id) verdict = `Same person.`;
    else if (lca && lca.id === A.id) verdict = `<b>${esc(B.name)}</b> is <b>${esc(A.name)}</b>'s academic <b>${esc(kinTerm(0, lca.db))}</b> (${plural(lca.db, "generation")} down).`;
    else if (lca && lca.id === B.id) verdict = `<b>${esc(B.name)}</b> is <b>${esc(A.name)}</b>'s academic <b>${esc(kinTerm(lca.da, 0))}</b> (${plural(lca.da, "generation")} up).`;
    else if (lca) verdict = `<b>${esc(B.name)}</b> is <b>${esc(A.name)}</b>'s academic <b>${esc(kinTerm(lca.da, lca.db))}</b>, through ${esc(P.get(lca.id).name)} (${plural(lca.da, "generation")} and ${plural(lca.db, "generation")} below).`;
    else verdict = `Connected through shared students or co-advising, not through a common ancestor.`;

    const steps = path ? path.map((id, i) => {
      const nx = path[i + 1];
      let rel = "";
      if (nx != null) {
        const down = (kids.get(id) || []).includes(nx);
        const y = yearsOf.get(down ? `${id}>${nx}` : `${nx}>${id}`);
        const span = y ? ` (${[y[0], y[1]].filter(Boolean).join("–")})` : "";
        rel = (down ? "advised the next person" : "was advised by the next person") + span;
      }
      return `<li><a href="${lineageHash(id, state.params)}">${esc(P.get(id).name)}</a><span class="rel">${esc(P.get(id).inst || "")}${rel ? " · " + rel : ""}</span></li>`;
    }).join("") : "";

    els.panel.innerHTML = `
      <h2>Connection</h2>
      <p class="inst">${esc(A.name)} → ${esc(B.name)}</p>
      <p class="verdict">${verdict}</p>
      ${path ? `<div class="stats"><div class="stat"><span>Steps on the path</span><b>${fmt(path.length - 1)}</b></div>${lca ? `<div class="stat"><span>Nearest shared ancestor</span><b><a href="${lineageHash(lca.id, state.params)}">${esc(P.get(lca.id).name)}</a></b></div>` : ""}</div>
      <h3>Path</h3><ol class="steps">${steps}</ol>` : ""}
      <div class="actions"><a class="btn" href="${lineageHash(A.id, state.params)}">Open ${esc(A.name)}</a><a class="btn" href="${lineageHash(B.id, state.params)}">Open ${esc(B.name)}</a></div>`;
  }

  /* ---------------------------------------------------------------- tables */
  const COLS = { nd: "Descendants", ns: "Students", dep: "Generations below", cs: "Cluster" };

  function personTable(rows, { sortKey, onSort, ranked = true, selected }) {
    const caret = `<svg class="caret" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3"/></svg>`;
    const th = (k, label, num = true) => `<th class="${num ? "num" : ""}" ${sortKey === k ? 'aria-sort="descending"' : ""} scope="col"><button type="button" data-sort="${k}">${label}${sortKey === k ? caret : ""}</button></th>`;
    const html = `
      <table class="data"><thead><tr>${ranked ? `<th scope="col"><button type="button" tabindex="-1">#</button></th>` : ""}<th scope="col"><button type="button" data-sort="name">Name</button></th><th scope="col"><button type="button" tabindex="-1">Institution</button></th>${th("ns", "Students")}${th("nd", "Descendants")}${th("dep", "Gen. below")}${th("cs", "Cluster")}</tr></thead>
      <tbody>${rows.map((p, i) => `<tr data-id="${p.id}" tabindex="0" aria-selected="${selected === p.id}">${ranked ? `<td class="rank">${i + 1}</td>` : ""}<td><span class="nm ${isOut(p) ? "out" : ""}">${esc(p.name)}</span></td><td class="inst">${esc(p.inst)}</td><td class="num">${fmt(p.ns)}</td><td class="num">${fmt(p.nd)}</td><td class="num">${fmt(p.dep)}</td><td class="num">${fmt(p.cs)}</td></tr>`).join("")}</tbody></table>`;
    return { html, bind(root) {
      root.querySelectorAll("[data-sort]").forEach((b) => b.addEventListener("click", () => onSort(b.dataset.sort)));
      root.querySelectorAll("tbody tr").forEach((tr) => {
        const pick = () => { root.querySelectorAll("tbody tr[aria-selected=true]").forEach((x) => x.setAttribute("aria-selected", "false")); tr.setAttribute("aria-selected", "true"); renderPanel(+tr.dataset.id); };
        tr.addEventListener("click", pick);
        tr.addEventListener("dblclick", () => go(lineageHash(+tr.dataset.id, state.params)));
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(lineageHash(+tr.dataset.id, state.params)); else if (e.key === " ") { e.preventDefault(); pick(); } else if (e.key === "ArrowDown") tr.nextElementSibling?.focus(); else if (e.key === "ArrowUp") tr.previousElementSibling?.focus(); });
      });
    } };
  }

  function showDynasties(params) {
    state.view = "dynasties"; setTab("dynasties"); showCanvas(false); clearNotice(); els.toolbar.innerHTML = "";
    const sort = COLS[params.get("sort")] ? params.get("sort") : "nd";
    const socOnly = params.get("all") !== "1";
    const rows = index.filter((p) => !socOnly || !isOut(p)).sort((x, y) => y[sort] - x[sort] || y.nd - x.nd).slice(0, 100);
    const setQ = (k, v) => { const q = new URLSearchParams(params); if (v == null) q.delete(k); else q.set(k, v); go(`#/dynasties${q.toString() ? "?" + q : ""}`); };
    const t = personTable(rows, { sortKey: sort, onSort: (k) => k !== "name" && setQ("sort", k === "nd" ? null : k) });
    els.sheet.innerHTML = `
      <h2>Dynasties</h2>
      <p class="lede">The 100 largest academic families, ranked by ${COLS[sort].toLowerCase()}. Descendant counts include everyone below a person, inside the field or out. Double-click a row, or press Enter, to open its lineage.</p>
      <div class="sheet-controls">
        <span class="seg" role="group" aria-label="Rank by">${Object.entries(COLS).filter(([k]) => k !== "cs").map(([k, l]) => `<button type="button" data-k="${k}" aria-pressed="${k === sort}">${l}</button>`).join("")}</span>
        <label class="check"><input type="checkbox" id="socOnly" ${socOnly ? "checked" : ""}> Sociology only</label>
      </div>
      ${t.html}`;
    t.bind(els.sheet);
    els.sheet.querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => setQ("sort", b.dataset.k === "nd" ? null : b.dataset.k)));
    $("#socOnly").addEventListener("change", (e) => setQ("all", e.target.checked ? null : "1"));
    renderPanel(rows[0].id);
    els.sheet.querySelector("tbody tr")?.setAttribute("aria-selected", "true");
  }

  const GAPS = [
    { key: "no-advisor", label: "No advisor recorded", why: "Roots of the tree. A few are founders; most are missing links.", test: (p) => (p.f & F.NO_ADVISOR) && !isOut(p) },
    { key: "isolated", label: "No links at all", why: "Tagged sociology, but no advisor or student on record.", test: (p) => p.f & F.ISOLATED },
    { key: "small", label: "Small fragments", why: "Clusters of three or fewer, cut off from the main tree.", test: (p) => (p.f & F.SMALL) && !isOut(p) },
    { key: "prof-inst", label: "Practitioner-doctorate institution", why: "Capella, Walden, Alliant, La Verne and similar. Likely Ed.D.-style or professional doctorates.", test: (p) => (p.f & F.PROF_INST) && !isOut(p) },
    { key: "edu-area", label: "Education research area", why: "Research area is an education subject, or also listed in the education tree. Weaker signal; many are real sociologists.", test: (p) => (p.f & (F.EDU_AREA | F.EDUC)) && !(p.f & F.PROF_INST) && !isOut(p) },
    { key: "duplicate", label: "Possible duplicates", why: "Same name, or compatible names sharing an advisor or student.", test: (p) => p.f & F.DUP },
    { key: "multi", label: "Co-advised", why: "Two or more advisors on record. Not an error; worth a check.", test: (p) => p.f & F.MULTI_ADVISOR },
    { key: "outside", label: "Outside the field", why: "Kept because they advised or trained a sociologist.", test: (p) => p.f & F.OUTSIDE },
    { key: "no-openalex", label: "Not matched to OpenAlex", why: "No publication record linked yet.", test: (p) => !p.oa && !isOut(p), pending: () => !META.openalex_matched },
  ];

  function showGaps(key, params) {
    state.view = "gaps"; setTab("gaps"); showCanvas(false); clearNotice(); els.toolbar.innerHTML = "";
    const counts = GAPS.map((g) => ({ ...g, n: index.reduce((s, p) => s + (g.test(p) ? 1 : 0), 0) }));
    const cur = counts.find((g) => g.key === key) || null;
    const shown = Math.max(200, +(params.get("n") || 200));
    let table = "";
    if (cur) {
      const all = index.filter(cur.test).sort((x, y) => y.ns - x.ns || y.nd - x.nd || x.name.localeCompare(y.name));
      const t = personTable(all.slice(0, shown), { sortKey: "ns", ranked: false, onSort: () => {} });
      table = `<h2>${esc(cur.label)}</h2><p class="lede">${fmt(all.length)} people, most students first. ${esc(cur.why)}</p>${t.html}
        <div class="tbl-foot"><span>Showing ${fmt(Math.min(shown, all.length))} of ${fmt(all.length)}</span>${all.length > shown ? `<button type="button" class="btn" id="more">Show ${fmt(Math.min(200, all.length - shown))} more</button>` : ""}</div>`;
      setTimeout(() => { t.bind(els.sheet); $("#more")?.addEventListener("click", () => go(`#/gaps/${cur.key}?n=${shown + 200}`)); if (all[0]) { renderPanel(all[0].id); els.sheet.querySelector("tbody tr")?.setAttribute("aria-selected", "true"); } });
    }
    els.sheet.innerHTML = `
      <h2>Data gaps</h2>
      <p class="lede">Where the record is thin or suspect. Each count opens the people behind it.</p>
      <div class="gapgrid">${counts.map((g) => `<button type="button" class="gap" data-g="${g.key}" aria-pressed="${cur?.key === g.key}"><b>${g.pending?.() ? "…" : fmt(g.n)}</b><span class="lbl">${esc(g.label)}</span><span class="why">${g.pending?.() ? "OpenAlex matching is still running." : esc(g.why)}</span></button>`).join("")}</div>
      ${table || `<p class="muted">Pick a category to list the people in it.</p>`}`;
    els.sheet.querySelectorAll("[data-g]").forEach((b) => b.addEventListener("click", () => go(`#/gaps/${b.dataset.g}`)));
    if (!cur) renderPanelIntro();
  }





  /* ---------------------------------------------------------------- ORCID careers */
  function careerBlock(pid) {
    const c = CAREERS[pid];
    if (!c) return "";
    const [orcid, basis, items] = c;
    const now = new Date().getFullYear();
    const dated = items.filter((i) => i[4]);
    let chart = "";
    if (dated.length) {
      const lo = Math.min(...dated.map((i) => i[4])), hi = Math.max(now, ...dated.map((i) => i[5] || now));
      const W = 300, rowH = 15, x = (y) => ((y - lo) / Math.max(1, hi - lo)) * W;
      const rows = dated.slice(0, 14);
      const ticks = [];
      for (let y = Math.ceil(lo / 10) * 10; y <= hi; y += 10) ticks.push(y);
      chart = `<svg class="career" viewBox="0 0 ${W} ${rows.length * rowH + 18}" role="img" aria-label="Career timeline">
        ${ticks.map((y) => `<line x1="${x(y)}" x2="${x(y)}" y1="0" y2="${rows.length * rowH}" class="tick"/><text x="${x(y)}" y="${rows.length * rowH + 13}" class="tl">${y}</text>`).join("")}
        ${rows.map((i, k) => { const x0 = x(i[4]), x1 = Math.max(x0 + 3, x(i[5] || now)); return `<rect x="${x0}" y="${k * rowH + 3}" width="${x1 - x0}" height="${rowH - 6}" class="${i[0] === "education" ? "edu" : "emp"}${i[5] ? "" : " open"}"><title>${esc([i[3], i[2], i[1]].filter(Boolean).join(", "))} · ${i[4]}–${i[5] || "now"}</title></rect>`; }).join("")}
      </svg>`;
    }
    const row = (i) => `<li><span><span class="nm">${esc(i[1] || "")}</span><span class="rel">${esc([i[3], i[2]].filter(Boolean).join(" · "))}</span></span><span class="ct">${i[4] || ""}${i[4] || i[5] ? "–" : ""}${i[5] || (i[4] ? "now" : "")}</span></li>`;
    return `<h3>Career <span class="muted">· ORCID</span></h3>
      ${chart}<p class="muted career-key"><span class="sw edu"></span>Education <span class="sw emp"></span>Employment</p>
      <ul class="plist ev">${items.slice(0, 10).map(row).join("")}</ul>
      ${basis === "name" ? `<p class="note">ORCID record ${esc(CAREER_BASIS.name)}.</p>` : `<p class="muted">ORCID iD ${esc(CAREER_BASIS[basis] || basis)}.</p>`}
      <div class="actions"><a class="btn" href="https://orcid.org/${esc(orcid)}" target="_blank" rel="noopener">ORCID profile<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h7v7M13 3L5 11"/></svg></a></div>`;
  }

  /* ---------------------------------------------------------------- academic kinship */
  // a = generations from A up to the shared ancestor, b = generations from B up to it.
  // kinTerm(a, b) names what B is to A, as in genealogy ("first cousin twice removed").
  const ORD = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"];
  const TIMES = ["", "once", "twice", "three times", "four times", "five times", "six times"];
  const greats = (n) => (n > 0 ? "great-".repeat(n) : "");
  function kinTerm(a, b) {
    if (a === 0 && b === 0) return "self";
    if (a === 0) return b === 1 ? "student (academic child)" : `${greats(b - 2)}grandchild`;
    if (b === 0) return a === 1 ? "advisor (academic parent)" : `${greats(a - 2)}grandparent`;
    if (a === 1 && b === 1) return "sibling";
    if (a === 1) return `${b === 2 ? "" : greats(b - 3) + "grand-"}niece/nephew`;
    if (b === 1) return `${greats(a - 2)}aunt/uncle`;
    const n = Math.min(a, b) - 1, r = Math.abs(a - b);
    return `${ORD[n] || n + "th"} cousin${r ? " " + (TIMES[r] || r + " times") + " removed" : ""}`;
  }
  const kinShort = (a, b) => kinTerm(a, b).replace("student (academic child)", "student").replace("advisor (academic parent)", "advisor");

  const KIN_UP = 5, KIN_DOWN = 6;
  const kinCache = new Map();
  function relativesOf(pid) {
    if (kinCache.has(pid)) return kinCache.get(pid);
    const rel = new Map(); // other -> [a, b, via]
    const down = (root, a, skip) => {
      const seen = new Set([root]); let frontier = [root];
      for (let b = 1; b <= KIN_DOWN && frontier.length; b++) {
        const next = [];
        for (const n of frontier) for (const c of kids.get(n) || []) {
          if (seen.has(c) || skip.has(c)) continue;
          seen.add(c); next.push(c);
          if (!rel.has(c)) rel.set(c, [a, b, root]);
        }
        frontier = next;
      }
    };
    const up = bfsUp(pid);
    const line = new Set(up.dist.keys()); // pid and its ancestors: not their own relatives
    down(pid, 0, line);
    const anc = [...up.dist.entries()].filter(([u, a]) => u !== pid && a <= KIN_UP).sort((x, y) => x[1] - y[1]);
    for (const [u, a] of anc) if (!rel.has(u)) rel.set(u, [a, 0, u]);
    for (const [u, a] of anc) down(u, a, line);   // closest shared ancestor first, so the nearest relationship wins
    kinCache.set(pid, rel);
    return rel;
  }

  function kinSummary(pid) {
    const rel = relativesOf(pid);
    if (!rel.size) return "";
    const c = (f) => [...rel.values()].filter(([a, b]) => f(a, b)).length;
    const rows = [["Siblings", c((a, b) => a === 1 && b === 1)], ["Aunts/uncles", c((a, b) => b === 1 && a >= 2)],
      ["Nieces/nephews", c((a, b) => a === 1 && b >= 2)], ["First cousins", c((a, b) => a === 2 && b === 2)],
      ["All cousins", c((a, b) => a >= 2 && b >= 2)]].filter(([, n]) => n);
    return `<h3>Academic relatives</h3><div class="stats">${rows.map(([l, n]) => `<div class="stat"><span>${l}</span><b>${fmt(n)}</b></div>`).join("")}</div>
      <div class="actions"><a class="btn" href="#/kin/${pid}">Relationship chart</a></div>`;
  }

  function showKin(pid, params) {
    state.view = "kin"; setTab("lineage"); showCanvas(false); clearNotice(); els.toolbar.innerHTML = "";
    if (pid == null || !P.has(pid)) { go("#/"); return; }
    const p = P.get(pid), rel = relativesOf(pid);
    const grid = Array.from({ length: KIN_UP + 1 }, () => Array.from({ length: KIN_DOWN + 1 }, () => []));
    for (const [o, [a, b, via]] of rel) grid[a][b].push([o, via]);
    const sel = (params.get("cell") || "").split(",").map(Number);
    const cell = (a, b) => {
      const list = grid[a][b];
      const self = a === 0 && b === 0;
      const on = a === sel[0] && b === sel[1];
      return `<td class="kin ${self ? "self" : ""} ${list.length ? "has" : ""}" ${on ? 'aria-current="true"' : ""}>${self
        ? `<b>${esc(p.name)}</b>`
        : `<button type="button" data-cell="${a},${b}" ${list.length ? "" : "disabled"}><span class="term">${esc(kinShort(a, b))}</span><b>${list.length ? fmt(list.length) : "—"}</b></button>`}</td>`;
    };
    const rowLabel = (a) => a === 0 ? "You" : a === 1 ? "Advisor" : a === 2 ? "Grand-advisor" : `${greats(a - 2)}grand-advisor`;
    const colLabel = (b) => b === 0 ? "That ancestor" : b === 1 ? "Their students" : b === 2 ? "Grand-students" : `${greats(b - 2)}grand-students`;
    let list = "";
    if (sel.length === 2 && grid[sel[0]]?.[sel[1]]?.length) {
      const rows = grid[sel[0]][sel[1]].map(([o, via]) => ({ o, via, p: P.get(o) })).sort((x, y) => (y.p.nd - x.p.nd) || x.p.name.localeCompare(y.p.name));
      list = `<h2>${esc(p.name)}'s academic ${esc(kinTerm(sel[0], sel[1]))}${rows.length > 1 ? "s" : ""}</h2>
        <p class="lede">${fmt(rows.length)} ${rows.length === 1 ? "person" : "people"}, through ${plural(new Set(rows.map((r) => r.via)).size, "shared ancestor")}. Click a name for their lineage, or Connect to see the path.</p>
        <table class="data"><thead><tr><th scope="col"><button type="button" tabindex="-1">Name</button></th><th scope="col"><button type="button" tabindex="-1">Institution</button></th><th class="num" scope="col"><button type="button" tabindex="-1">PhD</button></th><th scope="col"><button type="button" tabindex="-1">Shared ancestor</button></th><th scope="col"><button type="button" tabindex="-1">Path</button></th></tr></thead>
        <tbody>${rows.slice(0, 400).map((r) => `<tr><td><a class="nm" href="${lineageHash(r.o, state.params)}">${esc(r.p.name)}</a></td><td class="inst">${esc(r.p.inst)}</td><td class="num">${r.p.yr ? (r.p.yb >= 3 ? "≈" : "") + r.p.yr : "—"}</td><td><a href="${lineageHash(r.via, state.params)}">${esc(P.get(r.via)?.name || "")}</a></td><td><a href="#/connect/${pid}/${r.o}">Connect</a></td></tr>`).join("")}</tbody></table>
        ${rows.length > 400 ? `<p class="muted">Showing 400 of ${fmt(rows.length)}.</p>` : ""}`;
    }
    els.sheet.innerHTML = `
      <h2>Academic relatives of ${esc(p.name)}</h2>
      <p class="lede">The classic cousin chart, applied to advising. Rows go up from ${esc(p.name)} to an academic ancestor; columns go down from that ancestor to a relative. Each cell names the relationship and counts the people in it, using the nearest shared ancestor. ${fmt(rel.size)} relatives within ${KIN_UP} generations up and ${KIN_DOWN} down.</p>
      <div class="kinwrap"><table class="kinchart"><thead><tr><th></th>${Array.from({ length: KIN_DOWN + 1 }, (_, b) => `<th scope="col">${colLabel(b)}</th>`).join("")}</tr></thead>
      <tbody>${Array.from({ length: KIN_UP + 1 }, (_, a) => `<tr><th scope="row">${rowLabel(a)}</th>${Array.from({ length: KIN_DOWN + 1 }, (_, b) => cell(a, b)).join("")}</tr>`).join("")}</tbody></table></div>
      ${list || `<p class="muted">Pick a cell to list the people in it.</p>`}`;
    els.sheet.querySelectorAll("[data-cell]").forEach((btn) => btn.addEventListener("click", () => go(`#/kin/${pid}?cell=${btn.dataset.cell}`)));
    renderPanel(pid);
  }

  /* ---------------------------------------------------------------- dissertations & committees */
  const DISS_SRC = (src) => src === "theses.fr" || src.startsWith("oai:") || src === "nsf_ddrig";
  function dissertationBlock(pid) {
    const recs = [];
    for (const m of parents.get(pid) || []) for (const e of EVIDENCE[m + ">" + pid] || []) if (DISS_SRC(e[0])) recs.push(e);
    if (!recs.length) return "";
    const seen = new Set();
    const items = recs.filter((e) => { const k = e[2] || e[4]; if (seen.has(k)) return false; seen.add(k); return true; });
    return `<h3>Dissertation</h3>${items.map(([src, yr, url, inst, title]) => `
      <div class="diss">
        ${title ? `<p class="diss-title">${esc(title)}</p>` : ""}
        <p class="muted">${[yr, inst, srcLabel(src)].filter(Boolean).map(esc).join(" · ")}</p>
        ${url ? `<a class="btn" href="${esc(url)}" target="_blank" rel="noopener">${src === "nsf_ddrig" ? "NSF award" : "Read the record"}<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h7v7M13 3L5 11"/></svg></a>` : ""}
      </div>`).join("")}`;
  }

  function committeeLists(pid) {
    const mine = COMMITTEE.get(pid) || [], served = SERVED.get(pid) || [];
    if (!mine.length && !served.length) return "";
    const row = (o, y) => `<li><a href="${lineageHash(o, state.params)}"><span class="nm">${esc(P.get(o)?.name || o)}</span></a><span class="ct">${y || ""}</span></li>`;
    return (mine.length ? `<h3>Dissertation committee</h3><ul class="plist">${mine.slice(0, 12).map(([o, y]) => row(o, y)).join("")}</ul>` : "")
      + (served.length ? `<h3>Served on ${plural(served.length, "committee")}</h3><ul class="plist">${served.slice(0, 12).map(([o, y]) => row(o, y)).join("")}</ul>${served.length > 12 ? `<p class="muted">and ${fmt(served.length - 12)} more</p>` : ""}` : "");
  }


  function textTies(pid) {
    const mine = NAMES.get(pid) || [], named = NAMED_IN.get(pid) || [];
    if (!mine.length && !named.length) return "";
    const row = ([o, sec, y, url, snip]) => `<li title="${esc(snip)}"><span><a href="${lineageHash(o, state.params)}"><span class="nm">${esc(P.get(o)?.name || o)}</span></a><span class="rel">${esc(TEXT_SEC[sec])}${y ? " · " + y : ""}</span></span>${url ? `<a class="ct" href="${esc(url)}" target="_blank" rel="noopener">PDF</a>` : ""}</li>`;
    return `<h3>Read from dissertations <span class="muted">· unverified</span></h3>`
      + (mine.length ? `<p class="muted">People named in ${esc(P.get(pid).name)}'s dissertation:</p><ul class="plist ev">${mine.slice(0, 15).map(row).join("")}</ul>` : "")
      + (named.length ? `<p class="muted">Named in ${plural(named.length, "dissertation")} by others:</p><ul class="plist ev">${named.slice(0, 15).map(row).join("")}</ul>` : "")
      + `<p class="note">Found by reading the PDF's acknowledgments and committee pages for people already in the data. Hover a row for the passage.</p>`;
  }

  function textOverlay(elements) {
    const shown = new Set(elements.filter((e) => e.group === "nodes" && !e.data.more).map((e) => +e.data.id));
    const out = [];
    for (const n of shown) for (const [st, sec] of NAMED_IN.get(n) || []) {
      if (shown.has(st) && !(kids.get(n) || []).includes(st)) out.push({ group: "edges", data: { id: `x${n}-${st}`, source: String(n), target: String(st) }, classes: `tx overlay${sec < 2 ? " strong" : ""}` });
    }
    return out;
  }

  function committeeOverlay(elements) {
    const shown = new Set(elements.filter((e) => e.group === "nodes" && !e.data.more).map((e) => +e.data.id));
    const out = [];
    for (const m of shown) for (const [st] of SERVED.get(m) || []) {
      if (shown.has(st) && !(kids.get(m) || []).includes(st)) out.push({ group: "edges", data: { id: `m${m}-${st}`, source: String(m), target: String(st) }, classes: "cm overlay" });
    }
    return out;
  }

  /* ---------------------------------------------------------------- co-authors */
  const coW = (n) => +(0.8 + Math.log2(n + 1) * 1.2).toFixed(2);
  // co-author links among the people already drawn (lineage overlay); excluded from the layout
  function coauthorOverlay(elements) {
    const shown = new Set(elements.filter((e) => e.group === "nodes" && !e.data.more).map((e) => +e.data.id));
    const out = [];
    for (const a of shown) for (const [b, n] of CO.get(a) || []) {
      if (a < b && shown.has(b)) out.push({ group: "edges", data: { id: `c${a}-${b}`, source: String(a), target: String(b), w: coW(n) }, classes: "co overlay" });
    }
    return out;
  }

  function coauthorList(pid) {
    if (!CO.size) return "";
    const l = CO.get(pid) || [];
    const total = CO_DEG[pid];
    if (!l.length) return total ? `<h3>Co-authors</h3><p class="muted">${fmt(total)} co-authors on OpenAlex, none of them in this dataset.</p>` : "";
    const row = ([o, n, y0, y1, rel]) => `<li><a href="#/co/${o}"><span class="nm">${esc(P.get(o)?.name || o)}</span></a><span class="ct">${fmt(n)} ${n === 1 ? "paper" : "papers"}${rel ? " · " + rel : ""}${y0 ? ` · ${y0 === y1 ? y0 : y0 + "–" + y1}` : ""}</span></li>`;
    return `<h3>Co-authors</h3>
      <p class="muted">${fmt(l.length)} in this dataset${total ? `, ${fmt(total)} on OpenAlex overall` : ""}.</p>
      <ul class="plist">${l.slice(0, 10).map(row).join("")}</ul>
      ${l.length > 10 ? `<button type="button" class="more-btn" data-expand>Show all ${fmt(l.length)}</button><ul class="plist" hidden data-rest>${l.slice(10).map(row).join("")}</ul>` : ""}
      ${state.view !== "co" ? `<div class="actions"><a class="btn" href="#/co/${pid}">Co-author network</a></div>` : ""}`;
  }

  function showCoauthors(pid, params) {
    state.view = "co"; setTab("co"); showCanvas(true); setColorKey(null);
    if (!CO.size) {
      cy.elements().remove(); els.toolbar.innerHTML = "";
      notice(`<h2>Co-author data isn't built yet</h2><p>Run <b>scripts/export_coauthors.py</b>, then reload.</p>`);
      return renderPanelIntro();
    }
    if (pid == null || !P.has(pid)) {
      pid = null;
      cy.elements().remove(); els.toolbar.innerHTML = "";
      const top = [...CO.entries()].filter(([p]) => P.has(p)).sort((a, b) => b[1].length - a[1].length).slice(0, 8);
      notice(`<h2>See who published together</h2><p>Co-authorship among ${fmt(CO_META.people)} people matched to OpenAlex: ${fmt(CO_META.pairs)} pairs, ${fmt(CO_META.advisor_student_coauthors)} of them advisor and student. Search a person, or start with one of the most connected.</p>
        <div class="starts">${top.map(([p, l]) => `<a class="chip" href="#/co/${p}">${esc(P.get(p).name)}<small>${fmt(l.length)}</small></a>`).join("")}</div>`);
      return renderPanelIntro();
    }
    clearNotice();
    const cap = Math.min(80, Math.max(10, +(params.get("n") || 30)));
    const p = P.get(pid);
    const list = (CO.get(pid) || []).slice(0, cap);
    els.toolbar.innerHTML = `<span class="title">${esc(p.name)}</span>
      <span class="sub">${plural((CO.get(pid) || []).length, "co-author")} in this dataset${CO_DEG[pid] ? ` · ${fmt(CO_DEG[pid])} on OpenAlex` : ""}</span>
      <span class="seg-label">Show</span>
      <span class="seg" role="group" aria-label="How many co-authors">${[15, 30, 60].map((n) => `<button type="button" data-n="${n}" aria-pressed="${n === cap}">${n}</button>`).join("")}</span>
      <a class="btn" href="${lineageHash(pid, state.params)}">Lineage</a>`;
    els.toolbar.querySelectorAll("[data-n]").forEach((b) => b.addEventListener("click", () => go(`#/co/${pid}?n=${b.dataset.n}`)));
    if (!list.length) {
      cy.elements().remove();
      notice(`<h2>No co-authors in this dataset</h2><p class="note">${p.oa ? `${esc(p.name)} is matched to OpenAlex, but none of their co-authors on the papers we looked up are in the lineage data.` : `${esc(p.name)} isn't matched to an OpenAlex record, so there are no papers to read co-authors from.`}</p>`);
      return renderPanel(pid);
    }
    const ids = new Set([pid, ...list.map(([o]) => o)]);
    const node = (id, cls) => { const e = nodeEl(P.get(id), cls); const n = (CO.get(pid) || []).find(([o]) => o === id)?.[1]; if (n) e.data.label = `${P.get(id).name}\n${fmt(n)} ${n === 1 ? "paper" : "papers"}`; return e; };
    const nodes = [node(pid, "focus"), ...list.map(([o]) => node(o, ""))];
    const ring = new Map(list.map(([o, n]) => [o, n >= 5 ? 3 : n >= 2 ? 2 : 1]));
    nodes.forEach((e) => { e.data.ring = +e.data.id === pid ? 4 : ring.get(+e.data.id); });
    const edges = [];
    for (const [o, n] of list) edges.push({ group: "edges", data: { id: `c${pid}-${o}`, source: String(pid), target: String(o), w: coW(n) }, classes: "co ego" });
    for (const a of ids) for (const [b, n] of CO.get(a) || []) {
      if (a !== pid && b !== pid && a < b && ids.has(b)) edges.push({ group: "edges", data: { id: `c${a}-${b}`, source: String(a), target: String(b), w: coW(n) }, classes: "co faint" });
    }
    // advising links among the drawn people, as in the lineage view
    for (const a of ids) for (const t of kids.get(a) || []) if (ids.has(t)) edges.push(edgeEl(a, t));
    draw([...nodes, ...edges], { fitTo: `node[id="${pid}"]`, layoutOpts: { name: "concentric", concentric: (n) => n.data("ring"), levelWidth: () => 1, minNodeSpacing: 28, nodeDimensionsIncludeLabels: true, animate: false } });
    renderPanel(pid);
  }

  /* ---------------------------------------------------------------- generic table */
  // cols: [{ key, label, num, fmt }]; rows: objects with .id
  function dataTable(cols, rows, { sortKey, onSort, selected, onPick, onOpen }) {
    const caret = `<svg class="caret" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3"/></svg>`;
    const head = cols.map((c) => `<th class="${c.num ? "num" : ""}" ${sortKey === c.key ? 'aria-sort="descending"' : ""} scope="col"><button type="button" ${c.sort === false ? 'tabindex="-1"' : `data-sort="${c.key}"`}>${c.label}${sortKey === c.key ? caret : ""}</button></th>`).join("");
    const body = rows.map((r) => `<tr data-id="${r.id}" tabindex="0" aria-selected="${selected === r.id}">${cols.map((c) => `<td class="${c.num ? "num" : ""} ${c.cls || ""}">${c.fmt ? c.fmt(r) : esc(r[c.key])}</td>`).join("")}</tr>`).join("");
    return { html: `<table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`, bind(root) {
      root.querySelectorAll("[data-sort]").forEach((b) => b.addEventListener("click", () => onSort?.(b.dataset.sort)));
      root.querySelectorAll("tbody tr").forEach((tr) => {
        const id = isNaN(+tr.dataset.id) ? tr.dataset.id : +tr.dataset.id;
        const pick = () => { root.querySelectorAll("tbody tr[aria-selected=true]").forEach((x) => x.setAttribute("aria-selected", "false")); tr.setAttribute("aria-selected", "true"); onPick?.(id); };
        tr.addEventListener("click", pick);
        tr.addEventListener("dblclick", () => onOpen?.(id));
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") onOpen?.(id); else if (e.key === " ") { e.preventDefault(); pick(); } else if (e.key === "ArrowDown") tr.nextElementSibling?.focus(); else if (e.key === "ArrowUp") tr.previousElementSibling?.focus(); });
      });
    } };
  }
  const pct = (x) => x == null ? "—" : `${(x * 100).toFixed(x < 0.1 ? 1 : 0)}%`;
  const noContext = () => {
    showCanvas(false); clearNotice(); els.toolbar.innerHTML = "";
    els.sheet.innerHTML = `<h2>Schools and institutions need one more export</h2><p class="lede">Run <b>scripts/export_context.py</b> to build data/context.json, then reload.</p>`;
    renderPanelIntro();
  };

  /* ---------------------------------------------------------------- schools */
  const memberCache = new Map();
  function schoolMembers(kind, id) {
    const key = kind + ":" + id;
    if (memberCache.has(key)) return memberCache.get(key);
    let out = [];
    if (kind === "curated") {
      const seen = new Set(CTX.schools[id].founders); const st = [...seen];
      while (st.length) for (const c of kids.get(st.pop()) || []) if (!seen.has(c)) { seen.add(c); st.push(c); }
      out = [...seen];
    } else if (kind === "detected") out = [...PC].filter(([, c]) => c.comm === id).map(([p]) => p);
    else if (kind === "subfields") out = [...PC].filter(([, c]) => c.sf?.includes(id)).map(([p]) => p);
    else if (kind === "topics") out = [...PC].filter(([, c]) => c.tp?.includes(id)).map(([p]) => p);
    out = out.filter((p) => P.has(p)).sort((a, b) => P.get(b).nd - P.get(a).nd);
    memberCache.set(key, out);
    return out;
  }
  function trainedAt(pids, n = 8) {
    const c = new Map();
    for (const p of pids) { const l = PC.get(p)?.phd; if (l != null) c.set(l, (c.get(l) || 0) + 1); }
    return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, n);
  }
  const instCountList = (pairs, unit) => pairs.length
    ? `<ul class="plist">${pairs.map(([l, n]) => `<li>${instLink(l)}<span class="ct">${fmt(n)} ${unit}</span></li>`).join("")}</ul>`
    : `<p class="muted">None on record.</p>`;

  const SCHOOL_KINDS = { curated: "Curated schools", detected: "Detected communities", subfields: "Subfields", topics: "Publication topics" };
  let schoolSort = { curated: "size", detected: "size", subfields: "size", topics: "size" };

  function showSchools(kind, id) {
    state.view = "schools"; setTab("schools");
    if (!CTX) return noContext();
    showCanvas(false); clearNotice(); els.toolbar.innerHTML = "";
    if (!SCHOOL_KINDS[kind]) kind = "curated";
    const seg = `<span class="seg" role="group" aria-label="Kind of school">${Object.entries(SCHOOL_KINDS).map(([k, l]) => `<button type="button" data-kind="${k}" aria-pressed="${k === kind}">${l}</button>`).join("")}</span>`;
    let lede = "", table = null, rows = [];
    if (kind === "curated") {
      lede = `Schools named by their founders. Members are the founders and every recorded academic descendant, so schools overlap; "closest" counts people whose nearest founder belongs to this school. Edit the list in data/schools.json.`;
      rows = CTX.schools.map((s, i) => ({ id: i, name: s.name, founders: s.founders.map((f) => P.get(f)?.name).filter(Boolean), size: s.size, exclusive: s.exclusive, depth: s.depth, main: s.top_institutions[0]?.[0] }));
      table = [
        { key: "name", label: "School", fmt: (r) => `<span class="nm">${esc(r.name)}</span>` },
        { key: "founders", label: "Founders", sort: false, cls: "inst", fmt: (r) => esc(r.founders.slice(0, 2).join(", ") + (r.founders.length > 2 ? ` +${r.founders.length - 2}` : "")) },
        { key: "size", label: "Members", num: true, fmt: (r) => fmt(r.size) },
        { key: "exclusive", label: "Closest", num: true, fmt: (r) => fmt(r.exclusive) },
        { key: "depth", label: "Generations", num: true, fmt: (r) => fmt(r.depth) },
        { key: "main", label: "Main PhD institution", sort: false, cls: "inst", fmt: (r) => esc(INST.get(r.main)?.name || "") },
      ];
    } else if (kind === "detected") {
      lede = `Communities found by the Louvain algorithm in the advisor network: groups more tightly linked to each other than to the rest. Each is named after its most prolific member and its most common PhD institution. These are data-driven groupings; interpret the labels with care.`;
      rows = CTX.communities.map((c, i) => ({ id: i, name: c.label, size: c.size, main: c.main_institution, share: c.institution_share }));
      table = [
        { key: "name", label: "Community", fmt: (r) => `<span class="nm">${esc(r.name)}</span>` },
        { key: "size", label: "People", num: true, fmt: (r) => fmt(r.size) },
        { key: "share", label: "At main institution", num: true, fmt: (r) => pct(r.share) },
      ];
    } else if (kind === "subfields") {
      lede = `Research areas from the Academic Family Tree record (subject codes, often from ProQuest). "Inherited" is the share of advisor-to-student pairs where the student shares the advisor's subfield; "baseline" is how common the subfield is overall. A high ratio means the subfield passes down lineages.`;
      rows = CTX.subfields.map((s, i) => ({ id: i, name: s.name, size: s.size, pairs: s.advised_pairs, inh: s.inheritance, base: s.baseline, lift: s.inheritance != null && s.baseline ? s.inheritance / s.baseline : null }));
      table = [
        { key: "name", label: "Subfield", fmt: (r) => `<span class="nm">${esc(r.name)}</span>` },
        { key: "size", label: "People", num: true, fmt: (r) => fmt(r.size) },
        { key: "pairs", label: "Advised pairs", num: true, fmt: (r) => fmt(r.pairs) },
        { key: "inh", label: "Inherited", num: true, fmt: (r) => pct(r.inh) },
        { key: "base", label: "Baseline", num: true, fmt: (r) => pct(r.base) },
        { key: "lift", label: "Ratio", num: true, fmt: (r) => r.lift == null ? "—" : `${r.lift.toFixed(r.lift < 10 ? 1 : 0)}×` },
      ];
    }
    if (kind === "topics" && CTX.topics?.length) {
      lede = `Research topics from OpenAlex, each person's top three across their publications. Unlike the subfield tags, these come from each person's own papers, so "inherited" (the student shares the advisor's topic) is not built into the data.`;
      rows = CTX.topics.map((t, i) => ({ id: i, name: t.name, field: t.subfield, size: t.size, pairs: t.advised_pairs, inh: t.inheritance, base: t.baseline, lift: t.inheritance != null && t.baseline ? t.inheritance / t.baseline : null }));
      table = [
        { key: "name", label: "Topic", fmt: (r) => `<span class="nm">${esc(r.name)}</span>` },
        { key: "field", label: "Subfield", sort: false, cls: "inst" },
        { key: "size", label: "People", num: true, fmt: (r) => fmt(r.size) },
        { key: "pairs", label: "Advised pairs", num: true, fmt: (r) => fmt(r.pairs) },
        { key: "inh", label: "Inherited", num: true, fmt: (r) => pct(r.inh) },
        { key: "base", label: "Baseline", num: true, fmt: (r) => pct(r.base) },
        { key: "lift", label: "Ratio", num: true, fmt: (r) => r.lift == null ? "—" : `${r.lift.toFixed(r.lift < 10 ? 1 : 0)}×` },
      ];
    } else if (kind === "topics") {
      els.sheet.innerHTML = `<h2>Schools of thought</h2><div class="sheet-controls">${seg}</div>
        <p class="lede">Publication topics come from OpenAlex once people are matched to their publication records.</p>
        <p class="note">OpenAlex matching is still running (${fmt(META.openalex_matched)} matched so far). Re-run the exports when it finishes and topics will appear here.</p>`;
      bindSeg(); renderPanelIntro(); return;
    }
    const sk = schoolSort[kind];
    rows.sort((a, b) => ((b[sk] ?? -1) - (a[sk] ?? -1)) || 0);
    const sel = id != null && rows.some((r) => r.id === id) ? id : rows[0]?.id;
    const t = dataTable(table, rows, {
      sortKey: sk, selected: sel,
      onSort: (k) => { schoolSort[kind] = k; showSchools(kind, sel); },
      onPick: (i) => { history.replaceState(null, "", `#/schools/${kind}/${i}`); renderSchoolPanel(kind, i); },
      onOpen: (i) => openSchoolLineage(kind, i),
    });
    els.sheet.innerHTML = `<h2>Schools of thought</h2><div class="sheet-controls">${seg}</div><p class="lede">${esc(lede)}</p>${t.html}`;
    t.bind(els.sheet); bindSeg();
    if (sel != null) renderSchoolPanel(kind, sel);
    function bindSeg() { els.sheet.querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => go(`#/schools/${b.dataset.kind}`))); }
  }

  function schoolLead(kind, id) {
    if (kind === "curated") return CTX.schools[id].founders[0];
    if (kind === "detected") return CTX.communities[id].top;
    return schoolMembers(kind, id)[0];
  }
  function openSchoolLineage(kind, id) {
    const mode = kind === "curated" ? "school" : kind === "detected" ? "community" : kind === "topics" ? "topic" : "subfield";
    const lead = schoolLead(kind, id);
    if (lead != null && P.has(lead)) pinAndColor(mode, id, lead);
  }

  function renderSchoolPanel(kind, id) {
    const members = schoolMembers(kind, id);
    let title, sub, stats = "", lists = "", note = "";
    if (kind === "curated") {
      const s = CTX.schools[id];
      title = s.name; sub = s.note;
      stats = `<div class="stat"><span>Members</span><b>${fmt(s.size)}</b></div><div class="stat"><span>Closest to this school</span><b>${fmt(s.exclusive)}</b></div><div class="stat"><span>Generations deep</span><b>${fmt(s.depth)}</b></div>`;
      lists = `<h3>Founders</h3>${personList(s.founders.filter((f) => P.has(f)))}`
        + `<h3>Overlaps with</h3>${s.overlap.length ? `<ul class="plist">${s.overlap.map(([sid, n]) => { const j = CTX.schools.findIndex((x) => x.id === sid); return `<li><a href="#/schools/curated/${j}">${esc(CTX.schools[j].name)}</a><span class="ct">${fmt(n)} shared</span></li>`; }).join("")}</ul>` : `<p class="muted">No overlap.</p>`}`;
      note = `Membership is the founders plus every recorded descendant. The founder attributions are conventional groupings; edit data/schools.json to change them.`;
    } else if (kind === "detected") {
      const c = CTX.communities[id];
      title = c.label; sub = "Detected community";
      stats = `<div class="stat"><span>People</span><b>${fmt(c.size)}</b></div><div class="stat"><span>Trained at the main institution</span><b>${pct(c.institution_share)}</b></div>`;
      note = `Found by the Louvain algorithm on advisor links. The name comes from the most prolific member and the most common PhD institution.`;
    } else if (kind === "topics") {
      const t = CTX.topics[id];
      title = t.name; sub = `Publication topic · ${t.subfield || t.field || ""}`;
      stats = `<div class="stat"><span>People</span><b>${fmt(t.size)}</b></div><div class="stat"><span>Advisor-student pairs</span><b>${fmt(t.advised_pairs)}</b></div><div class="stat"><span>Student shares the topic</span><b>${pct(t.inheritance)}</b></div><div class="stat"><span>Baseline share of people</span><b>${pct(t.baseline)}</b></div>`;
      note = `From OpenAlex: each person's top three topics across their matched publications. Only people matched to OpenAlex appear.`;
    } else {
      const s = CTX.subfields[id];
      title = s.name; sub = "Subfield";
      stats = `<div class="stat"><span>People</span><b>${fmt(s.size)}</b></div><div class="stat"><span>Advisor-student pairs</span><b>${fmt(s.advised_pairs)}</b></div><div class="stat"><span>Student shares the subfield</span><b>${pct(s.inheritance)}</b></div><div class="stat"><span>Baseline share of people</span><b>${pct(s.baseline)}</b></div>`;
      note = `From the research-area field. Many entries are ProQuest subject codes, so a subtree imported from ProQuest can share a code by construction.`;
    }
    const leaders = members.filter((p) => kind !== "curated" || !CTX.schools[id].founders.includes(p)).slice(0, 12);
    els.panel.innerHTML = `
      <h2>${esc(title)}</h2><p class="inst">${esc(sub)}</p>
      <div class="stats">${stats}</div>
      ${lists}
      <h3>Leading members</h3>${personList(leaders)}
      <h3>Where members trained</h3>${instCountList(kind === "curated" ? CTX.schools[id].top_institutions : trainedAt(members), "PhDs")}
      <p class="note">${esc(note)}</p>
      <div class="actions"><button type="button" class="btn primary" id="colorSchool">Color a lineage by this</button></div>`;
    $("#colorSchool").addEventListener("click", () => openSchoolLineage(kind, id));
    els.panel.scrollTop = 0;
  }

  /* ---------------------------------------------------------------- institutions */
  let byPhd = null, byFac = null;
  function instIndexes() {
    if (byPhd) return;
    byPhd = new Map(); byFac = new Map();
    for (const [p, c] of PC) {
      if (c.phd != null) { if (!byPhd.has(c.phd)) byPhd.set(c.phd, []); byPhd.get(c.phd).push(p); }
      if (c.fac != null) { if (!byFac.has(c.fac)) byFac.set(c.fac, []); byFac.get(c.fac).push(p); }
    }
  }
  const INST_VIEWS = { network: "Placement network", map: "Map", table: "Table" };

  function showInstitutions(sel, params) {
    state.view = "institutions"; setTab("institutions");
    if (!CTX) return noContext();
    instIndexes();
    if (sel != null && !INST.has(sel)) sel = null;
    const v = INST_VIEWS[params.get("v")] ? params.get("v") : "network";
    const toolbar = (extra = "") => {
      els.toolbar.innerHTML = `<span class="title">Institutions</span>
        <span class="seg" role="group" aria-label="View">${Object.entries(INST_VIEWS).map(([k, l]) => `<button type="button" data-v="${k}" aria-pressed="${k === v}">${l}</button>`).join("")}</span>
        ${CTX.hiring_flows?.length ? `<label class="selectlbl">Placement data <select id="flowSrc">${Object.entries(FLOW_NAME).map(([k, l]) => `<option value="${k}" ${k === FLOW_SRC ? "selected" : ""}>${l}</option>`).join("")}</select></label>` : ""}
        <span class="sub">${extra}</span>`;
      $("#flowSrc")?.addEventListener("change", (e) => { setFlowSource(e.target.value); route(); });
      els.toolbar.querySelectorAll("[data-v]").forEach((b) => b.addEventListener("click", () => go(`${sel != null ? `#/i/${sel}` : "#/institutions"}?v=${b.dataset.v}`)));
    };
    clearNotice();
    if (v === "network") {
      showCanvas(true); setColorKey(null);
      const went = FLOW_SRC === "census" ? "were hired as faculty" : "later advised";
      toolbar(sel != null ? `Red arrows: where its PhDs ${went}. Dashed: where its faculty trained. Click a partner to follow it.` : `The 20 busiest institutions. Arrows run from where people trained to where they ${went}; clockwise from the top, institutions that place more PhDs elsewhere than they hire in.`);
      drawPlacementNetwork(sel);
      els.legend.hidden = true;
    } else if (v === "map") {
      showCanvas(true, { map: true });
      const withGeo = [...INST.values()].filter((i) => i.lat != null).length;
      toolbar(`${fmt(withGeo)} of ${fmt(INST.size)} institutions have coordinates. ${sel != null ? "Red lines: where its PhDs went. Dashed: where its faculty trained." : "Circle size is sociology PhDs granted. Click one to trace its placements."}`);
      drawMap(sel);
    } else {
      showCanvas(false); els.toolbar.innerHTML = "";
      showInstTable(sel, params);
    }
    if (sel != null) renderInstPanel(sel); else if (v !== "table") renderInstIntro();
  }

  function drawPlacementNetwork(sel) {
    const size = (i) => Math.round(14 + 1.8 * Math.sqrt(i.phds));
    const net = (i) => { const t = tot(i.id); return t.out - t.in; };
    const node = (i, cls = "") => ({ group: "nodes", data: { id: "i" + i.id, loc: i.id, label: shortInst(i.name), size: size(i), net: net(i) }, classes: "inst " + cls });
    const edge = (a, b, n, cls = "") => ({ group: "edges", data: { id: `f${a}-${b}`, source: "i" + a, target: "i" + b, w: +(0.8 + Math.log2(n + 1) * 1.1).toFixed(2) }, classes: "flow " + cls });
    if (sel != null) {
      // ego view: the institution in the centre, everyone it sent PhDs to or hired from around it
      const partners = new Map();
      for (const [b, n] of (flowsOut.get(sel) || [])) partners.set(b, (partners.get(b) || 0) + n);
      for (const [b, n] of (flowsIn.get(sel) || [])) partners.set(b, (partners.get(b) || 0) + n);
      const top = [...partners.entries()].filter(([l]) => INST.has(l)).sort((x, y) => y[1] - x[1]).slice(0, 28).map(([l]) => l);
      const keep = new Set(top);
      const nodes = [node(INST.get(sel), "sel"), ...top.map((l) => node(INST.get(l)))];
      const edges = [
        ...(flowsOut.get(sel) || []).filter(([b]) => keep.has(b)).map(([b, n]) => edge(sel, b, n, "sel")),
        ...(flowsIn.get(sel) || []).filter(([b]) => keep.has(b)).map(([b, n]) => edge(b, sel, n, "sel selin")),
      ];
      draw([...nodes, ...edges], { layoutOpts: { name: "concentric", concentric: (n) => (n.data("loc") === sel ? 2 : 1), levelWidth: () => 1, minNodeSpacing: 46, animate: false } });
      return;
    }
    // overview: the 20 busiest institutions on one ring, clockwise from the top by net placement
    const busy = (i) => { const t = tot(i.id); return t.out + t.in; };
    const pool = [...INST.values()].filter((i) => busy(i) > 0).sort((a, b) => busy(b) - busy(a)).slice(0, 20);
    const minN = FLOW_SRC === "census" ? 4 : 2;
    const ids = new Set(pool.map((i) => i.id));
    const edges = [];
    for (const i of pool) for (const [b, n] of flowsOut.get(i.id) || []) if (ids.has(b) && n >= minN) edges.push(edge(i.id, b, n));
    const radius = Math.max(200, Math.min(cy.width(), cy.height() - 140) / 2 - 80);
    draw([...pool.map((i) => node(i)), ...edges], { layoutOpts: { name: "circle", radius, startAngle: -Math.PI / 2, sort: (a, b) => b.data("net") - a.data("net"), animate: false } });
  }

  let lmap = null, lmarkers = null, llines = null;
  function drawMap(sel) {
    if (!window.L) { els.map.innerHTML = `<p class="notice">The map library didn't load.</p>`; return; }
    if (!lmap) {
      // No tile service: land drawn in ink from a vendored Natural Earth outline, like a hand-ruled base map.
      lmap = L.map(els.map, { zoomSnap: 0.5, minZoom: 2, maxZoom: 9, attributionControl: true }).setView([38, -40], 3);
      lmap.attributionControl.setPrefix(false).addAttribution("Land: Natural Earth");
      fetch("data/land-110m.geojson").then((r) => r.json()).then((g) => {
        L.geoJSON(g, { interactive: false, style: { color: INK, weight: 0.8, opacity: 0.55, fillColor: "#f6f4ef", fillOpacity: 1 } }).addTo(lmap).bringToBack();
      }).catch(() => {});
      llines = L.layerGroup().addTo(lmap); lmarkers = L.layerGroup().addTo(lmap);
    }
    // the map starts under the toolbar band (on narrow screens the toolbar is in flow already)
    els.map.style.top = getComputedStyle(els.toolbar).position === "absolute" ? els.toolbar.offsetHeight + "px" : "";
    requestAnimationFrame(() => lmap.invalidateSize());
    lmarkers.clearLayers(); llines.clearLayers();
    const A = sel != null ? INST.get(sel) : null;
    if (A && A.lat != null) {
      for (const [b, n] of flowsIn.get(sel) || []) { const B = INST.get(b); if (B?.lat != null) llines.addLayer(L.polyline([[B.lat, B.lon], [A.lat, A.lon]], { color: INK, weight: 1 + Math.log2(n + 1), opacity: 0.6, dashArray: "4 4" })); }
      for (const [b, n] of flowsOut.get(sel) || []) { const B = INST.get(b); if (B?.lat != null) llines.addLayer(L.polyline([[A.lat, A.lon], [B.lat, B.lon]], { color: RED, weight: 1.5 + Math.log2(n + 1) * 1.4, opacity: 0.9 })); }
    }
    const linked = new Set(A ? [...(flowsOut.get(sel) || []), ...(flowsIn.get(sel) || [])].map(([l]) => l) : []);
    for (const i of INST.values()) {
      if (i.lat == null || i.lon == null || !(i.phds || i.people)) continue;
      const isSel = i.id === sel;
      const m = L.circleMarker([i.lat, i.lon], { radius: 2.5 + Math.sqrt(i.phds) * 0.8, color: isSel ? RED : INK, weight: isSel ? 2.5 : 1.1, fillColor: isSel ? RED : PAPER, fillOpacity: A && !isSel && !linked.has(i.id) ? 0.4 : 0.9, opacity: A && !isSel && !linked.has(i.id) ? 0.35 : 1 });
      m.bindTooltip(`${esc(i.name)} · ${fmt(i.phds)} PhDs`, { direction: "top", offset: [0, -4] });
      m.on("click", () => go(`#/i/${i.id}?v=map`));
      lmarkers.addLayer(m);
    }
    if (A && A.lat != null) lmap.setView([A.lat, A.lon], Math.max(lmap.getZoom(), 4), { animate: false });
  }

  let instSort = "phds";
  function showInstTable(sel, params) {
    const rows = [...INST.values()].map((i) => { const t = tot(i.id); return { ...i, placed_out: t.out, hired_in: t.in, self_hired: t.self, net: t.out - t.in, rank: i.prestige_rank ?? null, place: [i.city, i.country].filter((x) => x && x !== "NULL").join(", ") }; })
      .filter((i) => i.phds || i.placed_out || i.hired_in || i.rank);
    rows.sort(instSort === "rank" ? (a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9) : (a, b) => (b[instSort] ?? 0) - (a[instSort] ?? 0));
    const shown = rows.slice(0, Math.max(150, +(params.get("n") || 150)));
    const t = dataTable([
      { key: "name", label: "Institution", fmt: (r) => `<span class="nm">${esc(r.name)}</span>` },
      { key: "place", label: "Place", sort: false, cls: "inst" },
      ...(CTX.hiring ? [{ key: "rank", label: "Prestige rank", num: true, fmt: (r) => r.rank ?? "—" }] : []),
      { key: "phds", label: "PhDs", num: true, fmt: (r) => fmt(r.phds) },
      { key: "advisors", label: "Advisors", num: true, fmt: (r) => fmt(r.advisors) },
      { key: "placed_out", label: "Placed elsewhere", num: true, fmt: (r) => fmt(r.placed_out) },
      { key: "hired_in", label: "Hired in", num: true, fmt: (r) => fmt(r.hired_in) },
      { key: "net", label: "Net", num: true, fmt: (r) => (r.net > 0 ? "+" : "") + fmt(r.net) },
    ], shown, {
      sortKey: instSort, selected: sel,
      onSort: (k) => { instSort = k; showInstTable(sel, params); },
      onPick: (l) => { history.replaceState(null, "", `#/i/${l}?v=table`); renderInstPanel(l); },
      onOpen: (l) => go(`#/i/${l}?v=network`),
    });
    els.sheet.innerHTML = `<h2>Institutions</h2>
      <div class="sheet-controls"><span class="seg" role="group" aria-label="View">${Object.entries(INST_VIEWS).map(([k, l]) => `<button type="button" data-v="${k}" aria-pressed="${k === "table"}">${l}</button>`).join("")}</span></div>
      ${CTX.hiring_flows?.length ? `<div class="sheet-controls"><label class="selectlbl">Placement data <select id="flowSrcT">${Object.entries(FLOW_NAME).map(([k, l]) => `<option value="${k}" ${k === FLOW_SRC ? "selected" : ""}>${l}</option>`).join("")}</select></label></div>` : ""}
      <p class="lede">${FLOW_SRC === "census"
        ? `Placement from the faculty hiring census: every US sociology faculty member 2011–20, by PhD institution and employer (${esc(CTX.hiring.citation)}). Prestige rank is the census's own ranking (1 = top). "Net" is PhDs placed on other faculties minus faculty hired from elsewhere.`
        : `Placement from the Academic Family Tree: where people trained versus where they later advised students. Known only for people who went on to advise, so counts are small.`} PhDs are sociology PhDs on record in the Academic Family Tree.</p>
      ${t.html}<div class="tbl-foot"><span>Showing ${fmt(shown.length)} of ${fmt(rows.length)}</span>${rows.length > shown.length ? `<button type="button" class="btn" id="moreInst">Show more</button>` : ""}</div>`;
    t.bind(els.sheet);
    $("#flowSrcT")?.addEventListener("change", (e) => { setFlowSource(e.target.value); route(); });
    els.sheet.querySelectorAll("[data-v]").forEach((b) => b.addEventListener("click", () => go(`${sel != null ? `#/i/${sel}` : "#/institutions"}?v=${b.dataset.v}`)));
    $("#moreInst")?.addEventListener("click", () => go(`#/institutions?v=table&n=${shown.length + 150}`));
    if (sel != null) renderInstPanel(sel); else if (shown[0]) { renderInstPanel(shown[0].id); els.sheet.querySelector("tbody tr")?.setAttribute("aria-selected", "true"); }
  }

  function renderInstIntro() {
    const totalPlaced = [...flowsOut.values()].reduce((s, l) => s + sum(l), 0);
    els.panel.innerHTML = `<h2>Institutions</h2><p class="inst">Where sociologists trained and where they went</p>
      <div class="stats"><div class="stat"><span>Institutions</span><b>${fmt(INST.size)}</b></div>
      <div class="stat"><span>Placement links</span><b>${fmt([...flowsOut.values()].reduce((s, l) => s + l.length, 0))}</b></div>
      <div class="stat"><span>Faculty placed at another institution</span><b>${fmt(totalPlaced)}</b></div></div>
      <p class="note">${FLOW_SRC === "census" ? `Placement source: faculty hiring census (${esc(CTX.hiring.citation)}, ${esc(CTX.hiring.license)}). ${fmt(CTX.hiring.faculty_matched)} of ${fmt(CTX.hiring.faculty)} faculty matched to institutions here.` : esc(CTX.meta.note)}</p>
      <div class="panel-empty"><h3>How to read it</h3><p>Click an institution to see its PhDs, top advisors, where its students went, where its faculty trained, and which schools of thought run through it.</p></div>`;
  }

  function renderInstPanel(loc) {
    const i = INST.get(loc);
    const T = tot(loc);
    const phds = byPhd.get(loc) || [];
    const fac = byFac.get(loc) || [];
    const advCount = new Map();
    for (const p of phds) for (const m of parents.get(p) || []) advCount.set(m, (advCount.get(m) || 0) + 1);
    const topAdv = [...advCount.entries()].filter(([m]) => P.has(m)).sort((a, b) => b[1] - a[1]).slice(0, 8);
    const schoolCount = new Map();
    for (const p of phds) { const s = PC.get(p)?.school; if (s != null) schoolCount.set(s, (schoolCount.get(s) || 0) + 1); }
    const schools = [...schoolCount.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
    const place = [i.city, i.country].filter((x) => x && x !== "NULL").join(", ");
    els.panel.innerHTML = `
      <h2>${esc(i.name)}</h2><p class="inst">${esc(place || "Location not recorded")}</p>
      <div class="stats">
        <div class="stat"><span>Sociology PhDs granted</span><b>${fmt(i.phds)}</b></div>
        <div class="stat"><span>Advisors who supervised here</span><b>${fmt(i.advisors)}</b></div>
        <div class="stat"><span>People who advised here</span><b>${fmt(fac.length)}</b></div>
        ${i.prestige_rank ? `<div class="stat"><span>Prestige rank (hiring census)</span><b>${fmt(i.prestige_rank)}</b></div>` : ""}
        <div class="stat"><span>PhDs placed on other faculties</span><b>${fmt(T.out)}</b></div>
        <div class="stat"><span>Faculty hired from elsewhere</span><b>${fmt(T.in)}</b></div>
        <div class="stat"><span>Own PhDs on its faculty</span><b>${fmt(T.self)}</b></div>
      </div>
      <p class="note">Placement counts: ${esc(FLOW_NAME[FLOW_SRC])}.</p>
      ${/capella|walden|alliant|la verne|fielding|argosy|northcentral|nova southeastern|grand canyon|phoenix|integral|saybrook|professional psychology/i.test(i.name) ? `<p class="note">Practitioner-doctorate institution: most of these PhDs are likely Ed.D.-style or professional doctorates.</p>` : ""}
      <h3>Top advisors here</h3>${topAdv.length ? `<ul class="plist">${topAdv.map(([m, n]) => `<li><a href="${lineageHash(m, state.params)}"><span class="nm">${esc(P.get(m).name)}</span></a><span class="ct">${fmt(n)} PhDs here</span></li>`).join("")}</ul>` : `<p class="muted">None on record.</p>`}
      <h3>Where its PhDs went</h3>${instCountList(flowsOut.get(loc) || [], "people")}
      <h3>Where its faculty trained</h3>${instCountList(flowsIn.get(loc) || [], "people")}
      <h3>Schools of thought among its PhDs</h3>${schools.length ? `<ul class="plist">${schools.map(([s, n]) => `<li><a href="#/schools/curated/${s}">${esc(CTX.schools[s].name)}</a><span class="ct">${fmt(n)} PhDs</span></li>`).join("")}</ul>` : `<p class="muted">None of the curated schools.</p>`}
      <div class="actions">
        <a class="btn" href="#/i/${loc}?v=network">Network</a><a class="btn" href="#/i/${loc}?v=map">Map</a>
        ${topAdv[0] ? `<button type="button" class="btn primary" id="colorInst">Color a lineage by this institution</button>` : ""}
      </div>`;
    $("#colorInst")?.addEventListener("click", () => pinAndColor("phd", loc, topAdv[0][0]));
    els.panel.scrollTop = 0;
  }

  /* ---------------------------------------------------------------- boot */
  async function boot() {
    showCanvas(true);
    const n = notice(`<h2>Loading the sociology tree</h2><p>Reading 27,254 people and their advisor links.</p>`, "loading");
    let data;
    try {
      const res = await fetch("data/lineage.json");
      if (!res.ok) throw new Error(res.status + " " + res.statusText);
      data = await res.json();
    } catch (err) {
      n.remove();
      notice(`<h2>Couldn't load data/lineage.json</h2><p>Open the explorer through a local server, not as a file. From the project folder run <b>python3 -m http.server -d explorer 8000</b>, then visit localhost:8000. If the file is missing, run <b>scripts/export_explorer.py</b>.</p><p class="note">${esc(err.message)}</p>`);
      return;
    }
    try { load(data); } catch (err) {
      n.remove();
      notice(`<h2>The data file loaded but couldn't be read</h2><p>Re-export it with <b>scripts/export_explorer.py</b>. If this keeps happening, the export format and the explorer are out of step.</p><p class="note">${esc(err.message)}</p>`);
      console.error(err);
      return;
    }
    try {
      const res = await fetch("data/context.json");
      if (res.ok) loadContext(await res.json());
    } catch (err) { console.warn("context.json not loaded; schools and institutions are unavailable", err); }
    try {
      const res = await fetch("data/careers.json");
      if (res.ok) CAREERS = await res.json();
    } catch (err) { console.warn("careers.json not loaded", err); }
    try {
      const res = await fetch("data/coauthors.json");
      if (res.ok) loadCoauthors(await res.json());
    } catch (err) { console.warn("coauthors.json not loaded; co-author views are unavailable", err); }
    await document.fonts.ready;
    initCy();
    $("#search").placeholder = `Search ${fmt(META.people)} people`;
    attachSearch($("#search"), $("#search-results"), (p, input) => { input.value = ""; go(lineageHash(p.id, state.params)); input.blur(); });
    els.credit.innerHTML = `<span>Data: Academic Family Tree, snapshot 2022-03-12 (CC-BY-4.0). <span title="${esc(META.citation)}">Cite Liénard et al., Nature Communications 9:4840 (2018).</span></span><span class="counts">${fmt(META.people)} people · ${fmt(META.edges)} advisor links · ${fmt(META.openalex_matched)} matched to OpenAlex</span>`;
    window.addEventListener("hashchange", route);
    window.addEventListener("resize", () => cy && cy.resize());
    document.addEventListener("keydown", (e) => { if (e.key === "/" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); $("#search").focus(); } });
    route();
  }
  boot();
})();
