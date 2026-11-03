export default function handler(req, res) {
  res.status(200).json({
    ok: true,
    app: "ТРЕЙДМИШКА · JOB RADAR",
    version: "1.4.0",
    configured: {
      telegram: Boolean(process.env.TELEGRAM_BOT_TOKEN && process.env.TELEGRAM_CHAT_ID),
      deduplication: Boolean(process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN),
      cronProtection: Boolean(process.env.CRON_SECRET)
    },
    applicationFlow: {
      packageGeneration: true,
      userApprovalRequired: true,
      externalEmailOrAtsSubmission: false,
      privateDraftsStoredInPublicRepository: false
    },
    schedule: "GitHub Actions daily at 07:00 UTC (09:00 Kyiv in winter, 10:00 in summer)",
    profile: "Remote 3D / Blender / Game Art / Illustration · Europe/Worldwide · English A2 · up to 10 daily matches · Himalayas + Remotive + RemoteOK + Arbeitnow"
  });
}
