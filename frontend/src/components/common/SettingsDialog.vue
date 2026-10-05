<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import type { RuntimeConfig } from '../../types/api'
import { api, ApiError } from '../../api/client'
import { mergeFields, type FieldConflict } from '../../mergeFields'
import { useData } from '../../stores/data'
import { useUI } from '../../stores/ui'
import FieldConflicts from './FieldConflicts.vue'
import Modal from './Modal.vue'
const props = defineProps<{ config: RuntimeConfig }>(), emit = defineEmits<{ close: [] }>()
function editable(config: RuntimeConfig) {
  const { temp_dir, temp_max_age_hours, max_concurrent_tasks, min_free_disk_mb, download_workers, upload_workers, web_auth_ttl_hours } = config
  return { temp_dir, temp_max_age_hours, max_concurrent_tasks, min_free_disk_mb, download_workers, upload_workers, web_auth_ttl_hours }
}
const baseline = ref(editable(props.config)), revision = ref(props.config.revision)
const form = reactive({ ...baseline.value, web_password: '' })
const busy = ref(false), error = ref(''), conflict = ref(false), store = useData(), ui = useUI()
const fieldConflicts = ref<FieldConflict[]>([])
const unresolved = computed(() => fieldConflicts.value.some(field => !field.choice))
const fields = [
 { key: 'max_concurrent_tasks', label: '最大并发媒体组', min: 1, max: 32, step: 1 },
 { key: 'min_free_disk_mb', label: '最低剩余磁盘（MB）', min: 0, max: 10000000, step: 1 },
 { key: 'temp_max_age_hours', label: '临时文件保留周期（小时）', min: 0, max: undefined, step: 'any' },
 { key: 'download_workers', label: '下载分块并发数', min: 1, max: 16, step: 1 },
 { key: 'upload_workers', label: '上传分块并发数', min: 1, max: 16, step: 1 },
 { key: 'web_auth_ttl_hours', label: '登录有效期（小时）', min: 0.001, max: undefined, step: 'any' },
] as const
const conflictLabels: Record<string, string> = { ...Object.fromEntries(fields.map(field => [field.key, field.label])), temp_dir: '临时目录', web_password: 'Web 管理密码' }
function resolveField(key: string, choice: 'current' | 'latest') {
  const field = fieldConflicts.value.find(item => item.key === key)
  if (!field) return
  Object.assign(form, { [key]: choice === 'latest' ? field.latest : field.current })
  field.choice = choice
}
async function save() {
  if (busy.value || conflict.value || unresolved.value) return
  busy.value = true; error.value = ''
  try {
    await api.updateConfig({ ...form, revision: revision.value })
    store.changed(); ui.notify('配置已保存'); emit('close')
  } catch (e) { error.value = (e as Error).message; conflict.value = e instanceof ApiError && e.code === 'configuration_conflict' }
  finally { busy.value = false }
}
async function reload() {
  if (busy.value) return
  busy.value = true
  try {
    const current = await api.config(), latest = editable(current)
    const result = mergeFields(baseline.value, editable({ ...props.config, ...form }), latest)
    Object.assign(form, result.merged)
    fieldConflicts.value = result.conflicts
    // Passwords are write-only. A concurrent revision cannot prove that the password is unchanged.
    if (form.web_password) fieldConflicts.value.push({ key: 'web_password', baseline: '', current: form.web_password, latest: '' })
    baseline.value = latest
    revision.value = current.revision
    conflict.value = false
    error.value = fieldConflicts.value.length ? '已读取最新版本，请解决字段冲突后保存。' : '已合并最新版本，当前修改已保留，请核对后保存。'
  } catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}
</script>
<template>
  <Modal id="config-modal" title="编辑运行配置" subtitle="登录设置可随时修改；修改传输参数需先停止全部任务" :busy="busy" @close="emit('close')">
    <form id="config-form" @submit.prevent="save">
      <fieldset class="form-body" :disabled="busy"><div class="form-grid">
        <div class="form-field full"><label for="config-form-temp">临时目录</label><input id="config-form-temp" v-model.trim="form.temp_dir" required /><span class="hint">媒体处理期间用于落盘的工作目录</span></div>
        <div v-for="field in fields" :key="field.key" class="form-field"><label :for="'config-form-' + field.key">{{ field.label }}</label><input :id="'config-form-' + field.key" v-model.number="form[field.key]" type="number" :min="field.min" :max="field.max" :step="field.step" required /></div>
        <div class="form-field full"><label for="config-form-password">Web 管理密码</label><input id="config-form-password" v-model="form.web_password" type="password" autocomplete="new-password" placeholder="留空表示不修改" /><span class="hint">修改后现有登录会失效；有效期修改影响下次登录</span></div>
      </div></fieldset>
      <FieldConflicts :conflicts="fieldConflicts" :labels="conflictLabels" :busy="busy" @resolve="resolveField" />
      <p id="config-form-error" class="modal-error" role="alert">{{ error }}</p>
      <button v-if="conflict" type="button" class="btn" :disabled="busy" @click="reload">读取最新版本并保留输入</button>
      <div class="modal-actions"><button class="btn ghost" type="button" :disabled="busy" @click="emit('close')">取消</button><button id="config-submit" class="btn primary" :class="{ busy }" :disabled="busy || conflict || unresolved">保存配置</button></div>
    </form>
  </Modal>
</template>
