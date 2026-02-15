import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router";
import { useAuth } from "./hooks/useAuth";
import Header from "./components/Header";
import ChatList from "./components/ChatList";
import ChatView from "./components/ChatView";
import FileTree from "./components/FileTree";
import FileViewer from "./components/FileViewer";
import FileSearchDialog from "./components/FileSearchDialog";

export default function App() {
  const auth = useAuth();
  const { chatId: urlChatId } = useParams<{ chatId: string }>();
  const navigate = useNavigate();
  const selectedChatId = urlChatId || null;
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [chatListOpen, setChatListOpen] = useState(false);
  const [openFiles, setOpenFiles] = useState<string[]>([]);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [chatMaximize, setChatMaximize] = useState(() => localStorage.getItem("chatMaximize") === "true");
  const [chatHide, setChatHide] = useState(() => localStorage.getItem("chatHide") === "true");
  const [fileSearchOpen, setFileSearchOpen] = useState(false);

  const handleOpenFile = useCallback((path: string) => {
    setOpenFiles((files) => files.includes(path) ? files : [...files, path]);
    setActiveFile(path);
  }, []);

  const handleCloseFile = useCallback((path: string) => {
    setOpenFiles((files) => {
      const idx = files.indexOf(path);
      const next = files.filter((f) => f !== path);
      setActiveFile((cur) => {
        if (cur !== path) return cur;
        if (next.length === 0) return null;
        return next[Math.min(idx, next.length - 1)];
      });
      return next;
    });
  }, []);

  useEffect(() => { localStorage.setItem("chatMaximize", String(chatMaximize)); }, [chatMaximize]);
  useEffect(() => { localStorage.setItem("chatHide", String(chatHide)); }, [chatHide]);

  const activeFileRef = useRef(activeFile);
  activeFileRef.current = activeFile;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "`") {
        e.preventDefault();
        setChatHide((v) => !v);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "p") {
        e.preventDefault();
        setFileSearchOpen(true);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "w") {
        e.preventDefault();
        if (activeFileRef.current) handleCloseFile(activeFileRef.current);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleCloseFile]);

  const handleSelectChat = useCallback((id: string | null) => {
    navigate(id ? `/${id}` : "/");
    setSidebarOpen(false);
    setChatListOpen(false);
  }, [navigate]);

  const handleChatCreated = useCallback((chatId: string) => {
    navigate(`/${chatId}`);
    setSidebarOpen(false);
    setChatListOpen(false);
  }, [navigate]);

  const handleLogout = useCallback(() => {
    auth.logout();
    navigate("/");
  }, [auth, navigate]);

  return (
    <div className="h-dvh flex flex-col overflow-hidden">
      <Header key={String(auth.isLoggedIn)} email={auth.email} isLoggedIn={auth.isLoggedIn} gsiReady={auth.gsiReady} onLogout={handleLogout} onToggleSidebar={() => setSidebarOpen((v) => !v)} onClickLogo={() => handleSelectChat(null)} />
      <div className="flex flex-1 min-h-0">
        {/* Mobile overlay backdrop */}
        {(sidebarOpen || chatListOpen) && (
          <div className="fixed inset-0 bg-black/40 z-20 md:hidden" onClick={() => { setSidebarOpen(false); setChatListOpen(false); }} />
        )}
        {/* Left: FileTree */}
        <div className={`
          fixed inset-y-0 left-0 z-30 w-80 transform transition-transform duration-200 md:relative md:translate-x-0 md:z-auto shrink-0 border-r border-sol-base02 bg-sol-base03 overflow-hidden
          ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
        `}>
          <FileTree isLoggedIn={auth.isLoggedIn} onSelectFile={handleOpenFile} />
        </div>
        {/* Right */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          {/* Right top: FileViewer (always takes half, hidden content when no file) */}
          {(!chatMaximize || chatHide) && (
            <div className={`${chatHide ? "flex-1" : "h-2/5"} min-h-0 overflow-hidden`}>
              <FileViewer openFiles={openFiles} activeFile={activeFile} onSelectFile={setActiveFile} onCloseFile={handleCloseFile} />
            </div>
          )}
          {/* Toolbar (always visible) */}
          <div className="flex items-center justify-end gap-1 px-3 py-0.5 border-t border-sol-base02 bg-sol-base03 shrink-0">
            {!chatHide && (
              <button
                onClick={() => handleSelectChat(null)}
                className="p-1 text-sol-base01 hover:text-sol-base1 bg-sol-base02 rounded cursor-pointer"
                title="New task"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <line x1="7" y1="2" x2="7" y2="12" />
                  <line x1="2" y1="7" x2="12" y2="7" />
                </svg>
              </button>
            )}
            {!chatHide && (
              <button
                onClick={() => setChatMaximize((v) => !v)}
                className="p-1 text-sol-base01 hover:text-sol-base1 bg-sol-base02 rounded cursor-pointer"
                title={chatMaximize ? "Restore chat" : "Maximize chat"}
              >
                {chatMaximize ? (
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <polyline points="1,5 5,5 5,1" />
                    <polyline points="13,5 9,5 9,1" />
                    <polyline points="1,9 5,9 5,13" />
                    <polyline points="13,9 9,9 9,13" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <polyline points="5,1 1,1 1,5" />
                    <polyline points="9,1 13,1 13,5" />
                    <polyline points="1,9 1,13 5,13" />
                    <polyline points="13,9 13,13 9,13" />
                  </svg>
                )}
              </button>
            )}
            {!chatHide && (
              <button
                onClick={() => setChatListOpen((v) => !v)}
                className="md:hidden p-1 text-sol-base01 hover:text-sol-base1 bg-sol-base02 rounded cursor-pointer"
                title="Toggle task list"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              </button>
            )}
            <button
              onClick={() => setChatHide((v) => !v)}
              className="p-1 text-sol-base01 hover:text-sol-base1 bg-sol-base02 rounded cursor-pointer"
              title={chatHide ? "Open terminal (Ctrl+`)" : "Close terminal (Ctrl+`)"}
            >
              {chatHide ? (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <polyline points="2,4 6,7 2,10" />
                  <line x1="7" y1="11" x2="12" y2="11" />
                </svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <line x1="3" y1="3" x2="11" y2="11" />
                  <line x1="11" y1="3" x2="3" y2="11" />
                </svg>
              )}
            </button>
          </div>
          {/* Right bottom: ChatView + ChatList */}
          <div className={`flex flex-col min-h-0 ${chatMaximize ? "flex-1" : "h-3/5"} ${chatHide ? "hidden" : ""}`}>
            <div className="flex flex-1 min-h-0">
            <div className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden">
              <ChatView
                chatId={selectedChatId}
                onChatCreated={handleChatCreated}
                isLoggedIn={auth.isLoggedIn}
              />
            </div>
            {/* Mobile chat list overlay */}
            <div className={`
              fixed inset-y-0 right-0 z-30 w-80 transform transition-transform duration-200 md:relative md:translate-x-0 md:z-auto shrink-0 border-l border-sol-base02 bg-sol-base03 overflow-hidden
              ${chatListOpen ? "translate-x-0" : "translate-x-full"}
            `}>
              <ChatList
                isLoggedIn={auth.isLoggedIn}
                selectedChatId={selectedChatId}
                onSelectChat={handleSelectChat}
              />
            </div>
            </div>
          </div>
        </div>
      </div>
      <FileSearchDialog open={fileSearchOpen} onClose={() => setFileSearchOpen(false)} onSelectFile={handleOpenFile} />
    </div>
  );
}
