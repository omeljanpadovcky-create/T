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
    schedule: "09:00 and 16:00 Europe/Kyiv (DST-aware hourly GitHub Actions runner)",
    delivery: "Telegram vacancy cards and daily report",
    duplicateProtection: "Persistent jobs/seen.json state committed by GitHub Actions",
    profile: "Remote 3D / Blender / Game Art / characters / props / environment art · all experience levels · English is not an exclusion filter · ArtStation, Robota.ua, Work.ua, DOU, Djinni, Remotive, RemoteOK, Himalayas, We Work Remotely"
  });
}
