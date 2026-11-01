export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ ok: false });
  if (!process.env.MANUAL_RUN_KEY || req.headers["x-manual-run-key"] !== process.env.MANUAL_RUN_KEY) return res.status(401).json({ ok: false });
  if (!process.env.CRON_SECRET) return res.status(503).json({ ok: false, error: "Cron secret missing" });
  try {
    const response = await fetch("https://myshka-job-radar.vercel.app/api/check", {
      method: "POST",
      headers: { authorization: "Bearer " + process.env.CRON_SECRET }
    });
    const result = await response.json();
    return res.status(response.status).json(result);
  } catch (e) { return res.status(502).json({ ok: false, error: "Could not trigger scan" }); }
}
