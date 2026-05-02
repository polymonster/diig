export default defineNuxtRouteMiddleware(async (to) => {
  const currentUser = await getCurrentUser()

  if (!currentUser && to.path !== '/login' && to.path !== '/faq') {
    return navigateTo({ path: '/login' })
  }
})