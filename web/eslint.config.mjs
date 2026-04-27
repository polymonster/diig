// @ts-check
import withNuxt from './.nuxt/eslint.config.mjs'

export default withNuxt({
  rules: {
    'no-unused-vars': ['error', { varsIgnorePattern: '^_', argsIgnorePattern: '^_' }],
    '@typescript-eslint/no-unused-vars': ['error', { varsIgnorePattern: '^_', argsIgnorePattern: '^_' }],
    'no-empty': ['error', { allowEmptyCatch: true }],
    '@typescript-eslint/no-explicit-any': 'off',
    '@typescript-eslint/no-unused-expressions': 'off',
  },
})
