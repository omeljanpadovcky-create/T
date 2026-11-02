# ТРЕЙДМИШКА — Job Search

GitHub Actions runs a daily search for remote paid opportunities and sends matching listings to Telegram.

## Search profile
- Remote roles that explicitly allow applicants from Ukraine, Europe or worldwide.
- 3D Artist, Blender Artist, 3D Modeler, Character Artist, Game Artist, Environment / Prop Artist.
- Illustration, Concept Artist, Book Cover Artist and Cover Illustrator.
- Trainee / junior / middle; senior listings are reviewed against actual requirements rather than assumed suitable.
- Paid freelance, contract, part-time and full-time work.
- Maximum 10 matches per run; fewer are sent when fewer relevant jobs exist.

## Sources
Public feeds: Arbeitnow, RemoteOK, Remotive, Jobicy and Himalayas. Availability and completeness depend on each provider's public API. Some sources do not publish salary or country eligibility, so those details must be checked on the employer's page.

## GitHub Actions secrets
- `TELEGRAM_BOT_TOKEN` — token from BotFather.
- `TELEGRAM_CHAT_ID` — private chat ID after sending /start to the bot.

Add both in repository Settings → Secrets and variables → Actions. Never commit them.

## Schedule
The workflow runs daily at 07:00 UTC and can also be started manually from Actions → ТРЕЙДМИШКА — щоденний пошук вакансій → Run workflow.

## Current limits
The current Telegram workflow sends vacancy links and match scores. It does not submit applications, bypass logins/CAPTCHAs, or yet provide interactive approve/edit/skip buttons and persistent application-status tracking. Review each employer page before applying.
