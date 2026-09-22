<script setup lang="ts">
import type { Toast } from '../types'

defineProps<{ toasts: Toast[] }>()
defineEmits<{ dismiss: [id: number] }>()
</script>

<template>
  <div class="toast-stack" aria-live="polite" aria-atomic="false">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      class="toast"
      :class="{ 'toast--error': toast.kind === 'error' }"
      role="status"
      @click="$emit('dismiss', toast.id)"
    >
      {{ toast.text }}
    </div>
  </div>
</template>
