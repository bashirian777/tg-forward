<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import type { TaskSnapshot } from '../../types/api'
import { statusLabels, time } from '../../format'
import Icon from '../common/Icon.vue'
import TransferProgress from './TransferProgress.vue'
const props = defineProps<{ task: TaskSnapshot; pending?: string; canMoveUp?: boolean; canMoveDown?: boolean; moveDisabledReason?: string }>()
const emit = defineEmits<{ action: [action: string] }>()
const menu = ref<HTMLDetailsElement>()
const active = computed(() => props.task.status === 'running')
const action = computed(() => active.value ? 'stop' : 'start')
const label = computed(() => active.value ? '停止任务' : '启动任务')
const rules = computed(() => {
  const c = props.task.config
  return [
    { key: 'source_topic_id', label: '来源话题', value: c.source_topic_id == null ? null : String(c.source_topic_id) },
    { key: 'target_topic_id', label: '目标话题', value: c.target_topic_id == null ? null : String(c.target_topic_id) },
    { key: 'hide_source', label: '隐藏转发来源', value: c.hide_source ? '开启' : null },
    { key: 'caption_prefix', label: '描述前缀', value: c.caption_prefix.trim() ? c.caption_prefix : null },
    { key: 'filter_keywords', label: '跳过关键词', value: c.filter_keywords.length ? c.filter_keywords.join('、') : null },
    { key: 'required_hashtags', label: '必须包含的 Hashtag', value: c.required_hashtags.length ? c.required_hashtags.join('、') : null },
    { key: 'remove_hashtags', label: '删除匹配标签', value: c.remove_hashtags ? '开启' : null },
    { key: 'send_as_channel', label: '以目标频道身份发送', value: c.send_as_channel ? '开启' : null },
    { key: 'include_topic_name', label: '标题携带来源话题名', value: c.include_topic_name ? '开启' : null },
    { key: 'require_video', label: '仅转发含视频的消息', value: c.require_video ? '开启' : null },
    { key: 'deduplicate', label: '媒体 ID 去重', value: c.deduplicate ? '开启' : null },
  ].filter(rule => rule.value !== null)
})
function closeMenuOutside(event: PointerEvent) {
  if (menu.value?.open && event.target instanceof Node && !menu.value.contains(event.target)) menu.value.open = false
}
onMounted(() => document.addEventListener('pointerdown', closeMenuOutside, true))
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeMenuOutside, true))
function select(value: string) { if (menu.value) menu.value.open = false; emit('action', value) }
</script>
<template><article class="card task-card" :data-card-id="task.task_id" :aria-busy="!!pending">
  <div class="task-head"><div class="task-main"><div class="task-avatar"><Icon name="send" /></div><div><h3 class="task-title">{{ task.config.note || task.task_id }}</h3><span class="task-id">{{ task.task_id }}</span></div></div><div class="task-badges"><span class="badge" :class="task.status"><span class="dot"></span>{{ statusLabels[task.status] }}</span><span v-if="!task.config.enabled" class="badge off">已禁用</span></div></div>
  <div class="route"><div><span class="route-label">来源频道</span><code>{{ task.config.source_channel }}</code></div><Icon name="arrow" /><div><span class="route-label">目标频道</span><code>{{ task.config.target_channel }}</code></div></div>
  <div class="task-meta"><div><span class="k">已转发</span><span class="v">{{ task.progress.forwarded_count }}<small> 条</small></span></div><div><span class="k">当前断点</span><span class="v mono">{{ task.progress.last_message_id }}</span></div><div><span class="k">转发间隔</span><span class="v">{{ task.config.min_delay }}–{{ task.config.max_delay }}<small> 秒</small></span></div><div><span class="k">最后转发</span><span class="v">{{ time(task.progress.last_forward_time) }}</span></div></div>
  <details v-if="rules.length" class="task-rules"><summary>转发规则 <span>{{ rules.length }} 项</span></summary><dl class="task-rule-list"><div v-for="rule in rules" :key="rule.key" :data-rule="rule.key"><dt>{{ rule.label }}</dt><dd>{{ rule.value }}</dd></div></dl></details>
  <TransferProgress v-if="task.transfer" :transfer="task.transfer" />
  <div class="task-actions"><div class="task-secondary"><button v-if="task.errors?.unresolved" class="btn error-button" @click="emit('action', 'errors')"><Icon name="alert" />查看错误 <span class="error-count">{{ task.errors.unresolved }}</span></button><span v-else class="task-ready">{{ pending ? '正在执行操作…' : !task.config.enabled ? '请先启用任务' : task.status === 'stopped' ? '等待启动' : '从当前断点继续' }}</span></div>
    <div class="task-buttons"><button class="btn" data-action="edit" :disabled="active || !!pending" :title="active ? '请先停止任务再编辑' : '编辑任务'" @click="emit('action', 'edit')"><Icon name="edit" />编辑</button><button class="btn primary" :class="{ busy: pending === action }" :data-action="action" :disabled="!!pending || !active && !task.config.enabled" :title="!active && !task.config.enabled ? '请先编辑并启用任务' : label" @click="emit('action', action)"><Icon :name="active ? 'stop' : 'play'" /><span>{{ label }}</span></button>
      <details ref="menu" class="task-menu"><summary aria-label="更多任务操作"><Icon name="more" /></summary><div class="menu-panel">
        <button class="btn menu-action" :disabled="!canMoveUp || !!moveDisabledReason || !!pending" :title="moveDisabledReason || (canMoveUp ? '上移一位' : '已经是第一项')" data-action="up" @click="select('up')"><Icon name="up" />上移</button>
        <button class="btn menu-action" :disabled="!canMoveDown || !!moveDisabledReason || !!pending" :title="moveDisabledReason || (canMoveDown ? '下移一位' : '已经是最后一项')" data-action="down" @click="select('down')"><Icon name="down" />下移</button>
        <div class="menu-divider"></div>
        <button class="btn menu-action" :disabled="active || !!pending" data-action="progress" @click="select('progress')"><Icon name="flag" />修改断点</button>
        <template v-if="task.transfer"><button class="btn menu-action" :disabled="!!pending" data-action="retry" @click="select('retry')"><Icon name="refresh" />从断点重试</button><button class="btn menu-action" :disabled="!!pending" data-action="skip" @click="select('skip')"><Icon name="skip" />跳过媒体组</button></template>
        <div class="menu-divider"></div><button class="btn menu-action danger" :disabled="!!pending" data-action="cleanup" @click="select('cleanup')"><Icon name="trash" />清理任务文件</button><button class="btn menu-action danger" :disabled="active || !!pending" data-action="dedup" @click="select('dedup')"><Icon name="eraser" />清空去重记录</button><button class="btn menu-action danger" :disabled="!!pending" data-action="delete" @click="select('delete')"><Icon name="trash" />删除任务</button>
      </div></details>
    </div>
  </div>
</article></template>
