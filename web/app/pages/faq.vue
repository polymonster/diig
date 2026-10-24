<script setup lang="ts">
import source from '~/content/faq.md?raw'
</script>

<template>
  <!-- public page, linked from login, so back goes there -->
  <MarkdownPage :source="source" back="/login" />
</template>
