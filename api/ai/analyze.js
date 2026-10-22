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
    error: "AI analysis is disabled until MYSHKA_ACCESS_TOKEN is configured in Vercel."
  });
  const suppliedToken = String(req.headers["x-myshka-access"] || "");
  const expectedBytes = Buffer.from(requiredToken, "utf8");
  const suppliedBytes = Buffer.from(suppliedToken, "utf8");
  if (expectedBytes.length !== suppliedBytes.length || !timingSafeEqual(expectedBytes, suppliedBytes)) {
    return json(res, 401, { ok: false, code: "AI_ACCESS_DENIED", error: "Private workspace token is missing or incorrect." });
  }

  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) return json(res, 503, {
    ok: false, code: "AI_KEY_MISSING",
    error: "AI analysis requires OPENAI_API_KEY in Vercel. No external request was made."
  });

  const body = typeof req.body === "string" ? (() => { try { return JSON.parse(req.body); } catch { return {}; } })() : (req.body || {});
  const keywords = String(body.keywords || "").trim().slice(0, 120);
  const market = body.market && typeof body.market === "object" ? {
    code: String(body.market.code || "").slice(0, 4),
    label: String(body.market.label || "").slice(0, 60),
    currency: String(body.market.currency || "").slice(0, 4)
  } : {};
  const listings = Array.isArray(body.listings) ? body.listings.slice(0, 30).map(item => ({
    title: String(item.title || "").slice(0, 240),
    price: Number.isFinite(Number(item.price)) ? Number(item.price) : null,
    currency: String(item.currency || "").slice(0, 8),
    favorites: Number.isFinite(Number(item.favorites)) ? Number(item.favorites) : null,
    listingType: String(item.listingType || "").slice(0, 40),
    tags: Array.isArray(item.tags) ? item.tags.slice(0, 8).map(t => String(t).slice(0, 40)) : []
  })) : [];
  const metrics = body.metrics && typeof body.metrics === "object" ? {
    priceByCurrency: Array.isArray(body.metrics.priceByCurrency) ? body.metrics.priceByCurrency.slice(0, 8) : [],
    averageFavorites: Number.isFinite(Number(body.metrics.averageFavorites)) ? Number(body.metrics.averageFavorites) : null,
    listingsWithFavorites: Number.isFinite(Number(body.metrics.listingsWithFavorites)) ? Number(body.metrics.listingsWithFavorites) : null
  } : {};
  const resultCount = Number.isFinite(Number(body.resultCount)) ? Number(body.resultCount) : null;
  if (keywords.length < 2 || listings.length === 0) {
    return json(res, 400, { ok: false, error: "Run a live Etsy search first. A niche name and at least one returned listing are required." });
  }

  const system = [
    "You are MYSHKA, a cautious Etsy niche research analyst.",
    "Analyze only the supplied public active-listing sample and the numbers provided. Do not browse or claim to know sales, conversion, profit, search volume, trend growth, ad costs, or true demand. Favorites and active listing counts are not sales.",
    "Do not treat sample price as supplier cost. Do not assume that a generic resale item is eligible on Etsy. Flag Etsy Creativity Standards and production-partner/original-design questions when relevant.",
    "Give an opportunity score from 0 to 100 as a transparent heuristic for further research only, not probability of success. If data is weak, score conservatively and use low confidence.",
    "Recommend a small, reversible validation plan before inventory purchases. Identify missing evidence and realistic risks. Never invent product features, supplier quotes, or sales estimates.",
    "Return valid JSON with keys: score (integer 0-100), verdict (short label such as 'Validate further', 'Weak evidence', or 'Promising angle to test'), confidence ('Low','Medium','High'), summary (2-4 sentences), differentiation (array of strings), signals (array of strings), risks (array of strings), missingEvidence (array of strings), nextSteps (array of strings).",
    "Keep the answer concise, specific, and honest. Do not make legal guarantees."
  ].join("\n");

  const input = {
    niche: keywords,
    targetBuyerMarket: market,
    reportedActiveListingResultCount: resultCount,
    returnedSampleCount: listings.length,
    aggregateMetrics: metrics,
    activeListingSample: listings,
    request: "Assess the niche as a research lead. Prioritize differentiation, Etsy eligibility, and the next evidence to collect before spending money."
  };

  try {
    const upstream = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { "Authorization": "Bearer " + apiKey, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: process.env.OPENAI_MODEL || "gpt-4.1-mini",
        temperature: 0.2,
        response_format: { type: "json_object" },
        messages: [{ role: "system", content: system }, { role: "user", content: JSON.stringify(input) }]
      }),
      signal: AbortSignal.timeout(25000)
    });
    if (!upstream.ok) {
      let payload = {};
      try { payload = await upstream.json(); } catch {}
      const providerCode = typeof payload?.error?.code === "string" ? payload.error.code.replace(/[^a-zA-Z0-9_.-]/g, "").slice(0, 80) : "";
      if (upstream.status === 401 || upstream.status === 403) return json(res, 502, {
        ok: false, code: "AI_PROVIDER_AUTH_ERROR",
        error: "OpenAI rejected the request. Check OPENAI_API_KEY and project access."
      });
      if (upstream.status === 429) return json(res, 429, {
        ok: false, code: "AI_PROVIDER_LIMIT",
        error: "OpenAI usage or rate limit reached. Check API billing, credits and rate limits."
      });
      return json(res, 502, {
        ok: false, code: "AI_PROVIDER_ERROR",
        error: "AI analysis failed (HTTP " + upstream.status + (providerCode ? ", code " + providerCode : "") + "). Check provider settings and try again."
      });
    }
    const result = await upstream.json();
    const raw = result.choices?.[0]?.message?.content;
    if (!raw) return json(res, 502, { ok: false, error: "AI returned an empty analysis." });
    let analysis;
    try { analysis = JSON.parse(raw); } catch { return json(res, 502, { ok: false, error: "AI returned an unreadable analysis." }); }
    const score = Number(analysis.score);
    analysis.score = Number.isFinite(score) ? Math.max(0, Math.min(100, Math.round(score))) : null;
    return json(res, 200, { ok: true, analysis, status: "analysis_only_no_sales_data", autoPublishing: false });
  } catch {
    return json(res, 502, { ok: false, error: "Could not reach the AI provider. Try again later." });
  }
}
