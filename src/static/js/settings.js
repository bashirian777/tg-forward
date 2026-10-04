import { esc, get, state, requestRefresh, setBusy } from "./core.js";
import { apiFetch, session } from "./api.js";
import { openModal, closeModal, askConfirm, showToast } from "./ui.js";

let editingConfigRevision = null;
export function renderConfig() {
  const c = state.config;
  if (!c) return;
  get("config-temp-dir").textContent = c.temp_dir || "—";
  get("config-concurrency").textContent = c.max_concurrent_tasks + " 个媒体组";
  get("config-workers").textContent = c.download_workers + " / " + c.upload_workers;
  get("config-min-disk").textContent = c.min_free_disk_mb + " MB";
  get("config-cleanup").textContent = c.temp_max_age_hours + " 小时";
  get("config-password").textContent = c.web_password_configured ? "已设置" : "未设置";
  get("config-storage-source").textContent = c.storage_source || "SQLite";
  get("config-auth-ttl").textContent = c.web_auth_ttl_hours + " 小时";
  get("auth-expiry").textContent = session.expiresAt
    ? "本次登录到期：" + new Date(session.expiresAt * 1000).toLocaleString("zh-CN", { hour12: false })
    : "未启用登录有效期";
}
export function renderDeployment() {
  const deployment = state.deployment;
  if (!deployment) return;
  const sources = { environment: "系统环境变量", ".env": ".env", default: "默认值" };
  const labels = {
    TG_API_ID: "API ID",
    TG_API_HASH: "API Hash",
    TG_PHONE: "手机号",
    TG_BOT_TOKEN: "Bot token",
    TG_ADMIN_IDS: "管理员 ID",
    TG_PROXY_URL: "Telegram 代理",
    DB_PATH: "数据库",
    SESSION_PATH: "登录会话",
    WEB_HOST: "监听地址",
    WEB_PORT: "监听端口",
  };
  get("connection-panel").innerHTML = Object.entries(deployment.services || {})
    .map(([name, status]) => {
      const color =
        status.state === "ready"
          ? "var(--green)"
          : status.state === "disabled"
            ? "var(--faint)"
            : "var(--amber)";
      return `<div class="connection-item"><div class="connection-title"><span class="dot" style="background:${color}"></span>${name === "telegram" ? "Telegram 用户账号" : "管理 Bot"}</div><p>${esc(status.message)}</p></div>`;
    })
    .join("");
  const telegram = deployment.services?.telegram;
  if (telegram && telegram.state !== "ready") {
    get("sidebar-health").textContent = telegram.message || "Telegram 未连接";
    get("health-dot").style.background = "var(--amber)";
  }
  const fields = Object.entries(deployment.fields || {}).map(([name, field]) => {
    const value =
      "value" in field
        ? Array.isArray(field.value)
          ? field.value.join(", ") || "未设置"
          : field.value
        : field.configured
          ? "已配置"
          : "未配置";
    return (
      '<div class="config-item"><span class="k">' +
      esc(labels[name] || name) +
      '</span><span class="v">' +
      esc(value) +
      '</span><span class="sub">来源：' +
      esc(sources[field.source] || field.source) +
      "</span></div>"
    );
  });
  get("deployment-panel").innerHTML = fields.join("");
}
/* ---------- config modal ---------- */
async function openConfigModal() {
  const c = state.config;
  if (!c) {
    showToast("配置尚未加载");
    return;
  }
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

export function initSettings() {
  get("edit-config-btn").addEventListener("click", openConfigModal);
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
      revision: editingConfigRevision,
    };
    const password = get("config-form-password").value;
    if (password) payload.web_password = password;
    try {
      const response = await apiFetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (data.error === "stop_all_tasks_before_editing_config")
        throw new Error("还有任务在运行，请先停止全部任务再修改传输参数");
      if (!response.ok) throw new Error(data.error || "保存配置失败");
      closeModal("config-modal");
      showToast("配置已保存");
      requestRefresh();
    } catch (e) {
      error.textContent = e.message || "保存失败";
    } finally {
      setBusy(submit, false);
    }
  });

  get("cleanup-temp-btn").addEventListener("click", async () => {
    if (
      !(await askConfirm(
        "清理临时文件",
        "删除非活动传输的媒体、未完成文件、缩略图和封面；活动传输保留。删除后失败任务需要重新下载。",
        true,
      ))
    )
      return;
    try {
      const response = await apiFetch("/api/cleanup", { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "清理失败");
      showToast(
        "已删除 " +
          data.removed +
          " 个文件，释放 " +
          (data.freed_bytes / 1024 / 1024).toFixed(1) +
          " MB" +
          (data.errors?.length ? "，部分删除失败" : ""),
      );
      requestRefresh();
    } catch (error) {
      showToast(error.message);
    }
  });
}
