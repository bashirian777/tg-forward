import { test, expect, type Page } from '@playwright/test'

function fixtures() {
  return [
    { task_id: 'daily', status: 'running', revision: 2, config: { task_id: 'daily', note: '每日精选 · 视频转发', source_channel: -100111222333, target_channel: -100444555666, min_delay: 10, max_delay: 20, enabled: true, hide_source: true, caption_prefix: '', filter_keywords: [], required_hashtags: ['纪录片', '科普'], target_topic_id: null, source_topic_id: null, remove_hashtags: false, send_as_channel: false, deduplicate: true }, progress: { forwarded_count: 1234, last_message_id: 8012, last_forward_time: new Date().toISOString() }, transfer: { type: 'download', state: 'downloading', filename: '地球脉动第三季·第六集：共同生存之路（4K修复版）.mp4', percent: 62.4, current: 1.2e9, total: 1.9e9, speed_bps: 8.6e6, file_index: 1, total_files: 3 }, errors: { unresolved: 0, count: 0 } },
    { task_id: 'archive', status: 'stopped', revision: 3, config: { task_id: 'archive', note: '资料归档', source_channel: -100777888999, target_channel: -100222333444, min_delay: 5, max_delay: 15, enabled: true, hide_source: true, caption_prefix: '', filter_keywords: ['广告'], required_hashtags: [], target_topic_id: null, source_topic_id: null, remove_hashtags: false, send_as_channel: false, deduplicate: false }, progress: { forwarded_count: 86, last_message_id: 402, last_forward_time: new Date(Date.now() - 7200000).toISOString() }, transfer: null, errors: { unresolved: 2, count: 2 } },
    { task_id: 'paused', status: 'paused', revision: 1, config: { task_id: 'paused', note: '稍后继续的转发任务', source_channel: -100111, target_channel: -100222, min_delay: 10, max_delay: 20, enabled: true, hide_source: true, caption_prefix: '', filter_keywords: [], required_hashtags: [], target_topic_id: null, source_topic_id: null, remove_hashtags: false, send_as_channel: false, deduplicate: false }, progress: { forwarded_count: 320, last_message_id: 1040, last_forward_time: '' }, transfer: null, errors: { unresolved: 0, count: 0 } },
  ]
}
async function setup(page: Page) {
  const tasks = fixtures(), writes: { path: string; method: string; body: any }[] = []
  const control = { expired: false, failTasks: false, conflict: false, delayAction: false, actionCount: 0 }
  let authenticated = false
  const config = { revision: 4, temp_dir: '/var/lib/tg-forward/temp', max_concurrent_tasks: 1, min_free_disk_mb: 1024, temp_max_age_hours: 24, download_workers: 4, upload_workers: 4, web_auth_ttl_hours: 24, web_password_configured: true }
  const auth = () => ({ authenticated, auth_required: true, csrf_token: authenticated ? 'csrf-test' : '', expires_at: Date.now() / 1000 + 86400 })
  await page.route('**/api/**', async route => {
    const req = route.request(), url = new URL(req.url()), method = req.method(), body = req.postDataJSON() || {}
    const send = (data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    if (url.pathname === '/api/auth') {
      if (method === 'GET') return send(auth())
      if (method === 'DELETE') { authenticated = false; return send({ success: true }) }
      if (body.password === '测试密码') { authenticated = true; control.expired = false; return send(auth()) }
      return send({ error: 'invalid_password', message: '管理密码不正确' }, 401)
    }
    if (control.expired || !authenticated) return send({ error: 'unauthorized', message: '登录已过期' }, 401)
    if (method !== 'GET') {
      expect(req.headers()['x-csrf-token']).toBe('csrf-test')
      writes.push({ path: url.pathname, method, body })
    }
    if (url.pathname === '/api/tasks') {
      if (method === 'POST') { tasks.push({ task_id: body.task_id, status: 'stopped', revision: 1, config: body, progress: { forwarded_count: 0, last_message_id: 0, last_forward_time: '' }, transfer: null, errors: { unresolved: 0, count: 0 } }); return send({ success: true }) }
      return control.failTasks ? send({ error: 'unavailable', message: '服务暂时不可用' }, 503) : send(tasks)
    }
    if (url.pathname === '/api/config') return send(config)
    if (url.pathname === '/api/system') return send({ disk: { free: 85e9, used: 115e9, total: 200e9, percent: 57.5 }, temp_disk: { free: 100e6, used: 99.9e9, total: 100e9, percent: 99.9 }, temp_exists: true, temp_dir: config.temp_dir, temp_files: { files: 12, bytes: 2.3e9 }, load_average: [0.18, 0.24, 0.21], uptime_seconds: 93240 })
    if (url.pathname === '/api/deployment') return send({ services: { telegram: { state: 'ready', message: 'Telegram 已连接' }, bot: { state: 'disabled', message: '未启用 Bot' } }, fields: { TG_API_HASH: { configured: true, source: '.env' }, DB_PATH: { value: 'data/forwarder.db', source: '.env' }, WEB_PORT: { value: 10082, source: '.env' } } })
    if (url.pathname === '/api/logs') return send([{ id: 1, action: 'create_task', task_id: 'daily', result: 'success', created_at: new Date().toISOString() }])
    const match = url.pathname.match(/^\/api\/tasks\/([^/]+)(.*)$/)
    if (match) {
      const task = tasks.find(t => t.task_id === decodeURIComponent(match[1]))
      if (!task) return send({ error: 'task_not_found', message: '任务不存在' }, 404)
      if (match[2] === '/errors') return send({ errors: [{ id: 1, stage: 'telegram_download', filename: '资料中文名.mp4', error: '临时错误 <script>不会执行</script>', created_at: new Date().toISOString(), message_id: 401 }] })
      if (match[2] === '/action') {
        control.actionCount++
        if (control.delayAction) await new Promise(resolve => setTimeout(resolve, 800))
        task.status = ({ pause: 'paused', resume: 'running', start: 'running', stop: 'stopped' } as Record<string, string>)[body.action]
        return send({ success: true })
      }
      if (!match[2] && method === 'PUT') {
        if (control.conflict) return send({ error: 'configuration_conflict', message: '配置已修改，请重新读取' }, 409)
        task.config = body; task.revision++; return send({ success: true })
      }
      if (!match[2] && method === 'DELETE') { tasks.splice(tasks.indexOf(task), 1); return send({ success: true }) }
      return send(task)
    }
    return send({ success: true, removed: 3, freed_bytes: 1000, errors: [] })
  })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  return { tasks, writes, control, errors }
}
async function login(page: Page, path = '/') {
  await page.goto(path)
  await expect(page.locator('#auth-gate')).toBeVisible()
  await page.fill('#auth-password', '测试密码')
  await page.click('#auth-submit')
  await expect(page.locator('#app-content')).toBeVisible()
}
async function noOverflow(page: Page) {
  const value = await page.evaluate(() => ({ body: document.documentElement.scrollWidth, viewport: innerWidth }))
  expect(value.body).toBeLessThanOrEqual(value.viewport)
}

test('authentication, tasks, forms, conflicts, resources and expiry', async ({ page }) => {
  const state = await setup(page)
  await login(page)
  await expect(page.locator('.task-card')).toHaveCount(3)
  const daily = page.locator('[data-card-id="daily"]'), archive = page.locator('[data-card-id="archive"]')
  await expect(daily.locator('[data-action="edit"]')).toBeDisabled()
  await page.fill('#task-search', '资料')
  await expect(page.locator('.task-card')).toHaveCount(1)
  await page.fill('#task-search', '不存在')
  await expect(page.locator('#tasks')).toContainText('没有匹配')
  await page.fill('#task-search', '')
  await page.click('[data-filter="paused"]')
  await expect(page.locator('.task-card')).toHaveCount(1)
  await page.click('[data-filter="all"]')
  state.control.delayAction = true
  await daily.locator('[data-action="pause"]').click()
  await expect(daily.locator('[data-action="pause"]')).toBeDisabled()
  await page.click('#refresh-btn')
  await expect(daily.locator('[data-action="pause"]')).toBeDisabled()
  await expect(daily.locator('[data-action="resume"]')).toBeVisible()
  expect(state.control.actionCount).toBe(1)
  state.control.delayAction = false
  await daily.locator('[data-action="resume"]').click()
  await expect(daily.locator('[data-action="pause"]')).toBeVisible()
  await archive.locator('.task-menu summary').click()
  await archive.locator('[data-action="delete"]').click()
  await expect(page.locator('#confirm-modal')).toBeVisible()
  const count = state.writes.length
  await page.keyboard.press('Escape')
  expect(state.writes.length).toBe(count)
  await archive.getByRole('button', { name: /查看错误/ }).click()
  await expect(page.locator('.error-item')).toContainText('<script>')
  await expect(page.locator('#errors-modal script')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await archive.locator('[data-action="edit"]').click()
  await expect(page.locator('#task-form-id')).toBeDisabled()
  await page.fill('#task-form-source_channel', '-100777')
  await expect(page.locator('#source-reset-options')).toBeVisible()
  await page.click('#task-submit')
  await expect(page.locator('#confirm-modal')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('#task-modal')).toBeVisible()
  await page.keyboard.press('Escape')
  await archive.locator('[data-action="edit"]').click()
  await page.fill('#task-form-note', '保留的修改')
  state.control.conflict = true
  await page.click('#task-submit')
  await expect(page.locator('#task-form-error')).toContainText('配置已修改')
  await expect(page.locator('#task-form-note')).toHaveValue('保留的修改')
  await page.getByRole('button', { name: '读取最新版本并保留输入' }).click()
  await expect(page.locator('#task-form-note')).toHaveValue('保留的修改')
  state.control.conflict = false
  await page.click('#task-submit')
  await expect(page.locator('#task-modal')).toHaveCount(0)
  await page.click('#new-task-btn')
  await page.fill('#task-form-id', 'created_task')
  await page.fill('#task-form-source_channel', '-100777')
  await page.fill('#task-form-target_channel', '-100777')
  await page.click('#task-submit')
  await expect(page.locator('#task-form-error')).toContainText('不能相同')
  await page.fill('#task-form-target_channel', '-100888')
  await page.click('#task-submit')
  await expect(page.locator('[data-card-id="created_task"]')).toBeVisible()
  await page.click('[data-view="settings"]')
  await expect(page.locator('[data-page="settings"]')).toBeVisible()
  await page.reload()
  await expect(page.locator('[data-page="settings"]')).toBeVisible()
  await page.click('#edit-config-btn')
  await page.fill('#config-form-web_auth_ttl_hours', '12')
  await page.click('#config-submit')
  expect(state.writes.at(-1)?.body.revision).toBe(4)
  await expect(page.locator('#config-modal')).toHaveCount(0)
  await page.click('[data-view="resources"]')
  await expect(page.getByText('临时目录所在磁盘空间偏低')).toBeVisible()
  await page.click('[data-view="tasks"]')
  state.control.failTasks = true
  await page.click('#refresh-btn')
  await expect(page.locator('#banner')).toBeVisible()
  await expect(page.locator('.task-card')).toHaveCount(4)
  state.control.failTasks = false
  await page.click('#refresh-btn')
  await expect(page.locator('#banner')).toHaveCount(0)
  state.control.expired = true
  await page.click('#refresh-btn')
  await expect(page.locator('#auth-gate')).toBeVisible()
  expect(state.errors).toEqual([])
})

for (const width of [1440, 1024, 768, 390, 360]) {
  test(`layout, theme and dialog keyboard at ${width}px`, async ({ page }, testInfo) => {
    const state = await setup(page)
    await page.setViewportSize({ width, height: 900 })
    await login(page)
    await expect(page.locator('.task-card')).toHaveCount(3)
    for (const view of ['tasks', 'resources', 'settings', 'activity']) {
      await page.click(`[data-view="${view}"]`)
      await expect(page.locator(`[data-page="${view}"]`)).toBeVisible()
      await noOverflow(page)
    }
    await page.click('[data-view="tasks"]')
    await page.screenshot({ path: testInfo.outputPath('light.png'), fullPage: true })
    await page.click('#theme-btn')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await page.screenshot({ path: testInfo.outputPath('dark.png'), fullPage: true })
    await page.click('#new-task-btn')
    await expect(page.locator('#task-modal')).toBeVisible()
    await noOverflow(page)
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press('Tab')
      expect(await page.evaluate(() => !!document.activeElement?.closest('#task-modal'))).toBe(true)
    }
    await page.screenshot({ path: testInfo.outputPath('task-form.png') })
    await page.keyboard.press('Escape')
    await expect(page.locator('#new-task-btn')).toBeFocused()
    expect(state.errors).toEqual([])
  })
}
