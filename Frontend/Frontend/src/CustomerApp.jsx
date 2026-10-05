import { useEffect, useRef, useState } from "react";
import { CloudClient } from "./cloud-client";
import "./customer.css";

export default function CustomerApp() {
  const [cloud] = useState(() => new CloudClient(import.meta.env.VITE_CLOUD_API_URL || "https://caughtin4k-1.onrender.com"));
  const [account, setAccount] = useState(cloud.account);
  const [home, setHome] = useState(null);
  const [homes, setHomes] = useState([]);
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [signup, setSignup] = useState(false);
  const [recovery, setRecovery] = useState(false);
  const [tick, setTick] = useState(0);
  const [now, setNow] = useState(Date.now());
  const mounted = useRef(true);
  const running = useRef(false);
  const choosingHome = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(timer);
  }, []);

  function logout() {
    choosingHome.current = false;
    cloud.logout(); setAccount(null); setHome(null); setHomes([]); setSnapshot(null); setError(""); setMessage("");
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
    cloud.select(choice); setHome(choice); setSnapshot(null); setError("");
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
        if (active) { setSnapshot(data); setError(""); }
      } catch (failure) { if (active) setError(failure.message); }
      finally { fetching = false; }
    };
    refresh();
    const timer = setInterval(refresh, 15_000);
    return () => { active = false; clearInterval(timer); };
  }, [home]);

  const stale = !snapshot || snapshot.data_stale || !snapshot.recent_contact || Boolean(error) ||
      now - Date.parse(snapshot.observed_at) > 90_000;
  const canControl = ["owner", "admin"].includes(home?.role);
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
          setMessage(action === "register"
            ? "Device added on your Pi. It may take up to 30 seconds to appear."
            : "Your Pi confirmed the device action.");
          setSnapshot(await cloud.snapshot());
          return;
        }
        if (!["queued", "delivered"].includes(result.status)) {
          throw new Error(`Network action not confirmed: ${result.status}. Check device state.`);
        }
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
      throw new Error("Timed out. Check command status before retrying.");
  }

  return <main className="customer-app">
    <header><h1>caughtIn4K</h1><span>Your smart home, wherever you are</span>
      {account && <button disabled={busy} onClick={logout}>Sign out</button>}
    </header>
    {error && <p role="alert" className="customer-error">{error}</p>}
    {message && <p role="status">{message}</p>}
    {!account ? <section className="customer-panel">
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
        <label>Email<input name="email" type="email" required autoComplete="email" /></label>
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
    </section> : !account.email_verified ? <section className="customer-panel">
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
        const label = JSON.parse(data.setup);
        if (label.version !== 1 || typeof label.gateway_id !== "string" || typeof label.pairing_code !== "string") throw new Error("Invalid Pi setup label.");
        await cloud.request("POST", "/cloud/gateways/pair", {
          gateway_id: label.gateway_id, pairing_code: label.pairing_code, household_name: data.name,
        }, 201);
        setTick((value) => value + 1);
      }); }}>
        <label>Home name<input name="name" defaultValue="My home" required maxLength={200} /></label>
        <label>Pi setup label<textarea name="setup" required /></label><button disabled={busy}>Pair Pi</button>
      </form>
      <form onSubmit={(event) => { const data = values(event); run(async () => {
        await cloud.request("POST", "/cloud/household-invites/accept", { invite_code: data.code });
        setTick((value) => value + 1);
      }); }}><label>Household invitation code<input name="code" required /></label><button disabled={busy}>Join home</button></form>
    </section> : <>
      <section className="customer-panel"><h2>{home.name}</h2><p>{home.gateway_name} · {home.role}</p>
        <button disabled={busy} onClick={() => { choosingHome.current = true; cloud.select(null); setHome(null); setSnapshot(null); }}>Manage homes</button>
        <p>{stale ? "Your home is offline or updates are delayed. Showing the last update." : "Your home is connected. Updates may take up to 30 seconds."}</p>
        {snapshot && <p>Updated: {new Date(snapshot.observed_at).toLocaleString()}</p>}
      </section>
      <section className="customer-panel"><h2>Devices</h2>
        {!snapshot && <p>Waiting for a gateway snapshot...</p>}
        {snapshot?.devices.length === 0 && <p>No devices reported yet.</p>}
        {snapshot?.devices.map((device) => <article className="customer-device" key={device.mac}>
          <div><h3>{device.name}</h3><p>{device.mac} · {device.ip_address || "IP not reported"}</p>
            <p>{device.status} · {device.attack_probability}% attack probability</p></div>
          <button disabled={busy || stale || !canControl || cloud.pending?.unconfirmed}
            onClick={() => control(device)}>{busy && cloud.pending?.mac === device.mac ? "Waiting for Pi..." : device.blocked ? "Unblock" : "Block"}</button>
          {canControl && <button disabled={busy || stale || cloud.pending?.unconfirmed} onClick={() => {
            if (window.confirm(`Remove ${device.name}? Its device record and detection history will be deleted on the Pi. A blocked device will first be unblocked.`)) {
              run(() => execute(device.mac, "remove"));
            }
          }}>Remove</button>}
        </article>)}
        {canControl && <form onSubmit={(event) => {
          const data = values(event);
          run(() => execute(data.mac.trim().toLowerCase(), "register", {device_name: data.name, ip_address: data.ip.trim()}));
        }}>
          <h3>Add device</h3>
          <label>Device name<input name="name" required maxLength={200} /></label>
          <label>MAC address<input name="mac" required pattern="([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}" /></label>
          <label>IP address (optional)<input name="ip" /></label>
          <button disabled={busy || stale || cloud.pending?.unconfirmed}>Add device</button>
        </form>}
        {!canControl && <p>Read-only: only owners/admins can manage devices.</p>}
        {cloud.pending?.unconfirmed && <><p>A device action is awaiting confirmation.</p><button disabled={busy} onClick={() => run(async () => {
          const result = await cloud.commandStatus();
          setMessage(result.status === "succeeded" ? "Your Pi confirmed the device action." : `Device action: ${result.status}. Check before retrying.`);
          if (result.status === "succeeded") setSnapshot(await cloud.snapshot());
        })}>Check command status</button></>}
      </section>
      <section className="customer-panel"><h2>Threat detection</h2>
        <p>{snapshot?.model.available ? "Detection model available on your home gateway." : "Waiting for a detection-model update from your home gateway."}</p>
      </section>
      <section className="customer-panel"><h2>Recent alerts</h2>
        {snapshot?.alerts.map((alert) => <p key={alert.event_id}>
          {new Date(alert.timestamp).toLocaleString()} · {alert.mac} · {alert.status} · {alert.attack_probability}%</p>)}
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
    </>}
  </main>;
}
