import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowLeft,
  RotateCcw,
  Search,
  Check,
  CircleHelp,
  Database,
  FileText,
  History,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  MessageSquare,
  Plus,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Unplug,
  Paperclip,
  Pencil,
  X,
} from "lucide-react";
import { MarkdownContent } from "./MarkdownContent";
import { Brand } from "./Brand";
import { Select } from "./Select";
import { TrafficPanel } from "./TrafficPanel";
import { api, streamChat } from "./api";
import {
  ConversationRuns,
  pendingAssistantMessages,
  messagesBeforeRestart,
  runningReports,
} from "./conversationRuns";
import { label, errorMessage, auditLabel } from "./locale";
import { recoverSubscription } from "./subscriptionRecovery";
import { buildChatTimeline } from "./chatTimeline";
import type {
  Audit,
  Attachment,
  Conversation,
  Dataset,
  Login,
  Message,
  Model,
  Provider,
  Overview,
  RateLimits,
  Report,
  Source,
  Subscription,
  Template,
  User,
} from "./types";

type Page =
  | "conversations"
  | "chat"
  | "reports"
  | "sources"
  | "connection"
  | "admin";
function cReasoning(c: Conversation) {
  return c.reasoning_effort || "";
}
const initialSubscription: Subscription = { connected: false, available: true };
function providerLoginUrl(login: Login) {
  try {
    const url = new URL(login.verificationUrl || "");
    const hosts =
      login.provider === "claude"
        ? ["claude.com", "claude.ai", "platform.claude.com"]
        : ["auth.openai.com"];
    return url.protocol === "https:" && hosts.includes(url.hostname);
  } catch {
    return false;
  }
}
const date = (value: string) =>
  new Date(value).toLocaleDateString("sq-AL", {
    month: "short",
    day: "numeric",
  });

function Badge({
  children,
  good = false,
}: {
  children: ReactNode;
  good?: boolean;
}) {
  return (
    <span className={`badge ${good ? "good" : ""}`}>
      <span />
      {children}
    </span>
  );
}
function ThinkingDots({ description }: { description: string }) {
  return (
    <div
      className="thinking"
      role="status"
      aria-label={description}
      title={description}
    >
      <span aria-hidden="true" />
      <span aria-hidden="true" />
      <span aria-hidden="true" />
    </div>
  );
}
function Modal({
  title,
  children,
  onClose,
  error,
  className,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  error?: string;
  className?: string;
}) {
  return (
    <div className="modal-scrim" onClick={onClose}>
      <section
        className={`modal ${className || ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-title">
          <h2>{title}</h2>
          <button
            className="icon-button"
            aria-label="Mbyll dritaren"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        {error && (
          <p className="error-box" role="alert">
            {error}
          </p>
        )}
        {children}
      </section>
    </div>
  );
}

function Auth({
  setup,
  onDone,
}: {
  setup: boolean;
  onDone: (u: User) => void;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      onDone(
        await api<User>(`/auth/${setup ? "setup" : "login"}`, {
          method: "POST",
          body: JSON.stringify(data),
        }),
      );
    } catch (e) {
      setError(errorMessage((e as Error).message));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-page">
      <div className="auth-brand">
        <Brand />
      </div>
      <div className="auth-card">
        <span className="eyebrow"> Një pamje më e qartë e biznesit tuaj </span>
        <h1>
          {setup ? "Mirë se vini në hapësirën tuaj." : "Mirë se u kthyet."}
        </h1>
        <p>
          {setup
            ? "Krijoni llogarinë e administratorit. Pasi të hyni, lidhni abonimin tuaj ChatGPT ose Claude."
            : "Hyni në llogari për të vazhduar bisedat dhe raportet tuaja."}
        </p>
        <form onSubmit={submit}>
          {setup && (
            <label>
              {" "}
              Emri juaj{" "}
              <input
                name="name"
                required
                autoComplete="name"
                placeholder="Administratori i hapësirës"
              />
            </label>
          )}
          <label>
            {" "}
            Adresa e emailit{" "}
            <input
              name="email"
              type="email"
              required
              autoComplete="username"
              placeholder="you@company.com"
            />
          </label>
          <label>
            {" "}
            Fjalëkalimi{" "}
            <input
              name="password"
              type="password"
              required
              minLength={setup ? 12 : 1}
              autoComplete={setup ? "new-password" : "current-password"}
              placeholder={
                setup
                  ? "Të paktën 12 karaktere"
                  : "Fjalëkalimi i llogarisë suaj"
              }
            />
          </label>
          {error && (
            <p className="error-box" role="alert">
              {error}
            </p>
          )}
          <button className="button primary wide" disabled={busy}>
            {busy ? (
              <LoaderCircle className="spin" size={18} />
            ) : (
              <ArrowRight size={18} />
            )}{" "}
            {setup ? "Krijo hapësirën" : "Hyr"}
          </button>
        </form>
        <div className="auth-note">
          <ShieldCheck size={16} /> Lidhja e abonimit kryhet përmes OpenAI ose
          Anthropic.{" "}
        </div>
      </div>
      <p className="auth-footer">
        {" "}
        DUKA GROUP <span> Biseda që sjellin qartësi. </span>
      </p>
    </div>
  );
}

export default function App() {
  const [loading, setLoading] = useState(true),
    [setup, setSetup] = useState(false),
    [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const stop = recoverSubscription(
      async () => {
        try {
          const r = await api<{ needs_setup: boolean; user: User | null }>(
            "/auth/status",
          );
          if (active) {
            setSetup(r.needs_setup);
            setUser(r.user);
            setError("");
          }
          return true;
        } catch (e) {
          if (active) setError(errorMessage((e as Error).message));
          return false;
        } finally {
          if (active) setLoading(false);
        }
      },
      5000,
      true,
    );
    return () => {
      active = false;
      stop();
    };
  }, []);
  if (loading)
    return (
      <div className="loading-screen">
        <Brand />
        <LoaderCircle className="spin" />
        <p> Duke hapur hapësirën… </p>
      </div>
    );
  if (error && !user)
    return (
      <div className="loading-screen">
        <p role="alert">{error}</p>
        <p>Po provojmë lidhjen përsëri automatikisht…</p>
        <button
          className="button primary"
          onClick={() => window.location.reload()}
        >
          {" "}
          Provo përsëri{" "}
        </button>
      </div>
    );
  if (!user)
    return (
      <Auth
        setup={setup}
        onDone={(u) => {
          setUser(u);
          setSetup(false);
        }}
      />
    );
  return <Workspace key={user.id} user={user} onLogout={() => setUser(null)} />;
}

function Workspace({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [page, setPage] = useState<Page>("conversations"),
    [error, setError] = useState("");
  const [subscription, setSubscription] =
      useState<Subscription>(initialSubscription),
    [login, setLogin] = useState<Login | null>(null),
    [connecting, setConnecting] = useState(false);
  const [providerSubscriptions, setProviderSubscriptions] = useState<
    Record<Provider, Subscription>
  >({ chatgpt: initialSubscription, claude: initialSubscription });
  const [choosingProvider, setChoosingProvider] = useState(false);
  const [loginCode, setLoginCode] = useState("");
  const selectedProvider = subscription.provider_id || "chatgpt";
  const providerName = selectedProvider === "claude" ? "Claude" : "ChatGPT";
  const [models, setModels] = useState<Model[]>([]),
    [model, setModel] = useState("");
  const subscriptionRequest = useRef<Promise<Subscription> | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]),
    [currentId, setCurrentId] = useState<string | null>(null),
    [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [retryMessageId, setRetryMessageId] = useState<string | null>(null);
  const [reasoningEffort, setReasoningEffort] = useState("");
  const supportedEfforts =
    models.find((m) => m.model === model)?.supported_reasoning_efforts || [];
  const effort = supportedEfforts.includes(reasoningEffort)
    ? reasoningEffort
    : "";
  const effortLabels: Record<string, string> = {
    none: "Pa arsyetim",
    minimal: "Minimal",
    low: "I ulët",
    medium: "Mesatar",
    high: "I lartë",
    xhigh: "Shumë i lartë",
    max: "Maksimal",
  };
  const runs = useRef(new ConversationRuns());
  const [, refreshRuns] = useState(0);
  const busy =
    runs.current.has(currentId) ||
    messages.some((m) => m.status === "streaming");
  const activity = runs.current.activity(currentId);
  const drafts = useRef(
    new Map<
      string,
      {
        draft: string;
        attachments: Attachment[];
        model: string;
        reasoningEffort: string;
        retryMessageId: string | null;
      }
    >(),
  );
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>(
    [],
  );
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const [limits, setLimits] = useState<RateLimits | null>(null);
  const [reportsLoaded, setReportsLoaded] = useState(false);
  const [stoppingIds, setStoppingIds] = useState<Record<string, boolean>>({});
  const stoppingReports = !!stoppingIds[currentId || ""];
  const [reports, setReports] = useState<Report[]>([]),
    [report, setReport] = useState<Report | null>(null),
    [templates, setTemplates] = useState<Template[]>([]),
    [datasets, setDatasets] = useState<Dataset[]>([]),
    [reportForm, setReportForm] = useState(false);
  const activeReports = runningReports(reports, currentId);
  const reportBusy = activeReports.length > 0;
  const pendingMessages = pendingAssistantMessages(
    messages,
    reports,
    currentId,
  );
  const pendingDescription = reportBusy
    ? "Raporti në Excel po përgatitet"
    : activity || "Në pritje të përgjigjes";
  const chatLocked =
    busy || reportBusy || !reportsLoaded || stoppingReports || uploading;
  const reasoningControl = (
    <label className="reasoning-picker">
      Arsyetimi
      <Select
        aria-label="Niveli i arsyetimit"
        value={effort}
        disabled={chatLocked || !subscription.connected}
        onChange={(e) => setReasoningEffort(e.target.value)}
      >
        <option value="">Automatik</option>
        {supportedEfforts.map((level) => (
          <option key={level} value={level}>
            {effortLabels[level] || level}
          </option>
        ))}
      </Select>
    </label>
  );

  const reportBusyRef = useRef(false);
  reportBusyRef.current = reportBusy;
  const [overview, setOverview] = useState<Overview | null>(null),
    [users, setUsers] = useState<User[]>([]),
    [sources, setSources] = useState<Source[]>([]),
    [adminDatasets, setAdminDatasets] = useState<Dataset[]>([]),
    [audit, setAudit] = useState<Audit[]>([]);
  const [adminTab, setAdminTab] = useState("overview"),
    [addUser, setAddUser] = useState(false),
    [addSource, setAddSource] = useState(false),
    [addDataset, setAddDataset] = useState(false),
    [grant, setGrant] = useState<Dataset | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [businessSources, setBusinessSources] = useState<Source[]>([]);
  const [sourceAccess, setSourceAccess] = useState<Source | null>(null);
  const [sourceGrants, setSourceGrants] = useState<string[]>([]);
  const [editSource, setEditSource] = useState<Source | null>(null);
  const [sourceKind, setSourceKind] = useState("sqlserver");
  const [savingSource, setSavingSource] = useState(false);
  const [overrideEnvironment, setOverrideEnvironment] = useState(false);
  const [autoDiscoverDatabases, setAutoDiscoverDatabases] = useState(true);
  const [sourceActions, setSourceActions] = useState<Record<string, boolean>>(
    {},
  );
  const [deleteSource, setDeleteSource] = useState<Source | null>(null);
  const [databaseBrowser, setDatabaseBrowser] = useState<Source | null>(null);
  const [serverDatabases, setServerDatabases] = useState<
    { name: string; is_default: number }[]
  >([]);
  const [databaseOffset, setDatabaseOffset] = useState<number | null>(null);
  const [loadingDatabases, setLoadingDatabases] = useState(false);
  const environmentActive =
    editSource?.configuration_origin === "environment" &&
    !overrideEnvironment &&
    sourceKind === editSource.kind;
  const sourcePrefix = sourceKind === "saphana" ? "HANA" : "SQLSERVER";
  const sourceSupported =
    sourceKind === "sqlserver" || sourceKind === "saphana";
  const changingSourceKind = !!editSource && editSource.kind !== sourceKind;
  const keepConnectionFields =
    !!editSource &&
    (editSource.configuration_origin === "saved" || changingSourceKind);
  const [conversationSearch, setConversationSearch] = useState("");
  const [openingConversation, setOpeningConversation] = useState(false);
  const [deleteReport, setDeleteReport] = useState<Report | null>(null);
  const [deletingReport, setDeletingReport] = useState(false);
  const [reportTrash, setReportTrash] = useState(false);
  const [deletedReports, setDeletedReports] = useState<Report[]>([]);
  const [emptyTrashConfirm, setEmptyTrashConfirm] = useState(false);
  const [emptyingTrash, setEmptyingTrash] = useState(false);
  const [restoringReportId, setRestoringReportId] = useState<string | null>(
    null,
  );
  const reportSelection = useRef<string | null>(null);
  const [deleteChat, setDeleteChat] = useState<Conversation | null>(null);
  const [chatHistory, setChatHistory] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [checkingSource, setCheckingSource] = useState<string | null>(null);
  const messageScroll = useRef<HTMLDivElement>(null),
    scrolledConversation = useRef<string | null>(null),
    mounted = useRef(true),
    activeId = useRef<string | null>(null);

  const fail = (e: unknown) =>
    setError(errorMessage((e as Error).message || "Ndodhi një gabim."));
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    activeId.current = currentId;
  }, [currentId]);
  useLayoutEffect(() => {
    if (page !== "chat") {
      scrolledConversation.current = null;
      return;
    }
    const switched = scrolledConversation.current !== currentId;
    scrolledConversation.current = currentId;
    const scroll = messageScroll.current;
    scroll?.scrollTo({
      top: scroll.scrollHeight,
      behavior: switched || busy ? "instant" : "smooth",
    });
  }, [messages, busy, reportBusy, currentId, page]);
  async function loadSubscription() {
    if (subscriptionRequest.current) return subscriptionRequest.current;
    const request = fetchSubscription().catch((e: unknown) => {
      if (mounted.current)
        setSubscription((prev) => ({
          ...prev,
          connected: false,
          available: false,
          error: errorMessage((e as Error).message),
        }));
      throw e;
    });
    subscriptionRequest.current = request;
    try {
      return await request;
    } finally {
      if (subscriptionRequest.current === request)
        subscriptionRequest.current = null;
    }
  }
  async function fetchSubscription() {
    const result = await api<Subscription>("/subscription");
    if (!mounted.current) return result;
    setSubscription(result);
    const provider = result.provider_id || "chatgpt";
    const other: Provider = provider === "chatgpt" ? "claude" : "chatgpt";
    const otherStatus = await api<Subscription>(
      `/subscription?provider=${other}`,
    ).catch(() => ({ connected: false, available: false }) as Subscription);
    if (!mounted.current) return result;
    const statuses = { [provider]: result, [other]: otherStatus } as Record<
      Provider,
      Subscription
    >;
    setProviderSubscriptions(statuses);
    const loginProvider = login?.provider || provider;
    if (statuses[loginProvider].login?.status === "failed") {
      setLogin(null);
      setError(
        statuses[loginProvider].login?.error ||
          "Hyrja nuk përfundoi. Provoni përsëri.",
      );
    }
    setLogin((prev) =>
      prev && statuses[prev.provider || "chatgpt"].connected ? null : prev,
    );
    if (result.connected) {
      const list = await api<Model[]>(
        `/subscription/models?provider=${provider}`,
      );
      if (!mounted.current) return result;
      setModels(list);
      setModel((prev) =>
        list.some((m) => m.model === prev)
          ? prev
          : (list.find((m) => m.isDefault) || list[0])?.model || "",
      );
    } else {
      setModels([]);
      setModel("");
    }
    return result;
  }
  async function loadReports() {
    const next = await api<Report[]>("/reports");
    reportBusyRef.current = runningReports(next, activeId.current).length > 0;
    setReports(next);
    setReportsLoaded(true);
    if (reportTrash)
      setDeletedReports(await api<Report[]>("/reports?deleted=true"));
  }
  async function loadAdmin() {
    const [o, u, s, d, a] = await Promise.all([
      api<Overview>("/admin/overview"),
      api<User[]>("/admin/users"),
      api<Source[]>("/admin/sources"),
      api<Dataset[]>("/admin/datasets"),
      api<Audit[]>("/admin/audit"),
    ]);
    setOverview(o);
    setUsers(u);
    setSources(s);
    setAdminDatasets(d);
    setAudit(a);
    setBusinessSources(await api<Source[]>("/sources"));
  }
  useEffect(() => {
    if (!user) return;
    void Promise.all([
      loadSubscription().catch(() => undefined),
      api<Conversation[]>("/conversations").then(setConversations),
      api<Template[]>("/report-templates").then(setTemplates),
      api<Dataset[]>("/datasets").then(setDatasets),
      api<Source[]>("/sources").then(setBusinessSources),
      loadReports(),
    ]).catch(fail);
  }, [user]);
  useEffect(() => {
    if (user?.role === "devs" && (page === "admin" || page === "sources"))
      void loadAdmin().catch(fail);
  }, [page, user]);
  useEffect(() => {
    if (subscription.available) return;
    return recoverSubscription(
      async () => (await loadSubscription()).available,
    );
  }, [subscription.available]);
  useEffect(() => {
    if (!login) return;
    const timer = setInterval(() => {
      void loadSubscription().catch(() => undefined);
    }, 3000);
    return () => clearInterval(timer);
  }, [login?.loginId]);
  useEffect(() => {
    const timer = setInterval(
      () => {
        void loadReports().catch(fail);
        if (report && ["queued", "running"].includes(report.status))
          void api<Report>(`/reports/${report.id}`)
            .then((next) => {
              if (reportSelection.current === next.id) setReport(next);
            })
            .catch(fail);
      },
      runs.current.size ||
        reports.some((r) => ["queued", "running"].includes(r.status))
        ? 1000
        : 5000,
    );
    return () => clearInterval(timer);
  }, [
    busy,
    reportBusy,
    reports.some((r) => ["queued", "running"].includes(r.status)),
    report?.id,
    report?.status,
    reportTrash,
  ]);

  useEffect(() => {
    let disposed = false;
    const poll = async () => {
      try {
        const list = await api<Conversation[]>("/conversations");
        if (disposed) return;
        setConversations(list);
        const id = activeId.current;
        if (
          id &&
          !runs.current.has(id) &&
          (list.some((c) => c.id === id && c.running) ||
            messages.some((m) => m.status === "streaming"))
        ) {
          const detail = await api<Conversation & { messages: Message[] }>(
            `/conversations/${id}`,
          );
          if (!disposed && activeId.current === id && !runs.current.has(id))
            setMessages(detail.messages);
        }
      } catch {
        /* The normal request path surfaces connection errors. */
      }
    };
    const timer = setInterval(() => void poll(), 1500);
    return () => {
      disposed = true;
      clearInterval(timer);
    };
  }, [currentId, busy]);

  async function connect(provider: Provider = selectedProvider) {
    setConnecting(true);
    setError("");
    try {
      setLoginCode("");
      setLogin(
        await api<Login>(`/subscription/login?provider=${provider}`, {
          method: "POST",
        }),
      );
    } catch (e) {
      fail(e);
    } finally {
      setConnecting(false);
    }
  }
  async function disconnect(provider: Provider = selectedProvider) {
    try {
      await api(`/subscription/disconnect?provider=${provider}`, {
        method: "POST",
      });
      setLimits(null);
      setLogin(null);
      await loadSubscription();
    } catch (e) {
      fail(e);
    }
  }
  async function chooseProvider(provider: Provider) {
    setChoosingProvider(true);
    setError("");
    try {
      if (subscriptionRequest.current)
        await subscriptionRequest.current.catch(() => undefined);
      await api("/subscription/select", {
        method: "POST",
        body: JSON.stringify({ provider }),
      });
      setModel("");
      setModels([]);
      setLimits(null);
      await loadSubscription();
    } catch (e) {
      fail(e);
    } finally {
      setChoosingProvider(false);
    }
  }
  async function finishClaudeLogin(e: FormEvent) {
    e.preventDefault();
    if (!login || !loginCode.trim()) return;
    setConnecting(true);
    try {
      await api("/subscription/login/code", {
        method: "POST",
        body: JSON.stringify({
          login_id: login.loginId,
          code: loginCode.trim(),
        }),
      });
      setLoginCode("");
      await loadSubscription();
    } catch (e) {
      fail(e);
    } finally {
      setConnecting(false);
    }
  }
  function conversationRunning(id: string) {
    return (
      runs.current.has(id) ||
      conversations.some((c) => c.id === id && c.running) ||
      runningReports(reports, id).length > 0
    );
  }
  async function selectConversation(c: Conversation) {
    if (uploading) return;
    if (c.id === currentId) {
      setPage("chat");
      return;
    }
    if (openingConversation) return;

    setOpeningConversation(true);
    setError("");
    try {
      const result = await api<Conversation & { messages: Message[] }>(
        `/conversations/${c.id}`,
      );
      if (currentId && c.id !== currentId)
        drafts.current.set(currentId, {
          draft,
          attachments: pendingAttachments,
          model,
          reasoningEffort,
          retryMessageId,
        });
      const saved = drafts.current.get(c.id);
      setPendingAttachments(saved?.attachments || []);
      setCurrentId(c.id);
      activeId.current = c.id;
      setMessages(runs.current.snapshot(c.id) || result.messages);
      setDraft(saved?.draft || "");
      setReasoningEffort(saved?.reasoningEffort ?? cReasoning(result));
      setRetryMessageId(saved?.retryMessageId || null);
      if (saved?.model || result.model) {
        const candidate = saved?.model || result.model || "";
        setModel(
          models.some((m) => m.model === candidate)
            ? candidate
            : (models.find((m) => m.isDefault) || models[0])?.model || "",
        );
      }
      setPage("chat");
    } catch (e) {
      fail(e);
    } finally {
      setOpeningConversation(false);
    }
  }
  function newChat() {
    if (uploading || openingConversation) return;

    setError("");
    if (currentId)
      drafts.current.set(currentId, {
        draft,
        attachments: pendingAttachments,
        model,
        reasoningEffort,
        retryMessageId,
      });
    // An untouched chat is local UI state. Sending, uploading or requesting a
    // report creates its server conversation when there is something to keep.
    setCurrentId(null);
    activeId.current = null;
    setMessages([]);
    setRetryMessageId(null);
    setPendingAttachments([]);
    setDraft("");
    setPage("chat");
  }
  async function openReport(item: Report) {
    reportSelection.current = item.id;
    setError("");
    try {
      const next = await api<Report>(`/reports/${item.id}`);
      if (reportSelection.current === item.id) setReport(next);
    } catch (e) {
      fail(e);
    }
  }
  function closeReport() {
    reportSelection.current = null;
    setReport(null);
  }
  async function removeReport() {
    if (!deleteReport || deletingReport) return;
    setDeletingReport(true);
    try {
      await api(`/reports/${deleteReport.id}`, { method: "DELETE" });
      if (report?.id === deleteReport.id) closeReport();
      setReports((items) =>
        items.filter((item) => item.id !== deleteReport.id),
      );
      setDeleteReport(null);
      await loadReports();
    } catch (e) {
      fail(e);
    } finally {
      setDeletingReport(false);
    }
  }
  async function restoreReport(item: Report) {
    if (emptyingTrash || restoringReportId) return;
    setRestoringReportId(item.id);
    try {
      await api(`/reports/${item.id}/restore`, { method: "POST" });
      setDeletedReports((items) => items.filter((row) => row.id !== item.id));
      await loadReports();
    } catch (e) {
      fail(e);
    } finally {
      setRestoringReportId(null);
    }
  }
  async function emptyReportTrash() {
    if (emptyingTrash || restoringReportId || !deletedReports.length) return;
    setEmptyingTrash(true);
    setError("");
    try {
      await api("/reports/trash", { method: "DELETE" });
      setDeletedReports([]);
      setEmptyTrashConfirm(false);
      await loadReports();
    } catch (e) {
      fail(e);
    } finally {
      setEmptyingTrash(false);
    }
  }
  async function send(
    text: string,
    retryId = retryMessageId,
    retryFiles?: Attachment[],
  ) {
    if (
      (!text.trim() && !pendingAttachments.length) ||
      chatLocked ||
      openingConversation ||
      runs.current.has(currentId) ||
      reportBusyRef.current
    )
      return;
    text = text.trim() ? text : "Analizo skedarët e bashkëngjitur.";
    const outgoing = [...(retryFiles ?? pendingAttachments)];
    if (!subscription.connected) {
      setError(`Lidhni abonimin ${providerName} për të nisur bisedën.`);
      setPage("connection");
      return;
    }
    setError("");
    setDraft("");
    setPendingAttachments([]);
    let id = currentId,
      full = "";
    try {
      if (!id) {
        setOpeningConversation(true);
        const conversation = await api<Conversation>("/conversations", {
          method: "POST",
          body: JSON.stringify({
            model: model || null,
            reasoning_effort: effort || null,
          }),
        });
        id = conversation.id;
        setCurrentId(id);
        activeId.current = id;
        setOpeningConversation(false);
      }
      const streamId = id;
      setRetryMessageId(retryId);
      drafts.current.delete(id);
      const initialMessages: Message[] = [
        ...(retryId ? messagesBeforeRestart(messages, retryId) : messages),
        {
          id: retryId || `u-${Date.now()}`,
          role: "user",
          created_at: new Date().toISOString(),
          content: text,
          attachments: outgoing,
          status: "completed",
        },
        {
          id: "streaming",
          role: "assistant",
          created_at: new Date().toISOString(),
          content: "",
          status: "streaming",
        },
      ];
      runs.current.start(id, initialMessages);
      setMessages(initialMessages);
      refreshRuns((n) => n + 1);
      await streamChat(
        id,
        text,
        model,
        (event) => {
          if (event.type === "message" && retryId)
            void loadReports().catch(fail);
          if (event.type === "delta") full += event.text;
          if (event.type === "error") throw new Error(event.message);
          if (event.type === "done") {
            full = event.text || full;
          }
          const next = runs.current.update(
            streamId,
            full,
            event.type === "done" ? event.status : "streaming",
            event.type === "tool"
              ? "Duke kontrolluar të dhënat"
              : event.type === "delta"
                ? "Duke shkruar"
                : undefined,
          );
          if (activeId.current === streamId && next) setMessages(next);
          refreshRuns((n) => n + 1);
        },
        outgoing.map((a) => a.id),
        { reasoning_effort: effort || null, retry_message_id: retryId },
      );
      const [list, detail] = await Promise.all([
        api<Conversation[]>("/conversations"),
        api<Conversation & { messages: Message[] }>(`/conversations/${id}`),
      ]);
      setConversations(list);
      drafts.current.delete(id);
      if (activeId.current === id) {
        setMessages(detail.messages);
        setRetryMessageId(null);
      }
      setBusinessSources(await api<Source[]>("/sources"));
      await loadReports();
    } catch (e) {
      if (id) {
        runs.current.update(id, full, "failed");
        drafts.current.set(id, {
          draft: text,
          attachments: outgoing,
          model,
          reasoningEffort,
          retryMessageId: retryId,
        });
      }
      if (activeId.current === id) {
        fail(e);

        setDraft(text);
        setPendingAttachments(outgoing);
        const next = id ? runs.current.snapshot(id) : undefined;
        if (next) setMessages(next);
        if (id) {
          try {
            const detail = await api<Conversation & { messages: Message[] }>(
              `/conversations/${id}`,
            );
            if (activeId.current === id) setMessages(detail.messages);
          } catch {
            /* Preserve the visible attempt until reconnection. */
          }
        }
      }
    } finally {
      try {
        await loadReports();
      } catch (e) {
        if (activeId.current === id) fail(e);
      }
      if (id) runs.current.finish(id);
      refreshRuns((n) => n + 1);
      if (!id) setOpeningConversation(false);
    }
  }
  async function uploadFiles(files: FileList | null) {
    if (!files || chatLocked) return;
    const selected = Array.from(files);
    if (selected.length + pendingAttachments.length > 5) {
      setError("Bashkëngjitni deri në 5 skedarë për mesazh.");
      return;
    }
    if (selected.some((f) => f.size > 12 * 1024 * 1024)) {
      setError("Skedarët duhet të jenë më të vegjël se 12 MB.");
      return;
    }
    setUploading(true);
    setError("");
    try {
      let id = currentId;
      if (!id) {
        const chat = await api<Conversation>("/conversations", {
          method: "POST",
          body: JSON.stringify({
            model: model || null,
            reasoning_effort: effort || null,
          }),
        });
        id = chat.id;
        setCurrentId(id);
        activeId.current = id;
      }
      for (const file of selected) {
        const form = new FormData();
        form.append("file", file);
        const result = await api<Attachment>(
          `/conversations/${id}/attachments`,
          { method: "POST", body: form },
        );
        if (mounted.current && activeId.current === id)
          setPendingAttachments((items) => [...items, result]);
      }
    } catch (e) {
      fail(e);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  async function toggleAttachmentTemplate(item: Attachment) {
    try {
      const next = await api<Attachment>(`/attachments/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          purpose: item.purpose === "template" ? "analysis" : "template",
        }),
      });
      setPendingAttachments((items) =>
        items.map((a) => (a.id === next.id ? next : a)),
      );
      setMessages((items) =>
        items.map((m) => ({
          ...m,
          attachments: m.attachments?.map((a) => (a.id === next.id ? next : a)),
        })),
      );
    } catch (e) {
      fail(e);
    }
  }
  function attachmentChip(item: Attachment, pending = false) {
    return (
      <div
        key={item.id}
        className={`attachment-chip ${item.purpose === "template" ? "template" : ""}`}
      >
        <Paperclip size={16} />
        <div className="attachment-name">
          {pending ? (
            <strong>{item.name}</strong>
          ) : (
            <a href={`/api/attachments/${item.id}/download`}>{item.name}</a>
          )}
          <small>
            {item.kind.toUpperCase()} ·{" "}
            {Math.max(1, Math.round(item.size / 1024))} KB
          </small>
        </div>
        {item.kind === "xlsx" && Object.keys(item.format || {}).length > 0 && (
          <button
            type="button"
            className="attachment-template"
            aria-pressed={item.purpose === "template"}
            disabled={chatLocked}
            onClick={() => void toggleAttachmentTemplate(item)}
          >
            {item.purpose === "template"
              ? "Model paraqitjeje ✓"
              : "Përdor formatin"}
          </button>
        )}
        {pending && (
          <button
            type="button"
            className="icon-button"
            aria-label={`Hiq skedarin ${item.name}`}
            disabled={chatLocked}
            onClick={() =>
              setPendingAttachments((items) =>
                items.filter((a) => a.id !== item.id),
              )
            }
          >
            <X size={15} />
          </button>
        )}
      </div>
    );
  }
  async function stopResponse() {
    const targetId = currentId;
    setStoppingIds((ids) => ({ ...ids, [targetId || ""]: true }));
    try {
      if (targetId)
        await api(`/conversations/${targetId}/stop`, { method: "POST" });
      else
        for (const item of activeReports)
          await api(`/reports/${item.id}/stop`, { method: "POST" });
      await loadReports();
    } catch (e) {
      fail(e);
    } finally {
      setStoppingIds((ids) => {
        const next = { ...ids };
        delete next[targetId || ""];
        return next;
      });
    }
  }
  function navigate(next: Page) {
    closeReport();
    setPage(next);
    setError("");
    if (next === "reports") void loadReports().catch(fail);
    if (next === "conversations")
      void api<Conversation[]>("/conversations")
        .then(setConversations)
        .catch(fail);
  }

  async function createReport(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      const rows = String(data.rows).trim()
        ? JSON.parse(String(data.rows))
        : null;
      if (rows && !Array.isArray(rows))
        throw new Error(
          "Të dhënat manuale duhet të jenë një listë JSON me rreshta.",
        );
      const parameters = JSON.parse(
        String(data.parameters || "{}").trim() || "{}",
      );
      let conversationId = page === "chat" ? currentId : null;
      if (page === "chat" && !conversationId) {
        setOpeningConversation(true);
        const next = await api<Conversation>("/conversations", {
          method: "POST",
          body: JSON.stringify({
            model: model || null,
            reasoning_effort: effort || null,
          }),
        });
        conversationId = next.id;
        setCurrentId(next.id);
        activeId.current = next.id;
      }
      const result = await api<Report>("/reports", {
        method: "POST",
        body: JSON.stringify({
          title: data.title,
          template_id: data.template_id,
          instructions: data.instructions,
          dataset_id: data.dataset_id || null,
          rows,
          parameters,
          model: model || null,
          reasoning_effort: effort || null,
          conversation_id: conversationId,
        }),
      });
      setReportForm(false);
      setReportTrash(false);
      reportSelection.current = result.id;
      setReport(result);
      setPage("reports");
      await loadReports();
      setConversations(await api<Conversation[]>("/conversations"));
    } catch (e) {
      fail(e);
    } finally {
      setOpeningConversation(false);
    }
  }
  async function adminSubmit(
    e: FormEvent<HTMLFormElement>,
    kind: "users" | "sources" | "datasets",
  ) {
    e.preventDefault();
    if (kind === "sources" && savingSource) return;
    const data = Object.fromEntries(new FormData(e.currentTarget));
    if (kind === "sources") {
      data.kind = sourceKind;
      for (const key of Object.keys(data)) {
        if (
          (key.startsWith("SQLSERVER_") || key.startsWith("HANA_")) &&
          data[key] === ""
        )
          delete data[key];
      }
      if (sourceSupported && !environmentActive && autoDiscoverDatabases)
        data[sourcePrefix + "_DATABASE"] = "";
      setSavingSource(true);
    }
    try {
      await api(
        kind === "sources" && editSource
          ? `/admin/sources/${editSource.id}`
          : `/admin/${kind}`,
        {
          method: kind === "sources" && editSource ? "PATCH" : "POST",
          body: JSON.stringify(data),
        },
      );
      setAddUser(false);
      setAddSource(false);
      setAddDataset(false);
      await loadAdmin();
    } catch (e) {
      fail(e);
    } finally {
      if (kind === "sources") setSavingSource(false);
    }
  }
  async function openSourceAccess(source: Source) {
    try {
      const rows = await api<{ user_id: string }[]>(
        `/admin/sources/${source.id}/grants`,
      );
      setSourceGrants(rows.map((row) => row.user_id));
      setSourceAccess(source);
    } catch (e) {
      fail(e);
    }
  }
  async function changeSourceAccess(member: User) {
    if (!sourceAccess) return;
    const granted = sourceGrants.includes(member.id);
    try {
      await api(`/admin/sources/${sourceAccess.id}/grants/${member.id}`, {
        method: granted ? "DELETE" : "PUT",
      });
      setSourceGrants((ids) =>
        granted ? ids.filter((id) => id !== member.id) : [...ids, member.id],
      );
    } catch (e) {
      fail(e);
    }
  }
  function openSource(source: Source | null = null) {
    setError("");
    setEditSource(source);
    setSourceKind(source?.kind || "sqlserver");
    setOverrideEnvironment(false);
    setAutoDiscoverDatabases(
      !source?.connection_fields?.[
        source.kind === "saphana" ? "HANA_DATABASE" : "SQLSERVER_DATABASE"
      ],
    );
    setAddSource(true);
  }
  async function changeConnection(
    source: Source,
    action: "connect" | "disconnect" | "remove",
  ) {
    setError("");
    setSourceActions((current) => ({ ...current, [source.id]: true }));
    try {
      await api(
        `/admin/sources/${source.id}${action === "remove" ? "" : `/${action}`}`,
        {
          method: action === "remove" ? "DELETE" : "POST",
        },
      );
      if (action === "remove") setDeleteSource(null);
      await loadAdmin();
    } catch (e) {
      fail(e);
    } finally {
      setSourceActions((current) => ({ ...current, [source.id]: false }));
    }
  }
  async function browseDatabases(source: Source, offset = 0) {
    if (loadingDatabases) return;
    setError("");
    setDatabaseBrowser(source);
    if (offset === 0) {
      setServerDatabases([]);
      setDatabaseOffset(null);
    }
    setLoadingDatabases(true);
    try {
      const result = await api<{
        databases: { name: string; is_default: number }[];
        next_offset: number | null;
      }>(`/admin/sources/${source.id}/databases?offset=${offset}&limit=100`);
      setServerDatabases((previous) =>
        offset === 0 ? result.databases : [...previous, ...result.databases],
      );
      setDatabaseOffset(result.next_offset);
    } catch (e) {
      fail(e);
    } finally {
      setLoadingDatabases(false);
    }
  }
  async function removeConversation() {
    if (uploading) return;
    if (!deleteChat || conversationRunning(deleteChat.id) || deleting) return;
    setDeleting(true);
    try {
      await api(`/conversations/${deleteChat.id}`, { method: "DELETE" });
      if (currentId === deleteChat.id) {
        setCurrentId(null);
        activeId.current = null;
        setMessages([]);
        setRetryMessageId(null);
        setDraft("");
        setPage("conversations");
      }
      setConversations((items) => items.filter((c) => c.id !== deleteChat.id));
      setReports((items) =>
        items.map((r) =>
          r.conversation_id === deleteChat.id
            ? { ...r, conversation_id: null }
            : r,
        ),
      );
      drafts.current.delete(deleteChat.id);
      setDeleteChat(null);
    } catch (e) {
      fail(e);
    } finally {
      setDeleting(false);
    }
  }
  async function checkSource(source: Source) {
    setCheckingSource(source.id);
    try {
      await api(`/admin/sources/${source.id}/check`, { method: "POST" });
      await loadAdmin();
    } catch (e) {
      fail(e);
    } finally {
      setCheckingSource(null);
    }
  }
  async function toggleDataset(dataset: Dataset) {
    try {
      await api(`/admin/datasets/${dataset.id}`, {
        method: "PATCH",
        body: JSON.stringify({ active: !dataset.enabled }),
      });
      await loadAdmin();
      setDatasets(await api<Dataset[]>("/datasets"));
    } catch (e) {
      fail(e);
    }
  }
  async function updateUser(u: User) {
    try {
      await api(`/admin/users/${u.id}`, {
        method: "PATCH",
        body: JSON.stringify({ active: !u.active }),
      });
      await loadAdmin();
    } catch (e) {
      fail(e);
    }
  }

  const nav = [
    { id: "conversations" as Page, label: "Bisedat", icon: MessageSquare },
    { id: "reports" as Page, label: "Raportet", icon: FileText },
    { id: "sources" as Page, label: "Burimet e të dhënave", icon: Database },
  ];
  const current = conversations.find((c) => c.id === currentId);
  const caption = {
    conversations: "Bisedat",
    chat: current?.title || "Bisedë e re",
    reports: "Biblioteka e raporteve",
    sources: "Burimet e të dhënave",
    connection: "Modeli",
    admin: "Administrimi",
  }[page];
  const conversationReports = currentId
    ? reports.filter((r) => r.conversation_id === currentId)
    : [];
  const chatTimeline = buildChatTimeline(messages, conversationReports);
  const empty = messages.length === 0 && conversationReports.length === 0;
  const visibleConversations = conversations.filter((c) =>
    `${c.title} ${c.preview || ""}`
      .toLocaleLowerCase("sq")
      .includes(conversationSearch.toLocaleLowerCase("sq")),
  );
  const libraryReports = reportTrash ? deletedReports : reports;

  return (
    <div className="workspace">
      <aside className="sidebar">
        <button className="brand" onClick={() => navigate("conversations")}>
          <Brand light />
        </button>
        <button
          className="new-chat"
          onClick={newChat}
          disabled={uploading || openingConversation}
        >
          <Plus size={18} /> Bisedë e re <span>↗</span>
        </button>
        <span className="sidebar-label"> HAPËSIRA </span>
        <nav>
          {nav.map((n) => (
            <button
              key={n.id}
              className={
                page === n.id || (page === "chat" && n.id === "conversations")
                  ? "nav-item selected"
                  : "nav-item"
              }
              onClick={() => navigate(n.id)}
            >
              <n.icon size={19} />
              {n.label}
              {n.id === "reports" && (
                <span className="nav-count">{reports.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="recent">
          <span className="sidebar-label"> BISEDAT E FUNDIT </span>
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`recent-row ${currentId === c.id ? "active" : ""}`}
            >
              <button
                disabled={uploading || openingConversation}
                className={`recent-item ${currentId === c.id ? "active" : ""}`}
                onClick={() => void selectConversation(c)}
              >
                <>
                  {conversationRunning(c.id) ? (
                    <LoaderCircle
                      size={14}
                      className="spin"
                      aria-label="Duke përgatitur përgjigjen"
                    />
                  ) : (
                    <MessageSquare size={14} />
                  )}
                </>
                <span>{c.title}</span>
              </button>
              <button
                type="button"
                className="delete-conversation"
                disabled={conversationRunning(c.id) || uploading || deleting}
                aria-label={`Fshi bisedën: ${c.title}`}
                title="Fshi bisedën"
                onClick={() => {
                  setError("");
                  setDeleteChat(c);
                }}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          {!conversations.length && (
            <p className="sidebar-empty"> Bisedat tuaja do të shfaqen këtu. </p>
          )}
        </div>
        <div className="sidebar-bottom">
          <button
            className="connection-mini"
            onClick={() => navigate("connection")}
          >
            <span
              className={`status-dot ${subscription.connected ? "online" : ""}`}
            />
            <span>
              {" "}
              Modeli · {providerName}{" "}
              <small>
                {subscription.connected
                  ? `${subscription.account?.planType || "I lidhur"} · I lidhur`
                  : "Lidh llogarinë"}
              </small>
            </span>
            <ArrowRight size={15} />
          </button>
          {user.role === "devs" && (
            <button
              className={`nav-item ${page === "admin" ? "selected" : ""}`}
              onClick={() => navigate("admin")}
            >
              <Settings size={18} /> Administrimi{" "}
            </button>
          )}
          <button
            className="nav-item"
            title="Cilësimet"
            aria-label="Cilësimet"
            onClick={() => setSettingsOpen(true)}
          >
            <Settings size={18} /> Cilësimet
          </button>
          <div className="profile">
            <span className="avatar">
              {user.name.slice(0, 1).toUpperCase()}
            </span>
            <span>
              {user.name}
              <small>{label(user.role)}</small>
            </span>
            <button
              className="icon-button"
              aria-label="Dil nga llogaria"
              disabled={chatLocked}
              onClick={() => {
                void api("/auth/logout", { method: "POST" })
                  .then(onLogout)
                  .catch(fail);
              }}
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <span className="breadcrumb"> Hapësira </span>
            <span className="slash">/</span>
            <span>{caption}</span>
          </div>
          <div className="topbar-right">
            <button
              className="icon-button"
              aria-label="Historiku i bisedave"
              title="Historiku i bisedave"
              onClick={() => setChatHistory(true)}
            >
              <History size={19} />
            </button>
            <span className="workspace-tag">
              <span /> Duka Group{" "}
            </span>
            <button
              className="icon-button"
              aria-label="Ndihmë për lidhjen"
              onClick={() => navigate("connection")}
            >
              <CircleHelp size={19} />
            </button>
          </div>
        </header>
        {error && (
          <div className="global-error" role="alert">
            <span>{error}</span>
            <button
              className="icon-button"
              aria-label="Mbyll gabimin"
              onClick={() => setError("")}
            >
              <X size={17} />
            </button>
          </div>
        )}
        {page === "conversations" && (
          <main className="page-content conversation-library">
            <PageHeading
              eyebrow="HAPËSIRA JUAJ E BISEDAVE"
              title="Bisedat tuaja."
              text="Hapni një bisedë për të vazhduar aty ku e latë, ose nisni një të re."
              action={
                <button
                  className="button primary"
                  onClick={() => void newChat()}
                  disabled={uploading || openingConversation}
                >
                  <Plus size={17} />
                  Bisedë e re
                </button>
              }
            />
            {conversations.length > 0 && (
              <label className="library-search">
                <Search size={17} />
                <input
                  aria-label="Kërko biseda"
                  placeholder="Kërko në bisedat tuaja…"
                  value={conversationSearch}
                  onChange={(e) => setConversationSearch(e.target.value)}
                />
              </label>
            )}
            {visibleConversations.length ? (
              <div className="conversation-grid">
                {visibleConversations.map((c) => (
                  <article className="conversation-card" key={c.id}>
                    <button
                      className="conversation-card-main"
                      aria-label={`Hap bisedën: ${c.title}`}
                      disabled={uploading || openingConversation}
                      onClick={() => void selectConversation(c)}
                    >
                      <span className="report-icon">
                        <>
                          {conversationRunning(c.id) ? (
                            <LoaderCircle
                              size={23}
                              className="spin"
                              aria-label="Duke përgatitur përgjigjen"
                            />
                          ) : (
                            <MessageSquare size={23} />
                          )}
                        </>
                      </span>
                      <h3>{c.title}</h3>
                      <p>
                        {c.preview ||
                          "Shkruani mesazhin tuaj të parë për të nisur bisedën."}
                      </p>
                      <span className="conversation-card-meta">
                        <span>{c.message_count || 0} mesazhe</span>
                        <span>{date(c.updated_at)}</span>
                        <ArrowRight size={17} />
                      </span>
                    </button>
                    <button
                      className="icon-button conversation-card-delete"
                      title="Fshi bisedën"
                      aria-label={`Fshi bisedën: ${c.title}`}
                      disabled={
                        conversationRunning(c.id) || uploading || deleting
                      }
                      onClick={() => {
                        setError("");
                        setDeleteChat(c);
                      }}
                    >
                      <Trash2 size={16} />
                    </button>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<MessageSquare size={30} />}
                title={
                  conversationSearch
                    ? "Nuk u gjet asnjë bisedë."
                    : "Biseda juaj e parë fillon këtu."
                }
                text={
                  conversationSearch
                    ? "Provoni një fjalë tjetër për kërkimin."
                    : "Shtypni “Bisedë e re” për të biseduar me asistentin dhe për të krijuar raporte."
                }
              />
            )}
          </main>
        )}
        {page === "chat" && (
          <div className="chat-layout">
            <main className="chat-main">
              <div className="chat-toolbar">
                <div className="chat-toolbar-title">
                  <button
                    className="icon-button"
                    aria-label="Kthehu te bisedat"
                    onClick={() => navigate("conversations")}
                  >
                    <ArrowLeft size={18} />
                  </button>
                  <span>{current?.title || "Bisedë e re"}</span>
                </div>
                <div>
                  <Badge good={subscription.connected}>
                    {subscription.connected
                      ? "Abonimi është lidhur"
                      : "Llogaria nuk është lidhur"}
                  </Badge>
                  <button
                    className="button subtle small"
                    onClick={() => setReportForm(true)}
                    disabled={chatLocked}
                  >
                    <FileText size={15} /> Krijo raport{" "}
                  </button>
                </div>
              </div>
              <div
                ref={messageScroll}
                className={`message-scroll ${empty ? "empty-scroll" : ""}`}
              >
                {empty ? (
                  <section className="chat-welcome">
                    <div className="welcome-symbol">
                      <Sparkles size={27} />
                    </div>
                    <span className="eyebrow"> BIZNESI JUAJ NË BISEDË </span>
                    <h1>
                      {" "}
                      Një pyetje për <br /> një pamje më të qartë.{" "}
                    </h1>
                    <p>
                      {" "}
                      Diskutoni një ide, analizoni shifrat ose ktheni{" "}
                      <br className="desktop-break" /> një pyetje në raport.
                      Filloni këtu.{" "}
                    </p>
                    <div className="suggestions">
                      {[
                        {
                          icon: MessageSquare,
                          title: "Nis një bisedë",
                          text: "Më ndihmo me një pyetje biznesi.",
                          prompt:
                            "Përshëndetje! Më ndihmo të analizoj një pyetje biznesi.",
                        },
                        {
                          icon: FileText,
                          title: "Përgatit një raport",
                          text: "Planifikojmë së bashku një raport drejtues.",
                          prompt:
                            "Më ndihmo të planifikoj një raport drejtues. Çfarë të dhënash duhen?",
                        },
                        {
                          icon: Database,
                          title: "Eksploro të dhënat",
                          text: "Çfarë mund të mësojmë nga të dhënat tona?",
                          prompt:
                            "Zbulo tabelat e databazës dhe më sugjero raporte të dobishme që mund të krijojmë.",
                        },
                      ].map((s) => (
                        <button
                          key={s.title}
                          onClick={() => setDraft(s.prompt)}
                        >
                          <s.icon size={20} />
                          <strong>{s.title}</strong>
                          <span>{s.text}</span>
                          <ArrowRight size={16} />
                        </button>
                      ))}
                    </div>
                    <div className="welcome-note">
                      <ShieldCheck size={15} /> Mundësuar nga abonimi juaj
                      {providerName}.{" "}
                    </div>
                  </section>
                ) : (
                  <div className="messages">
                    {chatTimeline.map((entry) => {
                      if (entry.kind === "message") {
                        const m = entry.message;
                        return (
                          <article
                            key={entry.key}
                            className={`message ${m.role}`}
                          >
                            <div className={`message-avatar ${m.role}`}>
                              {m.role === "assistant" ? (
                                <Sparkles size={18} />
                              ) : (
                                user.name.slice(0, 1)
                              )}
                            </div>
                            <div className="message-body">
                              <div className="message-author">
                                {m.role === "assistant"
                                  ? "Asistenti Duka"
                                  : user.name}
                                <span>
                                  {m.role === "assistant" ? "AI" : "Ju"}
                                </span>
                              </div>
                              {!!m.attachments?.length && (
                                <div className="message-attachments">
                                  {m.attachments.map((a) => attachmentChip(a))}
                                </div>
                              )}
                              {pendingMessages.has(m.id) && (
                                <ThinkingDots
                                  description={pendingDescription}
                                />
                              )}
                              {m.content && (
                                <MarkdownContent>{m.content}</MarkdownContent>
                              )}
                              {m.role === "user" && !chatLocked && (
                                <div className="message-actions">
                                  <button
                                    type="button"
                                    className="icon-button"
                                    aria-label="Ndrysho mesazhin"
                                    title="Ndrysho mesazhin dhe rinis bisedën"
                                    onClick={() => {
                                      setRetryMessageId(m.id);
                                      setDraft(m.content);
                                      setPendingAttachments(
                                        m.attachments || [],
                                      );
                                    }}
                                  >
                                    <Pencil size={16} aria-hidden="true" />
                                  </button>
                                  <button
                                    type="button"
                                    className="icon-button"
                                    aria-label="Ridërgo"
                                    title="Ridërgo dhe rinis bisedën nga ky mesazh"
                                    onClick={() =>
                                      void send(
                                        m.content,
                                        m.id,
                                        m.attachments || [],
                                      )
                                    }
                                  >
                                    <RotateCcw size={16} aria-hidden="true" />
                                  </button>
                                </div>
                              )}
                              {m.status === "failed" && (
                                <span className="message-warning">
                                  {" "}
                                  Përgjigjja nuk përfundoi.{" "}
                                </span>
                              )}
                              {m.status === "interrupted" && (
                                <span className="message-warning">
                                  {" "}
                                  Përgjigjja u ndërpre.{" "}
                                </span>
                              )}
                            </div>
                          </article>
                        );
                      }
                      const r = entry.report;
                      return (
                        <div
                          className="chat-report"
                          key={entry.key}
                          aria-live="polite"
                        >
                          <div className="chat-report-heading">
                            <FileText size={20} />
                            <strong>{r.title}</strong>
                            <Badge good={r.status === "completed"}>
                              {label(
                                r.stage === "interrupted"
                                  ? "interrupted"
                                  : r.status,
                              )}
                            </Badge>
                          </div>
                          {["queued", "running"].includes(r.status) && (
                            <p>{label(r.stage || "gathering")}</p>
                          )}
                          {r.error && (
                            <p className="message-warning">
                              {errorMessage(r.error)}
                            </p>
                          )}
                          {r.status === "completed" && (
                            <a
                              className="button primary small"
                              href={`/api/reports/${r.id}/export/xlsx`}
                            >
                              <ArrowDownToLine size={16} />
                              Shkarko Excel
                            </a>
                          )}
                        </div>
                      );
                    })}
                    {reportBusy && pendingMessages.size === 0 && (
                      <article className="message assistant">
                        <div className="message-avatar assistant">
                          <Sparkles size={18} />
                        </div>
                        <div className="message-body">
                          <div className="message-author">
                            Asistenti Duka <span>{providerName}</span>
                          </div>
                          <ThinkingDots description={pendingDescription} />
                        </div>
                      </article>
                    )}
                  </div>
                )}
              </div>
              <div className="composer-wrap">
                {!subscription.connected && (
                  <div className="connect-prompt">
                    <span>
                      <Sparkles size={15} /> Lidhni abonimin {providerName} për
                      të biseduar.{" "}
                    </span>
                    <button
                      onClick={() => void connect()}
                      disabled={connecting}
                    >
                      {connecting ? "Duke u lidhur…" : "Lidh llogarinë"}
                      <ArrowRight size={14} />
                    </button>
                  </div>
                )}
                {retryMessageId && (
                  <div className="retry-banner" role="status">
                    Biseda do të rinisë nga ky mesazh. Mesazhet pas tij do të
                    zëvendësohen.
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => {
                        setRetryMessageId(null);
                        setDraft("");
                        setPendingAttachments([]);
                      }}
                    >
                      Anulo ndryshimin
                    </button>
                  </div>
                )}
                <form
                  className="composer"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void send(draft);
                  }}
                >
                  <input
                    ref={fileInput}
                    type="file"
                    hidden
                    multiple
                    accept=".xlsx,.csv,.pdf,.docx,.txt"
                    aria-label="Zgjidh skedarët për analizë"
                    disabled={chatLocked}
                    onChange={(e) => void uploadFiles(e.target.files)}
                  />
                  {!!pendingAttachments.length && (
                    <div className="pending-attachments">
                      {pendingAttachments.map((a) => attachmentChip(a, true))}
                    </div>
                  )}
                  {uploading && (
                    <p className="upload-status" role="status">
                      <LoaderCircle size={16} className="spin" />
                      Duke lexuar skedarin…
                    </p>
                  )}
                  <textarea
                    aria-label="Mesazhi"
                    placeholder="Bëni një pyetje ose kërkoni analizë dhe raport nga databaza…"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    disabled={chatLocked}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void send(draft);
                      }
                    }}
                  />
                  <div className="composer-controls">
                    <div className="composer-left">
                      <span className="model-picker">
                        <Sparkles size={14} />
                        <Select
                          aria-label={`Modeli ${providerName}`}
                          value={model}
                          onChange={(e) => setModel(e.target.value)}
                          disabled={!subscription.connected || chatLocked}
                        >
                          {!models.length && (
                            <option value=""> Abonimi {providerName} </option>
                          )}
                          {models.map((m) => (
                            <option key={m.id} value={m.model}>
                              {m.displayName}
                            </option>
                          ))}
                        </Select>
                      </span>
                      {reasoningControl}
                      <span className="composer-divider" />
                      <button
                        type="button"
                        className="button outline small upload-button"
                        aria-label="Ngarko skedar"
                        title="Ngarko Excel, CSV, PDF, Word ose tekst (deri në 12 MB)"
                        disabled={chatLocked || pendingAttachments.length >= 5}
                        onClick={() => fileInput.current?.click()}
                      >
                        <Paperclip size={18} />
                        {uploading ? "Duke ngarkuar…" : "Ngarko skedar"}
                      </button>
                    </div>
                    {busy || reportBusy ? (
                      <button
                        type="button"
                        className="send-button stop"
                        aria-label={
                          reportBusy ? "Ndërprit raportin" : "Ndalo përgjigjen"
                        }
                        disabled={stoppingReports || (!busy && !reportBusy)}
                        onClick={() => void stopResponse()}
                      >
                        <Square size={16} />
                      </button>
                    ) : (
                      <button
                        type="submit"
                        className="send-button"
                        aria-label="Dërgo mesazhin"
                        disabled={
                          chatLocked ||
                          (!draft.trim() && !pendingAttachments.length)
                        }
                      >
                        <ArrowRight size={21} />
                      </button>
                    )}
                  </div>
                </form>
                <div className="composer-footer">
                  <span>
                    {" "}
                    Verifikoni shifrat e rëndësishme me të dhënat burimore.{" "}
                  </span>
                </div>
              </div>
            </main>
          </div>
        )}

        {page === "connection" && (
          <main className="page-content">
            <PageHeading
              eyebrow="LLOGARIA DHE ABONIMI JUAJ"
              title="Modeli"
              text="Lidhni ChatGPT dhe Claude, pastaj zgjidhni cilin abonim të përdorni për biseda, analiza dhe raporte."
            />
            {(["chatgpt", "claude"] as Provider[]).map((provider) => {
              const status = providerSubscriptions[provider];
              const name = provider === "claude" ? "Claude" : "ChatGPT";
              const selected = selectedProvider === provider;
              return (
                <section
                  key={provider}
                  className={`connection-card ${selected ? "selected-provider" : ""}`}
                  aria-label={`Abonimi ${name}`}
                >
                  <div className="provider-logo">
                    <Sparkles size={28} />
                  </div>
                  <div className="provider-details">
                    <h2> Abonimi {name} </h2>
                    <p>
                      {status.connected
                        ? status.account?.email || `Llogaria juaj ${name}`
                        : `Hyni në llogarinë tuaj ${name} për të lidhur abonimin.`}
                    </p>
                    <Badge good={status.connected}>
                      {status.connected
                        ? `${status.account?.planType || "Abonimi"} · I lidhur`
                        : "I palidhur"}
                    </Badge>
                  </div>
                  <div className="provider-actions">
                    <button
                      className={`button ${status.connected ? "outline" : "primary"}`}
                      onClick={() =>
                        void (status.connected
                          ? disconnect(provider)
                          : connect(provider))
                      }
                      disabled={
                        connecting || choosingProvider || busy || reportBusy
                      }
                    >
                      {connecting && (
                        <LoaderCircle className="spin" size={17} />
                      )}{" "}
                      {status.connected ? `Shkëput ${name}` : `Lidh ${name}`}
                    </button>
                    <button
                      className={`button ${selected ? "provider-chosen" : "outline"}`}
                      aria-pressed={selected}
                      onClick={() => void chooseProvider(provider)}
                      disabled={
                        selected ||
                        choosingProvider ||
                        connecting ||
                        busy ||
                        reportBusy
                      }
                    >
                      {selected ? "Në përdorim" : `Përdor ${name}`}
                    </button>
                  </div>
                </section>
              );
            })}
            <section className="panel provider-model-panel">
              <label>
                Modeli për biseda dhe raporte
                <select
                  aria-label="Zgjidh modelin"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  disabled={
                    !subscription.connected || choosingProvider || chatLocked
                  }
                >
                  {!models.length && (
                    <option value="">Lidhni abonimin {providerName}</option>
                  )}
                  {models.map((m) => (
                    <option key={m.id} value={m.model}>
                      {m.displayName}
                    </option>
                  ))}
                </select>
              </label>
              <p>
                Zgjedhja përdoret për mesazhet dhe raportet e ardhshme. Të dyja
                llogaritë mund të qëndrojnë të lidhura.
              </p>
            </section>
            {!subscription.available && (
              <p className="error-box">
                {errorMessage(subscription.error || "")} Lidhja do të provohet
                përsëri automatikisht sapo rrjeti të jetë gati.
              </p>
            )}
            <section className="panel">{reasoningControl}</section>
            <div className="info-grid">
              <div className="info-card">
                <ShieldCheck size={21} />
                <h3> Biseda përdor abonimin tuaj </h3>
                <p>
                  {" "}
                  Përdoret abonimi që keni zgjedhur dhe kufijtë e llogarisë
                  përkatëse. Mund të ndërroni ofruesin duke ruajtur bisedat dhe
                  raportet tuaja.{" "}
                </p>
              </div>
              <div className="info-card">
                <MessageSquare size={21} />
                <h3> Hapësirë e veçantë bisedash </h3>
                <p>
                  {" "}
                  Kjo hapësirë ruan bisedat e veta. Lidhja e llogarisë nuk
                  importon bisedat ose kujtesën nga ChatGPT ose Claude.{" "}
                </p>
              </div>
            </div>
            {subscription.connected && selectedProvider === "chatgpt" && (
              <section className="panel">
                <div className="panel-heading">
                  <h3> Përdorimi i abonimit </h3>
                  <button
                    className="button outline small"
                    onClick={() =>
                      void api<{ rateLimits: RateLimits }>(
                        "/subscription/usage",
                      )
                        .then((r) => setLimits(r.rateLimits))
                        .catch(fail)
                    }
                  >
                    {" "}
                    Rifresko përdorimin{" "}
                  </button>
                </div>
                {limits ? (
                  <div className="usage-grid">
                    {[limits.primary, limits.secondary]
                      .filter(Boolean)
                      .map((w, i) => (
                        <div key={i}>
                          <span>
                            {w!.windowDurationMins >= 1440
                              ? "Periudha më e gjatë"
                              : "Periudha aktuale"}
                          </span>
                          <strong>
                            {Math.max(0, 100 - w!.usedPercent)} % të
                            mbetura{" "}
                          </strong>
                          <progress
                            value={Math.max(0, 100 - w!.usedPercent)}
                            max={100}
                          />
                          <small>
                            {" "}
                            Rinovohet{" "}
                            {new Date(w!.resetsAt * 1000).toLocaleString(
                              "sq-AL",
                            )}
                          </small>
                        </div>
                      ))}
                  </div>
                ) : (
                  <p> Rifreskoni për të parë kufijtë e llogarisë ChatGPT. </p>
                )}
              </section>
            )}
            {subscription.connected && selectedProvider === "claude" && (
              <p className="footnote">
                Përdorimin dhe kufijtë e abonimit mund t’i kontrolloni te{" "}
                <a
                  href="https://claude.ai/settings/usage"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  llogaria Claude
                </a>
                .
              </p>
            )}
            <p className="footnote">
              {selectedProvider === "chatgpt"
                ? "Hyrja me kod pajisjeje duhet të aktivizohet në cilësimet e sigurisë të ChatGPT ose të lejohet nga administratori."
                : "Për Claude, hyni në shfletues me abonimin tuaj dhe vendosni këtu kodin njëpërdorimësh që shfaqet pas hyrjes."}
            </p>
          </main>
        )}

        {page === "reports" && (
          <main className="page-content">
            <PageHeading
              eyebrow="NGA TË DHËNAT TE VENDIMET"
              title="Biblioteka juaj e raporteve."
              text="Një pasqyrë e qartë e rezultateve, gjetjeve dhe hapave të ardhshëm."
              action={
                <button
                  className="button primary"
                  onClick={() => setReportForm(true)}
                >
                  <Plus size={17} /> Krijo raport{" "}
                </button>
              }
            />
            <div className="library-tabs" aria-label="Pamjet e raporteve">
              <button
                className={!reportTrash ? "active" : ""}
                aria-pressed={!reportTrash}
                onClick={() => setReportTrash(false)}
              >
                <FileText size={16} />
                Raportet ({reports.length})
              </button>
              <button
                className={reportTrash ? "active" : ""}
                aria-pressed={reportTrash}
                onClick={() => {
                  setReportTrash(true);
                  void api<Report[]>("/reports?deleted=true")
                    .then(setDeletedReports)
                    .catch(fail);
                }}
              >
                <Trash2 size={16} />
                Të fshira
              </button>
            </div>
            {reportTrash && (
              <div className="trash-toolbar">
                <span>{deletedReports.length} raporte të fshira</span>
                <button
                  className="button danger small"
                  disabled={
                    !deletedReports.length ||
                    emptyingTrash ||
                    !!restoringReportId
                  }
                  onClick={() => {
                    setError("");
                    setEmptyTrashConfirm(true);
                  }}
                >
                  <Trash2 size={16} /> Zbraz koshin
                </button>
              </div>
            )}
            {libraryReports.length ? (
              <div className="report-grid">
                {libraryReports.map((r) => (
                  <article className="report-card" key={r.id}>
                    <div className="report-card-top">
                      <span className="report-icon">
                        <FileText size={23} />
                      </span>
                      <Badge good={!reportTrash && r.status === "completed"}>
                        {reportTrash
                          ? "I fshirë"
                          : label(
                              r.stage === "interrupted"
                                ? "interrupted"
                                : r.status,
                            )}
                      </Badge>
                    </div>
                    {reportTrash ? (
                      <h3>{r.title}</h3>
                    ) : (
                      <button
                        className="report-card-open"
                        aria-label={`Hap raportin: ${r.title}`}
                        onClick={() => void openReport(r)}
                      >
                        <h3>{r.title}</h3>
                        <ArrowRight size={17} />
                      </button>
                    )}
                    <p>
                      {label(
                        templates.find((t) => t.id === r.template_id)?.name ||
                          "",
                      ) || "Raport biznesi"}
                    </p>
                    <div className="report-card-footer">
                      <span>{date(r.deleted_at || r.created_at)}</span>
                    </div>
                    <div className="report-card-actions">
                      {reportTrash ? (
                        <button
                          className="button outline small"
                          disabled={emptyingTrash || !!restoringReportId}
                          onClick={() => void restoreReport(r)}
                        >
                          <RotateCcw size={15} />
                          {restoringReportId === r.id
                            ? "Duke rikthyer…"
                            : "Rikthe raportin"}
                        </button>
                      ) : (
                        <>
                          <button
                            className="button outline small"
                            onClick={() => void openReport(r)}
                          >
                            Hap raportin
                          </button>
                          {r.status === "completed" && (
                            <a
                              className="button primary small"
                              aria-label={`Shkarko Excel: ${r.title}`}
                              href={`/api/reports/${r.id}/export/xlsx`}
                            >
                              <ArrowDownToLine size={15} />
                              Excel
                            </a>
                          )}
                          <button
                            className="icon-button report-card-delete"
                            aria-label={`Fshi raportin: ${r.title}`}
                            title={
                              ["queued", "running"].includes(r.status)
                                ? "Ndërpriteni raportin para fshirjes"
                                : "Fshi raportin"
                            }
                            disabled={["queued", "running"].includes(r.status)}
                            onClick={() => {
                              setError("");
                              setDeleteReport(r);
                            }}
                          >
                            <Trash2 size={16} />
                          </button>
                        </>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<FileText size={30} />}
                title={
                  reportTrash
                    ? "Nuk ka raporte të fshira."
                    : "Raporti juaj i parë fillon këtu."
                }
                text={
                  reportTrash
                    ? "Raportet e fshira mund t’i riktheni nga kjo pamje."
                    : "Kërkoni raport direkt në bisedë ose përdorni një model raporti. Raportet e përfunduara ruhen këtu."
                }
              />
            )}
          </main>
        )}

        {page === "sources" && (
          <main className="page-content">
            <PageHeading
              eyebrow="BAZA E RAPORTEVE TUAJA"
              title="Burimet e të dhënave tuaja."
              text="Menaxhoni lidhje SQL Server dhe SAP HANA. Çdo server mund të ketë shumë databaza."
              action={
                user.role === "devs" && (
                  <button
                    className="button primary"
                    onClick={() => openSource()}
                  >
                    <Plus size={17} /> Shto lidhje{" "}
                  </button>
                )
              }
            />
            <div className="notice">
              <Database size={20} />
              <div>
                <strong>
                  {" "}
                  Raporte nga SQL Server dhe SAP HANA me kredenciale
                  private.{" "}
                </strong>
                <p>
                  {" "}
                  Shtoni hostin, portin, përdoruesin dhe fjalëkalimin për çdo
                  lidhje. Emri i databazës është opsional: asistenti zbulon
                  databazat dhe tabelat që lejon secili përdorues SQL.
                  Kredencialet mbeten private në backend.{" "}
                </p>
              </div>
            </div>
            {user.role === "devs" ? (
              <>
                {sources.length ? (
                  <div className="source-grid">
                    {sources.map((s) => (
                      <div className="source-card" key={s.id}>
                        <Database size={25} />
                        <Badge good={s.status === "connected"}>
                          {label(s.status)}
                        </Badge>
                        <h3>{s.name}</h3>
                        <span className="source-type">{s.kind}</span>
                        {(s.kind === "sqlserver" || s.kind === "saphana") && (
                          <p className="source-scope">
                            {s.database_scope === "all"
                              ? "Zbulim automatik i databazave në server"
                              : "Databazë parazgjedhje dhe zbulim në server"}
                          </p>
                        )}
                        <p>
                          {s.description ||
                            (s.configuration_origin === "saved"
                              ? "Përdor cilësimet private të ruajtura të lidhjes."
                              : "Përdor konfigurimin nga .env në server; vlerat mbeten private.")}
                        </p>
                        {s.last_error && (
                          <p className="database-error" role="status">
                            {s.error_scope === "query" && "Gabim në pyetje: "}
                            {errorMessage(s.last_error || "")}
                          </p>
                        )}
                        {s.checked_at && (
                          <small>
                            {" "}
                            Kontrolluar më{" "}
                            {new Date(s.checked_at).toLocaleString("sq-AL")}
                          </small>
                        )}
                        {(s.kind === "sqlserver" || s.kind === "saphana") && (
                          <button
                            className="button outline small"
                            onClick={() => openSource(s)}
                          >
                            <Settings size={15} /> Konfiguro lidhjen{" "}
                          </button>
                        )}
                        {(s.kind === "sqlserver" || s.kind === "saphana") && (
                          <button
                            className="button outline small"
                            onClick={() => void openSourceAccess(s)}
                          >
                            <ShieldCheck size={15} /> Qasja te burimi{" "}
                          </button>
                        )}
                        {(s.kind === "sqlserver" || s.kind === "saphana") &&
                          s.enabled !== 0 && (
                            <button
                              className="button outline small"
                              disabled={
                                checkingSource === s.id || sourceActions[s.id]
                              }
                              onClick={() => void checkSource(s)}
                            >
                              {checkingSource === s.id ? (
                                <LoaderCircle size={15} className="spin" />
                              ) : (
                                <Check size={15} />
                              )}{" "}
                              Kontrollo lidhjen{" "}
                            </button>
                          )}
                        <div className="source-actions">
                          {(s.kind === "sqlserver" || s.kind === "saphana") &&
                            s.enabled !== 0 && (
                              <button
                                className="button outline small"
                                disabled={sourceActions[s.id]}
                                onClick={() => void browseDatabases(s)}
                              >
                                <Database size={15} /> Shiko databazat
                              </button>
                            )}
                          {(s.kind === "sqlserver" || s.kind === "saphana") && (
                            <button
                              className="button outline small"
                              disabled={
                                sourceActions[s.id] || checkingSource === s.id
                              }
                              onClick={() =>
                                void changeConnection(
                                  s,
                                  s.enabled === 0 ? "connect" : "disconnect",
                                )
                              }
                            >
                              {sourceActions[s.id] ? (
                                <LoaderCircle size={15} className="spin" />
                              ) : (
                                <Unplug size={15} />
                              )}
                              {s.enabled === 0 ? "Rilidh" : "Shkëput"}
                            </button>
                          )}
                          <button
                            className="button outline small danger-text"
                            disabled={sourceActions[s.id]}
                            onClick={() => {
                              setError("");
                              setDeleteSource(s);
                            }}
                          >
                            <Trash2 size={15} /> Hiq lidhjen
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    icon={<Database size={30} />}
                    title="Nuk ka ende burime të dhënash."
                    text="Shtoni një databazë për të nisur analizat dhe raportet."
                  />
                )}
                <section className="panel">
                  <div className="panel-heading">
                    <h3> Dataset-e opsionale për raporte </h3>
                    <button
                      className="button outline small"
                      disabled={!sources.length}
                      onClick={() => setAddDataset(true)}
                    >
                      <Plus size={15} /> Përcakto dataset{" "}
                    </button>
                  </div>
                  <DatasetTable
                    datasets={adminDatasets}
                    onGrant={setGrant}
                    onToggle={(d) => void toggleDataset(d)}
                  />
                </section>
              </>
            ) : (
              <section className="panel">
                <h3> Databazat ku keni qasje </h3>
                {businessSources.map((source) => (
                  <div className="service-row" key={source.id}>
                    <strong>{source.name}</strong>
                    <Badge good={source.status === "connected"}>
                      {label(source.status)}
                    </Badge>
                  </div>
                ))}
                {!businessSources.length && (
                  <p className="muted">
                    {" "}
                    Kërkojini administratorit t’ju japë qasje në databazë.{" "}
                  </p>
                )}
                <h3> Dataset-et ku keni qasje </h3>
                <DatasetTable datasets={datasets} />
              </section>
            )}
          </main>
        )}

        {page === "admin" && user.role === "devs" && (
          <main className="page-content">
            <PageHeading
              eyebrow="ADMINISTRIMI I HAPËSIRËS"
              title="Kontrollet e hapësirës tuaj."
              text="Menaxhoni anëtarët, kontrolloni shërbimet dhe ndiqni aktivitetin."
            />
            <div className="tabs">
              {["overview", "users", "traffic", "activity"].map((t) => (
                <button
                  className={adminTab === t ? "active" : ""}
                  key={t}
                  onClick={() => setAdminTab(t)}
                >
                  {t === "overview"
                    ? "Përmbledhje"
                    : t === "users"
                      ? "Anëtarët dhe qasja"
                      : t === "traffic"
                        ? "Trafiku"
                        : "Regjistri i aktivitetit"}
                </button>
              ))}
            </div>
            {adminTab === "overview" && overview && (
              <>
                <div className="stats-grid">
                  {[
                    {
                      label: "Anëtarët e hapësirës",
                      count: overview.counts.users,
                      icon: ShieldCheck,
                    },
                    {
                      label: "Bisedat",
                      count: overview.counts.conversations,
                      icon: MessageSquare,
                    },
                    {
                      label: "Raporte të krijuara",
                      count: overview.counts.reports,
                      icon: FileText,
                    },
                    {
                      label: "Burimet e të dhënave",
                      count: overview.counts.data_sources,
                      icon: Database,
                    },
                  ].map((s) => (
                    <div className="stat-card" key={s.label}>
                      <s.icon size={20} />
                      <span>{s.label}</span>
                      <strong>{s.count}</strong>
                    </div>
                  ))}
                </div>
                <section className="panel">
                  <h3> Gjendja e shërbimeve </h3>
                  <div className="service-row">
                    <span>
                      <Sparkles size={19} /> Lidhjet me modelet AI{" "}
                    </span>
                    <Badge good>ChatGPT · Claude</Badge>
                  </div>
                  <div className="service-row">
                    <span>
                      <Database size={19} /> Lidhjet me databazat e
                      biznesit{" "}
                    </span>
                    <Badge
                      good={overview.database_sources.some(
                        (s) => s.status === "connected",
                      )}
                    >
                      {overview.database_sources.some(
                        (s) => s.status === "connected",
                      )
                        ? "I lidhur"
                        : overview.database_sources.some(
                              (s) => s.status === "error",
                            )
                          ? "Gabim në lidhje"
                          : "Në pritje të konfigurimit"}
                    </Badge>
                  </div>
                  <div className="service-row">
                    <span>
                      <LayoutDashboard size={19} /> Lidhje aktive me
                      abonimin{" "}
                    </span>
                    <strong>
                      {overview.active_runtimes} / {overview.max_runtimes}
                    </strong>
                  </div>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <h3> Konfigurimi i databazave </h3>
                    <button
                      className="button outline small"
                      onClick={() => void loadAdmin().catch(fail)}
                    >
                      {" "}
                      Rifresko gjendjen{" "}
                    </button>
                  </div>
                  <p className="muted">
                    {" "}
                    Lidhjet SQL Server dhe SAP HANA ruhen në .env të projektit.
                    Çdo lidhje ka profilin e vet dhe përdor drejtuesin përkatës.
                    Vlerat e kredencialeve nuk shfaqen në shfletues.{" "}
                  </p>
                  {Object.entries(
                    overview.database_configuration.environment,
                  ).map(([key, configured]) => (
                    <div className="service-row" key={key}>
                      <code>{key}</code>
                      <Badge good={configured}>
                        {configured ? "Vendosur" : "Mungon"}
                      </Badge>
                    </div>
                  ))}
                  {overview.database_sources.map((source) => (
                    <div className="database-status" key={source.id}>
                      <div className="service-row">
                        <strong>{source.name}</strong>
                        <Badge good={source.status === "connected"}>
                          {label(source.status)}
                        </Badge>
                      </div>
                      {source.last_error && (
                        <p className="database-error" role="status">
                          {source.error_scope === "query" &&
                            "Gabim në pyetje: "}
                          {errorMessage(source.last_error || "")}
                        </p>
                      )}
                      {source.checked_at && (
                        <small>
                          {" "}
                          Kontrolluar më{" "}
                          {new Date(source.checked_at).toLocaleString("sq-AL")}
                        </small>
                      )}
                      {(source.kind === "sqlserver" ||
                        source.kind === "saphana") && (
                        <button
                          className="button outline small"
                          onClick={() => openSource(source)}
                        >
                          <Settings size={15} /> Konfiguro lidhjen{" "}
                        </button>
                      )}
                      {(source.kind === "sqlserver" ||
                        source.kind === "saphana") && (
                        <button
                          className="button outline small"
                          disabled={checkingSource === source.id}
                          onClick={() => void checkSource(source)}
                        >
                          {checkingSource === source.id
                            ? "Duke kontrolluar…"
                            : "Kontrollo lidhjen"}
                        </button>
                      )}
                    </div>
                  ))}
                  {!overview.database_sources.length && (
                    <p className="muted">
                      {" "}
                      Shtoni një lidhje SQL Server ose SAP HANA për të
                      kontrolluar lidhjen.{" "}
                    </p>
                  )}
                </section>
                <p className="footnote">
                  {" "}
                  Çdo anëtar lidh abonimet e veta ChatGPT ose Claude.
                  Administratori nuk sheh kredencialet e anëtarëve të
                  tjerë.{" "}
                </p>
              </>
            )}
            {adminTab === "users" && (
              <section className="panel">
                <div className="panel-heading">
                  <h3> Anëtarët e hapësirës </h3>
                  <button
                    className="button primary small"
                    onClick={() => setAddUser(true)}
                  >
                    <Plus size={16} /> Shto anëtar{" "}
                  </button>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th> Anëtar </th>
                        <th> Roli </th>
                        <th> Gjendja </th>
                        <th> Lidhja </th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u) => (
                        <tr key={u.id}>
                          <td>
                            <strong>{u.name}</strong>
                            <small>{u.email}</small>
                          </td>
                          <td>
                            <Select
                              aria-label={`Roli i ${u.name}`}
                              value={u.role}
                              disabled={u.id === user.id}
                              onChange={(e) =>
                                void api(`/admin/users/${u.id}`, {
                                  method: "PATCH",
                                  body: JSON.stringify({
                                    role: e.target.value,
                                  }),
                                })
                                  .then(loadAdmin)
                                  .catch(fail)
                              }
                            >
                              <option value="devs">Devs</option>
                              <option value="president">President</option>
                              <option value="manager">Manager</option>
                            </Select>
                          </td>
                          <td>
                            <Badge good={!!u.active}>
                              {u.active ? "Aktiv" : "Joaktiv"}
                            </Badge>
                          </td>
                          <td>
                            <button
                              className="text-button"
                              onClick={() =>
                                void api(`/admin/runtimes/${u.id}/restart`, {
                                  method: "POST",
                                })
                                  .then(loadAdmin)
                                  .catch(fail)
                              }
                            >
                              {" "}
                              Rinis{" "}
                            </button>
                          </td>
                          <td>
                            <button
                              className="button outline small"
                              disabled={u.id === user.id}
                              onClick={() => void updateUser(u)}
                            >
                              {u.active ? "Çaktivizo" : "Aktivizo"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
            {adminTab === "traffic" && <TrafficPanel />}
            {adminTab === "activity" && (
              <section className="panel">
                <div className="panel-heading">
                  <h3> Aktiviteti i fundit </h3>
                  <button
                    className="button outline small"
                    onClick={() => void loadAdmin().catch(fail)}
                  >
                    {" "}
                    Rifresko{" "}
                  </button>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th> Veprimi </th>
                        <th> Anëtar </th>
                        <th> Koha </th>
                      </tr>
                    </thead>
                    <tbody>
                      {audit.map((a) => (
                        <tr key={a.id}>
                          <td>{auditLabel(a.action)}</td>
                          <td>{a.actor_email || "Sistemi"}</td>
                          <td>
                            {new Date(a.created_at).toLocaleString("sq-AL")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </main>
        )}
      </div>

      {databaseBrowser && (
        <Modal
          title={`Databazat: ${databaseBrowser.name}`}
          error={error}
          onClose={() => setDatabaseBrowser(null)}
        >
          <p className="footnote">
            Databazat e biznesit që lejon kjo lidhje. Asistenti i zbulon
            automatikisht; nuk duhet t’i shtoni veçmas.
          </p>
          <div className="server-database-list">
            {serverDatabases.map((database) => (
              <div className="service-row" key={database.name}>
                <strong>{database.name}</strong>
                {!!database.is_default && <Badge good>Parazgjedhje</Badge>}
              </div>
            ))}
          </div>
          {loadingDatabases && (
            <p className="inline-progress" role="status">
              <LoaderCircle size={17} className="spin" /> Duke zbuluar
              databazat…
            </p>
          )}
          {!loadingDatabases && !serverDatabases.length && !error && (
            <p>
              Nuk u gjetën databaza biznesi të disponueshme. Kontrolloni lejet e
              përdoruesit SQL.
            </p>
          )}
          {databaseOffset !== null && (
            <button
              className="button outline small"
              disabled={loadingDatabases}
              onClick={() =>
                void browseDatabases(databaseBrowser, databaseOffset)
              }
            >
              Shfaq më shumë
            </button>
          )}
        </Modal>
      )}
      {deleteSource && (
        <Modal
          title="Të hiqet lidhja?"
          error={error}
          onClose={() => {
            if (!sourceActions[deleteSource.id]) setDeleteSource(null);
          }}
        >
          <p>
            Hiq lidhjen “{deleteSource.name}” nga aplikacioni?{" "}
            {deleteSource.configuration_origin === "environment"
              ? "Konfigurimi .env mbetet në server."
              : "Profili i ruajtur i kësaj lidhjeje do të hiqet nga .env."}{" "}
            Raportet e krijuara do të ruhen. Databazat në server nuk ndryshohen.
          </p>
          <div className="modal-actions">
            <button
              className="button outline"
              disabled={sourceActions[deleteSource.id]}
              onClick={() => setDeleteSource(null)}
            >
              Anulo
            </button>
            <button
              className="button danger"
              disabled={sourceActions[deleteSource.id]}
              onClick={() => void changeConnection(deleteSource, "remove")}
            >
              {sourceActions[deleteSource.id] ? "Duke hequr…" : "Hiq lidhjen"}
            </button>
          </div>
        </Modal>
      )}

      {settingsOpen && (
        <Modal title="Cilësimet" onClose={() => setSettingsOpen(false)}>
          {reasoningControl}
          <p>
            Zgjidhni sa arsyetim përdor modeli. Nivelet varen nga modeli i
            zgjedhur dhe zbatohen për mesazhet dhe raportet e ardhshme.
          </p>
          <div className="modal-actions">
            <button
              className="button primary"
              onClick={() => setSettingsOpen(false)}
            >
              Mbyll
            </button>
          </div>
        </Modal>
      )}

      {page === "reports" && report && (
        <Modal
          title={report.title}
          onClose={closeReport}
          error={error}
          className="report-preview-modal"
        >
          <section className="report-detail">
            <div className="panel-heading">
              <div>
                <span className="eyebrow"> PAMJA E RAPORTIT </span>
              </div>
              <Badge good={report.status === "completed"}>
                {label(report.status)}
              </Badge>
            </div>
            <div className="report-detail-actions">
              {report.status === "completed" && (
                <a
                  className="button primary small"
                  href={`/api/reports/${report.id}/export/xlsx`}
                >
                  <ArrowDownToLine size={16} />
                  Shkarko Excel
                </a>
              )}
              <button className="button outline small" onClick={closeReport}>
                <X size={16} />
                Mbyll raportin
              </button>
              <button
                className="button danger small"
                disabled={["queued", "running"].includes(report.status)}
                onClick={() => setDeleteReport(report)}
              >
                <Trash2 size={16} />
                Fshi raportin
              </button>
            </div>
            {report.error && (
              <p className="error-box">{errorMessage(report.error || "")}</p>
            )}
            {["queued", "running"].includes(report.status) && (
              <div className="working">
                <LoaderCircle className="spin" size={18} />{" "}
                {label(report.stage || "gathering")}{" "}
                <button
                  className="button outline small"
                  disabled={!!stoppingIds[report.conversation_id || ""]}
                  onClick={async () => {
                    const targetId = report.conversation_id || null;
                    setStoppingIds((ids) => ({
                      ...ids,
                      [targetId || ""]: true,
                    }));
                    try {
                      await api(`/reports/${report.id}/stop`, {
                        method: "POST",
                      });
                      const next = await api<Report>(`/reports/${report.id}`);
                      if (reportSelection.current === next.id) setReport(next);
                      await loadReports();
                    } catch (e) {
                      fail(e);
                    } finally {
                      setStoppingIds((ids) => {
                        const next = { ...ids };
                        delete next[targetId || ""];
                        return next;
                      });
                    }
                  }}
                >
                  <Square size={14} />
                  Ndërprit raportin
                </button>
              </div>
            )}
            {report.document && (
              <>
                <p className="report-summary">{report.document.summary}</p>
                <div className="metric-grid">
                  {report.document.metrics.map((m, i) => (
                    <div key={i}>
                      <span>{m.label}</span>
                      <strong>{m.value}</strong>
                      <p>{m.explanation}</p>
                    </div>
                  ))}
                </div>
                {report.document.sections.map((s, i) => (
                  <div className="report-section" key={i}>
                    <h3>{s.heading}</h3>
                    <MarkdownContent>{s.body}</MarkdownContent>
                  </div>
                ))}
                {report.document.limitations.length > 0 && (
                  <div className="report-section">
                    <h3> Kufizimet e të dhënave </h3>
                    <ul>
                      {report.document.limitations.map((l, i) => (
                        <li key={i}>{l}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="export-buttons">
                  {["markdown", "json", "csv"].map((format) => (
                    <a
                      key={format}
                      className={`button ${format === "xlsx" ? "primary" : "outline"} small`}
                      href={`/api/reports/${report.id}/export/${format}`}
                    >
                      <ArrowDownToLine size={16} />
                      {format === "xlsx"
                        ? "Shkarko Excel"
                        : format === "csv"
                          ? "Të dhënat CSV"
                          : format.toUpperCase()}
                    </a>
                  ))}
                </div>
              </>
            )}
          </section>
        </Modal>
      )}

      {login && (
        <Modal
          error={error}
          title={`Lidhni llogarinë ${login.provider === "claude" ? "Claude" : "ChatGPT"}`}
          onClose={() => setLogin(null)}
        >
          <div className="login-steps">
            <span className="provider-logo">
              <Sparkles size={27} />
            </span>
            <p>
              {" "}
              {login.provider === "claude"
                ? "Hapni faqen e hyrjes së Claude. Hyni me abonimin tuaj, pastaj kopjoni kodin që shfaqet dhe vendoseni më poshtë."
                : "Hapni faqen e hyrjes së OpenAI, hyni në llogari dhe vendosni këtë kod njëpërdorimësh."}
            </p>
            {login.userCode && (
              <div className="device-code">{login.userCode}</div>
            )}
            {providerLoginUrl(login) && (
              <a
                className="button primary wide"
                href={login.verificationUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                {" "}
                Hap hyrjen {login.provider === "claude"
                  ? "Claude"
                  : "OpenAI"}{" "}
                <ArrowRight size={17} />
              </a>
            )}
            {login.requiresCode && (
              <form onSubmit={finishClaudeLogin} className="claude-login-form">
                <label>
                  Kodi njëpërdorimësh nga Claude
                  <input
                    aria-label="Kodi nga Claude"
                    type="password"
                    autoComplete="off"
                    spellCheck={false}
                    maxLength={4096}
                    value={loginCode}
                    onChange={(e) => setLoginCode(e.target.value)}
                  />
                </label>
                <button
                  className="button primary wide"
                  disabled={connecting || !loginCode.trim()}
                >
                  Përfundo lidhjen
                </button>
              </form>
            )}
            <p className="waiting">
              <LoaderCircle size={16} className="spin" /> Në pritje që të
              përfundoni hyrjen…{" "}
            </p>
            <p className="footnote">
              {" "}
              {login.provider === "claude"
                ? "Kodi përdoret vetëm për të përfunduar këtë hyrje në Claude."
                : "Nëse hyrja me kod pajisjeje është e çaktivizuar, aktivizojeni te cilësimet e sigurisë të ChatGPT."}
            </p>
          </div>
        </Modal>
      )}
      {chatHistory && (
        <Modal
          error={error}
          title="Bisedat tuaja"
          onClose={() => setChatHistory(false)}
        >
          {conversations.map((c) => (
            <div className="history-row" key={c.id}>
              <button
                className="text-button history-title"
                disabled={uploading || deleting}
                onClick={() => {
                  setChatHistory(false);
                  void selectConversation(c);
                }}
              >
                <MessageSquare size={16} />
                <span>{c.title}</span>
              </button>
              <button
                className="delete-conversation"
                aria-label={`Fshi bisedën: ${c.title}`}
                disabled={conversationRunning(c.id) || uploading || deleting}
                onClick={() => {
                  setChatHistory(false);
                  setDeleteChat(c);
                }}
              >
                <Trash2 size={17} />
              </button>
            </div>
          ))}
          {!conversations.length && (
            <p className="muted"> Nuk ka ende biseda të ruajtura. </p>
          )}
        </Modal>
      )}
      {deleteChat && (
        <Modal
          error={error}
          title="Të fshihet biseda?"
          onClose={() => {
            if (!deleting) setDeleteChat(null);
          }}
        >
          <p>
            {" "}
            Fshi “ {deleteChat.title} ” dhe mesazhet e saj nga hapësira?
            Raportet e ruajtura do të mbeten.{" "}
          </p>
          <div className="modal-actions">
            <button
              className="button outline"
              disabled={deleting}
              onClick={() => setDeleteChat(null)}
            >
              {" "}
              Anulo{" "}
            </button>
            <button
              className="button danger"
              disabled={deleting || conversationRunning(deleteChat.id)}
              onClick={() => void removeConversation()}
            >
              {deleting ? "Duke fshirë…" : "Fshi bisedën"}
            </button>
          </div>
        </Modal>
      )}
      {deleteReport && (
        <Modal
          title="Të fshihet raporti?"
          error={error}
          onClose={() => {
            if (!deletingReport) setDeleteReport(null);
          }}
        >
          <p>
            Raporti “{deleteReport.title}” do të kalojë te “Të fshira”. Mund ta
            riktheni më vonë.
          </p>
          <div className="modal-actions">
            <button
              className="button outline"
              disabled={deletingReport}
              onClick={() => setDeleteReport(null)}
            >
              Anulo
            </button>
            <button
              className="button danger"
              disabled={deletingReport}
              onClick={() => void removeReport()}
            >
              {deletingReport ? "Duke fshirë…" : "Fshi raportin"}
            </button>
          </div>
        </Modal>
      )}
      {emptyTrashConfirm && (
        <Modal
          title="Të zbrazet koshi?"
          error={error}
          onClose={() => {
            if (!emptyingTrash) setEmptyTrashConfirm(false);
          }}
        >
          <p>
            Do të fshihen përgjithmonë {deletedReports.length} raporte nga “Të
            fshira”, skedarët e tyre Excel dhe të dhënat e ruajtura të
            raporteve. Ky veprim nuk mund të zhbëhet.
          </p>
          <div className="modal-actions">
            <button
              className="button outline"
              disabled={emptyingTrash}
              onClick={() => setEmptyTrashConfirm(false)}
            >
              Anulo
            </button>
            <button
              className="button danger"
              disabled={
                emptyingTrash || !!restoringReportId || !deletedReports.length
              }
              onClick={() => void emptyReportTrash()}
            >
              {emptyingTrash
                ? "Duke fshirë përgjithmonë…"
                : "Fshi përgjithmonë"}
            </button>
          </div>
        </Modal>
      )}
      {reportForm && (
        <Modal
          error={error}
          title="Krijo një raport"
          onClose={() => setReportForm(false)}
        >
          <form onSubmit={createReport}>
            <label>
              {" "}
              Titulli i raportit{" "}
              <input
                name="title"
                required
                placeholder="Pasqyra mujore e performancës"
              />
            </label>
            <label>
              {" "}
              Modeli i raportit{" "}
              <Select name="template_id">
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {label(t.name)}
                  </option>
                ))}
              </Select>
            </label>
            <label>
              {" "}
              Dataset-i{" "}
              <Select name="dataset_id">
                <option value=""> Përdor të dhënat manuale më poshtë </option>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                    {!d.enabled ? " — në pritje të lidhjes" : ""}
                  </option>
                ))}
              </Select>
            </label>
            <label>
              {" "}
              Parametrat e dataset-it (JSON){" "}
              <textarea
                name="parameters"
                rows={2}
                className="code-input"
                placeholder={'{"schema_name": "dbo"}'}
              />
            </label>
            <label>
              {" "}
              Të dhëna manuale (rreshta JSON){" "}
              <textarea
                name="rows"
                rows={5}
                className="code-input"
                placeholder={'[{"month": "September", "revenue": 12500}]'}
              />
            </label>
            <label>
              {" "}
              Ku duhet të përqendrohet raporti?{" "}
              <textarea
                name="instructions"
                rows={3}
                placeholder="Gjetjet kryesore, prirjet dhe hapat e rekomanduar…"
              />
            </label>
            <p className="footnote">
              {" "}
              Nuk shtohen të dhëna shembull automatikisht. Pa të dhëna, raporti
              ruhet në pritje të të dhënave.{" "}
            </p>
            <button className="button primary wide">
              <FileText size={17} /> Përgatit raportin{" "}
            </button>
          </form>
        </Modal>
      )}
      {addUser && (
        <Modal
          error={error}
          title="Shto një anëtar"
          onClose={() => setAddUser(false)}
        >
          <form onSubmit={(e) => void adminSubmit(e, "users")}>
            <label>
              {" "}
              Emri i plotë <input name="name" required />
            </label>
            <label>
              {" "}
              Emaili <input name="email" type="email" required />
            </label>
            <label>
              {" "}
              Fjalëkalimi fillestar{" "}
              <input
                name="password"
                type="password"
                minLength={12}
                required
                autoComplete="new-password"
              />
            </label>
            <label>
              {" "}
              Roli{" "}
              <Select name="role">
                <option value="manager">Manager</option>
                <option value="president">President</option>
                <option value="devs">Devs</option>
              </Select>
            </label>
            <button className="button primary wide"> Shto anëtar </button>
          </form>
        </Modal>
      )}
      {sourceAccess && (
        <Modal
          error={error}
          title={`Qasja në databazë: ${sourceAccess.name}`}
          onClose={() => setSourceAccess(null)}
        >
          <p>
            {" "}
            Administratorët mund të analizojnë automatikisht burimet e lidhura.
            Jepuni anëtarëve qasje te burimi për të zbuluar dhe analizuar
            tabelat që lejon përdoruesi SQL. Qasja te dataset-et mbetet e
            veçantë.{" "}
          </p>
          {users
            .filter((member) => member.role !== "devs")
            .map((member) => (
              <div className="grant-row" key={member.id}>
                <div>
                  <strong>{member.name}</strong>
                  <small>{member.email}</small>
                </div>
                <button
                  className="button outline small"
                  onClick={() => void changeSourceAccess(member)}
                >
                  {sourceGrants.includes(member.id)
                    ? "Hiq qasjen"
                    : "Jep qasje"}
                </button>
              </div>
            ))}
          {!users.some((member) => member.role !== "devs") && (
            <p className="muted"> Nuk ka ende llogari anëtarësh. </p>
          )}
        </Modal>
      )}
      {addSource && (
        <Modal
          error={error}
          title={
            editSource
              ? "Konfiguro burimin e të dhënave"
              : "Shto burim të dhënash"
          }
          onClose={() => {
            if (!savingSource) setAddSource(false);
          }}
        >
          <form onSubmit={(e) => void adminSubmit(e, "sources")}>
            <label>
              {" "}
              Emri i lidhjes{" "}
              <input
                name="name"
                required
                maxLength={120}
                defaultValue={editSource?.name || ""}
                placeholder="P.sh. serveri i financës ose GoTech"
              />
            </label>
            <label>
              {" "}
              Lloji i databazës{" "}
              <Select
                name="kind"
                value={sourceKind}
                disabled={
                  !!editSource &&
                  !["sqlserver", "saphana"].includes(editSource.kind)
                }
                onChange={(e) => {
                  setSourceKind(e.target.value);
                  setAutoDiscoverDatabases(true);
                }}
              >
                {[
                  "sqlserver",
                  "saphana",
                  "postgresql",
                  "mysql",
                  "sqlite",
                  "other",
                ].map((kind) => (
                  <option key={kind} value={kind}>
                    {
                      {
                        sqlserver: "SQL Server",
                        saphana: "SAP HANA",
                        postgresql: "PostgreSQL",
                        mysql: "MySQL",
                        sqlite: "SQLite",
                        other: "Tjetër",
                      }[kind]
                    }
                  </option>
                ))}
              </Select>
            </label>
            {sourceSupported && (
              <fieldset className="source-connection-fields" key={sourceKind}>
                <legend>
                  {sourceKind === "saphana"
                    ? "Lidhja SAP HANA"
                    : "Lidhja SQL Server"}
                </legend>
                {environmentActive ? (
                  <>
                    <div className="notice environment-source">
                      <div>
                        <strong>Lidhja përdor .env në server.</strong>
                        <p>
                          Kredencialet janë ngarkuar privatisht. Nuk shfaqen në
                          shfletues.
                        </p>
                        <button
                          type="button"
                          className="button outline small"
                          onClick={() => setOverrideEnvironment(true)}
                        >
                          Ndrysho konfigurimin e lidhjes
                        </button>
                      </div>
                    </div>
                    <div className="environment-fields">
                      {["HOST", "PORT", "USER", "PASSWORD", "DATABASE"].map(
                        (field) => (
                          <div className="service-row" key={field}>
                            <code>
                              {sourcePrefix}_{field}
                            </code>
                            <Badge
                              good={
                                !!editSource?.connection_fields?.[
                                  sourcePrefix + "_" + field
                                ] || field === "DATABASE"
                              }
                            >
                              {editSource?.connection_fields?.[
                                sourcePrefix + "_" + field
                              ]
                                ? "Ngarkuar nga .env"
                                : field === "DATABASE"
                                  ? "Zbulim automatik"
                                  : "Mungon në .env"}
                            </Badge>
                          </div>
                        ),
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    {keepConnectionFields && (
                      <p className="footnote">
                        Fushat bosh mbajnë hostin, përdoruesin dhe fjalëkalimin
                        aktual. Kredencialet ruhen në .env.
                      </p>
                    )}
                    {changingSourceKind && (
                      <p className="notice">
                        Vendosni portin SQL të llojit të ri. Databaza
                        parazgjedhje pastrohet për zbulim automatik.
                      </p>
                    )}
                    {["HOST", "PORT", "USER", "PASSWORD"].map((field) => (
                      <label key={field}>
                        {sourcePrefix}_{field}
                        <input
                          name={sourcePrefix + "_" + field}
                          type={
                            field === "PASSWORD"
                              ? "password"
                              : field === "PORT"
                                ? "number"
                                : "text"
                          }
                          required={
                            !keepConnectionFields ||
                            (field === "PORT" && changingSourceKind)
                          }
                          min={field === "PORT" ? 1 : undefined}
                          max={field === "PORT" ? 65535 : undefined}
                          maxLength={field === "PASSWORD" ? 1024 : 255}
                          autoComplete={
                            field === "PASSWORD" ? "new-password" : "off"
                          }
                          defaultValue={
                            field === "PORT" && !editSource
                              ? sourceKind === "saphana"
                                ? "30015"
                                : "1433"
                              : ""
                          }
                          placeholder={
                            field === "PORT"
                              ? sourceKind === "saphana"
                                ? "Porti SQL HANA, p.sh. 30015 ose 443"
                                : "1433"
                              : keepConnectionFields
                                ? "Lëreni bosh për të mbajtur vlerën aktuale"
                                : field === "HOST"
                                  ? "Adresa e serverit"
                                  : field === "USER"
                                    ? "Përdoruesi i raporteve"
                                    : "Fjalëkalimi"
                          }
                        />
                      </label>
                    ))}
                    <label>
                      <span className="source-discovery-option">
                        <input
                          type="checkbox"
                          checked={autoDiscoverDatabases}
                          onChange={(e) =>
                            setAutoDiscoverDatabases(e.target.checked)
                          }
                        />
                        Zbulo automatikisht databazat
                      </span>
                    </label>
                    <label>
                      {sourcePrefix}_DATABASE (opsionale)
                      <input
                        name={sourcePrefix + "_DATABASE"}
                        disabled={autoDiscoverDatabases}
                        maxLength={128}
                        autoComplete="off"
                        placeholder={
                          autoDiscoverDatabases
                            ? "Databazat do të zbulohen automatikisht"
                            : "Databaza parazgjedhje, nëse dëshironi"
                        }
                      />
                    </label>
                    {sourceKind === "saphana" && (
                      <>
                        <label>
                          Certifikata CA e besuar (PEM, opsionale)
                          <textarea
                            name="HANA_TLS_CA_CERTIFICATE"
                            rows={5}
                            maxLength={65536}
                            autoComplete="off"
                            spellCheck={false}
                            placeholder={
                              editSource?.tls?.custom_ca
                                ? "Certifikata është ruajtur. Lëreni bosh për ta mbajtur."
                                : "-----BEGIN CERTIFICATE-----\nCertifikata rrënjë/ndërmjetëse nga administratori SAP HANA\n-----END CERTIFICATE-----"
                            }
                          />
                        </label>
                        <label>
                          Emri DNS në certifikatën e serverit (opsionale)
                          <input
                            name="HANA_TLS_SERVER_NAME"
                            maxLength={253}
                            autoComplete="off"
                            placeholder={
                              editSource?.tls?.server_name_configured
                                ? "Emri është ruajtur. Lëreni bosh për ta mbajtur."
                                : "P.sh. hana.company.internal"
                            }
                          />
                        </label>
                        <p className="footnote">
                          Certifikata CA dhe emri i serverit merren nga
                          administratori i SAP HANA. Mos vendosni çelësa
                          privatë. Ruhet në .env dhe përdoret vetëm nga
                          backend-i për verifikimin TLS.
                        </p>
                        <label>
                          HANA_ENCRYPT
                          <Select
                            name="HANA_ENCRYPT"
                            defaultValue={
                              editSource?.tls?.encrypt === false
                                ? "false"
                                : "true"
                            }
                          >
                            <option value="true">TLS i aktivizuar</option>
                            <option value="false">
                              Pa TLS — vetëm nëse serveri e kërkon
                            </option>
                          </Select>
                        </label>
                        <label>
                          HANA_VALIDATE_CERTIFICATE
                          <Select
                            name="HANA_VALIDATE_CERTIFICATE"
                            defaultValue={
                              editSource?.tls?.validate_certificate === false
                                ? "false"
                                : "true"
                            }
                          >
                            <option value="true">
                              Kontrollo certifikatën e serverit
                            </option>
                            <option value="false">
                              Pa kontroll certifikate — lidhje pa verifikim
                            </option>
                          </Select>
                        </label>
                      </>
                    )}
                  </>
                )}
                {sourceKind === "saphana" && (
                  <p className="footnote">
                    Përdorni portin SQL të SAP HANA, jo portin SQL Server. HANA
                    Cloud zakonisht përdor 443 dhe TLS. Skemat e kompanive në
                    SAP Business One zbulohen brenda tenant-it; HANA_DATABASE
                    është emri i tenant-it, jo skema.
                  </p>
                )}
                <p className="footnote">
                  Konfigurimi ruhet në .env të projektit dhe lexohet vetëm nga
                  backend-i. Modeli nuk merr hostin, përdoruesin apo
                  fjalëkalimin.
                </p>
                {editSource?.env_prefix && (
                  <p className="footnote">
                    Prefiksi në .env: <code>{editSource.env_prefix}</code>
                  </p>
                )}
              </fieldset>
            )}
            {!sourceSupported && (
              <p className="footnote">
                {" "}
                Ky lloj databaze mund të përcaktohet, por lidhja e tij nuk është
                implementuar ende.{" "}
              </p>
            )}
            <label>
              {" "}
              Përshkrimi{" "}
              <textarea
                name="description"
                rows={2}
                defaultValue={editSource?.description || ""}
                placeholder="Çfarë të dhënash ofron ky burim?"
              />
            </label>
            <button className="button primary wide" disabled={savingSource}>
              {savingSource
                ? "Duke ruajtur…"
                : editSource
                  ? "Ruaj lidhjen"
                  : "Ruaj burimin"}
            </button>
          </form>
        </Modal>
      )}
      {addDataset && (
        <Modal
          error={error}
          title="Përcakto një dataset opsional"
          onClose={() => setAddDataset(false)}
        >
          <form onSubmit={(e) => void adminSubmit(e, "datasets")}>
            <label>
              {" "}
              Emri i dataset-it{" "}
              <input
                name="name"
                required
                placeholder="Përmbledhja mujore e shitjeve"
              />
            </label>
            <label>
              {" "}
              Burimi{" "}
              <Select name="source_id">
                {sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </label>
            <label>
              {" "}
              Çelësi i pyetjes së miratuar{" "}
              <Select
                name="query_key"
                required
                allowCustom
                defaultValue=""
                options={
                  overview?.database_configuration.queries
                    .filter((q) => !q.error)
                    .map((q) => ({
                      value: q.query_key,
                      label: q.name ? label(q.name) : q.query_key,
                    })) || []
                }
              />
            </label>
            <label>
              {" "}
              Përshkrimi <textarea name="description" rows={3} />
            </label>
            <p className="footnote">
              {" "}
              Çelësat lidhen me skriptet .sql dhe .json të miratuara. Të
              disponueshme:{" "}
              {overview?.database_configuration.queries
                .filter((q) => !q.error)
                .map((q) => q.query_key)
                .join(", ") || "asnjë"}{" "}
              . Dataset-et nisin joaktive. Aktivizoni dhe jepni qasje pas
              konfigurimit të burimit. Katalogu përdor parametrat{" "}
              {'{"schema_name":"dbo"}'}.
            </p>
            <button className="button primary wide"> Ruaj dataset-in </button>
          </form>
        </Modal>
      )}
      {grant && (
        <Modal
          error={error}
          title={`Jep qasje te ${grant.name}`}
          onClose={() => setGrant(null)}
        >
          <p> Zgjidhni një anëtar për t’i dhënë qasje në dataset. </p>
          {users.map((u) => (
            <div className="grant-row" key={u.id}>
              <div>
                <strong>{u.name}</strong>
                <small>{u.email}</small>
              </div>
              <button
                className="button outline small"
                onClick={() =>
                  void api(`/admin/datasets/${grant.id}/grants/${u.id}`, {
                    method: "PUT",
                  })
                    .then(() => {
                      setGrant(null);
                      void api<Dataset[]>("/datasets").then(setDatasets);
                    })
                    .catch(fail)
                }
              >
                <Check size={15} /> Jep qasje{" "}
              </button>
              <button
                className="text-button"
                onClick={() =>
                  void api(`/admin/datasets/${grant.id}/grants/${u.id}`, {
                    method: "DELETE",
                  })
                    .then(() => {
                      setGrant(null);
                      void api<Dataset[]>("/datasets").then(setDatasets);
                    })
                    .catch(fail)
                }
              >
                {" "}
                Hiq qasjen{" "}
              </button>
            </div>
          ))}
        </Modal>
      )}
    </div>
  );
}

function PageHeading({
  eyebrow,
  title,
  text,
  action,
}: {
  eyebrow: string;
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{text}</p>
      </div>
      {action}
    </div>
  );
}
function EmptyState({
  icon,
  title,
  text,
}: {
  icon: ReactNode;
  title: string;
  text: string;
}) {
  return (
    <div className="empty-state">
      <div>{icon}</div>
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
function DatasetTable({
  datasets,
  onGrant,
  onToggle,
}: {
  datasets: Dataset[];
  onGrant?: (d: Dataset) => void;
  onToggle?: (d: Dataset) => void;
}) {
  return datasets.length ? (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th> Dataset-i </th>
            <th> Gjendja </th>
            <th> Çelësi i pyetjes </th>
            {onGrant && <th> Qasja </th>}
          </tr>
        </thead>
        <tbody>
          {datasets.map((d) => (
            <tr key={d.id}>
              <td>
                <strong>{d.name}</strong>
                <small>{d.description || d.source}</small>
              </td>
              <td>
                <Badge good={!!d.enabled}>
                  {d.enabled ? "Aktiv" : "Joaktiv"}
                </Badge>
                {onToggle && (
                  <button className="text-button" onClick={() => onToggle(d)}>
                    {d.enabled ? "Çaktivizo" : "Aktivizo"}
                  </button>
                )}
                {d.status && <small> Burimi: {label(d.status || "")}</small>}
              </td>
              <td>
                <code>{d.query_key || "—"}</code>
              </td>
              {onGrant && (
                <td>
                  <button className="text-button" onClick={() => onGrant(d)}>
                    {" "}
                    Menaxho qasjen <ArrowRight size={14} />
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <p className="muted">
      {" "}
      Nuk ka dataset-e të përcaktuara ose të ndara me ju.{" "}
    </p>
  );
}
