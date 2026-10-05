<script setup lang="ts">
import type { FieldConflict } from '../../mergeFields'
defineProps<{ conflicts: FieldConflict[]; labels: Record<string, string>; busy: boolean }>()
const emit = defineEmits<{ resolve: [key: string, choice: 'current' | 'latest'] }>()
function display(value: unknown) {
  if (Array.isArray(value)) return value.length ? value.join('\n') : '（空）'
  if (typeof value === 'boolean') return value ? '开启' : '关闭'
  return value === null || value === '' ? '（空）' : String(value)
}
</script>
<template>
  <section v-if="conflicts.length" class="field-conflicts" aria-label="字段冲突">
    <p role="status">以下字段也被其他人修改。请逐项明确选择后再保存。</p>
    <fieldset v-for="field in conflicts" :key="field.key" :data-conflict-field="field.key" :disabled="busy">
      <legend>{{ labels[field.key] || field.key }}</legend>
      <p v-if="field.key === 'web_password'" class="hint">服务器不返回密码原文，无法比较密码修改；选择最新值表示放弃本次密码修改。</p>
      <div class="conflict-values">
        <div><span>编辑基线</span><pre>{{ field.key === 'web_password' ? '密码原文不可读取' : display(field.baseline) }}</pre></div>
        <div><span>当前输入</span><pre>{{ field.key === 'web_password' ? '已输入新密码（隐藏）' : display(field.current) }}</pre></div>
        <div><span>最新服务器值</span><pre>{{ field.key === 'web_password' ? '保留服务器密码' : display(field.latest) }}</pre></div>
      </div>
      <div class="conflict-choices">
        <label><input type="radio" :name="'conflict-' + field.key" :checked="field.choice === 'current'" @change="emit('resolve', field.key, 'current')" />使用当前输入</label>
        <label><input type="radio" :name="'conflict-' + field.key" :checked="field.choice === 'latest'" @change="emit('resolve', field.key, 'latest')" />使用最新值</label>
      </div>
    </fieldset>
  </section>
</template>
