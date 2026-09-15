const NAV = [
  { view: 'accounts', label: 'Accounts', icon: '◎' },
  { view: 'content', label: 'Content', icon: '▤' },
  { view: 'research', label: 'Research', icon: '⌕' },
  { view: 'publish', label: 'Publish', icon: '↗' },
  { view: 'mcp', label: 'MCP access', icon: '⎔' },
];

function groupByDate(conversations) {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const groups = { Today: [], 'Previous 7 days': [], Older: [] };
  for (const conversation of conversations) {
    const time = new Date(conversation.updated_at).getTime();
    if (time >= startOfToday) groups.Today.push(conversation);
    else if (time >= startOfToday - 7 * 86400000) groups['Previous 7 days'].push(conversation);
    else groups.Older.push(conversation);
  }
  return Object.entries(groups).filter(([, items]) => items.length);
}

export default function Sidebar({ user, route, conversations, onNavigate, onDelete, onLogout, onClose }) {
  const initial = (user.name || user.email || '?').charAt(0).toUpperCase();
  return (
    <aside className="sidebar" aria-label="Navigation">
      <div className="sidebar-top">
        <button type="button" className="brand" onClick={() => onNavigate({ view: 'chat', conversationId: null })}>
          <span className="brand-mark">✦</span>
          <span className="brand-name">Content AI</span>
        </button>
        <button type="button" className="icon-btn sidebar-close" onClick={onClose} aria-label="Close menu">✕</button>
      </div>

      <button type="button" className="new-chat" onClick={() => onNavigate({ view: 'chat', conversationId: null })}>
        <span className="new-chat-icon">+</span> New chat
      </button>

      <nav className="nav">
        {NAV.map((item) => (
          <button key={item.view} type="button"
            className={`nav-item ${route.view === item.view ? 'active' : ''}`}
            onClick={() => onNavigate({ view: item.view, conversationId: null })}>
            <span className="nav-icon" aria-hidden="true">{item.icon}</span>{item.label}
          </button>
        ))}
      </nav>

      <div className="recents">
        {conversations.length === 0 && <p className="recents-empty">Your conversations will appear here.</p>}
        {groupByDate(conversations).map(([label, items]) => (
          <div key={label} className="recents-group">
            <div className="recents-label">{label}</div>
            {items.map((conversation) => (
              <div key={conversation.id}
                className={`recent ${route.view === 'chat' && route.conversationId === conversation.id ? 'active' : ''}`}>
                <button type="button" className="recent-title" title={conversation.title}
                  onClick={() => onNavigate({ view: 'chat', conversationId: conversation.id })}>
                  {conversation.title}
                </button>
                <button type="button" className="recent-delete" aria-label={`Delete ${conversation.title}`}
                  onClick={() => window.confirm('Delete this conversation?') && onDelete(conversation.id)}>✕</button>
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="sidebar-user">
        {user.picture_url ? <img className="avatar" src={user.picture_url} alt="" referrerPolicy="no-referrer" />
          : <span className="avatar avatar-initial">{initial}</span>}
        <div className="user-meta">
          <span className="user-name">{user.name}{user.is_demo && <span className="badge badge-mock">DEMO</span>}</span>
          <span className="user-email">{user.email}</span>
        </div>
        <button type="button" className="icon-btn" onClick={onLogout} title="Sign out" aria-label="Sign out">⏻</button>
      </div>
    </aside>
  );
}
