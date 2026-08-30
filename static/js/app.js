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
      window.dispatchEvent(new CustomEvent('theme-changed', { detail: { dark: this.dark } }));
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

  /**
   * The dependent Examination Category / Paper Type pair.
   *
   * `catalogue` maps a category to the papers configured under it, so a paper
   * added or renamed in the admin appears here without a code change. Changing
   * the category clears the paper and reloads the list, which is what makes an
   * invalid pair -- Cabin Crew with Flight Dispatch's Paper 1 -- unreachable.
   * The server checks the pair again on submit.
   */
  Alpine.data('examSelection', (catalogue, category, paper) => ({
    catalogue: catalogue || {},
    category: category || '',
    paper: paper || '',
    papers() {
      return this.catalogue[this.category] || [];
    },
    onCategoryChange() {
      // Clear first: a paper carried over from the previous category would be
      // a combination the officer never chose.
      this.paper = '';
      const available = this.papers();
      // A category with exactly one paper has nothing to choose.
      if (available.length === 1) this.paper = available[0].value;
    },
    placeholder() {
      return this.category ? 'Select Paper Type' : 'Select Examination Category First';
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
