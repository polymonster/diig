
<script setup lang="ts">
import { useFirebaseAuth, useCurrentUser } from 'vuefire'
import { signInWithEmailAndPassword } from 'firebase/auth'

const auth = useFirebaseAuth()
const user = useCurrentUser()
const router = useRouter()

const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const success = ref('')

watch(user, (newUser) => {
  if (newUser) router.push('/')
}, { immediate: true })

const handleEmailLogin = async () => {
  if (!auth) return

  loading.value = true
  error.value = ''
  success.value = ''

  try {
    await signInWithEmailAndPassword(auth, email.value, password.value)
    success.value = 'Login successful! Redirecting...'
  } catch (err: any) {
    error.value = getErrorMessage(err.code)
  } finally {
    loading.value = false
  }
}

const getErrorMessage = (code: string): string => {
  const messages: Record<string, string> = {
    'auth/invalid-email': 'Invalid email address.',
    'auth/user-disabled': 'This account has been disabled.',
    'auth/user-not-found': 'No account found with this email.',
    'auth/wrong-password': 'Incorrect password.',
    'auth/invalid-credential': 'Invalid email or password.',
    'auth/too-many-requests': 'Too many failed attempts. Please try again later.',
  }
  return messages[code] || 'An error occurred. Please try again.'
}
</script>

<template>
  <div>
    <h1 class="text-3xl">diig - login</h1>
    <div v-if="error">
      {{ error }}
    </div>
    <div v-if="success">
      {{ success }}
    </div>
    <form @submit.prevent="handleEmailLogin">
      <div>
        <label for="email">Email address</label>
        <input
          id="email"
          v-model="email"
          type="email"
          required
          placeholder="you@example.com"
        />
      </div>
      <div>
        <label for="password">Password</label>
        <input
          id="password"
          v-model="password"
          type="password"
          required
          placeholder="••••••••"
        />
      </div>
      <button type="submit" :disabled="loading">
        <span v-if="!loading">Sign in</span>
        <span v-else>Signing in...</span>
      </button>
    </form>
  </div>
</template>
