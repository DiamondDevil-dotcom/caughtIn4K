import { AlertTriangle, Cpu, LayoutGrid, LogOut, Moon, Network, Settings, Sun, Timer, Trash2, Wifi } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export function DashboardHeader({ account, light, onTheme, onLogout, busy, connected }) {
  return <header className="app-header dashboard-header">
    <div className="brand-lockup">
      <img className="brand-logo" src="/caughtIn4k_logo.png" alt="" />
      <span><strong>caughtIn4K</strong><small>IoT security intelligence</small></span>
    </div>
    <div className="dashboard-account">
      <button aria-label={light ? "Use dark theme" : "Use light theme"} onClick={onTheme}>
        {light ? <Moon size={17} /> : <Sun size={17} />}
      </button>
      {account && <>
        <span className={`connection-indicator ${connected ? "connected" : ""}`}>{connected ? "Home connected" : "Awaiting home data"}</span>
        <span className="dashboard-username">{account.name}</span>
        <button disabled={busy} onClick={onLogout}><LogOut size={14} /> Sign out</button>
      </>}
    </div>
  </header>;
}

export function DashboardSidebar({ tab, onTab, alertCount }) {
  const items = [
    ["Home", "Operations", LayoutGrid],
    ["Activity", "Detection history", AlertTriangle],
    ["Model", "Federated model", Network],
    ["Settings", "Settings & access", Settings],
  ];
  return <aside className="app-sidebar dashboard-sidebar">
    <p className="dashboard-eyebrow">Security intelligence</p>
    <h1>Know your exposure.</h1>
    <p className="dashboard-intro">A shared view for security leaders and engineering teams to understand IoT risk, validate model decisions, and respond with evidence.</p>
    <nav aria-label="Dashboard sections">
      {items.map(([value, label, Icon]) => <button key={value}
        aria-current={tab === value || (value === "Home" && tab === "Devices") ? "page" : undefined}
        onClick={() => onTab(value)}><Icon size={17} />{label}
        {value === "Activity" && <span className="dashboard-count">{alertCount}</span>}
      </button>)}
    </nav>
  </aside>;
}

export function StatusMetric({ icon: Icon, label, value, detail }) {
  return <div className="metric-panel dashboard-metric">
    <div><Icon size={16} /><span>{label}</span></div>
    <p>{value}</p><small>{detail}</small>
  </div>;
}

export function DashboardMetrics({ snapshot }) {
  const round = snapshot?.model?.federated?.federated_round;
  return <div className="dashboard-metrics">
    <StatusMetric icon={Wifi} label="Live devices" value={snapshot?.devices.length ?? 0} detail="Router telemetry" />
    <StatusMetric icon={AlertTriangle} label="Recent events" value={snapshot?.alerts.length ?? 0} detail="Uploaded Pi detection history" />
    <StatusMetric icon={Cpu} label="Global model" value={Number.isInteger(round) ? `Round ${round}` : snapshot?.model.available ? "Pretrained" : "Unavailable"} detail="Pi checkpoint status" />
    <StatusMetric icon={Timer} label="Refresh rate" value="2s" detail="Active shared snapshot polling" />
  </div>;
}

export function CustomerDeviceCard({ device, warning, canControl, disabled, managementDisabled, waiting, onControl, onRemove }) {
  const attack = Number(device.attack_probability ?? 0);
  const threat = ["WARNING", "ATTACK", "ALERT", "BLOCKED"].includes(device.status);
  return <article className="site-card dashboard-device">
    <div className="dashboard-device-top"><span className="device-icon"><Wifi size={21} /></span>
      <span className={threat ? "device-threat" : "device-safe"}>{device.status || "WAITING"}</span></div>
    <h3>{device.name}</h3><p className="device-mac">{device.mac}</p>
    <div className="device-metrics">
      <div><small>Prediction</small><span>{device.status || "WAITING"}</span></div>
      <div><small>Attack probability</small><span>{Number.isFinite(attack) ? `${attack.toFixed(2)}%` : "Unavailable"}</span></div>
      <div><small>IP address</small><span>{device.ip_address || "Not reported"}</span></div>
      <div><small>Enforcement</small><span>{device.blocked ? "Blocked" : "Not blocked"}</span></div>
    </div>
    {warning && <p className="device-warning">Recent WARNING detected (last 60 seconds).</p>}
    <button className={device.blocked ? "device-unblock" : "device-block"} disabled={disabled}
      onClick={onControl}>{waiting ? "Waiting for Pi..." : device.blocked ? "Unblock device" : "Block device"}</button>
    {canControl && <button className="device-remove" disabled={managementDisabled} onClick={onRemove}><Trash2 size={14} /> Remove device</button>}
  </article>;
}

export function DetectionHistory({ snapshot }) {
  const alerts = snapshot?.alerts ?? [];
  const counts = new Map();
  for (const alert of alerts) counts.set(alert.status, (counts.get(alert.status) ?? 0) + 1);
  const chartData = [...counts].map(([label, count]) => ({ label, count }));
  return <>
    <div className="history-summary">
      <section className="customer-panel"><h3>Detection status counts</h3><p>Uploaded gateway history; not inferred attack types.</p>
        <div className="history-chart">
          {alerts.length ? <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 5, left: -20, bottom: 0 }}>
              <CartesianGrid stroke="#64748b30" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis allowDecimals={false} tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ background: "#132237", border: "1px solid #64748b", color: "#fff", fontSize: 12 }} />
              <Bar dataKey="count" fill="#62d6a7" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer> : <p>No detection events reported yet.</p>}
        </div>
      </section>
      <section className="customer-panel"><p className="dashboard-eyebrow">Activity pulse</p><p className="activity-total">{alerts.length}</p><p>detections in uploaded history</p><small>Newest events appear first</small></section>
    </div>
    <section className="customer-panel history-table"><table>
      <thead><tr><th>Device</th><th>Classification</th><th>Attack probability</th><th>Timestamp</th></tr></thead>
      <tbody>{alerts.map(alert => <tr key={`${alert.event_id}:${alert.timestamp}`}>
        <td>{snapshot.devices.find(device => device.mac === alert.mac)?.name || alert.mac}</td>
        <td>{alert.status}</td><td>{alert.attack_probability}%</td><td>{new Date(alert.timestamp).toLocaleString()}</td>
      </tr>)}</tbody>
    </table></section>
  </>;
}
