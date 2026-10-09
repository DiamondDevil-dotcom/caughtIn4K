export function snapshotStale(snapshot, now = Date.now()) {
  const time = Date.parse(snapshot?.observed_at);
  return !snapshot || snapshot.data_stale || !snapshot.recent_contact ||
    !Number.isFinite(time) || time > now || now - time > 90_000;
}

export function trainingReady(snapshot, now = Date.now()) {
  const federated = snapshot?.model?.federated;
  const time = Date.parse(federated?.observed_at);
  return !snapshotStale(snapshot, now) && snapshot.training_available === true &&
    Number.isFinite(time) && time <= now && now - time <= 30_000 &&
    ["idle", "completed", "failed"].includes(federated?.training?.state);
}

export function recentWarnings(snapshot, now = Date.now()) {
  if (snapshotStale(snapshot, now)) return [];
  const visible = new Set(snapshot.devices.map(device => device.mac));
  const warnings = new Map();
  for (const event of snapshot.alerts) {
    const time = Date.parse(event.timestamp);
    if (event.status !== "WARNING" || !visible.has(event.mac) ||
        !Number.isFinite(time) || time > now || now - time >= 60_000) continue;
    const previous = warnings.get(event.mac);
    if (!previous || time > Date.parse(previous.timestamp)) warnings.set(event.mac, event);
  }
  return [...warnings.values()];
}

export class LiveAlertTracker {
  constructor() { this.seen = new Set(); this.initialized = false; }
  reset() { this.seen.clear(); this.initialized = false; }
  update(snapshot, now = Date.now()) {
    if (snapshotStale(snapshot, now)) return [];
    const next = new Set();
    const fresh = [];
    for (const event of snapshot.alerts) {
      const key = `${event.event_id}:${event.timestamp}`;
      next.add(key);
      const time = Date.parse(event.timestamp);
      if (this.initialized && !this.seen.has(key) &&
          ["WARNING", "ATTACK", "ALERT", "BLOCKED"].includes(event.status) &&
          Number.isFinite(time) && time <= now && now - time < 60_000 &&
          snapshot.devices.some(device => device.mac === event.mac)) fresh.push(event);
    }
    this.seen = next;
    this.initialized = true;
    return fresh;
  }
}

export class CloudClient {
  constructor(origin, { fetcher = globalThis.fetch.bind(globalThis), storage = globalThis.sessionStorage } = {}) {
    const url = new URL(origin);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash ||
        (url.pathname !== "/" && url.pathname !== "")) throw new Error("Invalid application cloud origin.");
    this.origin = url.origin;
    this.fetcher = fetcher;
    this.storage = storage;
    this.account = JSON.parse(storage.getItem("customer-account") || "null");
    this.generation = 0;
    this.pending = this.account ? JSON.parse(storage.getItem(`customer-command:${this.account.account_id}`) || "null") : null;
    this.home = null;
    this.submitting = false;
    this.confirmed = new Map();
    this.removed = new Map();
  }

  async request(method, path, body, expected = 200) {
    const version = this.generation;
    const response = await this.fetcher(this.origin + path, {
      method, redirect: "error", signal: AbortSignal.timeout(60_000),
      headers: {
        ...(this.account?.access_token ? { Authorization: `Bearer ${this.account.access_token}` } : {}),
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (version !== this.generation) throw new Error("Account or home changed.");
    if (response.status !== expected) {
      let message;
      if (path === "/cloud/gateways/email-setup-qr") {
        message = {
          400: "This setup label is invalid, expired, or already paired. Use the original label for a new, unpaired Pi.",
          403: "Verify your account email before requesting a setup QR.",
          422: "Use a valid Pi setup label without any machine credential.",
          503: "The setup QR could not be sent. Email or account storage is unavailable; try again later.",
        }[response.status];
      }
      if (path === "/cloud/auth/signup") {
        message = response.status === 409
          ? "An account with this email already exists. Sign in or use Forgot password."
          : response.status >= 500
          ? "The account service is temporarily unavailable. Try again shortly."
          : response.status === 400 || response.status === 422
          ? "Check your name, email address and password (8–1024 characters)."
          : undefined;
        if (response.status === 400) {
          const safe = ["Enter a valid email address.", "Use a password between 8 and 1024 characters.", "Use a name between 1 and 200 characters."];
          try {
            const body = await response.json();
            if (safe.includes(body?.detail)) message = body.detail;
          } catch (failure) {
            if (!(failure instanceof SyntaxError)) throw failure;
            message = "The account service returned an unreadable error. Check your account details and retry.";
          }
        }
      }
      const error = new Error(message || `Request failed (HTTP ${response.status}). ${
        response.status === 401 ? "Sign in again." :
        response.status === 429 ? "Too many requests. Try again later." : "Check access or command status before retrying."}`);
      error.status = response.status;
      throw error;
    }
    const result = await response.json();
    if (version !== this.generation) throw new Error("Account or home changed.");
    if (!result || Array.isArray(result) || typeof result !== "object") throw new Error("Invalid cloud response.");
    return result;
  }

  async login(email, password, name) {
    email = email.trim();
    if (name !== undefined) {
      name = name.trim();
      if (!name || name.length > 200) throw new Error("Use a name between 1 and 200 characters.");
      if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw new Error("Enter a valid email address.");
      if (password.length < 8 || password.length > 1024) throw new Error("Use a password between 8 and 1024 characters.");
    }
    const account = await this.request("POST", name ? "/cloud/auth/signup" : "/cloud/auth/login",
      { email, password, ...(name ? { name } : {}) }, name ? 201 : 200);
    if (typeof account.account_id !== "string" || !account.access_token?.startsWith("cloud-v1.") || typeof account.email !== "string" ||
        typeof account.name !== "string") throw new Error("Invalid account response.");
    this.generation++;
    this.account = account;
    this.home = null;
    this.confirmed.clear();
    this.removed.clear();
    this.pending = JSON.parse(this.storage.getItem(`customer-command:${account.account_id}`) || "null");
    this.storage.setItem("customer-account", JSON.stringify(account));
    return account;
  }

  logout() {
    this.generation++;
    this.account = this.home = null;
    this.confirmed.clear();
    this.removed.clear();
    this.pending = null;
    this.storage.removeItem("customer-account");
    // Retain an unresolved command UUID for recovery, not credentials.
  }

  async refreshAccount() {
    const account = await this.request("GET", "/cloud/auth/me");
    this.account = { ...account, access_token: this.account.access_token };
    this.storage.setItem("customer-account", JSON.stringify(this.account));
    return this.account;
  }

  async homes() {
    const { households } = await this.request("GET", "/cloud/households");
    if (!Array.isArray(households)) throw new Error("Invalid household list.");
    const choices = [];
    for (const home of households) {
      const { gateways } = await this.request("GET", `/cloud/households/${home.household_id}/gateways`);
      if (!Array.isArray(gateways)) throw new Error("Invalid gateway list.");
      for (const gateway of gateways) {
        if (!gateway.revoked_at) choices.push({ ...gateway, ...home, name: home.name, gateway_name: gateway.name });
      }
    }
    return choices;
  }

  select(home) {
    this.generation++;
    this.home = home;
    this.confirmed.clear();
    this.removed.clear();
  }

  path() {
    if (!this.home) throw new Error("Choose your home first.");
    return `/cloud/households/${this.home.household_id}/gateways/${this.home.gateway_id}`;
  }

  async snapshot() {
    const snapshot = await this.request("GET", `${this.path()}/snapshot`);
    if (snapshot.gateway_id !== this.home.gateway_id || !snapshot.snapshot_available ||
        !Array.isArray(snapshot.devices) || !Array.isArray(snapshot.alerts) ||
        typeof snapshot.data_stale !== "boolean" || typeof snapshot.recent_contact !== "boolean" ||
        !snapshot.model || !Number.isFinite(Date.parse(snapshot.observed_at))) {
      throw new Error("No valid snapshot available yet.");
    }
    const observed = Date.parse(snapshot.observed_at);
    for (const [mac, confirmation] of this.confirmed) {
      if (observed >= confirmation.completedAt) this.confirmed.delete(mac);
    }
    for (const [mac, completed] of this.removed) {
      if (observed >= completed) this.removed.delete(mac);
    }
    for (const device of snapshot.devices) {
      const confirmation = this.confirmed.get(device.mac);
      if (!confirmation) continue;
      device.blocked = confirmation.blocked;
      device.status = confirmation.blocked ? "BLOCKED" : device.status === "BLOCKED" ? "SAFE" : device.status;
    }
    snapshot.devices = snapshot.devices.filter((device) => !this.removed.has(device.mac));
    return snapshot;
  }

  async submit(mac, action, details = {}) {
    if (this.submitting || this.pending?.unconfirmed) throw new Error("Check the previous command before sending another.");
    if (!["owner", "admin"].includes(this.home?.role)) throw new Error("Only owners/admins can control the network.");
    if (!["block", "unblock", "register", "remove", "train"].includes(action) ||
        (action === "train" ? mac !== null : !/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/.test(mac))) {
      throw new Error("Invalid device action.");
    }
    this.submitting = true;
    try {
    const snapshot = await this.snapshot();
    if (action === "train" && !trainingReady(snapshot)) {
      throw new Error("Training is disabled, or laptop status is unavailable, stale or already running. No command sent.");
    }
    if (["register", "remove"].includes(action) && !snapshot.device_management_available) {
      throw new Error("Device management requires the Pi update. No command sent.");
    }
    if (action === "register" && (typeof details.device_name !== "string" || !details.device_name.trim() ||
        details.device_name.length > 200 || typeof details.ip_address !== "string")) {
      throw new Error("Enter a device name and optional IPv4 address.");
    }
    if (snapshotStale(snapshot)) throw new Error("Gateway offline or stale. No command sent.");
    const id = globalThis.crypto.randomUUID();
    const path = this.path();
    if (!["register", "train"].includes(action) && !snapshot.devices.some((device) => device.mac === mac)) throw new Error("Device is no longer reported by this Pi.");
    this.pending = { id, path, gateway_id: this.home.gateway_id, mac, action, unconfirmed: true };
    this.storage.setItem(`customer-command:${this.account.account_id}`, JSON.stringify(this.pending));
    try {
      const response = await this.request("POST", `${path}/commands`, {
        command_id: id, mac, action,
        ...(action === "register" ? {device_name: details.device_name.trim(), ip_address: details.ip_address} : {}),
      }, 202);
      if (response.id !== id || response.gateway_id !== this.home.gateway_id ||
          response.mac !== mac || response.action !== action) throw new Error("Invalid command acknowledgement.");
    } catch (error) {
      if ([400, 401, 403, 404, 409, 422].includes(error.status)) {
        this.pending.unconfirmed = false;
        this.storage.setItem(`customer-command:${this.account.account_id}`, JSON.stringify(this.pending));
      }
      throw error;
    }
    return id;
    } finally {
      this.submitting = false;
    }
  }

  async commandStatus() {
    if (!this.pending) throw new Error("No command to check.");
    const { id, path, gateway_id, mac, action } = this.pending;
    const result = await this.request("GET", `${path}/commands/${id}`);
    if (result.id !== id || result.gateway_id !== gateway_id || result.mac !== mac || result.action !== action ||
        !["queued", "delivered", "succeeded", "failed", "expired", "cancelled", "unknown"].includes(result.status) ||
        (result.status === "succeeded" && result.result_code !== "applied")) throw new Error("Invalid command result.");
    if (result.status === "succeeded" && gateway_id === this.home?.gateway_id && ["block", "unblock"].includes(action)) {
      this.confirmed.set(mac, {
        blocked: action === "block",
        completedAt: Date.parse(result.completed_at) || Date.now(),
      });
    }
    if (result.status === "succeeded" && gateway_id === this.home?.gateway_id && action === "remove") {
      this.removed.set(mac, Date.parse(result.completed_at) || Date.now());
    }
    if (["succeeded", "failed", "expired", "cancelled"].includes(result.status)) {
      this.pending.unconfirmed = false;
      this.storage.setItem(`customer-command:${this.account.account_id}`, JSON.stringify(this.pending));
    }
    return result;
  }
}
