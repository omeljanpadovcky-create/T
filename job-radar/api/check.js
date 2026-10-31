const SEARCH_TERMS = [
  "3d artist", "blender artist", "3d character artist", "character artist",
  "game asset artist", "3d modeler", "3d modeller", "3d generalist",
  "environment artist", "prop artist", "hard surface artist"
];

const POSITIVE = [
  ["3d character", 12], ["character artist", 11], ["blender", 9],
  ["game asset", 10], ["3d artist", 9], ["3d model", 8],
  ["3d modeler", 9], ["3d modeller", 9], ["environment artist", 8],
  ["prop artist", 8], ["hard surface", 7], ["maya", 4],
  ["zbrush", 5], ["substance painter", 5], ["game art", 6],
  ["unreal engine", 4], ["unity", 3], ["remote", 2]
];

const NEGATIVE = [
  "ai trainer", "ai data annotator", "data annotation", "prompt engineer",
  "llm evaluator", "machine learning engineer", "sales", "account executive",
  "customer support", "commission only", "unpaid", "volunteer", "internship unpaid"
];

const SOURCES = [
  {
    name: "Remotive",
    url: "https://remotive.com/api/remote-jobs?search=3d%20artist",
    parse: (json) => (json.jobs || []).map(j => ({
      id: "remotive:" + j.id, title: j.title, company: j.company_name,
      url: j.url, description: j.description || "", tags: j.tags || [],
      location: j.candidate_required_location || "Remote",
      salary: j.salary || "", type: j.job_type || "", source: "Remotive"
    }))
  },
  {
    name: "RemoteOK",
    url: "https://remoteok.com/api",
    parse: (json) => (Array.isArray(json) ? json.slice(1) : []).map(j => ({
      id: "remoteok:" + j.id, title: j.position, company: j.company,
      url: j.url, description: j.description || "", tags: j.tags || [],
      location: j.location || "Remote",
      salary: [j.salary_min, j.salary_max].filter(Boolean).join("–"),
      type: j.job_type || "", source: "RemoteOK"
    }))
  },
  {
    name: "Arbeitnow",
    url: "https://www.arbeitnow.com/api/job-board-api",
    parse: (json) => (json.data || []).map(j => ({
      id: "arbeitnow:" + (j.slug || j.url), title: j.title, company: j.company_name,
      url: j.url, description: j.description || "", tags: j.tags || [],
      location: j.location || "Remote",
      salary: j.salary || "", type: j.job_types || "", source: "Arbeitnow"
    }))
  }
];

function plainText(value) {
  return String(value || "").replace(/<[^>]*>/g, " ").replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();
}

function scoreJob(job) {
  const title = plainText(job.title).toLowerCase();
  const body = plainText(job.description).toLowerCase();
  const tags = (job.tags || []).join(" ").toLowerCase();
  const searchable = title + " " + tags + " " + body.slice(0, 5000);
  if (!title || !job.url) return 0;
  if (NEGATIVE.some(word => title.includes(word) || searchable.includes(word))) return 0;
  const salary = String(job.salary || "").toLowerCase();
  const hourly = salary.match(/(?:\\$|usd\\s*)(\\d+(?:\\.\\d+)?)\\s*(?:\\/|per\\s+)?(?:hour|hr)\\b/);
  if (hourly && Number(hourly[1]) < 5) return 0;

  const remoteText = (job.location + " " + body.slice(0, 1200)).toLowerCase();
  const isRemote = /remote|anywhere|worldwide|work from home|distributed/.test(remoteText);
  if (!isRemote) return 0;

  let score = 0;
  for (const [word, points] of POSITIVE) {
    if (searchable.includes(word)) score += points;
  }
  if (score < 7) return 0;
  if (/junior|entry.level|associate|mid.level/.test(title)) score += 3;
  if (/senior|lead|principal|director|head of/.test(title)) score -= 4;
  if (/ukraine|europe|emea|worldwide|anywhere/.test(remoteText)) score += 2;
  return Math.max(0, Math.min(100, score));
}

function escapeHtml(value) {
  return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

async function fetchJson(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { "User-Agent": "MyshkaJobRadar/1.0 (personal job alert bot)", "Accept": "application/json" }
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

async function isNew(id) {
  const base = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!base || !token) return true;
  try {
    const key = encodeURIComponent("myshka-job-radar:" + id);
    const response = await fetch(base.replace(/\/$/, "") + "/set/" + key + "/1/EX/2592000/NX", {
      method: "POST", headers: { Authorization: "Bearer " + token }
    });
    const result = await response.json();
    return result.result === "OK";
  } catch (error) {
    console.error("Deduplication store error:", error.message);
    return true;
  }
}

async function sendTelegram(jobs) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!token || !chatId) throw new Error("Telegram is not configured");

  const top = jobs.slice(0, 8);
  const lines = [
    "🐭 <b>MYSHKA JOB RADAR</b>",
    "Знайшов " + jobs.length + " нових вакансій, що відповідають твоєму профілю:",
    ""
  ];
  for (let i = 0; i < top.length; i++) {
    const j = top[i];
    lines.push("<b>" + (i + 1) + ". " + escapeHtml(j.title) + "</b>");
    lines.push("🏢 " + escapeHtml(j.company || "Компанія не вказана"));
    lines.push("🌍 " + escapeHtml(j.location || "Remote") + " · " + escapeHtml(j.source));
    if (j.salary) lines.push("💰 " + escapeHtml(j.salary));
    lines.push("🎯 Відповідність: " + j.score + "/100");
    lines.push('<a href="' + escapeHtml(j.url) + '">Відкрити вакансію</a>');
    lines.push("");
  }
  if (jobs.length > top.length) lines.push("Ще " + (jobs.length - top.length) + " знайдено, показую найкращі 8.");
  lines.push("", "Фокус: 3D Character Artist · Blender · Game Assets · Junior 3D Artist.");
  const text = lines.join("\n");

  const response = await fetch("https://api.telegram.org/bot" + token + "/sendMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text, parse_mode: "HTML", disable_web_page_preview: true })
  });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error("Telegram API error: " + (result.description || response.status));
  return result;
}

export default async function handler(req, res) {
  if (req.method !== "GET" && req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed" });
  }
  const secret = process.env.CRON_SECRET;
  const auth = req.headers.authorization || "";
  if (secret && auth !== "Bearer " + secret) {
    return res.status(401).json({ ok: false, error: "Unauthorized" });
  }
  if (!process.env.TELEGRAM_BOT_TOKEN || !process.env.TELEGRAM_CHAT_ID) {
    return res.status(503).json({ ok: false, error: "Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Vercel Environment Variables." });
  }

  const sourceResults = await Promise.allSettled(SOURCES.map(async source => {
    const data = await fetchJson(source.url);
    return source.parse(data);
  }));

  const all = [];
  const sourceErrors = [];
  sourceResults.forEach((result, index) => {
    if (result.status === "fulfilled") all.push(...result.value);
    else sourceErrors.push({ source: SOURCES[index].name, error: result.reason?.message || "Fetch failed" });
  });

  const unique = new Map();
  for (const job of all) {
    const score = scoreJob(job);
    if (!score) continue;
    const key = job.url;
    const old = unique.get(key);
    if (!old || score > old.score) unique.set(key, { ...job, score });
  }

  const ranked = [...unique.values()].sort((a, b) => b.score - a.score);
  const fresh = [];
  for (const job of ranked) {
    if (fresh.length >= 20) break;
    if (await isNew(job.id)) fresh.push(job);
  }

  try {
    if (fresh.length) await sendTelegram(fresh);
    return res.status(200).json({
      ok: true, scanned: all.length, matched: ranked.length, sent: fresh.length,
      sources: sourceResults.filter(r => r.status === "fulfilled").length,
      sourceErrors,
      note: process.env.UPSTASH_REDIS_REST_URL ? "Persistent duplicate filtering enabled." : "Set Upstash Redis variables to prevent repeats across daily runs."
    });
  } catch (error) {
    console.error(error);
    return res.status(500).json({ ok: false, error: error.message, scanned: all.length, matched: ranked.length });
  }
}
