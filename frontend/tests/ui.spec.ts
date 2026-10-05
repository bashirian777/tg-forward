import { test, expect, type Page } from '@playwright/test'
import type { RuntimeConfig, TaskSnapshot } from '../src/types/api'

function fixtures(): TaskSnapshot[] {
  return [
    { task_id: 'daily', status: 'running', revision: 2, config: { task_id: 'daily', note: '每日精选 · 视频转发', source_channel: -100111222333, target_channel: -100444555666, min_delay: 10, max_delay: 20, enabled: true, hide_source: true, caption_prefix: '', filter_keywords: [], required_hashtags: ['纪录片', '科普'], target_topic_id: null, source_topic_id: null, remove_hashtags: false, send_as_channel: false, deduplicate: true }, progress: { forwarded_count: 1234, last_message_id: 8012, last_forward_time: new Date().toISOString() }, transfer: { type: 'download', state: 'downloading', filename: '地球脉动第三季·第六集：共同生存之路（4K修复版）.mp4', percent: 62.4, current: 1.2e9, total: 1.9e9, speed_bps: 8.6e6, file_index: 1, total_files: 3 }, errors: { unresolved: 0, count: 0 } },
    { task_id: 'archive', status: 'stopped', revision: 3, config: { task_id: 'archive', note: '资料归档', source_channel: -100777888999, target_channel: -100222333444, min_delay: 5, max_delay: 15, enabled: true, hide_source: true, caption_prefix: '', filter_keywords: ['广告'], required_hashtags: [], target_topic_id: null, source_topic_id: null, remove_hashtags: false, send_as_channel: false, deduplicate: false }, progress: { forwarded_count: 86, last_message_id: 402, last_forward_time: new Date(Date.now() - 7200000).toISOString() }, transfer: null, errors: { unresolved: 2, count: 2 } },
    { task_id: 'paused', status: 'paused', revision: 1, config: { task_id: 'paused', note: '稍后继续的转发任务', source_channel: -100111, target_channel: -100222, min_delay: 10, max_delay: 20, enabled: true, hide_source: true, caption_prefix: '', filter_keywords: [], required_hashtags: [], target_topic_id: null, source_topic_id: null, remove_hashtags: false, send_as_channel: false, deduplicate: false }, progress: { forwarded_count: 320, last_message_id: 1040, last_forward_time: '' }, transfer: null, errors: { unresolved: 0, count: 0 } },
  ]
}
async function setup(page: Page) {
  const tasks = fixtures(), writes: { path: string; method: string; body: any }[] = []
  const control = { expired: false, failTasks: false, delayAction: false, actionCount: 0 }
  const settings = { password: '测试密码' }
  let authenticated = false
  const config: RuntimeConfig = { revision: 4, temp_dir: '/var/lib/tg-forward/temp', max_concurrent_tasks: 1, min_free_disk_mb: 1024, temp_max_age_hours: 24, download_workers: 4, upload_workers: 4, web_auth_ttl_hours: 24, web_password_configured: true }
  const auth = () => ({ authenticated, auth_required: true, csrf_token: authenticated ? 'csrf-test' : '', expires_at: Date.now() / 1000 + 86400 })
  await page.route('**/api/**', async route => {
    const req = route.request(), url = new URL(req.url()), method = req.method(), body = req.postDataJSON() || {}
    const send = (data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    if (url.pathname === '/api/auth') {
      if (method === 'GET') return send(auth())
      if (method === 'DELETE') { authenticated = false; return send({ success: true }) }
      if (body.password === settings.password) { authenticated = true; control.expired = false; return send(auth()) }
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
    if (url.pathname === '/api/config') {
      if (method === 'PUT') {
        if (body.revision !== config.revision) return send({ error: 'configuration_conflict', message: '配置已修改，请重新读取' }, 409)
        const { revision, web_password, ...values } = body
        Object.assign(config, values)
        if (web_password) { settings.password = web_password; config.web_password_configured = true }
        config.revision++
        return send({ success: true, revision: config.revision })
      }
      return send(config)
    }
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
        task.status = ({ pause: 'paused', resume: 'running', start: 'running', stop: 'stopped' } as Record<string, TaskSnapshot['status']>)[body.action]
        return send({ success: true })
      }
      if (!match[2] && method === 'PUT') {
        if (body.revision !== task.revision) return send({ error: 'configuration_conflict', message: '配置已修改，请重新读取' }, 409)
        const { revision, source_reset, ...values } = body
        const sourceChanged = task.config.source_channel !== values.source_channel || task.config.source_topic_id !== values.source_topic_id
        if (sourceChanged && !source_reset) return send({ error: 'source_reset_required', message: '来源变更需要重置起点' }, 400)
        expect(!!source_reset).toBe(sourceChanged)
        task.config = values
        if (source_reset) task.progress.last_message_id = source_reset.last_message_id
        task.revision++
        return send({ success: true, revision: task.revision })
      }
      if (!match[2] && method === 'DELETE') { tasks.splice(tasks.indexOf(task), 1); return send({ success: true }) }
      return send(task)
    }
    return send({ success: true, removed: 3, freed_bytes: 1000, errors: [] })
  })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  return { tasks, config, settings, writes, control, errors }
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
  state.tasks[1].config.max_delay = 25
  state.tasks[1].revision++
  await page.click('#task-submit')
  await expect(page.locator('#task-form-error')).toContainText('配置已修改')
  await expect(page.locator('#task-form-note')).toHaveValue('保留的修改')
  await page.getByRole('button', { name: '读取最新版本并保留输入' }).click()
  await expect(page.locator('#task-form-note')).toHaveValue('保留的修改')
  await expect(page.locator('#task-form-max_delay')).toHaveValue('25')
  await page.click('#task-submit')
  await expect(page.locator('#task-modal')).toHaveCount(0)
  expect(state.tasks[1].config.note).toBe('保留的修改')
  expect(state.tasks[1].config.max_delay).toBe(25)
  expect(state.tasks[1].revision).toBe(5)
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
  expect(state.config.web_auth_ttl_hours).toBe(12)
  expect(state.config.revision).toBe(5)
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

async function reloadConflict(page: Page, kind: 'task' | 'config') {
  await expect(page.locator(`#${kind}-form-error`)).toContainText('配置已修改')
  await expect(page.locator(`#${kind}-submit`)).toBeDisabled()
  await page.getByRole('button', { name: '读取最新版本并保留输入' }).click()
  await expect(page.locator(`#${kind}-form-error`)).toContainText('最新版本')
}

test('task merge adopts remote arrays and source without resetting the latest source', async ({ page }) => {
  const state = await setup(page)
  await login(page)
  await page.locator('[data-card-id="archive"] [data-action="edit"]').click()
  await page.fill('#task-form-note', '本地备注')
  const task = state.tasks[1]
  Object.assign(task.config, { filter_keywords: ['服务器关键词', '新增词'], required_hashtags: ['最新标签'], source_channel: -100999, source_topic_id: 7, target_topic_id: 9, caption_prefix: '服务器前缀', remove_hashtags: true })
  task.revision++
  await page.click('#task-submit')
  await reloadConflict(page, 'task')
  await expect(page.locator('#task-form-keywords')).toHaveValue('服务器关键词\n新增词')
  await expect(page.locator('#task-form-hashtags')).toHaveValue('最新标签')
  await expect(page.locator('#task-form-prefix')).toHaveValue('服务器前缀')
  await expect(page.locator('#task-form-remove_hashtags')).toBeChecked()
  await expect(page.locator('#source-reset-options')).toHaveCount(0)
  await expect(page.locator('[data-conflict-field]')).toHaveCount(0)
  await page.click('#task-submit')
  await expect(page.locator('#task-modal')).toHaveCount(0)
  expect(task.config).toMatchObject({ note: '本地备注', source_channel: -100999, source_topic_id: 7, target_topic_id: 9, filter_keywords: ['服务器关键词', '新增词'], required_hashtags: ['最新标签'], remove_hashtags: true })
  expect(state.writes.at(-1)?.body).not.toHaveProperty('source_reset')
  expect(task.progress.last_message_id).toBe(402)
  expect(task.config).not.toHaveProperty('revision')
  expect(state.errors).toEqual([])
})

for (const choice of ['current', 'latest'] as const) {
  test(`task same-field conflicts require explicit ${choice} choices, including textareas`, async ({ page }) => {
    const state = await setup(page)
    await login(page)
    await page.locator('[data-card-id="archive"] [data-action="edit"]').click()
    await page.fill('#task-form-note', '本地备注')
    await page.fill('#task-form-keywords', ' 本地词 \n\n本地词二 ')
    await page.fill('#task-form-hashtags', '本地标签')
    const task = state.tasks[1]
    Object.assign(task.config, { note: '远端备注', filter_keywords: ['远端词'], required_hashtags: ['远端标签'], max_delay: 30 })
    task.revision++
    await page.click('#task-submit')
    await reloadConflict(page, 'task')
    await expect(page.locator('[data-conflict-field]')).toHaveCount(3)
    const note = page.locator('[data-conflict-field="note"]')
    await expect(note).toContainText('资料归档')
    await expect(note).toContainText('本地备注')
    await expect(note).toContainText('远端备注')
    await expect(page.locator('#task-submit')).toBeDisabled()
    const writes = state.writes.length
    // The handler also blocks submission dispatched without the disabled button.
    await page.locator('#task-form').evaluate(form => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
    expect(state.writes.length).toBe(writes)
    for (const key of ['note', 'filter_keywords', 'required_hashtags']) {
      await page.locator(`[data-conflict-field="${key}"]`).getByRole('radio', { name: choice === 'current' ? '使用当前输入' : '使用最新值' }).check()
      if (key !== 'required_hashtags') await expect(page.locator('#task-submit')).toBeDisabled()
    }
    await expect(page.locator('#task-form-keywords')).toHaveValue(choice === 'current' ? '本地词\n本地词二' : '远端词')
    await expect(page.locator('#task-form-hashtags')).toHaveValue(choice === 'current' ? '本地标签' : '远端标签')
    await page.click('#task-submit')
    await expect(page.locator('#task-modal')).toHaveCount(0)
    expect(task.config).toMatchObject({ note: choice === 'current' ? '本地备注' : '远端备注', filter_keywords: choice === 'current' ? ['本地词', '本地词二'] : ['远端词'], required_hashtags: choice === 'current' ? ['本地标签'] : ['远端标签'], max_delay: 30 })
    expect(task.revision).toBe(5)
    expect(state.errors).toEqual([])
  })

  test(`task source conflict uses latest baseline after choosing ${choice}`, async ({ page }) => {
    const state = await setup(page)
    await login(page)
    await page.locator('[data-card-id="archive"] [data-action="edit"]').click()
    await page.fill('#task-form-source_channel', '-100555')
    await page.fill('#source-reset-id', '123')
    const task = state.tasks[1]
    task.config.source_channel = -100999
    task.revision++
    await page.click('#task-submit')
    await page.locator('#confirm-modal').getByRole('button', { name: '确认' }).click()
    await reloadConflict(page, 'task')
    await page.locator('[data-conflict-field="source_channel"]').getByRole('radio', { name: choice === 'current' ? '使用当前输入' : '使用最新值' }).check()
    if (choice === 'current') {
      await expect(page.locator('#source-reset-id')).toHaveValue('123')
      await page.click('#task-submit')
      await page.locator('#confirm-modal').getByRole('button', { name: '确认' }).click()
    } else {
      await expect(page.locator('#source-reset-options')).toHaveCount(0)
      await page.click('#task-submit')
    }
    await expect(page.locator('#task-modal')).toHaveCount(0)
    expect(task.config.source_channel).toBe(choice === 'current' ? -100555 : -100999)
    expect(task.progress.last_message_id).toBe(choice === 'current' ? 123 : 402)
    if (choice === 'current') expect(state.writes.at(-1)?.body.source_reset).toEqual({ last_message_id: 123, clear_dedup: true })
    else expect(state.writes.at(-1)?.body).not.toHaveProperty('source_reset')
    expect(state.errors).toEqual([])
  })

  test(`settings merge requires ${choice} choice and survives another concurrent update`, async ({ page }) => {
    const state = await setup(page)
    await login(page, '/settings')
    await page.click('#edit-config-btn')
    await page.fill('#config-form-web_auth_ttl_hours', '12')
    await page.fill('#config-form-download_workers', '6')
    await page.fill('#config-form-temp', '/local/temp')
    Object.assign(state.config, { web_auth_ttl_hours: 48, upload_workers: 8, temp_dir: '/remote/temp' })
    state.config.revision++
    const latest = structuredClone(state.config)
    await page.click('#config-submit')
    await reloadConflict(page, 'config')
    expect(state.config).toEqual(latest)
    expect(state.writes.at(-1)?.body.revision).toBe(4)
    await expect(page.locator('#config-form-download_workers')).toHaveValue('6')
    await expect(page.locator('#config-form-upload_workers')).toHaveValue('8')
    await expect(page.locator('#config-form-temp')).toHaveValue('/local/temp')
    await expect(page.locator('[data-conflict-field]')).toHaveCount(2)
    const ttl = page.locator('[data-conflict-field="web_auth_ttl_hours"]')
    await expect(ttl.locator('.conflict-values pre')).toHaveText(['24', '12', '48'])
    const writes = state.writes.length
    await page.locator('#config-form').evaluate(form => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
    expect(state.writes.length).toBe(writes)
    await ttl.getByRole('radio', { name: choice === 'current' ? '使用当前输入' : '使用最新值' }).check()
    await expect(page.locator('#config-submit')).toBeDisabled()
    await page.locator('[data-conflict-field="temp_dir"]').getByRole('radio', { name: '使用最新值' }).check()
    await expect(page.locator('#config-submit')).toBeEnabled()
    // A second writer changes a different field before this save.
    state.config.min_free_disk_mb = 2048
    state.config.revision++
    await page.click('#config-submit')
    await reloadConflict(page, 'config')
    await expect(page.locator('[data-conflict-field]')).toHaveCount(0)
    await expect(page.locator('#config-form-min_free_disk_mb')).toHaveValue('2048')
    await expect(page.locator('#config-form-web_auth_ttl_hours')).toHaveValue(choice === 'current' ? '12' : '48')
    await page.click('#config-submit')
    await expect(page.locator('#config-modal')).toHaveCount(0)
    expect(state.config).toMatchObject({ revision: 7, web_auth_ttl_hours: choice === 'current' ? 12 : 48, download_workers: 6, upload_workers: 8, temp_dir: '/remote/temp', min_free_disk_mb: 2048 })
    expect(state.settings.password).toBe('测试密码')
    expect(state.errors).toEqual([])
  })

  test(`write-only password requires ${choice} confirmation without exposing input`, async ({ page }) => {
    const state = await setup(page)
    await login(page, '/settings')
    await page.click('#edit-config-btn')
    await page.fill('#config-form-password', '本地新密码')
    await page.fill('#config-form-temp', '/local/temp')
    state.settings.password = '远端新密码'
    state.config.revision++
    await page.click('#config-submit')
    await reloadConflict(page, 'config')
    await expect(page.locator('#config-form-password')).toHaveValue('本地新密码')
    const field = page.locator('[data-conflict-field="web_password"]')
    await expect(field).not.toContainText('本地新密码')
    await expect(page.locator('#config-submit')).toBeDisabled()
    await field.getByRole('radio', { name: choice === 'current' ? '使用当前输入' : '使用最新值' }).check()
    await page.click('#config-submit')
    await expect(page.locator('#config-modal')).toHaveCount(0)
    expect(state.settings.password).toBe(choice === 'current' ? '本地新密码' : '远端新密码')
    expect(state.config.temp_dir).toBe('/local/temp')
    expect(state.config).not.toHaveProperty('web_password')
    expect(state.errors).toEqual([])
  })
}

test('matching edits and normalized textarea values do not create false conflicts', async ({ page }) => {
  const state = await setup(page)
  await login(page)
  await page.locator('[data-card-id="archive"] [data-action="edit"]').click()
  await page.fill('#task-form-keywords', ' 广告 \n\n')
  await page.fill('#task-form-note', '共同修改')
  state.tasks[1].config.filter_keywords = ['远端新增词']
  state.tasks[1].config.note = '共同修改'
  state.tasks[1].revision++
  await page.click('#task-submit')
  await reloadConflict(page, 'task')
  await expect(page.locator('[data-conflict-field]')).toHaveCount(0)
  await expect(page.locator('#task-form-keywords')).toHaveValue('远端新增词')
  await page.click('#task-submit')
  await expect(page.locator('#task-modal')).toHaveCount(0)
  expect(state.tasks[1].config.filter_keywords).toEqual(['远端新增词'])
  expect(state.tasks[1].config.note).toBe('共同修改')
  expect(state.errors).toEqual([])
})

test('settings automatically merge disjoint edits and persist successive saves', async ({ page }) => {
  const state = await setup(page)
  await login(page, '/settings')
  await page.click('#edit-config-btn')
  await page.fill('#config-form-temp', '/local/temp')
  await page.fill('#config-form-download_workers', '6')
  Object.assign(state.config, { upload_workers: 8, web_auth_ttl_hours: 48 })
  state.config.revision++
  const latest = structuredClone(state.config)
  await page.click('#config-submit')
  await reloadConflict(page, 'config')
  expect(state.config).toEqual(latest)
  await expect(page.locator('[data-conflict-field]')).toHaveCount(0)
  await expect(page.locator('#config-form-temp')).toHaveValue('/local/temp')
  await expect(page.locator('#config-form-download_workers')).toHaveValue('6')
  await expect(page.locator('#config-form-upload_workers')).toHaveValue('8')
  await expect(page.locator('#config-form-web_auth_ttl_hours')).toHaveValue('48')
  const saved = page.waitForResponse(response => response.url().endsWith('/api/config') && response.request().method() === 'PUT' && response.status() === 200)
  await page.click('#config-submit')
  expect(await (await saved).json()).toMatchObject({ success: true, revision: 6 })
  await expect(page.locator('#config-modal')).toHaveCount(0)
  expect(state.config).toMatchObject({ revision: 6, temp_dir: '/local/temp', download_workers: 6, upload_workers: 8, web_auth_ttl_hours: 48 })
  expect(state.config).not.toHaveProperty('web_password')
  // Reopening after a full page reload verifies GET serves the saved values.
  await page.reload()
  await page.click('#edit-config-btn')
  await expect(page.locator('#config-form-temp')).toHaveValue('/local/temp')
  await expect(page.locator('#config-form-download_workers')).toHaveValue('6')
  await expect(page.locator('#config-form-upload_workers')).toHaveValue('8')
  await expect(page.locator('#config-form-web_auth_ttl_hours')).toHaveValue('48')
  await page.fill('#config-form-temp_max_age_hours', '12')
  await page.click('#config-submit')
  await expect(page.locator('#config-modal')).toHaveCount(0)
  expect(state.config).toMatchObject({ revision: 7, temp_max_age_hours: 12, temp_dir: '/local/temp', download_workers: 6, upload_workers: 8, web_auth_ttl_hours: 48 })
  expect(state.writes.filter(write => write.path === '/api/config').map(write => write.body.revision)).toEqual([4, 5, 6])
  expect(state.settings.password).toBe('测试密码')
  expect(state.errors).toEqual([])
})

test('task consecutive same-field conflicts use the latest baseline and require new choices', async ({ page }) => {
  const state = await setup(page)
  await login(page)
  await page.locator('[data-card-id="archive"] [data-action="edit"]').click()
  await page.fill('#task-form-note', '本地备注')
  await page.fill('#task-form-keywords', '本地词')
  await page.fill('#task-form-hashtags', '本地标签')
  await page.getByText('删除已匹配 Hashtag', { exact: true }).click()
  await expect(page.locator('#task-form-remove_hashtags')).toBeChecked()
  const task = state.tasks[1]
  Object.assign(task.config, { note: '远端第一版', filter_keywords: ['远端第一版词'], max_delay: 25 })
  task.revision++
  const firstLatest = structuredClone(task)
  await page.click('#task-submit')
  await reloadConflict(page, 'task')
  expect(task).toEqual(firstLatest)
  await expect(page.locator('[data-conflict-field]')).toHaveCount(2)
  await page.locator('[data-conflict-field="note"]').getByRole('radio', { name: '使用当前输入' }).check()
  await page.locator('[data-conflict-field="filter_keywords"]').getByRole('radio', { name: '使用最新值' }).check()
  await expect(page.locator('#task-form-keywords')).toHaveValue('远端第一版词')
  await expect(page.locator('#task-submit')).toBeEnabled()
  await page.fill('#task-form-keywords', ' 二次本地词 \n\n二次本地词二 ')
  Object.assign(task.config, { note: '远端第二版', filter_keywords: ['远端第二版词'], max_delay: 30 })
  task.revision++
  const secondLatest = structuredClone(task)
  await page.click('#task-submit')
  await reloadConflict(page, 'task')
  expect(task).toEqual(secondLatest)
  await expect(page.locator('[data-conflict-field]')).toHaveCount(2)
  await expect(page.locator('[data-conflict-field] input:checked')).toHaveCount(0)
  const note = page.locator('[data-conflict-field="note"]'), keywords = page.locator('[data-conflict-field="filter_keywords"]')
  await expect(note.locator('.conflict-values pre')).toHaveText(['远端第一版', '本地备注', '远端第二版'])
  await expect(keywords.locator('.conflict-values pre')).toHaveText(['远端第一版词', '二次本地词\n二次本地词二', '远端第二版词'])
  await expect(page.locator('#task-submit')).toBeDisabled()
  await note.getByRole('radio', { name: '使用最新值' }).check()
  await expect(page.locator('#task-submit')).toBeDisabled()
  await keywords.getByRole('radio', { name: '使用当前输入' }).check()
  await expect(page.locator('#task-form-keywords')).toHaveValue('二次本地词\n二次本地词二')
  await expect(page.locator('#task-form-hashtags')).toHaveValue('本地标签')
  await expect(page.locator('#task-form-remove_hashtags')).toBeChecked()
  await page.click('#task-submit')
  await expect(page.locator('#task-modal')).toHaveCount(0)
  expect(task).toMatchObject({ revision: 6, config: { note: '远端第二版', filter_keywords: ['二次本地词', '二次本地词二'], required_hashtags: ['本地标签'], remove_hashtags: true, max_delay: 30 } })
  expect(state.writes.filter(write => write.path === '/api/tasks/archive').map(write => write.body.revision)).toEqual([3, 4, 5])
  expect(task.config).not.toHaveProperty('revision')
  expect(task.config).not.toHaveProperty('source_reset')
  await page.reload()
  await page.locator('[data-card-id="archive"] [data-action="edit"]').click()
  await expect(page.locator('#task-form-keywords')).toHaveValue('二次本地词\n二次本地词二')
  await expect(page.locator('#task-form-hashtags')).toHaveValue('本地标签')
  expect(state.errors).toEqual([])
})

test('settings consecutive same-field conflicts discard previous choices', async ({ page }) => {
  const state = await setup(page)
  await login(page, '/settings')
  await page.click('#edit-config-btn')
  await page.fill('#config-form-web_auth_ttl_hours', '12')
  await page.fill('#config-form-download_workers', '6')
  Object.assign(state.config, { web_auth_ttl_hours: 48, upload_workers: 8 })
  state.config.revision++
  await page.click('#config-submit')
  await reloadConflict(page, 'config')
  await page.locator('[data-conflict-field="web_auth_ttl_hours"]').getByRole('radio', { name: '使用当前输入' }).check()
  await expect(page.locator('#config-submit')).toBeEnabled()
  Object.assign(state.config, { web_auth_ttl_hours: 96, min_free_disk_mb: 2048 })
  state.config.revision++
  const latest = structuredClone(state.config)
  await page.click('#config-submit')
  await reloadConflict(page, 'config')
  expect(state.config).toEqual(latest)
  await expect(page.locator('[data-conflict-field]')).toHaveCount(1)
  await expect(page.locator('[data-conflict-field] input:checked')).toHaveCount(0)
  const ttl = page.locator('[data-conflict-field="web_auth_ttl_hours"]')
  await expect(ttl.locator('.conflict-values pre')).toHaveText(['48', '12', '96'])
  await expect(page.locator('#config-submit')).toBeDisabled()
  await ttl.getByRole('radio', { name: '使用最新值' }).check()
  await page.click('#config-submit')
  await expect(page.locator('#config-modal')).toHaveCount(0)
  expect(state.config).toMatchObject({ revision: 7, web_auth_ttl_hours: 96, download_workers: 6, upload_workers: 8, min_free_disk_mb: 2048 })
  expect(state.writes.filter(write => write.path === '/api/config').map(write => write.body.revision)).toEqual([4, 5, 6])
  expect(state.errors).toEqual([])
})

for (const source of [
  { key: 'source_channel', input: '#task-form-source_channel', initial: -100777888999, latest: -100999 },
  { key: 'source_topic_id', input: '#task-form-source-topic', initial: 4, latest: 7 },
] as const) {
  test(`editing ${source.key} after merge compares source_reset against the latest source`, async ({ page }) => {
    const state = await setup(page), task = state.tasks[1]
    task.config[source.key] = source.initial
    await login(page)
    await page.locator('[data-card-id="archive"] [data-action="edit"]').click()
    await page.fill('#task-form-note', '本地备注')
    task.config[source.key] = source.latest
    task.progress.last_message_id = 777
    task.revision++
    await page.click('#task-submit')
    await reloadConflict(page, 'task')
    await expect(page.locator(source.input)).toHaveValue(String(source.latest))
    await expect(page.locator('#source-reset-options')).toHaveCount(0)
    // Returning to the value from when the dialog opened still changes the latest source.
    await page.fill(source.input, String(source.initial))
    await expect(page.locator('#source-reset-options')).toBeVisible()
    await page.fill('#source-reset-id', '123')
    await page.uncheck('#source-reset-dedup')
    task.config.caption_prefix = '远端第二版前缀'
    task.revision++
    const latest = structuredClone(task)
    await page.click('#task-submit')
    await page.locator('#confirm-modal').getByRole('button', { name: '确认' }).click()
    await reloadConflict(page, 'task')
    expect(task).toEqual(latest)
    await expect(page.locator('[data-conflict-field]')).toHaveCount(0)
    await expect(page.locator('#source-reset-options')).toBeVisible()
    await expect(page.locator('#source-reset-id')).toHaveValue('123')
    await expect(page.locator('#source-reset-dedup')).not.toBeChecked()
    await page.click('#task-submit')
    await page.locator('#confirm-modal').getByRole('button', { name: '确认' }).click()
    await expect(page.locator('#task-modal')).toHaveCount(0)
    expect(task.revision).toBe(6)
    expect(task.config[source.key]).toBe(source.initial)
    expect(task.config).toMatchObject({ note: '本地备注', caption_prefix: '远端第二版前缀' })
    expect(task.progress.last_message_id).toBe(123)
    expect(state.writes.at(-1)?.body.source_reset).toEqual({ last_message_id: 123, clear_dedup: false })
    expect(state.writes.filter(write => write.path === '/api/tasks/archive').map(write => write.body.revision)).toEqual([3, 4, 5])
    expect(state.errors).toEqual([])
  })
}

for (const kind of ['config', 'task'] as const) {
  test(`browser mock ${kind} writes enforce revisions without mutating rejected updates`, async ({ page }) => {
    const state = await setup(page)
    await login(page)
    const task = state.tasks[1], revision = kind === 'config' ? state.config.revision : task.revision
    const { web_password_configured, ...configValues } = state.config
    const path = kind === 'config' ? '/api/config' : '/api/tasks/archive'
    const payload = kind === 'config'
      ? { ...configValues, web_password: '保存的新密码', temp_dir: '/saved/temp' }
      : { ...task.config, revision, note: '保存的新备注', source_channel: -100555, source_reset: { last_message_id: 123, clear_dedup: false } }
    const snapshot = () => structuredClone({ config: state.config, password: state.settings.password, task })
    const write = (data: Record<string, unknown>) => page.evaluate(async ({ path, data }) => {
      const response = await fetch(path, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-test' }, body: JSON.stringify(data) })
      return { status: response.status, body: await response.json() }
    }, { path, data })
    const baseline = snapshot(), { revision: omitted, ...missingRevision } = payload
    for (const rejected of [missingRevision, { ...payload, revision: revision - 1 }]) {
      expect(await write(rejected)).toMatchObject({ status: 409, body: { error: 'configuration_conflict' } })
      expect(snapshot()).toEqual(baseline)
    }
    expect(await write(payload)).toEqual({ status: 200, body: { success: true, revision: revision + 1 } })
    const saved = snapshot()
    expect(await write(payload)).toMatchObject({ status: 409, body: { error: 'configuration_conflict' } })
    expect(snapshot()).toEqual(saved)
    const read = await page.evaluate(async path => (await fetch(path)).json(), path)
    if (kind === 'config') {
      expect(read).toEqual(state.config)
      expect(read).toMatchObject({ revision: revision + 1, temp_dir: '/saved/temp' })
      expect(read).not.toHaveProperty('web_password')
      expect(state.settings.password).toBe('保存的新密码')
    } else {
      expect(read).toEqual(task)
      expect(read).toMatchObject({ revision: revision + 1, config: { note: '保存的新备注', source_channel: -100555 }, progress: { last_message_id: 123 } })
      expect(read.config).not.toHaveProperty('revision')
      expect(read.config).not.toHaveProperty('source_reset')
    }
    expect(state.errors).toEqual([])
  })
}

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
