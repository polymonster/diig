<script setup lang="ts">
// On-screen console for debugging on phones, toggled from the menu. Mounted
// for the whole session so it has the logs from before it was switched on

interface LogLine { type: string, msg: string, t: string }

const showDebug = useState('showDebug', () => storageGet('showDebug') === 'true')
const logs      = ref<LogLine[]>([])

function log(type: string, msg: unknown) {
  logs.value.unshift({ type, msg: String(msg).slice(0, 300), t: new Date().toISOString().slice(11, 23) })
  if (logs.value.length > 50) logs.value.pop()
}

const origError = console.error.bind(console)
const origWarn  = console.warn.bind(console)

console.error = (...args) => { log('err',  args.join(' ')); origError(...args) }
console.warn  = (...args) => { log('warn', args.join(' ')); origWarn(...args) }
window.addEventListener('error', e => log('exc', `${e.message} @ ${e.filename?.split('/').pop()}:${e.lineno}`))
window.addEventListener('unhandledrejection', e => log('rej', e.reason?.message || e.reason))
</script>

<template>
  <div v-if="showDebug" class="debug">
    <div class="bar">
      <span>debug</span>
      <button @click="logs = []">clear</button>
    </div>
    <div v-for="(l, i) in logs" :key="i" class="line" :class="l.type">
      <span class="t">{{ l.t }}</span> <span class="type">{{ l.type }}</span> {{ l.msg }}
    </div>
  </div>
</template>

<style scoped>
.debug {
  position: fixed;
  bottom: 60px;
  left: 0;
  right: 0;
  max-height: 40vh;
  overflow-y: auto;
  background: rgba(0, 0, 0, 0.88);
  z-index: 9999;
  font-family: monospace;
  font-size: 10px;
  color: #ccc;
}

.bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 8px;
  background: #111;
  color: #888;
  position: sticky;
  top: 0;
}

.bar button {
  background: none;
  border: 1px solid #444;
  color: #888;
  font-size: 10px;
  padding: 1px 6px;
  cursor: pointer;
}

.line {
  padding: 2px 8px;
  border-bottom: 1px solid #222;
  word-break: break-all;
  white-space: pre-wrap;
}
.line.err, .line.exc, .line.rej { color: #f88; }
.line.warn { color: #fa8; }

.t    { color: #555; }
.type { color: #88f; margin-right: 4px; }
</style>
