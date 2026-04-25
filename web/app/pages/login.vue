<script setup lang="ts">
import { useFirebaseAuth, useCurrentUser } from 'vuefire'
import {
  signInWithEmailAndPassword,
  browserLocalPersistence,
  setPersistence,
  sendPasswordResetEmail
} from 'firebase/auth'

const auth = useFirebaseAuth()
const user = useCurrentUser()
const router = useRouter()

const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const success = ref('')
const showForgotPassword = ref(false)
const resetLoading = ref(false)

const isValidEmail = computed(() => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value))
const isFormValid = computed(() => isValidEmail.value && password.value.length >= 6)

watch(user, (newUser) => {
  if (newUser) router.push('/')
}, { immediate: true })

const handleEmailLogin = async () => {
  if (!auth || !isFormValid.value) return
  loading.value = true
  error.value = ''
  try {
    await setPersistence(auth, browserLocalPersistence)
    await signInWithEmailAndPassword(auth, email.value, password.value)
  } catch (err: any) {
    error.value = getErrorMessage(err.code)
    password.value = ''
  } finally {
    loading.value = false
  }
}

const handlePasswordReset = async () => {
  if (!auth || !isValidEmail.value) return
  resetLoading.value = true
  error.value = ''
  success.value = ''
  try {
    await sendPasswordResetEmail(auth, email.value)
    success.value = 'Reset link sent — check your inbox.'
    setTimeout(() => {
      showForgotPassword.value = false
      success.value = ''
    }, 3000)
  } catch (err: any) {
    error.value = getPasswordResetErrorMessage(err.code)
  } finally {
    resetLoading.value = false
  }
}

const getErrorMessage = (code: string) => ({
  'auth/invalid-email': 'Invalid email address.',
  'auth/user-disabled': 'This account has been disabled.',
  'auth/user-not-found': 'Invalid email or password.',
  'auth/wrong-password': 'Invalid email or password.',
  'auth/invalid-credential': 'Invalid email or password.',
  'auth/too-many-requests': 'Too many attempts — try again later.',
} as Record<string, string>)[code] ?? 'Something went wrong, please try again.'

const getPasswordResetErrorMessage = (code: string) => ({
  'auth/invalid-email': 'Invalid email address.',
  'auth/user-not-found': 'No account found with that email.',
  'auth/too-many-requests': 'Too many requests — try again later.',
} as Record<string, string>)[code] ?? 'Failed to send reset email.'
</script>

<template>
  <div class="page">
    <div class="card">
      <h1 class="title">diig</h1>
      <p class="subtitle">{{ showForgotPassword ? 'reset password' : 'sign in' }}</p>

      <div v-if="error" class="msg error">{{ error }}</div>
      <div v-if="success" class="msg success">{{ success }}</div>

      <form v-if="!showForgotPassword" @submit.prevent="handleEmailLogin">
        <input
          v-model="email"
          type="email"
          placeholder="email"
          autocomplete="email"
          required
          class="field"
        />
        <input
          v-model="password"
          type="password"
          placeholder="password"
          autocomplete="current-password"
          required
          class="field"
        />
        <div class="actions">
          <button type="submit" :disabled="loading || !isFormValid" class="btn">
            {{ loading ? 'signing in...' : 'sign in' }}
          </button>
          <button type="button" class="ghost" @click="showForgotPassword = true">
            forgot password
          </button>
        </div>
      </form>

      <form v-else @submit.prevent="handlePasswordReset">
        <input
          v-model="email"
          type="email"
          placeholder="email"
          autocomplete="email"
          required
          class="field"
        />
        <div class="actions">
          <button type="submit" :disabled="resetLoading || !isValidEmail" class="btn">
            {{ resetLoading ? 'sending...' : 'send reset link' }}
          </button>
          <button type="button" class="ghost" @click="showForgotPassword = false">
            back to sign in
          </button>
        </div>
      </form>
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

* {
  font-family: 'Cousine', monospace;
}

.page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f5f5;
}

.card {
  width: 100%;
  max-width: 400px;
  padding: 2.5rem;
}

.title {
  font-size: 2rem;
  color: #0a0a0a;
  margin: 0 0 0.25rem;
  letter-spacing: 0.05em;
}

.subtitle {
  font-size: 0.85rem;
  color: #999;
  margin: 0 0 2rem;
}

.field {
  display: block;
  width: 100%;
  padding: 0.9rem 1rem;
  margin-bottom: 0.75rem;
  background: #fff;
  border: 1px solid #ccc;
  color: #0a0a0a;
  font-family: 'Cousine', monospace;
  font-size: 1rem;
  box-sizing: border-box;
  outline: none;
  transition: border-color 0.15s;
}

.field::placeholder {
  color: #aaa;
}

.field:focus {
  border-color: #999;
}

.actions {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  margin-top: 1.25rem;
}

.btn {
  padding: 0.75rem 1.5rem;
  background: #0a0a0a;
  color: #fff;
  border: none;
  font-family: 'Cousine', monospace;
  font-size: 0.9rem;
  cursor: pointer;
  transition: opacity 0.15s;
}

.btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.btn:not(:disabled):hover {
  opacity: 0.75;
}

.ghost {
  background: none;
  border: none;
  color: #aaa;
  font-family: 'Cousine', monospace;
  font-size: 0.85rem;
  cursor: pointer;
  padding: 0;
  transition: color 0.15s;
}

.ghost:hover {
  color: #666;
}

.msg {
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.error {
  background: #fff0f0;
  border: 1px solid #f0b0b0;
  color: #a03030;
}

.success {
  background: #f0fff0;
  border: 1px solid #b0e0b0;
  color: #307030;
}
</style>
