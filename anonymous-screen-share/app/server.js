const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const PORT = Number(process.env.PORT || 3000);
const ROOT = path.join(__dirname, "public");
const rooms = new Map();
const MAX_AGE_MS = 15 * 60 * 1000;

function roomFor(id) {
  let room = rooms.get(id);
  if (!room || Date.now() - room.updatedAt > MAX_AGE_MS) {
    room = { offer: null, answer: null, updatedAt: Date.now() };
    rooms.set(id, room);
  }
  room.updatedAt = Date.now();
  return room;
}

function send(res, status, data, type = "application/json; charset=utf-8") {
  res.writeHead(status, { "Content-Type": type, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
  res.end(type.startsWith("application/json") ? JSON.stringify(data) : data);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (req.method === "GET" && url.pathname === "/api/health") return send(res, 200, { ok: true, app: "anonymous-screen-share" });
  if (url.pathname.startsWith("/api/rooms/")) {
    const parts = url.pathname.split("/").filter(Boolean);
    const id = parts[2];
    const kind = parts[3];
    if (!/^[A-Z0-9]{6}$/.test(id || "")) return send(res, 400, { error: "Invalid room code" });
    if (req.method === "GET" && kind === "offer") return send(res, 200, { value: roomFor(id).offer });
    if (req.method === "GET" && kind === "answer") return send(res, 200, { value: roomFor(id).answer });
    if (req.method === "POST" && (kind === "offer" || kind === "answer")) {
      let raw = "";
      req.on("data", chunk => { raw += chunk; if (raw.length > 1_000_000) req.destroy(); });
      req.on("end", () => {
        try {
          const body = JSON.parse(raw || "{}");
          if (!body.value || typeof body.value !== "object" || typeof body.value.type !== "string" || typeof body.value.sdp !== "string") {
            return send(res, 400, { error: "Expected a WebRTC session description" });
          }
          roomFor(id)[kind] = body.value;
          return send(res, 200, { ok: true });
        } catch { return send(res, 400, { error: "Invalid JSON" }); }
      });
      return;
    }
    if (req.method === "DELETE" && kind === "room") {
      rooms.delete(id);
      return send(res, 200, { ok: true });
    }
    return send(res, 404, { error: "Unknown signaling endpoint" });
  }

  const requested = url.pathname === "/" ? "index.html" : url.pathname.replace(/^\/+/, "");
  const target = path.resolve(ROOT, requested);
  if (!target.startsWith(ROOT + path.sep) && target !== path.join(ROOT, "index.html")) return send(res, 403, { error: "Forbidden" });
  fs.readFile(target, (err, data) => {
    if (err) return send(res, 404, "Not found", "text/plain; charset=utf-8");
    const ext = path.extname(target);
    const types = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8" };
    send(res, 200, data, types[ext] || "application/octet-stream");
  });
});

setInterval(() => {
  for (const [id, room] of rooms) if (Date.now() - room.updatedAt > MAX_AGE_MS) rooms.delete(id);
}, 60_000).unref();

server.listen(PORT, "0.0.0.0", () => {
  console.log(`Anonymous Screen Share demo listening on http://localhost:${PORT}`);
  console.log("Use only with people who knowingly start and control their own screen share.");
});
