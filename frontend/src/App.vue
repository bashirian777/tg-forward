<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useAuth } from './stores/auth'
import { useData } from './stores/data'
import { useUI } from './stores/ui'
import AdminLayout from './layouts/AdminLayout.vue'
import LoginGate from './components/common/LoginGate.vue'
import Modal from './components/common/Modal.vue'
import Icon from './components/common/Icon.vue'
const auth = useAuth(), data = useData(), ui = useUI()
watch(() => auth.ready, ready => { if (!ready) { data.reset(); ui.resolve(false) } })
onMounted(auth.init)
</script>
<template>
  <div v-if="auth.loading" class="empty" role="status">正在连接服务…</div>
  <AdminLayout v-else-if="auth.ready" />
  <LoginGate v-else />
  <div v-if="ui.toast" class="toast show" id="toast" role="status" aria-live="polite"><Icon name="check" /><span id="toast-text">{{ ui.toast }}</span></div>
  <Modal v-if="ui.confirmation && auth.ready" id="confirm-modal" :title="ui.confirmation.title" small @close="ui.resolve(false)">
    <p id="confirm-message">{{ ui.confirmation.message }}</p>
    <div class="modal-actions"><button class="btn ghost" @click="ui.resolve(false)">取消</button><button id="confirm-ok" class="btn" :class="ui.confirmation.danger ? 'danger' : 'primary'" @click="ui.resolve(true)">确认</button></div>
  </Modal>
</template>
