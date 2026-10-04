import {
  ICONS,
  get,
  esc,
  applyIcons,
  fmtTime,
  formatBytes,
  state,
  requestRefresh,
  setBusy,
} from "./core.js";
import { apiFetch } from "./api.js";
import { askConfirm, showToast } from "./ui.js";
import { openTaskModal } from "./task-form.js";
import { openCheckpointModal, openErrorsModal } from "./task-dialogs.js";

let filter = "all";
let search = "";
const cards = new Map();
const statusLabels = { running: "运行中", paused: "已暂停", stopped: "已停止", error: "发生错误" };
const transferLabels = {
  error: "传输失败",
  interrupted: "已中断",
  fetching: "等待处理",
  waiting_disk: "等待磁盘空间",
  sending: "等待发送确认",
  downloading: "下载中",
  uploading: "上传中",
};

function button(task, action, label, icon, className = "") {
  return `<button type="button" class="btn ${className}" data-task="${esc(task.task_id)}" data-action="${action}">${ICONS[icon]}<span>${label}</span></button>`;
}
function transferStrip(d) {
  const percent = Math.max(0, Math.min(100, Number(d.percent) || 0));
  return `<div class="transfer-strip ${d.state === "error" ? "has-error" : ""}">
    <div class="transfer-heading"><span class="transfer-type">${ICONS[d.type === "upload" ? "up" : "down"]}${transferLabels[d.state] || "等待处理"}</span><span class="transfer-percent">${percent.toFixed(1)}%</span></div>
    <div class="transfer-filename" title="${esc(d.filename)}">${esc(d.filename || "正在准备媒体")}</div>
    <div class="progress" role="progressbar" aria-label="文件传输进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><div class="fill ${d.type === "upload" ? "up" : "down"}" style="width:${percent}%"></div></div>
    <div class="transfer-meta"><span>文件 ${Number(d.file_index) || 1} / ${Number(d.total_files) || 1}</span><span>${esc(d.current_str || "0 B")} / ${esc(d.total_str || "—")}</span><span>${esc(d.speed_str || "计算速度中")}</span></div>
  </div>`;
}
function taskCard(t) {
  const c = t.config || {},
    p = t.progress || {};
  const status = t.status in statusLabels ? t.status : "stopped";
  const action = status === "running" ? "pause" : status === "paused" ? "resume" : "start";
  const errors = Number(t.errors?.unresolved) || 0;
  const rules = [];
  if (c.source_topic_id) rules.push("来源话题 " + c.source_topic_id);
  if (c.target_topic_id) rules.push("目标话题 " + c.target_topic_id);
  if (c.filter_keywords?.length) rules.push("过滤：" + c.filter_keywords.join("、"));
  if (c.required_hashtags?.length) rules.push("标签：" + c.required_hashtags.join("、"));
  if (c.send_as_channel) rules.push("以频道身份发送");
  if (c.deduplicate) rules.push("文件去重");
  let menu = button(t, "progress", "修改断点", "flag", "menu-action");
  if (t.status === "running" || t.status === "paused")
    menu += button(t, "stop", "停止任务", "stop", "menu-action");
  if (t.transfer)
    menu +=
      button(t, "refresh-transfer", "从断点重试", "refresh", "menu-action") +
      button(t, "skip-transfer", "跳过媒体组", "skip", "menu-action");
  menu +=
    '<div class="menu-divider"></div>' +
    button(t, "cleanup-files", "清理任务文件", "trash", "menu-action danger") +
    button(t, "clear-dedup", "清空去重记录", "eraser", "menu-action danger") +
    button(t, "delete", "删除任务", "trash", "menu-action danger");
  return `<article class="card task-card" data-card-id="${esc(t.task_id)}">
    <div class="task-head"><div class="task-main"><div class="task-avatar">${ICONS.send}</div><div><h3 class="task-title">${esc(c.note || t.task_id)}</h3><span class="task-id">${esc(t.task_id)}</span></div></div>
      <div class="task-badges"><span class="badge ${status}"><span class="dot"></span>${statusLabels[status]}</span>${c.enabled === false ? '<span class="badge off">已禁用</span>' : ""}</div></div>
    <div class="route"><div><span class="route-label">来源频道</span><code>${esc(c.source_channel ?? "—")}</code></div>${ICONS.arrow}<div><span class="route-label">目标频道</span><code>${esc(c.target_channel ?? "—")}</code></div></div>
    <div class="task-meta"><div><span class="k">已转发</span><span class="v">${Number(p.forwarded_count) || 0}<small> 条</small></span></div><div><span class="k">当前断点</span><span class="v mono">${esc(p.last_message_id ?? 0)}</span></div><div><span class="k">转发间隔</span><span class="v">${esc(c.min_delay ?? 0)}–${esc(c.max_delay ?? 0)}<small> 秒</small></span></div><div><span class="k">最后转发</span><span class="v">${fmtTime(p.last_forward_time)}</span></div></div>
    ${rules.length ? `<details class="task-rules"><summary>转发规则 <span>${rules.length} 项</span></summary><div class="tags">${rules.map((rule) => `<span class="tag">${esc(rule)}</span>`).join("")}</div></details>` : ""}
    ${t.transfer ? transferStrip(t.transfer) : ""}
    <div class="task-actions"><div class="task-secondary">${errors ? button(t, "errors", `查看错误 <span class="error-count">${errors}</span>`, "alert", "error-button") : '<span class="task-ready">' + (c.enabled === false ? "任务已禁用" : status === "stopped" ? "等待启动" : status === "paused" ? "可从当前断点继续" : "正在处理来源消息") + "</span>"}</div><div class="task-buttons">${button(t, "edit", "编辑", "edit")}${button(t, action, { start: "启动任务", pause: "暂停", resume: "继续任务" }[action], action === "start" ? "play" : action, "primary")}
    <details class="task-menu"><summary aria-label="更多任务操作" title="更多操作">${ICONS.more}</summary><div class="menu-panel">${menu}</div></details></div></div>
  </article>`;
}
export function renderStats() {
  get("stat-total").textContent = state.tasks.length;
  get("stat-running").textContent = state.tasks.filter((t) => t.status === "running").length;
  get("stat-paused").textContent = state.tasks.filter((t) => t.status === "paused").length;
  get("stat-forwarded").textContent = state.tasks
    .reduce((sum, t) => sum + (Number(t.progress?.forwarded_count) || 0), 0)
    .toLocaleString();
  get("task-count").textContent = state.tasks.length + " 个任务";
}
export function renderTasks() {
  document.querySelectorAll("#task-chips .chip").forEach((chip) => {
    const active = chip.dataset.filter === filter;
    chip.classList.toggle("active", active);
    chip.setAttribute("aria-pressed", String(active));
  });
  const visible = state.tasks.filter((t) => {
    const matches =
      filter === "all" ||
      (filter === "transfer"
        ? !!t.transfer
        : filter === "disabled"
          ? t.config?.enabled === false
          : t.status === filter);
    return (
      matches &&
      [t.task_id, t.config?.note, t.config?.source_channel, t.config?.target_channel]
        .join(" ")
        .toLowerCase()
        .includes(search)
    );
  });
  const container = get("tasks");
  get("task-results").textContent =
    visible.length === state.tasks.length
      ? ""
      : `显示 ${visible.length} / ${state.tasks.length} 个任务`;
  if (!visible.length) {
    container.innerHTML = `<div class="empty"><span class="empty-icon" data-icon="${state.tasks.length ? "search" : "layers"}"></span><h3>${state.tasks.length ? "没有匹配的任务" : "创建第一个转发任务"}</h3><p>${state.tasks.length ? "试试其他关键词或筛选条件" : "选择来源与目标频道，开始自动转发"}</p></div>`;
    applyIcons(container);
    cards.clear();
    return;
  }
  container.querySelectorAll(".empty, .loading-state").forEach((el) => el.remove());
  const present = new Set(visible.map((t) => t.task_id));
  for (const [id, card] of cards) {
    if (!present.has(id)) {
      card.el.remove();
      cards.delete(id);
    }
  }
  visible.forEach((task, index) => {
    const signature = JSON.stringify(task);
    let card = cards.get(task.task_id);
    if (!card || card.signature !== signature) {
      const template = document.createElement("template");
      template.innerHTML = taskCard(task);
      const next = template.content.firstElementChild;
      if (card) {
        next
          .querySelector(".task-rules")
          ?.toggleAttribute("open", !!card.el.querySelector(".task-rules[open]"));
        next.querySelector(".task-menu").open = !!card.el.querySelector(".task-menu[open]");
        const focusedAction = card.el.contains(document.activeElement)
          ? document.activeElement.dataset.action
          : null;
        card.el.replaceWith(next);
        if (focusedAction)
          next.querySelector(`[data-action="${focusedAction}"]`)?.focus({ preventScroll: true });
      }
      card = { el: next, signature };
      cards.set(task.task_id, card);
    }
    if (container.children[index] !== card.el)
      container.insertBefore(card.el, container.children[index] || null);
  });
}
async function runTaskAction(taskId, action) {
  if (action === "errors") return openErrorsModal(taskId);
  if (action === "edit") return openTaskModal(taskId);
  if (action === "progress") return openCheckpointModal(taskId);
  const confirmations = {
    delete: ["删除任务", "任务配置、断点和去重记录都会被删除，此操作不可恢复。"],
    "clear-dedup": ["清空去重记录", "清空后将无法识别已经转发过的媒体，可能造成重复转发。"],
    "skip-transfer": [
      "跳过媒体组",
      "跳过当前媒体组；断点只越过已完成消息，穿插的其他消息仍会处理。",
    ],
    "cleanup-files": [
      "清理任务文件",
      "停止此任务并删除它的临时媒体、未完成文件、封面和缩略图，保留转发断点。",
    ],
    "refresh-transfer": [
      "从断点重试",
      "清除当前活动传输和临时文件，任务会从原有断点重新处理未完成的媒体。",
    ],
  };
  if (
    confirmations[action] &&
    !(await askConfirm(...confirmations[action], action !== "refresh-transfer"))
  )
    return;
  const control = document.querySelector(
    `[data-task="${CSS.escape(taskId)}"][data-action="${action}"]`,
  );
  if (control) setBusy(control, true);
  try {
    const base = "/api/tasks/" + encodeURIComponent(taskId);
    const routes = {
      "refresh-transfer": [base + "/transfer", "DELETE"],
      "skip-transfer": [base + "/transfer/skip", "POST"],
      "cleanup-files": [base + "/cleanup", "POST"],
      "clear-dedup": [base + "/dedup", "DELETE"],
      delete: [base, "DELETE"],
    };
    const [url, method] = routes[action] || [base + "/action", "POST"];
    const response = await apiFetch(url, {
      method,
      ...(routes[action]
        ? {}
        : { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "操作失败");
    showToast(
      action === "cleanup-files"
        ? `已删除 ${data.removed} 个文件，释放 ${formatBytes(data.freed_bytes)}`
        : "操作成功",
    );
    requestRefresh();
  } catch (error) {
    showToast(error.message || "操作失败");
  } finally {
    if (control) setBusy(control, false);
  }
}
export function initTasks() {
  get("tasks").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-task][data-action]");
    if (!button) return;
    const menu = button.closest("details");
    if (menu) menu.open = false;
    runTaskAction(button.dataset.task, button.dataset.action);
  });
  get("task-chips").addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (chip) {
      filter = chip.dataset.filter;
      renderTasks();
    }
  });
  get("task-search").addEventListener("input", (event) => {
    search = event.target.value.trim().toLowerCase();
    renderTasks();
  });
}
