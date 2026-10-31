export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ ok: false, error: "Method not allowed" });
  if (!process.env.MANUAL_RUN_KEY || req.query.key !== process.env.MANUAL_RUN_KEY) {
    return res.status(401).json({ ok: false, error: "Unauthorized" });
  }
  if (!process.env.CRON_SECRET) return res.status(503).json({ ok: false, error: "Cron secret is missing" });
  const { default: runCheck } = await import("./check.js");
  return runCheck({
    method: "POST",
    headers: { authorization: "Bearer " + process.env.CRON_SECRET }
  }, res);
}
