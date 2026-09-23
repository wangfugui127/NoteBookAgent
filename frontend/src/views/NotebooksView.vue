<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'

interface Notebook {
  id: string
  title: string
  description: string
  created_at: string
}

const notebooks = ref<Notebook[]>([])
const title = ref('')
const error = ref('')
const pendingDelete = ref('')
const deleting = ref(false)

async function load() {
  try {
    notebooks.value = (await api.get('/notebooks')).data
    error.value = ''
  } catch {
    error.value = 'Notebook 列表加载失败，请刷新页面。'
  }
}

async function create() {
  if (!title.value.trim()) return
  await api.post('/notebooks', { title: title.value, description: '' })
  title.value = ''
  await load()
}

async function remove(id: string) {
  if (deleting.value) return
  deleting.value = true
  try {
    await api.delete(`/notebooks/${id}`)
    pendingDelete.value = ''
    await load()
  } catch {
    error.value = '删除 Notebook 失败，请稍后重试。'
  } finally {
    deleting.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="library">
    <header class="library__head">
      <div>
        <p class="kicker">你的研究资料库</p>
        <h1 class="library__title">选择一个 Notebook 继续</h1>
      </div>
      <form class="library__create" @submit.prevent="create">
        <label class="field">
          <span>新 Notebook 名称</span>
          <input v-model="title" class="input" placeholder="例如：遥感火灾变化检测" />
        </label>
        <button class="btn btn--primary" type="submit">创建</button>
      </form>
    </header>

    <p v-if="error" class="form-error" role="alert">{{ error }}</p>

    <div class="notebook-list">
      <article v-for="(item, index) in notebooks" :key="item.id" class="notebook-card">
        <span class="notebook-card__index">{{ String(index + 1).padStart(2, '0') }}</span>
        <router-link class="notebook-card__main" :to="`/notebooks/${item.id}`">
          <h2>{{ item.title }}</h2>
          <p>{{ item.description || '上传论文，建立一个可追溯的研究对话。' }}</p>
        </router-link>
        <div class="notebook-card__meta">
          <time>{{ new Date(item.created_at).toLocaleDateString() }}</time>
          <template v-if="pendingDelete === item.id">
            <button
              class="notebook-card__danger"
              type="button"
              :disabled="deleting"
              @click="remove(item.id)"
            >
              删除
            </button>
            <button class="notebook-card__cancel" type="button" @click="pendingDelete = ''">
              取消
            </button>
          </template>
          <button
            v-else
            class="notebook-card__delete"
            type="button"
            title="删除这个 Notebook"
            :aria-label="`删除 Notebook：${item.title}`"
            @click="pendingDelete = item.id"
          >
            ✕
          </button>
        </div>
      </article>
    </div>

    <p v-if="!notebooks.length && !error" class="empty-note" style="padding: 40px 0">
      创建第一个 Notebook，然后上传论文、检索外部研究并启动证据优先的对话。
    </p>
  </section>
</template>
