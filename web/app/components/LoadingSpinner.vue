<script setup lang="ts">
// the spinning record. full: centred in the page while it has nothing to show,
// otherwise a small one inline (e.g. "loading more" under a list)
defineProps<{ full?: boolean }>()
</script>

<template>
  <div class="spinner-wrap" :class="{ full }">
    <img src="/spinner.png" class="spinner" alt="loading">
  </div>
</template>

<style scoped>
.spinner-wrap {
  display: flex;
  justify-content: center;
  padding: 1rem 0 2rem;
}
.spinner-wrap.full {
  align-items: center;
  min-height: 60vh;
  padding: 0;
}

.spinner {
  width: 36px;
  height: 36px;
  animation: spin 1.2s linear infinite;
}
.full .spinner {
  width: 80px;
  height: 80px;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
</style>
