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
  if (req.method !== "POST") { res.setHeader("Allow", "POST"); return send(res, 405, { ok: false, error: "Method not allowed" }); }
  if (!process.env.OPENAI_API_KEY) return send(res, 503, { ok: false, error: "AI не налаштовано. Додай OPENAI_API_KEY у Vercel Environment Variables." });
  const body = req.body || {};
  const title = String(body.title || "").trim().slice(0, 160);
  const facts = String(body.facts || "").trim().slice(0, 3000);
  const type = String(body.type || "physical");
  const aiUsed = Boolean(body.aiUsed);
  if (!title || facts.length < 5) return send(res, 400, { ok: false, error: "Вкажи назву товару й підтверджені факти." });
  if (["functional_guide", "recipe", "pattern", "instructions"].includes(type)) return send(res, 400, { ok: false, error: "Цей помічник не генерує функціональні інструкції, шаблони або рецепти для продажу на Etsy." });
  const prompt = [
    "Create an Etsy listing draft for HUMAN REVIEW only. Never create or publish marketplace listings.",
    "Use only facts supplied by seller. Never invent materials, dimensions, origin, production method, benefits, certifications, shipping promises, reviews, or sales. Do not claim handmade unless the facts support it.",
    "Return: one title idea, a concise factual description, up to 13 appropriate tags, and a human-review checklist. Avoid keyword stuffing.",
    aiUsed ? "Seller says AI was used to create the item itself. Add a clear, plain disclosure suggestion in the description." : "Do not claim the item itself was AI-created.",
    "Item type: " + ({physical:"physical product",customized:"customized or made-to-order item",ai_art:"AI-assisted art/design",digital_design:"digital design/printable"}[type] || "product"),
    "Product title: " + title,
    "Seller-confirmed facts:\n" + facts
  ].join("\n\n");
  let response;
  try {
    response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { "Authorization": "Bearer " + process.env.OPENAI_API_KEY, "Content-Type": "application/json" },
      body: JSON.stringify({ model: process.env.OPENAI_MODEL || "gpt-4o-mini", temperature: 0.35, messages: [
        { role: "system", content: "You are a careful assistant who produces transparent listing drafts. Never perform marketplace actions." },
        { role: "user", content: prompt }
      ] }),
      signal: AbortSignal.timeout(25000)
    });
  } catch (_) { return send(res, 502, { ok: false, error: "Не вдалося з'єднатися з AI-сервісом." }); }
  if (!response.ok) return send(res, 502, { ok: false, error: response.status === 401 || response.status === 403 ? "AI-сервіс відхилив ключ. Перевір OPENAI_API_KEY." : "AI-сервіс повернув помилку (" + response.status + ")." });
  let data; try { data = await response.json(); } catch (_) { return send(res, 502, { ok: false, error: "AI-сервіс повернув некоректну відповідь." }); }
  const draft = data.choices?.[0]?.message?.content;
  if (!draft) return send(res, 502, { ok: false, error: "AI-сервіс не повернув чернетку." });
  return send(res, 200, { ok: true, draft: String(draft).slice(0, 12000), model: process.env.OPENAI_MODEL || "gpt-4o-mini", published: false });
}