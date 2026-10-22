function cors(req, res) {
  const origin = req.headers.origin || "";
  let sameHost = false;
  try { sameHost = Boolean(origin) && new URL(origin).host === req.headers.host; } catch (_) {}
  const allowed = origin === "https://omeljanpadovcky-create.github.io" || sameHost;
  if (allowed) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  }
  if (req.method === "OPTIONS") {
    if (!allowed) { res.status(403).end(); return true; }
    res.status(204).end(); return true;
  }
  return false;
}
function send(res, status, body) {
  res.status(status).setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}
export default async function handler(req, res) {
  if (cors(req, res)) return;
  if (req.method !== "GET") { res.setHeader("Allow", "GET"); return send(res, 405, { ok: false, error: "Method not allowed" }); }
  const key = process.env.ETSY_API_KEY || process.env.ETSY_KEYSTRING || "";
  return send(res, 200, {
    ok: true, app: "MYSHKA ETSY AI", version: "1.0.0",
    etsyConfigured: Boolean(key.includes(":") || (key && process.env.ETSY_SHARED_SECRET)),
    aiConfigured: Boolean(process.env.OPENAI_API_KEY),
    storage: "browser-local", publishing: false
  });
}