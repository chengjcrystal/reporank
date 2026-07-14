const $ = (id) => document.getElementById(id);
const state = { page: 1, total: 0, perPage: 20, selectedTopics: new Set() };

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function loadFilters() {
  const data = await fetch("/api/filters").then((r) => r.json());
  const langSel = $("language");
  data.languages.forEach((l) => {
    const o = document.createElement("option");
    o.value = l; o.textContent = l; langSel.appendChild(o);
  });
  const chips = $("topics");
  data.topics.forEach((t) => {
    const c = document.createElement("span");
    c.className = "topic-chip"; c.textContent = t;
    c.onclick = () => {
      c.classList.toggle("active");
      state.selectedTopics.has(t) ? state.selectedTopics.delete(t) : state.selectedTopics.add(t);
    };
    chips.appendChild(c);
  });
}

function buildParams() {
  const p = new URLSearchParams();
  p.set("q", $("q").value.trim());
  if ($("language").value) p.set("language", $("language").value);
  if ($("minStars").value) p.set("min_stars", $("minStars").value);
  if ($("updatedAfter").value) p.set("updated_after", $("updatedAfter").value);
  if (state.selectedTopics.size) p.set("topics", [...state.selectedTopics].join(","));
  p.set("ranker", $("ranker").value);
  p.set("page", state.page);
  p.set("per_page", state.perPage);
  return p;
}

function relativeTime(iso) {
  if (!iso) return "unknown";
  const days = Math.floor((Date.now() - new Date(iso)) / 86400000);
  if (days < 1) return "today";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

function card(r, query, ranker) {
  const el = document.createElement("div");
  el.className = "card";
  el.innerHTML = `
    <div class="card-head">
      <a class="name" href="${r.html_url}" target="_blank" rel="noopener">${r.full_name}</a>
      <span class="score" title="blended score (bm25 component)">score ${r.score} · bm25 ${r.bm25}</span>
    </div>
    <div class="desc">${r.description ? escapeHtml(r.description) : "<em>No description</em>"}</div>
    <div class="card-stats">
      ${r.language ? `<span class="lang-pill"><span class="lang-dot"></span>${r.language}</span>` : ""}
      <span>★ ${r.stars.toLocaleString()}</span>
      <span>⑂ ${r.forks.toLocaleString()}</span>
      <span>updated ${relativeTime(r.pushed_at)}</span>
    </div>
    <div class="tags">${r.topics.slice(0, 8).map((t) => `<span class="tag">${t}</span>`).join("")}</div>
  `;
  el.querySelector("a.name").addEventListener("click", () => {
    fetch("/api/events/click", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, repo_id: r.id, ranker }),
    });
  });
  return el;
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function syncUrl() {
  const q = $("q").value.trim();
  if (!q) { history.replaceState(null, "", location.pathname); return; }
  const u = new URLSearchParams({ q });
  if ($("ranker").value && $("ranker").value !== "bm25f_v1") {
    u.set("ranker", $("ranker").value);  // only when off the default
  }
  history.replaceState(null, "", `?${u}`);
}

async function runSearch() {
  syncUrl();
  const params = buildParams();
  const data = await fetch(`/api/search?${params}`).then((r) => r.json());
  state.total = data.total;

  $("meta").innerHTML = `<span>${data.total.toLocaleString()} results</span>
    <span class="latency-badge">${data.latency_ms} ms</span>
    <span>ranker: ${data.ranker}</span>`;

  const box = $("results");
  box.innerHTML = "";
  if (!data.results.length) {
    box.innerHTML = `<div class="empty">No repositories matched. Try broader terms or fewer filters.</div>`;
  } else {
    data.results.forEach((r) => box.appendChild(card(r, data.query, data.ranker)));
  }
  renderPager();
}

function renderPager() {
  const pages = Math.ceil(state.total / state.perPage);
  const pager = $("pager");
  pager.innerHTML = "";
  if (pages <= 1) return;
  const prev = document.createElement("button");
  prev.textContent = "← Prev"; prev.disabled = state.page <= 1;
  prev.onclick = () => { state.page--; runSearch(); window.scrollTo(0, 0); };
  const info = document.createElement("button");
  info.textContent = `Page ${state.page} / ${pages}`; info.disabled = true;
  const next = document.createElement("button");
  next.textContent = "Next →"; next.disabled = state.page >= pages;
  next.onclick = () => { state.page++; runSearch(); window.scrollTo(0, 0); };
  pager.append(prev, info, next);
}

async function showSuggestions() {
  const q = $("q").value.trim();
  const list = $("suggestions");
  if (q.length < 2) { list.classList.add("hidden"); return; }
  const data = await fetch(`/api/suggest?q=${encodeURIComponent(q)}`).then((r) => r.json());
  if (!data.suggestions.length) { list.classList.add("hidden"); return; }
  list.innerHTML = "";
  data.suggestions.forEach((s) => {
    const li = document.createElement("li");
    li.textContent = s;
    li.onclick = () => { $("q").value = s; list.classList.add("hidden"); state.page = 1; runSearch(); };
    list.appendChild(li);
  });
  list.classList.remove("hidden");
}

async function showStats() {
  const panel = $("statsPanel");
  if (!panel.classList.contains("hidden")) { panel.classList.add("hidden"); return; }
  const s = await fetch("/api/stats").then((r) => r.json());
  panel.innerHTML = `
    <h3>Analytics</h3>
    <div class="stat-grid">
      <div class="stat-box"><div class="num">${s.repositories_indexed.toLocaleString()}</div><div class="lbl">repos indexed</div></div>
      <div class="stat-box"><div class="num">${s.vocabulary_size.toLocaleString()}</div><div class="lbl">vocabulary terms</div></div>
      <div class="stat-box"><div class="num">${s.total_searches}</div><div class="lbl">searches</div></div>
      <div class="stat-box"><div class="num">${(s.ctr * 100).toFixed(1)}%</div><div class="lbl">click-through rate</div></div>
      <div class="stat-box"><div class="num">${s.latency_p50_ms}</div><div class="lbl">p50 latency (ms)</div></div>
      <div class="stat-box"><div class="num">${s.latency_p95_ms}</div><div class="lbl">p95 latency (ms)</div></div>
      <div class="stat-box"><div class="num">${s.zero_result_searches}</div><div class="lbl">zero-result searches</div></div>
    </div>
    <h4>Top queries</h4>
    ${s.top_queries.map((q) => `<div class="tq-row"><span>${escapeHtml(q.query)}</span><span>${q.count}</span></div>`).join("") || "<p class='lbl'>No queries yet.</p>"}
  `;
  panel.classList.remove("hidden");
}

$("q").addEventListener("input", debounce(showSuggestions, 180));
$("q").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { $("suggestions").classList.add("hidden"); state.page = 1; runSearch(); }
});
$("apply").onclick = () => { state.page = 1; runSearch(); };
$("ranker").onchange = () => { state.page = 1; runSearch(); };
$("statsToggle").onclick = showStats;
document.addEventListener("click", (e) => {
  if (!e.target.closest(".searchbar")) $("suggestions").classList.add("hidden");
});

function initFromUrl() {
  const params = new URLSearchParams(location.search);
  if (params.get("q")) $("q").value = params.get("q");
  if (params.get("ranker")) $("ranker").value = params.get("ranker");
}

loadFilters();
initFromUrl();
runSearch();
