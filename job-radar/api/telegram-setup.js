export default async function handler(req, res) {
  if (req.method !== "GET" && req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed" });
  }
  const secret = process.env.CRON_SECRET;
  const auth = req.headers.authorization || "";
  if (!secret || auth !== "Bearer " + secret) {
    return res.status(401).json({ ok: false, error: "Unauthorized" });
  }
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) {
    return res.status(503).json({ ok: false, error: "Add TELEGRAM_BOT_TOKEN to Vercel Environment Variables first." });
  }
  try {
    const response = await fetch("https://api.telegram.org/bot" + token + "/getUpdates?limit=20&allowed_updates=%5B%22message%22%5D");
    const result = await response.json();
    if (!response.ok || !result.ok) {
      return res.status(502).json({ ok: false, error: "Telegram could not return updates. Check the bot token and send /start again." });
    }
    const matching = (result.result || [])
      .filter(update => update.message && update.message.chat && update.message.text)
      .filter(update => update.message.text.trim() === "/start" || update.message.text.trim().startsWith("/start@"))
      .sort((a, b) => b.update_id - a.update_id)[0];
    if (!matching) {
      return res.status(404).json({ ok: false, error: "No /start message found. Open the bot and send /start, then retry." });
    }
    return res.status(200).json({
      ok: true,
      chatId: String(matching.message.chat.id),
      chatType: matching.message.chat.type,
      message: "Save chatId as TELEGRAM_CHAT_ID in Vercel Environment Variables."
    });
  } catch (error) {
    console.error("Telegram setup error:", error.message);
    return res.status(500).json({ ok: false, error: "Could not contact Telegram." });
  }
}
