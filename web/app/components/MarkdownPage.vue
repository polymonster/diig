<script setup lang="ts">
import { marked } from 'marked'

// a static page rendered from one of the markdown files in app/content
const props = withDefaults(defineProps<{
  source: string   // markdown text, import it with the ?raw suffix
  back?: string    // where the back link goes
}>(), { back: '/' })

// the markdown is our own, checked in, so v-html is safe here
const html = computed(() => marked(props.source, { async: false }) as string)
</script>

<template>
  <div class="card-page top">
    <div class="card wide">
      <NuxtLink :to="back" class="back">&#8592; back</NuxtLink>
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div class="md" v-html="html" />
    </div>
  </div>
</template>

<style scoped>
.md :deep(h1) {
  font-size: 2rem;
  color: var(--ink);
  margin: 0 0 2rem;
  letter-spacing: 0.05em;
}

.md :deep(h2) {
  font-size: 0.85rem;
  color: var(--ink);
  margin: 2rem 0 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.md :deep(p),
.md :deep(li) {
  font-size: 0.85rem;
  color: #555;
  line-height: 1.7;
}

.md :deep(p)      { margin: 0 0 0.5rem; }
.md :deep(ul)     { margin: 0 0 0.5rem; padding-left: 1.2rem; }
.md :deep(a)      { color: var(--ink); }
.md :deep(strong) { color: #333; }
</style>
