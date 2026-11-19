import { ref } from 'vue'
import { defineStore } from 'pinia'

// 登录用户信息，刷新页面后依然保留
export const useUserStore = defineStore('user', () => {
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))

  function setUser(data) {
    user.value = data
    localStorage.setItem('user', JSON.stringify(data))
  }

  function clearUser() {
    user.value = null
    localStorage.removeItem('user')
  }

  return { user, setUser, clearUser }
})
