<script setup lang="ts">
import { computed, reactive, ref, watch, toRaw } from 'vue'
import { api, ApiError } from '../../api/client'
import { useData } from '../../stores/data'
import { useUI } from '../../stores/ui'
import FieldConflicts from '../common/FieldConflicts.vue'
import { mergeFields, type FieldConflict } from '../../mergeFields'
import Modal from '../common/Modal.vue'
import type { TaskConfig, TaskSnapshot } from '../../types/api'
const props = defineProps<{ task?: TaskSnapshot }>(), emit = defineEmits<{ close: [] }>()
const store = useData(), ui = useUI(), error = ref(''), busy = ref(false), conflict = ref(false)
const defaults: TaskConfig = { task_id: '', source_channel: 0, target_channel: 0, min_delay: 10, max_delay: 20,
 enabled: true, note: '', hide_source: true, caption_prefix: '', filter_keywords: [], required_hashtags: [],
 target_topic_id: null, source_topic_id: null, remove_hashtags: false, send_as_channel: false, deduplicate: false }
const form = reactive<TaskConfig>(structuredClone(toRaw(props.task?.config || defaults)))
const original = ref<TaskConfig | undefined>(props.task ? structuredClone(toRaw(props.task.config)) : undefined), revision = ref(props.task?.revision || 0)
const fieldConflicts = ref<FieldConflict[]>([])
const unresolved = computed(() => fieldConflicts.value.some(field => !field.choice))
let applyingMerge = false
const keywords = ref(form.filter_keywords.join('\n')), hashtags = ref(form.required_hashtags.join('\n'))
const startId = ref(0), clearDedup = ref(true)
const sourceChanged = computed(() => !!original.value && (form.source_channel !== original.value.source_channel || form.source_topic_id !== original.value.source_topic_id))
const lines = (value: string) => value.split('\n').map(item => item.trim()).filter(Boolean)
watch(() => form.hide_source, hide => { if (!applyingMerge && !hide) { form.caption_prefix = ''; form.remove_hashtags = false; form.send_as_channel = false } }, { flush: 'sync' })
watch(() => form.send_as_channel, enabled => { if (!applyingMerge && enabled) form.hide_source = true }, { flush: 'sync' })
watch(hashtags, text => { if (!applyingMerge && !lines(text).length) form.remove_hashtags = false }, { flush: 'sync' })
const numbers = [
 { key: 'source_channel', label: '来源频道 ID', hint: '频道或群组使用负数 ID', required: true },
 { key: 'target_channel', label: '目标频道 ID', hint: '登录账号需要具有发送权限', required: true },
 { key: 'min_delay', label: '最小转发间隔（秒）', min: 0, step: 0.1, required: true },
 { key: 'max_delay', label: '最大转发间隔（秒）', min: 0, step: 0.1, required: true },
] as const
const switches = [
 { key: 'enabled', label: '启用任务', description: '关闭后任务无法启动' },
 { key: 'hide_source', label: '隐藏转发来源', description: '目标消息不显示“转发自”' },
 { key: 'remove_hashtags', label: '删除已匹配 Hashtag', description: '从转发描述中移除匹配的标签' },
 { key: 'send_as_channel', label: '以目标频道身份发送', description: '需要登录账号具有相应管理员权限' },
 { key: 'deduplicate', label: '媒体 ID 去重', description: '识别同一 Telegram 媒体；重新上传的相同内容可能无法识别' },
] as const
function locked(key: string) { return key === 'hide_source' && form.send_as_channel || key === 'remove_hashtags' && (!form.hide_source || !lines(hashtags.value).length) || key === 'send_as_channel' && !form.hide_source }
const conflictLabels: Record<string, string> = {
  ...Object.fromEntries([...numbers, ...switches].map(field => [field.key, field.label])),
  task_id: '任务 ID', note: '任务名称 / 备注', source_topic_id: '来源话题 ID', target_topic_id: '目标话题 ID',
  caption_prefix: '描述前缀', filter_keywords: '跳过关键词', required_hashtags: '必须包含的 Hashtag',
}
function inputConfig(): TaskConfig { return { ...toRaw(form), filter_keywords: lines(keywords.value), required_hashtags: lines(hashtags.value) } }
function applyConfig(config: TaskConfig) {
  applyingMerge = true
  try {
    Object.assign(form, config)
    keywords.value = config.filter_keywords.join('\n')
    hashtags.value = config.required_hashtags.join('\n')
  } finally { applyingMerge = false }
}
function resolveField(key: string, choice: 'current' | 'latest') {
  const field = fieldConflicts.value.find(item => item.key === key)
  if (!field) return
  applyConfig({ ...inputConfig(), [key]: choice === 'latest' ? field.latest : field.current })
  field.choice = choice
}
async function reloadRevision() {
  if (!props.task || !original.value || busy.value) return
  busy.value = true
  try {
    const latest = await api.task(props.task.task_id)
    const result = mergeFields(original.value, inputConfig(), latest.config)
    applyConfig(result.merged)
    fieldConflicts.value = result.conflicts
    revision.value = latest.revision
    original.value = structuredClone(latest.config)
    conflict.value = false
    error.value = result.conflicts.length ? '已读取最新版本，请解决字段冲突后保存。' : '已合并最新版本，当前修改已保留，请核对后保存。'
  } catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}
async function submit() {
  if (busy.value || conflict.value || unresolved.value) return
  error.value = ''
  if (!/^[A-Za-z0-9_-]{1,48}$/.test(form.task_id)) { error.value = '任务 ID 仅允许 1–48 位字母、数字、下划线和短横线'; return }
  if (![form.source_channel, form.target_channel].every(value => Number.isSafeInteger(value) && value < 0)) { error.value = '来源和目标频道 ID 必须是负整数'; return }
  if (form.source_channel === form.target_channel) { error.value = '来源与目标频道不能相同'; return }
  if (form.min_delay > form.max_delay) { error.value = '最小延迟不能大于最大延迟'; return }
  const payload = inputConfig()
  let source_reset: { last_message_id: number; clear_dedup: boolean } | undefined
  if (sourceChanged.value) {
    if (!await ui.confirm('更换来源', '将清理旧传输，使用新起点和所选去重设置，确认更换来源？')) return
    source_reset = { last_message_id: startId.value, clear_dedup: clearDedup.value }
  }
  busy.value = true
  try {
    await store.run(form.task_id, 'save', () => props.task ? api.update(props.task.task_id, { ...payload, revision: revision.value, source_reset }) : api.create(payload))
    ui.notify(props.task ? '任务已更新' : '任务已创建'); emit('close')
  } catch (e) { error.value = (e as Error).message; conflict.value = e instanceof ApiError && e.code === 'configuration_conflict' }
  finally { busy.value = false }
}
</script>
<template>
  <Modal id="task-modal" :title="task ? '编辑任务' : '新建任务'" :subtitle="task ? '修改配置前需先停止任务' : '创建后即可在列表中启动'" :busy="busy" @close="emit('close')">
    <form id="task-form" @submit.prevent="submit">
      <fieldset :disabled="busy" class="form-body">
      <fieldset class="form-section"><legend>基本信息</legend><div class="form-grid">
        <div class="form-field"><label for="task-form-id">任务 ID</label><input id="task-form-id" v-model.trim="form.task_id" :disabled="!!task || busy" required maxlength="48" placeholder="例如 daily_forward" /><span class="hint">字母、数字、下划线和短横线</span></div>
        <div class="form-field"><label for="task-form-note">任务名称 / 备注</label><input id="task-form-note" v-model.trim="form.note" maxlength="120" placeholder="一个便于识别的名称" /></div>
        <div v-for="field in numbers" :key="field.key" class="form-field"><label :for="'task-form-' + field.key">{{ field.label }}</label>
          <input :id="'task-form-' + field.key" v-model.number="form[field.key]" type="number" :min="'min' in field ? field.min : undefined" :step="'step' in field ? field.step : 1" required />
          <span v-if="'hint' in field" class="hint">{{ field.hint }}</span>
        </div>
      </div></fieldset>
      <details class="advanced-fields" id="task-advanced" :open="!!task"><summary>话题、描述与过滤规则</summary><div class="form-grid">
        <div class="form-field"><label for="task-form-source-topic">来源话题 ID</label><input id="task-form-source-topic" :value="form.source_topic_id" @input="form.source_topic_id = ($event.target as HTMLInputElement).value ? Number(($event.target as HTMLInputElement).value) : null" type="number" min="1" step="1" placeholder="可选" /></div>
        <div class="form-field"><label for="task-form-topic">目标话题 ID</label><input id="task-form-topic" :value="form.target_topic_id" @input="form.target_topic_id = ($event.target as HTMLInputElement).value ? Number(($event.target as HTMLInputElement).value) : null" type="number" min="1" step="1" placeholder="可选" /></div>
        <div class="form-field full"><label for="task-form-prefix">描述前缀</label><input id="task-form-prefix" v-model="form.caption_prefix" :disabled="!form.hide_source" placeholder="转发描述前添加的文字" /><span v-if="!form.hide_source" class="hint">显示来源时保留原描述</span></div>
        <div class="form-field"><label for="task-form-keywords">跳过关键词</label><textarea id="task-form-keywords" v-model="keywords" placeholder="每行一个关键词" /><span class="hint">包含任意一个关键词时跳过</span></div>
        <div class="form-field"><label for="task-form-hashtags">必须包含的 Hashtag</label><textarea id="task-form-hashtags" v-model="hashtags" placeholder="每行一个标签" /><span class="hint">至少包含一个才转发，留空不过滤</span></div>
      </div></details>
      <fieldset class="form-section"><legend>转发行为</legend><div class="switches">
        <label v-for="item in switches" :key="item.key" class="switch" :class="{ locked: locked(item.key) }"><input :id="'task-form-' + item.key" v-model="form[item.key]" type="checkbox" :disabled="locked(item.key)" /><span class="track"></span><span class="copy"><span class="title">{{ item.label }}</span><span class="desc">{{ item.description }}</span></span></label>
      </div></fieldset>
      <fieldset v-if="sourceChanged" id="source-reset-options" class="form-section"><legend>来源变更</legend><div class="form-grid"><div class="form-field"><label for="source-reset-id">新来源起始消息 ID</label><input id="source-reset-id" v-model.number="startId" type="number" min="0" step="1" required /></div><label><input id="source-reset-dedup" v-model="clearDedup" type="checkbox" />清空旧来源的去重记录</label></div></fieldset>
      </fieldset>
      <FieldConflicts :conflicts="fieldConflicts" :labels="conflictLabels" :busy="busy" @resolve="resolveField" />
      <p class="modal-error" id="task-form-error" role="alert">{{ error }}</p><button v-if="conflict" type="button" class="btn" :disabled="busy" @click="reloadRevision">读取最新版本并保留输入</button>
      <div class="modal-actions"><button type="button" class="btn ghost" :disabled="busy" @click="emit('close')">取消</button><button id="task-submit" class="btn primary" :class="{ busy }" :disabled="busy || conflict || unresolved">保存任务</button></div>
    </form>
  </Modal>
</template>
