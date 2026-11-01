export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ ok: false });
  if (!process.env.MANUAL_RUN_KEY || req.headers["x-manual-run-key"] !== process.env.MANUAL_RUN_KEY) return res.status(401).json({ ok: false });
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!token || !chatId) return res.status(503).json({ ok: false, error: "Telegram settings missing" });
  try {
    const response = await fetch("https://api.telegram.org/bot" + token + "/sendMessage", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: "🐭 MYSHKA JOB RADAR: Telegram-з'єднання працює. Бот готовий надсилати вакансії щодня о 09:00 за Києвом." })
    });
    const result = await response.json();
    if (!response.ok || !result.ok) return res.status(502).json({ ok: false, error: result.description || "Telegram API error" });
    return res.status(200).json({ ok: true, messageSent: true });
  } catch (e) { return res.status(500).json({ ok: false, error: "Telegram request failed" }); }
}
