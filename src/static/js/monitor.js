import { get, esc, applyIcons, formatBytes, formatUptime, state } from "./core.js";

export function renderSystem() {
  const system = state.system;
  if (!system) return;
  if (system.disk) {
    get("system-disk").textContent = formatBytes(system.disk.free) + " 可用";
    get("system-disk-sub").textContent =
      formatBytes(system.disk.used) +
      " / " +
      formatBytes(system.disk.total) +
      " · " +
      system.disk.percent +
      "% 已用";
    get("disk-fill").style.width =
      Math.max(0, Math.min(100, Number(system.disk.percent) || 0)) + "%";
    get("system-load").textContent = (system.load_average || []).join(" / ") || "—";
    get("system-uptime").textContent = "运行 " + formatUptime(system.uptime_seconds);
    get("sidebar-uptime").textContent = "运行 " + formatUptime(system.uptime_seconds);
  }
  get("system-temp").textContent = system.temp_exists ? "可用" : "不存在";
  const files = system.temp_files || {};
  get("system-temp-sub").textContent =
    (system.temp_dir || "—") +
    " · " +
    (files.files || 0) +
    " 个临时文件，" +
    formatBytes(files.bytes || 0);
  const lowDisk =
    system.disk && system.disk.free < (Number(state.config?.min_free_disk_mb) || 0) * 1024 * 1024;
  get("sidebar-health").textContent = lowDisk ? "磁盘空间偏低" : "服务已连接";
  get("health-dot").style.background = lowDisk ? "var(--amber)" : "var(--green)";
}
let logsSig = "";
export function renderLogs() {
  const logs = state.logs || [];
  get("log-count").textContent = logs.length ? "最近 " + logs.length + " 条" : "";
  const sig = JSON.stringify(logs);
  if (sig === logsSig) return;
  logsSig = sig;
  const el = get("logs");
  if (!logs.length) {
    el.innerHTML =
      '<div class="empty"><span data-icon="terminal" class="empty-icon"></span>暂无操作记录</div>';
    applyIcons(el);
    return;
  }
  el.innerHTML = logs
    .slice(0, 20)
    .map((l) => {
      const when = (l.created_at || "").replace("T", " ").slice(5, 16);
      const ok = l.result === "success" || l.result === null || l.result === undefined;
      return (
        '<div class="log-row">' +
        '<div class="log-when">' +
        esc(when) +
        "</div>" +
        '<div class="log-body"><div class="log-action ' +
        (ok ? "ok" : "err") +
        '">' +
        esc(l.action || "操作") +
        '</div><div class="log-detail">' +
        (l.task_id ? "任务 " + esc(l.task_id) : "") +
        "</div></div>" +
        '<div class="log-task">' +
        (l.error ? esc(l.error) : "") +
        "</div>" +
        "</div>"
      );
    })
    .join("");
}
