import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import ChatView from '../views/ChatView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'login',
      component: LoginView,
    },
    {
      path: '/chat',
      name: 'chat',
      component: ChatView,
    },
  ],
})

// 未登录只能去登录页，已登录直接进聊天页
router.beforeEach((to) => {
  const user = localStorage.getItem('user')
  if (to.name === 'chat' && !user) return { name: 'login' }
  if (to.name === 'login' && user) return { name: 'chat' }
})

export default router
