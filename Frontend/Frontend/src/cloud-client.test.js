import test from "node:test";
import assert from "node:assert/strict";
import { CloudClient } from "./cloud-client.js";

const mac = "aa:bb:cc:dd:ee:ff";
const account = { account_id: "owner-a", email: "owner@example.invalid", name: "Owner",
  email_verified: true, access_token: "cloud-v1.test.signature" };
const home = { gateway_id: "gateway-a", household_id: "home-a", role: "owner" };
const snapshot = () => ({ gateway_id: home.gateway_id, snapshot_available: true,
  observed_at: new Date().toISOString(), data_stale: false, recent_contact: true,
  devices: [{ mac, name: "Test phone", blocked: false, status: "SAFE" }], alerts: [], model: { available: false } });
const response = (body, status = 200) => ({ status, json: async () => body });
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
