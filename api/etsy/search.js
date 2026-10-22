function send(res, status, body) {
  res.status(status).setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(body));
}
function apiKey() {
  const value = process.env.ETSY_API_KEY || "";
  if (value.includes(":")) return value;
  const key = process.env.ETSY_KEYSTRING || value;
  return key && process.env.ETSY_SHARED_SECRET ? key + ":" + process.env.ETSY_SHARED_SECRET : "";
}
function toMoney(raw) {
  if (raw == null) return null;
  if (typeof raw === "number") return raw;
  if (typeof raw === "object") {
    const amount = Number(raw.amount), divisor = Number(raw.divisor || 100);
    return Number.isFinite(amount) && divisor > 0 ? amount / divisor : null;
  }
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}
function percentile(sorted, p) {
  if (!sorted.length) return null;
  const position = (sorted.length - 1) * p, base = Math.floor(position), rest = position - base;
  return sorted[base + 1] === undefined ? sorted[base] : sorted[base] + rest * (sorted[base + 1] - sorted[base]);
}
export default async function handler(req, res) {
  if (req.method !== "GET") { res.setHeader("Allow", "GET"); return send(res, 405, { ok: false, error: "Method not allowed" }); }
  const keywords = String(req.query?.keywords || "").trim().replace(/\s+/g, " ");
  const limit = Math.min(100, Math.max(1, parseInt(req.query?.limit || "48", 10) || 48));
  if (keywords.length < 2 || keywords.length > 100) return send(res, 400, { ok: false, error: "Ключові слова мають містити від 2 до 100 символів." });
  const key = apiKey();
  if (!key) return send(res, 503, { ok: false, error: "Etsy API не налаштовано. Додай ETSY_API_KEY у Vercel; якщо це лише keystring, також додай ETSY_SHARED_SECRET." });
  const url = new URL("https://openapi.etsy.com/v3/application/listings/active");
  url.searchParams.set("keywords", keywords); url.searchParams.set("limit", String(limit));
  url.searchParams.set("sort_on", "score"); url.searchParams.set("sort_order", "desc");
  let response;
  try { response = await fetch(url, { headers: { "x-api-key": key, "Accept": "application/json" }, signal: AbortSignal.timeout(24000) }); }
  catch (_) { return send(res, 502, { ok: false, error: "Не вдалося зв'язатися з Etsy API. Спробуй ще раз." }); }
  if (!response.ok) {
    const message = response.status === 401 || response.status === 403
      ? "Etsy відхилив доступ. Перевір активність/схвалення API keystring та shared secret."
      : "Etsy API повернув статус " + response.status + ". Спробуй пізніше.";
    return send(res, response.status === 429 ? 429 : 502, { ok: false, error: message, upstream_status: response.status });
  }
  let payload;
  try { payload = await response.json(); } catch (_) { return send(res, 502, { ok: false, error: "Etsy повернув некоректну відповідь." }); }
  const raw = Array.isArray(payload.results) ? payload.results : [];
  const listings = raw.map(item => {
    const priceRaw = item.price, price = toMoney(priceRaw);
    const images = Array.isArray(item.images) ? item.images : [];
    const image = images.find(x => x && (x.url_fullxfull || x.url_570xN || x.url_170x135)) || {};
    return {
      listing_id: item.listing_id ?? null,
      title: String(item.title || "Untitled listing").slice(0, 300),
      price, currency: priceRaw && typeof priceRaw === "object" ? (priceRaw.currency_code || "USD") : (item.currency_code || "USD"),
      url: item.url || (item.listing_id ? "https://www.etsy.com/listing/" + item.listing_id : ""),
      shop_name: item.shop_name || null,
      views: Number.isFinite(Number(item.views)) ? Number(item.views) : null,
      favorites: Number.isFinite(Number(item.num_favorers)) ? Number(item.num_favorers) : null,
      image_url: image.url_fullxfull || image.url_570xN || image.url_170x135 || null,
      tags: Array.isArray(item.tags) ? item.tags.map(t => typeof t === "string" ? t : t?.name).filter(Boolean).slice(0, 13) : []
    };
  });
  const prices = listings.map(x => x.price).filter(x => x !== null && Number.isFinite(x)).sort((a,b) => a-b);
  const avg = prices.length ? prices.reduce((a,b) => a+b, 0) / prices.length : null;
  const median = percentile(prices, .5);
  return send(res, 200, {
    ok: true, source: "Etsy Open API v3", keywords,
    total_results: Number(payload.count ?? listings.length), sample_count: listings.length,
    currency: listings.find(x => x.price !== null)?.currency || "USD",
    price_stats: { count: prices.length, min: prices.length ? prices[0] : null, max: prices.length ? prices[prices.length-1] : null, average: avg === null ? null : Math.round(avg*100)/100, median: median === null ? null : Math.round(median*100)/100, p25: percentile(prices,.25), p75: percentile(prices,.75) },
    disclaimer: "Active listings and sampled prices do not prove demand, sales, or profitability.",
    listings
  });
}