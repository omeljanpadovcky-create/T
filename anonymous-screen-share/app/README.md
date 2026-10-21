# Run locally (localhost:3000)

Requirements: Node.js 18 or newer.

1. Download this repository ZIP or clone the repo.
2. Open a terminal in `anonymous-screen-share/app`.
3. Run:

```bash
npm start
```

4. Open `http://localhost:3000`.

## Test
- Open the page in a browser that supports screen capture (usually desktop Chrome/Edge).
- Click **Create session & choose screen**, then explicitly choose a screen/window in the browser prompt.
- In a second browser window, select **Watch a session**, enter the six-character code, and connect.

## Limitations
- This is a minimal demo, not a production-secure service. Signaling rooms are in-memory and disappear when the server restarts.
- For remote internet access, HTTPS, authenticated session links, TURN support, rate limiting, and security review are needed.
- iPhone Safari generally cannot share the entire device screen through a normal webpage. Use a compatible native iOS app with Apple's system screen-broadcast consent flow for that use case.
- The viewer only receives a stream after the sharer starts it. This project does not secretly capture screens or record sessions.
