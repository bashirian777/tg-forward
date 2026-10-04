<script setup lang="ts">
import { ref } from 'vue'
import { useAuth } from '../../stores/auth'
import Icon from './Icon.vue'
const auth = useAuth(), password = ref(''), busy = ref(false)
async function submit() {
  busy.value = true; auth.error = ''
  try { await auth.login(password.value); password.value = '' } catch (e) { auth.error = (e as Error).message } finally { busy.value = false }
}
</script>
<template>
  <div class="auth-gate" id="auth-gate"><div class="auth-panel">
    <div class="auth-brand"><div class="brand-mark"><Icon name="send" /></div><span>Forwarder</span></div>
    <h1>欢迎回来</h1><p>登录以管理你的 Telegram 转发任务。</p>
    <form id="auth-form" @submit.prevent="submit"><label for="auth-password">管理密码</label>
      <input id="auth-password" v-model="password" type="password" autocomplete="current-password" placeholder="输入 Web 管理密码" required />
      <button id="auth-submit" class="btn primary block" :class="{ busy }" :disabled="busy">登录控制台<Icon name="arrow" /></button>
      <p id="auth-error" class="auth-error" role="alert">{{ auth.error }}</p>
    </form><span class="auth-caption">Telegram Forwarder</span>
  </div></div>
</template>
