const POSITIVE = [
  ["3d character artist", 16], ["character artist", 13], ["blender artist", 13],
  ["game asset artist", 14], ["game asset", 12], ["3d artist", 12],
  ["3d modeler", 12], ["3d modeller", 12], ["3d model", 10],
  ["3d generalist", 10], ["environment artist", 11], ["prop artist", 11],
  ["hard surface", 10], ["game artist", 9], ["game art", 8],
  ["texture artist", 8], ["3d sculptor", 8], ["sculptor", 6],
  ["3d animator", 9], ["3d layout", 10], ["3d visual", 10], ["blender specialist", 9],
  ["blender", 9], ["zbrush", 4], ["substance painter", 4],
  ["maya", 3], ["unreal engine", 3], ["unity", 2]
];

const TITLE_EXCLUDES = [
  "ai trainer", "ai data annotator", "data annotation", "data annotator",
  "prompt engineer", "llm evaluator", "machine learning engineer",
  "sales", "account executive", "customer support", "support specialist",
  "customer success", "recruiter", "business development",
  "senior", "lead", "principal", "director", "head of"
];

const SOURCES = [
  {
    name: "Remotive · 3D",
    url: "https://remotive.com/api/remote-jobs?search=3d%20artist",
    parse: (json) => (json.jobs || []).map(j => ({
      id: "remotive:" + j.id, title: j.title, company: j.company_name,
      url: j.url, description: j.description || "", tags: j.tags || [],
      location: j.candidate_required_location || "Remote",
      salary: j.salary || "", type: j.job_type || "", source: "Remotive"
    }))
  },
  {
    name: "Remotive · Blender",
    url: "https://remotive.com/api/remote-jobs?search=blender",
    parse: (json) => (json.jobs || []).map(j => ({
      id: "remotive:" + j.id, title: j.title, company: j.company_name,
      url: j.url, description: j.description || "", tags: j.tags || [],
      location: j.candidate_required_location || "Remote",
      salary: j.salary || "", type: j.job_type || "", source: "Remotive"
    }))
  },
  {
    name: "Remotive · Game Art",
    url: "https://remotive.com/api/remote-jobs?search=game%20artist",
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
  },
  ...["blender", "3d artist", "character artist", "game artist", "environment artist", "3d modeler", "prop artist"].map(query => ({
    name: "Himalayas · " + query,
    url: "https://himalayas.app/jobs/api/search?q=" + encodeURIComponent(query) + "&sort=recent",
    parse: (json) => (json.jobs || []).map(j => ({
      id: "himalayas:" + (j.guid || j.applicationLink || j.title),
      guid: j.guid || "",
      title: j.title,
      company: j.companyName,
      url: j.applicationLink || "",
      description: j.description || j.excerpt || "",
      tags: [...(j.categories || []), ...(j.parentCategories || [])],
      location: (j.locationRestrictions || []).length
        ? "Remote · " + j.locationRestrictions.join(", ")
        : "Remote · Worldwide",
      locationRestrictions: j.locationRestrictions || [],
      salary: [j.minSalary, j.maxSalary].filter(v => v !== null && v !== undefined).join("–") +
        (j.currency ? " " + j.currency : "") + (j.salaryPeriod ? "/" + j.salaryPeriod : ""),
      salaryMin: j.minSalary,
      salaryPeriod: j.salaryPeriod || "",
      currency: j.currency || "",
      level: Array.isArray(j.seniority) ? j.seniority.join(" ") : (j.seniority || ""),
      type: j.employmentType || "",
      source: "Himalayas"
    }))
  }))
];

function plainText(value) {
  return String(value || "").replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&")
    .replace(/&#39;|&apos;/gi, "'").replace(/&quot;/gi, '"')
    .replace(/\s+/g, " ").trim();
}

function englishRequirementTooHigh(text) {
  const patterns = [
    /\b(?:english|spoken english)\s*(?:level|proficiency)?\s*[:\-]?\s*(?:b2\+?|c1|c2|fluent|native|advanced|upper[- ]intermediate)\b/i,
    /\b(?:b2\+?|c1|c2)\s+(?:level\s+)?english\b/i,
    /\b(?:fluent|native|advanced|upper[- ]intermediate)\s+(?:in\s+)?english\b/i,
    /\benglish\s+(?:is\s+)?(?:fluent|native|advanced|upper[- ]intermediate)\b/i,
    /\b(?:full professional|professional working|near-native)\s+proficiency\b/i
  ];
  return patterns.some(pattern => pattern.test(text));
}

function salaryBelowFive(salaryValue) {
  const salary = String(salaryValue || "");
  const match = salary.match(/(?:\$|usd\s*)(\d+(?:\.\d+)?)(?:\s*[-–]\s*(?:\$|usd\s*)?\d+(?:\.\d+)?)?\s*(?:\/\s*(?:h|hr|hour)|per\s+(?:h|hr|hour)|hourly)\b/i);
  return Boolean(match && Number(match[1]) < 5);
}

function isAllowedLocation(job) {
  if (job.source !== "Himalayas") return true;
  const restrictions = job.locationRestrictions || [];
  if (!restrictions.length) return true;
  const allowed = new Set([
    "ukraine", "europe", "european union", "emea", "united kingdom", "turkey", "türkiye",
    "worldwide", "anywhere", "remote",
    "poland", "germany", "france", "spain", "italy", "netherlands", "belgium",
    "czechia", "czech republic", "slovakia", "romania", "bulgaria", "hungary",
    "austria", "sweden", "norway", "denmark", "finland", "estonia", "latvia",
    "lithuania", "croatia", "slovenia", "serbia", "portugal", "ireland",
    "switzerland", "greece", "cyprus", "iceland", "luxembourg", "moldova"
  ]);
  return restrictions.some(value => allowed.has(String(value).toLowerCase()));
}

function scoreJob(job) {
  const title = plainText(job.title).toLowerCase();
  const body = plainText(job.description).toLowerCase();
  const tags = (job.tags || []).map(plainText).join(" ").toLowerCase();
  const level = String(job.level || "").toLowerCase();
  if (!title || !job.url) return 0;
  if (/\\b2d\\b/i.test(title) && !/\\b3d\\b/i.test(title)) return 0;
  if (/\\bbim\\b/i.test(title)) return 0;

  if (TITLE_EXCLUDES.some(word => title.includes(word) || tags.includes(word))) return 0;
  if (/senior|lead|principal|director|manager|executive/.test(level)) return 0;
  if (!isAllowedLocation(job)) return 0;
  const searchable = title + " " + tags + " " + body.slice(0, 7000);
  if (/\b(?:unpaid|volunteer|commission[- ]only|no salary|equity only)\b/i.test(searchable)) return 0;
  if (englishRequirementTooHigh(searchable)) return 0;
  if (salaryBelowFive(job.salary)) return 0;
  if (job.salaryPeriod === "hourly" && String(job.currency).toUpperCase() === "USD" &&
      typeof job.salaryMin === "number" && job.salaryMin < 5) return 0;

  const remoteText = (String(job.location || "") + " " + body.slice(0, 1800)).toLowerCase();
  if (!/remote|anywhere|worldwide|work from home|distributed|europe|emea|ukraine/.test(remoteText)) return 0;
  if (/\b(?:us|usa|united states|canada|australia)\s+only\b|only\s+(?:us|usa|united states|canada|australia)\s+(?:based|residents|candidates)/i.test(remoteText)) return 0;

  let score = 0;
  for (const [word, points] of POSITIVE) {
    if (title.includes(word)) score += points;
    else if (tags.includes(word)) score += Math.round(points * 0.65);
    else if (body.slice(0, 7000).includes(word)) score += Math.round(points * 0.25);
  }
  if (/(junior|entry[- ]level|associate|mid[- ]level)/i.test(title)) score += 4;
  if (/(ukraine|europe|emea|worldwide|anywhere)/i.test(remoteText)) score += 2;
  return score >= 8 ? Math.min(100, score) : 0;
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
      headers: { "User-Agent": "MyshkaJobRadar/1.1 (personal job alert bot)", "Accept": "application/json" }
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

function canonicalId(job) {
  try {
    const url = new URL(job.url);
    return (url.hostname + url.pathname).replace(/\/$/, "").toLowerCase();
  } catch {
    return String(job.id || job.url);
  }
}

async function wasAlreadySent(job) {
  const base = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!base || !token) return false;
  try {
    const key = encodeURIComponent("myshka-job-radar:" + canonicalId(job));
    const response = await fetch(base.replace(/\/$/, "") + "/exists/" + key, {
      headers: { Authorization: "Bearer " + token }
    });
    if (!response.ok) throw new Error("Redis HTTP " + response.status);
    const result = await response.json();
    return Number(result.result) > 0;
  } catch (error) {
    console.error("Deduplication lookup failed:", error.message);
    return false;
  }
}

async function markAsSent(jobs) {
  const base = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!base || !token) return false;
  for (const job of jobs) {
    const key = encodeURIComponent("myshka-job-radar:" + canonicalId(job));
    const response = await fetch(base.replace(/\/$/, "") + "/set/" + key + "/1/EX/2592000", {
      method: "POST", headers: { Authorization: "Bearer " + token }
    });
    if (!response.ok) throw new Error("Redis write failed: HTTP " + response.status);
    const result = await response.json();
    if (result.error) throw new Error(result.error);
  }
  return true;
}

async function sendTelegram(jobs, meta) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!token || !chatId) throw new Error("Telegram is not configured");

  const top = jobs.slice(0, 8);
  const lines = [
    "🐭 <b>MYSHKA JOB RADAR</b>",
    top.length
      ? "Знайшов " + top.length + " нових вакансій під твій профіль:"
      : "Сьогодні нових релевантних вакансій не знайшов.",
    "Перевірено джерел: " + meta.sourcesOk + "/" + SOURCES.length,
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
  if (meta.sourceErrors.length) {
    lines.push("⚠️ Частина джерел тимчасово недоступна: " +
      meta.sourceErrors.map(x => escapeHtml(x.source)).join(", "));
    lines.push("");
  }
  lines.push("Фільтри: 3D/Blender/Game Art · Remote · Junior/Middle · English A2.");
  lines.push("", '🎨 <a href="https://www.artstation.com/jobs/all?work_remotely=true">ArtStation: remote-вакансії</a>');

  const response = await fetch("https://api.telegram.org/bot" + token + "/sendMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId, text: lines.join("\n"), parse_mode: "HTML",
      disable_web_page_preview: true
    })
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
  if (!secret) return res.status(503).json({ ok: false, error: "CRON_SECRET is not configured." });
  if (auth !== "Bearer " + secret) return res.status(401).json({ ok: false, error: "Unauthorized" });
  if (!process.env.TELEGRAM_BOT_TOKEN || !process.env.TELEGRAM_CHAT_ID) {
    return res.status(503).json({ ok: false, error: "Telegram is not configured." });
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

  const sourcesOk = sourceResults.filter(result => result.status === "fulfilled").length;
  if (sourcesOk === 0) {
    return res.status(502).json({ ok: false, error: "All job sources failed. Telegram alert was not sent.", sourceErrors });
  }

  const unique = new Map();
  for (const job of all) {
    const score = scoreJob(job);
    if (!score) continue;
    const key = canonicalId(job);
    const old = unique.get(key);
    if (!old || score > old.score) unique.set(key, { ...job, score });
  }

  const ranked = [...unique.values()].sort((a, b) => b.score - a.score);
  const fresh = [];
  for (const job of ranked) {
    if (fresh.length >= 8) break;
    if (!(await wasAlreadySent(job))) fresh.push(job);
  }

  try {
    await sendTelegram(fresh, { sourcesOk, sourceErrors });
    let deduplication = false;
    try {
      deduplication = await markAsSent(fresh);
    } catch (error) {
      console.error("Could not save sent job IDs:", error.message);
    }
    return res.status(200).json({
      ok: true, scanned: all.length, matched: ranked.length, sent: fresh.length,
      sourcesOk, totalSources: SOURCES.length, sourceErrors, deduplication,
      note: deduplication
        ? "Persistent duplicate filtering active for 30 days."
        : "Redis is not connected; cross-run duplicate filtering is not active."
    });
  } catch (error) {
    console.error("Job Radar run failed:", error.message);
    return res.status(500).json({ ok: false, error: error.message, scanned: all.length, matched: ranked.length });
  }
}
