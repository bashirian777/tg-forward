/* Browser regression checks. API requests are mocked; no live tasks or settings are changed. */
const { chromium } = require("playwright-core");
const { spawn } = require("node:child_process");
const { once } = require("node:events");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const screenshotDir = process.env.UI_SCREENSHOT_DIR || "/tmp/tg-forward-ui-check";
const tasks = [
  { task_id: "daily", status: "running", revision: 2, config: { task_id: "daily", note: "每日精选 · 视频转发", source_channel: -100111222333, target_channel: -100444555666, min_delay: 10, max_delay: 20, enabled: true, hide_source: true, required_hashtags: ["纪录片", "科普"], deduplicate: true }, progress: { forwarded_count: 1234, last_message_id: 8012, last_forward_time: new Date().toISOString() }, transfer: { type: "download", state: "downloading", filename: "地球脉动第三季·第六集：共同生存之路（4K修复版）.mp4", percent: 62.4, current_str: "1.2 GB", total_str: "1.9 GB", speed_str: "8.6 MB/s", file_index: 1, total_files: 3 }, errors: { unresolved: 0 } },
  { task_id: "archive", status: "stopped", revision: 3, config: { task_id: "archive", note: "资料归档", source_channel: -100777888999, target_channel: -100222333444, min_delay: 5, max_delay: 15, enabled: true, hide_source: true, filter_keywords: ["广告"] }, progress: { forwarded_count: 86, last_message_id: 402, last_forward_time: new Date(Date.now() - 7200000).toISOString() }, errors: { unresolved: 2 } },
  { task_id: "paused", status: "paused", revision: 1, config: { task_id: "paused", note: "稍后继续的转发任务", source_channel: -100111, target_channel: -100222, min_delay: 10, max_delay: 20, enabled: true, hide_source: true }, progress: { forwarded_count: 320, last_message_id: 1040 }, errors: { unresolved: 0 } },
];
const config = { revision: 4, temp_dir: "/var/lib/tg-forward/temp", max_concurrent_tasks: 1, min_free_disk_mb: 1024, temp_max_age_hours: 24, download_workers: 4, upload_workers: 4, web_auth_ttl_hours: 24, web_password_configured: true, storage_source: "SQLite" };
let expired = false, failTasks = false;
const writes = [];
let browser, server;

async function setup(context) {
  await context.route("**/api/**", async (route) => {
    const request = route.request(), url = new URL(request.url()), method = request.method();
    const body = request.postDataJSON() || {};
    const send = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (url.pathname === "/api/auth") return body.password === "测试密码" ? send({ token: "browser-test-token", expires_at: Date.now() / 1000 + 86400 }) : send({ error: "invalid_password" }, 401);
    if (expired) return send({ error: "unauthorized" }, 401);
    if (method !== "GET") writes.push({ path: url.pathname, method, body });
    if (url.pathname === "/api/tasks") {
      if (method === "POST") { tasks.push({ task_id: body.task_id, status: "stopped", config: body, progress: {}, revision: 1 }); return send({ success: true }); }
      return failTasks ? send({ error: "unavailable" }, 503) : send(tasks);
    }
    if (url.pathname === "/api/config") return send(config);
    if (url.pathname === "/api/system") return send({ disk: { free: 85e9, used: 115e9, total: 200e9, percent: 57.5 }, temp_exists: true, temp_dir: config.temp_dir, temp_files: { files: 12, bytes: 2.3e9 }, load_average: [0.18, 0.24, 0.21], uptime_seconds: 93240 });
    if (url.pathname === "/api/deployment") return send({ services: { telegram: { state: "ready", message: "已连接，可以启动转发任务" }, bot: { state: "ready", message: "Bot 已连接" } }, fields: { TG_API_HASH: { configured: true, source: ".env" }, TG_PHONE: { configured: true, source: ".env" }, DB_PATH: { value: "data/forwarder.db", source: ".env" }, WEB_HOST: { value: "127.0.0.1", source: "default" }, WEB_PORT: { value: 10082, source: ".env" } } });
    if (url.pathname === "/api/logs") return send([{ id: 3, action: "启动任务", task_id: "daily", result: "success", created_at: new Date().toISOString() }, { id: 2, action: "更新运行配置", result: "success", created_at: new Date().toISOString() }, { id: 1, action: "Telegram 上传失败", task_id: "archive", result: "error", error: "网络连接中断，等待重试", created_at: new Date().toISOString() }]);
    const match = url.pathname.match(/^\/api\/tasks\/([^/]+)(.*)$/);
    if (match) {
      const task = tasks.find((t) => t.task_id === decodeURIComponent(match[1]));
      if (!task) return send({ error: "not_found" }, 404);
      if (match[2] === "/errors") return send({ errors: [{ stage: "telegram_download", filename: "资料中文名.mp4", error: "临时网络错误 <script>不会执行</script>", created_at: new Date().toISOString(), message_id: 401 }] });
      if (match[2] === "/action") { task.status = { pause: "paused", resume: "running", start: "running", stop: "stopped" }[body.action]; return send({ success: true }); }
      if (!match[2] && method === "PUT") { task.config = body; return send({ success: true }); }
      return send(task);
    }
    return send({ success: true });
  });
}
async function login(page, url) {
  await page.goto(url);
  await page.locator("#auth-gate").waitFor({ state: "visible" });
  await page.fill("#auth-password", "测试密码");
  await page.click("#auth-submit");
  await page.waitForFunction(() => document.querySelector("#stat-total").textContent !== "—");
}
async function noOverflow(page) {
  const dimensions = await page.evaluate(() => ({ body: document.documentElement.scrollWidth, viewport: innerWidth }));
  assert(dimensions.body <= dimensions.viewport, JSON.stringify(dimensions));
}
async function run() {
  await fs.mkdir(screenshotDir, { recursive: true });
  server = spawn(path.join(root, ".venv/bin/python"), ["-B", "-u", "-m", "tests.web.serve"], { cwd: root, stdio: ["ignore", "pipe", "inherit"] });
  const [chunk] = await once(server.stdout, "data");
  const url = chunk.toString().trim();
  assert.match(url, /^http:\/\/127\.0\.0\.1:\d+$/);
  browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || "/snap/bin/chromium", headless: true, args: ["--no-sandbox"] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, colorScheme: "light" });
  await setup(context);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page, url);
  assert.equal(await page.locator(".task-card").count(), 3);
  await noOverflow(page);
  await page.screenshot({ path: path.join(screenshotDir, "desktop-light.png"), fullPage: true });
  await page.click("#theme-btn");
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  await page.screenshot({ path: path.join(screenshotDir, "desktop-dark.png"), fullPage: true });
  await page.fill("#task-search", "资料");
  assert.equal(await page.locator(".task-card").count(), 1);
  await page.fill("#task-search", "不存在的搜索");
  assert.match(await page.locator("#tasks").textContent(), /没有匹配/);
  await page.fill("#task-search", "");
  await page.click('[data-filter="paused"]');
  assert.equal(await page.locator(".task-card").count(), 1);
  await page.click('[data-filter="all"]');
  await page.click('[data-task="daily"][data-action="pause"]');
  await page.waitForSelector('[data-task="daily"][data-action="resume"]');
  await page.click('[data-task="daily"][data-action="resume"]');
  await page.waitForSelector('[data-task="daily"][data-action="pause"]');
  const archive = page.locator('[data-card-id="archive"]');
  await archive.locator('.task-menu > summary').click();
  await archive.locator('[data-action="delete"]').click();
  await page.locator("#confirm-modal").waitFor({ state: "visible" });
  const count = writes.length;
  await page.keyboard.press("Escape");
  assert.equal(writes.length, count);
  assert.equal(await page.locator("#app-content").evaluate((el) => el.inert), false);
  await archive.locator('[data-action="errors"]').click();
  await page.waitForSelector(".error-item");
  assert.match(await page.locator(".error-item").textContent(), /<script>/);
  assert.equal(await page.locator("#errors-modal script").count(), 0);
  await page.keyboard.press("Escape");
  await archive.locator('[data-action="edit"]').click();
  await page.locator("#task-modal").waitFor({ state: "visible" });
  assert.equal(await page.locator("#task-form-id").isDisabled(), true);
  assert.equal(await page.locator("#source-reset-options").isVisible(), false);
  await page.fill("#task-form-source", "-100777");
  assert.equal(await page.locator("#source-reset-options").isVisible(), true);
  await page.click("#task-submit");
  await page.locator("#confirm-modal").waitFor({ state: "visible" });
  await page.keyboard.press("Escape");
  assert.equal(await page.locator("#task-modal").isVisible(), true);
  assert.equal(await page.locator("#app-content").evaluate((el) => el.inert), true);
  await page.keyboard.press("Escape");
  await page.click("#new-task-btn");
  await page.fill("#task-form-id", "created_task");
  await page.fill("#task-form-note", "新建测试任务");
  await page.fill("#task-form-source", "-100777");
  await page.fill("#task-form-target", "-100777");
  await page.click("#task-submit");
  assert.match(await page.locator("#task-form-error").textContent(), /不能相同/);
  await page.fill("#task-form-target", "-100888");
  await page.click("#task-submit");
  await page.waitForSelector('[data-card-id="created_task"]');
  assert.equal(writes.at(-1).body.hide_source, true);
  await page.click('[data-view="settings"]');
  await page.locator('[data-page="settings"]').waitFor({ state: "visible" });
  await page.reload();
  await page.locator('[data-page="settings"]').waitFor({ state: "visible" });
  await page.waitForFunction(() => document.querySelector("#config-temp-dir").textContent !== "—");
  await page.click("#edit-config-btn");
  await page.locator("#config-modal").waitFor({ state: "visible" });
  await page.locator("#config-modal .modal-close").focus();
  await page.keyboard.press("Shift+Tab");
  assert.equal(await page.evaluate(() => document.activeElement.id), "config-submit");
  await page.click("#config-submit");
  await page.locator("#config-modal").waitFor({ state: "hidden" });
  assert.equal(writes.at(-1).body.revision, 4);
  await page.locator("#toast").waitFor({ state: "hidden" });
  await page.screenshot({ path: path.join(screenshotDir, "settings-dark.png"), fullPage: true });
  for (const view of ["resources", "activity", "tasks"]) {
    await page.click(`[data-view="${view}"]`);
    await page.locator(`[data-page="${view}"]`).waitFor({ state: "visible" });
    await noOverflow(page);
  }
  failTasks = true;
  await page.click("#refresh-btn");
  await page.locator("#banner").waitFor({ state: "visible" });
  assert.equal(await page.locator(".task-card").count(), 4);
  failTasks = false;
  await page.click("#refresh-btn");
  await page.locator("#banner").waitFor({ state: "hidden" });
  for (const width of [360, 390, 768, 1024]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(await page.locator(".sidebar-brand .brand-mark svg").isVisible(), true);
    for (const view of ["tasks", "resources", "settings", "activity"]) {
      await page.click(`[data-view="${view}"]`);
      await page.locator(`[data-page="${view}"]`).waitFor({ state: "visible" });
      await noOverflow(page);
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.click('[data-view="tasks"]');
  await page.locator('[data-page="tasks"]').waitFor({ state: "visible" });
  await page.click("#theme-btn");
  await page.screenshot({ path: path.join(screenshotDir, "mobile-light.png"), fullPage: true });
  await page.click("#new-task-btn");
  await page.locator("#task-modal").waitFor({ state: "visible" });
  await noOverflow(page);
  await page.screenshot({ path: path.join(screenshotDir, "mobile-task-form.png"), fullPage: false });
  await page.keyboard.press("Escape");
  expired = true;
  await page.click("#refresh-btn");
  await page.locator("#auth-gate").waitFor({ state: "visible" });
  assert.equal(await page.locator("#app-content").isVisible(), false);
  assert.deepEqual(errors, []);
  console.log("Browser checks passed: authentication, views, filters, task actions/forms, confirmations, settings, failed refresh, expiry; 5 viewport sizes; light/dark themes.");
  console.log("Screenshots:", screenshotDir);
}
run().catch((error) => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server) server.kill("SIGTERM");
});
