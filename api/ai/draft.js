import { timingSafeEqual } from "node:crypto";

const json = (res, status, body) => {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  return res.status(status).json(body);
};

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return json(res, 405, { ok: false, error: "Method not allowed" });
  }
  const requiredToken = process.env.MYSHKA_ACCESS_TOKEN || "";
  if (!requiredToken) return json(res, 503, {
    ok: false, code: "AI_ACCESS_TOKEN_MISSING",
    error: "AI drafting is disabled until MYSHKA_ACCESS_TOKEN is configured in Vercel."
  });
  const suppliedToken = String(req.headers["x-myshka-access"] || "");
  const expectedBytes = Buffer.from(requiredToken, "utf8");
  const suppliedBytes = Buffer.from(suppliedToken, "utf8");
  if (expectedBytes.length !== suppliedBytes.length || !timingSafeEqual(expectedBytes, suppliedBytes)) {
    return json(res, 401, { ok: false, code: "AI_ACCESS_DENIED", error: "AI access token is missing or incorrect." });
  }
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) return json(res, 503, {
    ok: false, code: "AI_KEY_MISSING",
    error: "AI drafting is not connected yet. Add OPENAI_API_KEY in Vercel environment variables."
  });

  const body = typeof req.body === "string" ? (() => { try { return JSON.parse(req.body); } catch { return {}; } })() : (req.body || {});
  const title = String(body.title || "").trim().slice(0, 180);
  const product = String(body.product || "").trim().slice(0, 600);
  const materials = String(body.materials || "").trim().slice(0, 400);
  const sellerRole = String(body.sellerRole || "").trim().slice(0, 500);
  const itemType = String(body.itemType || "physical").slice(0, 40);
  const aiUsed = body.aiUsed === true;
  if (!title || !product) return json(res, 400, { ok: false, error: "Enter a working title and accurate product details." });

  const system = [
    "You help an Etsy seller draft honest listing copy. Do not invent product materials, sizes, certifications, performance claims, personalization, shipping promises, handmade status, sales data, or customer reviews.",
    "Only use facts supplied by the seller. If information is missing, mark it as [SELLER TO CONFIRM] rather than guessing.",
    "Write in English. Return valid JSON with keys: title, description, tags (array of at most 13 concise strings), assumptionsToCheck (array), aiDisclosureSuggestion.",
    "This is a DRAFT only. Never publish a listing, call Etsy write endpoints, or suggest bypassing Etsy policies.",
    "If the item is a functional guide such as a pattern, recipe, or instructions, do not write or invent the functional instructions themselves. Only draft a listing summary based on human-authored facts supplied by the seller, and warn that the content must be the seller's own work.",
    "If the seller used AI to create an item, include a clear disclosure suggestion. Never describe AI-generated work as entirely handmade or entirely the seller's own creation.",
    "Avoid keyword stuffing and misleading claims."
  ].join("\n");
  const user = {
    itemType, workingTitle: title, productFacts: product, materialsOrFeatures: materials,
    sellerCreativeRole: sellerRole, aiUsed,
    task: "Create a transparent, factual Etsy listing draft for human review."
  };

  try {
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { "Authorization": "Bearer " + apiKey, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: process.env.OPENAI_MODEL || "gpt-4.1-mini",
        temperature: 0.3,
        response_format: { type: "json_object" },
        messages: [{ role: "system", content: system }, { role: "user", content: JSON.stringify(user) }]
      }),
      signal: AbortSignal.timeout(25000)
    });
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) return json(res, 502, { ok: false, error: "The AI provider did not accept the configured API key." });
      if (response.status === 429) return json(res, 429, { ok: false, error: "AI provider limit reached. Check your account limits and retry." });
      return json(res, 502, { ok: false, error: "AI drafting failed. Check provider settings and deployment logs." });
    }
    const data = await response.json();
    const raw = data.choices?.[0]?.message?.content;
    if (!raw) return json(res, 502, { ok: false, error: "AI returned an empty draft." });
    let draft;
    try { draft = JSON.parse(raw); } catch { return json(res, 502, { ok: false, error: "AI returned a draft that could not be parsed." }); }
    return json(res, 200, { ok: true, draft, status: "draft_requires_human_review", autoPublishing: false });
  } catch (error) {
    return json(res, 502, { ok: false, error: "Could not reach the AI provider right now." });
  }
}
