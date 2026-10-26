(() => {
  const storageKey = 'pitchpulse.selfHostSetup.v1';
  const requiredSettings = [
    ['AZURE_CLIENT_ID', 'Secret'],
    ['AZURE_TENANT_ID', 'Secret'],
    ['AZURE_SUBSCRIPTION_ID', 'Secret'],
    ['AZURE_RESOURCE_GROUP', 'Variable'],
    ['AZURE_LOCATION', 'Variable'],
    ['EVENT_HUB_NAMESPACE_NAME', 'Variable'],
    ['EVENT_HUB_NAME', 'Variable'],
  ];
  const optionalSettings = [
    ['FOUNDRY_PROJECT_ENDPOINT', 'Variable'],
    ['FOUNDRY_MODEL', 'Variable'],
  ];
  const fields = [...document.querySelectorAll('#setup-form input')];
  const byId = (id) => document.getElementById(id);
  const form = byId('setup-form');
  const settingsList = byId('settings-list');
  let storageAvailable = true;

  function readSaved() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
      return saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : {};
    } catch {
      storageAvailable = false;
      return {};
    }
  }

  function values() {
    return Object.fromEntries(fields.map((field) => [field.name, field.value.trim()]));
  }

  function setStatus(message) {
    byId('save-status').textContent = message;
  }

  function save() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(values()));
      storageAvailable = true;
      setStatus('Saved in this browser.');
    } catch {
      storageAvailable = false;
      setStatus('Browser storage is unavailable. Keep this tab open while you copy the values.');
    }
  }

  function validRepository(owner, repo) {
    return /^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/.test(owner)
      && /^[A-Za-z0-9._-]{1,100}$/.test(repo);
  }

  function setLink(id, url) {
    const link = byId(id);
    if (url) {
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.classList.remove('disabled');
      link.removeAttribute('aria-disabled');
    } else {
      link.removeAttribute('href');
      link.classList.add('disabled');
      link.setAttribute('aria-disabled', 'true');
    }
  }

  function renderLinks(current) {
    const owner = current.githubOwner;
    const repo = current.githubRepo;
    const valid = validRepository(owner, repo);
    const error = byId('repo-error');
    error.hidden = !((owner || repo) && !valid);
    error.textContent = error.hidden ? '' : 'Enter a valid GitHub owner and repository name to enable the links.';
    byId('oidc-repo').textContent = valid ? `${owner}/${repo}` : 'your-owner/your-repo';
    const base = valid ? `https://github.com/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}` : '';
    setLink('secrets-link', base && `${base}/settings/secrets/actions`);
    setLink('variables-link', base && `${base}/settings/variables/actions`);
    setLink('workflow-link', base && `${base}/actions/workflows/deploy-infrastructure.yml`);
  }

  function settingRow(name, kind, value) {
    const row = document.createElement('div');
    row.className = 'setting-row';
    const text = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = name;
    const meta = document.createElement('span');
    meta.textContent = `${kind} · ${value ? 'Ready to copy' : 'Not entered'}`;
    text.append(title, meta);
    const copy = document.createElement('button');
    copy.type = 'button';
    copy.textContent = 'Copy value';
    copy.disabled = !value;
    copy.setAttribute('aria-label', `Copy ${name} value`);
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(value);
        copy.textContent = 'Copied';
        setTimeout(() => { copy.textContent = 'Copy value'; }, 2200);
      } catch {
        setStatus('Clipboard access was blocked. Copy the value from its input field.');
      }
    });
    row.append(text, copy);
    return row;
  }

  function render() {
    const current = values();
    const complete = ['githubOwner', 'githubRepo', ...requiredSettings.map(([name]) => name)]
      .filter((name) => Boolean(current[name])).length;
    byId('completed-count').textContent = String(complete);
    byId('progress-fill').style.width = `${Math.round(complete / 9 * 100)}%`;
    const foundryError = byId('foundry-error');
    const foundryIncomplete = Boolean(current.FOUNDRY_PROJECT_ENDPOINT) !== Boolean(current.FOUNDRY_MODEL);
    foundryError.hidden = !foundryIncomplete;
    foundryError.textContent = foundryIncomplete ? 'Enter both Foundry values, or leave both blank.' : '';
    renderLinks(current);
    settingsList.replaceChildren(...[...requiredSettings, ...optionalSettings]
      .filter(([name]) => requiredSettings.some(([required]) => required === name) || current[name])
      .map(([name, kind]) => settingRow(name, kind, current[name])));
  }

  const saved = readSaved();
  for (const field of fields) {
    if (typeof saved[field.name] === 'string') field.value = saved[field.name];
    field.addEventListener('input', () => { save(); render(); });
  }
  form.addEventListener('submit', (event) => event.preventDefault());
  byId('clear-details').addEventListener('click', () => {
    for (const field of fields) field.value = '';
    try {
      localStorage.removeItem(storageKey);
      storageAvailable = true;
      setStatus('Saved details cleared from this browser.');
    } catch {
      storageAvailable = false;
      setStatus('Fields cleared. Browser storage could not be updated.');
    }
    render();
  });
  if (Object.keys(saved).length && storageAvailable) setStatus('Restored details saved in this browser.');
  else if (!storageAvailable) setStatus('Browser storage is unavailable. Values will last only while this page stays open.');
  render();
})();
