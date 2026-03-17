(() => {
  const toggleBtn = document.querySelector('[data-lang-toggle]');

  const apply = (lang) => {
    const elements = document.querySelectorAll('[data-en],[data-zh],[data-en-html],[data-zh-html]');
    elements.forEach((el) => {
      if (lang === 'zh' && el.dataset.zhHtml) {
        el.innerHTML = el.dataset.zhHtml;
        return;
      }
      if (lang === 'en' && el.dataset.enHtml) {
        el.innerHTML = el.dataset.enHtml;
        return;
      }
      if (lang === 'zh' && el.dataset.zh) {
        el.textContent = el.dataset.zh;
        return;
      }
      if (lang === 'en' && el.dataset.en) {
        el.textContent = el.dataset.en;
        return;
      }
    });

    document.documentElement.setAttribute('lang', lang === 'zh' ? 'zh' : 'en');
    if (toggleBtn) {
      toggleBtn.textContent = lang === 'zh' ? 'English' : '中文';
    }
    localStorage.setItem('lang', lang);
  };

  window.applyLang = apply;
  window.getLang = () => document.documentElement.getAttribute('lang') || localStorage.getItem('lang') || 'en';

  const saved = localStorage.getItem('lang') || 'en';
  apply(saved);

  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('lang') || 'en';
      apply(current === 'en' ? 'zh' : 'en');
    });
  }
})();
