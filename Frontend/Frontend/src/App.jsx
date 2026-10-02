import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Cpu,
  Gauge,
  LayoutGrid,
  LoaderCircle,
  LogIn,
  LogOut,
  Moon,
  Network,
  Radio,
  Router,
  Server,
  ShieldCheck,
  Sun,
  Trash2,
  Timer,
  Wifi,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const API_URL = (import.meta.env.VITE_API_URL || "https://caughtin4k.onrender.com").replace(/\/+$/, "");
const DASHBOARD_REFRESH_MS = 10_000;

async function apiFetch(url, options = {}) {
  const token = sessionStorage.getItem("gateway-token");
  const response = await fetch(url, {
    ...options,
    headers: { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    signal: AbortSignal.timeout(60_000),
  });
  if (response.status === 401 && token) {
    sessionStorage.removeItem("gateway-token");
    sessionStorage.removeItem("signal-watch-auth");
    window.location.reload();
    throw new Error("Session expired. Sign in again.");
  }
  return response;
}

const classColors = {
  Benign: "#62d6a7",
  Attack: "#f58c7c",
};

const deviceIcons = [Radio, Router, Server, Wifi, Gauge];

function App() {
  const [theme, setTheme] = useState(
    () => localStorage.getItem("caughtin4k-theme") || "dark",
  );
  const [authenticated, setAuthenticated] = useState(
    () => sessionStorage.getItem("signal-watch-auth") === "true" && Boolean(sessionStorage.getItem("gateway-token")),
  );
  const [username, setUsername] = useState(
    () => sessionStorage.getItem("signal-watch-user") || "",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    localStorage.setItem("caughtin4k-theme", theme);
  }, [theme]);

  const toggleTheme = () => setTheme((current) => current === "dark" ? "light" : "dark");

  if (!authenticated) {
    return (
      <LoginView
        onLogin={(user) => {
          sessionStorage.setItem("signal-watch-auth", "true");
          sessionStorage.setItem("signal-watch-user", user);
          setUsername(user);
          setAuthenticated(true);
        }}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
    );
  }

  return (
    <Dashboard
      username={username}
      theme={theme}
      onToggleTheme={toggleTheme}
      onLogout={() => {
        sessionStorage.clear();
        setAuthenticated(false);
      }}
    />
  );
}

function Dashboard({ username, onLogout, theme, onToggleTheme }) {
  const [view, setView] = useState("devices");
  const [devices, setDevices] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [loginEvents, setLoginEvents] = useState([]);
  const [federatedStatus, setFederatedStatus] = useState(null);
  const [federatedError, setFederatedError] = useState("");
  const [trainingStarting, setTrainingStarting] = useState(false);
  const [selected, setSelected] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [apiReady, setApiReady] = useState(null);

  const loadDevices = async () => {
    const response = await apiFetch(`${API_URL}/devices`);
    if (!response.ok) throw new Error("Could not load devices");
    setDevices((await response.json()).devices);
  };

  const loadAlerts = async () => {
    const response = await apiFetch(`${API_URL}/alerts`);
    if (!response.ok) throw new Error("Could not load alert history");
    setAlerts((await response.json()).detections);
  };

  const loadLoginEvents = async () => {
    const response = await apiFetch(`${API_URL}/login-history`);
    if (!response.ok) throw new Error("Could not load login history");
    setLoginEvents((await response.json()).logins);
  };

  const loadFederatedStatus = async () => {
    try {
      const response = await apiFetch(`${API_URL}/federated-status`);
      if (!response.ok) throw new Error("Could not load federated model status");
      setFederatedStatus(await response.json());
      setFederatedError("");
    } catch (requestError) {
      setFederatedError(requestError.message);
    }
  };

  const startFederatedTraining = async () => {
    setTrainingStarting(true);
    setFederatedError("");
    try {
      const response = await apiFetch(`${API_URL}/federated/train`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not start federated training");
      await loadFederatedStatus();
    } catch (requestError) {
      setFederatedError(requestError.message);
    } finally {
      setTrainingStarting(false);
    }
  };

  useEffect(() => {
    Promise.all([loadDevices(), loadAlerts(), loadLoginEvents(), loadFederatedStatus()])
      .then(() => setApiReady(true))
      .catch((requestError) => {
        setApiReady(false);
        setError(requestError.message);
      });
    const interval = window.setInterval(() => {
      Promise.all([loadDevices(), loadAlerts(), loadFederatedStatus()]).catch((requestError) =>
        setError(requestError.message),
      );
    }, DASHBOARD_REFRESH_MS);
    return () => window.clearInterval(interval);
  }, []);

  const runDetection = async (device) => {
    setSelected(device);
    setResult(null);
    setLoading(true);
    setError("");
    try {
      const response = await apiFetch(`${API_URL}/detect/${device.device_id}`);
      if (!response.ok) throw new Error("Detection request failed");
      setResult(await response.json());
      await loadAlerts();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  const chartData = useMemo(() => {
    const counts = Object.fromEntries(
      Object.keys(classColors).map((label) => [label, 0]),
    );
    alerts.forEach(({ label }) => {
      counts[label] = (counts[label] || 0) + 1;
    });
    return Object.entries(counts).map(([label, count]) => ({ label, count }));
  }, [alerts]);

  return (
    <main className="app-shell site-shell min-h-screen overflow-hidden bg-[#07111f] text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-[1440px] flex-col px-5 py-5 sm:px-8 lg:px-12">
        <header className="app-header flex items-center justify-between border-b border-white/10 pb-5">
          <button
            className="brand-lockup flex items-center gap-3 text-left"
            onClick={() => setView("devices")}
          >
            <img
              className="brand-logo"
              src="/caughtIn4k_logo.png"
              alt="caughtIn4K"
            />
            <span>
              <strong className="block font-display text-lg">caughtIn4K</strong>
              <small className="text-xs text-slate-400">
                IoT security intelligence
              </small>
            </span>
          </button>
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
            <span className="hidden items-center gap-2 sm:flex">
              <span
                className={`h-2 w-2 rounded-full ${apiReady === false ? "bg-[#f58c7c]" : apiReady === true ? "bg-[#62d6a7] shadow-[0_0_12px_#62d6a7]" : "animate-pulse bg-[#f7b955]"}`}
              />{" "}
              {apiReady === false
                ? "API unavailable"
                : apiReady === true
                  ? "API connected"
                  : "Connecting API"}
            </span>
            <span className="hidden md:inline">{username}</span>
            <button
              className="flex items-center gap-1 text-[#f58c7c]"
              onClick={onLogout}
            >
              <LogOut size={14} /> Sign out
            </button>
          </div>
        </header>

        <section className="flex flex-1 flex-col py-10 lg:flex-row lg:gap-16">
          <aside className="app-sidebar mb-10 shrink-0 lg:mb-0 lg:w-60">
            <p className="mb-5 text-[11px] font-semibold uppercase tracking-[0.22em] text-[#62d6a7]">
              Security intelligence
            </p>
            <h1 className="max-w-xs font-display text-4xl leading-[0.95] tracking-tight text-white sm:text-5xl">
              Know your exposure.
            </h1>
            <p className="mt-5 max-w-xs text-sm leading-6 text-slate-400">
              A shared view for security leaders and engineering teams to
              understand IoT risk, validate model decisions, and respond with
              evidence.
            </p>
            <nav className="mt-10 space-y-2">
              <NavButton
                active={view === "devices"}
                icon={<LayoutGrid size={17} />}
                onClick={() => setView("devices")}
              >
                Operations
              </NavButton>
              <NavButton
                active={view === "alerts"}
                icon={<AlertTriangle size={17} />}
                onClick={() => {
                  setView("alerts");
                  loadAlerts();
                }}
              >
                Detection history{" "}
                <span className="ml-auto rounded-full bg-white/10 px-2 py-0.5 text-[10px]">
                  {alerts.length}
                </span>
              </NavButton>
              <NavButton
                active={view === "logins"}
                icon={<LogIn size={17} />}
                onClick={() => {
                  setView("logins");
                  loadLoginEvents();
                }}
              >
                Access audit
              </NavButton>
              <NavButton
                active={view === "federated"}
                icon={<Network size={17} />}
                onClick={() => {
                  setView("federated");
                  loadFederatedStatus();
                }}
              >
                Federated model
              </NavButton>
            </nav>
          </aside>

          <div className="app-content min-w-0 flex-1">
            {error && (
              <div className="mb-5 flex items-center gap-2 border border-[#f58c7c]/30 bg-[#f58c7c]/10 px-4 py-3 text-sm text-[#ffb4a8]">
                <AlertTriangle size={16} /> {error}
              </div>
            )}
            <div key={view} className="view-enter">
              {view === "devices" ? (
                <DevicesView
                  devices={devices}
                  alerts={alerts}
                  federatedStatus={federatedStatus}
                  onAdded={loadDevices}
                />
              ) : view === "alerts" ? (
                <AlertsView alerts={alerts} chartData={chartData} />
              ) : view === "logins" ? (
                <LoginHistoryView events={loginEvents} />
              ) : (
                <FederatedView
                  status={federatedStatus}
                  error={federatedError}
                  onStartTraining={startFederatedTraining}
                  trainingStarting={trainingStarting}
                />
              )}
            </div>
          </div>
        </section>
        <footer className="flex justify-between border-t border-white/10 py-4 text-[11px] text-slate-500">
          <span>GHOST-1D-GRU / EA-NGO</span>
          <span>SECURITY OPERATIONS PLATFORM</span>
        </footer>
      </div>
    </main>
  );
}

function FederatedView({ status, error, onStartTraining, trainingStarting }) {
  const participants = status?.participants || [];
  const updatedAt = status?.updated_at
    ? new Date(status.updated_at).toLocaleString()
    : "Not reported";
  const ready = status?.status === "federated";
  const training = status?.training;
  const trainingActive = training?.state === "running" || trainingStarting;

  return (
    <div>
      <div className="mb-8">
        <p className="text-sm text-slate-400">Training coordination</p>
        <h2 className="mt-1 font-display text-3xl tracking-tight">Federated model</h2>
      </div>
      {error && (
        <div className="mb-5 flex items-center gap-2 border border-[#f58c7c]/30 bg-[#f58c7c]/10 px-4 py-3 text-sm text-[#ffb4a8]">
          <AlertTriangle size={16} /> {error}
        </div>
      )}
      <section className="surface-panel border border-white/10 bg-[#0d1b2b] p-5 sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-white/10 pb-5">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center bg-[#132b39] text-[#62d6a7]">
              <Network size={21} />
            </span>
            <div>
              <p className="font-display text-xl">GHOST-1D-GRU</p>
              <p className="text-xs text-slate-400">Global intrusion detection model</p>
            </div>
          </div>
          <span className={`text-xs font-semibold uppercase ${ready ? "text-[#62d6a7]" : "text-[#f7b955]"}`}>
            {status ? (ready ? "Federated checkpoint" : "Pretrained checkpoint") : "Status unavailable"}
          </span>
        </div>
        {status ? (
          <>
            <div className="grid gap-4 py-5 sm:grid-cols-2 xl:grid-cols-4">
              <Metric label="Aggregation" value={status.aggregation || "—"} />
              <Metric label="Completed round" value={status.federated_round ?? "—"} />
              <Metric label="Training clients" value={status.federated_clients ?? "—"} />
              <Metric label="Input features" value={status.feature_count ?? "—"} />
            </div>
            <p className="border-t border-white/10 pt-4 text-xs text-slate-400">
              Checkpoint saved {updatedAt}. Laptop coordinates and trains locally; Raspberry Pi trains locally and runs the gateway IDS. Neither is an IoT device entry.
            </p>
            <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-white">
                  Training {training?.state || "idle"}
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  Round {training?.current_round ?? 0} of {training?.total_rounds ?? 10}
                </p>
              </div>
              <button
                type="button"
                disabled={trainingActive}
                onClick={onStartTraining}
                className="inline-flex items-center gap-2 bg-[#62d6a7] px-4 py-3 text-sm font-semibold text-[#07111f] disabled:cursor-wait disabled:opacity-60"
              >
                {trainingStarting ? <LoaderCircle size={16} className="animate-spin" /> : <Network size={16} />}
                {trainingStarting ? "Starting…" : training?.state === "running" ? "Training in progress" : "Update global model"}
              </button>
            </div>
          </>
        ) : !error ? (
          <p className="py-8 text-sm text-slate-400">Loading checkpoint metadata…</p>
        ) : null}
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {participants.map((participant) => (
            <div key={participant.role} className="border border-white/10 px-4 py-4">
              <p className="text-sm font-semibold text-white">{participant.role}</p>
              <p className="mt-1 text-xs leading-5 text-slate-400">{participant.function}</p>
              <p className="mt-3 text-[10px] uppercase tracking-widest text-[#62d6a7]">Training participant</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function LoginView({ onLogin, theme, onToggleTheme }) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await apiFetch(
        `${API_URL}/${creating ? "signup" : "login"}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            creating
              ? { name, email: username, password }
              : { username, password },
          ),
        },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Login failed");
      if (!data.access_token) throw new Error("Update the backend to support gateway sessions.");
      sessionStorage.setItem("gateway-token", data.access_token);
      onLogin(data.username);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="login-shell grid min-h-screen place-items-center bg-[#07111f] px-5 text-slate-100">
      <form
        onSubmit={submit}
        className="login-panel w-full max-w-md border border-white/10 bg-[#0d1b2b] p-7 shadow-2xl sm:p-9"
      >
        <div className="mb-8 flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-[#62d6a7] text-[#07111f]">
              <ShieldCheck size={23} />
            </span>
            <span>
              <strong className="block font-display text-xl">caughtIn4K</strong>
              <small className="text-xs text-slate-400">
                IoT security operations
              </small>
            </span>
          </div>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
        <p className="text-sm text-[#62d6a7]">
          {creating ? "Create shared account" : "Authorized access"}
        </p>
        <h1 className="mt-2 font-display text-3xl tracking-tight">
          {creating ? "Create an account" : "Sign in to continue"}
        </h1>
        {creating && (
          <label className="mt-8 block text-xs uppercase tracking-widest text-slate-400">
            Name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="mt-2 w-full border border-white/10 bg-white/[0.04] px-3 py-3 text-sm outline-none focus:border-[#62d6a7]"
              required
            />
          </label>
        )}
        <label
          className={`${creating ? "mt-5" : "mt-8"} block text-xs uppercase tracking-widest text-slate-400`}
        >
          Email
          <input
            type="email"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className="mt-2 w-full border border-white/10 bg-white/[0.04] px-3 py-3 text-sm outline-none focus:border-[#62d6a7]"
            required
          />
        </label>
        <label className="mt-5 block text-xs uppercase tracking-widest text-slate-400">
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-2 w-full border border-white/10 bg-white/[0.04] px-3 py-3 text-sm outline-none focus:border-[#62d6a7]"
            required
          />
        </label>
        {error && <p className="mt-4 text-sm text-[#f58c7c]">{error}</p>}
        <button
          disabled={loading}
          className="mt-7 flex w-full items-center justify-center gap-2 bg-[#62d6a7] px-4 py-3 text-sm font-semibold text-[#07111f] disabled:opacity-60"
        >
          <LogIn size={17} />
          {loading
            ? "Working..."
            : creating
              ? "Create account"
              : "Enter control room"}
        </button>
        <button
          type="button"
          onClick={() => {
            setCreating(!creating);
            setError("");
          }}
          className="mt-4 w-full text-sm text-slate-400 hover:text-white"
        >
          {creating
            ? "Already have an account? Sign in"
            : "New here? Create an account"}
        </button>
      </form>
    </main>
  );
}

function LoginHistoryView({ events }) {
  return (
    <div>
      <div className="mb-8">
        <p className="text-sm text-slate-400">Access audit</p>
        <h2 className="mt-1 font-display text-3xl tracking-tight">
          Login history
        </h2>
      </div>
      <section className="overflow-hidden border border-white/10 bg-[#0d1b2b]">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-sm">
            <thead className="border-b border-white/10 text-[10px] uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-5 py-4 font-medium">Username</th>
                <th className="px-5 py-4 font-medium">Result</th>
                <th className="px-5 py-4 font-medium">IP address</th>
                <th className="px-5 py-4 font-medium">Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event, index) => (
                <tr
                  key={`${event.timestamp}-${index}`}
                  className="border-b border-white/5"
                >
                  <td className="px-5 py-4">{event.username}</td>
                  <td
                    className={`px-5 py-4 ${event.success ? "text-[#62d6a7]" : "text-[#f58c7c]"}`}
                  >
                    {event.success ? "Successful" : "Failed"}
                  </td>
                  <td className="px-5 py-4 font-mono text-xs text-slate-500">
                    {event.ip_address || "—"}
                  </td>
                  <td className="px-5 py-4 text-xs text-slate-400">
                    {event.timestamp}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {events.length === 0 && (
            <p className="px-5 py-8 text-sm text-slate-500">
              No login events recorded.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function NavButton({ active, icon, children, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left text-sm transition ${active ? "bg-white/10 text-white" : "text-slate-400 hover:bg-white/5 hover:text-white"}`}
    >
      {icon}
      {children}
    </button>
  );
}

function ThemeToggle({ theme, onToggle }) {
  const nextTheme = theme === "dark" ? "light" : "dark";
  const Icon = theme === "dark" ? Sun : Moon;
  return (
    <button
      type="button"
      className="theme-toggle inline-flex h-9 w-9 items-center justify-center border border-white/10 text-slate-300 transition hover:bg-white/10 hover:text-white"
      onClick={onToggle}
      aria-label={`Switch to ${nextTheme} mode`}
      title={`Switch to ${nextTheme} mode`}
    >
      <Icon size={17} />
    </button>
  );
}

function DevicesView({ devices, alerts, federatedStatus, onAdded }) {
  const [removeError, setRemoveError] = useState("");
  const setBlocked = async (device) => {
    setRemoveError("");
    const action =
      device.blocked || device.status === "BLOCKED" ? "unblock" : "block";
    try {
      const response = await apiFetch(
        `${API_URL}/devices/${encodeURIComponent(device.mac)}/${action}`,
        { method: "POST" },
      );
      const data = await response.json();
      if (!response.ok || data.success !== true)
        throw new Error(data.detail || `Could not ${action} device`);
      await onAdded();
    } catch (requestError) {
      setRemoveError(requestError.message);
    }
  };
  const removeDevice = async (device) => {
    if (!window.confirm(`Remove ${device.name} from caughtIn4K?`)) return;
    setRemoveError("");
    try {
      const response = await apiFetch(
        `${API_URL}/devices/${encodeURIComponent(device.mac)}`,
        { method: "DELETE" },
      );
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.detail || "Could not remove device");
      await onAdded();
    } catch (requestError) {
      setRemoveError(requestError.message);
    }
  };
  const modelRound = federatedStatus?.federated_round;
  const modelValue = modelRound ? `Round ${modelRound}` : federatedStatus ? "Pretrained" : "Unavailable";
  const modelDetail = federatedStatus
    ? `${federatedStatus.aggregation} · ${federatedStatus.federated_clients ?? 0} clients`
    : "Checkpoint status unavailable";
  return (
    <div>
      <div className="mb-8 flex items-end justify-between gap-4">
        <div>
          <p className="text-sm text-slate-400">Live router telemetry</p>
          <h2 className="mt-1 font-display text-3xl tracking-tight">
            IoT network
          </h2>
        </div>
        <div className="hidden items-center gap-2 rounded-full border border-white/10 px-3 py-2 text-xs text-slate-400 sm:flex">
          <Wifi size={14} className="text-[#62d6a7]" /> {devices.length} device
          monitored
        </div>
      </div>
      <div className="mb-8 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatusMetric
          icon={<Wifi size={16} />}
          label="Live devices"
          value={devices.length}
          detail="Router connection"
        />
        <StatusMetric
          icon={<AlertTriangle size={16} />}
          label="Recent events"
          value={alerts.length}
          detail="Open detection history"
        />
        <StatusMetric
          icon={<Cpu size={16} />}
          label="Global model"
          value={modelValue}
          detail={modelDetail}
        />
        <StatusMetric
          icon={<Timer size={16} />}
          label="Refresh rate"
          value="10s"
          detail="Sender telemetry cadence"
        />
      </div>
      <AddDevicePanel onAdded={onAdded} />
      {removeError && (
        <p className="mb-4 text-sm text-[#f58c7c]" role="alert">{removeError}</p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {devices.map((device) => (
          <DeviceCard
            key={device.device_id}
            device={device}
            onSetBlocked={setBlocked}
            onRemove={removeDevice}
          />
        ))}
      </div>
    </div>
  );
}

function AddDevicePanel({ onAdded }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [mac, setMac] = useState("");
  const [ip, setIp] = useState("");
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    setError("");
    try {
      const response = await apiFetch(`${API_URL}/devices/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, mac: mac.toLowerCase(), ip_address: ip }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.detail || "Device registration failed");
      setOpen(false);
      setName("");
      setMac("");
      setIp("");
      onAdded();
    } catch (requestError) {
      setError(requestError.message);
    }
  };
  return (
    <section className="mb-6 border border-white/10 bg-[#0d1b2b] p-5">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-sm font-semibold text-[#62d6a7]"
      >
        <Wifi size={16} /> {open ? "Close device form" : "Add device"}
      </button>
      {open && (
        <form onSubmit={submit} className="mt-5 grid gap-3 sm:grid-cols-4">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Device name"
            className="border border-white/10 bg-white/[0.04] px-3 py-2 text-sm"
            required
          />
          <input
            value={mac}
            onChange={(event) => setMac(event.target.value)}
            placeholder="aa:bb:cc:dd:ee:ff"
            pattern="^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$"
            className="border border-white/10 bg-white/[0.04] px-3 py-2 text-sm"
            required
          />
          <input
            value={ip}
            onChange={(event) => setIp(event.target.value)}
            placeholder="IP address (optional)"
            className="border border-white/10 bg-white/[0.04] px-3 py-2 text-sm"
          />
          <button className="bg-[#62d6a7] px-3 py-2 text-sm font-semibold text-[#07111f]">
            Register device
          </button>
          {error && (
            <p className="text-sm text-[#f58c7c] sm:col-span-4">{error}</p>
          )}
        </form>
      )}
    </section>
  );
}

function StatusMetric({ icon, label, value, detail }) {
  return (
    <div className="border border-white/10 bg-white/[0.035] p-4">
      <div className="flex items-center gap-2 text-[#62d6a7]">
        {icon}
        <span className="text-[10px] uppercase tracking-widest text-slate-500">
          {label}
        </span>
      </div>
      <p className="mt-3 font-display text-2xl text-white">{value}</p>
      <p className="mt-1 text-xs text-slate-500">{detail}</p>
    </div>
  );
}

function DeviceCard({ device, onSetBlocked, onRemove }) {
  const DeviceIcon = deviceIcons[device.class_index % deviceIcons.length];
  const attack = Number(device.attack_probability || 0);
  const isThreat = ["WARNING", "ALERT", "BLOCKED"].includes(device.status);
  return (
    <article className="group border border-white/10 bg-[#0d1b2b] p-5 transition duration-300 hover:-translate-y-1 hover:border-[#62d6a7]/50">
      <div className="mb-7 flex items-start justify-between">
        <span className="grid h-11 w-11 place-items-center rounded-lg bg-[#132b39] text-[#62d6a7]">
          <DeviceIcon size={21} />
        </span>
        <span
          className={`flex items-center gap-1.5 text-[10px] uppercase tracking-widest ${isThreat ? "text-[#f58c7c]" : "text-[#62d6a7]"}`}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-current" />{" "}
          {device.status || "SAFE"}
        </span>
      </div>
      <p className="font-display text-xl">{device.name}</p>
      <p className="mt-1 font-mono text-xs text-slate-500">
        {device.mac || device.device_id}
      </p>
      <div className="mt-6 grid grid-cols-2 gap-3 border-t border-white/10 pt-4 text-xs">
        <Metric label="Prediction" value={device.prediction || "Benign"} />
        <Metric label="Attack probability" value={`${attack.toFixed(2)}%`} />
        <Metric label="IP address" value={device.ip_address || "—"} />
        <Metric
          label="Last seen"
          value={
            device.last_seen
              ? new Date(device.last_seen * 1000).toLocaleTimeString()
              : "—"
          }
        />
      </div>
      <button
        onClick={() => onSetBlocked(device)}
        className={`mt-5 w-full px-4 py-3 text-sm font-semibold transition ${device.blocked || device.status === "BLOCKED" ? "bg-[#62d6a7] text-[#07111f]" : "border border-[#f58c7c]/50 text-[#f58c7c] hover:bg-[#f58c7c]/10"}`}
      >
        {device.blocked || device.status === "BLOCKED"
          ? "Unblock device"
          : "Block device"}
      </button>
      <button
        type="button"
        onClick={() => onRemove(device)}
        className="mt-2 inline-flex w-full items-center justify-center gap-2 border border-white/10 px-4 py-2 text-xs text-slate-400 transition hover:border-[#f58c7c]/50 hover:text-[#f58c7c]"
      >
        <Trash2 size={14} /> Remove device
      </button>
    </article>
  );
}

function DetectionPanel({ selected, result, loading }) {
  if (!selected)
    return (
      <div className="mt-10 border border-dashed border-white/15 px-6 py-10 text-center text-sm text-slate-500">
        <Activity className="mx-auto mb-3 text-slate-600" size={22} />
        Select a device to run an intrusion detection scan.
      </div>
    );
  return (
    <section className="mt-10 border border-white/10 bg-[#0d1b2b] p-5 sm:p-7">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-[#62d6a7]">
            Latest scan
          </p>
          <h3 className="mt-1 font-display text-2xl">{selected.name}</h3>
        </div>
        <span className="font-mono text-xs text-slate-500">
          {selected.device_id}
        </span>
      </div>
      {loading ? (
        <div className="flex items-center gap-3 py-8 text-sm text-slate-400">
          <LoaderCircle className="animate-spin text-[#62d6a7]" size={19} />{" "}
          Classifying traffic sample...
        </div>
      ) : result ? (
        <ResultCard result={result} />
      ) : null}
    </section>
  );
}

function ResultCard({ result }) {
  const breakdown = Object.entries(result.class_probabilities || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3);
  const isNormal = result.label === "Benign";
  const modelSize = result.model_size_bytes
    ? `${(result.model_size_bytes / 1024).toFixed(1)} KB`
    : "Unavailable";
  return (
    <div>
      <div className="grid gap-5 md:grid-cols-[1fr_1fr]">
        <div
          className={`border-l-2 pl-4 ${isNormal ? "border-[#62d6a7]" : "border-[#f58c7c]"}`}
        >
          <p className="text-xs text-slate-400">Predicted attack type</p>
          <p
            className={`mt-2 font-display text-3xl ${isNormal ? "text-[#62d6a7]" : "text-[#f58c7c]"}`}
          >
            {result.label}
          </p>
          <div className="mt-5 flex items-center justify-between text-xs">
            <span className="text-slate-400">Confidence</span>
            <strong>{(result.confidence * 100).toFixed(1)}%</strong>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10">
            <div
              className={`h-full rounded-full transition-all ${isNormal ? "bg-[#62d6a7]" : "bg-[#f58c7c]"}`}
              style={{ width: `${result.confidence * 100}%` }}
            />
          </div>
        </div>
        <div>
          <p className="mb-3 text-xs text-slate-400">Top class breakdown</p>
          {breakdown.map(([label, probability]) => (
            <div key={label} className="mb-3">
              <div className="mb-1 flex justify-between text-xs">
                <span>{label}</span>
                <span className="text-slate-400">
                  {(probability * 100).toFixed(1)}%
                </span>
              </div>
              <div className="h-1.5 bg-white/10">
                <div
                  className="h-full"
                  style={{
                    width: `${probability * 100}%`,
                    backgroundColor: classColors[label],
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="mt-6 grid gap-3 border-t border-white/10 pt-4 sm:grid-cols-2">
        <Metric
          label="Inference latency"
          value={`${result.inference_latency_ms ?? "—"} ms`}
        />
        <Metric label="Model size" value={modelSize} />
      </div>
      <div
        className={`mt-4 flex items-center gap-2 text-xs ${isNormal ? "text-[#62d6a7]" : "text-[#f58c7c]"}`}
      >
        <CheckCircle2 size={15} /> Detection recorded in alert history
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="border border-white/10 bg-white/[0.03] px-3 py-2">
      <p className="text-[10px] uppercase tracking-widest text-slate-500">
        {label}
      </p>
      <p className="mt-1 font-mono text-sm text-slate-200">{value}</p>
    </div>
  );
}

function AlertsView({ alerts, chartData }) {
  return (
    <div>
      <div className="mb-8">
        <p className="text-sm text-slate-400">Historical telemetry</p>
        <h2 className="mt-1 font-display text-3xl tracking-tight">
          Alerts & history
        </h2>
      </div>
      <div className="mb-5 grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
        <section className="border border-white/10 bg-[#0d1b2b] p-5">
          <div className="mb-3 flex justify-between">
            <h3 className="font-display text-lg">Attack type counts</h3>
            <span className="text-xs text-slate-500">All detections</span>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                margin={{ top: 10, right: 5, left: -20, bottom: 0 }}
              >
                <CartesianGrid stroke="#ffffff12" vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fill: "#94a3b8", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    background: "#132237",
                    border: "1px solid #ffffff1a",
                    color: "#fff",
                    fontSize: 12,
                  }}
                  cursor={{ fill: "#ffffff08" }}
                />
                <Bar dataKey="count" fill="#62d6a7" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
        <div className="border border-white/10 bg-[#0d1b2b] p-5">
          <p className="text-xs uppercase tracking-widest text-[#62d6a7]">
            Activity pulse
          </p>
          <p className="mt-3 font-display text-5xl">{alerts.length}</p>
          <p className="mt-2 text-sm text-slate-400">detections recorded</p>
          <div className="mt-10 border-t border-white/10 pt-4 text-xs text-slate-500">
            Newest events appear first
          </div>
        </div>
      </div>
      <section className="overflow-hidden border border-white/10 bg-[#0d1b2b]">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-sm">
            <thead className="border-b border-white/10 text-[10px] uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-5 py-4 font-medium">Device</th>
                <th className="px-5 py-4 font-medium">Classification</th>
                <th className="px-5 py-4 font-medium">Confidence</th>
                <th className="px-5 py-4 font-medium">Timestamp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {alerts.map((alert, index) => (
                <tr
                  key={`${alert.timestamp}-${index}`}
                  className="text-slate-300"
                >
                  <td className="px-5 py-4 font-mono text-xs">
                    {alert.device_id}
                  </td>
                  <td className="px-5 py-4">
                    <span className="inline-flex items-center gap-2">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: classColors[alert.label] }}
                      />
                      {alert.label}
                    </span>
                  </td>
                  <td className="px-5 py-4">
                    {(alert.confidence * 100).toFixed(1)}%
                  </td>
                  <td className="px-5 py-4 text-xs text-slate-500">
                    {new Date(alert.timestamp).toLocaleString()}
                  </td>
                </tr>
              ))}
              {alerts.length === 0 && (
                <tr>
                  <td
                    colSpan="4"
                    className="px-5 py-12 text-center text-slate-500"
                  >
                    No detections have been recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default App;
