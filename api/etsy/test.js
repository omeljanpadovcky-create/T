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
  if (!requiredToken) {
    return json(res, 503, {
      ok: false,
      code: "WORKSPACE_ACCESS_NOT_CONFIGURED",
      error: "Private workspace access is not configured in Vercel yet."
    });
  }

  const suppliedToken = String(req.headers["x-myshka-access"] || "");
  const expectedBytes = Buffer.from(requiredToken, "utf8");
  const suppliedBytes = Buffer.from(suppliedToken, "utf8");
  if (expectedBytes.length !== suppliedBytes.length || !timingSafeEqual(expectedBytes, suppliedBytes)) {
    return json(res, 401, {
      ok: false,
      code: "WORKSPACE_ACCESS_DENIED",
      error: "Private workspace token is missing or incorrect."
    });
  }

  const apiKey = process.env.ETSY_API_KEY || "";
  if (!apiKey) {
    return json(res, 503, {
      ok: false,
      code: "ETSY_KEY_MISSING",
      error: "ETSY_API_KEY is not configured in Vercel."
    });
  }

  const keywords = "personalized dog collar";
  const params = new URLSearchParams({
    keywords,
    limit: "5",
    sort_on: "score",
    sort_order: "desc"
  });

  try {
    const upstream = await fetch(
      "https://openapi.etsy.com/v3/application/listings/active?" + params.toString(),
      {
        method: "GET",
        headers: {
          "x-api-key": apiKey,
          "Accept": "application/json"
        },
        signal: AbortSignal.timeout(12000)
      }
    );

    if (upstream.status === 401 || upstream.status === 403) {
      return json(res, 502, {
        ok: false,
        code: "ETSY_AUTH_FAILED",
        error: "Etsy rejected the configured API credentials or the app lacks listing-search access."
      });
    }
    if (upstream.status === 429) {
      return json(res, 429, {
        ok: false,
        code: "ETSY_RATE_LIMIT",
        error: "Etsy rate limit reached during the connection test. Wait and retry."
      });
    }
    if (!upstream.ok) {
      return json(res, 502, {
        ok: false,
        code: "ETSY_UPSTREAM_ERROR",
        error: "Etsy API returned HTTP " + upstream.status + "."
      });
    }

    const data = await upstream.json();
    if (!Array.isArray(data.results)) {
      return json(res, 502, {
        ok: false,
        code: "ETSY_INVALID_RESPONSE",
        error: "Etsy responded, but the listing response format was unexpected."
      });
    }

    return json(res, 200, {
      ok: true,
      service: "Etsy Open API v3",
      checkedAt: new Date().toISOString(),
      query: keywords,
      resultCount: Number.isFinite(Number(data.count)) ? Number(data.count) : data.results.length,
      sampleCount: data.results.length,
      checks: {
        workspaceTokenAccepted: true,
        etsyCredentialsAccepted: true,
        activeListingSearchResponded: true
      },
      note: "A successful connection test does not establish sales, demand, or profitability."
    });
  } catch {
    return json(res, 502, {
      ok: false,
      code: "ETSY_CONNECTION_ERROR",
      error: "Could not reach Etsy during the connection test. Check deployment logs and retry."
    });
  }
}
