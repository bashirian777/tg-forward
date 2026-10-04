"use strict";

const ICONS = {
  grid: '<svg class="icon" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>',
  layers: '<svg class="icon" viewBox="0 0 24 24"><path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="m3 13 9 5 9-5"/><path d="m3 18 9 5 9-5"/></svg>',
  database: '<svg class="icon" viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
  sliders: '<svg class="icon" viewBox="0 0 24 24"><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M2 14h4M10 8h4M18 16h4"/></svg>',
  terminal: '<svg class="icon" viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m6 9 3 3-3 3M12 15h6"/></svg>',
  send: '<svg class="icon" viewBox="0 0 24 24"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z"/></svg>',
  lock: '<svg class="icon" viewBox="0 0 24 24"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  moon: '<svg class="icon" viewBox="0 0 24 24"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>',
  sun: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  plus: '<svg class="icon" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  play: '<svg class="icon" viewBox="0 0 24 24"><path d="m7 4 13 8-13 8V4Z"/></svg>',
  pause: '<svg class="icon" viewBox="0 0 24 24"><path d="M9 5v14M15 5v14"/></svg>',
  resume: '<svg class="icon" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg>',
  stop: '<svg class="icon" viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="3"/></svg>',
  edit: '<svg class="icon" viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  flag: '<svg class="icon" viewBox="0 0 24 24"><path d="M5 21V4"/><path d="M5 4c4-1.5 8 1.5 12 0v11c-4 1.5-8-1.5-12 0"/></svg>',
  trash: '<svg class="icon" viewBox="0 0 24 24"><path d="M3 6h18M8 6V3h8v3M19 6l-1 15H6L5 6M10 11v5M14 11v5"/></svg>',
  eraser: '<svg class="icon" viewBox="0 0 24 24"><path d="m20 20-8.5-8.5a2.1 2.1 0 0 0-3 0L3 17M16 7l4-4M13 4l7 7"/></svg>',
  skip: '<svg class="icon" viewBox="0 0 24 24"><path d="m5 4 10 8-10 8V4Z"/><path d="M19 5v14"/></svg>',
  refresh: '<svg class="icon" viewBox="0 0 24 24"><path d="M20 6v5h-5M4 18v-5h5M6.1 9A7 7 0 0 1 18 6l2 3M4 15l2 3a7 7 0 0 0 11.9-3"/></svg>',
  x: '<svg class="icon" viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  check: '<svg class="icon" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>',
  alert: '<svg class="icon" viewBox="0 0 24 24"><path d="M12 3 2.5 20h19L12 3Z"/><path d="M12 10v4M12 17h.01"/></svg>',
  search: '<svg class="icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>',
  arrow: '<svg class="icon" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  clock: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  hash: '<svg class="icon" viewBox="0 0 24 24"><path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/></svg>',
  history: '<svg class="icon" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5M12 7v5l3 2"/></svg>',
  move: '<svg class="icon" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  disk: '<svg class="icon" viewBox="0 0 24 24"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 5h.01M2 14h20M2 17h20"/></svg>',
  folder: '<svg class="icon" viewBox="0 0 24 24"><path d="M3 6a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6Z"/></svg>',
  activity: '<svg class="icon" viewBox="0 0 24 24"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>',
  pen: '<svg class="icon" viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  inbox: '<svg class="icon" viewBox="0 0 24 24"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1Z"/></svg>',
  message: '<svg class="icon" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10Z"/></svg>',
  filter: '<svg class="icon" viewBox="0 0 24 24"><path d="M22 3H2l8 9.5V19l4 2v-8.5L22 3Z"/></svg>',
  tag: '<svg class="icon" viewBox="0 0 24 24"><path d="M20.6 13.4 12 22 4 14V4h10l6.6 6.6a2 2 0 0 1 0 2.8Z"/><path d="M8 8h.01"/></svg>',
  up: '<svg class="icon sm" viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
  down: '<svg class="icon sm" viewBox="0 0 24 24"><path d="M12 5v14M19 12l-7 7-7-7"/></svg>'
};

function applyIcons(root) {
  (root || document).querySelectorAll("[data-icon]").forEach((el) => {
    const name = el.dataset.icon;
    if (ICONS[name]) el.innerHTML = ICONS[name];
  });
}

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const get = (id) => document.getElementById(id);

const AUTH_TOKEN_KEY = "tg_forwarder_web_token";
let authToken = localStorage.getItem(AUTH_TOKEN_KEY) || "";
const AUTH_EXPIRY_KEY = "tg_forwarder_web_expiry";
let authExpiresAt = Number(localStorage.getItem(AUTH_EXPIRY_KEY)) || 0;
let refreshTimer = null;
const state = { tasks: [], system: null, config: null, deployment: null, logs: [] };
let taskFilter = "all";
let taskSearch = "";

/* ---------- auth ---------- */
function showGate(message = "") {
  get("auth-gate").hidden = false;
  get("app-content").hidden = true;
  get("auth-error").textContent = message;
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
}
function showApp() {
  get("auth-gate").hidden = true;
  get("app-content").hidden = false;
  if (!refreshTimer) { refresh(); refreshTimer = setInterval(refresh, 5000); }
}
async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (authToken) headers.set("Authorization", "Bearer " + authToken);
  const response = await fetch(url, { ...options, headers });
  if (response.status === 401) {
    authToken = "";
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_EXPIRY_KEY);
    authExpiresAt = 0;
    showGate("登录已过期，请重新输入密码");
  }
  return response;
}

get("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = get("auth-submit");
  const error = get("auth-error");
  button.disabled = true;
  button.classList.add("busy");
  error.textContent = "";
  try {
    const response = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: get("auth-password").value })
    });
    const data = await response.json();
    if (!response.ok) throw new Error("invalid");
    authToken = data.token || "";
    if (authToken) localStorage.setItem(AUTH_TOKEN_KEY, authToken);
    authExpiresAt = Number(data.expires_at) || 0;
    localStorage.setItem(AUTH_EXPIRY_KEY, String(authExpiresAt));
    get("auth-form").reset();
    showApp();
  } catch (e) {
    error.textContent = "密码错误或服务不可用";
  } finally {
    button.disabled = false;
    button.classList.remove("busy");
  }
});

/* ---------- theme ---------- */
function syncThemeIcon(theme) {
  const moon = get("theme-btn").querySelector('[data-icon="moon"]');
  const sun = get("theme-btn").querySelector('[data-icon="sun"]');
  if (moon) moon.classList.toggle("on", theme === "dark");
  if (sun) sun.classList.toggle("on", theme === "light");
}
(function initTheme() {
  const stored = localStorage.getItem("theme");
  const theme = stored === "light" || stored === "dark"
    ? stored
    : (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  document.documentElement.dataset.theme = theme;
  syncThemeIcon(theme);
  get("theme-btn").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme", next);
    syncThemeIcon(next);
  });
})();

/* ---------- dialog helpers ---------- */
function openModal(id) {
  const modal = get(id);
  modal.hidden = false;
  requestAnimationFrame(() => modal.classList.add("show"));
}
function closeModal(id) {
  const modal = get(id);
  modal.classList.remove("show");
  setTimeout(() => { modal.hidden = true; }, 200);
}
document.querySelectorAll("[data-close]").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.close === "confirm-modal" && confirmResolver) {
      confirmResolver(false);
      confirmResolver = null;
    }
    closeModal(btn.dataset.close);
  });
});
document.querySelectorAll(".modal").forEach((modal) => {
  modal.addEventListener("click", (e) => {
    if (e.target === modal) {
      if (modal.id === "confirm-modal" && confirmResolver) {
        confirmResolver(false);
        confirmResolver = null;
      }
      closeModal(modal.id);
    }
  });
});

let confirmResolver = null;
function askConfirm(title, message, danger = true) {
  return new Promise((resolve) => {
    confirmResolver = resolve;
    get("confirm-title").textContent = title;
    get("confirm-message").textContent = message;
    get("confirm-ok").className = "btn " + (danger ? "danger" : "primary");
    openModal("confirm-modal");
  });
}
get("confirm-ok").addEventListener("click", () => {
  closeModal("confirm-modal");
  if (confirmResolver) { confirmResolver(true); confirmResolver = null; }
});

let toastTimer = null;
function showToast(message) {
  const toast = get("toast");
  get("toast-text").textContent = message;
  toast.hidden = false;
  requestAnimationFrame(() => toast.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => { toast.hidden = true; }, 220);
  }, 2800);
}

/* ---------- formatting ---------- */
const fmtTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return esc(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
  if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
  if (diff < 86400 * 7) return Math.floor(diff / 86400) + " 天前";
  return d.toLocaleString();
};
function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024 * 1024) return (value / 1024).toFixed(1) + " KB";
  if (value < 1024 * 1024 * 1024) return (value / (1024 * 1024)).toFixed(1) + " MB";
  return (value / (1024 * 1024 * 1024)).toFixed(2) + " GB";
}
function formatUptime(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const d = Math.floor(value / 86400);
  const h = Math.floor((value % 86400) / 3600);
  const m = Math.floor((value % 3600) / 60);
  return (d ? d + " 天 " : "") + h + " 小时 " + m + " 分钟";
}

/* ---------- animated numbers ---------- */
const statPrev = {};
function animateValue(id, value) {
  const el = get(id);
  const from = statPrev[id] ?? 0;
  const to = Number(value) || 0;
  statPrev[id] = to;
  if (from === to) { el.textContent = to; return; }
  const t0 = performance.now();
  const dur = 380;
  function tick(now) {
    const p = Math.min(1, (now - t0) / dur);
    const e = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(from + (to - from) * e);
    if (p < 1) requestAnimationFrame(tick);
    else el.textContent = to;
  }
  requestAnimationFrame(tick);
}

/* ---------- filters ---------- */
function matchesFilter(t) {
  if (taskFilter === "transfer") return !!t.transfer;
  if (taskFilter === "disabled") return t.config && t.config.enabled === false;
  if (taskFilter !== "all") return t.status === taskFilter;
  return true;
}
function matchesSearch(t) {
  if (!taskSearch) return true;
  const cfg = t.config || {};
  const q = taskSearch.toLowerCase();
  return [t.task_id, cfg.note, cfg.source_channel, cfg.target_channel]
    .map((v) => String(v ?? "")).join(" ").toLowerCase().includes(q);
}
function updateChips() {
  document.querySelectorAll("#task-chips .chip").forEach((chip) => {
    chip.classList.toggle("active", chip.dataset.filter === taskFilter);
  });
  const counts = { running: 0, paused: 0, stopped: 0, transfer: 0, disabled: 0 };
  state.tasks.forEach((t) => {
    if (t.status === "running") counts.running++;
    else if (t.status === "paused") counts.paused++;
    else counts.stopped++;
    if (t.transfer) counts.transfer++;
    if (t.config && t.config.enabled === false) counts.disabled++;
  });
  const chipAll = get("chip-all");
  if (chipAll) chipAll.textContent = state.tasks.length;
}

/* ---------- render: stats ---------- */
function renderStats() {
  const tasks = state.tasks;
  const running = tasks.filter((t) => t.status === "running").length;
  const paused = tasks.filter((t) => t.status === "paused").length;
  const forwarded = tasks.reduce((s, t) => s + (Number((t.progress || {}).forwarded_count) || 0), 0);
  animateValue("stat-total", tasks.length);
  animateValue("stat-running", running);
  animateValue("stat-paused", paused);
  animateValue("stat-forwarded", forwarded);
  get("task-count").textContent = tasks.length ? tasks.length + " 个" : "";
}

/* ---------- render: tasks (keyed patch, 无页面跳动) ---------- */
const taskCards = new Map();
const taskSigs = new Map();

function taskSignature(t) {
  return JSON.stringify([t.task_id, t.status, t.config, t.progress, t.transfer, t.dedup, t.errors]);
}
function buildTaskCard(t) {
  const cfg = t.config || {};
  const prog = t.progress || {};
  const cls = t.status === "running" ? "running" : t.status === "paused" ? "paused" : "stopped";
  const label = t.status === "running" ? "运行中" : t.status === "paused" ? "已暂停" : t.status === "error" ? "需要处理错误" : "已停止";
  const action = t.status === "running" ? "pause" : t.status === "paused" ? "resume" : "start";
  const actionLabel = t.status === "running" ? "暂停" : t.status === "paused" ? "恢复" : "启动";
  const actionIcon = t.status === "running" ? "pause" : t.status === "paused" ? "resume" : "play";

  let strip = "";
  if (t.transfer) {
    const d = t.transfer;
    const isUp = d.type === "upload";
    const pct = Math.max(0, Math.min(100, Number(d.percent) || 0));
    const failed = d.state === "error";
    const stateLabels = { error: "传输失败", interrupted: "已中断", fetching: "等待处理", waiting_disk: "等待磁盘空间", sending: "等待发送确认", downloading: "下载中", uploading: "上传中" };
    const stText = stateLabels[d.state] || "等待处理";
    strip = '<div class="transfer-strip ' + (failed ? "has-error" : "") + '">'
      + '<div class="head"><span class="transfer-type">' + (isUp ? ICONS.up : ICONS.down) + " 媒体组 " + (Number(d.file_index) || 1) + " / " + (Number(d.total_files) || 1) + " · " + stText + "</span><span>" + esc(d.filename || "处理中") + "</span></div>"
      + '<div class="progress"><div class="fill ' + (isUp ? "up" : "down") + '" style="width:' + pct + '%"></div></div>'
      + '<div class="sub"><span>' + (d.current_str || "0B") + " / " + (d.total_str || "—") + "</span><span>" + esc(d.speed_str || "计算中") + "</span></div>"
      + "</div>";
  }

  let tags = "";
  const kw = cfg.filter_keywords || [];
  const ht = cfg.required_hashtags || [];
  const dedup = t.dedup && t.dedup.total_tracked ? t.dedup.total_tracked : 0;
  if (kw.length) tags += '<span class="tag">' + ICONS.filter + " " + esc(kw.slice(0, 3).join(", ")) + (kw.length > 3 ? " 等" : "") + "</span>";
  if (ht.length) tags += '<span class="tag">' + ICONS.tag + " " + esc(ht.slice(0, 3).join(", ")) + (ht.length > 3 ? " 等" : "") + "</span>";
  if (cfg.source_topic_id) tags += '<span class="tag">' + ICONS.message + " 来源话题 " + esc(cfg.source_topic_id) + "</span>";
  if (cfg.target_topic_id) tags += '<span class="tag">' + ICONS.message + " 目标话题 " + esc(cfg.target_topic_id) + "</span>";
  if (cfg.send_as_channel) tags += '<span class="tag">' + ICONS.send + " 渠道身份</span>";

  let buttons = "";
  const errorCount = Number(t.errors && t.errors.unresolved) || 0;
  if (errorCount > 0) {
    buttons += '<button class="icon-btn task-error-btn" data-task="' + esc(t.task_id) + '" data-action="errors" aria-label="查看错误" title="查看错误（' + errorCount + '）">' + ICONS.alert + '<span class="error-count">' + errorCount + '</span></button>';
  }
  if (t.transfer) {
    buttons += '<button class="btn" data-task="' + esc(t.task_id) + '" data-action="refresh-transfer">' + ICONS.refresh + " 从断点重试</button>";
    buttons += '<button class="btn" data-task="' + esc(t.task_id) + '" data-action="skip-transfer">' + ICONS.skip + " 跳过媒体组</button>";
  }
  buttons += '<button class="btn" data-task="' + esc(t.task_id) + '" data-action="progress">' + ICONS.flag + " 断点</button>";
  buttons += '<button class="btn" data-task="' + esc(t.task_id) + '" data-action="edit">' + ICONS.edit + " 编辑</button>";
  buttons += '<button class="btn" data-task="' + esc(t.task_id) + '" data-action="' + action + '">' + ICONS[actionIcon] + " " + actionLabel + "</button>";
  buttons += '<button class="btn danger" data-task="' + esc(t.task_id) + '" data-action="cleanup-files">' + ICONS.trash + " 清理文件</button>";
  if (t.status === "running" || t.status === "paused") buttons += '<button class="btn" data-task="' + esc(t.task_id) + '" data-action="stop">' + ICONS.stop + " 停止</button>";
  buttons += '<button class="btn danger" data-task="' + esc(t.task_id) + '" data-action="clear-dedup">' + ICONS.eraser + " 清空去重</button>";
  buttons += '<button class="btn danger" data-task="' + esc(t.task_id) + '" data-action="delete">' + ICONS.trash + " 删除</button>";

  return '<div class="card" data-card-id="' + esc(t.task_id) + '">'
    + '<div class="task-head">'
    + '<div class="task-main">'
    + '<div class="task-avatar">' + ICONS.send + "</div>"
    + '<div><div class="task-title">' + esc(cfg.note || t.task_id) + '</div><div class="task-id">' + esc(t.task_id) + "</div></div>"
    + "</div>"
    + '<div class="task-badges">'
    + '<span class="badge ' + cls + '"><span class="dot"></span>' + label + "</span>"
    + (cfg.enabled === false ? '<span class="badge off">已禁用</span>' : "")
    + "</div>"
    + "</div>"
    + '<div class="route">' + ICONS.inbox + "<code>" + esc(cfg.source_channel ?? "—") + "</code>" + ICONS.arrow + ICONS.send + "<code>" + esc(cfg.target_channel ?? "—") + "</code></div>"
    + '<div class="task-meta">'
    + '<div class="meta-item"><span class="k">' + ICONS.clock + " 延迟</span><span class=\"v\">" + esc(cfg.min_delay ?? 0) + "s - " + esc(cfg.max_delay ?? 0) + "s</span></div>"
    + '<div class="meta-item"><span class="k">' + ICONS.send + " 已转发</span><span class=\"v\">" + (Number(prog.forwarded_count) || 0) + " 条</span></div>"
    + '<div class="meta-item"><span class="k">' + ICONS.flag + " 断点</span><span class=\"v\"><code>" + esc(prog.last_message_id ?? 0) + "</code></span></div>"
    + '<div class="meta-item"><span class="k">' + ICONS.history + " 最后转发</span><span class=\"v\">" + fmtTime(prog.last_forward_time) + "</span></div>"
    + "</div>"
    + (tags ? '<div class="tags">' + tags + "</div>" : "")
    + strip
    + '<div class="task-actions">' + buttons + "</div>"
    + "</div>";
}

function renderTasks() {
  updateChips();
  const visible = state.tasks.filter(matchesFilter).filter(matchesSearch);
  const container = get("tasks");

  if (!visible.length) {
    if (container.dataset.empty !== "1") {
      container.innerHTML = '<div class="empty"><span data-icon="' + (state.tasks.length ? "filter" : "layers") + '" class="empty-icon"></span>' + (state.tasks.length ? "没有符合当前筛选条件的任务" : "还没有任务，点击右上角“新建任务”开始") + "</div>";
      container.dataset.empty = "1";
      applyIcons(container);
    }
    taskCards.clear();
    taskSigs.clear();
    return;
  }

  if (container.dataset.empty === "1") {
    container.innerHTML = "";
    container.dataset.empty = "";
  }

  const present = new Set();
  visible.forEach((t) => {
    present.add(t.task_id);
    const sig = taskSignature(t);
    let el = taskCards.get(t.task_id);
    if (!el) {
      const wrapper = document.createElement("div");
      wrapper.innerHTML = buildTaskCard(t);
      el = wrapper.firstElementChild;
      taskCards.set(t.task_id, el);
      taskSigs.set(t.task_id, sig);
    } else if (taskSigs.get(t.task_id) !== sig) {
      const wrapper = document.createElement("div");
      wrapper.innerHTML = buildTaskCard(t);
      const newEl = wrapper.firstElementChild;
      el.replaceWith(newEl);
      el = newEl;
      taskCards.set(t.task_id, el);
      taskSigs.set(t.task_id, sig);
    }
    container.appendChild(el);
  });

  taskCards.forEach((el, id) => {
    if (!present.has(id)) {
      el.remove();
      taskCards.delete(id);
      taskSigs.delete(id);
    }
  });
}

/* ---------- render: system / config / logs ---------- */
function renderSystem() {
  const system = state.system;
  if (!system) return;
  if (system.disk) {
    get("system-disk").textContent = formatBytes(system.disk.free) + " 可用";
    get("system-disk-sub").textContent = formatBytes(system.disk.used) + " / " + formatBytes(system.disk.total) + " · " + system.disk.percent + "% 已用";
    get("system-load").textContent = (system.load_average || []).join(" / ") || "—";
    get("system-uptime").textContent = "运行 " + formatUptime(system.uptime_seconds);
    get("sidebar-uptime").textContent = "运行 " + formatUptime(system.uptime_seconds);
  }
  get("system-temp").textContent = system.temp_exists ? "可用" : "不存在";
  const files = system.temp_files || {};
  get("system-temp-sub").textContent = (system.temp_dir || "—") + " · " + (files.files || 0) + " 个临时文件，" + formatBytes(files.bytes || 0);
  const lowDisk = system.disk && system.disk.free < 1024 * 1024 * 1024;
  get("sidebar-health").textContent = lowDisk ? "磁盘空间偏低" : "服务正常";
  get("sidebar-health").parentElement.style.color = lowDisk ? "var(--amber)" : "var(--text)";
}
function renderConfig() {
  const c = state.config;
  if (!c) return;
  get("config-temp-dir").textContent = c.temp_dir || "—";
  get("config-concurrency").textContent = c.max_concurrent_tasks + " 个媒体组";
  get("config-min-disk").textContent = c.min_free_disk_mb + " MB";
  get("config-cleanup").textContent = c.temp_max_age_hours + " 小时";
  get("config-password").textContent = c.web_password_configured ? "已设置" : "未设置";
  get("config-storage-source").textContent = c.storage_source || "SQLite";
  get("config-auth-ttl").textContent = c.web_auth_ttl_hours + " 小时";
  get("auth-expiry").textContent = authExpiresAt ? "本次登录到期：" + new Date(authExpiresAt * 1000).toLocaleString() : "未启用登录有效期";
}
function renderDeployment() {
  const deployment = state.deployment;
  if (!deployment) return;
  const sources = { environment: "系统环境变量", ".env": ".env", default: "默认值" };
  const labels = { TG_API_ID: "API ID", TG_API_HASH: "API Hash", TG_PHONE: "手机号", TG_BOT_TOKEN: "Bot token", TG_ADMIN_IDS: "管理员 ID", TG_PROXY_URL: "Telegram 代理", DB_PATH: "数据库", SESSION_PATH: "登录会话", WEB_HOST: "监听地址", WEB_PORT: "监听端口" };
  const services = Object.entries(deployment.services || {}).map(([name, status]) => '<div class="config-item"><span class="k">' + (name === "telegram" ? "Telegram" : "Bot") + '</span><span class="v">' + esc(status.message) + '</span></div>');
  const fields = Object.entries(deployment.fields || {}).map(([name, field]) => {
    const value = "value" in field ? (Array.isArray(field.value) ? field.value.join(", ") || "未设置" : field.value) : field.configured ? "已配置" : "未配置";
    return '<div class="config-item"><span class="k">' + esc(labels[name] || name) + '</span><span class="v">' + esc(value) + '</span><span class="sub">来源：' + esc(sources[field.source] || field.source) + '</span></div>';
  });
  get("deployment-panel").innerHTML = services.join("") + fields.join("") + '<div class="config-item"><span class="sub">修改 .env 后重启生效；Telegram 登录使用命令行 login</span></div>';
}
let logsSig = "";
function renderLogs() {
  const logs = state.logs || [];
  get("log-count").textContent = logs.length ? "最近 " + logs.length + " 条" : "";
  const sig = JSON.stringify(logs.slice(0, 20).map((l) => [l.id, l.action, l.result]));
  if (sig === logsSig) return;
  logsSig = sig;
  const el = get("logs");
  if (!logs.length) {
    el.innerHTML = '<div class="empty"><span data-icon="terminal" class="empty-icon"></span>暂无操作记录</div>';
    applyIcons(el);
    return;
  }
  el.innerHTML = logs.slice(0, 20).map((l) => {
    const when = (l.created_at || "").replace("T", " ").slice(5, 16);
    const ok = l.result === "success" || l.result === null || l.result === undefined;
    return '<div class="log-row">'
      + '<div class="log-when">' + esc(when) + "</div>"
      + '<div class="log-body"><div class="log-action ' + (ok ? "ok" : "err") + '">' + esc(l.action || "操作") + '</div><div class="log-detail">' + (l.task_id ? "任务 " + esc(l.task_id) : "") + "</div></div>"
      + '<div class="log-task">' + (l.error ? esc(l.error) : "") + "</div>"
      + "</div>";
  }).join("");
}

/* ---------- refresh ---------- */
async function refresh() {
  const banner = get("banner");
  const requests = [
    ["任务", "/api/tasks"],
    ["系统资源", "/api/system"],
    ["运行配置", "/api/config"],
    ["操作日志", "/api/logs?limit=20"],
    ["启动配置", "/api/deployment"]
  ];
  try {
    const results = await Promise.allSettled(requests.map(([, url]) => apiFetch(url)));
    const failed = [];
    const payloads = [];
    for (let i = 0; i < results.length; i++) {
      const result = results[i];
      if (result.status === "rejected") {
        failed.push(requests[i][0] + "请求失败：" + (result.reason && result.reason.message || "网络错误"));
        payloads.push(null);
        continue;
      }
      if (!result.value.ok) {
        // Older running instances serve these assets before their next restart.
        if (!(requests[i][1] === "/api/deployment" && result.value.status === 404)) {
          failed.push(requests[i][0] + "接口返回 HTTP " + result.value.status);
        }
        payloads.push(null);
        continue;
      }
      try {
        payloads.push(await result.value.json());
      } catch (error) {
        failed.push(requests[i][0] + "响应不是有效 JSON");
        payloads.push(null);
      }
    }

    if (payloads[0] !== null) state.tasks = Array.isArray(payloads[0]) ? payloads[0] : [];
    if (payloads[1] !== null) state.system = payloads[1];
    if (payloads[2] !== null) state.config = payloads[2];
    if (payloads[3] !== null) state.logs = Array.isArray(payloads[3]) ? payloads[3] : [];
    if (payloads[4] !== null) state.deployment = payloads[4];

    const sections = [
      ["任务", renderStats], ["任务列表", renderTasks],
      ["系统资源", renderSystem], ["运行配置", renderConfig], ["启动配置", renderDeployment], ["操作日志", renderLogs]
    ];
    for (const [name, render] of sections) {
      try {
        render();
      } catch (error) {
        failed.push(name + "渲染失败：" + (error && error.message || String(error)));
        console.error("Web UI render failed:", name, error);
      }
    }

    if (failed.length) {
      banner.hidden = false;
      get("banner-text").textContent = failed.join("；");
    } else {
      banner.hidden = true;
    }
    get("last-updated").textContent = new Date().toLocaleTimeString();
  } catch (error) {
    banner.hidden = false;
    get("banner-text").textContent = "刷新失败：" + (error.message || String(error));
    console.error("Web UI refresh failed:", error);
  }
}

/* ---------- task actions ---------- */
function setBusy(button, busy) {
  button.disabled = busy;
  button.classList.toggle("busy", busy);
}

async function runTaskAction(taskId, action) {
  if (action === "errors") { await openErrorsModal(taskId); return; }
  if (action === "edit") { await openTaskModal(taskId); return; }
  if (action === "progress") { await openCheckpointModal(taskId); return; }

  const messages = {
    "delete": ["删除任务", "任务配置、断点和去重记录都会被删除，此操作不可恢复。"],
    "clear-dedup": ["清空去重记录", "清空后将无法识别已经转发过的媒体，可能造成重复转发。"],
    "skip-transfer": ["跳过媒体组", "跳过当前媒体组；断点只越过已完成消息，穿插的其他消息仍会处理。"],
    "cleanup-files": ["清理任务文件", "停止此任务并删除它的临时媒体、未完成文件、封面和缩略图，保留转发断点。"],
    "refresh-transfer": ["从断点重试", "清除当前活动传输和临时文件，任务会从原有断点重新处理未完成的媒体。"]
  };
  if (messages[action]) {
    const [title, message] = messages[action];
    const ok = await askConfirm(title, message, action !== "refresh-transfer");
    if (!ok) return;
  }

  const button = document.querySelector('[data-task="' + CSS.escape(taskId) + '"][data-action="' + action + '"]');
  if (button) setBusy(button, true);
  try {
    let url = "/api/tasks/" + encodeURIComponent(taskId) + "/action";
    let options = { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) };
    if (action === "refresh-transfer") {
      url = "/api/tasks/" + encodeURIComponent(taskId) + "/transfer";
      options = { method: "DELETE" };
    } else if (action === "skip-transfer") {
      url = "/api/tasks/" + encodeURIComponent(taskId) + "/transfer/skip";
      options = { method: "POST" };
    } else if (action === "cleanup-files") {
      url = "/api/tasks/" + encodeURIComponent(taskId) + "/cleanup";
      options = { method: "POST" };
    } else if (action === "clear-dedup") {
      url = "/api/tasks/" + encodeURIComponent(taskId) + "/dedup";
      options = { method: "DELETE" };
    } else if (action === "delete") {
      url = "/api/tasks/" + encodeURIComponent(taskId);
      options = { method: "DELETE" };
    }
    const response = await apiFetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "操作失败");
    showToast(action === "cleanup-files" ? "已删除 " + data.removed + " 个文件，释放 " + formatBytes(data.freed_bytes) : "操作成功");
    await refresh();
  } catch (error) {
    showToast(error.message || "操作失败");
  } finally {
    if (button) setBusy(button, false);
  }
}

get("tasks").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-task][data-action]");
  if (button) runTaskAction(button.dataset.task, button.dataset.action);
});
get("task-chips").addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  taskFilter = chip.dataset.filter;
  renderTasks();
});
get("task-search").addEventListener("input", (event) => {
  taskSearch = event.target.value.trim();
  renderTasks();
});

/* ---------- task form (create / edit 共用) ---------- */
let editingTaskId = null;
let editingTaskRevision = null;
let editingTaskConfig = null;
let editingConfigRevision = null;
function formLines(id) { return get(id).value.split("\n").map((v) => v.trim()).filter(Boolean); }

function updateFormDependencies() {
  const hashtags = formLines("task-form-hashtags");
  const removeSwitch = get("remove-switch");
  const removeInput = get("task-form-remove");
  const sendAs = get("task-form-send-as").checked;
  const hideSwitch = get("task-form-hide").closest(".switch");

  if (!hashtags.length) {
    removeSwitch.classList.add("locked");
    removeInput.disabled = true;
    removeInput.checked = false;
  } else {
    removeSwitch.classList.remove("locked");
    removeInput.disabled = false;
  }
  if (sendAs) {
    hideSwitch.classList.add("locked");
    get("task-form-hide").disabled = true;
  } else {
    hideSwitch.classList.remove("locked");
    get("task-form-hide").disabled = false;
  }

  const min = Number(get("task-form-min").value);
  const hideSource = get("task-form-hide").checked;
  if (!hideSource && (get("task-form-prefix").value || get("task-form-remove").checked || sendAs)) {
    get("task-form-error").textContent = "显示来源时不能修改描述或以频道身份发送";
  }
  const max = Number(get("task-form-max").value);
  const hint = get("delay-hint");
  if (min > max) {
    hint.textContent = "最小延迟不能大于最大延迟";
    hint.className = "hint error";
    get("task-form-max").classList.add("invalid");
  } else {
    get("task-form-max").classList.remove("invalid");
    hint.textContent = "每两条转发之间随机等待 " + (isNaN(min) ? 0 : min) + " - " + (isNaN(max) ? 0 : max) + " 秒";
    hint.className = "hint";
  }
}

function setTaskForm(task) {
  const c = task || {};
  get("task-form-id").value = c.task_id || "";
  get("task-form-note").value = c.note || "";
  get("task-form-source").value = c.source_channel ?? "";
  get("task-form-target").value = c.target_channel ?? "";
  get("task-form-min").value = c.min_delay ?? 10;
  get("task-form-max").value = c.max_delay ?? 20;
  get("task-form-prefix").value = c.caption_prefix || "";
  get("task-form-topic").value = c.target_topic_id ?? "";
  get("task-form-source-topic").value = c.source_topic_id ?? "";
  get("task-form-keywords").value = (c.filter_keywords || []).join("\n");
  get("task-form-hashtags").value = (c.required_hashtags || []).join("\n");
  get("task-form-enabled").checked = c.enabled !== false;
  get("task-form-hide").checked = c.hide_source !== false;
  get("task-form-remove").checked = !!c.remove_hashtags;
  get("task-form-send-as").checked = !!c.send_as_channel;
  get("task-form-dedup").checked = !!c.deduplicate;
  updateFormDependencies();
}

async function openTaskModal(taskId = null) {
  editingTaskId = taskId;
  get("task-modal-title").textContent = taskId ? "编辑任务" : "新建任务";
  get("task-modal-subtitle").textContent = taskId ? "修改任务配置前请先停止该任务" : "创建后即可在列表中启动";
  get("task-form-error").textContent = "";
  try {
    if (taskId) {
      const data = await (await apiFetch("/api/tasks/" + encodeURIComponent(taskId))).json();
      setTaskForm(data.config || {});
      editingTaskRevision = data.revision;
      editingTaskConfig = data.config;
      get("source-reset-options").hidden = false;
      get("source-reset-id").value = 0;
      get("source-reset-dedup").checked = true;
    } else {
      setTaskForm({});
      editingTaskConfig = null;
      get("source-reset-options").hidden = true;
    }
    get("task-form-id").disabled = !!taskId;
    get("task-id-hint").textContent = taskId ? "任务 ID 不可修改，避免断点和去重数据失去关联" : "仅允许字母、数字、下划线和短横线";
    openModal("task-modal");
  } catch (error) {
    showToast("读取任务失败");
  }
}

function validateTaskForm() {
  const id = get("task-form-id").value.trim();
  const source = get("task-form-source").value;
  const target = get("task-form-target").value;
  const min = Number(get("task-form-min").value);
  const max = Number(get("task-form-max").value);
  if (!/^[A-Za-z0-9_-]{1,48}$/.test(id)) return "任务 ID 仅允许字母、数字、下划线和短横线，长度 1-48";
  if (!source || !target) return "源频道和目标频道不能为空";
  const sourceTopic = get("task-form-source-topic").value;
  if (sourceTopic && (!Number.isInteger(Number(sourceTopic)) || Number(sourceTopic) < 1)) return "来源话题 ID 必须是正整数";
  const targetTopic = get("task-form-topic").value;
  if (targetTopic && (!Number.isInteger(Number(targetTopic)) || Number(targetTopic) < 1)) return "目标话题 ID 必须是正整数";
  if (Number(source) === 0 || Number(target) === 0) return "频道 ID 不能为 0，频道通常使用负数 ID";
  if (isNaN(min) || isNaN(max)) return "延迟必须是数字";
  if (min < 0 || max < 0) return "延迟不能为负数";
  if (!get("task-form-hide").checked && (get("task-form-prefix").value || get("task-form-remove").checked || get("task-form-send-as").checked)) return "显示来源时不能修改描述或以频道身份发送";
  if (Number(source) === Number(target)) return "源频道与目标频道不能相同";
  if (min > max) return "最小延迟不能大于最大延迟";
  return null;
}

get("new-task-btn").addEventListener("click", () => openTaskModal());
get("edit-config-btn").addEventListener("click", openConfigModal);
["task-form-min", "task-form-max", "task-form-hashtags", "task-form-send-as"].forEach((id) => {
  get(id).addEventListener("input", updateFormDependencies);
  get(id).addEventListener("change", updateFormDependencies);
});

get("task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = get("task-form-error");
  const submit = get("task-submit");
  error.textContent = "";
  setBusy(submit, true);
  try {
    const validationError = validateTaskForm();
    if (validationError) throw new Error(validationError);

    const taskId = get("task-form-id").value.trim();
    const task = {
      task_id: taskId,
      note: get("task-form-note").value.trim(),
      source_channel: Number(get("task-form-source").value),
      target_channel: Number(get("task-form-target").value),
      source_topic_id: get("task-form-source-topic").value ? Number(get("task-form-source-topic").value) : null,
      min_delay: Number(get("task-form-min").value),
      max_delay: Number(get("task-form-max").value),
      caption_prefix: get("task-form-prefix").value,
      target_topic_id: get("task-form-topic").value ? Number(get("task-form-topic").value) : null,
      filter_keywords: formLines("task-form-keywords"),
      required_hashtags: formLines("task-form-hashtags"),
      enabled: get("task-form-enabled").checked,
      hide_source: get("task-form-hide").checked,
      remove_hashtags: get("task-form-remove").checked,
      send_as_channel: get("task-form-send-as").checked,
      deduplicate: get("task-form-dedup").checked
    };

    let response;
    if (editingTaskId) {
      task.revision = editingTaskRevision;
      if (editingTaskConfig.source_channel !== task.source_channel || (editingTaskConfig.source_topic_id ?? null) !== task.source_topic_id) {
        if (!await askConfirm("更换来源", "将清理旧传输并使用新起点和所选去重设置，确认更换来源？", true)) return;
        task.source_reset = { last_message_id: Number(get("source-reset-id").value), clear_dedup: get("source-reset-dedup").checked };
      }
      response = await apiFetch("/api/tasks/" + encodeURIComponent(editingTaskId), {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(task)
      });
    } else {
      response = await apiFetch("/api/tasks", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(task)
      });
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "保存任务失败");

    closeModal("task-modal");
    showToast(editingTaskId ? "任务已更新" : "任务已创建");
    await refresh();
  } catch (e) {
    error.textContent = e.message || "保存失败";
  } finally {
    setBusy(submit, false);
  }
});

/* ---------- checkpoint modal（只做断点） ---------- */
let checkpointTaskId = null;
async function openCheckpointModal(taskId) {
  checkpointTaskId = taskId;
  get("checkpoint-error").textContent = "";
  try {
    const data = await (await apiFetch("/api/tasks/" + encodeURIComponent(taskId))).json();
    const cfg = data.config || {};
    const prog = data.progress || {};
    get("checkpoint-task-name").textContent = cfg.note || taskId;
    get("checkpoint-task-id").textContent = taskId;
    get("checkpoint-last-id").value = prog.last_message_id ?? 0;
    get("checkpoint-count").value = prog.forwarded_count ?? 0;
    openModal("checkpoint-modal");
  } catch (error) {
    showToast("读取断点失败");
  }
}

get("checkpoint-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = get("checkpoint-error");
  const submit = get("checkpoint-submit");
  error.textContent = "";
  setBusy(submit, true);
  try {
    const response = await apiFetch("/api/tasks/" + encodeURIComponent(checkpointTaskId) + "/progress", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        last_message_id: Number(get("checkpoint-last-id").value) || 0,
        forwarded_count: Number(get("checkpoint-count").value) || 0
      })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "保存断点失败");
    closeModal("checkpoint-modal");
    showToast("断点已保存");
    await refresh();
  } catch (e) {
    error.textContent = e.message || "保存失败";
  } finally {
    setBusy(submit, false);
  }
});

/* ---------- error modal ---------- */
let errorTaskId = null;
const errorStageLabels = {
  telegram_download: "Telegram 下载",
  telegram_upload_send: "Telegram 单文件上传",
  telegram_album_upload: "媒体组单文件上传",
  telegram_album_send: "媒体组发送",
  transfer: "媒体组处理",
};
function errorStageLabel(stage) {
  return errorStageLabels[stage] || stage || "传输处理";
}
function renderErrorList(errors) {
  const list = get("error-list");
  if (!errors.length) {
    list.innerHTML = '<div class="empty"><span data-icon="check" class="empty-icon"></span>暂无错误记录</div>';
    applyIcons(list);
    return;
  }
  list.innerHTML = errors.map((item) => {
    const meta = [];
    if (item.message_id !== null && item.message_id !== undefined) meta.push("消息 " + item.message_id);
    if (item.file_index !== null && item.file_index !== undefined) meta.push("文件 " + item.file_index);
    if (item.filename) meta.push(item.filename);
    if (item.resolved) meta.push("已解决");
    return '<article class="error-item ' + (item.resolved ? "resolved" : "") + '">'
      + '<div class="error-item-head"><span class="error-item-stage">' + esc(errorStageLabel(item.stage)) + '</span><span class="error-item-time">' + esc(fmtTime(item.created_at)) + '</span></div>'
      + (meta.length ? '<div class="error-item-meta">' + esc(meta.join(" · ")) + "</div>" : "")
      + '<pre class="error-item-message">' + esc(item.error || "未知错误") + (item.details ? "\n\n" + esc(item.details) : "") + "</pre>"
      + "</article>";
  }).join("");
}
async function openErrorsModal(taskId) {
  errorTaskId = taskId;
  get("errors-modal-error").textContent = "";
  get("errors-modal-subtitle").textContent = "任务 " + taskId;
  get("error-list").innerHTML = '<div class="empty">正在读取错误记录…</div>';
  openModal("errors-modal");
  try {
    const response = await apiFetch("/api/tasks/" + encodeURIComponent(taskId) + "/errors?limit=200");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "读取错误记录失败");
    renderErrorList(data.errors || []);
  } catch (error) {
    get("errors-modal-error").textContent = error.message || "读取错误记录失败";
  }
}
get("clear-errors-btn").addEventListener("click", async () => {
  if (!errorTaskId) return;
  const ok = await askConfirm("清空错误记录", "只删除这个任务的错误历史，不会修改任务断点。", true);
  if (!ok) return;
  const button = get("clear-errors-btn");
  setBusy(button, true);
  try {
    const response = await apiFetch("/api/tasks/" + encodeURIComponent(errorTaskId) + "/errors", { method: "DELETE" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "清空错误记录失败");
    renderErrorList([]);
    showToast("错误记录已清空");
    await refresh();
  } catch (error) {
    get("errors-modal-error").textContent = error.message || "清空错误记录失败";
  } finally {
    setBusy(button, false);
  }
});

/* ---------- config modal ---------- */
async function openConfigModal() {
  const c = state.config;
  if (!c) { showToast("配置尚未加载"); return; }
  get("config-form-temp").value = c.temp_dir || "";
  get("config-form-concurrency").value = c.max_concurrent_tasks || 1;
  get("config-form-mindisk").value = c.min_free_disk_mb || 0;
  get("config-form-cleanup").value = c.temp_max_age_hours || 0;
  get("config-form-ttl").value = c.web_auth_ttl_hours;
  get("config-form-download").value = c.download_workers;
  get("config-form-upload").value = c.upload_workers;
  editingConfigRevision = c.revision;
  get("config-form-password").value = "";
  get("config-form-error").textContent = "";
  openModal("config-modal");
}

get("config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = get("config-form-error");
  const submit = get("config-submit");
  error.textContent = "";
  setBusy(submit, true);
  const payload = {
    temp_dir: get("config-form-temp").value.trim(),
    max_concurrent_tasks: Number(get("config-form-concurrency").value),
    min_free_disk_mb: Number(get("config-form-mindisk").value),
    temp_max_age_hours: Number(get("config-form-cleanup").value),
    web_auth_ttl_hours: Number(get("config-form-ttl").value),
    download_workers: Number(get("config-form-download").value),
    upload_workers: Number(get("config-form-upload").value),
    revision: editingConfigRevision
  };
  const password = get("config-form-password").value;
  if (password) payload.web_password = password;
  try {
    const response = await apiFetch("/api/config", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (data.error === "stop_all_tasks_before_editing_config") throw new Error("还有任务在运行，请先停止全部任务再修改传输参数");
    if (!response.ok) throw new Error(data.error || "保存配置失败");
    closeModal("config-modal");
    showToast("配置已保存");
    await refresh();
  } catch (e) {
    error.textContent = e.message || "保存失败";
  } finally {
    setBusy(submit, false);
  }
});

get("cleanup-temp-btn").addEventListener("click", async () => {
  if (!await askConfirm("清理临时文件", "删除非活动传输的媒体、未完成文件、缩略图和封面；活动传输保留。删除后失败任务需要重新下载。", true)) return;
  try {
    const response = await apiFetch("/api/cleanup", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "清理失败");
    showToast("已删除 " + data.removed + " 个文件，释放 " + (data.freed_bytes / 1024 / 1024).toFixed(1) + " MB" + (data.errors?.length ? "，部分删除失败" : ""));
    await refresh();
  } catch (error) { showToast(error.message); }
});

/* ---------- navigation ---------- */
document.querySelectorAll(".nav-btn").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    const target = get(button.dataset.target);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

/* ---------- init ---------- */
applyIcons(document);
(async function initialize() {
  if (authToken) { showApp(); return; }
  try {
    const response = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: "" })
    });
    const data = await response.json();
    if (response.ok && data.auth_required === false) showApp();
    else showGate();
  } catch (e) {
    showGate("无法连接到 Web 服务");
  }
})();