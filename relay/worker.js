// Vinci's relay on Cloudflare Workers: what a page opened from WhatsApp sends back (the sealed Canvas token, a tick
// on the dashboard) waits here until Vinci's PC fetches it. The PC opens no port, and the relay reads nothing it
// keeps: a token arrives sealed to a one-time key only the PC holds.
//
// POST /m/<mailbox>  {kind, ...}  from a page; the mailbox, random and in the link's fragment, is its capability.
// GET  /inbox                     the PC (bearer RELAY_TOKEN): every message waiting.
// POST /ack {ids}                 the PC: delete what it handled.
import { DurableObject } from "cloudflare:workers";

const MAILBOX = /^[A-Za-z0-9_-]{22,64}$/;
const MAX_BODY = 4096;
const MAX_KEPT = 500;
const KEEP_MS = 48 * 3600 * 1000;
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

const json = (status, data, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json", ...headers } });

function authorized(request, env) {
  const given = new TextEncoder().encode(request.headers.get("Authorization") || "");
  const wanted = new TextEncoder().encode(`Bearer ${env.RELAY_TOKEN || ""}`);
  return Boolean(env.RELAY_TOKEN) && given.length === wanted.length && crypto.subtle.timingSafeEqual(given, wanted);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    const inbox = env.INBOX.get(env.INBOX.idFromName("inbox"));
    const mailbox = url.pathname.match(/^\/m\/([^/]+)$/)?.[1];
    if (mailbox && request.method === "POST") {
      if (!MAILBOX.test(mailbox)) return json(404, { error: "mailbox" }, CORS);
      const body = await request.text();
      if (body.length > MAX_BODY) return json(413, { error: "too large" }, CORS);
      let data;
      try {
        data = JSON.parse(body);
      } catch {
        return json(400, { error: "json" }, CORS);
      }
      if (!data || typeof data !== "object" || Array.isArray(data)) return json(400, { error: "json" }, CORS);
      await inbox.put(mailbox, data);
      return json(202, { ok: true }, CORS);
    }
    if (url.pathname === "/inbox" && request.method === "GET") {
      if (!authorized(request, env)) return json(401, { error: "token" });
      return json(200, { messages: await inbox.list() });
    }
    if (url.pathname === "/ack" && request.method === "POST") {
      if (!authorized(request, env)) return json(401, { error: "token" });
      const { ids } = await request.json().catch(() => ({}));
      await inbox.ack(Array.isArray(ids) ? ids.map(String) : []);
      return json(200, { ok: true });
    }
    return json(404, { error: "not found" }, CORS);
  },
};

// One Durable Object holds every message: unlike KV, a message is readable the moment it is written.
export class Inbox extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY, mailbox TEXT NOT NULL, body TEXT NOT NULL, at INTEGER NOT NULL)`);
  }

  async put(mailbox, data) {
    const now = Date.now();
    this.sql.exec("DELETE FROM messages WHERE at < ?", now - KEEP_MS);
    this.sql.exec("INSERT INTO messages VALUES (?, ?, ?, ?)", crypto.randomUUID(), mailbox, JSON.stringify(data), now);
    this.sql.exec(`DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY at DESC LIMIT ${MAX_KEPT})`);
  }

  async list() {
    return this.sql.exec("SELECT id, mailbox, body, at FROM messages ORDER BY at").toArray()
      .map((row) => ({ id: row.id, mailbox: row.mailbox, data: JSON.parse(row.body), at: row.at }));
  }

  async ack(ids) {
    for (const id of ids) this.sql.exec("DELETE FROM messages WHERE id = ?", id);
  }
}
