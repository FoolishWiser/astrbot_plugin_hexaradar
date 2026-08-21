const bridge = window.AstrBotPluginPage;

const $ = (id) => document.getElementById(id);

let pwdValue = "";

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function authParams(params = {}) {
  return pwdValue ? { ...params, pwd: pwdValue } : params;
}

function authBody(body = {}) {
  return pwdValue ? { ...body, pwd: pwdValue } : body;
}

function toast(msg, isError = false) {
  const el = $("save-hint");
  el.textContent = msg;
  el.hidden = false;
  el.classList.toggle("error", isError);
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 2600);
}

function showPasswordModal(withError = false) {
  $("password-modal").hidden = false;
  $("password-error").hidden = !withError;
  if (!withError) $("password-input").focus();
}

let settings = null;

async function load() {
  try {
    const data = await bridge.apiGet("settings", authParams());
    settings = data;
    $("cfg-social").checked = !!data.show_social_score;
    $("cfg-scar").checked = !!data.show_scarcity_score;
    $("cfg-auto").checked = !!data.auto_review;
    $("cfg-auto-trigger").value = ["both", "user", "reply"].includes(data.auto_review_trigger)
      ? data.auto_review_trigger
      : "both";
    $("cfg-auto-evidence").checked = data.auto_review_require_evidence !== false;
    $("cfg-auto-delta").value = data.auto_review_max_delta ?? 0;
    $("cfg-auto-cooldown").value = data.auto_review_cooldown ?? 30;
    $("cfg-pwd-on").checked = !!data.password_enabled;
    $("cfg-pwd").value = data.password || "";
    renderAliases(data.aliases || {});
  } catch (e) {
    if (String(e.message || "").includes("密码") || e.message === "Unauthorized") {
      showPasswordModal(!!pwdValue);
    } else {
      $("err-banner").hidden = false;
      $("err-banner").textContent = "页面错误：" + e.message;
    }
  }
}

function renderAliases(aliases) {
  const entries = Object.entries(aliases);
  $("alias-list").innerHTML = entries.length
    ? entries.map(([name, alias]) => `
        <div class="alias-row">
          <span class="alias-name">${esc(name)}</span>
          <span class="alias-arrow">→</span>
          <span class="alias-alias">${esc(alias)}</span>
          <button class="btn ghost" data-del="${esc(name)}">删除</button>
        </div>`).join("")
    : `<p class="hint">暂无别名</p>`;
  $("alias-list").querySelectorAll("button[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.del;
      try {
        const data = await bridge.apiPost("settings", authBody({
          ...currentForm(),
          aliases: { [name]: "" },
        }));
        settings.aliases = data.aliases || {};
        renderAliases(settings.aliases);
        toast("别名已删除");
      } catch (e) {
        toast("操作失败：" + e.message, true);
      }
    });
  });
}

function currentForm() {
  return {
    password_enabled: $("cfg-pwd-on").checked,
    password: $("cfg-pwd").value,
    show_social_score: $("cfg-social").checked,
    show_scarcity_score: $("cfg-scar").checked,
    auto_review: $("cfg-auto").checked,
    auto_review_trigger: $("cfg-auto-trigger").value,
    auto_review_require_evidence: $("cfg-auto-evidence").checked,
    auto_review_max_delta: Number($("cfg-auto-delta").value) || 0,
    auto_review_cooldown: Number($("cfg-auto-cooldown").value) || 0,
  };
}

async function saveAll() {
  const body = currentForm();
  const aliasName = $("alias-name").value.trim();
  const aliasVal = $("alias-alias").value.trim();
  if (aliasName) {
    body.aliases = { [aliasName]: aliasVal };
  }
  try {
    const data = await bridge.apiPost("settings", authBody(body));
    settings.aliases = data.aliases || {};
    renderAliases(settings.aliases);
    $("alias-name").value = "";
    $("alias-alias").value = "";
    toast("已保存");
  } catch (e) {
    toast("保存失败：" + e.message, true);
  }
}

async function unlock() {
  const value = $("password-input").value;
  if (!value) return;
  pwdValue = value;
  try {
    await bridge.apiGet("settings", authParams());
    $("password-modal").hidden = true;
    await load();
  } catch (e) {
    pwdValue = "";
    showPasswordModal(true);
  }
}

function bindEvents() {
  $("btn-save").addEventListener("click", saveAll);
  $("password-ok").addEventListener("click", unlock);
  $("password-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") unlock();
  });
}

async function init() {
  try {
    await bridge.ready();
    bindEvents();
    await load();
  } catch (e) {
    $("err-banner").hidden = false;
    $("err-banner").textContent = "页面错误：" + e.message;
  }
}

init();
