import { timingSafeEqual } from "node:crypto";

const json = (res, status, body) => {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  return res.status(status).json(body);
};

export default async function handler(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return json(res, 405, { ok: false, error: "Method not allowed" });
  }
  const requiredToken = process.env.MYSHKA_ACCESS_TOKEN || "";
  if (!requiredToken) return json(res, 503, {
    ok: false,
    code: "WORKSPACE_ACCESS_NOT_CONFIGURED",
    error: "Private workspace access is not configured yet. Set MYSHKA_ACCESS_TOKEN in Vercel."
  });
  const suppliedToken = String(req.headers["x-myshka-access"] || "");
  const expectedBytes = Buffer.from(requiredToken, "utf8");
  const suppliedBytes = Buffer.from(suppliedToken, "utf8");
  if (expectedBytes.length !== suppliedBytes.length || !timingSafeEqual(expectedBytes, suppliedBytes)) {
    return json(res, 401, {
      ok: false,
      code: "WORKSPACE_ACCESS_DENIED",
      error: "Private workspace token is missing or incorrect. Enter the token in MYSHKA settings."
    });
  }

  const key = process.env.ETSY_API_KEY;
  if (!key) return json(res, 503, {
    ok: false,
    code: "ETSY_KEY_MISSING",
    error: "Etsy API is not connected yet. Add an approved Etsy API key in the Vercel environment variables."
  });

  const keywords = String(req.query?.keywords || "").trim().slice(0, 120);
  if (keywords.length < 2) return json(res, 400, { ok: false, error: "Enter at least 2 characters to search." });
  const parsedLimit = Number.parseInt(req.query?.limit || "40", 10);
  const limit = Math.min(100, Math.max(10, Number.isFinite(parsedLimit) ? parsedLimit : 40));
  const markets = {
    US: { country: "US", currency: "USD", label: "United States" },
    GB: { country: "GB", currency: "GBP", label: "United Kingdom" },
    CA: { country: "CA", currency: "CAD", label: "Canada" },
    AU: { country: "AU", currency: "AUD", label: "Australia" },
    DE: { country: "DE", currency: "EUR", label: "Germany" },
    FR: { country: "FR", currency: "EUR", label: "France" }
  };
  const marketCode = String(req.query?.market || "US").trim().toUpperCase();
  const market = markets[marketCode];
  if (!market) return json(res, 400, {
    ok: false,
    code: "UNSUPPORTED_MARKET",
    error: "Choose one of the supported target markets in the MYSHKA search form."
  });
  const params = new URLSearchParams({
    keywords,
    limit: String(limit),
    sort_on: "score",
    sort_order: "desc",
    buyer_country: market.country,
    currency: market.currency
  });

  try {
    const upstream = await fetch("https://openapi.etsy.com/v3/application/listings/active?" + params.toString(), {
      method: "GET",
      headers: { "x-api-key": key, "Accept": "application/json" },
      signal: AbortSignal.timeout(15000)
    });
    if (!upstream.ok) {
      if (upstream.status === 401 || upstream.status === 403) return json(res, 502, {
        ok: false, code: "ETSY_AUTH_FAILED",
        error: "Etsy did not accept the API credentials or the app lacks access. Check key approval and the required keystring:shared_secret format."
      });
      if (upstream.status === 429) return json(res, 429, {
        ok: false, code: "ETSY_RATE_LIMIT", error: "Etsy rate limit reached. Wait a little and retry."
      });
      return json(res, 502, { ok: false, code: "ETSY_UPSTREAM_ERROR", error: "Etsy search failed with status " + upstream.status + ". Retry later." });
    }

    const data = await upstream.json();
    const results = Array.isArray(data.results) ? data.results : [];
    const items = results.map((item) => {
      const priceObject = item.price || {};
      const divisor = Number(priceObject.divisor) || 1;
      const amount = Number(priceObject.amount);
      const price = Number.isFinite(amount) ? amount / divisor : null;
      return {
        listingId: item.listing_id ?? null,
        title: String(item.title || "Untitled listing").slice(0, 240),
        price,
        currency: String(priceObject.currency_code || "USD").slice(0, 8),
        favorites: Number.isFinite(Number(item.num_favorers)) ? Number(item.num_favorers) : null,
        quantity: Number.isFinite(Number(item.quantity)) ? Number(item.quantity) : null,
        listingType: String(item.listing_type || ""),
        tags: Array.isArray(item.tags) ? item.tags.slice(0, 13).map((tag) => String(tag).slice(0, 40)) : [],
        url: item.url && /^https:\/\/www\.etsy\.com\//i.test(item.url) ? item.url : null,
        shopId: item.shop_id ?? null
      };
    });
    const pricesByCurrency = new Map();
    for (const item of items) {
      if (!Number.isFinite(item.price) || item.price < 0) continue;
      const currency = /^[A-Z]{3}$/.test(item.currency) ? item.currency : "UNK";
      if (!pricesByCurrency.has(currency)) pricesByCurrency.set(currency, []);
      pricesByCurrency.get(currency).push(item.price);
    }
    const medianOf = (values) => {
      const sorted = [...values].sort((a, b) => a - b);
      if (!sorted.length) return null;
      const middle = Math.floor(sorted.length / 2);
      return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
    };
    const average = (values) => values.length ? values.reduce((sum, v) => sum + v, 0) / values.length : null;
    const priceByCurrency = Array.from(pricesByCurrency.entries())
      .map(([currency, values]) => ({
        currency,
        pricedListings: values.length,
        medianPrice: medianOf(values),
        averagePrice: average(values)
      }))
      .sort((a, b) => b.pricedListings - a.pricedListings || a.currency.localeCompare(b.currency));
    const favs = items.map((i) => i.favorites).filter((v) => Number.isFinite(v) && v >= 0);
    return json(res, 200, {
      ok: true, keywords, market: { code: marketCode, country: market.country, currency: market.currency, label: market.label }, fetchedAt: new Date().toISOString(),
      resultCount: Number.isFinite(Number(data.count)) ? Number(data.count) : items.length,
      sampleCount: items.length,
      metrics: { priceByCurrency, averageFavorites: average(favs), listingsWithFavorites: favs.length },
      items,
      caveat: "Results are filtered to listings that Etsy reports can ship to the selected buyer country. Prices are requested in the selected currency using Etsy conversion. This does not mean the seller is located in that country. Active-listing counts and favorites are not verified sales, demand, profit, or conversion data."
    });
  } catch (error) {
    return json(res, 502, { ok: false, code: "ETSY_CONNECTION_ERROR", error: "Could not reach Etsy right now. Check the deployment logs and retry." });
  }
}
