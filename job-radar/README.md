# ТРЕЙДМИШКА — Job Radar

The GitHub Actions workflows provide the daily job search and Telegram callback processing. The primary search runs at 07:00 UTC. Telegram inline-button actions are checked every 5 minutes.

## Profile
- Remote work: Ukraine, Europe and worldwide where explicitly eligible.
- Roles: 3D / Blender / Game Art / Illustration / Concept Art / Book Cover.
- English: avoid explicit B2+ requirements.
- Up to 10 new matches per run.

## Telegram workflow
Each vacancy message includes buttons to open, confirm, skip, generate a cover-letter draft, or mark as applied. Statuses are stored in the repository. No application is submitted without the user's own action.

## Deployment
The GitHub Actions workflows are the primary scheduler and callback processor. The Vercel API is optional and is not required for Telegram button processing.
