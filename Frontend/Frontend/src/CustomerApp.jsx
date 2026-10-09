import { useEffect, useRef, useState } from "react";
import { CloudClient, LiveAlertTracker, recentWarnings, snapshotStale, trainingReady } from "./cloud-client";
import { CustomerDeviceCard, DashboardHeader, DashboardMetrics, DashboardSidebar, DetectionHistory, SecurityIntro } from "./customer-dashboard";
import { parseSetupLabel } from "./setup-label";
import "./customer.css";

export default function CustomerApp() {
  const [cloud] = useState(() => new CloudClient(import.meta.env.VITE_CLOUD_API_URL || "https://caughtin4k-1.onrender.com"));
  const [account, setAccount] = useState(cloud.account);
  const [home, setHome] = useState(null);
  const [homes, setHomes] = useState([]);
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState("");
  const [syncError, setSyncError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [signup, setSignup] = useState(false);
  const [recovery, setRecovery] = useState(false);
  const [tick, setTick] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [tab, setTab] = useState("Home");
  const [light, setLight] = useState(() => localStorage.getItem("customer-theme") === "light");
  const [notifications, setNotifications] = useState(false);
  const [liveAlerts, setLiveAlerts] = useState([]);
  const [notificationError, setNotificationError] = useState("");
  const alertTracker = useRef(new LiveAlertTracker());
  const notificationsRef = useRef(false);
  const openNotifications = useRef(new Set());
  const mounted = useRef(true);
  const running = useRef(false);
  const choosingHome = useRef(false);
  useEffect(() => { mounted.current = true; return () => {
    mounted.current = false;
    for (const notification of openNotifications.current) notification.close();
    openNotifications.current.clear();
  }; }, []);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 2000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.customerTheme = light ? "light" : "dark";
    document.documentElement.dataset.theme = light ? "light" : "dark";
    localStorage.setItem("customer-theme", light ? "light" : "dark");
  }, [light]);
  useEffect(() => {
    const enabled = Boolean(account && sessionStorage.getItem(`customer-notifications:${account.account_id}`) === "true");
    notificationsRef.current = enabled;
    setNotifications(enabled);
  }, [account?.account_id]);

  async function toggleNotifications() {
    setNotificationError("");
    if (notifications) {
      notificationsRef.current = false; setNotifications(false);
      for (const notification of openNotifications.current) notification.close();
      openNotifications.current.clear();
      sessionStorage.removeItem(`customer-notifications:${account.account_id}`);
      return;
    }
    if (!("Notification" in window)) throw new Error("This browser does not support desktop notifications. Live alerts remain visible on Home.");
    if (await Notification.requestPermission() !== "granted") throw new Error("Notifications were not allowed. Enable them in your browser's site settings.");
    notificationsRef.current = true; setNotifications(true);
    sessionStorage.setItem(`customer-notifications:${account.account_id}`, "true");
    setMessage("Live browser notifications enabled while this website is open. Closed-browser push is not enabled.");
  }

  function logout() {
    choosingHome.current = false;
    notificationsRef.current = false;
    for (const notification of openNotifications.current) notification.close();
    openNotifications.current.clear();
    alertTracker.current.reset(); setLiveAlerts([]);
    cloud.logout(); setAccount(null); setHome(null); setHomes([]); setSnapshot(null); setError(""); setSyncError(""); setNotificationError(""); setMessage(""); setTab("Home");
  }

  async function run(action) {
    if (running.current) return;
    running.current = true;
    setBusy(true); setError(""); setMessage("");
    try { await action(); }
    catch (failure) { if (mounted.current) setError(failure.message); }
    finally { running.current = false; if (mounted.current) setBusy(false); }
  }

  function choose(choice) {
    choosingHome.current = false;
    alertTracker.current.reset(); setLiveAlerts([]);
    for (const notification of openNotifications.current) notification.close();
    openNotifications.current.clear();
    cloud.select(choice); setHome(choice); setSnapshot(null); setError(""); setSyncError(""); setMessage(""); setTab("Home");
  }

  function manageHomes() {
    choosingHome.current = true;
    cloud.select(null);
    alertTracker.current.reset(); setLiveAlerts([]);
    for (const notification of openNotifications.current) notification.close();
    openNotifications.current.clear();
    setHome(null); setSnapshot(null); setSyncError(""); setError(""); setMessage(""); setTab("Home");
  }

  useEffect(() => {
    if (!account?.email_verified || home) return;
    let active = true;
    cloud.homes().then((choices) => {
      if (!active) return;
      setHomes(choices);
      if (choices.length === 1 && !choosingHome.current) choose(choices[0]);
    }).catch((failure) => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [account, home, tick]);

  useEffect(() => {
    if (!home) return;
    let active = true;
    let fetching = false;
    const refresh = async () => {
      if (fetching) return;
      fetching = true;
      try {
        const data = await cloud.snapshot();
        if (active) {
          setSnapshot(data); setSyncError("");
          const alerts = alertTracker.current.update(data);
          if (alerts.length) {
            setLiveAlerts(previous => [...alerts, ...previous].slice(0, 20));
            if (notificationsRef.current && "Notification" in window && Notification.permission === "granted") {
              try {
                for (const event of alerts) {
                  const version = cloud.generation;
                  const notification = new Notification(`caughtIn4K: ${event.status}`, {
                    body: "A threat event was reported by your home gateway. Open Activity for details.",
                    tag: `${home.gateway_id}:${event.event_id}:${event.timestamp}`,
                  });
                  notification.onclick = () => {
                    if (mounted.current && version === cloud.generation) { window.focus(); setTab("Activity"); }
                    notification.close();
                  };
                  openNotifications.current.add(notification);
                  setTimeout(() => { notification.close(); openNotifications.current.delete(notification); }, 10_000);
                }
              } catch (failure) {
                console.error("Browser notification display failed:", failure.name);
                notificationsRef.current = false; setNotifications(false);
                sessionStorage.removeItem(`customer-notifications:${account.account_id}`);
                setNotificationError("This browser could not display a notification. Live alerts remain on Home and Activity; desktop notifications have been disabled.");
              }
            }
          }
        }
      } catch (failure) { if (active) setSyncError(failure.message); }
      finally { fetching = false; }
    };
    refresh();
    const timer = setInterval(refresh, 2000);
    window.addEventListener("focus", refresh);
    return () => { active = false; clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [home]);

  const checkedAt = Math.max(now, Date.now());
  const stale = snapshotStale(snapshot, checkedAt) || Boolean(syncError);
  const canControl = ["owner", "admin"].includes(home?.role);
  const warnings = recentWarnings(snapshot, checkedAt);
  const federated = snapshot?.model?.federated;
  const training = federated?.training;
  const trainEnabled = !stale && trainingReady(snapshot, checkedAt);
  const commandSuccess = action => action === "train"
    ? "Your Pi confirmed the laptop accepted training startup. Watch round progress below; this is not completion."
    : action === "register" ? "Device added on your Pi. It may take up to 30 seconds to appear."
    : "Your Pi confirmed the device action.";
  const checkCommand = async () => {
    const result = await cloud.commandStatus();
    setMessage(result.status === "succeeded" ? commandSuccess(result.action)
      : `Command: ${result.status}. Check before retrying; no start has been replayed.`);
    if (result.status === "succeeded") setSnapshot(await cloud.snapshot());
  };
  function values(event) { event.preventDefault(); return Object.fromEntries(new FormData(event.currentTarget)); }

  async function control(device) {
    const action = device.blocked ? "unblock" : "block";
    if (!window.confirm(`${action.toUpperCase()} ${device.name} (${device.mac})?\nBlocking your current phone can disconnect it. Keep another connection available.`)) return;
    await run(() => execute(device.mac, action));
  }

  async function execute(mac, action, details = {}) {
      const version = cloud.generation;
      await cloud.submit(mac, action, details);
      setMessage("Command queued. Waiting for the Pi—not yet confirmed.");
      const deadline = Date.now() + 150_000;
      while (Date.now() < deadline) {
        if (version !== cloud.generation) throw new Error("Account changed; check the command before retrying.");
        const result = await cloud.commandStatus();
        if (result.status === "succeeded") {
          setMessage(commandSuccess(action));
          setSnapshot(await cloud.snapshot());
          return;
        }
        if (!["queued", "delivered"].includes(result.status)) {
          throw new Error(`Command not confirmed: ${result.status}. Check ${action === "train" ? "training" : "device"} state before retrying.`);
        }
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
      throw new Error("Timed out. Check command status before retrying.");
  }

  return <main className={`customer-app ${home ? "site-shell" : "login-shell"}`}>
    <DashboardHeader account={account} light={light} onTheme={() => setLight(value => !value)}
      onLogout={logout} busy={busy} connected={!stale && Boolean(home)} />
    {error && <p role="alert" className="customer-error">{error}</p>}
    {syncError && <p role="alert" className="customer-error">Live updates: {syncError}</p>}
    {notificationError && <p role="alert" className="customer-error">{notificationError}</p>}
    {message && <p role="status">{message}</p>}
    {!account ? <div className="login-layout"><SecurityIntro /><section className="customer-panel customer-login login-panel">
      <p className="dashboard-eyebrow">{signup ? "Create your secure home account" : "Authorized access"}</p>
      <h2>{recovery ? "Recover your account" : signup ? "Create an account" : "Sign in"}</h2>
      <form onSubmit={(event) => {
        const data = values(event);
        run(async () => {
          if (recovery) {
            await cloud.request("POST", "/cloud/auth/reset-password", { email: data.email, token: data.token, new_password: data.password });
            setRecovery(false); setMessage("Password reset. Sign in with your new password.");
          } else {
            setAccount(await cloud.login(data.email, data.password, signup ? data.name : undefined));
          }
        });
      }}>
        {signup && !recovery && <label>Name<input name="name" required maxLength={200} /></label>}
        <label>Email<input name="email" type="email" required maxLength={254} autoComplete="email" autoCapitalize="none" spellCheck={false} /></label>
        {recovery && <label>Email reset code<input name="token" required maxLength={256} /></label>}
        <label>{recovery ? "New password" : "Password"}<input name="password" type="password" required minLength={8} maxLength={1024} autoComplete={signup || recovery ? "new-password" : "current-password"} /></label>
        <button disabled={busy}>{busy ? "Please wait..." : recovery ? "Reset password" : signup ? "Create account" : "Sign in"}</button>
        {recovery && <button type="button" disabled={busy} onClick={(event) => {
          const form = event.currentTarget.form;
          const email = form.elements.email.value;
          run(async () => setMessage((await cloud.request("POST", "/cloud/auth/request-password-reset", { email })).message));
        }}>Send reset code</button>}
      </form>
      <button disabled={busy} onClick={() => { setSignup(!signup); setRecovery(false); }}>{signup ? "Already have an account? Sign in" : "Create account"}</button>
      <button disabled={busy} onClick={() => { setRecovery(!recovery); setSignup(false); }}>{recovery ? "Back to sign in" : "Forgot password?"}</button>
    </section></div> : !account.email_verified ? <section className="customer-panel">
      <h2>Verify your email</h2><p>Verify {account.email} before accessing a home.</p>
      <button disabled={busy} onClick={() => run(async () =>
        setMessage((await cloud.request("POST", "/cloud/auth/request-verification")).message))}>Send verification code</button>
      <form onSubmit={(event) => { const data = values(event); run(async () => {
        await cloud.request("POST", "/cloud/auth/verify-email", { token: data.token });
        setAccount(await cloud.refreshAccount());
      }); }}><label>Email code<input name="token" required /></label><button disabled={busy}>Verify email</button></form>
    </section> : !home ? <section className="customer-panel">
      <h2>Your homes</h2>
      {homes.map((choice) => <button key={choice.gateway_id} disabled={busy} onClick={() => choose(choice)}>
        {choice.name} · {choice.gateway_name} · {choice.role}</button>)}
      <button disabled={busy} onClick={() => setTick((value) => value + 1)}>Refresh homes</button>
      <h3>Pair your Pi</h3><p>Scan the setup label in the mobile app, or paste its setup text here. Never paste the gateway machine credential.</p>
      <form onSubmit={(event) => { const data = values(event); run(async () => {
        const label = parseSetupLabel(data.setup);
        await cloud.request("POST", "/cloud/gateways/pair", {
          gateway_id: label.gateway_id, pairing_code: label.pairing_code, household_name: data.name,
        }, 201);
        setTick((value) => value + 1);
      }); }}>
        <label>Home name<input name="name" defaultValue="My home" required maxLength={200} /></label>
        <label>Pi setup label<textarea name="setup" required maxLength={2048} /></label><button disabled={busy}>Pair Pi</button>
        <button type="button" disabled={busy} onClick={(event) => {
          const setup = event.currentTarget.form.elements.setup.value;
          run(async () => {
            const label = parseSetupLabel(setup);
            const result = await cloud.request("POST", "/cloud/gateways/email-setup-qr", {
              gateway_id: label.gateway_id, pairing_code: label.pairing_code,
            });
            setMessage(result.message);
          });
        }}>Email my setup QR</button>
        <small>Enter your new Pi's setup label first. A PNG copy goes only to your verified account email; it keeps its original expiry and stops working once paired. Your existing homes are not changed.</small>
      </form>
      <form onSubmit={(event) => { const data = values(event); run(async () => {
        await cloud.request("POST", "/cloud/household-invites/accept", { invite_code: data.code });
        setTick((value) => value + 1);
      }); }}><label>Household invitation code<input name="code" required /></label><button disabled={busy}>Join home</button></form>
    </section> : <>
      <div className="dashboard-layout">
      <DashboardSidebar tab={tab} onTab={setTab} alertCount={snapshot?.alerts.length ?? 0} />
      <div className="app-content dashboard-content">
      {cloud.pending?.unconfirmed && <section className="customer-panel" aria-label="Command recovery">
        <p>A {cloud.pending.action === "train" ? "training start" : "device action"} is awaiting confirmation. Do not send it again.</p>
        <button disabled={busy} onClick={() => run(checkCommand)}>Check command status</button>
      </section>}
      <div className="customer-tab">
      <div hidden={!["Home", "Model"].includes(tab)}>
      <section className="customer-panel home-overview" hidden={tab === "Model"}><h2>{home.name}</h2><p>{home.gateway_name} · {home.role}</p>
        <button disabled={busy} onClick={manageHomes}>Manage homes</button>
        <p>{stale ? "Your home is offline or updates are delayed. Showing the last update." : "Your home is connected. Checking updates every 2 seconds."}</p>
        {!stale && warnings.map(event => <p key={event.mac} role="status">
          Recent WARNING: {snapshot.devices.find(device => device.mac === event.mac)?.name || event.mac}.
          Detected in the last 60 seconds; current status is shown separately.
        </p>)}
        {snapshot && <p>Updated: {new Date(snapshot.observed_at).toLocaleString()}</p>}
      </section>
      {tab === "Home" && <DashboardMetrics snapshot={snapshot} />}
      <section className="customer-panel" hidden={tab !== "Model"}><p className="dashboard-eyebrow">Distributed learning</p><h2>Federated model</h2>
        <p>{snapshot?.model.available ? "Detection model available on your home gateway." : "Waiting for a detection-model update from your home gateway."}</p>
        <p>Training: {training?.state || "unavailable"}{training && ` · ${training.current_round}/${training.total_rounds} rounds`}</p>
        <p>Pi checkpoint: {Number.isInteger(federated?.federated_round) ? `round ${federated.federated_round}` : "not yet reported"}</p>
        {training?.error && <p role="status">{training.error}</p>}
        {canControl ? <>
          <button disabled={busy || !trainEnabled || cloud.pending?.unconfirmed}
            onClick={() => {
              if (window.confirm("Start real federated training on the laptop and Pi? Keep the coordinator running and connected to the Pi network.")) run(() => execute(null, "train"));
            }}>Update global model</button>
          {!trainEnabled && <p>{!snapshot?.training_available ? "Training rollout is not enabled." : training?.state === "running" ? "Training is in progress. Do not start another run." : "Waiting for fresh laptop coordinator status. Monitoring continues independently."}</p>}
        </> : <p>Only household owners and admins can update the global model.</p>}
        <p>Startup acceptance is not training completion. Coordinator rounds and the Pi checkpoint are reported separately.</p>
      </section>
      <section className="customer-panel" hidden={tab !== "Home"}><h2>Live alerts</h2>
        <p role="status" aria-live="polite">{liveAlerts.length ? `Latest event: ${liveAlerts[0].status}` : "New threat events will appear here while this page is open."}</p>
        {liveAlerts.slice(0, 5).map(alert => <p key={`${alert.event_id}:${alert.timestamp}`}>
          {alert.status} · {snapshot?.devices.find(device => device.mac === alert.mac)?.name || alert.mac} · {new Date(alert.timestamp).toLocaleTimeString()}
        </p>)}
      </section>
      </div>
      <div hidden={!["Home", "Devices"].includes(tab)}>
      <section className="operations-section"><p className="dashboard-eyebrow">Live router telemetry</p><h2>IoT network</h2>
        {!snapshot && <p>Waiting for a gateway snapshot...</p>}
        {snapshot?.devices.length === 0 && <p>No devices reported yet.</p>}
        <div className="dashboard-device-grid">
        {snapshot?.devices.map((device) => <CustomerDeviceCard key={device.mac} device={device}
          warning={!stale && warnings.some(event => event.mac === device.mac)}
          canControl={canControl} disabled={busy || stale || !canControl || cloud.pending?.unconfirmed}
          managementDisabled={busy || stale || !snapshot?.device_management_available || cloud.pending?.unconfirmed}
          waiting={busy && cloud.pending?.mac === device.mac}
          onControl={() => control(device)} onRemove={() => {
            if (window.confirm(`Remove ${device.name}? Its device record and detection history will be deleted on the Pi. A blocked device will first be unblocked.`)) {
              run(() => execute(device.mac, "remove"));
            }
          }} />)}
        </div>
        {canControl && <form className="customer-panel add-device-panel" onSubmit={(event) => {
          const data = values(event);
          run(() => execute(data.mac.trim().toLowerCase(), "register", {device_name: data.name, ip_address: data.ip.trim()}));
        }}>
          <h3>Add device</h3>
          <label>Device name<input name="name" required maxLength={200} /></label>
          <label>MAC address<input name="mac" required pattern="([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}" /></label>
          <label>IP address (optional)<input name="ip" /></label>
          <button disabled={busy || stale || !snapshot?.device_management_available || cloud.pending?.unconfirmed}>Add device</button>
        </form>}
        {!canControl && <p>Read-only: only owners/admins can manage devices.</p>}
      </section>
      </div>
      <div hidden={tab !== "Activity"}>
      <section className="history-heading"><p className="dashboard-eyebrow">Historical telemetry</p><h2>Alerts &amp; history</h2>
        <p>Real Pi detection history, refreshed every 2 seconds. {stale && "Updates are delayed; showing the last received history."}</p>
      </section>
      {tab === "Activity" && <DetectionHistory snapshot={snapshot} />}
      </div>
      <div hidden={tab !== "Settings"}>
      <section className="customer-panel"><h2>Settings</h2>
        <p>{account.name} · {account.email}</p><p>{home.name} · Role: {home.role}</p>
        <button aria-pressed={light} onClick={() => setLight(value => !value)}>{light ? "Use dark theme" : "Use light theme"}</button>
        <button disabled={busy} aria-pressed={notifications} onClick={() => run(toggleNotifications)}>{notifications ? "Mute live browser notifications" : "Enable live browser notifications"}</button>
        <p>Browser notifications require permission and an open website. They are independent of your phone notification preference.</p>
      </section>
      {canControl && <section className="customer-panel"><h2>Invite a household member</h2>
        <form onSubmit={(event) => { const data = values(event); run(async () => {
          const result = await cloud.request("POST", `/cloud/households/${home.household_id}/invites`, { email: data.email, role: data.role }, 201);
          setMessage(`Share privately with ${data.email}: ${result.invite_code}. Expires in 24 hours.`);
        }); }}><label>Email<input name="email" type="email" required /></label>
          <label>Role<select name="role"><option value="member">Member</option>{home.role === "owner" && <option value="admin">Admin</option>}</select></label>
          <button disabled={busy}>Create invitation</button></form>
      </section>}
      <section className="customer-panel"><h2>Change password</h2><form onSubmit={(event) => {
        const data = values(event); run(async () => {
          await cloud.request("POST", "/cloud/auth/change-password", { current_password: data.current, new_password: data.next });
          logout(); setMessage("Password changed. Sign in again.");
        });
      }}><label>Current password<input name="current" type="password" required /></label>
        <label>New password<input name="next" type="password" required minLength={8} maxLength={1024} /></label>
        <button disabled={busy}>Change password</button></form></section>
      </div>
      </div>
      </div>
      </div>
    </>}
    {home && <footer className="dashboard-footer"><span>GHOST-1D-GRU / EA-NGO</span><span>SECURITY OPERATIONS PLATFORM</span></footer>}
  </main>;
}
