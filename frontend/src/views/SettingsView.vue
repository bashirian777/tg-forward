<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAuth } from '../stores/auth'
import { useData } from '../stores/data'
import { usePolling } from '../composables/usePolling'
import Icon from '../components/common/Icon.vue'
import SettingsDialog from '../components/common/SettingsDialog.vue'
const store = useData(), auth = useAuth(), poll = usePolling(['config'], 0), editing = ref(false)
const labels: Record<string, string> = { TG_API_ID: 'API ID', TG_API_HASH: 'API Hash', TG_PHONE: '手机号', TG_BOT_TOKEN: 'Bot token', TG_ADMIN_IDS: '管理员 ID', TG_PROXY_URL: 'Telegram 代理', DB_PATH: '数据库', SESSION_PATH: '登录会话', WEB_HOST: '监听地址', WEB_PORT: '监听端口' }
const sources: Record<string, string> = { environment: '系统环境变量', '.env': '.env', default: '默认值' }
const items = computed(() => {
 const c = store.config
 return c ? [['临时目录', c.temp_dir], ['最大并发媒体组', c.max_concurrent_tasks + ' 个媒体组'], ['最低剩余磁盘', c.min_free_disk_mb + ' MB'], ['下载 / 上传并发', c.download_workers + ' / ' + c.upload_workers], ['临时文件保留周期', c.temp_max_age_hours ? c.temp_max_age_hours + ' 小时' : '自动过期清理已关闭'], ['Web 管理密码', c.web_password_configured ? '已设置' : '未设置'], ['登录有效期', c.web_auth_ttl_hours + ' 小时']] : []
})
</script>
<template><section class="view settings-view" data-page="settings" aria-label="设置"><div v-if="poll.error.value" class="banner" role="alert">{{ poll.error.value }}</div><article class="settings-card"><div class="section-heading"><div><h2>运行设置</h2><p>传输、存储与登录参数。</p></div><button id="edit-config-btn" class="btn" :disabled="!store.config" @click="editing = true"><Icon name="edit" />编辑设置</button></div><dl class="config-panel"><div v-for="[label, value] in items" :key="label" class="config-item"><dt class="k">{{ label }}</dt><dd class="v">{{ value }}</dd></div><div class="config-item full"><dt class="k">本次登录到期</dt><dd class="v">{{ auth.info?.expires_at ? new Date(auth.info.expires_at * 1000).toLocaleString('zh-CN') : '—' }}</dd></div></dl></article>
  <article class="settings-card"><div class="section-heading"><div><h2>Telegram 连接</h2><p>用户账号与 Bot 的实时连接状态。</p></div></div><div class="connection-grid"><div v-for="(service, name) in store.deployment?.services" :key="name" class="connection-item"><div class="connection-title"><span class="dot" :style="{ background: service.state === 'ready' ? 'var(--green)' : 'var(--amber)' }"></span>{{ name === 'telegram' ? 'Telegram 用户账号' : '管理 Bot' }}</div><p>{{ service.message }}</p></div></div></article>
  <details class="settings-card deployment-details"><summary><span>部署信息</span><span class="sub">启动参数与配置来源</span></summary><div class="config-panel"><div v-for="(field, name) in store.deployment?.fields" :key="name" class="config-item"><span class="k">{{ labels[name] || name }}</span><span class="v">{{ 'value' in field ? Array.isArray(field.value) ? field.value.join(', ') || '未设置' : field.value : field.configured ? '已配置' : '未配置' }}</span><span class="sub">来源：{{ sources[field.source] || field.source }}</span></div></div><p class="settings-footnote">启动参数从 .env 或系统环境读取，修改后重启生效。Telegram 登录使用命令行 login。</p></details>
  <SettingsDialog v-if="editing && store.config" :config="store.config" @close="editing = false" />
</section></template>
