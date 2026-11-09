export default function handler(req, res) {
  res.status(200).json({
    ok: true,
    app: "ТРЕЙДМИШКА · JOB RADAR",
    version: "1.4.0",
    configured: {
      telegram: Boolean(process.env.TELEGRAM_BOT_TOKEN && process.env.TELEGRAM_CHAT_ID),
      deduplication: true,
      cronProtection: Boolean(process.env.CRON_SECRET)
    },
    applicationFlow: {
      packageGeneration: true,
      userApprovalRequired: true,
      externalEmailOrAtsSubmission: false,
      privateDraftsStoredInPublicRepository: false
    },
    schedule: "Telegram polling every 5 minutes; vacancy scans every 15 minutes via GitHub Actions",
    delivery: "Telegram vacancy cards and daily report",
    duplicateProtection: "Persistent jobs/seen.json state committed by GitHub Actions",
    minimumScore: 80,
    profile: "Remote 3D / Blender / Game Art / characters / props / environment art / illustration · all experience levels · English is not an exclusion filter · Ukraine / Europe / EMEA / worldwide where eligible"
  });
}
