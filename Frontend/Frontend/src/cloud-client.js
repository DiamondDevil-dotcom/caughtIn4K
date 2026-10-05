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
      const error = new Error(`Request failed (HTTP ${response.status}). ${
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
    const account = await this.request("POST", name ? "/cloud/auth/signup" : "/cloud/auth/login",
      { email, password, ...(name ? { name } : {}) }, name ? 201 : 200);
    if (!account.access_token?.startsWith("cloud-v1.") || typeof account.email !== "string" ||
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
    if (!["block", "unblock", "register", "remove"].includes(action) || !/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/.test(mac)) {
      throw new Error("Invalid device action.");
    }
    this.submitting = true;
    try {
    const snapshot = await this.snapshot();
    if (["register", "remove"].includes(action) && !snapshot.device_management_available) {
      throw new Error("Device management requires the Pi update. No command sent.");
    }
    if (action === "register" && (typeof details.device_name !== "string" || !details.device_name.trim() ||
        details.device_name.length > 200 || typeof details.ip_address !== "string")) {
      throw new Error("Enter a device name and optional IPv4 address.");
    }
    if (snapshot.data_stale || !snapshot.recent_contact ||
        Date.now() - Date.parse(snapshot.observed_at) > 90_000) throw new Error("Gateway offline or stale. No command sent.");
    const id = globalThis.crypto.randomUUID();
    const path = this.path();
    if (action !== "register" && !snapshot.devices.some((device) => device.mac === mac)) throw new Error("Device is no longer reported by this Pi.");
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
