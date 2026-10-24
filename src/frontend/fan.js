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

  function setStatus(text, connected = false) {
    status.textContent = text;
    status.className = connected ? 'feed-status connected' : 'feed-status';
  }

  function updateStats(stats) {
    const accuracy = stats?.passing_accuracy;
    byId('home-pass').textContent = `Pass accuracy ${accuracy?.HOME == null ? '—' : `${Math.round(accuracy.HOME * 100)}%`}`;
    byId('away-pass').textContent = `Pass accuracy ${accuracy?.AWAY == null ? '—' : `${Math.round(accuracy.AWAY * 100)}%`}`;
  }

  function createCard(event) {
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
    kind.textContent = event.event_type.replace('_', ' ').toUpperCase();
    const time = document.createElement('time');
    time.className = 'event-time';
    time.dateTime = event.occurred_at;
    time.textContent = new Date(event.occurred_at).toLocaleTimeString();
    top.append(kind, time);
    const title = document.createElement('h3');
    title.textContent = event.team_id || event.player?.team_id || 'MATCH';
    const fact = document.createElement('p');
    fact.className = 'event-fact';
    fact.textContent = `${event.player_id || event.player?.display_name || ''} ${event.outcome || ''}`.trim();
    const commentary = document.createElement('p');
    commentary.className = 'event-text pending';
    commentary.textContent = event.event_type === 'pass' || event.event_type === 'shot' ? 'Commentary is on its way…' : '';
    body.append(top, title, fact, commentary);
    card.append(rail, body);
    if (list.querySelector('.feed-empty')) list.replaceChildren();
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
    if (message.kind === 'match_event') {
      createCard(message.event);
      updateStats(message.stats);
      setStatus('Live match feed', true);
    } else if (message.kind === 'personalized_text') {
      const card = cards.get(message.sequence);
      if (card) { card.commentary.textContent = message.text; card.commentary.classList.remove('pending'); }
    } else if (message.kind === 'speech_audio') {
      const card = cards.get(message.sequence);
      if (!card) return;
      const binary = atob(message.audio_base64);
      const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
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
        note.textContent = message.kind === 'speech_unavailable' ? 'Audio is unavailable for this moment.' : 'Commentary is unavailable for this moment.';
        card.body.append(note);
      }
    }
  }

  function connect() {
    if (!matchId) return;
    const language = byId('language').value;
    const style = byId('style').value;
    const voice = byId('voice').checked ? '1' : '0';
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const query = new URLSearchParams({language, style, voice});
    setStatus('Connecting…');
    socket = new WebSocket(`${protocol}//${location.host}/ws/fan/${encodeURIComponent(matchId)}?${query}`);
    socket.addEventListener('open', () => { reconnectDelay = 1000; setStatus('Connected', true); });
    socket.addEventListener('message', ({data}) => {
      try { renderMessage(JSON.parse(data)); } catch (error) { console.error('Could not render feed message', error); }
    });
    socket.addEventListener('close', () => {
      if (!matchId) return;
      setStatus('Reconnecting…');
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
    if (socket) { matchId = null; socket.close(); }
    for (const url of audioUrls.values()) URL.revokeObjectURL(url);
    audioUrls.clear(); cards.clear(); list.replaceChildren();
    matchId = selected;
    byId('setup-note').textContent = `Following ${selected}`;
    const url = new URL(location.href);
    url.searchParams.set('match_id', selected);
    history.replaceState(null, '', url);
    connect();
  });

  const requestedMatch = new URLSearchParams(location.search).get('match_id');
  if (requestedMatch) { byId('match-input').value = requestedMatch; form.requestSubmit(); }
})();
