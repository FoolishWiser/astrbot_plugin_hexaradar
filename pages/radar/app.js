const bridge = window.AstrBotPluginPage;

const DIMS = [
  { key: "learning", label: "学习能力" },
  { key: "psychology", label: "心理承受力" },
  { key: "social", label: "社交能力" },
  { key: "judgment", label: "判断决策" },
  { key: "self_awareness", label: "自我认知" },
  { key: "direction", label: "长期方向感" },
];

const SCORE_KEYS = new Set(DIMS.map((d) => d.key));

const state = {
  persons: [],
  query: "",
  view: "cards",
  sortKey: "composite",
  sortDir: "desc",
  pyFilter: null,
  editing: null,
  viewing: null,
};

const collator = new Intl.Collator("zh-Hans-CN", { sensitivity: "base" });

const $ = (id) => document.getElementById(id);

function composite(scores) {
  const w = { learning: 1, psychology: 2, social: 1.5, judgment: 2, self_awareness: 1.5, direction: 1 };
  let total = 0;
  for (const dim of DIMS) total += w[dim.key] * Number(scores[dim.key] || 0);
  return Math.round((total / 9) * 10) / 10;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function hueFor(name) {
  let h = 0;
  for (const ch of String(name)) h = (h * 31 + ch.codePointAt(0)) % 360;
  return h;
}

function avatarStyle(name) {
  return `background:linear-gradient(135deg,hsl(${hueFor(name)},72%,55%),hsl(${(hueFor(name) + 40) % 360},72%,45%));color:#fff;`;
}

let pwdValue = "";

function pwd() {
  return pwdValue;
}

function authParams(params = {}) {
  return pwdValue ? { ...params, pwd: pwdValue } : params;
}

function authBody(body = {}) {
  return pwdValue ? { ...body, pwd: pwdValue } : body;
}

function badgeClass(v) {
  if (v >= 80) return "high";
  if (v >= 60) return "mid";
  return "low";
}

function toast(msg, isError = false) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " error" : "");
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 2600);
}

function showError(msg) {
  const el = $("err-banner");
  el.textContent = "页面错误：" + msg;
  el.hidden = false;
}

function clearError() {
  $("err-banner").hidden = true;
}

function radarSVG(scores, size) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 36;
  const pt = (i, radius) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / DIMS.length;
    return [cx + radius * Math.cos(a), cy + radius * Math.sin(a)];
  };
  const ringPts = (lv) => DIMS.map((_, i) => pt(i, r * lv).join(",")).join(" ");
  let s = "";
  for (const lv of [1, 0.8, 0.6, 0.4, 0.2]) {
    s += `<polygon points="${ringPts(lv)}" fill="none" stroke="var(--border)" stroke-width="1"/>`;
  }
  for (let i = 0; i < DIMS.length; i++) {
    const [x, y] = pt(i, r);
    s += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="var(--border)" stroke-width="1"/>`;
  }
  const pts = DIMS.map((dim, i) => {
    const v = Math.max((Number(scores?.[dim.key]) || 0) / 100, 0.005);
    return pt(i, r * v).join(",");
  }).join(" ");
  s += `<polygon points="${pts}" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>`;
  DIMS.forEach((dim, i) => {
    const v = Math.max((Number(scores?.[dim.key]) || 0) / 100, 0.005);
    const [x, y] = pt(i, r * v);
    s += `<circle cx="${x}" cy="${y}" r="3.5" fill="var(--accent)"/>`;
  });
  for (let i = 0; i < DIMS.length; i++) {
    const [x, y] = pt(i, r + 22);
    s += `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle" font-size="11" fill="var(--muted)">${DIMS[i].label}</text>`;
  }
  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">${s}</svg>`;
}

function filteredPersons() {
  if (!state.pyFilter) return state.persons;
  return state.persons.filter((p) => (p.py_initial || "#") === state.pyFilter);
}

function sortPersons() {
  const { sortKey, sortDir } = state;
  const arr = [...filteredPersons()];
  arr.sort((a, b) => {
    let cmp;
    if (sortKey === "name") {
      cmp = collator.compare(a.name, b.name);
    } else if (SCORE_KEYS.has(sortKey)) {
      cmp = (Number(a.scores?.[sortKey]) || 0) - (Number(b.scores?.[sortKey]) || 0);
    } else {
      cmp = (Number(a[sortKey]) || 0) - (Number(b[sortKey]) || 0);
    }
    return sortDir === "asc" ? cmp : -cmp;
  });
  return arr;
}

function defaultDir(key) {
  return key === "name" ? "asc" : "desc";
}

function dimLabel(key) {
  const dim = DIMS.find((d) => d.key === key);
  return dim ? dim.label : null;
}

function renderMain() {
  const persons = sortPersons();
  const empty = $("empty");
  empty.hidden = persons.length > 0;
  $("empty-text").textContent = state.pyFilter
    ? `没有以「${esc(state.pyFilter)}」开头的人员`
    : state.query
      ? `未找到与「${esc(state.query)}」匹配的人员`
      : "暂无人员数据，点击「+ 新建人员」开始";

  const cards = $("cards");
  const tableWrap = $("table-wrap");
  $("detail").hidden = true;
  const isCards = state.view === "cards";
  cards.hidden = !isCards;
  tableWrap.hidden = isCards;
  $("py-stack").hidden = isCards || (persons.length === 0 && !state.pyFilter);
  $("py-reset").hidden = !state.pyFilter;

  if (isCards) {
    cards.innerHTML = persons.map(cardHTML).join("");
  } else {
    $("table-body").innerHTML = persons.map(tableRowHTML).join("");
    document.querySelectorAll("th[data-sort]").forEach((th) => {
      th.classList.toggle("sorted", th.dataset.sort === state.sortKey);
    });
    renderPyIndex();
  }

  $("sort-dir").textContent = state.sortDir === "desc" ? "↓" : "↑";
}

function renderPyIndex() {
  const present = new Set(state.persons.map((p) => p.py_initial || "#"));
  const letters = [];
  if (present.has("#")) letters.push("#");
  for (let c = 65; c <= 90; c++) letters.push(String.fromCharCode(c));
  $("py-letters").innerHTML = letters.map((l) => {
    const on = present.has(l);
    const active = state.pyFilter === l;
    return `<button class="py-item ${on ? "on" : "off"} ${active ? "active" : ""}" data-letter="${l}" ${on ? "" : "disabled"}>${l}</button>`;
  }).join("");
  $("py-letters").querySelectorAll(".py-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const letter = btn.dataset.letter;
      state.pyFilter = state.pyFilter === letter ? null : letter;
      render();
    });
  });
  $("py-reset").hidden = !state.pyFilter;
}

function render() {
  try {
    if (currentRoute()) {
      renderDetail();
    } else {
      renderMain();
    }
  } catch (e) {
    console.error("hexaradar: 渲染失败", e);
    showError(e.message);
  }
}

function cardHTML(p) {
  const ordered = [...DIMS];
  if (SCORE_KEYS.has(state.sortKey)) {
    const i = ordered.findIndex((d) => d.key === state.sortKey);
    if (i > 0) {
      const [first] = ordered.splice(i, 1);
      ordered.unshift(first);
    }
  }
  const bars = ordered.map((dim) => {
    const v = Number(p.scores[dim.key] || 0);
    const isSorted = dim.key === state.sortKey;
    const arrow = isSorted ? (state.sortDir === "desc" ? " ↓" : " ↑") : "";
    const valueHtml = isSorted
      ? `<span class="chip ${badgeClass(v)} bar-chip">${v}</span>`
      : `<span class="bar-value">${v}</span>`;
    return `
      <div class="bar-row ${isSorted ? "sorted-first" : ""}">
        <span class="bar-label">${dim.label}${arrow}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${v}%"></span></span>
        ${valueHtml}
      </div>`;
  }).join("");
  return `
    <div class="card" data-name="${esc(p.name)}">
      <div class="card-top">
        <button class="avatar" style="${avatarStyle(p.name)}" data-act="detail" data-name="${esc(p.name)}" title="查看详情">${esc([...p.name][0] || "?")}</button>
        <div class="card-info">
          <div class="card-name" data-act="detail" data-name="${esc(p.name)}">${esc(p.name)}</div>
          ${p.desc ? `<div class="card-desc">${esc(p.desc)}</div>` : ""}
        </div>
        <span class="badge ${badgeClass(p.composite)}">${p.composite}</span>
      </div>
      <div class="card-mini"><div class="mini-bars">${bars}</div></div>
    </div>`;
}

function tableRowHTML(p) {
  const dimBadge = SCORE_KEYS.has(state.sortKey)
    ? `<span class="badge sub ${badgeClass(Number(p.scores[state.sortKey] || 0))}">${dimLabel(state.sortKey)} ${state.sortDir === "desc" ? "↓" : "↑"} ${Number(p.scores[state.sortKey] || 0)}</span>`
    : "";
  const compBadge = `<span class="badge ${badgeClass(p.composite)}">${p.composite}</span>`;
  return `
    <tr data-row="${esc(p.name)}">
      <td>
        <div class="name-cell">
          <button class="name-link" data-act="detail" data-name="${esc(p.name)}">${esc(p.name)}</button>
          ${compBadge}
          ${dimBadge}
          <div class="cell-actions">
            <button class="icon-btn" data-act="edit" data-name="${esc(p.name)}" title="编辑">✎</button>
            <button class="icon-btn danger" data-act="del" data-name="${esc(p.name)}" title="删除">🗑</button>
          </div>
        </div>
        ${p.desc ? `<div class="row-desc">${esc(p.desc)}</div>` : ""}
      </td>
    </tr>`;
}

async function loadList() {
  clearError();
  try {
    const data = await bridge.apiGet("list", authParams({ q: state.query }));
    console.log("hexaradar: list 返回", data);
    if (!data || !Array.isArray(data.persons)) {
      throw new Error("接口返回格式异常: " + JSON.stringify(data));
    }
    state.persons = data.persons || [];
    $("btn-lock").hidden = !pwd();
    render();
  } catch (e) {
    console.error("hexaradar: list 请求失败", e);
    if (String(e.message || "").includes("密码") || e.message === "Unauthorized") {
      showPasswordModal(true, !!pwd());
    } else {
      showError(e.message + "\n（若持续出现，请查看 AstrBot 日志中 astrbot_plugin_hexaradar 的 list 记录）");
    }
  }
}

function showPasswordModal(show, withError = false) {
  $("password-modal").hidden = !show;
  $("password-error").hidden = !withError;
  if (show) $("password-input").value = "";
  if (show && !withError) $("password-input").focus();
}

let confirmResolve = null;

function confirmDialog(message) {
  return new Promise((resolve) => {
    $("confirm-message").textContent = message;
    $("confirm-modal").hidden = false;
    confirmResolve = resolve;
  });
}

function settleConfirm(value) {
  $("confirm-modal").hidden = true;
  if (confirmResolve) {
    confirmResolve(value);
    confirmResolve = null;
  }
}

async function unlock() {
  const value = $("password-input").value;
  if (!value) return;
  pwdValue = value;
  try {
    await bridge.apiGet("list", authParams({ q: state.query }));
    showPasswordModal(false);
    await loadList();
  } catch (e) {
    pwdValue = "";
    showPasswordModal(true, true);
  }
}

function currentRoute() {
  const m = location.hash.match(/^#\/person\/(.+)$/);
  return m ? decodeURIComponent(m[1]) : null;
}

function openDetail(name) {
  location.hash = "#/person/" + encodeURIComponent(name);
}

function goBack() {
  location.hash = "";
}

function renderDetail() {
  const name = currentRoute();
  const p = state.persons.find((x) => x.name === name);
  $("cards").hidden = true;
  $("table-wrap").hidden = true;
  $("empty").hidden = true;
  $("py-stack").hidden = true;
  $("detail").hidden = false;
  if (!p) {
    $("detail-avatar").textContent = "?";
    $("detail-avatar").style.cssText = "";
    $("detail-name").textContent = name;
    $("detail-radar").innerHTML = "";
    $("detail-composite").textContent = "0";
    $("detail-scores").innerHTML = `<p class="detail-missing">未找到人员「${esc(name)}」，可能已被删除或搜索过滤。</p>`;
    $("detail-desc-text").textContent = "—";
    $("detail-edit").hidden = true;
    $("detail-delete").hidden = true;
    return;
  }
  $("detail-edit").hidden = false;
  $("detail-delete").hidden = false;
  $("detail-avatar").textContent = [...p.name][0] || "?";
  $("detail-avatar").style.cssText = avatarStyle(p.name);
  $("detail-name").textContent = p.name;
  $("detail-radar").innerHTML = radarSVG(p.scores, 300);
  $("detail-composite").textContent = p.composite;
  const reasons = p.reasons || {};
  $("detail-scores").innerHTML = DIMS.map((dim) => {
    const v = Number(p.scores[dim.key] || 0);
    const reason = reasons[dim.key];
    return `
      <div class="detail-score-row">
        <div class="detail-score-head">
          <span class="detail-dim">${dim.label}</span>
          <span class="chip ${badgeClass(v)}">${v}</span>
        </div>
        <span class="bar-track"><span class="bar-fill" style="width:${v}%"></span></span>
        <p class="detail-reason">${reason ? esc(reason) : "—"}</p>
      </div>`;
  }).join("");
  $("detail-desc-text").textContent = p.desc || "—";
}

function openView(person) {
  state.viewing = person;
  $("edit-title").textContent = `查看：${person.name}`;
  $("view-radar").innerHTML = radarSVG(person.scores, 260);
  $("view-composite").textContent = person.composite;
  $("view-name").textContent = person.name;
  const reasons = person.reasons || {};
  $("view-scores").innerHTML = DIMS.map((dim) => {
    const v = Number(person.scores[dim.key] || 0);
    const reason = reasons[dim.key];
    return `
      <div class="detail-score-row">
        <div class="detail-score-head">
          <span class="detail-dim">${dim.label}</span>
          <span class="chip ${badgeClass(v)}">${v}</span>
        </div>
        <span class="bar-track"><span class="bar-fill" style="width:${v}%"></span></span>
        <p class="detail-reason">${reason ? esc(reason) : "—"}</p>
      </div>`;
  }).join("");
  $("view-desc-text").textContent = person.desc || "—";
  $("view-body").hidden = false;
  $("edit-body").hidden = true;
  $("edit-modal").hidden = false;
  $("edit-modal").querySelector(".modal").scrollTop = 0;
}

function openEdit(person) {
  $("view-body").hidden = true;
  $("edit-body").hidden = false;
  if (person) {
    state.editing = {
      name: person.name,
      desc: person.desc || "",
      scores: { ...person.scores },
      reasons: { ...(person.reasons || {}) },
      isNew: false,
    };
  } else {
    const scores = {};
    for (const dim of DIMS) scores[dim.key] = 60;
    state.editing = { name: "", desc: "", scores, reasons: {}, isNew: true };
  }
  $("edit-title").textContent = state.editing.isNew ? "新建人员" : `编辑：${state.editing.name}`;
  $("edit-name").value = state.editing.name;
  $("edit-name").readOnly = !state.editing.isNew;
  $("edit-desc").value = state.editing.desc;
  $("edit-delete").hidden = state.editing.isNew;
  buildSliders();
  updateEditPreview();
  $("edit-modal").hidden = false;
  $("edit-modal").querySelector(".modal").scrollTop = 0;
  $("edit-sliders").scrollTop = 0;
}

function closeEdit() {
  $("edit-modal").hidden = true;
  state.editing = null;
  state.viewing = null;
}

function buildSliders() {
  $("edit-sliders").innerHTML = DIMS.map((dim) => {
    const v = Number(state.editing.scores[dim.key] || 0);
    const reason = state.editing.reasons[dim.key] || "";
    return `
      <div class="slider-block" data-key="${dim.key}">
        <div class="slider-row">
          <label>${dim.label}</label>
          <input type="range" min="0" max="100" step="1" value="${v}" data-role="range"/>
          <input type="number" min="0" max="100" step="1" value="${v}" data-role="num"/>
        </div>
        <input class="reason-input" type="text" value="${esc(reason)}" data-role="reason" placeholder="评分理由（可选）"/>
      </div>`;
  }).join("");
}

function updateEditPreview() {
  const scores = state.editing.scores;
  $("edit-radar").innerHTML = radarSVG(scores, 260);
  $("edit-composite").textContent = composite(scores);
}

async function saveEdit() {
  const name = $("edit-name").value.trim();
  if (!name) {
    toast("请输入姓名", true);
    return;
  }
  try {
    await bridge.apiPost("person", authBody({
      name,
      scores: state.editing.scores,
      desc: $("edit-desc").value,
      reasons: state.editing.reasons,
    }));
    toast("已保存");
    closeEdit();
    await loadList();
  } catch (e) {
    toast("保存失败：" + e.message, true);
  }
}

async function deleteEditing() {
  const name = state.editing.name;
  const ok = await confirmDialog(`确定删除「${name}」的六边形数据吗？此操作不可恢复。`);
  if (!ok) return;
  try {
    await bridge.apiPost("person/delete", authBody({ name }));
    toast("已删除");
    closeEdit();
    goBack();
    await loadList();
  } catch (e) {
    toast("删除失败：" + e.message, true);
  }
}

async function deletePerson(name) {
  const ok = await confirmDialog(`确定删除「${name}」的六边形数据吗？此操作不可恢复。`);
  if (!ok) return;
  try {
    await bridge.apiPost("person/delete", authBody({ name }));
    toast("已删除");
    await loadList();
  } catch (e) {
    toast("删除失败：" + e.message, true);
  }
}

function bindEvents() {
  let timer = null;
  $("search").addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.query = e.target.value.trim();
      loadList();
    }, 250);
  });

  $("sort-select").addEventListener("change", (e) => {
    state.sortKey = e.target.value;
    state.sortDir = defaultDir(state.sortKey);
    render();
  });

  $("sort-dir").addEventListener("click", () => {
    state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
    render();
  });

  $("view-cards").addEventListener("click", () => switchView("cards"));
  $("view-table").addEventListener("click", () => switchView("table"));

  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
      } else {
        state.sortKey = key;
        state.sortDir = key === "name" ? "asc" : "desc";
      }
      $("sort-select").value = state.sortKey;
      render();
    });
  });

  $("cards").addEventListener("click", (e) => {
    const t = e.target.closest("[data-act]");
    if (t && t.dataset.act === "detail") {
      openDetail(t.dataset.name);
      return;
    }
    const card = e.target.closest(".card");
    if (card) {
      const p = state.persons.find((x) => x.name === card.dataset.name);
      if (p) openView(p);
    }
  });

  $("table-body").addEventListener("click", (e) => {
    const t = e.target.closest("[data-act]");
    if (!t) return;
    const name = t.dataset.name;
    const p = state.persons.find((x) => x.name === name);
    if (!p) return;
    if (t.dataset.act === "detail") openDetail(name);
    else if (t.dataset.act === "edit") openEdit(p);
    else if (t.dataset.act === "del") deletePerson(name);
  });

  $("btn-add").addEventListener("click", () => openEdit(null));
  $("btn-lock").addEventListener("click", () => {
    pwdValue = "";
    $("btn-lock").hidden = true;
    state.persons = [];
    render();
    loadList();
  });
  $("edit-save").addEventListener("click", saveEdit);
  $("edit-cancel").addEventListener("click", closeEdit);
  $("edit-delete").addEventListener("click", deleteEditing);
  $("view-edit").addEventListener("click", () => {
    if (state.viewing) openEdit(state.viewing);
  });
  $("view-close").addEventListener("click", closeEdit);
  $("password-ok").addEventListener("click", unlock);
  $("password-cancel").addEventListener("click", () => showPasswordModal(false));
  $("password-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") unlock();
  });

  $("confirm-ok").addEventListener("click", () => settleConfirm(true));
  $("confirm-cancel").addEventListener("click", () => settleConfirm(false));

  $("edit-sliders").addEventListener("input", (e) => {
    const block = e.target.closest(".slider-block");
    if (!block) return;
    const key = block.dataset.key;
    if (e.target.dataset.role === "reason") {
      state.editing.reasons[key] = e.target.value;
      return;
    }
    let v = Number(e.target.value);
    if (isNaN(v)) v = 0;
    v = Math.max(0, Math.min(100, v));
    state.editing.scores[key] = v;
    block.querySelector('[data-role="num"]').value = v;
    block.querySelector('[data-role="range"]').value = v;
    updateEditPreview();
  });

  $("py-reset").addEventListener("click", () => {
    state.pyFilter = null;
    render();
  });

  $("detail-back").addEventListener("click", goBack);  $("detail-edit").addEventListener("click", () => {
    const p = state.persons.find((x) => x.name === currentRoute());
    if (p) openEdit(p);
  });
  $("detail-delete").addEventListener("click", () => {
    const name = currentRoute();
    deletePerson(name);
  });

  window.addEventListener("hashchange", () => {
    if (currentRoute()) {
      loadList();
    } else {
      render();
    }
  });

  document.querySelectorAll(".modal-mask").forEach((mask) => {
    mask.addEventListener("click", (e) => {
      if (e.target === mask) {
        if (mask.id === "edit-modal") closeEdit();
        else if (mask.id === "confirm-modal") settleConfirm(false);
        else showPasswordModal(false);
      }
    });
  });
}

function switchView(view) {
  state.view = view;
  $("view-cards").classList.toggle("active", view === "cards");
  $("view-table").classList.toggle("active", view === "table");
  render();
}

async function init() {
  try {
    await bridge.ready();
    bindEvents();
    await loadList();
  } catch (e) {
    console.error("hexaradar: 初始化失败", e);
    showError(e.message + "（bridge 未就绪或插件未正确加载）");
  }
}

init();
