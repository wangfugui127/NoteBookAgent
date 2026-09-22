import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import LoginView from './views/LoginView.vue'
import NotebooksView from './views/NotebooksView.vue'
import WorkspaceView from './views/WorkspaceView.vue'
import PaperSearchView from './views/PaperSearchView.vue'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/notebooks' },
    { path: '/login', component: LoginView },
    { path: '/notebooks', component: NotebooksView },
    { path: '/notebooks/:id', component: WorkspaceView },
    { path: '/notebooks/:id/papers', component: PaperSearchView },
  ],
})

router.beforeEach((to) => {
  if (to.path !== '/login' && !localStorage.getItem('access_token')) return '/login'
})

createApp(App).use(createPinia()).use(router).mount('#app')
