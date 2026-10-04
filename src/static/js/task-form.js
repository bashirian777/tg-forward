import { get, requestRefresh, setBusy } from "./core.js";
import { apiFetch } from "./api.js";
import { openModal, closeModal, askConfirm, showToast } from "./ui.js";

/* ---------- task form (create / edit 共用) ---------- */
let editingTaskId = null;
let editingTaskRevision = null;
let editingTaskConfig = null;
function formLines(id) {
  return get(id)
    .value.split("\n")
    .map((v) => v.trim())
    .filter(Boolean);
}

function updateFormDependencies() {
  const sourceChanged =
    editingTaskConfig &&
    (Number(get("task-form-source").value) !== editingTaskConfig.source_channel ||
      (Number(get("task-form-source-topic").value) || null) !==
        (editingTaskConfig.source_topic_id ?? null));
  get("source-reset-options").hidden = !sourceChanged;
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
    hint.textContent =
      "每两条转发之间随机等待 " + (isNaN(min) ? 0 : min) + " - " + (isNaN(max) ? 0 : max) + " 秒";
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

export async function openTaskModal(taskId = null) {
  editingTaskId = taskId;
  get("task-modal-title").textContent = taskId ? "编辑任务" : "新建任务";
  get("task-modal-subtitle").textContent = taskId
    ? "修改任务配置前请先停止该任务"
    : "创建后即可在列表中启动";
  get("task-form-error").textContent = "";
  try {
    if (taskId) {
      const response = await apiFetch("/api/tasks/" + encodeURIComponent(taskId));
      if (!response.ok) throw new Error("读取任务失败");
      const data = await response.json();
      editingTaskRevision = data.revision;
      editingTaskConfig = data.config;
      setTaskForm(data.config || {});
      get("source-reset-id").value = 0;
      get("source-reset-dedup").checked = true;
    } else {
      editingTaskConfig = null;
      setTaskForm({});
      get("source-reset-options").hidden = true;
    }
    get("task-advanced").open = !!taskId;
    get("task-form-id").disabled = !!taskId;
    get("task-id-hint").textContent = taskId
      ? "任务 ID 不可修改，避免断点和去重数据失去关联"
      : "仅允许字母、数字、下划线和短横线";
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
  if (!/^[A-Za-z0-9_-]{1,48}$/.test(id))
    return "任务 ID 仅允许字母、数字、下划线和短横线，长度 1-48";
  if (!source || !target) return "源频道和目标频道不能为空";
  const sourceTopic = get("task-form-source-topic").value;
  if (sourceTopic && (!Number.isInteger(Number(sourceTopic)) || Number(sourceTopic) < 1))
    return "来源话题 ID 必须是正整数";
  const targetTopic = get("task-form-topic").value;
  if (targetTopic && (!Number.isInteger(Number(targetTopic)) || Number(targetTopic) < 1))
    return "目标话题 ID 必须是正整数";
  if (Number(source) === 0 || Number(target) === 0) return "频道 ID 不能为 0，频道通常使用负数 ID";
  if (isNaN(min) || isNaN(max)) return "延迟必须是数字";
  if (min < 0 || max < 0) return "延迟不能为负数";
  if (
    !get("task-form-hide").checked &&
    (get("task-form-prefix").value ||
      get("task-form-remove").checked ||
      get("task-form-send-as").checked)
  )
    return "显示来源时不能修改描述或以频道身份发送";
  if (Number(source) === Number(target)) return "源频道与目标频道不能相同";
  if (min > max) return "最小延迟不能大于最大延迟";
  return null;
}

export function initTaskForm() {
  get("new-task-btn").addEventListener("click", () => openTaskModal());
  [
    "task-form-min",
    "task-form-max",
    "task-form-hashtags",
    "task-form-send-as",
    "task-form-source",
    "task-form-source-topic",
    "task-form-hide",
    "task-form-prefix",
    "task-form-remove",
  ].forEach((id) => {
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
        source_topic_id: get("task-form-source-topic").value
          ? Number(get("task-form-source-topic").value)
          : null,
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
        deduplicate: get("task-form-dedup").checked,
      };

      let response;
      if (editingTaskId) {
        task.revision = editingTaskRevision;
        if (
          editingTaskConfig.source_channel !== task.source_channel ||
          (editingTaskConfig.source_topic_id ?? null) !== task.source_topic_id
        ) {
          if (
            !(await askConfirm(
              "更换来源",
              "将清理旧传输并使用新起点和所选去重设置，确认更换来源？",
              true,
            ))
          )
            return;
          task.source_reset = {
            last_message_id: Number(get("source-reset-id").value),
            clear_dedup: get("source-reset-dedup").checked,
          };
        }
        response = await apiFetch("/api/tasks/" + encodeURIComponent(editingTaskId), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(task),
        });
      } else {
        response = await apiFetch("/api/tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(task),
        });
      }
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "保存任务失败");

      closeModal("task-modal");
      showToast(editingTaskId ? "任务已更新" : "任务已创建");
      requestRefresh();
    } catch (e) {
      error.textContent = e.message || "保存失败";
    } finally {
      setBusy(submit, false);
    }
  });
}
