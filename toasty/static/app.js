// Intercept the fetch form to submit via AJAX and show a modal popup
(function () {
  function $(sel) { return document.querySelector(sel); }

  function showModal(message, isError = false) {
    const modal = $('#modal');
    const box = $('#modal-box');
    const msg = $('#modal-message');
    if (!modal || !box || !msg) return alert(message);
    msg.textContent = message || '';
    box.classList.toggle('error', !!isError);
    modal.removeAttribute('hidden');
    // Focus close button for accessibility / touch ease
    const closeBtn = $('#modal-close');
    if (closeBtn) closeBtn.focus();
  }

  function hideModal() {
    const modal = document.getElementById('modal');
    if (modal) modal.setAttribute('hidden', '');
  }

  document.addEventListener('DOMContentLoaded', () => {
    // Modal close handlers
    const closeBtn = document.getElementById('modal-close');
    if (closeBtn) closeBtn.addEventListener('click', hideModal);
    const modal = document.getElementById('modal');
    if (modal) modal.addEventListener('click', (e) => {
      if (e.target === modal) hideModal();
    });

    // Home page fetch form interception (do not navigate away)
    const fetchForm = document.querySelector('form.fetch-form');
    if (fetchForm) {
      fetchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = fetchForm.querySelector('button[type="submit"]');
        const origText = submitBtn ? submitBtn.textContent : '';
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.textContent = 'Starting…';
        }
        try {
          const fd = new FormData(fetchForm);
          const resp = await fetch('/run', {
            method: 'POST',
            body: fd,
            headers: { 'Accept': 'text/plain' },
          });
          const text = await resp.text();
          if (!resp.ok) throw new Error(text || ('Request failed: ' + resp.status));
          showModal(text || 'Fetch started.');
        } catch (err) {
          showModal((err && err.message) ? err.message : 'An error occurred.', true);
        } finally {
          if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = origText || 'Fetch';
          }
        }
      });
    }

    // Bartender multi-select count
    const bartenderSelect = document.getElementById('bartenders');
    const bartenderCount = document.getElementById('bartender-count');
    function updateBartenderCount() {
      if (!bartenderSelect || !bartenderCount) return;
      const n = Array.from(bartenderSelect.options).filter(o => o.selected).length;
      bartenderCount.textContent = `${n} selected`;
    }
    if (bartenderSelect && bartenderCount) {
      updateBartenderCount();
      bartenderSelect.addEventListener('change', updateBartenderCount);
      bartenderSelect.addEventListener('input', updateBartenderCount);
    }
  });
})();
