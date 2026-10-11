// Vinci's relay on Cloudflare Workers: what a page opened from WhatsApp sends back (the sealed Canvas token, a tick
// on the dashboard) waits here until Vinci's PC fetches it. The PC opens no port, and the relay reads nothing it
// keeps: a token arrives sealed to a one-time key only the PC holds.
//
// POST /m/<mailbox>  {kind, ...}  from a page; the mailbox, random and in the link's fragment, is its capability.
// GET  /inbox[?mailbox=]          the PC (bearer RELAY_TOKEN): every message waiting, or one mailbox's.
// POST /ack {ids}                 the PC: delete what it handled.
// PUT  /s/<mailbox>  {...}        the PC: what the page should show now (the Académico's CAPTCHA and progress).
// GET  /s/<mailbox>               the page: that status, by the same capability.
import { DurableObject } from "cloudflare:workers";

const MAILBOX = /^[A-Za-z0-9_-]{22,64}$/;
const MAX_BODY = 4096;
const MAX_STATUS = 65536; // a CAPTCHA image rides in it
const STATUS_MS = 2 * 3600 * 1000;
const MAX_KEPT = 500;
const KEEP_MS = 48 * 3600 * 1000;
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
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
    const status = url.pathname.match(/^\/s\/([^/]+)$/)?.[1];
    if (status) {
      if (!MAILBOX.test(status)) return json(404, { error: "mailbox" }, CORS);
      if (request.method === "GET") {
        const found = await inbox.status(status);
        return found ? json(200, found, { ...CORS, "Cache-Control": "no-store" }) : json(404, { error: "none" }, CORS);
      }
      if (request.method === "PUT") {
        if (!authorized(request, env)) return json(401, { error: "token" });
        const body = await request.text();
        if (body.length > MAX_STATUS) return json(413, { error: "too large" });
        let data;
        try {
          data = JSON.parse(body);
        } catch {
          return json(400, { error: "json" });
        }
        await inbox.setStatus(status, data);
        return json(200, { ok: true });
      }
    }
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
      return json(200, { messages: await inbox.list(url.searchParams.get("mailbox")) });
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
    this.sql.exec(`CREATE TABLE IF NOT EXISTS statuses (
      mailbox TEXT PRIMARY KEY, body TEXT NOT NULL, at INTEGER NOT NULL)`);
  }

  async put(mailbox, data) {
    const now = Date.now();
    this.sql.exec("DELETE FROM messages WHERE at < ?", now - KEEP_MS);
    this.sql.exec("INSERT INTO messages VALUES (?, ?, ?, ?)", crypto.randomUUID(), mailbox, JSON.stringify(data), now);
    this.sql.exec(`DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY at DESC LIMIT ${MAX_KEPT})`);
  }

  async list(mailbox) {
    const rows = mailbox
      ? this.sql.exec("SELECT id, mailbox, body, at FROM messages WHERE mailbox = ? ORDER BY at", mailbox)
      : this.sql.exec("SELECT id, mailbox, body, at FROM messages ORDER BY at");
    return rows.toArray().map((row) => ({ id: row.id, mailbox: row.mailbox, data: JSON.parse(row.body), at: row.at }));
  }

  async setStatus(mailbox, data) {
    const now = Date.now();
    this.sql.exec("DELETE FROM statuses WHERE at < ?", now - STATUS_MS);
    this.sql.exec("INSERT OR REPLACE INTO statuses VALUES (?, ?, ?)", mailbox, JSON.stringify(data), now);
  }

  async status(mailbox) {
    const row = this.sql.exec("SELECT body, at FROM statuses WHERE mailbox = ?", mailbox).toArray()[0];
    return row && row.at > Date.now() - STATUS_MS ? JSON.parse(row.body) : null;
  }

  async ack(ids) {
    for (const id of ids) this.sql.exec("DELETE FROM messages WHERE id = ?", id);
  }
}
