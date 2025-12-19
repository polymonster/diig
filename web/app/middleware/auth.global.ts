export default defineNuxtRouteMiddleware(async (to) => {
  const currentUser = await getCurrentUser()

  if (!currentUser && to.path !== '/login') {
    return navigateTo({ path: '/login' })
  }
})