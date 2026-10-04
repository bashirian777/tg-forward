import { get, state, setBusy } from "./js/core.js";
import { apiFetch, session, initAuth } from "./js/api.js";
import { initUI } from "./js/ui.js";
import { initTasks, renderStats, renderTasks } from "./js/tasks.js";
import { initTaskForm } from "./js/task-form.js";
import { initTaskDialogs } from "./js/task-dialogs.js";
import { initSettings, renderConfig, renderDeployment } from "./js/settings.js";
import { renderSystem, renderLogs } from "./js/monitor.js";

const endpoints = [
  ["tasks", "任务", "/api/tasks"],
  ["system", "系统资源", "/api/system"],
  ["config", "运行设置", "/api/config"],
  ["logs", "操作记录", "/api/logs?limit=20"],
  ["deployment", "连接状态", "/api/deployment"],
];
let timer;
let refreshing = false;
let pending = false;

async function refresh() {
  if (!session.ready || document.hidden) return;
  if (refreshing) {
    pending = true;
    return;
  }
  clearTimeout(timer);
  refreshing = true;
  setBusy(get("refresh-btn"), true);
  const failed = [];
  try {
    const results = await Promise.allSettled(
      endpoints.map(async ([key, , url]) => {
        const response = await apiFetch(url);
        if (!response.ok) throw new Error("HTTP " + response.status);
        const data = await response.json();
        if ((key === "tasks" || key === "logs") && !Array.isArray(data))
          throw new Error("响应格式不正确");
        return data;
      }),
    );
    if (!session.ready) return;
    results.forEach((result, i) => {
      if (result.status === "fulfilled") state[endpoints[i][0]] = result.value;
      else failed.push(endpoints[i][1] + "：" + (result.reason.message || "请求失败"));
    });
    for (const render of [
      renderStats,
      renderTasks,
      renderSystem,
      renderConfig,
      renderDeployment,
      renderLogs,
    ]) {
      try {
        render();
      } catch (error) {
        console.error("界面更新失败", error);
        failed.push("部分内容无法显示");
      }
    }
    if (!failed.length) get("last-updated").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  } finally {
    refreshing = false;
    setBusy(get("refresh-btn"), false);
    get("banner").hidden = !failed.length;
    get("banner-text").textContent = failed.length
      ? "部分数据未更新，保留上次结果。" + failed.join("；")
      : "";
    get("refresh-status").textContent = failed.length ? "更新失败" : "自动更新";
    get("refresh-status").classList.toggle("has-error", !!failed.length);
    if (session.ready && !document.hidden) {
      timer = setTimeout(refresh, pending ? 0 : 5000);
      pending = false;
    }
  }
}

initUI();
initTasks();
initTaskForm();
initTaskDialogs();
initSettings();
get("refresh-btn").addEventListener("click", refresh);
document.addEventListener("data:changed", refresh);
document.addEventListener("auth:ready", refresh);
document.addEventListener("auth:required", () => {
  clearTimeout(timer);
  pending = false;
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(timer);
  else refresh();
});
initAuth();
