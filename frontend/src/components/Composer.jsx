import { useEffect, useRef, useState } from 'react';

export const MODES = [
  { id: 'chat', label: 'Chat', placeholder: 'Ask about your content, audience, hooks…' },
  { id: 'plan', label: 'Content plan', placeholder: 'A topic, hashtag or draft caption to plan 3 posts for…' },
  { id: 'hashtags', label: 'Hashtags', placeholder: 'Paste a draft caption to get hashtag ideas…' },
];

const SOURCES = [['own', 'My posts'], ['competitor', 'Competitors'], ['hashtag', 'Hashtag research']];

export default function Composer({ onSend, busy, mode, onModeChange, sources, onSourcesChange, autoFocus }) {
  const [text, setText] = useState('');
  const [showSources, setShowSources] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [text]);

  const submit = () => {
    const value = text.trim();
    if (!value || busy) return;
    onSend(value);
    setText('');
  };

  const toggleSource = (id) => {
    const next = sources.includes(id) ? sources.filter((s) => s !== id) : [...sources, id];
    if (next.length) onSourcesChange(next);
  };

  const current = MODES.find((m) => m.id === mode);

  return (
    <div className="composer">
      <textarea
        ref={ref}
        rows={1}
        value={text}
        autoFocus={autoFocus}
        placeholder={current.placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        aria-label="Message"
      />
      <div className="composer-bar">
        <div className="composer-tools">
          <div className="mode-pills" role="radiogroup" aria-label="Mode">
            {MODES.map((m) => (
              <button key={m.id} type="button" role="radio" aria-checked={mode === m.id}
                className={`pill ${mode === m.id ? 'pill-active' : ''}`} onClick={() => onModeChange(m.id)}>
                {m.label}
              </button>
            ))}
          </div>
          {mode !== 'hashtags' && (
            <div className="sources">
              <button type="button" className="pill pill-quiet" aria-expanded={showSources}
                onClick={() => setShowSources((s) => !s)}>
                Sources · {sources.length === SOURCES.length ? 'All' : sources.length}
              </button>
              {showSources && (
                <div className="sources-menu" role="group" aria-label="Learn from">
                  <span className="sources-title">Learn from</span>
                  {SOURCES.map(([id, label]) => (
                    <label key={id} className="check">
                      <input type="checkbox" checked={sources.includes(id)} onChange={() => toggleSource(id)} /> {label}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        <button type="button" className="send" onClick={submit} disabled={busy || !text.trim()} aria-label="Send">
          ↑
        </button>
      </div>
    </div>
  );
}
