export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "Method not allowed" });
  }

  const secret = process.env.CRON_SECRET;
  if (!secret || req.headers.authorization !== "Bearer " + secret) {
    return res.status(401).json({ ok: false, error: "Unauthorized" });
  }

  const token = process.env.TELEGRAM_BOT_TOKEN;
  const webhookSecret = process.env.TELEGRAM_WEBHOOK_SECRET;
  if (!token || !webhookSecret || !process.env.MYSHKA_GITHUB_DISPATCH_TOKEN) {
    return res.status(503).json({
      ok: false,
      error: "Configure TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET and MYSHKA_GITHUB_DISPATCH_TOKEN first."
    });
  }

  const baseUrl = process.env.VERCEL_PROJECT_PRODUCTION_URL || "myshka-job-radar.vercel.app";
  const webhookUrl = "https://" + baseUrl + "/api/telegram-webhook";
  try {
    const response = await fetch("https://api.telegram.org/bot" + token + "/setWebhook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: webhookUrl,
        secret_token: webhookSecret,
        allowed_updates: ["callback_query", "message"],
        drop_pending_updates: false
      })
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      console.error("Telegram setWebhook failed:", result.description || response.status);
      return res.status(502).json({ ok: false, error: "Telegram rejected webhook setup" });
    }
    return res.status(200).json({ ok: true, webhookUrl, description: result.description });
  } catch (error) {
    console.error("Webhook setup request failed:", error.message);
    return res.status(502).json({ ok: false, error: "Could not configure Telegram webhook" });
  }
}
