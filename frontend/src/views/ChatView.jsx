import { useEffect, useRef, useState } from 'react';
import { api, isMock } from '../api.js';
import Composer, { MODES } from '../components/Composer.jsx';
import ExampleList from '../components/ExampleList.jsx';
import Markdown from '../components/Markdown.jsx';

const SUGGESTIONS = [
  { mode: 'chat', text: 'Which type of content works best for my audience?' },
  { mode: 'plan', text: 'A week of posts for our next product launch' },
  { mode: 'chat', text: 'Why did my best posts perform so well?' },
  { mode: 'hashtags', text: 'Weekend special: our new seasonal menu is here. Come try it!' },
];

function greeting(name) {
  const hour = new Date().getHours();
  const part = hour < 5 ? 'Up late' : hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const first = (name || '').replace(/\s*\(demo\)$/, '').split(' ')[0];
  return first ? `${part}, ${first}` : part;
}

function Message({ message }) {
  if (message.role === 'user') {
    return (
      <div className="msg msg-user">
        {message.mode !== 'chat' && <span className="msg-mode">{MODES.find((m) => m.id === message.mode)?.label}</span>}
        <div className="msg-bubble">{message.content}</div>
      </div>
    );
  }
  return (
    <div className={`msg msg-assistant ${message.is_error ? 'msg-error' : ''}`}>
      <span className="msg-avatar" aria-hidden="true">✦</span>
      <div className="msg-body">
        {isMock(message.content) && <span className="badge badge-mock">MOCK AI</span>}
        <div className="serif-body"><Markdown text={message.content} /></div>
        {message.examples?.length > 0 && <ExampleList examples={message.examples} />}
      </div>
    </div>
  );
}

export default function ChatView({ user, conversationId, onCreated, onUpdated, goTo }) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(Boolean(conversationId));
  const [loadError, setLoadError] = useState('');
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState('chat');
  const [sources, setSources] = useState(['own', 'competitor', 'hashtag']);
  const idRef = useRef(conversationId);
  const endRef = useRef(null);

  useEffect(() => {
    if (!conversationId) return;
    api.get(`/conversations/${conversationId}`)
      .then((data) => setMessages(data.messages))
      .catch((err) => setLoadError(err.message))
      .finally(() => setLoading(false));
    // Only on mount: a new conversation receiving its id must not reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, busy]);

  const send = async (text, sendMode = mode) => {
    const optimistic = { id: `tmp-${Date.now()}`, role: 'user', mode: sendMode, content: text };
    setMessages((prev) => [...prev, optimistic]);
    setBusy(true);
    try {
      const data = await api.post('/chat', {
        conversation_id: idRef.current, message: text, mode: sendMode,
        sources: sendMode === 'hashtags' ? undefined : sources,
      });
      setMessages((prev) => [...prev.filter((m) => m.id !== optimistic.id), data.user_message, data.assistant_message]);
      if (!idRef.current) {
        idRef.current = data.conversation.id;
        onCreated(data.conversation);
      } else {
        onUpdated();
      }
    } catch (err) {
      setMessages((prev) => [...prev, { id: `err-${Date.now()}`, role: 'assistant', mode: sendMode, is_error: true,
        content: `Couldn't send your message: ${err.message}` }]);
    } finally {
      setBusy(false);
    }
  };

  const composer = (
    <Composer onSend={send} busy={busy} mode={mode} onModeChange={setMode} sources={sources}
      onSourcesChange={setSources} autoFocus />
  );

  if (loadError) {
    return (
      <div className="chat-empty">
        <p className="muted">{loadError}</p>
      </div>
    );
  }

  if (!loading && messages.length === 0) {
    return (
      <div className="chat-empty">
        <div className="chat-empty-inner">
          <h1 className="greeting serif"><span className="brand-mark">✦</span>{greeting(user.name)}</h1>
          {composer}
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s.text} type="button" className="suggestion" onClick={() => { setMode(s.mode); send(s.text, s.mode); }}>
                <span className="suggestion-mode">{MODES.find((m) => m.id === s.mode).label}</span>
                {s.text}
              </button>
            ))}
          </div>
          {user.connections === 0 && (
            <p className="empty-hint">
              Answers are grounded in your synced posts. <button type="button" className="link" onClick={() => goTo('accounts')}>Connect your accounts</button> first.
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="chat">
      <div className="chat-scroll">
        <div className="thread">
          {loading && <p className="muted center">Loading conversation…</p>}
          {messages.map((message) => <Message key={message.id} message={message} />)}
          {busy && (
            <div className="msg msg-assistant">
              <span className="msg-avatar thinking" aria-hidden="true">✦</span>
              <div className="typing" aria-label="Thinking"><span /><span /><span /></div>
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>
      <div className="chat-footer">
        {composer}
        <p className="disclaimer">Answers are based on your synced posts and can be wrong. Check before publishing.</p>
      </div>
    </div>
  );
}
