const RAW = "https://raw.githubusercontent.com/omeljanpadovcky-create/T/main/jobs/";

async function readJson(path) {
  const response = await fetch(RAW + path, {
    headers: { "Accept": "application/vnd.github+json" }
  });
  if (!response.ok) {
    throw new Error("Could not read " + path + ": HTTP " + response.status);
  }
  return response.json();
}

export default async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "Method not allowed" });
  }

  try {
    const [applications, statuses] = await Promise.all([
      readJson("applications.json"),
      readJson("statuses.json")
    ]);

    const items = Object.entries(applications || {}).map(([id, job]) => {
      const state = (statuses || {})[id] || {};
      return {
        id,
        title: job.title || "Untitled vacancy",
        company: job.company || "Company not specified",
        location: job.location || "Remote",
        url: job.url || "",
        source: job.source || "",
        score: Number(job.score || 0),
        status: state.status || job.status || "new",
        updatedAt: state.submitted_at || state.approved_at || state.prepared_at || state.skipped_at || null
      };
    }).sort((a, b) => {
      const order = {
        awaiting_approval: 0,
        approved: 1,
        selected: 2,
        new: 3,
        submitted_user_confirmed: 4,
        skipped: 5
      };
      return (order[a.status] ?? 9) - (order[b.status] ?? 9) || b.score - a.score;
    });

    res.setHeader("Cache-Control", "s-maxage=30, stale-while-revalidate=60");
    return res.status(200).json({
      ok: true,
      total: items.length,
      counts: items.reduce((acc, item) => {
        acc[item.status] = (acc[item.status] || 0) + 1;
        return acc;
      }, {}),
      items
    });
  } catch (error) {
    console.error("Applications endpoint failed:", error.message);
    return res.status(502).json({
      ok: false,
      error: "Application tracker is temporarily unavailable."
    });
  }
}
