<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '../stores/auth'
import { useData } from '../stores/data'
import { useUI } from '../stores/ui'
import { usePolling } from '../composables/usePolling'
import Icon from '../components/common/Icon.vue'
import TaskForm from '../components/tasks/TaskForm.vue'
const auth = useAuth(), data = useData(), ui = useUI(), route = useRoute()
const poll = usePolling(['deployment'], 15000)
const theme = ref(localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'))
document.documentElement.dataset.theme = theme.value
function toggleTheme() { theme.value = theme.value === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = theme.value; localStorage.setItem('theme', theme.value) }
const nav = [['tasks', '转发任务', 'layers'], ['resources', '系统资源', 'database'], ['settings', '设置', 'sliders'], ['activity', '操作记录', 'history']]
const health = computed(() => data.deployment?.services.telegram)
const form = ref(false)
async function logout() { try { await auth.logout() } catch (e) { ui.notify((e as Error).message) } }
</script>
<template>
  <div id="app-content"><div class="admin-layout">
    <aside class="sidebar"><div class="sidebar-brand"><div class="brand-mark"><Icon name="send" /></div><div><b>Forwarder</b><span>Telegram 转发控制台</span></div></div>
      <div class="nav-label">工作空间</div><nav class="sidebar-nav" aria-label="管理导航">
        <RouterLink v-for="[key, title, icon] in nav" :key="key" :to="'/' + key" class="nav-btn" :class="{ active: route.path === '/' + key }" :data-view="key"><Icon :name="icon" /><span>{{ title }}</span></RouterLink>
      </nav>
      <div class="sidebar-bottom"><div class="sidebar-status"><span class="dot" id="health-dot" :style="{ background: health?.state === 'ready' ? 'var(--green)' : 'var(--amber)' }"></span><div><b id="sidebar-health">{{ health?.message || '正在连接…' }}</b><span>由用户账号执行转发</span></div></div>
        <button id="logout-btn" class="btn ghost logout-btn" @click="logout"><Icon name="lock" />退出登录</button>
      </div>
    </aside>
    <main class="main-area"><header class="topbar"><div><h1 id="page-title">{{ route.meta.title }}</h1><p id="page-description">{{ route.meta.description }}</p></div>
      <div class="topbar-actions"><button id="refresh-btn" class="icon-btn" aria-label="刷新数据" @click="data.changed"><Icon name="refresh" /></button><button id="theme-btn" class="icon-btn" :aria-label="theme === 'dark' ? '切换浅色主题' : '切换深色主题'" @click="toggleTheme"><Icon :name="theme === 'dark' ? 'sun' : 'moon'" /></button><button id="new-task-btn" class="btn primary" @click="form = true"><Icon name="plus" /><span>新建任务</span></button></div>
    </header><div class="page-content">
      <div v-if="poll.error.value" class="banner" role="alert">连接状态未更新，保留上次结果。{{ poll.error.value }}</div>
      <RouterView />
      <footer><span class="refresh-indicator"><span class="dot"></span><span>按页面自动更新</span></span><span>上次更新 <time id="last-updated">{{ data.lastUpdated || '—' }}</time></span></footer>
    </div></main>
  </div></div>
  <TaskForm v-if="form" @close="form = false" />
</template>
