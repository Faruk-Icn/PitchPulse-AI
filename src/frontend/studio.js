(() => {
  const byId = (id) => document.getElementById(id);
  const status = byId('connection');
  const feed = byId('event-feed');
  const marker = byId('pitch-marker');
  let socket;
  let reconnectDelay = 1000;
  let latestSequence = -1;

  function setStatus(label, className) {
    status.textContent = label;
    status.className = `connection ${className}`;
  }

  function formatPercent(value) {
    return value == null ? '—' : `${Math.round(value * 100)}%`;
  }

  function renderAnalysis(message) {
    const event = message.event;
    const result = message.result;
    if (!event || !result || !Number.isInteger(event.sequence)) return;
    byId('match-id').textContent = event.match_id;
    byId('last-sequence').textContent = `EVENT ${String(event.sequence).padStart(4, '0')}`;
    byId('event-kind').textContent = event.event_type.replace('_', ' ').toUpperCase();

    const point = event.start || event.location || event.coordinates;
    if (point && Number.isFinite(point.x) && Number.isFinite(point.y)) {
      marker.style.left = `${Math.max(0, Math.min(100, point.x))}%`;
      marker.style.top = `${Math.max(0, Math.min(100, point.y))}%`;
      marker.hidden = false;
    }

    const actor = event.player_id || event.player?.display_name || 'Match event';
    const label = event.event_type === 'pass' ? `${actor} · ${event.outcome} pass`
      : event.event_type === 'shot' ? `${actor} · ${event.outcome} shot`
      : event.event_type === 'position' ? `${actor} · position update`
      : `${actor} · player registered`;
    byId('event-summary').textContent = label;
    const item = document.createElement('li');
    const number = document.createElement('span');
    number.className = 'feed-sequence';
    number.textContent = String(event.sequence).padStart(3, '0');
    const body = document.createElement('div');
    const title = document.createElement('span');
    title.className = 'feed-title';
    title.textContent = label;
    const detail = document.createElement('span');
    detail.className = 'feed-detail';
    detail.textContent = `${event.team_id || event.player?.team_id || 'MATCH'} · ${new Date(event.occurred_at).toLocaleTimeString()}`;
    body.append(title, detail);
    item.append(number, body);
    if (feed.querySelector('.empty-feed')) feed.replaceChildren();
    feed.prepend(item);
    while (feed.children.length > 12) feed.lastElementChild.remove();

    const difficulty = result.pass_difficulty;
    const pressure = result.tactical_pressure;
    byId('pass-difficulty').textContent = difficulty == null ? '—' : difficulty.index.toFixed(2);
    byId('tactical-pressure').textContent = pressure == null ? '—' : String(pressure.defenders_within_10m);
    byId('home-accuracy').textContent = formatPercent(result.stats?.passing_accuracy?.HOME);
    byId('away-accuracy').textContent = formatPercent(result.stats?.passing_accuracy?.AWAY);
    if (event.sequence >= latestSequence) {
      latestSequence = event.sequence;
      if (difficulty != null) {
        byId('overlay-text').textContent = `Pass difficulty ${difficulty.index.toFixed(2)} · ${pressure.defenders_within_10m} nearby defender${pressure.defenders_within_10m === 1 ? '' : 's'}`;
        byId('overlay-sequence').textContent = `MATCH ${event.match_id} / EVENT ${event.sequence}`;
      }
    }
  }

  function renderNarrative(message) {
    const text = message.result?.narrative?.text;
    if (!text) return;
    byId('overlay-text').textContent = text;
    byId('overlay-sequence').textContent = `MATCH ${message.match_id} / EVENT ${message.sequence}`;
  }

  function connect() {
    setStatus('Connecting…', '');
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${location.host}/ws/studio`);
    socket.addEventListener('open', () => { reconnectDelay = 1000; setStatus('Studio connected', 'connected'); });
    socket.addEventListener('message', (incoming) => {
      let message;
      try { message = JSON.parse(incoming.data); } catch { return; }
      if (message.kind === 'analysis') { setStatus('Match feed live', 'connected'); renderAnalysis(message); }
      if (message.kind === 'narrative') renderNarrative(message);
    });
    socket.addEventListener('close', () => {
      setStatus('Reconnecting…', 'disconnected');
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 10000);
    });
    socket.addEventListener('error', () => socket.close());
  }
  connect();
})();
