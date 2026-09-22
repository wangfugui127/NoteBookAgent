<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import type { Paper } from '../types'

const route = useRoute()
const router = useRouter()
const notebookId = String(route.params.id)

const query = ref('')
const yearFrom = ref<number | undefined>()
const yearTo = ref<number | undefined>()
const papers = ref<Paper[]>([])
const selected = ref<Paper | null>(null)
const loading = ref(false)
const error = ref('')

async function search() {
  if (query.value.trim().length < 2) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get(`/notebooks/${notebookId}/papers/search`, {
      params: { q: query.value, year_from: yearFrom.value, year_to: yearTo.value, limit: 30 },
    })
    papers.value = data.items
    selected.value = papers.value[0] || null
  } catch (value: any) {
    error.value = value.response?.data?.detail || '外部论文检索失败。'
  } finally {
    loading.value = false
  }
}

async function useInChat(paper: Paper) {
  const prompt = [
    '请核对这篇外部论文线索，并与 Notebook 中的全文证据比较：',
    '标题：' + paper.title,
    '作者：' + paper.authors.join(', '),
    '年份：' + (paper.year || '未知'),
    'OpenAlex ID：' + paper.paper_id,
    '注意：当前只有外部元数据和摘要线索，不要把它当成已读取的论文全文。',
  ].join('\n')
  sessionStorage.setItem('paper_prompt:' + notebookId, prompt)
  await router.push('/notebooks/' + notebookId)
}
</script>

<template>
  <section class="papers">
    <header class="papers__head">
      <p class="kicker">OpenAlex</p>
      <h1>搜索外部论文</h1>
      <p>先发现研究线索，再决定是否下载全文并加入 Notebook。</p>
    </header>

    <form class="papers__form" @submit.prevent="search">
      <label class="field field--query">
        <span>研究主题</span>
        <input v-model="query" class="input" placeholder="例如：remote sensing wildfire change detection" />
      </label>
      <label class="field">
        <span>起始年份</span>
        <input v-model="yearFrom" class="input" type="number" min="1800" max="2200" placeholder="2020" />
      </label>
      <label class="field">
        <span>截止年份</span>
        <input v-model="yearTo" class="input" type="number" min="1800" max="2200" placeholder="2026" />
      </label>
      <button class="btn btn--primary" :disabled="loading">{{ loading ? '正在检索' : '搜索论文' }}</button>
    </form>

    <p v-if="error" class="form-error" role="alert">{{ error }}</p>

    <div class="papers__body">
      <div class="paper-results">
        <button
          v-for="paper in papers"
          :key="paper.paper_id"
          class="paper-item"
          :class="{ 'is-selected': selected?.paper_id === paper.paper_id }"
          type="button"
          @click="selected = paper"
        >
          <span class="paper-item__year">{{ paper.year || '—' }}</span>
          <div>
            <h2>{{ paper.title }}</h2>
            <p>
              {{ paper.authors.slice(0, 4).join(', ') }}{{ paper.authors.length > 4 ? ' 等' : '' }}
            </p>
            <small>{{ paper.source }} · 被引 {{ paper.citation_count }}</small>
          </div>
        </button>
        <p v-if="!papers.length" class="empty-note" style="padding: 24px 0">
          搜索一个具体研究主题。可以组合方法、数据集、研究区域和年份，减少泛化结果。
        </p>
      </div>

      <aside class="paper-detail">
        <template v-if="selected">
          <p class="kicker">论文详情</p>
          <h2>{{ selected.title }}</h2>
          <p class="paper-detail__authors">{{ selected.authors.join(', ') }}</p>
          <dl class="paper-detail__stats">
            <div><dt>年份</dt><dd>{{ selected.year || '未知' }}</dd></div>
            <div><dt>来源</dt><dd>{{ selected.source }}</dd></div>
            <div><dt>被引</dt><dd>{{ selected.citation_count }}</dd></div>
          </dl>
          <div class="paper-detail__abstract">
            <p class="kicker">摘要</p>
            <p>{{ selected.abstract || 'OpenAlex 没有提供这篇论文的摘要。' }}</p>
          </div>
          <div class="paper-detail__actions">
            <button class="btn btn--primary" type="button" @click="useInChat(selected)">带入研究对话</button>
            <a v-if="selected.url" :href="selected.url" target="_blank" rel="noreferrer">查看论文来源</a>
          </div>
          <p class="empty-note" style="margin-top: 12px">
            摘要是外部检索线索，不作为 Notebook 全文证据。
          </p>
        </template>
        <p v-else class="empty-note">从左侧选择论文查看作者、摘要和来源。</p>
      </aside>
    </div>
  </section>
</template>
