export default function handler(req, res) {
  res.status(200).json({
    ok: true,
    app: "MYSHKA JOB RADAR",
    version: "1.0.0",
    configured: {
      telegram: Boolean(process.env.TELEGRAM_BOT_TOKEN && process.env.TELEGRAM_CHAT_ID),
      deduplication: Boolean(process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN),
      cronProtection: Boolean(process.env.CRON_SECRET)
    },
    schedule: "Daily at 07:00 UTC (09:00 Kyiv time)"
  });
}
