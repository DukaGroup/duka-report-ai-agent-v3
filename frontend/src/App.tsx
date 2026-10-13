import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowLeft,
  RotateCcw,
  Search,
  AudioLines,
  Check,
  CircleHelp,
  Database,
  FileText,
  History,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  MessageSquare,
  Mic,
  Plus,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Volume2,
  X,
} from "lucide-react";
import Markdown from "react-markdown";
import { Select } from "./Select";
import { api, streamChat } from "./api";
import { label, errorMessage, auditLabel } from "./locale";
import { VoiceRecorder, speak } from "./voice";
import type {
  Audit,
  Conversation,
  Dataset,
  Login,
  Message,
  Model,
  Overview,
  RateLimits,
  Report,
  Source,
  Subscription,
  Template,
  User,
  VoiceStatus,
} from "./types";

type Page =
  | "conversations"
  | "chat"
  | "reports"
  | "sources"
  | "connection"
  | "admin";
const initialSubscription: Subscription = { connected: false, available: true };
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
        <div className="brand-mark">d.</div>
        <span>
          duka<span className="brand-sub"> HAPËSIRA E RAPORTEVE </span>
        </span>
      </div>
      <div className="auth-card">
        <span className="eyebrow"> Një pamje më e qartë e biznesit tuaj </span>
        <h1>
          {setup ? "Mirë se vini në hapësirën tuaj." : "Mirë se u kthyet."}
        </h1>
        <p>
          {setup
            ? "Krijoni llogarinë e administratorit. Pasi të hyni, lidhni abonimin tuaj ChatGPT."
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
          <ShieldCheck size={16} /> Hyrja në llogarinë ChatGPT kryhet nga
          OpenAI.{" "}
        </div>
      </div>
      <p className="auth-footer">
        {" "}
        GRUPI DUKA <span> Biseda që sjellin qartësi. </span>
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
    api<{ needs_setup: boolean; user: User | null }>("/auth/status")
      .then((r) => {
        setSetup(r.needs_setup);
        setUser(r.user);
      })
      .catch((e) => setError(errorMessage((e as Error).message)))
      .finally(() => setLoading(false));
  }, []);
  if (loading)
    return (
      <div className="loading-screen">
        <div className="brand-mark">d.</div>
        <LoaderCircle className="spin" />
        <p> Duke hapur hapësirën… </p>
      </div>
    );
  if (error && !user)
    return (
      <div className="loading-screen">
        <p role="alert">{error}</p>
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
  const [models, setModels] = useState<Model[]>([]),
    [model, setModel] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]),
    [currentId, setCurrentId] = useState<string | null>(null),
    [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState(""),
    [busy, setBusy] = useState(false),
    [activity, setActivity] = useState("");
  const [recording, setRecording] = useState(false),
    [transcribing, setTranscribing] = useState(false),
    [readReplies, setReadReplies] = useState(false),
    [voiceMode, setVoiceMode] = useState(false);
  const [voice, setVoice] = useState<VoiceStatus | null>(null),
    [limits, setLimits] = useState<RateLimits | null>(null);
  const [reportsLoaded, setReportsLoaded] = useState(false);
  const [stoppingReports, setStoppingReports] = useState(false);
  const [reports, setReports] = useState<Report[]>([]),
    [report, setReport] = useState<Report | null>(null),
    [templates, setTemplates] = useState<Template[]>([]),
    [datasets, setDatasets] = useState<Dataset[]>([]),
    [reportForm, setReportForm] = useState(false);
  const activeReports = reports.filter((r) =>
    ["queued", "running"].includes(r.status),
  );
  const reportBusy = activeReports.length > 0;
  const chatLocked = busy || reportBusy || !reportsLoaded || stoppingReports;
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
  const [voiceLanguage, setVoiceLanguage] = useState("sq");
  const [businessSources, setBusinessSources] = useState<Source[]>([]);
  const [sourceAccess, setSourceAccess] = useState<Source | null>(null);
  const [sourceGrants, setSourceGrants] = useState<string[]>([]);
  const [editSource, setEditSource] = useState<Source | null>(null);
  const [sourceKind, setSourceKind] = useState("sqlserver");
  const [savingSource, setSavingSource] = useState(false);
  const environmentActive =
    !!overview &&
    [
      "SQLSERVER_HOST",
      "SQLSERVER_USER",
      "SQLSERVER_PASSWORD",
      "SQLSERVER_DATABASE",
    ].some((key) => overview.database_configuration.environment[key]);
  const [conversationSearch, setConversationSearch] = useState("");
  const [openingConversation, setOpeningConversation] = useState(false);
  const [deleteReport, setDeleteReport] = useState<Report | null>(null);
  const [deletingReport, setDeletingReport] = useState(false);
  const [reportTrash, setReportTrash] = useState(false);
  const [deletedReports, setDeletedReports] = useState<Report[]>([]);
  const reportSelection = useRef<string | null>(null);
  const [deleteChat, setDeleteChat] = useState<Conversation | null>(null);
  const [chatHistory, setChatHistory] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [checkingSource, setCheckingSource] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null),
    recorder = useRef(new VoiceRecorder()),
    sendRef = useRef<(text: string, voiced?: boolean) => Promise<void>>(
      async () => {},
    ),
    voiceModeRef = useRef(false),
    resumeVoiceAfterReport = useRef(false),
    mounted = useRef(true),
    activeId = useRef<string | null>(null),
    voiceEpoch = useRef(0);

  const fail = (e: unknown) =>
    setError(errorMessage((e as Error).message || "Ndodhi një gabim."));
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      recorder.current.stop(true);
      window.speechSynthesis?.cancel();
    };
  }, []);
  useEffect(() => {
    activeId.current = currentId;
  }, [currentId]);
  useEffect(() => {
    voiceModeRef.current = voiceMode;
    if (!voiceMode) window.speechSynthesis?.cancel();
  }, [voiceMode]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: busy ? "instant" : "smooth" });
  }, [messages, busy]);
  useEffect(() => {
    if (reportBusy) {
      resumeVoiceAfterReport.current = voiceModeRef.current;
      recorder.current.stop(true);
      setRecording(false);
    } else if (
      resumeVoiceAfterReport.current &&
      voiceModeRef.current &&
      !busy &&
      !transcribing &&
      !recording &&
      !window.speechSynthesis?.speaking
    ) {
      resumeVoiceAfterReport.current = false;
      void startRecording();
    }
  }, [reportBusy, busy, transcribing, recording]);

  async function loadSubscription() {
    const result = await api<Subscription>("/subscription");
    setSubscription(result);
    if (result.login?.status === "failed") {
      setLogin(null);
      setError(
        result.login.error ||
          "Hyrja nuk përfundoi. Aktivizoni hyrjen me kod pajisjeje në cilësimet e sigurisë të ChatGPT dhe provoni përsëri.",
      );
    }
    if (result.connected) {
      setLogin(null);
      const list = await api<Model[]>("/subscription/models");
      setModels(list);
      setModel((prev) =>
        list.some((m) => m.model === prev)
          ? prev
          : (list.find((m) => m.isDefault) || list[0])?.model || "",
      );
    }
    return result;
  }
  async function loadReports() {
    const next = await api<Report[]>("/reports");
    reportBusyRef.current = next.some((r) =>
      ["queued", "running"].includes(r.status),
    );
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
      loadSubscription(),
      api<Conversation[]>("/conversations").then(setConversations),
      api<Template[]>("/report-templates").then(setTemplates),
      api<Dataset[]>("/datasets").then(setDatasets),
      api<Source[]>("/sources").then(setBusinessSources),
      api<VoiceStatus>("/voice").then(setVoice),
      loadReports(),
    ]).catch(fail);
  }, [user]);
  useEffect(() => {
    if (user?.role === "admin" && (page === "admin" || page === "sources"))
      void loadAdmin().catch(fail);
  }, [page, user]);
  useEffect(() => {
    if (!login) return;
    const timer = setInterval(() => {
      void loadSubscription().catch(fail);
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
      busy || reportBusy ? 1000 : 5000,
    );
    return () => clearInterval(timer);
  }, [busy, reportBusy, report?.id, report?.status, reportTrash]);

  async function connect() {
    setConnecting(true);
    setError("");
    try {
      setLogin(await api<Login>("/subscription/login", { method: "POST" }));
    } catch (e) {
      fail(e);
    } finally {
      setConnecting(false);
    }
  }
  async function disconnect() {
    try {
      await api("/subscription/disconnect", { method: "POST" });
      setSubscription(initialSubscription);
      setModels([]);
      setLimits(null);
      setLogin(null);
    } catch (e) {
      fail(e);
    }
  }
  async function selectConversation(c: Conversation) {
    if (busy && c.id === currentId) {
      setPage("chat");
      return;
    }
    if (busy || recording || transcribing || openingConversation) return;
    endVoice();
    setOpeningConversation(true);
    setError("");
    try {
      const result = await api<Conversation & { messages: Message[] }>(
        `/conversations/${c.id}`,
      );
      setCurrentId(c.id);
      activeId.current = c.id;
      setMessages(result.messages);
      setDraft("");
      if (result.model) setModel(result.model);
      setPage("chat");
    } catch (e) {
      fail(e);
    } finally {
      setOpeningConversation(false);
    }
  }
  async function newChat() {
    if (chatLocked || transcribing || openingConversation) return;
    endVoice();
    setOpeningConversation(true);
    setError("");
    try {
      const next = await api<Conversation>("/conversations", {
        method: "POST",
        body: JSON.stringify({ model: model || null }),
      });
      setConversations((items) => [
        { ...next, message_count: 0, preview: null },
        ...items,
      ]);
      setCurrentId(next.id);
      activeId.current = next.id;
      setMessages([]);
      setDraft("");
      setPage("chat");
    } catch (e) {
      fail(e);
    } finally {
      setOpeningConversation(false);
    }
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
    try {
      await api(`/reports/${item.id}/restore`, { method: "POST" });
      setDeletedReports((items) => items.filter((row) => row.id !== item.id));
      await loadReports();
    } catch (e) {
      fail(e);
    }
  }
  async function send(text: string, voiced = false) {
    if (!text.trim() || chatLocked || reportBusyRef.current) return;
    if (!subscription.connected) {
      setError("Lidhni abonimin ChatGPT për të nisur bisedën.");
      setPage("connection");
      return;
    }
    setBusy(true);
    setError("");
    setDraft("");
    setActivity("Duke menduar");
    const spokenEpoch = voiceEpoch.current;
    let id = currentId,
      full = "",
      finished = false;
    try {
      if (!id) {
        const conversation = await api<Conversation>("/conversations", {
          method: "POST",
          body: JSON.stringify({ model: model || null }),
        });
        id = conversation.id;
        setCurrentId(id);
        activeId.current = id;
      }
      setMessages((prev) => [
        ...prev,
        {
          id: `u-${Date.now()}`,
          role: "user",
          content: text,
          status: "completed",
        },
        {
          id: "streaming",
          role: "assistant",
          content: "",
          status: "streaming",
        },
      ]);
      await streamChat(id, text, model, (event) => {
        if (event.type === "delta") {
          full += event.text;
          setActivity("Duke shkruar");
        }
        if (event.type === "tool") setActivity("Duke kontrolluar të dhënat");
        if (event.type === "error") throw new Error(event.message);
        if (event.type === "done") {
          finished = event.status === "completed";
          full = event.text || full;
        }
        if (event.type === "delta" || event.type === "done")
          setMessages((prev) =>
            prev.map((m) =>
              m.id === "streaming"
                ? {
                    ...m,
                    content: full,
                    status: event.type === "done" ? event.status : "streaming",
                  }
                : m,
            ),
          );
      });
      if (
        spokenEpoch === voiceEpoch.current &&
        (readReplies || voiced || voiceModeRef.current) &&
        finished &&
        full
      )
        speak(full, () => {
          if (
            spokenEpoch === voiceEpoch.current &&
            voiceModeRef.current &&
            mounted.current
          )
            void startRecording();
        });
      const [list, detail] = await Promise.all([
        api<Conversation[]>("/conversations"),
        api<Conversation & { messages: Message[] }>(`/conversations/${id}`),
      ]);
      setConversations(list);
      if (activeId.current === id) setMessages(detail.messages);
      setBusinessSources(await api<Source[]>("/sources"));
      await loadReports();
    } catch (e) {
      fail(e);
      voiceModeRef.current = false;
      setVoiceMode(false);
      setDraft(text);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === "streaming" ? { ...m, status: "failed" } : m,
        ),
      );
    } finally {
      try {
        await loadReports();
      } catch (e) {
        fail(e);
      }
      setBusy(false);
      setActivity("");
    }
  }
  sendRef.current = send;
  async function startRecording() {
    if (reportBusyRef.current || stoppingReports) return;
    resumeVoiceAfterReport.current = false;
    if (!voice?.available) {
      setError(
        "Transkriptimi zanor nuk është i disponueshëm. Kontrolloni shërbimin në Administrim.",
      );
      voiceModeRef.current = false;
      setVoiceMode(false);
      return;
    }
    if (!subscription.connected) {
      setPage("connection");
      setError("Lidhni abonimin para se të nisni bisedën me zë.");
      voiceModeRef.current = false;
      setVoiceMode(false);
      return;
    }
    voiceEpoch.current += 1;
    window.speechSynthesis?.cancel();
    setRecording(true);
    try {
      const started = await recorder.current.start((blob) => {
        void transcribe(blob);
      }, voiceModeRef.current);
      if (!started) setRecording(false);
    } catch (e) {
      recorder.current.stop(true);
      setRecording(false);
      fail(e);
      voiceModeRef.current = false;
      setVoiceMode(false);
    }
  }
  async function transcribe(blob: Blob) {
    const epoch = voiceEpoch.current;
    setRecording(false);
    setTranscribing(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", blob, "recording");
      form.append("language", voiceLanguage || "auto");
      const result = await api<{ text: string; language: string }>(
        "/voice/transcribe",
        { method: "POST", body: form },
      );
      if (epoch !== voiceEpoch.current || !mounted.current) return;
      if (!result.text.trim()) {
        setError("Nuk u dëgjua të folur. Provoni përsëri.");
        setVoiceMode(false);
        voiceModeRef.current = false;
      } else {
        setTranscribing(false);
        await sendRef.current(result.text, true);
      }
    } catch (e) {
      fail(e);
      setVoiceMode(false);
      voiceModeRef.current = false;
    } finally {
      setTranscribing(false);
    }
  }
  function endVoice() {
    resumeVoiceAfterReport.current = false;
    voiceEpoch.current += 1;
    voiceModeRef.current = false;
    setVoiceMode(false);
    recorder.current.stop(true);
    setRecording(false);
    window.speechSynthesis?.cancel();
  }
  async function toggleVoiceMode() {
    if (voiceMode) endVoice();
    else {
      voiceModeRef.current = true;
      setVoiceMode(true);
      await startRecording();
    }
  }
  async function stopResponse() {
    endVoice();
    setStoppingReports(true);
    try {
      if (currentId)
        await api(`/conversations/${currentId}/stop`, { method: "POST" });
      else
        for (const item of activeReports)
          await api(`/reports/${item.id}/stop`, { method: "POST" });
      await loadReports();
    } catch (e) {
      fail(e);
    } finally {
      setStoppingReports(false);
    }
  }
  function navigate(next: Page) {
    endVoice();
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
      const result = await api<Report>("/reports", {
        method: "POST",
        body: JSON.stringify({
          title: data.title,
          template_id: data.template_id,
          instructions: data.instructions,
          dataset_id: data.dataset_id || null,
          rows,
          parameters: JSON.parse(
            String(data.parameters || "{}").trim() || "{}",
          ),
          model: model || null,
          conversation_id: page === "chat" ? currentId : null,
        }),
      });
      setReportForm(false);
      setReportTrash(false);
      reportSelection.current = result.id;
      setReport(result);
      setPage("reports");
      await loadReports();
    } catch (e) {
      fail(e);
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
        if (key.startsWith("SQLSERVER_") && data[key] === "") delete data[key];
      }
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
    setAddSource(true);
  }
  async function removeConversation() {
    if (!deleteChat || busy || recording || transcribing || deleting) return;
    setDeleting(true);
    try {
      await api(`/conversations/${deleteChat.id}`, { method: "DELETE" });
      if (currentId === deleteChat.id) {
        recorder.current.stop(true);
        window.speechSynthesis?.cancel();
        setVoiceMode(false);
        setCurrentId(null);
        activeId.current = null;
        setMessages([]);
        setDraft("");
        setPage("conversations");
      }
      setConversations((items) => items.filter((c) => c.id !== deleteChat.id));
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
    connection: "Lidhja me ChatGPT",
    admin: "Administrimi",
  }[page];
  const conversationReports = currentId
    ? reports.filter((r) => r.conversation_id === currentId)
    : [];
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
          <span className="brand-mark">d.</span>
          <span>
            duka<span className="brand-sub"> HAPËSIRA E RAPORTEVE </span>
          </span>
        </button>
        <button
          className="new-chat"
          onClick={newChat}
          disabled={chatLocked || transcribing || openingConversation}
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
                disabled={
                  (busy && c.id !== currentId) ||
                  transcribing ||
                  recording ||
                  openingConversation
                }
                className={`recent-item ${currentId === c.id ? "active" : ""}`}
                onClick={() => void selectConversation(c)}
              >
                <MessageSquare size={14} />
                <span>{c.title}</span>
              </button>
              <button
                type="button"
                className="delete-conversation"
                disabled={chatLocked || transcribing || recording || deleting}
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
              Abonimi ChatGPT{" "}
              <small>
                {subscription.connected
                  ? `${subscription.account?.planType || "I lidhur"} · I lidhur`
                  : "Lidh llogarinë"}
              </small>
            </span>
            <ArrowRight size={15} />
          </button>
          {user.role === "admin" && (
            <button
              className={`nav-item ${page === "admin" ? "selected" : ""}`}
              onClick={() => navigate("admin")}
            >
              <Settings size={18} /> Administrimi{" "}
            </button>
          )}
          <div className="profile">
            <span className="avatar">
              {user.name.slice(0, 1).toUpperCase()}
            </span>
            <span>
              {user.name}
              <small>
                {user.role === "admin"
                  ? "Administratori i hapësirës"
                  : "Anëtar i hapësirës"}
              </small>
            </span>
            <button
              className="icon-button"
              aria-label="Dil nga llogaria"
              disabled={chatLocked || transcribing}
              onClick={() => {
                endVoice();
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
              <span /> Grupi Duka{" "}
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
                  disabled={chatLocked || openingConversation}
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
                      disabled={
                        (busy && c.id !== currentId) ||
                        transcribing ||
                        recording ||
                        openingConversation
                      }
                      onClick={() => void selectConversation(c)}
                    >
                      <span className="report-icon">
                        <MessageSquare size={23} />
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
                      disabled={busy || recording || transcribing || deleting}
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
              <div className={`message-scroll ${empty ? "empty-scroll" : ""}`}>
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
                      ChatGPT.{" "}
                    </div>
                  </section>
                ) : (
                  <div className="messages">
                    {messages.map((m) => (
                      <article key={m.id} className={`message ${m.role}`}>
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
                              {m.role === "assistant" ? "ChatGPT" : "Ju"}
                            </span>
                          </div>
                          {m.content ? (
                            <div className="markdown">
                              <Markdown>{m.content}</Markdown>
                            </div>
                          ) : (
                            <div className="thinking">
                              <span />
                              <span />
                              <span />
                              {activity || "Në pritje të përgjigjes"}
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
                          {m.role === "assistant" &&
                            m.status === "completed" &&
                            m.content && (
                              <button
                                className="icon-button read-message"
                                aria-label="Lexo përgjigjen me zë"
                                onClick={() => speak(m.content)}
                              >
                                <Volume2 size={16} />
                              </button>
                            )}
                        </div>
                      </article>
                    ))}
                    {conversationReports.map((r) => (
                      <div
                        className="chat-report"
                        key={r.id}
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
                          <p>
                            <LoaderCircle className="spin" size={16} />
                            {label(r.stage || "gathering")}
                          </p>
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
                    ))}
                    <div ref={bottom} />
                  </div>
                )}
              </div>
              <div className="composer-wrap">
                {!subscription.connected && (
                  <div className="connect-prompt">
                    <span>
                      <Sparkles size={15} /> Lidhni abonimin ChatGPT për të
                      biseduar.{" "}
                    </span>
                    <button onClick={connect} disabled={connecting}>
                      {connecting ? "Duke u lidhur…" : "Lidh llogarinë"}
                      <ArrowRight size={14} />
                    </button>
                  </div>
                )}
                {(recording || transcribing || voiceMode) && (
                  <div className="voice-status">
                    <AudioLines size={17} />
                    {transcribing
                      ? "Duke transkriptuar lokalisht… Përdorimi i parë mund të shkarkojë modelin zanor."
                      : recording
                        ? "Po dëgjoj… Flisni natyrshëm ose shtypni mikrofonin për të përfunduar."
                        : "Biseda me zë është aktive."}
                    <button onClick={endVoice}> Ndalo zërin </button>
                  </div>
                )}
                {reportBusy && (
                  <div className="report-progress" role="status">
                    <LoaderCircle size={18} className="spin" />
                    <div>
                      <strong>Raporti në Excel po përgatitet</strong>
                      <span>
                        {activeReports
                          .map((r) => label(r.stage || "gathering"))
                          .join(" · ")}{" "}
                        — Prisni përfundimin ose ndërpriteni me butonin e
                        ndalimit.
                      </span>
                    </div>
                  </div>
                )}
                <form
                  className="composer"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void send(draft);
                  }}
                >
                  <textarea
                    aria-label="Mesazhi"
                    placeholder="Bëni një pyetje ose kërkoni analizë dhe raport nga databaza…"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    disabled={chatLocked || transcribing || recording}
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
                          aria-label="Modeli ChatGPT"
                          value={model}
                          onChange={(e) => setModel(e.target.value)}
                          disabled={!subscription.connected || chatLocked}
                        >
                          {!models.length && (
                            <option value=""> Abonimi ChatGPT </option>
                          )}
                          {models.map((m) => (
                            <option key={m.id} value={m.model}>
                              {m.displayName}
                            </option>
                          ))}
                        </Select>
                      </span>
                      <span className="composer-divider" />
                      <button
                        type="button"
                        className={`icon-button ${recording ? "recording" : ""}`}
                        aria-label={
                          recording
                            ? "Përfundo regjistrimin"
                            : "Regjistro një mesazh zanor"
                        }
                        onClick={() =>
                          recording
                            ? recorder.current.stop()
                            : void startRecording()
                        }
                        disabled={chatLocked || transcribing}
                      >
                        <Mic size={19} />
                      </button>
                      <button
                        type="button"
                        className={`icon-button ${readReplies ? "on" : ""}`}
                        aria-label="Aktivizo përgjigjet me zë"
                        title="Lexo përgjigjet me zë"
                        onClick={() => setReadReplies(!readReplies)}
                      >
                        <Volume2 size={18} />
                      </button>
                    </div>
                    {chatLocked ? (
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
                          !draft.trim() ||
                          recording ||
                          transcribing
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
                  <button
                    disabled={
                      (chatLocked || transcribing || recording) && !voiceMode
                    }
                    className={voiceMode ? "voice-toggle on" : "voice-toggle"}
                    onClick={() => void toggleVoiceMode()}
                  >
                    <AudioLines size={14} />
                    {voiceMode ? "Zëri është aktiv" : "Fillo bisedën me zë"}
                  </button>
                </div>
                <label className="voice-language">
                  Gjuha e të folurit
                  <Select
                    aria-label="Gjuha e të folurit"
                    value={voiceLanguage}
                    disabled={
                      chatLocked || recording || transcribing || voiceMode
                    }
                    onChange={(e) => setVoiceLanguage(e.target.value)}
                  >
                    <option value="sq">Shqip</option>
                    <option value="en">Anglisht</option>
                    <option value="">Zbulim automatik</option>
                  </Select>
                </label>
                <p className="voice-help">
                  Për bisedë me zë, shtyp “Fillo bisedën me zë” dhe lejo
                  mikrofonin. Për një mesazh të vetëm, përdor ikonën e
                  mikrofonit. Zëri funksionon në localhost ose HTTPS.
                </p>
              </div>
            </main>
            <aside className="context-panel">
              <span className="eyebrow"> KONTEKSTI I HAPËSIRËS </span>
              <h3>
                {" "}
                Përgjigjet e mira <br /> nisin nga konteksti.{" "}
              </h3>
              <p> Bisedat dhe raportet tuaja ruhen së bashku. </p>
              <section className="context-card">
                <div className="context-icon">
                  <Sparkles size={18} />
                </div>
                <strong> Llogaria juaj ChatGPT </strong>
                <p>
                  {subscription.connected
                    ? "Abonimi juaj është gati për bisedën."
                    : "Lidhni llogarinë tuaj për të nisur bisedën."}
                </p>
                <button
                  className="text-button"
                  onClick={() => navigate("connection")}
                >
                  {subscription.connected ? "Menaxho lidhjen" : "Lidh abonimin"}
                  <ArrowRight size={14} />
                </button>
              </section>
              <section className="context-card">
                <div className="context-icon neutral">
                  <Database size={18} />
                </div>
                <strong> Të dhënat e biznesit </strong>
                <Badge
                  good={businessSources.some((s) => s.status === "connected")}
                >
                  {businessSources.some((s) => s.status === "connected")
                    ? "I lidhur"
                    : "Në pritje të lidhjes"}
                </Badge>
                <p>
                  {" "}
                  Pas lidhjes, kërkojini asistentit të zbulojë tabelat, të
                  analizojë të dhënat dhe të krijojë raport. Nuk kërkohet
                  përcaktim manual i dataset-eve.{" "}
                </p>
                <button
                  className="text-button"
                  onClick={() => navigate("sources")}
                >
                  {" "}
                  Shiko burimet e të dhënave <ArrowRight size={14} />
                </button>
              </section>
              <div className="context-tip">
                <span> VAZHDONI BISEDËN </span>
                <p>
                  {" "}
                  “Mund ta shpjegosh?” <br /> “Çfarë të analizoj më pas?” <br />{" "}
                  “Ktheje këtë në raport.”{" "}
                </p>
              </div>
              <div className="context-footer">
                <ShieldCheck size={15} />
                <span>
                  {" "}
                  Kredencialet ruhen në server. <br /> Ju kontrolloni lidhjen
                  tuaj.{" "}
                </span>
              </div>
            </aside>
          </div>
        )}

        {page === "connection" && (
          <main className="page-content">
            <PageHeading
              eyebrow="LLOGARIA DHE ABONIMI JUAJ"
              title="Lidhni llogarinë tuaj ChatGPT."
              text="Përdorni abonimin tuaj ChatGPT për biseda, analiza dhe raporte."
            />
            <section className="connection-card">
              <div className="provider-logo">
                <Sparkles size={28} />
              </div>
              <div>
                <h2> Abonimi ChatGPT </h2>
                <p>
                  {subscription.connected
                    ? subscription.account?.email || "Llogaria juaj ChatGPT"
                    : "Hyni në mënyrë të sigurt përmes OpenAI për të lidhur llogarinë."}
                </p>
                <Badge good={subscription.connected}>
                  {subscription.connected
                    ? `${subscription.account?.planType || "Abonimi"} · I lidhur`
                    : "I palidhur"}
                </Badge>
              </div>
              <button
                className={`button ${subscription.connected ? "outline" : "primary"}`}
                onClick={subscription.connected ? disconnect : connect}
                disabled={connecting || busy}
              >
                {connecting && <LoaderCircle className="spin" size={17} />}{" "}
                {subscription.connected ? "Shkëput llogarinë" : "Lidh ChatGPT"}
              </button>
            </section>
            {!subscription.available && (
              <p className="error-box">
                {errorMessage(subscription.error || "")}
              </p>
            )}
            <div className="info-grid">
              <div className="info-card">
                <ShieldCheck size={21} />
                <h3> Biseda përdor abonimin tuaj </h3>
                <p>
                  {" "}
                  Backend-i përdor Codex CLI zyrtar me hyrjen ChatGPT. Zbatohen
                  kufijtë Codex të abonimit tuaj.{" "}
                </p>
              </div>
              <div className="info-card">
                <AudioLines size={21} />
                <h3> Bisedë me zë </h3>
                <p>
                  {" "}
                  Të folurit transkriptohet lokalisht me Whisper. Pajisja juaj
                  lexon përgjigjet me zë. Mikrofonin mund ta përdorni në
                  localhost ose HTTPS.{" "}
                </p>
              </div>
              <div className="info-card">
                <MessageSquare size={21} />
                <h3> Hapësirë e veçantë bisedash </h3>
                <p>
                  {" "}
                  Kjo hapësirë ruan bisedat e veta. Lidhja e llogarisë nuk
                  importon bisedat ose kujtesën nga ChatGPT.{" "}
                </p>
              </div>
            </div>
            {subscription.connected && (
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
            <p className="footnote">
              {" "}
              Hyrja me kod pajisjeje duhet të aktivizohet në cilësimet e
              sigurisë të ChatGPT ose të lejohet nga administratori.{" "}
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
                          onClick={() => void restoreReport(r)}
                        >
                          <RotateCcw size={15} />
                          Rikthe raportin
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
              text="Lidhni databazat e biznesit për t’i analizuar dhe për të krijuar raporte nga biseda."
              action={
                user.role === "admin" && (
                  <button
                    className="button primary"
                    onClick={() => openSource()}
                  >
                    <Plus size={17} /> Shto burim{" "}
                  </button>
                )
              }
            />
            <div className="notice">
              <Database size={20} />
              <div>
                <strong>
                  {" "}
                  Raporte nga SQL Server me kredenciale private.{" "}
                </strong>
                <p>
                  {" "}
                  Lidhni burimin SQL Server dhe kontrolloni lidhjen. Asistenti
                  zbulon tabelat, analizon të dhënat dhe krijon raporte direkt
                  nga biseda. Dataset-et manuale janë opsionale. Kredencialet
                  mbeten private në backend.{" "}
                </p>
              </div>
            </div>
            {user.role === "admin" ? (
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
                        {s.kind === "sqlserver" && (
                          <button
                            className="button outline small"
                            onClick={() => openSource(s)}
                          >
                            <Settings size={15} /> Konfiguro lidhjen{" "}
                          </button>
                        )}
                        {s.kind === "sqlserver" && (
                          <button
                            className="button outline small"
                            onClick={() => void openSourceAccess(s)}
                          >
                            <ShieldCheck size={15} /> Qasja te burimi{" "}
                          </button>
                        )}
                        {s.kind === "sqlserver" && (
                          <button
                            className="button outline small"
                            disabled={checkingSource === s.id}
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

        {page === "admin" && user.role === "admin" && (
          <main className="page-content">
            <PageHeading
              eyebrow="ADMINISTRIMI I HAPËSIRËS"
              title="Kontrollet e hapësirës tuaj."
              text="Menaxhoni anëtarët, kontrolloni shërbimet dhe ndiqni aktivitetin."
            />
            <div className="tabs">
              {["overview", "users", "activity"].map((t) => (
                <button
                  className={adminTab === t ? "active" : ""}
                  key={t}
                  onClick={() => setAdminTab(t)}
                >
                  {t === "overview"
                    ? "Përmbledhje"
                    : t === "users"
                      ? "Anëtarët dhe qasja"
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
                      <Sparkles size={19} /> Lidhja me abonimin ChatGPT{" "}
                    </span>
                    <Badge good>Codex CLI</Badge>
                  </div>
                  <div className="service-row">
                    <span>
                      <AudioLines size={19} /> Transkriptimi zanor lokal{" "}
                    </span>
                    <Badge good={overview.voice.available}>
                      {overview.voice.available
                        ? `Whisper · ${overview.voice.model}`
                        : "I padisponueshëm"}
                    </Badge>
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
                    <h3> Konfigurimi i SQL Server </h3>
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
                    Kur SQL Server është konfiguruar në .env, backend-i përdor
                    ato vlera për lidhjen. Nuk duhet t’i shkruani përsëri në
                    formular. Nëse .env nuk ka lidhje SQL Server, mund të ruani
                    cilësime private për çdo burim.{" "}
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
                      {source.kind === "sqlserver" && (
                        <button
                          className="button outline small"
                          onClick={() => openSource(source)}
                        >
                          <Settings size={15} /> Konfiguro lidhjen{" "}
                        </button>
                      )}
                      {source.kind === "sqlserver" && (
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
                      Shtoni një burim SQL Server për të kontrolluar
                      lidhjen.{" "}
                    </p>
                  )}
                </section>
                <p className="footnote">
                  {" "}
                  Çdo anëtar lidh abonimin e vet ChatGPT. Administratori nuk
                  sheh kredencialet ChatGPT të anëtarëve të tjerë.{" "}
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
                          <td>{label(u.role)}</td>
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
                  disabled={stoppingReports}
                  onClick={async () => {
                    setStoppingReports(true);
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
                      setStoppingReports(false);
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
                    <Markdown>{s.body}</Markdown>
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
          title="Lidhni llogarinë ChatGPT"
          onClose={() => setLogin(null)}
        >
          <div className="login-steps">
            <span className="provider-logo">
              <Sparkles size={27} />
            </span>
            <p>
              {" "}
              Hapni faqen e hyrjes së OpenAI, hyni në llogari dhe vendosni këtë
              kod njëpërdorimësh.{" "}
            </p>
            <div className="device-code">{login.userCode}</div>
            {login.verificationUrl?.startsWith("https://auth.openai.com/") && (
              <a
                className="button primary wide"
                href={login.verificationUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                {" "}
                Hap hyrjen OpenAI <ArrowRight size={17} />
              </a>
            )}
            <p className="waiting">
              <LoaderCircle size={16} className="spin" /> Në pritje që të
              përfundoni hyrjen…{" "}
            </p>
            <p className="footnote">
              {" "}
              Nëse hyrja me kod pajisjeje është e çaktivizuar, aktivizojeni te
              cilësimet e sigurisë të ChatGPT.{" "}
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
                disabled={chatLocked || recording || transcribing || deleting}
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
                disabled={chatLocked || recording || transcribing || deleting}
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
              disabled={deleting || busy || recording || transcribing}
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
                <option value="member"> Anëtar </option>
                <option value="admin"> Administrator </option>
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
            .filter((member) => member.role !== "admin")
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
          {!users.some((member) => member.role !== "admin") && (
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
              Emri i databazës{" "}
              <input
                name="name"
                required
                maxLength={120}
                defaultValue={editSource?.name || ""}
                placeholder="Databaza e raporteve të biznesit"
              />
            </label>
            <label>
              {" "}
              Lloji i databazës{" "}
              <Select
                name="kind"
                value={sourceKind}
                disabled={!!editSource}
                onChange={(e) => setSourceKind(e.target.value)}
              >
                {["sqlserver", "postgresql", "mysql", "sqlite", "other"].map(
                  (kind) => (
                    <option key={kind} value={kind}>
                      {
                        {
                          sqlserver: "SQL Server",
                          postgresql: "PostgreSQL",
                          mysql: "MySQL",
                          sqlite: "SQLite",
                          other: "Tjetër",
                        }[kind]
                      }
                    </option>
                  ),
                )}
              </Select>
            </label>
            {sourceKind === "sqlserver" && (
              <fieldset className="source-connection-fields">
                <legend> Lidhja SQL Server </legend>
                {environmentActive && (
                  <div className="notice environment-source">
                    <div>
                      <strong>Lidhja përdor .env në server.</strong>
                      <p>
                        Vlerat që janë vendosur janë ngarkuar dhe nuk janë
                        fshirë. Fushat më poshtë tregojnë vetëm gjendjen e
                        konfigurimit; nuk duhet t’i plotësoni përsëri.
                      </p>
                    </div>
                  </div>
                )}
                {!environmentActive &&
                  editSource?.configuration_origin === "saved" && (
                    <p className="footnote">
                      {" "}
                      Vlerat e ruajtura mbeten të fshehura. Lëreni fushën bosh
                      për të mbajtur vlerën aktuale.{" "}
                    </p>
                  )}
                {!environmentActive && (
                  <>
                    <label>
                      SQLSERVER_HOST
                      <input
                        name="SQLSERVER_HOST"
                        disabled={environmentActive}
                        required={
                          !environmentActive &&
                          (!editSource ||
                            editSource.configuration_origin !== "saved")
                        }
                        maxLength={255}
                        autoComplete="off"
                        placeholder={
                          environmentActive
                            ? "Konfiguruar në .env"
                            : "sql.example.internal"
                        }
                      />
                    </label>
                    <label>
                      SQLSERVER_PORT
                      <input
                        name="SQLSERVER_PORT"
                        disabled={environmentActive}
                        type="number"
                        min={1}
                        max={65535}
                        required={
                          !environmentActive &&
                          (!editSource ||
                            editSource.configuration_origin !== "saved")
                        }
                        defaultValue={
                          environmentActive ||
                          editSource?.configuration_origin === "saved"
                            ? ""
                            : "1433"
                        }
                        placeholder={
                          environmentActive ? "Konfiguruar në .env" : "1433"
                        }
                      />
                    </label>
                    <label>
                      SQLSERVER_USER
                      <input
                        name="SQLSERVER_USER"
                        disabled={environmentActive}
                        required={
                          !environmentActive &&
                          (!editSource ||
                            editSource.configuration_origin !== "saved")
                        }
                        maxLength={255}
                        autoComplete="off"
                        placeholder={
                          environmentActive
                            ? "Konfiguruar në .env"
                            : "Përdoruesi i raporteve"
                        }
                      />
                    </label>
                    <label>
                      SQLSERVER_PASSWORD
                      <input
                        name="SQLSERVER_PASSWORD"
                        disabled={environmentActive}
                        type="password"
                        required={
                          !environmentActive &&
                          (!editSource ||
                            editSource.configuration_origin !== "saved")
                        }
                        maxLength={1024}
                        autoComplete="new-password"
                        placeholder={
                          environmentActive
                            ? "Fjalëkalimi ruhet në .env"
                            : editSource?.configuration_origin === "saved"
                              ? "Lëreni bosh për të mbajtur fjalëkalimin"
                              : "Fjalëkalimi i databazës"
                        }
                      />
                    </label>
                    <label>
                      SQLSERVER_DATABASE
                      <input
                        name="SQLSERVER_DATABASE"
                        disabled={environmentActive}
                        required={
                          !environmentActive &&
                          (!editSource ||
                            editSource.configuration_origin !== "saved")
                        }
                        maxLength={128}
                        autoComplete="off"
                        placeholder={
                          environmentActive
                            ? "Konfiguruar në .env"
                            : "Databaza ku do të lidheni"
                        }
                      />
                    </label>
                  </>
                )}
                {environmentActive && (
                  <div className="environment-fields">
                    {[
                      "SQLSERVER_HOST",
                      "SQLSERVER_PORT",
                      "SQLSERVER_USER",
                      "SQLSERVER_PASSWORD",
                      "SQLSERVER_DATABASE",
                    ].map((key) => (
                      <div className="service-row" key={key}>
                        <code>{key}</code>
                        <Badge
                          good={
                            !!overview?.database_configuration.environment[key]
                          }
                        >
                          {overview?.database_configuration.environment[key]
                            ? "Ngarkuar nga .env"
                            : "Mungon në .env"}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
                <p className="footnote">
                  {environmentActive
                    ? "Backend-i i lexon kredencialet privatisht nga .env. Vlerat nuk i dërgohen ChatGPT dhe nuk shfaqen në shfletues. Për ndryshime në .env, rikrijoni container-in."
                    : "Të dhënat e lidhjes ruhen të enkriptuara në backend dhe nuk i dërgohen bisedës. Lëreni bosh një fushë për të mbajtur vlerën e ruajtur."}
                </p>
              </fieldset>
            )}
            {sourceKind !== "sqlserver" && (
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
