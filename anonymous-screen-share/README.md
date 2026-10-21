# Anonymous Screen Share — consent-based starter

This folder is a starter specification for a private, link-based screen-sharing session.

## Important iPhone limitation
A normal Safari webpage cannot silently capture and broadcast an iPhone's entire screen. iOS requires the person sharing to deliberately start the system screen-broadcast flow. For full-device capture, build/sign an iOS app with Apple's supported screen-sharing APIs (ReplayKit on supported older versions; ScreenCaptureKit on supported newer versions) and show the system picker/confirmation.

## Intended flow
1. The sharer opens a session link.
2. The page clearly explains what will be shared and who can view it.
3. The sharer explicitly chooses **Start sharing** and approves iOS's system screen-broadcast prompt.
4. The viewer joins using a private session link.
5. The sharer can stop sharing at any time.

## Security requirements before production
- Use HTTPS and authenticated, short-lived session tokens.
- Do not make a session publicly discoverable; “anonymous” must not mean that anyone can watch.
- Display a persistent “LIVE — screen is being shared” indicator and a Stop control.
- Do not record by default. If recording is added, disclose it and ask separately.
- Never collect passwords, messages, or other screen content without the sharer's informed consent.
- Add expiration, rate limits, and server-side authorization for viewer access.

## Current status
This is documentation only, not a working screen-capture or streaming service. A production implementation needs a native iOS app/extension plus a WebRTC media/signaling backend and a viewer page. Do not promise automatic capture from a website.
