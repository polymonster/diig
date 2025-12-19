<script setup lang="ts">
import { useFirebaseAuth, useCurrentUser } from 'vuefire'
import {
  signInWithEmailAndPassword,
  setPersistence,
  browserLocalPersistence,
  browserSessionPersistence,
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
const rememberMe = ref(false)
const showForgotPassword = ref(false) // Toggle forgot password view
const resetLoading = ref(false) // Separate loading state for password reset

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

  // Validate before proceeding
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
    // Set persistence based on user preference
    await setPersistence(
      auth,
      rememberMe.value ? browserLocalPersistence : browserSessionPersistence
    )

    await signInWithEmailAndPassword(auth, email.value, password.value)
    success.value = 'Login successful! Redirecting...'

    // Clear sensitive data
    password.value = ''
  } catch (err: any) {
    error.value = getErrorMessage(err.code)
    password.value = ''
  } finally {
    loading.value = false
  }
}

const handlePasswordReset = async () => {
  if (!auth) return

  // Validate email before sending reset
  if (!isValidEmail.value) {
    error.value = 'Please enter a valid email address to reset your password.'
    return
  }

  resetLoading.value = true
  error.value = ''
  success.value = ''

  try {
    await sendPasswordResetEmail(auth, email.value)
    success.value = 'Password reset email sent! Check your inbox.'

    // Optionally switch back to login view after a delay
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

const toggleForgotPassword = () => {
  showForgotPassword.value = !showForgotPassword.value
  error.value = ''
  success.value = ''
  password.value = ''
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

const getPasswordResetErrorMessage = (code: string): string => {
  const messages: Record<string, string> = {
    'auth/invalid-email': 'Invalid email address.',
    'auth/user-not-found': 'No account found with this email.',
    'auth/too-many-requests': 'Too many requests. Please try again later.',
  }
  return messages[code] || 'Failed to send password reset email. Please try again.'
}
</script>

<template>
  <div>
    <h1 class="text-3xl">diig - {{ showForgotPassword ? 'reset password' : 'login' }}</h1>

    <div v-if="error" class="error-message">
      {{ error }}
    </div>

    <div v-if="success" class="success-message">
      {{ success }}
    </div>

    <!-- Login Form -->
    <form v-if="!showForgotPassword" @submit.prevent="handleEmailLogin">
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

      <div class="remember-me">
        <input
          id="rememberMe"
          v-model="rememberMe"
          type="checkbox"
        />
        <label for="rememberMe">Remember me</label>
      </div>

      <button
        type="submit"
        :disabled="loading || !isFormValid"
      >
        <span v-if="!loading">Sign in</span>
        <span v-else>Signing in...</span>
      </button>

      <button
        type="button"
        @click="toggleForgotPassword"
        class="forgot-password-link"
      >
        Forgot password?
      </button>
    </form>

    <!-- Forgot Password Form -->
    <form v-else @submit.prevent="handlePasswordReset">
      <p class="reset-description">
        Enter your email address and we'll send you a link to reset your password.
      </p>

      <div>
        <label for="reset-email">Email address</label>
        <input
          id="reset-email"
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

      <button
        type="submit"
        :disabled="resetLoading || !isValidEmail"
      >
        <span v-if="!resetLoading">Send reset link</span>
        <span v-else>Sending...</span>
      </button>

      <button
        type="button"
        @click="toggleForgotPassword"
        class="back-to-login-link"
      >
        Back to login
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

.error-message {
  color: red;
  padding: 1rem;
  margin-bottom: 1rem;
  background-color: #fee;
  border-radius: 0.25rem;
}

.success-message {
  color: green;
  padding: 1rem;
  margin-bottom: 1rem;
  background-color: #efe;
  border-radius: 0.25rem;
}

.remember-me {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 1rem 0;
}

.remember-me input[type="checkbox"] {
  width: auto;
  cursor: pointer;
}

.remember-me label {
  cursor: pointer;
  margin: 0;
}

.forgot-password-link,
.back-to-login-link {
  background: none;
  border: none;
  color: #0066cc;
  text-decoration: underline;
  cursor: pointer;
  padding: 0.5rem 0;
  margin-top: 0.5rem;
  font-size: 0.875rem;
}

.forgot-password-link:hover,
.back-to-login-link:hover {
  color: #0052a3;
}

.reset-description {
  margin-bottom: 1.5rem;
  color: #666;
  font-size: 0.875rem;
}
</style>