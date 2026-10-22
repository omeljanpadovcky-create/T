function send(res, status, body) {
  res.status(status).setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}
export default async function handler(req, res) {
  if (req.method !== "GET") { res.setHeader("Allow", "GET"); return send(res, 405, { ok: false, error: "Method not allowed" }); }
  const key = process.env.ETSY_API_KEY || process.env.ETSY_KEYSTRING || "";
  return send(res, 200, {
    ok: true, app: "MYSHKA ETSY AI", version: "1.0.0",
    etsyConfigured: Boolean(key.includes(":") || (key && process.env.ETSY_SHARED_SECRET)),
    aiConfigured: Boolean(process.env.OPENAI_API_KEY),
    storage: "browser-local", publishing: false
  });
}