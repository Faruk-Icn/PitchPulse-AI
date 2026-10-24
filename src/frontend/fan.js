(() => {
  const byId = (id) => document.getElementById(id);
  const form = byId('preferences-form');
  const list = byId('feed-list');
  const status = byId('feed-status');
  const cards = new Map();
  const audioUrls = new Map();
  let socket = null;
  let reconnectTimer = null;
  let matchId = null;
  let reconnectDelay = 1000;
  let connectionEpoch = 0;
  let locales = null;
  let pendingMessages = [];
  let renderScheduled = false;

  const language = () => byId('language').value;
  const localized = (key) => locales?.[language()]?.labels?.[key] || key;

  function applyLocale() {
    const locale = locales?.[language()];
    if (!locale) return;
    document.documentElement.lang = language();
    document.documentElement.dir = locale.dir;
    for (const node of document.querySelectorAll('[data-i18n]')) {
      node.textContent = locale.labels[node.dataset.i18n];
    }
    byId('match-input').placeholder = locale.labels.match_placeholder;
    for (const option of byId('style').options) option.textContent = locale.styles[option.value];
    if (matchId) byId('setup-note').textContent = `${locale.labels.following} ${matchId}`;
    updateStats(null);
  }

  function setStatus(key, connected = false) {
    status.textContent = localized(key);
    status.className = connected ? 'feed-status connected' : 'feed-status';
  }

  function updateStats(stats) {
    const accuracy = stats?.passing_accuracy;
    byId('home-pass').textContent = `${localized('pass_accuracy')} ${accuracy?.HOME == null ? '—' : `${Math.round(accuracy.HOME * 100)}%`}`;
    byId('away-pass').textContent = `${localized('pass_accuracy')} ${accuracy?.AWAY == null ? '—' : `${Math.round(accuracy.AWAY * 100)}%`}`;
  }

  function createCard(event, summary) {
    const existing = cards.get(event.sequence);
    if (existing) return existing;
    const card = document.createElement('article');
    card.className = 'event-card';
    const rail = document.createElement('div');
    rail.className = 'event-rail';
    const bullet = document.createElement('span');
    bullet.className = `event-bullet ${event.event_type === 'shot' ? 'shot' : ''}`;
    bullet.textContent = event.event_type === 'shot' ? '↗' : event.event_type === 'pass' ? '→' : '·';
    const number = document.createElement('span');
    number.className = 'event-number';
    number.textContent = String(event.sequence).padStart(3, '0');
    rail.append(bullet, number);
    const body = document.createElement('div');
    body.className = 'event-body';
    const top = document.createElement('div');
    top.className = 'event-top';
    const kind = document.createElement('span');
    kind.className = 'event-kind';
    kind.textContent = locales?.[language()]?.events?.[event.event_type] || event.event_type.replace('_', ' ').toUpperCase();
    const time = document.createElement('time');
    time.className = 'event-time';
    time.dateTime = event.occurred_at;
    time.textContent = new Date(event.occurred_at).toLocaleTimeString(document.documentElement.lang);
    top.append(kind, time);
    const title = document.createElement('h3');
    title.textContent = localized((event.team_id || event.player?.team_id || '').toLowerCase());
    const fact = document.createElement('p');
    fact.className = 'event-fact';
    fact.textContent = event.player_id || event.player?.display_name || '';
    const commentary = document.createElement('p');
    commentary.className = 'event-text';
    commentary.textContent = summary || '';
    body.append(top, title, fact, commentary);
    card.append(rail, body);
    if (list.firstElementChild?.classList.contains('feed-empty')) list.replaceChildren();
    list.prepend(card);
    cards.set(event.sequence, {card, body, commentary});
    while (list.children.length > 20) {
      const oldest = list.lastElementChild;
      const seq = Number(oldest.dataset.sequence);
      if (audioUrls.has(seq)) URL.revokeObjectURL(audioUrls.get(seq));
      cards.delete(seq);
      oldest.remove();
    }
    card.dataset.sequence = String(event.sequence);
    return cards.get(event.sequence);
  }

  function renderMessage(message) {
    if (message.match_id !== matchId) return;
    if (message.language && message.language !== language()) return;
    if (message.style && message.style !== byId('style').value) return;
    if (message.kind === 'match_event') {
      createCard(message.event, message.summary);
      updateStats(message.stats);
      setStatus('feed_live', true);
    } else if (message.kind === 'personalized_text') {
      const card = cards.get(message.sequence);
      if (card) { card.commentary.textContent = message.text; card.commentary.classList.remove('pending'); }
    } else if (message.kind === 'speech_audio') {
      const card = cards.get(message.sequence);
      if (!card) return;
      const binary = atob(message.audio_base64);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
      const url = URL.createObjectURL(new Blob([bytes], {type: message.content_type}));
      if (audioUrls.has(message.sequence)) URL.revokeObjectURL(audioUrls.get(message.sequence));
      audioUrls.set(message.sequence, url);
      let audio = card.body.querySelector('audio');
      if (!audio) { audio = document.createElement('audio'); audio.className = 'event-audio'; audio.controls = true; card.body.append(audio); }
      audio.src = url;
    } else if (message.kind === 'personalization_unavailable' || message.kind === 'speech_unavailable') {
      const card = cards.get(message.sequence);
      if (card) {
        const note = document.createElement('p');
        note.className = 'event-error';
        note.textContent = localized(message.kind === 'speech_unavailable' ? 'speech_unavailable' : 'commentary_unavailable');
        card.body.append(note);
      }
    }
  }

  function queueMessage(message) {
    pendingMessages.push(message);
    if (renderScheduled) return;
    renderScheduled = true;
    requestAnimationFrame(() => {
      renderScheduled = false;
      const batch = pendingMessages;
      pendingMessages = [];
      for (const item of batch) {
        try { renderMessage(item); } catch (error) { console.error('Could not render feed message', error); }
      }
    });
  }

  function connect() {
    if (!matchId) return;
    const epoch = connectionEpoch;
    const selectedLanguage = language();
    const style = byId('style').value;
    const voice = byId('voice').checked ? '1' : '0';
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const query = new URLSearchParams({language: selectedLanguage, style, voice});
    setStatus('connecting');
    socket = new WebSocket(`${protocol}//${location.host}/ws/fan/${encodeURIComponent(matchId)}?${query}`);
    socket.addEventListener('open', () => { reconnectDelay = 1000; setStatus('connected', true); });
    socket.addEventListener('message', ({data}) => {
      try { queueMessage(JSON.parse(data)); } catch (error) { console.error('Could not render feed message', error); }
    });
    socket.addEventListener('close', () => {
      if (!matchId || epoch !== connectionEpoch) return;
      setStatus('reconnecting');
      reconnectTimer = setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 10000);
    });
    socket.addEventListener('error', () => socket.close());
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const selected = byId('match-input').value.trim();
    if (!selected) return;
    clearTimeout(reconnectTimer);
    connectionEpoch += 1;
    pendingMessages = [];
    if (socket) socket.close();
    for (const url of audioUrls.values()) URL.revokeObjectURL(url);
    audioUrls.clear(); cards.clear(); list.replaceChildren();
    matchId = selected;
    byId('setup-note').textContent = `${localized('following')} ${selected}`;
    try { localStorage.setItem('pitchpulse.fan.preferences', JSON.stringify({match_id: selected, language: language(), style: byId('style').value, voice: byId('voice').checked})); } catch {}
    const url = new URL(location.href);
    url.searchParams.set('match_id', selected);
    url.searchParams.set('language', language());
    url.searchParams.set('style', byId('style').value);
    history.replaceState(null, '', url);
    connect();
  });

  form.addEventListener('change', () => { applyLocale(); if (matchId) form.requestSubmit(); });

  async function initialize() {
    try {
      const saved = JSON.parse(localStorage.getItem('pitchpulse.fan.preferences') || 'null');
      if (saved) {
        if ([...byId('language').options].some((option) => option.value === saved.language)) byId('language').value = saved.language;
        if ([...byId('style').options].some((option) => option.value === saved.style)) byId('style').value = saved.style;
        byId('voice').checked = saved.voice === true;
        if (typeof saved.match_id === 'string') byId('match-input').value = saved.match_id;
      }
    } catch {}
    const parameters = new URLSearchParams(location.search);
    if ([...byId('language').options].some((option) => option.value === parameters.get('language'))) byId('language').value = parameters.get('language');
    if ([...byId('style').options].some((option) => option.value === parameters.get('style'))) byId('style').value = parameters.get('style');
    try {
      const response = await fetch('/api/fan/config');
      if (!response.ok) throw new Error('Locale configuration unavailable');
      locales = (await response.json()).locales;
      applyLocale();
    } catch (error) { console.error(error); }
    const requestedMatch = parameters.get('match_id');
    if (requestedMatch) byId('match-input').value = requestedMatch;
    if (byId('match-input').value) form.requestSubmit();
  }
  initialize();
})();
