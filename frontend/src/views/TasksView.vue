<script setup lang="ts">
import { computed, ref } from 'vue'
import { useData } from '../stores/data'
import { useUI } from '../stores/ui'
import { usePolling } from '../composables/usePolling'
import { api, StaleResponse } from '../api/client'
import { bytes } from '../format'
import type { TaskSnapshot, CleanupResult } from '../types/api'
import Icon from '../components/common/Icon.vue'
import TaskCard from '../components/tasks/TaskCard.vue'
import TaskForm from '../components/tasks/TaskForm.vue'
import CheckpointDialog from '../components/tasks/CheckpointDialog.vue'
import ErrorsDialog from '../components/tasks/ErrorsDialog.vue'
const store = useData(), ui = useUI(), poll = usePolling(['tasks'], 5000)
const search = ref(''), filter = ref('all'), editing = ref<TaskSnapshot | null>(null), checkpoint = ref<TaskSnapshot | null>(null), errors = ref<TaskSnapshot | null>(null)
const filters = [['all', '全部'], ['running', '运行中'], ['paused', '已暂停'], ['stopped', '已停止'], ['transfer', '有传输'], ['disabled', '已禁用']]
const visible = computed(() => store.tasks.filter(task => (filter.value === 'all' || filter.value === 'transfer' && !!task.transfer || filter.value === 'disabled' && !task.config.enabled || task.status === filter.value) && [task.task_id, task.config.note, task.config.source_channel, task.config.target_channel].join(' ').toLowerCase().includes(search.value.trim().toLowerCase())))
const stats = computed(() => [
 { id: 'total', title: '全部任务', value: store.tasks.length, icon: 'layers', class: '', hint: '已创建的转发流程' },
 { id: 'running', title: '运行中', value: store.tasks.filter(t => t.status === 'running').length, icon: 'play', class: 'green', hint: '正在处理来源消息' },
 { id: 'paused', title: '已暂停', value: store.tasks.filter(t => t.status === 'paused').length, icon: 'pause', class: 'amber', hint: '保留断点，随时继续' },
 { id: 'forwarded', title: '累计转发', value: store.tasks.reduce((sum, t) => sum + t.progress.forwarded_count, 0).toLocaleString(), icon: 'send', class: '', hint: '已成功转发的消息' },
])
const confirmations: Record<string, [string, string]> = { delete: ['删除任务', '任务配置、断点、去重和续传资料都会删除，此操作不可恢复。'], dedup: ['清空去重记录', '之后可能重复转发已经处理过的媒体。'], skip: ['跳过媒体组', '只跳过当前媒体组，穿插的其他消息仍会处理。'], cleanup: ['清理任务文件', '停止任务并删除其临时媒体、封面和续传资料，保留断点。'], retry: ['从断点重试', '清理当前传输资料，从原断点重新处理；暂停任务保持暂停。'] }
async function action(task: TaskSnapshot, name: string) {
  if (name === 'errors') { errors.value = task; return }
  if (name === 'edit' || name === 'progress') {
    try { const latest = await api.task(task.task_id); if (name === 'edit') editing.value = latest; else checkpoint.value = latest } catch (e) { ui.notify((e as Error).message) }
    return
  }
  const confirm = confirmations[name]
  if (confirm && !await ui.confirm(...confirm, name !== 'retry')) return
  const operations: Record<string, () => Promise<unknown>> = { delete: () => api.remove(task.task_id), dedup: () => api.clearDedup(task.task_id), skip: () => api.skip(task.task_id), cleanup: () => api.cleanupTask(task.task_id), retry: () => api.retry(task.task_id) }
  try { const result = await store.run(task.task_id, name, operations[name] || (() => api.action(task.task_id, name))); ui.notify(name === 'cleanup' ? `已删除 ${(result as CleanupResult).removed} 个文件，释放 ${bytes((result as CleanupResult).freed_bytes)}` : '操作成功') } catch (e) { if (!(e instanceof StaleResponse)) ui.notify((e as Error).message) }
}
</script>
<template><section class="view" data-page="tasks" aria-label="转发任务">
  <div v-if="poll.error.value" class="banner" id="banner" role="alert">部分数据未更新，保留上次结果。{{ poll.error.value }}</div>
  <div class="stats"><div v-for="stat in stats" :key="stat.id" class="stat" :class="stat.class"><div class="stat-top"><span>{{ stat.title }}</span><Icon :name="stat.icon" /></div><div :id="'stat-' + stat.id" class="stat-num">{{ stat.value }}</div><span class="stat-label">{{ stat.hint }}</span></div></div>
  <div class="section-heading"><div><h2>任务列表 <span class="count">{{ store.tasks.length }} 个任务</span></h2><p>从断点继续，按任务独立控制。</p></div><span class="results">{{ visible.length === store.tasks.length ? '' : `显示 ${visible.length} / ${store.tasks.length} 个任务` }}</span></div>
  <div class="controls"><div class="search"><label class="sr-only" for="task-search">搜索任务</label><Icon name="search" /><input id="task-search" v-model="search" type="search" placeholder="搜索任务、ID 或频道…" /></div><div class="chips" id="task-chips" role="group" aria-label="任务筛选"><button v-for="[key, label] in filters" :key="key" class="chip" :class="{ active: filter === key }" :data-filter="key" :aria-pressed="filter === key" @click="filter = key">{{ label }}</button></div></div>
  <div class="task-list" id="tasks"><TaskCard v-for="task in visible" :key="task.task_id" :task="task" :pending="store.pending[task.task_id]" @action="action(task, $event)" /><div v-if="!visible.length" class="empty"><span class="empty-icon"><Icon :name="store.tasks.length ? 'search' : 'layers'" /></span><h3>{{ store.tasks.length ? '没有匹配的任务' : '创建第一个转发任务' }}</h3><p>{{ store.tasks.length ? '试试其他关键词或筛选条件' : '选择来源与目标频道，开始自动转发' }}</p></div></div>
  <TaskForm v-if="editing" :task="editing" @close="editing = null" /><CheckpointDialog v-if="checkpoint" :task="checkpoint" @close="checkpoint = null" /><ErrorsDialog v-if="errors" :task="errors" @close="errors = null" />
</section></template>
