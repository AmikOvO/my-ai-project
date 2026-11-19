<template>
  <div class="chat-page">
    <header class="chat-header">
      <span class="title">企业智能客服</span>
      <span class="user">{{ user?.user_id }}</span>
      <el-button link type="primary" @click="logout">退出登录</el-button>
    </header>

    <main ref="listRef" class="messages">
      <p v-for="(message, index) in messages" :key="index" :class="['bubble', message.role]">
        {{ message.content }}
      </p>
      <p v-if="loading" class="bubble assistant loading">正在思考…</p>

      <!-- 第 3 题：HITL 审批卡片，高危操作由用户决定放行或拒绝 -->
      <div v-if="pending" class="approve-card">
        <p class="approve-title">高危操作待审批</p>
        <p class="approve-line">工具：{{ pending.tool }}</p>
        <p class="approve-line">参数：{{ JSON.stringify(pending.args) }}</p>
        <div class="approve-btns">
          <el-button type="danger" @click="decide('reject')">拒绝</el-button>
          <el-button type="primary" @click="decide('approve')">批准</el-button>
        </div>
      </div>
    </main>

    <footer class="send-box">
      <el-input
        v-model="question"
        placeholder="请输入您的问题"
        :disabled="loading || !!pending"
        @keyup.enter="send"
      />
      <el-button type="primary" :loading="loading" @click="send">发送</el-button>
    </footer>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import request from '@/api/request'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()
const user = userStore.user

const question = ref('')
const messages = ref([])
const pending = ref(null)
const loading = ref(false)
const listRef = ref(null)

function scrollToBottom() {
  nextTick(() => {
    if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
  })
}

// 登录后加载该账号自己的对话记录
async function loadHistory() {
  const { data } = await request.get(`/history/${user.user_id}`)
  messages.value = data.messages
  scrollToBottom()
}

async function send() {
  const text = question.value.trim()
  if (!text || loading.value || pending.value) return
  messages.value.push({ role: 'user', content: text })
  question.value = ''
  loading.value = true
  scrollToBottom()
  try {
    // 后端 RAG 不足时会转 MCP Agent，模型推理较慢，超时放宽
    const { data } = await request.post(
      '/chat',
      { user_id: user.user_id, question: text },
      { timeout: 180000 },
    )
    if (data.status === 'pending') {
      pending.value = data
    } else {
      messages.value.push({ role: 'assistant', content: data.answer })
    }
  } catch (error) {
    messages.value.push({ role: 'assistant', content: '请求失败，请稍后重试。' })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

async function decide(decision) {
  loading.value = true
  try {
    const { data } = await request.post(
      '/approve',
      { user_id: user.user_id, decision },
      { timeout: 180000 },
    )
    messages.value.push({ role: 'assistant', content: data.answer })
  } catch (error) {
    messages.value.push({ role: 'assistant', content: '审批请求失败，请稍后重试。' })
  } finally {
    pending.value = null
    loading.value = false
    scrollToBottom()
  }
}

function logout() {
  userStore.clearUser()
  router.push('/')
}

onMounted(loadHistory)
</script>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 820px;
  margin: 0 auto;
  background: #fff;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid #eee;
}

.chat-header .title {
  font-size: 17px;
  font-weight: 600;
}

.chat-header .user {
  margin-left: auto;
  font-size: 16px;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.bubble {
  width: fit-content;
  max-width: 78%;
  margin: 10px 0;
  padding: 10px 14px;
  border-radius: 10px;
  line-height: 1.6;
  font-size: 14px;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 用户问题靠左，大模型回复靠右 */
.user {
  background: #f2f3f5;
  color: #333;
}

.assistant {
  margin-left: auto;
  background: #e8f0fe;
  color: #1a3d7c;
}

.approve-card {
  margin: 14px 0 0 auto;
  width: 78%;
  padding: 14px 16px;
  border: 1px solid palevioletred;
  border-radius: 10px;
  background: white;
}

.approve-title {
  font-weight: 600;
  color: palevioletred;
}

.approve-line {
  font-size: 13px;
  color: #665200;
  word-break: break-all;
}

.approve-btns {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

.send-box {
  display: flex;
  gap: 8px;
  padding: 14px 20px;
  border-top: 1px solid #eee;
}
</style>
