import { createRouter, createWebHistory } from 'vue-router'
import TasksView from '../views/TasksView.vue'
export const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/tasks' },
  { path: '/tasks', component: TasksView, meta: { title: '转发任务', description: '管理转发流程，查看实时进度' } },
  { path: '/resources', component: () => import('../views/ResourcesView.vue'), meta: { title: '系统资源', description: '查看磁盘与临时文件的使用情况' } },
  { path: '/settings', component: () => import('../views/SettingsView.vue'), meta: { title: '设置', description: '管理运行参数与 Telegram 连接' } },
  { path: '/activity', component: () => import('../views/ActivityView.vue'), meta: { title: '操作记录', description: '查看最近的任务与配置变更' } },
] })
router.afterEach(route => document.title = route.meta.title + ' · Forwarder')
