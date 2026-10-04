import { applyIcons, esc, get, fmtTime, requestRefresh, setBusy } from "./core.js";
import { apiFetch } from "./api.js";
import { openModal, closeModal, askConfirm, showToast } from "./ui.js";

/* ---------- checkpoint modal（只做断点） ---------- */
let checkpointTaskId = null;
export async function openCheckpointModal(taskId) {
  checkpointTaskId = taskId;
  get("checkpoint-error").textContent = "";
  try {
    const response = await apiFetch("/api/tasks/" + encodeURIComponent(taskId));
    if (!response.ok) throw new Error("读取断点失败");
    const data = await response.json();
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
    list.innerHTML =
      '<div class="empty"><span data-icon="check" class="empty-icon"></span>暂无错误记录</div>';
    applyIcons(list);
    return;
  }
  list.innerHTML = errors
    .map((item) => {
      const meta = [];
      if (item.message_id !== null && item.message_id !== undefined)
        meta.push("消息 " + item.message_id);
      if (item.file_index !== null && item.file_index !== undefined)
        meta.push("文件 " + item.file_index);
      if (item.filename) meta.push(item.filename);
      if (item.resolved) meta.push("已解决");
      return (
        '<article class="error-item ' +
        (item.resolved ? "resolved" : "") +
        '">' +
        '<div class="error-item-head"><span class="error-item-stage">' +
        esc(errorStageLabel(item.stage)) +
        '</span><span class="error-item-time">' +
        esc(fmtTime(item.created_at)) +
        "</span></div>" +
        (meta.length ? '<div class="error-item-meta">' + esc(meta.join(" · ")) + "</div>" : "") +
        '<pre class="error-item-message">' +
        esc(item.error || "未知错误") +
        (item.details ? "\n\n" + esc(item.details) : "") +
        "</pre>" +
        "</article>"
      );
    })
    .join("");
}
export async function openErrorsModal(taskId) {
  errorTaskId = taskId;
  get("errors-modal-error").textContent = "";
  get("errors-modal-subtitle").textContent = "任务 " + taskId;
  get("error-list").innerHTML = '<div class="empty">正在读取错误记录…</div>';
  openModal("errors-modal");
  try {
    const response = await apiFetch(
      "/api/tasks/" + encodeURIComponent(taskId) + "/errors?limit=200",
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "读取错误记录失败");
    renderErrorList(data.errors || []);
  } catch (error) {
    get("errors-modal-error").textContent = error.message || "读取错误记录失败";
  }
}

export function initTaskDialogs() {
  get("checkpoint-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = get("checkpoint-error");
    const submit = get("checkpoint-submit");
    error.textContent = "";
    setBusy(submit, true);
    try {
      const response = await apiFetch(
        "/api/tasks/" + encodeURIComponent(checkpointTaskId) + "/progress",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            last_message_id: Number(get("checkpoint-last-id").value) || 0,
            forwarded_count: Number(get("checkpoint-count").value) || 0,
          }),
        },
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "保存断点失败");
      closeModal("checkpoint-modal");
      showToast("断点已保存");
      requestRefresh();
    } catch (e) {
      error.textContent = e.message || "保存失败";
    } finally {
      setBusy(submit, false);
    }
  });

  get("clear-errors-btn").addEventListener("click", async () => {
    if (!errorTaskId) return;
    const ok = await askConfirm(
      "清空错误记录",
      "只删除这个任务的错误历史，不会修改任务断点。",
      true,
    );
    if (!ok) return;
    const button = get("clear-errors-btn");
    setBusy(button, true);
    try {
      const response = await apiFetch("/api/tasks/" + encodeURIComponent(errorTaskId) + "/errors", {
        method: "DELETE",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "清空错误记录失败");
      renderErrorList([]);
      showToast("错误记录已清空");
      requestRefresh();
    } catch (error) {
      get("errors-modal-error").textContent = error.message || "清空错误记录失败";
    } finally {
      setBusy(button, false);
    }
  });
}
