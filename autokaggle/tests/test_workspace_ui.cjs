"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "static", "workspace.js"), "utf8");
const start = source.indexOf("  async function api(");
const end = source.indexOf("  function notice(", start);
assert.ok(start >= 0 && end > start);

for (const status of [401, 403, 404, 500]) {
  test(`Session-tool HTTP ${status} uses account recovery only for access errors`, async () => {
    const events = [], requests = [];
    const api = new Function("fetch", "notify", source.slice(start, end) + "\nreturn api;")(
      async (url, options) => {
        requests.push({ url, options });
        return { ok: false, status, json: async () => ({ detail: "Unavailable" }) };
      }, (name) => events.push(name));
    await assert.rejects(api("/api/projects/p1/privacy", "PATCH", { accepted: true }),
      (error) => error.status === status && error.message === "Unavailable");
    assert.deepEqual(events, status === 500 ? [] : ["refresh"]);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].options.credentials, "same-origin");
    assert.equal(requests[0].options.method, "PATCH");
    assert.equal(requests[0].options.body, JSON.stringify({ accepted: true }));
  });
}
