/* The assistant receives explicit scope; it never reads the page or browser storage. */
(() => {
  'use strict';
  const icons = {
    chat: '<path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l-3 3V11.5A7.5 7.5 0 0 1 9.5 4h3a7.5 7.5 0 0 1 7.5 7.5Z"/><path d="M7 10h8M7 14h5"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    send: '<path d="m12 19 0-14m-6 6 6-6 6 6"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',
    speaker: '<path d="m11 5-5 4H3v6h3l5 4V5Zm5 3a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    restart: '<path d="M3 10a9 9 0 1 1 2 8M3 4v6h6"/>',
    arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>'
  };
  function el(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value != null) node.textContent = value;
    return node;
  }
  function icon(name) {
    const holder = el('span', 'jarvis-icon');
    // Only these local constants enter innerHTML; replies and source labels use textContent.
    holder.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + icons[name] + '</svg>';
    return holder;
  }
  function button(label, className, iconName) {
    const node = el('button', className);
    node.type = 'button';
    node.setAttribute('aria-label', label);
    node.title = label;
    if (iconName) node.append(icon(iconName));
    return node;
  }
  function turnId() {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  }
  let mounted = null;
  function mount(options) {
    if (mounted) return mounted;
    if (!options || typeof options.api !== 'function') throw new Error('Jarvis requires the authenticated API helper.');
    const container = options.root || document.getElementById('app');
    if (!container) throw new Error('Jarvis requires the app container.');
    const root = el('div', 'jarvis-root');
    root.hidden = true;
    const fab = button('Open Jarvis shipment assistant', 'jarvis-fab', 'chat');
    fab.append(el('span', '', 'Jarvis'));
    fab.setAttribute('aria-expanded', 'false');
    fab.setAttribute('aria-controls', 'jarvis-panel');
    const panel = el('section', 'jarvis-panel');
    panel.id = 'jarvis-panel';
    panel.hidden = true;
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Jarvis shipment assistant');
    const header = el('header', 'jarvis-header');
    const identity = el('div', 'jarvis-identity');
    identity.append(el('h2', '', 'Jarvis'), el('span', 'jarvis-subtitle', 'Your shipment briefing'));
    const headerActions = el('div', 'jarvis-header-actions');
    const speak = button('Read latest reply aloud', 'jarvis-icon-button', 'speaker');
    const newChat = button('Start a new chat', 'jarvis-icon-button', 'restart');
    const closeButton = button('Close Jarvis', 'jarvis-icon-button', 'close');
    headerActions.append(newChat, speak, closeButton);
    header.append(identity, headerActions);
    const selection = el('div', 'jarvis-selection');
    const scopeLabel = el('span', 'jarvis-scope', 'Visible shipments');
    const modeLabel = el('span', 'jarvis-mode', 'Read-only');
    selection.append(scopeLabel, modeLabel);
    const feed = el('div', 'jarvis-feed');
    feed.setAttribute('role', 'log');
    feed.setAttribute('aria-label', 'Jarvis conversation');
    feed.setAttribute('aria-live', 'polite');
    feed.setAttribute('aria-relevant', 'additions');
    const status = el('div', 'jarvis-status');
    status.setAttribute('role', 'status');
    const prompts = el('div', 'jarvis-prompts');
    const form = el('form', 'jarvis-composer');
    const label = el('label', 'visually-hidden', 'Message Jarvis');
    label.htmlFor = 'jarvis-message';
    const input = el('textarea', 'jarvis-input');
    input.id = 'jarvis-message';
    input.rows = 2;
    input.maxLength = 2000;
    input.placeholder = 'Ask about shipments or next actions…';
    const tools = el('div', 'jarvis-composer-tools');
    const mic = button('Voice input unavailable in this browser', 'jarvis-icon-button', 'mic');
    mic.disabled = true;
    const send = button('Send message', 'jarvis-send', 'send');
    send.type = 'submit';
    send.disabled = true;
    const privacy = el('span', 'jarvis-privacy', 'Shipments & pending items only');
    tools.append(mic, privacy, send);
    form.append(label, input, tools);
    const voiceNote = el('p', 'jarvis-voice-note', 'Voice uses this device only when supported.');
    panel.append(header, selection, feed, status, prompts, form, voiceNote);
    root.append(panel, fab);
    container.append(root);

    let authenticated = false, opened = false, busy = false;
    let version = 0, conversation = null, latestText = '', lastFocus = null;
    let scope = { department_id: null, client_id: null, shipment_id: null };
    let recognition = null, listening = false, listeningTimer = null, speechActive = false;
    const compactPanel = matchMedia('(max-width:600px)');
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    let recognitionReady = false, host = container;

    function setStatus(text) { status.textContent = text || ''; status.hidden = !text; }
    function showError(error, fallback) {
      const message = error.message || fallback;
      setStatus(message);
      if (/start a new chat|visible shipments changed/i.test(message)) {
        const restart = button('Start a new chat', 'jarvis-restart');
        restart.textContent = 'Start a new chat';
        restart.addEventListener('click', () => { reset(); input.focus(); });
        status.append(restart);
      }
    }
    function updateSend() { send.disabled = busy || !input.value.trim(); }
    function setBusy(value) {
      busy = value;
      input.disabled = value;
      newChat.disabled = value;
      prompts.querySelectorAll('button').forEach(node => { node.disabled = value; });
      mic.disabled = value || !recognitionReady;
      updateSend();
      feed.setAttribute('aria-busy', String(value));
    }
    function localVoice() {
      if (!window.speechSynthesis) return null;
      const voices = speechSynthesis.getVoices().filter(voice => voice.localService && /^en(?:-|$)/i.test(voice.lang));
      return voices.find(voice => /^en-(NG|GB)/i.test(voice.lang)) || voices[0] || null;
    }
    function updateSpeak() {
      const available = Boolean(localVoice());
      speak.disabled = !latestText || !available;
      speak.title = available ? (speechActive ? 'Stop reading' : 'Read latest reply aloud') : 'Local English speech is unavailable in this browser';
      speak.setAttribute('aria-label', speak.title);
    }
    function stopVoice() {
      if (recognition) { const old = recognition; recognition = null; old.abort(); }
      clearTimeout(listeningTimer);
      listening = false;
      mic.classList.remove('jarvis-listening');
      mic.replaceChildren(icon('mic'));
      mic.setAttribute('aria-pressed', 'false');
      if (window.speechSynthesis) speechSynthesis.cancel();
      speechActive = false;
      speak.replaceChildren(icon('speaker'));
      updateSpeak();
    }
    function scrollEnd() { feed.scrollTop = feed.scrollHeight; }
    function addMessage(role, text, references) {
      const message = el('article', 'jarvis-message jarvis-message-' + role);
      message.append(el('span', 'jarvis-message-author', role === 'user' ? 'You' : 'Jarvis'));
      message.append(el('p', 'jarvis-message-text', text));
      if (role === 'assistant') {
        latestText = text;
        updateSpeak();
        if (Array.isArray(references) && references.length) {
          const links = el('div', 'jarvis-references');
          references.slice(0, 6).forEach(reference => {
            if (!Number.isInteger(reference.shipment_id) || reference.shipment_id <= 0) return;
            const link = button('Open ' + reference.label, 'jarvis-reference');
            link.append(el('span', '', reference.label), icon('arrow'));
            link.addEventListener('click', () => {
              stopVoice();
              if (options.onOpenShipment) options.onOpenShipment(reference.shipment_id, reference.tab);
            });
            links.append(link);
          });
          if (links.childElementCount) message.append(links);
        }
      }
      feed.append(message);
      // Conversations are intentionally short-lived and never copied into localStorage.
      while (feed.children.length > 26) feed.firstElementChild.remove();
      scrollEnd();
    }
    function updatePrompts() {
      prompts.replaceChildren();
      const values = ['What needs attention?', scope.shipment_id ? 'What is pending on this job?' : 'Brief me on next actions'];
      values.forEach(value => {
        const node = button(value, 'jarvis-prompt');
        node.textContent = value;
        node.addEventListener('click', () => submit(value));
        prompts.append(node);
      });
    }
    function renderReply(reply) {
      scopeLabel.textContent = reply.scope.shipment_id ? 'Selected job' : reply.scope.client_name || reply.scope.department_name || 'All visible shipments';
      const connected = reply.mode === 'hermes';
      modeLabel.textContent = connected ? 'Hermes · Read-only' : 'Local briefing';
      identity.querySelector('.jarvis-subtitle').textContent = connected ? 'Your shipment briefing' : 'Hermes connection pending';
      modeLabel.title = connected ? 'Hermes answered using the selected shipment context.' : 'Local guidance. The isolated Hermes connection is not active for this reply.';
      addMessage('assistant', reply.text, reply.references);
    }
    async function submit(value) {
      const message = String(value || input.value).trim();
      if (!message || message.length > 2000 || busy || !opened || !authenticated) return;
      stopVoice();
      const requestVersion = ++version;
      const body = { ...scope, message, turn_id: turnId() };
      if (conversation) body.conversation_id = conversation;
      input.value = '';
      addMessage('user', message);
      setBusy(true);
      setStatus('Checking shipment information…');
      try {
        const response = await options.api('/api/jarvis/chat', body);
        if (requestVersion !== version || !authenticated || !opened) return;
        conversation = response.conversation_id;
        renderReply(response);
        setStatus('');
      } catch (error) {
        if (requestVersion !== version || !authenticated || !opened) return;
        input.value = message;
        // An expired conversation must not leave the composer trapped behind the rejected ID.
        if (/start a new chat|visible shipments changed/i.test(error.message || '')) conversation = null;
        showError(error, 'Jarvis could not reply. Please try again.');
      } finally {
        if (requestVersion === version) { setBusy(false); input.focus(); }
      }
    }
    async function checkVoice() {
      updateSpeak();
      if (!SpeechRecognition || typeof SpeechRecognition.available !== 'function' || !('processLocally' in SpeechRecognition.prototype)) return;
      try {
        recognitionReady = await SpeechRecognition.available({ langs: ['en-US'], processLocally: true }) === 'available';
        mic.disabled = !recognitionReady || busy;
        mic.title = recognitionReady ? 'Dictate a message on this device' : 'On-device English speech recognition is unavailable';
        mic.setAttribute('aria-label', mic.title);
        voiceNote.textContent = recognitionReady ? 'Dictation stays on this device. Review the text before sending.' : 'On-device dictation unavailable. You can still type a message.';
      } catch (_) { recognitionReady = false; }
    }
    function open() {
      if (!authenticated || opened) return;
      opened = true;
      panel.setAttribute('aria-modal', String(compactPanel.matches));
      lastFocus = document.activeElement;
      panel.hidden = false;
      document.body.classList.add('jarvis-open');
      fab.hidden = true;
      fab.setAttribute('aria-expanded', 'true');
      input.focus();
      checkVoice();
    }
    function close() {
      if (!opened) return;
      opened = false;
      panel.setAttribute('aria-modal', 'false');
      document.body.classList.remove('jarvis-open');
      ++version;
      stopVoice();
      setBusy(false);
      setStatus('');
      panel.hidden = true;
      fab.hidden = false;
      fab.setAttribute('aria-expanded', 'false');
      const focus = lastFocus && lastFocus.isConnected ? lastFocus : fab;
      if (authenticated) focus.focus();
    }
    function reset() {
      ++version;
      stopVoice();
      conversation = null;
      latestText = '';
      input.value = '';
      feed.replaceChildren();
      setBusy(false);
      setStatus('');
      updateSpeak();
      updatePrompts();
    }
    function setContext(value) {
      scopeLabel.textContent = value?.shipment_id ? 'Selected job' : value?.client_name || value?.department_name || 'All visible shipments';
      const next = {};
      ['department_id', 'client_id', 'shipment_id'].forEach(key => {
        const id = Number(value && value[key]);
        next[key] = Number.isSafeInteger(id) && id > 0 ? id : null;
      });
      if (JSON.stringify(next) === JSON.stringify(scope)) return;
      scope = next;
      reset();
    }
    function setAuthenticated(value) {
      const next = value === true;
      if (authenticated === next) return;
      authenticated = next;
      if (!next) { close(); reset(); scope = { department_id: null, client_id: null, shipment_id: null }; }
      root.hidden = !next;
    }
    function cancelHost(event) {
      if (!opened) return;
      event.preventDefault();
      close();
    }
    function setHost(value) {
      const next = value || container;
      if (next === host || !next.appendChild || next === root || root.contains(next)) return;
      host.removeEventListener('cancel', cancelHost);
      const focus = root.contains(document.activeElement) ? document.activeElement : null;
      host = next;
      host.append(root);
      host.addEventListener('cancel', cancelHost);
      if (focus && opened) focus.focus();
    }
    fab.addEventListener('click', open);
    closeButton.addEventListener('click', close);
    newChat.addEventListener('click', () => { reset(); if (opened) input.focus(); });
    form.addEventListener('submit', event => { event.preventDefault(); submit(); });
    input.addEventListener('input', updateSend);
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); }
    });
    document.addEventListener('keydown', event => {
      if (opened && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
      if (opened && event.key === 'Tab' && compactPanel.matches) {
        const controls = [...panel.querySelectorAll('button:not(:disabled),textarea:not(:disabled)')].filter(node => node.getClientRects().length);
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }, true);
    compactPanel.addEventListener('change', () => panel.setAttribute('aria-modal', String(opened && compactPanel.matches)));
    document.addEventListener('visibilitychange', () => { if (document.hidden) stopVoice(); });
    speak.addEventListener('click', () => {
      if (speechActive) { stopVoice(); return; }
      const voice = localVoice();
      if (!latestText || !voice) return;
      stopVoice();
      const utterance = new SpeechSynthesisUtterance(latestText);
      utterance.voice = voice;
      utterance.lang = voice.lang;
      utterance.rate = 1;
      speechActive = true;
      speak.replaceChildren(icon('stop'));
      updateSpeak();
      utterance.onend = utterance.onerror = () => {
        speechActive = false;
        speak.replaceChildren(icon('speaker'));
        updateSpeak();
      };
      speechSynthesis.speak(utterance);
    });
    mic.addEventListener('click', () => {
      if (listening) { stopVoice(); setStatus('Dictation stopped. Review your message before sending.'); return; }
      if (!recognitionReady || busy || !authenticated || !opened) return;
      stopVoice();
      const current = new SpeechRecognition();
      // Never fall back to remote recognition when local language support is absent.
      current.processLocally = true;
      if (current.processLocally !== true) return;
      current.lang = 'en-US';
      current.interimResults = false;
      current.continuous = false;
      const draft = input.value;
      recognition = current;
      current.onresult = event => {
        if (recognition !== current || !authenticated || !opened) return;
        const result = Array.from(event.results).filter(item => item.isFinal).map(item => item[0].transcript).join(' ');
        input.value = (draft + (draft ? ' ' : '') + result).slice(0, 2000);
        updateSend();
      };
      current.onerror = () => { if (recognition === current) { stopVoice(); setStatus('Dictation could not finish. Type your message or try again.'); } };
      current.onend = () => { if (recognition === current) { recognition = null; stopVoice(); setStatus('Review your message, then send when ready.'); } };
      try {
        current.start();
        listening = true;
        mic.classList.add('jarvis-listening');
        mic.replaceChildren(icon('stop'));
        mic.setAttribute('aria-pressed', 'true');
        setStatus('Listening on this device. Tap stop when finished.');
        listeningTimer = setTimeout(() => { if (recognition === current) { stopVoice(); setStatus('Dictation stopped. Review your message.'); } }, 45000);
      } catch (_) { stopVoice(); setStatus('On-device dictation could not start. You can still type.'); }
    });
    if (window.speechSynthesis) speechSynthesis.addEventListener('voiceschanged', updateSpeak);
    updatePrompts();
    updateSpeak();
    mounted = { setContext, setAuthenticated, setHost, open, close, refresh() { reset(); } };
    return mounted;
  }
  window.LibraJarvis = { mount };
})();
