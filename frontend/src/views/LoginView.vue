<template>
  <div class="login-page">
    <el-card class="login-card">
      <h2>登录</h2>
  
      <el-form @submit.prevent="login">
        <el-form-item>
          <el-input v-model="username" placeholder="用户名" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="password" type="password" placeholder="密码" show-password />
        </el-form-item>
        <el-button type="primary" class="login-btn" :loading="loading" @click="login">
          登录
        </el-button>
      </el-form>
  
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '@/api/request'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

const username = ref('')
const password = ref('')
const loading = ref(false)

async function login() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const { data } = await request.post('/login', {
      username: username.value,
      password: password.value,
    })
    // 不同账号用 user_id 区分，聊天记录互不影响
    userStore.setUser(data)
    ElMessage.success('登录成功')
    router.push('/chat')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: #f4f6f9;
}

.login-card {
  width: 360px;
  text-align: center;
}

.tip {
  margin: 12px 0;
  font-size: 13px;
  color: #888;
}

.login-btn {
  width: 100%;
}
</style>
