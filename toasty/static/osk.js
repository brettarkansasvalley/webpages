// On-Screen Keyboard (OSK) for all pages
// - Attaches to text and number inputs
// - Numeric layout for number/decimal inputs
// - QWERTY layout for text inputs
// - Inserts characters at caret and dispatches input events
(function(){
  const osk = document.getElementById('osk');
  if (!osk) return;
  const keysWrap = osk.querySelector('.osk-keys');
  const btnDone = osk.querySelector('.osk-done');
  const btnBack = osk.querySelector('.osk-back');
  const btnClear = osk.querySelector('.osk-clear');

  let activeEl = null;
  let oskOpen = false;
  let layoutMode = 'numeric'; // 'numeric' | 'text'

  const NUMERIC_KEYS = ['7','8','9','4','5','6','1','2','3','0','.'];
  const ROWS_TEXT = [
    ['Q','W','E','R','T','Y','U','I','O','P'],
    ['A','S','D','F','G','H','J','K','L'],
    ['Z','X','C','V','B','N','M'],
    ['space']
  ];

  function isNumericInput(el){
    if (!el) return false;
    const t = (el.getAttribute('type')||'').toLowerCase();
    const im = (el.getAttribute('inputmode')||'').toLowerCase();
    if (t === 'number') return true;
    if (im.includes('numeric') || im.includes('decimal')) return true;
    // also consider data-osk="numeric"
    if ((el.dataset.osk||'').toLowerCase() === 'numeric') return true;
    // if OSK marked this input as numeric before mutation
    if (el.dataset.oskForceNumeric === '1') return true;
    return false;
  }

  function setLayout(mode){
    layoutMode = mode;
    // clear keys
    keysWrap.innerHTML = '';
    if (mode === 'numeric'){
      const grid = document.createElement('div');
      grid.className = 'osk-grid osk-grid-numeric';
      NUMERIC_KEYS.forEach(k => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'osk-btn';
        b.textContent = k;
        b.dataset.key = k;
        grid.appendChild(b);
      });
      keysWrap.appendChild(grid);
    } else {
      const wrap = document.createElement('div');
      wrap.className = 'osk-grid osk-grid-text';
      ROWS_TEXT.forEach(row => {
        const rowEl = document.createElement('div');
        rowEl.className = 'osk-row';
        row.forEach(k => {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'osk-btn';
          if (k === 'space'){
            b.textContent = '⎵';
            b.dataset.key = ' ';
            b.classList.add('osk-space');
          } else {
            b.textContent = k;
            b.dataset.key = k;
          }
          rowEl.appendChild(b);
        });
        wrap.appendChild(rowEl);
      });
      keysWrap.appendChild(wrap);
    }
  }

  function showOSK(forEl){
    activeEl = forEl;
    // Determine numeric intent BEFORE mutating attributes
    let wasNumeric = false;
    try {
      const t0 = (forEl.getAttribute('type')||'').toLowerCase();
      const im0 = (forEl.getAttribute('inputmode')||'').toLowerCase();
      wasNumeric = (t0 === 'number') || im0.includes('numeric') || im0.includes('decimal') || (forEl.dataset.osk === 'numeric');
    } catch(e){}
    if (wasNumeric) { forEl.dataset.oskForceNumeric = '1'; }
    // Decide layout based on original intent
    setLayout(wasNumeric ? 'numeric' : 'text');
    // Suppress native keyboard by forcing inputmode none (restored on hide)
    try {
      activeEl.dataset.oskOldInputmode = activeEl.getAttribute('inputmode') || '';
      activeEl.setAttribute('inputmode', 'none');
      // Also enforce readOnly to prevent native input handling
      activeEl.dataset.oskOldReadonly = activeEl.readOnly ? '1' : '';
      activeEl.readOnly = true;
      // Additionally: if it's a number input, switch to text to avoid native number behaviors
      const oldType = (activeEl.getAttribute('type')||'').toLowerCase();
      activeEl.dataset.oskOldType = oldType;
      if (oldType === 'number') {
        activeEl.setAttribute('type', 'text');
        // hint numeric
        activeEl.setAttribute('inputmode', 'none');
      }
    } catch(e){}
    osk.hidden = false;
    osk.setAttribute('aria-hidden','false');
    oskOpen = true;
    // Ensure native keyboard is closed
    try { activeEl.blur(); } catch(e){}
    // Ensure the input is visible above the keyboard
    try {
      const rect = forEl.getBoundingClientRect();
      const kbHeight = osk.offsetHeight || 260;
      const overlap = (rect.bottom + 12) - (window.innerHeight - kbHeight);
      if (overlap > 0) {
        window.scrollBy({ top: overlap, behavior: 'smooth' });
      }
    } catch(e){}
  }
  function hideOSK(){
    osk.hidden = true;
    osk.setAttribute('aria-hidden','true');
    oskOpen = false;
    // Restore previous inputmode
    try {
      if (activeEl) {
        const prev = activeEl.dataset.oskOldInputmode || '';
        if (prev) activeEl.setAttribute('inputmode', prev);
        else activeEl.removeAttribute('inputmode');
        const prevRO = activeEl.dataset.oskOldReadonly || '';
        activeEl.readOnly = !!prevRO;
        // Restore original type if needed
        const prevType = activeEl.dataset.oskOldType || '';
        if (prevType) {
          activeEl.setAttribute('type', prevType);
        }
        delete activeEl.dataset.oskOldInputmode;
        delete activeEl.dataset.oskOldReadonly;
        delete activeEl.dataset.oskOldType;
      }
    } catch(e){}
    activeEl = null;
  }

  function insertAtCaret(el, text){
    try {
      const wasRO = el.readOnly;
      try { el.blur(); } catch(_){}
      el.readOnly = false;
      const start = el.selectionStart ?? el.value.length;
      const end = el.selectionEnd ?? el.value.length;
      const before = el.value.substring(0, start);
      const after = el.value.substring(end);
      el.value = before + text + after;
      const newPos = start + text.length;
      if (typeof el.setSelectionRange === 'function'){
        el.setSelectionRange(newPos, newPos);
      }
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.readOnly = wasRO || oskOpen; // keep readOnly if OSK still open
      try { el.blur(); } catch(_){}
    } catch(e) {
      // fallback: append
      const wasRO = el.readOnly;
      try { el.blur(); } catch(_){}
      el.readOnly = false;
      el.value += text;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.readOnly = wasRO || oskOpen;
      try { el.blur(); } catch(_){}
    }
  }
  function backspaceAtCaret(el){
    try {
      const wasRO = el.readOnly;
      try { el.blur(); } catch(_){}
      el.readOnly = false;
      const start = el.selectionStart ?? el.value.length;
      const end = el.selectionEnd ?? el.value.length;
      if (start === end && start > 0){
        const before = el.value.substring(0, start - 1);
        const after = el.value.substring(end);
        el.value = before + after;
        const newPos = start - 1;
        el.setSelectionRange(newPos, newPos);
      } else {
        const before = el.value.substring(0, start);
        const after = el.value.substring(end);
        el.value = before + after;
        el.setSelectionRange(start, start);
      }
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.readOnly = wasRO || oskOpen;
      try { el.blur(); } catch(_){}
    } catch(e) {}
  }

  // Global listeners
  document.addEventListener('focusin', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLInputElement)) return;
    const type = (t.getAttribute('type')||'').toLowerCase();
    if (type === 'date' || type === 'time' || type === 'datetime-local' || type === 'checkbox' || type === 'radio' || type === 'range' || type === 'file' || type === 'color' || type === 'hidden'){
      return; // don't show for non-text inputs
    }
    // If it's a numeric field, tag it so OSK chooses numeric layout
    try {
      const rt = (t.type || '').toLowerCase();
      if (rt === 'number') { t.dataset.osk = 'numeric'; t.dataset.oskForceNumeric = '1'; }
    } catch(_){}
    showOSK(t);
    // Maintain focus without triggering native keyboard
    try { t.blur(); t.focus({preventScroll:true}); } catch(e){}
  });

  document.addEventListener('focusout', (e) => {
    // Don't auto-hide on blur to allow tapping keyboard; hide only with Done
  });

  // Debounce rapid duplicate key activations
  let lastKey = null;
  let lastTime = 0;

  // Block default/bubbling for legacy events that may also fire
  osk.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); }, true);
  osk.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); }, true);

  osk.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    e.stopPropagation();
    const btn = e.target.closest('button');
    if (!btn) return;
    const key = btn.dataset.key;
    if (!activeEl) return;
    const now = Date.now();
    if (key === lastKey && (now - lastTime) < 180) { return; }
    lastKey = key; lastTime = now;
    if (key === 'done'){ hideOSK(); return; }
    if (key === 'back'){ backspaceAtCaret(activeEl); return; }
    if (key === 'clear'){ activeEl.value = ''; activeEl.dispatchEvent(new Event('input', { bubbles: true })); return; }
    // Insert regular key
    insertAtCaret(activeEl, key);
    // Avoid refocusing to keep native keyboard suppressed
  });

  // Block hardware keyboard events when OSK is open to avoid duplicates
  document.addEventListener('keydown', (e) => {
    if (!oskOpen) return;
    const t = e.target;
    if (t instanceof HTMLInputElement) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  // Also block native beforeinput for inputs to avoid double insertions
  document.addEventListener('beforeinput', (e) => {
    if (!oskOpen) return;
    const t = e.target;
    if (t instanceof HTMLInputElement) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  // Initialize with a default layout to avoid flash
  setLayout('numeric');
})();
