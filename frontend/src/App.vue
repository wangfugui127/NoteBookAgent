<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const notebookId = computed(() => String(route.params.id || ''))

function logout() {
  localStorage.clear()
  router.push('/login')
}
</script>

<template>
  <div class="app-shell">
    <header v-if="route.path !== '/login'" class="topbar">
      <router-link class="brand" to="/notebooks">
        <span class="brand-mark">N</span>
        NotebookAgent
      </router-link>
      <nav v-if="notebookId" class="topnav" aria-label="Notebook 导航">
        <router-link :to="`/notebooks/${notebookId}`">研究对话</router-link>
        <router-link :to="`/notebooks/${notebookId}/papers`">搜索论文</router-link>
      </nav>
      <span class="topbar-spacer" />
      <button class="btn btn--quiet btn--sm" type="button" @click="logout">退出</button>
    </header>
    <router-view />
  </div>
</template>
