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

// Add email validation computed property
const isValidEmail = computed(() => {
  if (!email.value) return false
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value)
})

// Add form validation computed property
const isFormValid = computed(() => {
  return isValidEmail.value && password.value.length >= 6
})

watch(user, (newUser) => {
  if (newUser) router.push('/')
}, { immediate: true })

const handleEmailLogin = async () => {
  if (!auth) return

  if (!isValidEmail.value) {
    error.value = 'Please enter a valid email address.'
    return
  }

  if (password.value.length < 6) {
    error.value = 'Password must be at least 6 characters.'
    return
  }

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
          :class="{ 'invalid': email && !isValidEmail }"
        />
        <span v-if="email && !isValidEmail" class="error-hint">
          Please enter a valid email address
        </span>
      </div>

      <div>
        <label for="password">Password</label>
        <input
          id="password"
          v-model="password"
          type="password"
          required
          placeholder="••••••••"
          :class="{ 'invalid': password && password.length < 6 }"
        />
        <span v-if="password && password.length < 6" class="error-hint">
          Password must be at least 6 characters
        </span>
      </div>

      <button
        type="submit"
        :disabled="loading || !isFormValid"
      >
        <span v-if="!loading">Sign in</span>
        <span v-else>Signing in...</span>
      </button>
    </form>
  </div>
</template>

<style scoped>
.invalid {
  border-color: red;
}

.error-hint {
  color: red;
  font-size: 0.875rem;
  margin-top: 0.25rem;
  display: block;
}
</style>