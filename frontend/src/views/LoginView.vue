<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const email = ref('')
const password = ref('')
const register = ref(false)
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    const path = register.value ? '/auth/register' : '/auth/login'
    const { data } = await api.post(path, { email: email.value, password: password.value })
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    await router.push('/notebooks')
  } catch (value: any) {
    error.value = value.response?.data?.detail || '无法连接研究空间，请检查服务后重试。'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="auth">
    <section class="auth__pitch">
      <div class="auth__brand"><span class="brand-mark">N</span>NotebookAgent</div>
      <div>
        <p class="kicker">论文证据工作台</p>
        <h1 class="auth__title">让回答沿着证据，回到论文原文。</h1>
        <p class="auth__lead">
          上传、检索、比较和引用都在一个 Notebook 里完成。每条结论都能回到页码、字符范围与原始 chunk。
        </p>
      </div>
      <ul class="auth__chain" aria-label="证据链示意">
        <li><em>问题</em><span>不同方法为何得出相反结论？</span></li>
        <li><em>证据</em><span>论文 A · 第 7 页 · chunk 18</span></li>
        <li><em>回答</em><span>区分数据集、指标与实验边界</span></li>
      </ul>
    </section>

    <section class="auth__panel">
      <form class="auth__form" @submit.prevent="submit">
        <header>
          <h2>{{ register ? '创建研究账户' : '进入研究空间' }}</h2>
          <p>{{ register ? '保存你的 Notebook、对话与引用记录。' : '继续处理你的论文和研究问题。' }}</p>
        </header>
        <label class="field">
          <span>邮箱</span>
          <input v-model="email" class="input" autocomplete="email" type="email" required />
        </label>
        <label class="field">
          <span>密码</span>
          <input
            v-model="password"
            class="input"
            :autocomplete="register ? 'new-password' : 'current-password'"
            type="password"
            minlength="8"
            required
          />
        </label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="btn btn--primary" type="submit" :disabled="loading">
          {{ loading ? '正在连接…' : register ? '创建并进入' : '进入 Notebook' }}
        </button>
        <button class="btn btn--quiet" type="button" @click="register = !register">
          {{ register ? '已有账户，直接登录' : '第一次使用，创建账户' }}
        </button>
      </form>
    </section>
  </main>
</template>
