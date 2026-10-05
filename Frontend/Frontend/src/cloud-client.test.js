import test from "node:test";
import assert from "node:assert/strict";
import { CloudClient, LiveAlertTracker, recentWarnings, snapshotStale, trainingReady } from "./cloud-client.js";

const mac = "aa:bb:cc:dd:ee:ff";
const account = { account_id: "owner-a", email: "owner@example.invalid", name: "Owner",
  email_verified: true, access_token: "cloud-v1.test.signature" };
const home = { gateway_id: "gateway-a", household_id: "home-a", role: "owner" };
const snapshot = () => ({ gateway_id: home.gateway_id, snapshot_available: true,
  observed_at: new Date().toISOString(), data_stale: false, recent_contact: true,
  devices: [{ mac, name: "Test phone", blocked: false, status: "SAFE" }], alerts: [], model: { available: false } });
const response = (body, status = 200) => ({ status, json: async () => body });

test("brief warnings survive later blocked snapshots separately for parallel devices", () => {
  const now = Date.now();
  const other = "11:22:33:44:55:66";
  const data = { ...snapshot(), devices: [{mac, status:"BLOCKED"}, {mac:other, status:"SAFE"}],
    alerts: [
      {event_id:1, mac, status:"WARNING", timestamp:new Date(now - 2000).toISOString()},
      {event_id:2, mac, status:"BLOCKED", timestamp:new Date(now - 1000).toISOString()},
      {event_id:3, mac:other, status:"WARNING", timestamp:new Date(now - 3000).toISOString()},
      {event_id:4, mac:other, status:"WARNING", timestamp:new Date(now - 1000).toISOString()},
    ] };
  assert.deepEqual(recentWarnings(data, now).map(event => event.event_id), [1, 4]);
  assert.equal(data.devices[0].status, "BLOCKED");
  assert.equal(recentWarnings(data, now + 61_000).length, 0);
  assert.equal(recentWarnings({...data, data_stale:true}, now).length, 0);
  assert.equal(recentWarnings({...data, devices:[]}, now).length, 0);
});
function storage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
}
function client(fetcher, store = storage()) {
  store.setItem("customer-account", JSON.stringify(account));
  const cloud = new CloudClient("https://home.example.invalid", { fetcher, storage: store });
  cloud.select(home);
  return cloud;
}
function commandFetcher(status = "queued", changes = {}) {
  let command;
  return async (url, request) => {
    if (url.endsWith("/snapshot")) return response(snapshot());
    if (request.method === "POST") {
      const body = JSON.parse(request.body);
      command = { ...body, id: body.command_id, gateway_id: home.gateway_id };
      return response(command, 202);
    }
    return response({ ...command, status, result_code: status === "succeeded" ? "applied" : null, ...changes });
  };
}

test("normal account login never sends operator or machine credentials", async () => {
  const cloud = new CloudClient("https://home.example.invalid", { storage: storage(),
    fetcher: async (url, options) => {
      assert.equal(url, "https://home.example.invalid/cloud/auth/login");
      assert.equal(options.redirect, "error");
      assert.deepEqual(options.headers, { "Content-Type": "application/json" });
      return response(account);
    } });
  assert.equal((await cloud.login(account.email, "test-password")).account_id, account.account_id);
});

test("browser-native fetch keeps its required global receiver", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async function () {
      assert.equal(this, globalThis);
      return response(account);
    };
    const cloud = new CloudClient("https://home.example.invalid", { storage: storage() });
    await cloud.login(account.email, "test-password");
  } finally {
    globalThis.fetch = original;
  }
});

test("invalid or insecure built-in service origins fail explicitly", () => {
  for (const origin of ["http://example.invalid", "https://user:password@example.invalid", "https://example.invalid/private"]) {
    assert.throws(() => new CloudClient(origin, { storage: storage() }));
  }
});

test("read-only membership cannot send a network command", async () => {
  let requests = 0;
  const cloud = client(async () => { requests++; return response(snapshot()); });
  cloud.select({ ...home, role: "member" });
  await assert.rejects(cloud.submit(mac, "block"), /owners\/admins/);
  assert.equal(requests, 0);
});

test("stale/offline and old snapshots never submit a command", async () => {
  for (const changes of [{ data_stale: true }, { recent_contact: false },
    { observed_at: new Date(Date.now() - 91_000).toISOString() }]) {
    let posts = 0;
    const cloud = client(async (url, request) => {
      if (request.method === "POST") posts++;
      return response({ ...snapshot(), ...changes });
    });
    await assert.rejects(cloud.submit(mac, "block"), /stale/);
    assert.equal(posts, 0);
  }
});

test("queued and delivered never count as completed enforcement", async () => {
  for (const status of ["queued", "delivered", "unknown"]) {
    const cloud = client(commandFetcher(status));
    await cloud.submit(mac, "block");
    assert.equal((await cloud.commandStatus()).status, status);
    assert.equal(cloud.pending.unconfirmed, true);
    await assert.rejects(cloud.submit(mac, "unblock"), /previous command/);
  }
});

test("gateway/action/target and applied result must match the saved command", async () => {
  for (const changes of [{ gateway_id: "other-gateway" }, { mac: "11:22:33:44:55:66" },
    { action: "unblock" }, { result_code: "not-applied" }]) {
    const cloud = client(commandFetcher("succeeded", changes));
    await cloud.submit(mac, "block");
    await assert.rejects(cloud.commandStatus(), /Invalid command result/);
    assert.equal(cloud.pending.unconfirmed, true);
  }
});

test("confirmed enforcement remains visible until a post-command snapshot arrives", async () => {
  const old = snapshot();
  const completed = new Date(Date.parse(old.observed_at) + 1000).toISOString();
  const underlying = commandFetcher("succeeded", { completed_at: completed });
  const cloud = client((url, request) => url.endsWith("/snapshot") ? Promise.resolve(response(structuredClone(old))) : underlying(url, request));
  await cloud.submit(mac, "block");
  await cloud.commandStatus();
  assert.equal(cloud.pending.unconfirmed, false);
  assert.equal((await cloud.snapshot()).devices[0].blocked, true);
  old.observed_at = new Date(Date.parse(completed) + 1000).toISOString();
  assert.equal((await cloud.snapshot()).devices[0].blocked, false);
});

test("reload and sign-out/sign-in recover the original UUID without replay", async () => {
  const store = storage();
  let posts = 0;
  const underlying = commandFetcher();
  const fetcher = async (url, request) => {
    if (url.endsWith("/cloud/auth/login")) return response(account);
    if (request.method === "POST") posts++;
    return underlying(url, request);
  };
  const original = client(fetcher, store);
  const id = await original.submit(mac, "block");
  original.logout();
  await original.login(account.email, "test-password");
  assert.equal(original.pending.id, id);
  const restored = new CloudClient(original.origin, { storage: store, fetcher });
  restored.select(home);
  assert.equal(restored.pending.id, id);
  assert.equal((await restored.commandStatus()).status, "queued");
  assert.equal(posts, 1);
});

test("another signed-in account never inherits a previous owner's command", async () => {
  const store = storage();
  const first = client(commandFetcher(), store);
  await first.submit(mac, "block");
  first.logout();
  const second = new CloudClient(first.origin, { storage: store,
    fetcher: async () => response({ ...account, account_id: "owner-b" }) });
  await second.login("second@example.invalid", "test-password");
  assert.equal(second.pending, null);
});

test("concurrent clicks cannot queue two commands while checking freshness", async () => {
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  let posts = 0;
  const underlying = commandFetcher();
  const cloud = client(async (url, request) => {
    if (url.endsWith("/snapshot")) await waiting;
    if (request.method === "POST") posts++;
    return underlying(url, request);
  });
  const first = cloud.submit(mac, "block");
  await assert.rejects(cloud.submit(mac, "block"), /previous command/);
  release();
  await first;
  assert.equal(posts, 1);
});

test("lost responses retain UUID but explicit rejection permits a corrected action", async () => {
  for (const status of [503, 403]) {
    const cloud = client(async (url) => url.endsWith("/snapshot") ? response(snapshot()) : response({}, status));
    await assert.rejects(cloud.submit(mac, "block"), /Request failed/);
    assert.equal(cloud.pending.unconfirmed, status === 503);
    assert.ok(cloud.pending.id);
  }
});

test("a response decoded after sign-out cannot restore private data", async () => {
  let release;
  const body = new Promise((resolve) => { release = resolve; });
  const cloud = client(async () => ({ status: 200, json: () => body }));
  const pending = cloud.snapshot();
  await new Promise((resolve) => setTimeout(resolve, 0));
  cloud.logout();
  release(snapshot());
  await assert.rejects(pending, /Account or home changed/);
});

test("owners can register a new MAC with bounded details and wait for actual acknowledgement", async () => {
  let saved;
  const newMac = "11:22:33:44:55:66";
  const cloud = client(async (url, request) => {
    if (url.endsWith("/snapshot")) return response({ ...snapshot(), device_management_available: true });
    if (request.method === "POST") {
      saved = JSON.parse(request.body);
      return response({ ...saved, id: saved.command_id, gateway_id: home.gateway_id }, 202);
    }
    return response({ ...saved, id: saved.command_id, gateway_id: home.gateway_id,
      status: "succeeded", result_code: "applied", completed_at: new Date().toISOString() });
  });
  await cloud.submit(newMac, "register", { device_name: " Sensor ", ip_address: "" });
  assert.equal(saved.device_name, "Sensor");
  assert.equal(saved.ip_address, "");
  assert.equal(saved.mac, newMac);
  assert.equal(cloud.pending.unconfirmed, true);
  assert.equal((await cloud.commandStatus()).status, "succeeded");
  assert.equal(cloud.confirmed.size, 0);
  assert.equal(cloud.pending.unconfirmed, false);
});

test("removed devices stay hidden during old snapshots including recovered commands", async () => {
  const old = snapshot();
  const completed = new Date(Date.parse(old.observed_at) + 1000).toISOString();
  let saved;
  const store = storage();
  const fetcher = async (url, request) => {
    if (url.endsWith("/snapshot")) return response({ ...structuredClone(old), device_management_available: true });
    if (request.method === "POST") {
      saved = JSON.parse(request.body);
      return response({ ...saved, id: saved.command_id, gateway_id: home.gateway_id }, 202);
    }
    return response({ ...saved, id: saved.command_id, gateway_id: home.gateway_id,
      status: "succeeded", result_code: "applied", completed_at: completed });
  };
  const original = client(fetcher, store);
  await original.submit(mac, "remove");
  const recovered = new CloudClient(original.origin, { fetcher, storage: store });
  recovered.select(home);
  await recovered.commandStatus();
  assert.equal((await recovered.snapshot()).devices.length, 0);
  assert.equal(recovered.confirmed.size, 0);
  old.devices = [];
  old.observed_at = new Date(Date.parse(completed) + 1000).toISOString();
  assert.equal((await recovered.snapshot()).devices.length, 0);
  assert.equal(recovered.removed.size, 0);
});

test("management rollout gate and household membership prevent device mutations", async () => {
  for (const action of ["register", "remove"]) {
    let posts = 0;
    const cloud = client(async (url, request) => {
      if (request.method === "POST") posts++;
      return response(snapshot());
    });

    await assert.rejects(cloud.submit(mac, action, { device_name: "Sensor", ip_address: "" }), /Pi update/);
    assert.equal(posts, 0);
    cloud.select({ ...home, role: "member" });
    await assert.rejects(cloud.submit(mac, action), /owners\/admins/);
    assert.equal(posts, 0);
  }
});

test("freshness thresholds match mobile: snapshots 90s, training 30s, warnings 60s", () => {
  const now = Date.now();
  const data = { ...snapshot(), training_available: true, model: { federated: {
    observed_at: new Date(now - 30_000).toISOString(), training: { state: "idle" },
  } } };
  data.observed_at = new Date(now - 90_000).toISOString();
  assert.equal(snapshotStale(data, now), false);
  assert.equal(trainingReady(data, now), true);
  assert.equal(trainingReady(data, now + 1), false);
  assert.equal(snapshotStale(data, now + 1), true);
  data.observed_at = new Date(now).toISOString();
  data.alerts = [{ event_id: 1, mac, status: "WARNING", timestamp: new Date(now - 59_999).toISOString() }];
  assert.equal(recentWarnings(data, now).length, 1);
  assert.equal(recentWarnings(data, now + 1).length, 0);
});

test("two clients observe the same authoritative device state and model progress", async () => {
  let state = snapshot();
  let command;
  const fetcher = async (url, request) => {
    if (url.endsWith("/snapshot")) return response(structuredClone(state));
    if (request.method === "POST") {
      const payload = JSON.parse(request.body);
      command = { ...payload, id: payload.command_id, gateway_id: home.gateway_id };
      return response(command, 202);
    }
    state.devices[0].blocked = true; state.devices[0].status = "BLOCKED";
    state.observed_at = new Date().toISOString();
    return response({ ...command, status: "succeeded", result_code: "applied",
      completed_at: state.observed_at });
  };
  const phoneLike = client(fetcher);
  const website = client(fetcher);
  await phoneLike.submit(mac, "block");
  await phoneLike.commandStatus();
  assert.equal((await website.snapshot()).devices[0].blocked, true);
  state = trainingSnapshot();
  assert.equal((await website.snapshot()).model.federated.federated_round, 10);
  assert.equal((await phoneLike.snapshot()).model.federated.training.current_round, 10);
});

    function trainingSnapshot(changes = {}) {
      return { ...snapshot(), training_available: true, model: { available: true,
        federated: { observed_at: new Date().toISOString(), federated_round: 10,
          training: { state: "completed", current_round: 10, total_rounds: 10 } } }, ...changes };
    }

    test("training uses a null-MAC gateway command, accepts startup only, and never overlays a device", async () => {
      let saved;
      const cloud = client(async (url, request) => {
        if (url.endsWith("/snapshot")) return response(trainingSnapshot());
        if (request.method === "POST") {
          saved = JSON.parse(request.body);
          return response({ ...saved, id: saved.command_id, gateway_id: home.gateway_id }, 202);
        }
        return response({ ...saved, id: saved.command_id, gateway_id: home.gateway_id,
          status: "succeeded", result_code: "applied" });
      });
      await cloud.submit(null, "train");
      assert.equal(saved.mac, null);
      assert.equal(saved.action, "train");
      assert.deepEqual(Object.keys(saved).sort(), ["action", "command_id", "mac"]);
      assert.equal(cloud.pending.unconfirmed, true);
      assert.equal((await cloud.commandStatus()).status, "succeeded");
      assert.equal(cloud.pending.unconfirmed, false);
      assert.equal(cloud.confirmed.size, 0);
    });

    test("unavailable, stale, future and running training cannot start; members remain read-only", async () => {
      for (const data of [
        trainingSnapshot({ training_available: false }),
        trainingSnapshot({ data_stale: true }),
        trainingSnapshot({ model: { available: true } }),
        ...["running", "unavailable"].map(state => {
          const data = trainingSnapshot(); data.model.federated.training.state = state; return data;
        }),
        ...[-31_000, 5000].map(offset => {
          const data = trainingSnapshot(); data.model.federated.observed_at = new Date(Date.now() + offset).toISOString(); return data;
        }),
      ]) {
        let posts = 0;
        const cloud = client(async (_, request) => { if (request.method === "POST") posts++; return response(data); });
        await assert.rejects(cloud.submit(null, "train"), /No command sent/);
        assert.equal(posts, 0);
      }
      const cloud = client(async () => { throw new Error("No request permitted"); });
      cloud.select({ ...home, role: "member" });
      await assert.rejects(cloud.submit(null, "train"), /owners\/admins/);
      await assert.rejects(client(commandFetcher()).submit(mac, "train"), /Invalid device action/);
    });

    test("uncertain training survives reload and recovery without replaying startup", async () => {
      const store = storage();
      let saved; let posts = 0;
      const fetcher = async (url, request) => {
        if (url.endsWith("/snapshot")) return response(trainingSnapshot());
        if (request.method === "POST") {
          posts++; saved = JSON.parse(request.body);
          throw new Error("Connection lost after sending");
        }
        return response({ ...saved, id: saved.command_id, gateway_id: home.gateway_id, status: "unknown" });
      };
      const first = client(fetcher, store);
      await assert.rejects(first.submit(null, "train"), /Connection lost/);
      const restored = new CloudClient(first.origin, { fetcher, storage: store });
      restored.select(home);
      assert.equal(restored.pending.mac, null);
      assert.equal((await restored.commandStatus()).status, "unknown");
      await assert.rejects(restored.submit(null, "train"), /previous command/);
      assert.equal(posts, 1);
    });

    test("live browser alerts baseline history, dedupe parallel threats and reset between homes", () => {
      const tracker = new LiveAlertTracker();
      const now = Date.now();
      const event = (id, status = "WARNING") => ({
        event_id: id, mac, status, timestamp: new Date(now - 1000).toISOString(),
      });
      assert.deepEqual(tracker.update({ ...snapshot(), alerts: [event(1)] }, now), []);
      const next = { ...snapshot(), alerts: [event(1), event(2), event(3, "BLOCKED"), event(4, "SAFE")] };
      assert.deepEqual(tracker.update(next, now).map(event => event.event_id), [2, 3]);
      assert.deepEqual(tracker.update(next, now), []);
      assert.deepEqual(tracker.update({ ...next, data_stale: true, alerts: [event(5)] }, now), []);
      tracker.reset();
      assert.deepEqual(tracker.update(next, now), []);
    });

    test("invalid timestamps fail closed in UI freshness and training guards", () => {
      const data = trainingSnapshot({ observed_at: "invalid" });
      assert.equal(snapshotStale(data), true);
      assert.equal(trainingReady(data), false);
      assert.deepEqual(recentWarnings(data), []);
    });

    test("signup validates input without a request and preserves safe validation messages", async () => {
      let requests = 0;
      const cloud = new CloudClient("https://home.example.invalid", { storage: storage(), fetcher: async () => {
        requests++; return response({ detail: "Enter a valid email address." }, 400);
      } });
      await assert.rejects(cloud.login("test@ example.com", "password", "Name"), /valid email/);
      await assert.rejects(cloud.login("test@example.com", "short", "Name"), /password between/);
      await assert.rejects(cloud.login("test@example.com", "password", " "), /name between/);
      assert.equal(requests, 0);
      await assert.rejects(cloud.login("test@example.com", "password", "Name"), /Enter a valid email address/);
      assert.equal(requests, 1);
      for (const [status, detail, pattern] of [
        [409, "private diagnostic", /already exists/],
        [400, "private diagnostic", /Check your name/],
        [503, "private diagnostic", /temporarily unavailable/],
      ]) {
        cloud.fetcher = async () => response({ detail }, status);
        await assert.rejects(cloud.login("test@example.com", "password", "Name"), error =>
          error.status === status && pattern.test(error.message) && !error.message.includes("private diagnostic"));
      }
    });
