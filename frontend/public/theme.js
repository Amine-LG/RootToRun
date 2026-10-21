// Applied before first paint (no flash): saved choice, else the system preference.
try {
  var saved = localStorage.getItem('osa.theme')
  document.documentElement.dataset.theme = saved || (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
} catch (e) {
  document.documentElement.dataset.theme = 'dark'
}
