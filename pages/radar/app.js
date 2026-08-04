const bridge = window.AstrBotPluginPage;

const DIMS = [
  { key: "learning", label: "学习能力" },
  { key: "psychology", label: "心理承受力" },
  { key: "social", label: "社交能力" },
  { key: "judgment", label: "判断决策" },
  { key: "self_awareness", label: "自我认知" },
  { key: "direction", label: "长期方向感" },
];

const state = {
  persons: [],
  query: "",
  view: "cards",
  sortKey: "composite",
  sortDir: "desc",
  editing: null,
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
  s += `<polygon points="${pts}" fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="2"/>`;
  for (let i = 0; i < DIMS.length; i++) {
    const [x, y] = pt(i, r + 22);
    s += `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle" font-size="11" fill="var(--muted)">${DIMS[i].label}</text>`;
  }
  return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">${s}</svg>`;
}

function sortPersons() {
  const { sortKey, sortDir } = state;
  const arr = [...state.persons];
  arr.sort((a, b) => {
    let cmp;
    if (sortKey === "name") {
      cmp = collator.compare(a.name, b.name);
    } else {
      cmp = (Number(a[sortKey]) || 0) - (Number(b[sortKey]) || 0);
    }
    return sortDir === "asc" ? cmp : -cmp;
  });
  return arr;
}

function render() {
  try {
    const persons = sortPersons();
    const empty = $("empty");
    empty.hidden = persons.length > 0;
    $("empty-text").textContent = state.query
      ? `未找到与「${esc(state.query)}」匹配的人员`
      : "暂无人员数据，点击「+ 新建人员」开始";

    const cards = $("cards");
    const tableWrap = $("table-wrap");
    const isCards = state.view === "cards";
    cards.hidden = !isCards;
    tableWrap.hidden = isCards;

    if (isCards) {
      cards.innerHTML = persons.map(cardHTML).join("");
    } else {
      $("table-body").innerHTML = persons.map(tableRowHTML).join("");
      document.querySelectorAll("th[data-sort]").forEach((th) => {
        th.classList.toggle("sorted", th.dataset.sort === state.sortKey);
      });
    }

    $("sort-dir").textContent = state.sortDir === "desc" ? "↓" : "↑";
  } catch (e) {
    console.error("hexaradar: 渲染失败", e);
    showError(e.message);
  }
}

function cardHTML(p) {
  const bars = DIMS.map((dim) => {
    const v = Number(p.scores[dim.key] || 0);
    return `
      <div class="bar-row">
        <span class="bar-label">${dim.label}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${v}%"></span></span>
        <span class="bar-value">${v}</span>
      </div>`;
  }).join("");
  return `
    <div class="card" data-name="${esc(p.name)}">
      <div class="card-top">
        <div class="avatar">${esc([...p.name][0] || "?")}</div>
        <div class="card-info">
          <div class="card-name">${esc(p.name)}</div>
          ${p.desc ? `<div class="card-desc">${esc(p.desc)}</div>` : ""}
        </div>
        <span class="badge ${badgeClass(p.composite)}">${p.composite}</span>
      </div>
      <div class="card-mini"><div class="mini-bars">${bars}</div></div>
    </div>`;
}

function tableRowHTML(p) {
  const cells = DIMS.map((dim) => `<td class="score-cell">${Number(p.scores[dim.key] || 0)}</td>`).join("");
  return `
    <tr>
      <td><strong>${esc(p.name)}</strong>${p.desc ? `<br/><small style="color:var(--muted)">${esc(p.desc)}</small>` : ""}</td>
      <td class="score-cell"><span class="badge ${badgeClass(p.composite)}">${p.composite}</span></td>
      ${cells}
      <td>
        <div class="cell-actions">
          <button class="btn ghost" data-act="edit" data-name="${esc(p.name)}">编辑</button>
          <button class="btn ghost" data-act="del" data-name="${esc(p.name)}">删除</button>
        </div>
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

function openEdit(person) {
  if (person) {
    state.editing = {
      name: person.name,
      desc: person.desc || "",
      scores: { ...person.scores },
      isNew: false,
    };
  } else {
    const scores = {};
    for (const dim of DIMS) scores[dim.key] = 60;
    state.editing = { name: "", desc: "", scores, isNew: true };
  }
  $("edit-title").textContent = state.editing.isNew ? "新建人员" : `编辑：${state.editing.name}`;
  $("edit-name").value = state.editing.name;
  $("edit-name").readOnly = !state.editing.isNew;
  $("edit-desc").value = state.editing.desc;
  $("edit-delete").hidden = state.editing.isNew;
  buildSliders();
  updateEditPreview();
  $("edit-modal").hidden = false;
}

function closeEdit() {
  $("edit-modal").hidden = true;
  state.editing = null;
}

function buildSliders() {
  $("edit-sliders").innerHTML = DIMS.map((dim) => {
    const v = Number(state.editing.scores[dim.key] || 0);
    return `
      <div class="slider-row" data-key="${dim.key}">
        <label>${dim.label}</label>
        <input type="range" min="0" max="100" step="1" value="${v}" data-role="range"/>
        <input type="number" min="0" max="100" step="1" value="${v}" data-role="num"/>
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
    await bridge.apiPost("person", authBody({ name, scores: state.editing.scores, desc: $("edit-desc").value }));
    toast("已保存");
    closeEdit();
    await loadList();
  } catch (e) {
    toast("保存失败：" + e.message, true);
  }
}

async function deleteEditing() {
  const name = state.editing.name;
  if (!confirm(`确定删除「${name}」的六边形数据吗？此操作不可恢复。`)) return;
  try {
    await bridge.apiPost("person/delete", authBody({ name }));
    toast("已删除");
    closeEdit();
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
    if (state.sortKey === "name") state.sortDir = "asc";
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
    const card = e.target.closest(".card");
    if (card) {
      const p = state.persons.find((x) => x.name === card.dataset.name);
      if (p) openEdit(p);
    }
  });

  $("table-body").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const p = state.persons.find((x) => x.name === btn.dataset.name);
    if (!p) return;
    if (btn.dataset.act === "edit") openEdit(p);
    else {
      if (confirm(`确定删除「${p.name}」的六边形数据吗？此操作不可恢复。`)) deletePerson(p.name);
    }
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
  $("password-ok").addEventListener("click", unlock);
  $("password-cancel").addEventListener("click", () => showPasswordModal(false));
  $("password-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") unlock();
  });

  $("edit-sliders").addEventListener("input", (e) => {
    const row = e.target.closest(".slider-row");
    if (!row) return;
    const key = row.dataset.key;
    let v = Number(e.target.value);
    if (isNaN(v)) v = 0;
    v = Math.max(0, Math.min(100, v));
    state.editing.scores[key] = v;
    row.querySelector('[data-role="num"]').value = v;
    row.querySelector('[data-role="range"]').value = v;
    updateEditPreview();
  });

  document.querySelectorAll(".modal-mask").forEach((mask) => {
    mask.addEventListener("click", (e) => {
      if (e.target === mask) {
        if (mask.id === "edit-modal") closeEdit();
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

async function deletePerson(name) {
  try {
    await bridge.apiPost("person/delete", authBody({ name }));
    toast("已删除");
    await loadList();
  } catch (e) {
    toast("删除失败：" + e.message, true);
  }
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
