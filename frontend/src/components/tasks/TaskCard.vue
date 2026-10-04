<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TaskSnapshot } from '../../types/api'
import { statusLabels, time } from '../../format'
import Icon from '../common/Icon.vue'
import TransferProgress from './TransferProgress.vue'
const props = defineProps<{ task: TaskSnapshot; pending?: string }>()
const emit = defineEmits<{ action: [action: string] }>()
const menu = ref<HTMLDetailsElement>()
const action = computed(() => props.task.status === 'running' ? 'pause' : props.task.status === 'paused' ? 'resume' : 'start')
const label = computed(() => ({ start: '启动任务', pause: '暂停', resume: '继续任务' })[action.value])
const active = computed(() => ['running', 'paused'].includes(props.task.status))
const rules = computed(() => {
  const c = props.task.config, values = []
  if (c.source_topic_id) values.push('来源话题 ' + c.source_topic_id)
  if (c.target_topic_id) values.push('目标话题 ' + c.target_topic_id)
  if (c.filter_keywords?.length) values.push('过滤：' + c.filter_keywords.join('、'))
  if (c.required_hashtags?.length) values.push('标签：' + c.required_hashtags.join('、'))
  if (c.send_as_channel) values.push('以频道身份发送')
  if (c.deduplicate) values.push('媒体 ID 去重')
  return values
})
function select(value: string) { if (menu.value) menu.value.open = false; emit('action', value) }
</script>
<template><article class="card task-card" :data-card-id="task.task_id" :aria-busy="!!pending">
  <div class="task-head"><div class="task-main"><div class="task-avatar"><Icon name="send" /></div><div><h3 class="task-title">{{ task.config.note || task.task_id }}</h3><span class="task-id">{{ task.task_id }}</span></div></div><div class="task-badges"><span class="badge" :class="task.status"><span class="dot"></span>{{ statusLabels[task.status] }}</span><span v-if="!task.config.enabled" class="badge off">已禁用</span></div></div>
  <div class="route"><div><span class="route-label">来源频道</span><code>{{ task.config.source_channel }}</code></div><Icon name="arrow" /><div><span class="route-label">目标频道</span><code>{{ task.config.target_channel }}</code></div></div>
  <div class="task-meta"><div><span class="k">已转发</span><span class="v">{{ task.progress.forwarded_count }}<small> 条</small></span></div><div><span class="k">当前断点</span><span class="v mono">{{ task.progress.last_message_id }}</span></div><div><span class="k">转发间隔</span><span class="v">{{ task.config.min_delay }}–{{ task.config.max_delay }}<small> 秒</small></span></div><div><span class="k">最后转发</span><span class="v">{{ time(task.progress.last_forward_time) }}</span></div></div>
  <details v-if="rules.length" class="task-rules"><summary>转发规则 <span>{{ rules.length }} 项</span></summary><div class="tags"><span v-for="rule in rules" :key="rule" class="tag">{{ rule }}</span></div></details>
  <TransferProgress v-if="task.transfer" :transfer="task.transfer" />
  <div class="task-actions"><div class="task-secondary"><button v-if="task.errors?.unresolved" class="btn error-button" @click="emit('action', 'errors')"><Icon name="alert" />查看错误 <span class="error-count">{{ task.errors.unresolved }}</span></button><span v-else class="task-ready">{{ pending ? '正在执行操作…' : !task.config.enabled ? '请先启用任务' : task.status === 'stopped' ? '等待启动' : '从当前断点继续' }}</span></div>
    <div class="task-buttons"><button class="btn" data-action="edit" :disabled="active || !!pending" :title="active ? '请先停止任务再编辑' : '编辑任务'" @click="emit('action', 'edit')"><Icon name="edit" />编辑</button><button class="btn primary" :class="{ busy: pending === action }" :data-action="action" :disabled="!!pending || !task.config.enabled" :title="!task.config.enabled ? '请先编辑并启用任务' : label" @click="emit('action', action)"><Icon :name="action === 'start' ? 'play' : action" /><span>{{ label }}</span></button>
      <details ref="menu" class="task-menu"><summary aria-label="更多任务操作"><Icon name="more" /></summary><div class="menu-panel">
        <button class="btn menu-action" :disabled="active || !!pending" data-action="progress" @click="select('progress')"><Icon name="flag" />修改断点</button>
        <button v-if="active" class="btn menu-action" :disabled="!!pending" data-action="stop" @click="select('stop')"><Icon name="stop" />停止任务</button>
        <template v-if="task.transfer"><button class="btn menu-action" :disabled="!!pending" data-action="retry" @click="select('retry')"><Icon name="refresh" />从断点重试</button><button class="btn menu-action" :disabled="!!pending" data-action="skip" @click="select('skip')"><Icon name="skip" />跳过媒体组</button></template>
        <div class="menu-divider"></div><button class="btn menu-action danger" :disabled="!!pending" data-action="cleanup" @click="select('cleanup')"><Icon name="trash" />清理任务文件</button><button class="btn menu-action danger" :disabled="active || !!pending" data-action="dedup" @click="select('dedup')"><Icon name="eraser" />清空去重记录</button><button class="btn menu-action danger" :disabled="!!pending" data-action="delete" @click="select('delete')"><Icon name="trash" />删除任务</button>
      </div></details>
    </div>
  </div>
</article></template>
