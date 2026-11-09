const TELEGRAM_API = "https://api.telegram.org";

async function telegram(method, token, payload) {
  const response = await fetch(TELEGRAM_API + "/bot" + token + "/" + method, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) throw new Error(data.description || "Telegram API request failed");
  return data.result;
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "Method not allowed" });
  }

  const expectedSecret = process.env.TELEGRAM_WEBHOOK_SECRET;
  if (!expectedSecret || req.headers["x-telegram-bot-api-secret-token"] !== expectedSecret) {
    return res.status(401).json({ ok: false, error: "Unauthorized webhook" });
  }

  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  const githubToken = process.env.MYSHKA_GITHUB_DISPATCH_TOKEN;
  if (!token || !chatId || !githubToken) {
    console.error("Telegram webhook configuration is incomplete.");
    return res.status(503).json({ ok: false, error: "Webhook backend is not fully configured" });
  }

  const update = req.body;
  if (!update || !Number.isInteger(update.update_id)) {
    return res.status(400).json({ ok: false, error: "Invalid Telegram update" });
  }

  const callback = update.callback_query;
  const message = update.message;
  const updateChatId = String(callback?.message?.chat?.id ?? message?.chat?.id ?? "");
  if (!updateChatId) return res.status(200).json({ ok: true, ignored: true });

  if (updateChatId !== String(chatId)) {
    if (callback?.id) {
      try {
        await telegram("answerCallbackQuery", token, {
          callback_query_id: callback.id,
          text: "Немає доступу до цього бота."
        });
      } catch (error) {
        console.warn("Could not reject unauthorized callback:", error.message);
      }
    }
    return res.status(200).json({ ok: true, ignored: true });
  }

  try {
    const dispatch = await fetch(
      "https://api.github.com/repos/omeljanpadovcky-create/T/dispatches",
      {
        method: "POST",
        headers: {
          "Accept": "application/vnd.github+json",
          "Authorization": "Bearer " + githubToken,
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ event_type: "telegram_update", client_payload: { update } })
      }
    );
    if (!dispatch.ok) {
      const details = await dispatch.text();
      throw new Error("GitHub dispatch HTTP " + dispatch.status + ": " + details.slice(0, 300));
    }

    if (callback?.id) {
      try {
        await telegram("answerCallbackQuery", token, {
          callback_query_id: callback.id,
          text: "Прийняв. Мишка обробляє дію…"
        });
      } catch (error) {
        console.warn("Callback toast could not be delivered:", error.message);
      }
    }
    return res.status(200).json({ ok: true, queued: true, updateId: update.update_id });
  } catch (error) {
    console.error("Telegram webhook dispatch failed:", error.message);
    if (callback?.id) {
      try {
        await telegram("answerCallbackQuery", token, {
          callback_query_id: callback.id,
          text: "Не вдалося передати дію. Спробуй ще раз."
        });
      } catch {}
    }
    return res.status(502).json({ ok: false, error: "Could not queue Telegram update" });
  }
}
