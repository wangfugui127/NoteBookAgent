<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

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
      <nav class="topnav">
        <router-link class="topnav__link" to="/notebooks">Notebook</router-link>
        <router-link class="topnav__link" to="/evaluations">评测</router-link>
      </nav>
      <span class="topbar-spacer" />
      <button class="btn btn--quiet btn--sm" type="button" @click="logout">退出</button>
    </header>
    <router-view />
  </div>
</template>
