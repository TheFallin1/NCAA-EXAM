document.addEventListener('alpine:init', () => {
  Alpine.data('themeToggle', () => ({
    dark: localStorage.getItem('theme') === 'dark',
    sidebarOpen: false,
    init() {
      this.apply();
    },
    toggle() {
      this.dark = !this.dark;
      localStorage.setItem('theme', this.dark ? 'dark' : 'light');
      this.apply();
    },
    apply() {
      document.documentElement.classList.toggle('dark', this.dark);
      document.body.classList.toggle('dark', this.dark);
      document.body.classList.toggle('light', !this.dark);
    },
  }));

  Alpine.data('confirmModal', () => ({
    open: false,
    targetUrl: '',
    message: 'Are you sure?',
    show(url, message) {
      this.targetUrl = url;
      this.message = message || this.message;
      this.open = true;
    },
    confirm() {
      if (this.targetUrl) window.location.href = this.targetUrl;
      this.open = false;
    },
  }));

  Alpine.data('searchDebounce', () => ({
    timeout: null,
    submit(form) {
      clearTimeout(this.timeout);
      this.timeout = setTimeout(() => form.submit(), 400);
    },
  }));
});

function showLoading() {
  const el = document.getElementById('loading-overlay');
  if (el) el.classList.remove('hidden');
}

document.querySelectorAll('form[data-loading]').forEach((form) => {
  form.addEventListener('submit', showLoading);
});
