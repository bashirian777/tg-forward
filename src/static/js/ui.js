import { get, applyIcons } from "./core.js";

const modalStack = [];
const returnFocus = new Map();
let confirmResolver = null;
let toastTimer;
const focusable =
  'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]';

function syncModals() {
  get("app-content").inert = modalStack.length > 0;
  document.body.classList.toggle("modal-open", modalStack.length > 0);
  modalStack.forEach((modal, i) => {
    modal.inert = i !== modalStack.length - 1;
    modal.style.zIndex = 100 + i;
  });
}
export function openModal(id) {
  const modal = get(id);
  if (modalStack.includes(modal)) return;
  returnFocus.set(id, document.activeElement);
  modal.hidden = false;
  modalStack.push(modal);
  syncModals();
  modal.classList.add("show");
  const heading = modal.querySelector("h2");
  if (heading) {
    heading.id ||= id + "-heading";
    modal.setAttribute("aria-labelledby", heading.id);
  }
  const first =
    modal.querySelector("input:not(:disabled)") || modal.querySelector(focusable) || modal;
  first.focus({ preventScroll: true });
}
export function closeModal(id) {
  const modal = get(id);
  modal.classList.remove("show");
  modal.hidden = true;
  modal.inert = false;
  const index = modalStack.indexOf(modal);
  if (index >= 0) modalStack.splice(index, 1);
  syncModals();
  if (id === "confirm-modal" && confirmResolver) {
    confirmResolver(false);
    confirmResolver = null;
  }
  const previous = returnFocus.get(id);
  if (previous?.isConnected) previous.focus({ preventScroll: true });
  returnFocus.delete(id);
}
export function askConfirm(title, message, danger = true) {
  return new Promise((resolve) => {
    confirmResolver = resolve;
    get("confirm-title").textContent = title;
    get("confirm-message").textContent = message;
    get("confirm-ok").className = "btn " + (danger ? "danger" : "primary");
    openModal("confirm-modal");
  });
}
export function showToast(message) {
  const toast = get("toast");
  get("toast-text").textContent = message;
  toast.hidden = false;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove("show");
    toast.hidden = true;
  }, 3500);
}

const views = {
  tasks: ["转发任务", "管理转发流程，查看实时进度"],
  resources: ["系统资源", "查看磁盘与临时文件的使用情况"],
  settings: ["设置", "管理运行参数与 Telegram 连接"],
  activity: ["操作记录", "查看最近的任务与配置变更"],
};
function navigate() {
  const key = location.hash.slice(1) in views ? location.hash.slice(1) : "tasks";
  document.querySelectorAll("[data-page]").forEach((el) => {
    el.hidden = el.dataset.page !== key;
  });
  document.querySelectorAll("[data-view]").forEach((el) => {
    const active = el.dataset.view === key;
    el.classList.toggle("active", active);
    if (active) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  get("page-title").textContent = views[key][0];
  get("page-description").textContent = views[key][1];
  document.title = views[key][0] + " · Forwarder";
}
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  get("theme-btn").innerHTML =
    '<span data-icon="' + (theme === "dark" ? "sun" : "moon") + '"></span>';
  get("theme-btn").setAttribute("aria-label", theme === "dark" ? "切换浅色主题" : "切换深色主题");
  applyIcons(get("theme-btn"));
}
export function initUI() {
  applyIcons(document);
  const stored = localStorage.getItem("theme");
  setTheme(
    stored === "light" || stored === "dark"
      ? stored
      : matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light",
  );
  get("theme-btn").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("theme", next);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      location.hash = button.dataset.view;
    });
  });
  window.addEventListener("hashchange", navigate);
  navigate();
  document.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", () => closeModal(button.dataset.close));
  });
  document.querySelectorAll(".modal").forEach((modal) => {
    modal.addEventListener("click", (event) => {
      if (event.target === modal) closeModal(modal.id);
    });
  });
  get("confirm-ok").addEventListener("click", () => {
    const resolve = confirmResolver;
    confirmResolver = null;
    closeModal("confirm-modal");
    resolve?.(true);
  });
  document.addEventListener("auth:required", () => {
    [...modalStack].reverse().forEach((modal) => closeModal(modal.id));
  });
  document.addEventListener("keydown", (event) => {
    const modal = modalStack.at(-1);
    if (!modal) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeModal(modal.id);
    }
    if (event.key === "Tab") {
      const items = [...modal.querySelectorAll(focusable)].filter(
        (el) => el.getClientRects().length && !el.closest("[hidden]"),
      );
      const first = items[0],
        last = items.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  });
  document.addEventListener("click", (event) => {
    document.querySelectorAll(".task-menu[open]").forEach((menu) => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
}
