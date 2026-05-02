<script setup lang="ts">
import { marked } from 'marked'
import faqMd from '~/content/faq.md?raw'

const html = marked(faqMd, { async: false }) as string
</script>

<template>
  <div class="page">
    <div class="card">
      <NuxtLink to="/login" class="back">&#8592; back</NuxtLink>
      <div class="content" v-html="html" />
    </div>
  </div>
</template>

<style scoped>
@font-face {
  font-family: 'Cousine';
  src: url('/cousine-regular.ttf') format('truetype');
  font-weight: normal;
  font-style: normal;
}

* { font-family: 'Cousine', monospace; }

.page {
  min-height: 100vh;
  background: #f5f5f5;
  display: flex;
  justify-content: center;
  padding: 3rem 1rem 4rem;
}

.card {
  width: 100%;
  max-width: 620px;
}

.back {
  display: inline-block;
  font-size: 0.75rem;
  color: #aaa;
  text-decoration: none;
  margin-bottom: 2rem;
}
.back:hover { color: #555; }

.content :deep(h1) {
  font-size: 2rem;
  color: #0a0a0a;
  margin: 0 0 2rem;
  letter-spacing: 0.05em;
}

.content :deep(h2) {
  font-size: 0.85rem;
  color: #0a0a0a;
  margin: 2rem 0 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.content :deep(p) {
  font-size: 0.85rem;
  color: #555;
  line-height: 1.7;
  margin: 0 0 0.5rem;
}

.content :deep(a) {
  color: #0a0a0a;
}
</style>
