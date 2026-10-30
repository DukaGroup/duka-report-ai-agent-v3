import { useMemo } from "react";
import {
  ArrowRight,
  FileText,
  LoaderCircle,
  LogOut,
  MessageSquare,
  Plus,
  Settings,
  Trash2,
} from "lucide-react";
import { Brand } from "./Brand";
import { HanaSlot } from "./HanaFace";
import { UserAvatar } from "./UserAvatar";
import { label } from "./locale";
import type { Conversation, User } from "./types";
import "./home.css";

function greeting(name: string) {
  const hour = new Date().getHours();
  const salutation =
    hour < 12 ? "Mirëmëngjes" : hour < 18 ? "Mirëdita" : "Mirëmbrëma";
  return `${salutation}, ${name.trim().split(/\s+/)[0]}! Si mund t'ju ndihmoj sot?`;
}

/**
 * The workspace landing page. Hana speaks once each time the page is opened;
 * while her introduction is still flying in (`hanaArriving`) she waits.
 */
export function HomePage({
  user,
  conversations,
  reportCount,
  busy,
  onNewChat,
  onReports,
  onSettings,
  onLogout,
  onConversation,
  onDeleteConversation,
  conversationRunning,
  hanaArriving = false,
}: {
  user: User;
  conversations: Conversation[];
  reportCount: number;
  busy: boolean;
  onNewChat: () => void;
  onReports: () => void;
  onSettings: () => void;
  onLogout: () => void;
  onConversation: (conversation: Conversation) => void;
  onDeleteConversation: (conversation: Conversation) => void;
  conversationRunning: (id: string) => boolean;
  hanaArriving?: boolean;
}) {
  const line = useMemo(() => greeting(user.name), [user.name]);
  return (
    <main className="home-page">
      <div className="home-content">
        <header className="home-header">
          <Brand />
          <span className="home-header-caption">
            <span className="home-live-dot" aria-hidden="true" />
            HANA
          </span>
        </header>
        <div className="home-columns">
          <section className="home-navigation" aria-label="Fillimi">
            <div className="home-actions">
              <button
                className="home-new-chat"
                onClick={onNewChat}
                disabled={busy}
              >
                <Plus size={20} /> <span>Bisedë e re</span>{" "}
                <ArrowRight size={18} />
              </button>
              <button className="home-reports" onClick={onReports}>
                <FileText size={19} /> <span>Raportet</span>
                <span className="home-count">{reportCount}</span>
                <ArrowRight size={17} />
              </button>
            </div>
            <section className="home-history" aria-label="Bisedat e fundit">
              <h2>BISEDAT E FUNDIT</h2>
              <div className="home-history-list">
                {conversations.map((conversation) => (
                  <div className="home-conversation" key={conversation.id}>
                    <button
                      className="home-conversation-open"
                      onClick={() => onConversation(conversation)}
                      disabled={busy}
                    >
                      {conversationRunning(conversation.id) ? (
                        <LoaderCircle
                          size={17}
                          className="spin"
                          aria-label="Duke përgatitur përgjigjen"
                        />
                      ) : (
                        <MessageSquare size={17} />
                      )}
                      <span>{conversation.title}</span>
                      <ArrowRight
                        size={15}
                        className="home-conversation-arrow"
                      />
                    </button>
                    <button
                      className="home-conversation-delete"
                      aria-label={`Fshi bisedën: ${conversation.title}`}
                      onClick={() => onDeleteConversation(conversation)}
                      disabled={busy}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
                {!conversations.length && (
                  <p className="home-empty">
                    Bisedat tuaja do të shfaqen këtu.
                  </p>
                )}
              </div>
            </section>
          </section>
          <section className="home-greeting" aria-label="Përshëndetja e Hanës">
            <HanaSlot
              className="home-portrait"
              line={line}
              delay={180}
              awaiting={hanaArriving}
            />
            <p className={hanaArriving ? "is-waiting" : undefined}>{line}</p>
          </section>
        </div>
        <footer className="home-footer">
          <button className="home-settings" onClick={onSettings}>
            <Settings size={18} /> Cilësimet
          </button>
          <div className="home-account">
            <UserAvatar
              className="home-account-initial"
              name={user.name}
              seed={user.id}
            />
            <span className="home-account-label">
              {user.name}
              <small>{label(user.role)}</small>
            </span>
            <button
              aria-label="Dil nga llogaria"
              onClick={onLogout}
              disabled={busy}
            >
              <LogOut size={18} />
            </button>
          </div>
        </footer>
      </div>
    </main>
  );
}
