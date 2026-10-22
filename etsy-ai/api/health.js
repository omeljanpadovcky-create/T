export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ ok: false, error: "Method not allowed" });
  }
  return res.status(200).json({
    ok: true,
    app: "MYSHKA ETSY AI",
    version: "0.1.0",
    etsyConfigured: Boolean(process.env.ETSY_API_KEY),
    aiConfigured: Boolean(process.env.OPENAI_API_KEY && process.env.MYSHKA_ACCESS_TOKEN),
    aiProviderConfigured: Boolean(process.env.OPENAI_API_KEY),
    aiAccessConfigured: Boolean(process.env.MYSHKA_ACCESS_TOKEN),
    listingPublishing: false,
    mode: "research-and-human-review"
  });
}
