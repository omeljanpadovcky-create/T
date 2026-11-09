# MYSHKA JOB RADAR — applications with your approval

## Search and filtering
- A fresh vacancy scan runs hourly through GitHub Actions; Telegram buttons and messages are polled every 5 minutes.
- Sources currently integrated: Arbeitnow, RemoteOK, Remotive, Himalayas, We Work Remotely RSS, Jobicy public API, Working Nomads public JSON feed, WorkinGames Ukraine listings, DOU, Djinni, Work.ua, Robota.ua, ZipRecruiter and ArtStation Jobs. The public collectors include ArtStation, Djinni, Work.ua, Robota.ua and WorkinGames; API/RSS feeds include Jobicy and Working Nomads. Public access and page structures can fail independently. Jobicy's public API exposes recent remote listings; Working Nomads is consumed as a public JSON feed; WorkinGames is currently scoped to its Ukraine game-jobs listing.
- Some HTML sources may return 403 or change their markup. The bot records source failures and continues with available feeds; it does not bypass access controls. LinkedIn and Upwork are confirmed as candidate accounts but are not authenticated vacancy integrations. Fiverr is a freelance-service marketplace rather than a conventional job board; inquiries should be tracked separately.
- Target roles: 3D / Blender / modeling, Game Art / game assets, character / environment / prop art, concept art, illustration, book covers, Photobashing and Matte Painting.
- English level and seniority are not automatic rejection filters. The listing's actual requirements are shown for manual review.
- Country-specific locations and explicit country-only requirements are rejected unless the posting clearly allows Ukraine or a broader region. Generic Remote listings still require a manual eligibility check.
- New matches are ranked by title and skill relevance. The bot sends new matches only; already-seen listings are not resent.
- Candidate profile includes a two-year IT Step internship, accurately described as internship experience rather than paid employment.

## Application preparation flow
1. Review the vacancy card and open the original employer listing.
2. Choose **Підходить — підготувати відгук** to generate an editable application package.
3. Review the cover letter, email, short introduction, suggested form answers, CV and portfolio links.
4. Edit the cover letter if needed.
5. Press **ПІДТВЕРДИТИ ПАКЕТ** only after reviewing the text.
6. Open the employer page and submit manually. Then press **Я ВЖЕ ВІДПРАВИВ ЗАЯВКУ** to update the tracker.

## Safety and privacy
- The bot prepares application material but does not submit forms or send emails to employers.
- A vacancy is marked submitted only after the user explicitly confirms it.
- Generated application text is sent to the private Telegram chat, not stored in the public repository.
- Do not commit private contact details, CV links, or salary preferences to tracked JSON files. Configure them as GitHub Actions repository secrets.

## Candidate profile secrets
Repository → Settings → Secrets and variables → Actions:
- Required: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Recommended: `MYSHKA_CONTACT_EMAIL`, `MYSHKA_PHONE`, `MYSHKA_CV_URL` (set only to a verified, publicly accessible CV URL)
- Optional: `MYSHKA_CANDIDATE_NAME`, `MYSHKA_PORTFOLIO_URL`, `MYSHKA_PORTFOLIO_3D_URL`, `MYSHKA_PORTFOLIO_GAME_ART_URL`, `MYSHKA_PORTFOLIO_DESIGN_URL`, `MYSHKA_PORTFOLIO_ILLUSTRATION_URL`, `MYSHKA_SALARY_EXPECTATION`

Non-sensitive defaults in `jobs/profile.json` include the candidate's name, ArtStation portfolio, English level and skills. The previous CV URL was unverified and has been removed; set `MYSHKA_CV_URL` only after confirming the correct CV link. Contact email, phone, CV URL and salary preference remain unset unless supplied as repository secrets. The account/source capability matrix is maintained in `jobs/platforms.json`.

Never commit secret values or send them in chat.
