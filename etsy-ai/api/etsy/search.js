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
  const params = new URLSearchParams({ keywords, limit: String(limit), sort_on: "score", sort_order: "desc" });

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
    const prices = items.map((i) => i.price).filter((v) => Number.isFinite(v) && v >= 0).sort((a,b) => a-b);
    const favs = items.map((i) => i.favorites).filter((v) => Number.isFinite(v) && v >= 0);
    const median = prices.length ? (prices.length % 2 ? prices[(prices.length - 1) / 2] : (prices[prices.length / 2 - 1] + prices[prices.length / 2]) / 2) : null;
    const average = (values) => values.length ? values.reduce((sum, v) => sum + v, 0) / values.length : null;
    return json(res, 200, {
      ok: true, keywords, fetchedAt: new Date().toISOString(),
      resultCount: Number.isFinite(Number(data.count)) ? Number(data.count) : items.length,
      sampleCount: items.length,
      metrics: { averagePrice: average(prices), medianPrice: median, averageFavorites: average(favs), listingsWithFavorites: favs.length },
      items,
      caveat: "Active-listing results are a market snapshot, not verified sales, demand, profit, or conversion data."
    });
  } catch (error) {
    return json(res, 502, { ok: false, code: "ETSY_CONNECTION_ERROR", error: "Could not reach Etsy right now. Check the deployment logs and retry." });
  }
}
