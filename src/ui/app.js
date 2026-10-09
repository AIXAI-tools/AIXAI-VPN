"use strict";

// token 由啟動器放在網址 # 後面；讀完就從網址列移除
const TOKEN = new URLSearchParams(location.hash.slice(1)).get("token") || "";
history.replaceState(null, "", location.pathname);

const $ = (id) => document.getElementById(id);

let countries = [];   // 最近一次搜尋結果（VPN Gate）
let torList = null;   // 各國 Tor 出口節點數（null = 沒抓到）
let torAvailable = true;
let vpnbook = { available: false, configs: [], fetch: {} };  // VPNBook 設定檔狀態（來自 /api/status）
const VPNBOOK_COUNTRIES = { US: "美國", CA: "加拿大", GB: "英國", DE: "德國", FR: "法國" };  // 有 WireGuard 伺服器的目標國
// VPNBook 頁面「1 选择服务器」中各國要點的選項（頁面原文，與 src/server/vpnbook.py SERVER_LABELS 一致）
const VPNBOOK_SERVER_LABELS = { US: "US Server 1（us16.vpnbook.com）", CA: "Canada Server 1（ca149.vpnbook.com）",
  GB: "UK Server 1（uk205.vpnbook.com）", DE: "Germany Server 1（de20.vpnbook.com）", FR: "France Server 1（fr200.vpnbook.com）" };
let mode = "vpngate"; // 目前顯示的分頁
try {
  const saved = localStorage.getItem("aixai-mode");
  mode = ["vpngate", "tor", "vpnbook"].includes(saved) ? saved : "vpngate";
} catch (e) { /* 無法使用時用預設 */ }
let conn = { status: "idle" };  // 最近一次連線狀態
let lastStatus = null;
let pollTimer = null;

async function api(path, method = "GET", body = undefined) {
  const headers = { "X-AIXAI-Token": TOKEN };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function showError(msg) {
  const el = $("error");
  el.textContent = msg || "";
  el.hidden = !msg;
}

function countryName(code) {
  const all = [...countries, ...(torList || [])];
  return (all.find((c) => c.code === code) || {}).name || VPNBOOK_COUNTRIES[code] || code;
}

// VPNBook 半自動取得的進度訊息
function renderFetch() {
  const f = vpnbook.fetch || {};
  const msg = f.message || "";
  $("vpnbook-fetch").hidden = mode !== "vpnbook" || !msg;
  $("vpnbook-fetch-msg").textContent = msg;
  // 等待下載時，顯示對應國家的逐步說明（文字與 VPNBook 簡體中文頁面一致）
  const waiting = !!f.fetching;
  $("vpnbook-steps").hidden = !waiting;
  $("vpnbook-steps-foot").hidden = !waiting;
  $("step-server").textContent = VPNBOOK_SERVER_LABELS[f.country] || VPNBOOK_SERVER_LABELS.US;
}

async function fetchVpnbook(code) {
  showError("");
  try {
    renderStatus(await api("/api/vpnbook/fetch", "POST", { country: code }));
  } catch (e) {
    showError(e.message);
  }
  refreshStatus();
}

// 依分頁整理成同一種格式：{code, name, count, sub, action, warn}
function items() {
  if (mode === "vpnbook") {
    if (!vpnbook.available) return [];
    return Object.entries(VPNBOOK_COUNTRIES).map(([code, name]) => {
      const c = vpnbook.configs.find((x) => x.code === code);
      if (!c) return { code, name, count: 1, action: "fetch", sub: "需要取得設定檔" };
      if (c.expired) return { code, name, count: 1, action: "fetch", sub: "設定檔已過期，請重新取得", warn: true };
      const days = Math.floor(c.hours_left / 24);
      const left = c.hours_left < 24 ? `剩 ${c.hours_left} 小時，請盡快更新` : `剩 ${days} 天`;
      return { code, name, count: 1, action: "connect", sub: `設定檔${left} · ${c.server}`, warn: c.hours_left < 24 };
    });
  }
  if (mode === "tor") {
    if (!torAvailable) return [];
    return (torList || []).map((t) => ({ code: t.code, name: t.name, count: t.exits,
      sub: t.exits ? `出口節點 ${t.exits} 個` : "目前沒有出口節點" }));
  }
  return countries.map((c) => {
    // 只列出剛剛實際檢查過、確定能連的伺服器
    return { code: c.code, name: c.name, count: c.count,
      sub: c.count ? `${c.count} 台可連 · 最快 ${c.best.latency_ms} ms · ${c.best.host}` : "目前沒有可用的伺服器" };
  });
}

function setMode(m) {
  mode = m;
  try { localStorage.setItem("aixai-mode", m); } catch (e) { /* 忽略 */ }
  $("tab-vpngate").classList.toggle("is-on", m === "vpngate");
  $("tab-tor").classList.toggle("is-on", m === "tor");
  $("tab-vpnbook").classList.toggle("is-on", m === "vpnbook");
  $("tor-note").hidden = m !== "tor";
  $("vpnbook-note").hidden = m !== "vpnbook";
  renderFetch();
  renderCountries();
}

// 一律用 textContent 寫入，避免伺服器清單裡的文字被當成 HTML 執行
function renderCountries() {
  const list = $("country-list");
  const tpl = $("card-tpl");
  list.replaceChildren();

  const busy = conn.status !== "idle";
  const all = items();
  // 掃描結果沒有的國家不顯示（使用者回饋）；只在下方用一行文字帶過
  for (const c of all.filter((x) => x.count)) {
    const card = tpl.content.firstElementChild.cloneNode(true);
    const isMine = busy && conn.mode === mode && conn.country === c.code;
    card.classList.add(c.count ? "available" : "unavailable");
    if (isMine) card.classList.add("is-active");
    card.querySelector(".badge").textContent = c.code;
    card.querySelector(".name").textContent = c.name;
    card.querySelector(".sub").textContent = c.sub;
    card.querySelector(".sub").classList.toggle("is-warn", !!c.warn);

    const btn = card.querySelector(".connect");
    btn.removeAttribute("title");
    if (isMine) {
      btn.textContent = conn.status === "connecting" ? "取消" : "中斷";
      btn.disabled = conn.status === "disconnecting";
      btn.addEventListener("click", disconnect);
    } else if (c.action === "fetch") {
      btn.textContent = "取得";
      btn.disabled = !!vpnbook.fetch.fetching;
      btn.addEventListener("click", () => fetchVpnbook(c.code));
    } else {
      btn.textContent = "連線";
      btn.disabled = !c.count || busy;
      btn.addEventListener("click", () => connect(c.code, mode));
    }
    list.append(card);
  }
  const avail = all.filter((c) => c.count).length;
  const off = all.length - avail;
  $("avail-count").textContent = all.length ? `${avail} / ${all.length}` : "";
  const empty = $("empty-note");
  if (mode === "vpnbook" && !vpnbook.available) {
    empty.textContent = "尚未安裝 WireGuard（https://www.wireguard.com/install/），安裝後重新開啟 App。";
  } else if (mode === "tor" && !torAvailable) {
    empty.textContent = "找不到 Tor 程式（開發者請先執行 python tools/fetch_tor.py）。";
  } else if (mode === "tor" && torList === null && countries.length) {
    empty.textContent = "抓不到 Tor 出口節點資料，請稍後再搜尋。";
  } else {
    empty.textContent = "目前 15 國都沒有可用的連線，請稍後再搜尋。";
  }
  empty.hidden = !(all.length === 0 ? ((mode === "tor" && countries.length) || mode === "vpnbook") : avail === 0);
  const offNames = all.filter((x) => !x.count).map((x) => x.name).join("、");
  $("unavail-note").hidden = mode === "vpnbook" || off === 0 || avail === 0;
  $("unavail-note").textContent = `其他 ${off} 國目前沒有${mode === "tor" ? "出口節點" : "可用的伺服器"}：${offNames}`;
}

function renderStatus(s) {
  lastStatus = s;
  renderAbout(s);
  if (s.terms && !s.terms.accepted && !$("terms-dialog").open) openTerms(true);
  conn = s.connection;
  torAvailable = s.tor_available !== false;
  if (s.vpnbook) vpnbook = s.vpnbook;
  renderFetch();
  const on = conn.status === "connected";
  const pill = { idle: "未連線", connecting: "連線中", connected: "已連線", disconnecting: "中斷中",
                 reconnecting: "重新連線中", blocked: "網路暫停" };
  $("conn-pill").className = `pill ${on ? "pill-on" : conn.status === "idle" ? "pill-off" : "pill-busy"}`;
  $("conn-text").textContent = pill[conn.status] || conn.status;
  $("ks").textContent = s.kill_switch ? "開" : "關";
  // Tor 會為不同連線、不同時間換線路，IP 本來就會變；能保證的是國家 → 只顯示出口國家
  const tor = conn.mode === "tor";
  $("ip-label").textContent = tor && on ? "出口國家" : "對外 IP";
  $("ip").textContent = !on ? "—" : tor ? `${countryName(conn.loc)}（IP 會隨 Tor 線路變動）`
    : conn.ip ? `${conn.ip}（${conn.loc}）` : "—";

  if (on) {
    $("hero-value").textContent = `${countryName(conn.country)} · ${conn.host}`;
  } else if ((conn.status === "connecting" || conn.status === "reconnecting") && conn.mode === "tor") {
    $("hero-value").textContent = `啟動 Tor → ${countryName(conn.country)}（${conn.progress}%）`;
  } else if (conn.status === "connecting" || conn.status === "reconnecting") {
    $("hero-value").textContent = `連線到${countryName(conn.country)}…（${conn.attempt}/${conn.attempts_max}）`;
  } else if (conn.status === "blocked") {
    $("hero-value").textContent = "網路暫停中（斷線保護）";
  } else {
    $("hero-value").textContent = "未使用 VPN";
  }
  // 斷線保護狀態的提示框：重新連線中／網路暫停
  const guarded = conn.status === "reconnecting" || conn.status === "blocked";
  $("banner").hidden = !guarded;
  $("banner").classList.toggle("is-blocked", conn.status === "blocked");
  $("banner-text").textContent = guarded ? conn.message : "";
  $("retry-btn").hidden = conn.status !== "blocked";
  // 研究模式：強制使用 VPN（ADR-004）→ 不提供「改用一般網路」，暫停時自動重試
  const research = !!s.research_mode;
  $("research-toggle").checked = research;
  $("normal-btn").hidden = research;
  if (guarded && research) $("banner-text").textContent = `${conn.message}（研究模式：每 30 秒自動重試）`;
  $("warning").hidden = !(on && conn.warning);
  $("warning").textContent = conn.warning || "";

  const quiet = ["", "已中斷", "已取消"];
  if (conn.status === "idle" && !quiet.includes(conn.message || "")) showError(conn.message);
  $("search-btn").disabled = conn.status !== "idle";
  // 連線中 → 分頁自動切到正在使用的模式，避免連著 Tor 卻停在 VPN Gate 分頁
  if (conn.status !== "idle" && conn.mode && conn.mode !== mode) setMode(conn.mode);
  else if (vpnbook.fetch.fetching && mode !== "vpnbook") setMode("vpnbook");  // 等待下載時固定顯示步驟說明
  else renderCountries();
}

async function refreshStatus() {
  try {
    renderStatus(await api("/api/status"));
  } catch (e) {
    showError(`無法連到本機服務：${e.message}`);
  }
  // 連線或中斷進行中 → 每秒更新；否則停止輪詢
  const busy = ["connecting", "disconnecting", "reconnecting", "connected", "blocked"].includes(conn.status)
    || !!vpnbook.fetch.fetching  // 等待 VPNBook 下載時也要持續更新
    || ["checking", "installing", "restarting"].includes(lastStatus?.update?.stage);  // 查詢或安裝版本中
  clearTimeout(pollTimer);
  // 已連線時也要持續更新，才看得到意外斷線
  if (busy) pollTimer = setTimeout(refreshStatus, conn.status === "connected" ? 2000 : 1000);
}

async function connect(code, m) {
  showError("");
  try {
    renderStatus(await api("/api/connect", "POST", { country: code, mode: m }));
  } catch (e) {
    showError(e.message);
  }
  refreshStatus();
}

async function disconnect() {
  showError("");
  try {
    renderStatus(await api("/api/disconnect", "POST", {}));
  } catch (e) {
    showError(e.message);
  }
  refreshStatus();
}

async function search() {
  const btn = $("search-btn");
  btn.disabled = true;
  btn.classList.add("is-loading");
  btn.querySelector("span").textContent = "搜尋並檢查中";
  showError("");
  try {
    const data = await api("/api/search", "POST");
    countries = data.countries;
    torList = data.tor ?? null;
    // 國家名稱要等搜尋結果回來才知道 → 重畫一次狀態（例如把 JP 顯示成「日本」）
    if (lastStatus) renderStatus(lastStatus); else renderCountries();
    const t = new Date(data.fetched_at).toLocaleTimeString("zh-TW");
    $("meta").textContent =
      `檢查 ${data.checked} 台，${data.usable} 台確定可連 · 更新於 ${t}`;
  } catch (e) {
    showError(e.message);
  } finally {
    btn.disabled = conn.status !== "idle";
    btn.classList.remove("is-loading");
    btn.querySelector("span").textContent = "搜尋伺服器";
  }
}

async function retry() {
  showError("");
  try {
    renderStatus(await api("/api/retry", "POST", {}));
  } catch (e) {
    showError(e.message);
  }
  refreshStatus();
}

// 心跳：讓 App 知道視窗還開著；關閉視窗時通知 App（keepalive 讓請求在頁面關閉後仍送得出去）
setInterval(() => api("/api/heartbeat", "POST", {}).catch(() => {}), 5000);
api("/api/heartbeat", "POST", {}).catch(() => {});
addEventListener("pagehide", () => {
  fetch("/api/bye", { method: "POST", keepalive: true,
    headers: { "X-AIXAI-Token": TOKEN, "Content-Type": "application/json" }, body: "{}" });
});

// 研究模式警告：App 內對話框，文字會依視窗寬度換行；按 Esc 或「取消」都視為不同意
function confirmResearch() {
  const dlg = $("research-dialog");
  return new Promise((resolve) => {
    const done = (ok) => {
      dlg.removeEventListener("close", onClose);
      if (dlg.open) dlg.close();
      resolve(ok);
    };
    const onClose = () => done(false);
    dlg.addEventListener("close", onClose);
    $("research-ok").onclick = () => done(true);
    $("research-cancel").onclick = () => done(false);
    dlg.showModal();
    $("research-cancel").focus();  // 預設焦點放在「取消」，避免誤按 Enter 就開啟
  });
}

async function toggleResearch(e) {
  const want = e.target.checked;
  if (want && !(await confirmResearch())) {  // 開啟前一定先確認警告
    e.target.checked = false;
    return;
  }
  try {
    renderStatus(await api("/api/settings", "POST", { research_mode: want }));
  } catch (err) {
    e.target.checked = !want;
    showError(err.message);
  }
}

// ---- 使用條款（第一次啟動或條款改版時必須同意）----
let termsLoaded = false;
async function openTerms(required) {
  const dlg = $("terms-dialog");
  $("terms-consent").hidden = !required;
  $("terms-accept").hidden = !required;
  $("terms-decline").hidden = !required;
  $("terms-close").hidden = required;
  $("terms-check").checked = false;
  $("terms-accept").disabled = true;
  dlg.dataset.required = required ? "1" : "";
  if (!dlg.open) dlg.showModal();
  if (!termsLoaded) {
    try {
      const t = await api("/api/terms");
      // 純文字顯示（不解析 HTML）；去掉 Markdown 的標題與粗體符號比較好讀
      $("terms-text").textContent = t.text.replace(/^#+\s*/gm, "").replace(/\*\*|`/g, "");
      $("terms-ver").textContent = `版本 ${t.version}`;
      termsLoaded = true;
    } catch (e) {
      $("terms-text").textContent = `無法載入條款：${e.message}`;
    }
  }
}
$("terms-check").addEventListener("change", (e) => { $("terms-accept").disabled = !e.target.checked; });
$("terms-accept").addEventListener("click", async () => {
  try {
    renderStatus(await api("/api/terms/accept", "POST", { version: lastStatus.terms.version }));
    $("terms-dialog").dataset.required = "";
    $("terms-dialog").close();
  } catch (e) {
    $("terms-text").textContent = e.message;
  }
});
$("terms-decline").addEventListener("click", async () => {
  await api("/api/quit", "POST", {}).catch(() => {});
  window.close();  // Edge 模式時關閉視窗（App 視窗由程式自己關閉）
});
$("terms-close").addEventListener("click", () => $("terms-dialog").close());
// 必須同意時，Esc 不能關掉條款視窗
$("terms-dialog").addEventListener("cancel", (e) => { if ($("terms-dialog").dataset.required) e.preventDefault(); });

// ---- 關於：版本更新／退版 ----
let armedTag = null;  // 退回舊版要按兩次確認
function renderAbout(s) {
  const u = s.update || {};
  const sum = u.summary;
  $("about-ver").textContent = `v${s.version}`;
  $("update-dot").hidden = !(sum && sum.update_available);
  $("auto-update").checked = !!s.auto_update_check;
  const stage = u.stage || "idle";
  let msg = u.message || "";
  if (!msg && sum) msg = sum.update_available ? `有新版本 v${sum.latest}` : "目前是最新版本";
  if (!u.supported) msg = (msg ? msg + "。" : "") + "開發版不支援程式內更新（請改用 exe）";
  $("update-msg").textContent = msg;
  $("update-msg").classList.toggle("is-error", stage === "error");
  $("update-progress").hidden = stage !== "installing";
  $("update-bar").style.width = `${u.pct || 0}%`;
  $("update-check").disabled = ["checking", "installing", "restarting"].includes(stage);

  const list = $("release-list");
  list.replaceChildren();
  const idle = s.connection.status === "idle";
  for (const r of (sum ? sum.items : [])) {
    const li = document.createElement("li");
    li.className = "release";
    const info = document.createElement("div");
    info.className = "rinfo";
    const tag = document.createElement("p");
    tag.className = "rtag";
    tag.textContent = r.tag;
    for (const [show, text, cls] of [[r.current, "目前", ""], [r.beta, "測試版", ""], [r.newer && !r.beta, "新", "tag-new"]]) {
      if (!show) continue;
      const b = document.createElement("span");
      b.className = `tag ${cls}`;
      b.textContent = text;
      tag.append(b);
    }
    const sub = document.createElement("p");
    sub.className = "rsub";
    const firstLine = (r.notes || "").split("\n").map((l) => l.replace(/^[#\-*\s]+/, "")).find((l) => l) || "";
    sub.textContent = firstLine ? `${r.published} · ${firstLine}` : r.published;
    info.append(tag, sub);
    const btn = document.createElement("button");
    btn.className = "btn btn-ghost";
    if (r.current) {
      btn.textContent = "使用中";
      btn.disabled = true;
    } else {
      btn.textContent = armedTag === r.tag ? "確定退回？" : r.newer ? "更新" : "退回此版";
      btn.disabled = !u.supported || !r.installable || !idle || stage === "installing" || stage === "restarting";
      btn.title = !r.installable ? "此版本沒有可驗證的執行檔" : !idle ? "請先中斷 VPN" : "";
      btn.addEventListener("click", () => installVersion(r));
    }
    li.append(info, btn);
    list.append(li);
  }
}

async function installVersion(r) {
  if (!r.newer && armedTag !== r.tag) {  // 退回舊版：再按一次才執行
    armedTag = r.tag;
    renderAbout(lastStatus);
    return;
  }
  armedTag = null;
  try {
    renderStatus(await api("/api/updates/install", "POST", { tag: r.tag }));
  } catch (e) {
    $("update-msg").textContent = e.message;
    $("update-msg").classList.add("is-error");
  }
  refreshStatus();
}

async function checkUpdates() {
  try {
    renderStatus(await api("/api/updates/check", "POST", {}));
  } catch (e) {
    $("update-msg").textContent = e.message;
  }
  refreshStatus();
}

$("about-btn").addEventListener("click", () => {
  armedTag = null;
  $("about-dialog").showModal();
  const u = lastStatus?.update;
  if (u && !u.summary && u.stage !== "checking") checkUpdates();  // 還沒查過 → 打開時查一次
});
$("about-close").addEventListener("click", () => $("about-dialog").close());
$("update-check").addEventListener("click", checkUpdates);
$("auto-update").addEventListener("change", async (e) => {
  try {
    renderStatus(await api("/api/settings", "POST", { auto_update_check: e.target.checked }));
  } catch (err) {
    e.target.checked = !e.target.checked;
  }
});
$("open-terms").addEventListener("click", () => { $("about-dialog").close(); openTerms(false); });
for (const b of document.querySelectorAll("[data-open]")) {
  b.addEventListener("click", () => api("/api/open", "POST", { target: b.dataset.open }).catch(() => {}));
}

// ---- 回報問題：App 只整理內容並開啟 GitHub／郵件程式，由使用者確認後自己送出 ----
let lastReport = "";
$("open-feedback").addEventListener("click", () => {
  $("about-dialog").close();
  $("fb-msg").hidden = true;
  $("fb-copy").hidden = true;
  $("feedback-dialog").showModal();
  $("fb-text").focus();
});
$("fb-cancel").addEventListener("click", () => $("feedback-dialog").close());
async function sendFeedback(channel) {
  const kind = document.querySelector('input[name="fb-kind"]:checked').value;
  const msg = $("fb-msg");
  msg.hidden = false;
  msg.classList.remove("is-error");
  try {
    const r = await api("/api/feedback", "POST",
      { kind, text: $("fb-text").value, channel, include_diag: $("fb-diag").checked });
    lastReport = `# ${r.title}\n\n${r.body}`;
    $("fb-copy").hidden = false;
    msg.textContent = !r.opened ? "無法自動開啟，請按「複製內容」後自行貼上。"
      : channel === "github"
        ? "已在瀏覽器開啟 GitHub 回報頁（需登入 GitHub）。確認內容後按「Create」送出；截圖可直接拖曳進去。"
        : "已開啟郵件程式。確認內容後寄出；若沒有跳出，按「複製內容」改用網頁信箱寄到 aixai19861201@gmail.com。";
  } catch (e) {
    msg.textContent = e.message;
    msg.classList.add("is-error");
  }
}
$("fb-github").addEventListener("click", () => sendFeedback("github"));
$("fb-email").addEventListener("click", () => sendFeedback("email"));
$("fb-copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(lastReport);
    $("fb-msg").textContent = "已複製到剪貼簿。";
  } catch (e) {
    $("fb-msg").textContent = "無法複製到剪貼簿。";
  }
});

$("search-btn").addEventListener("click", search);
$("research-toggle").addEventListener("change", toggleResearch);
$("tab-vpngate").addEventListener("click", () => setMode("vpngate"));
$("tab-tor").addEventListener("click", () => setMode("tor"));
$("tab-vpnbook").addEventListener("click", () => setMode("vpnbook"));
setMode(mode);
$("retry-btn").addEventListener("click", retry);
$("normal-btn").addEventListener("click", disconnect);
refreshStatus().then(search);
