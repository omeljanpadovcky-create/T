# MYSHKA JOB RADAR — applications with your approval

## Search and filtering
- Telegram buttons are polled every 5 minutes through the same GitHub Actions workflow; vacancy scans run every 15 minutes. This keeps a single Telegram `getUpdates` consumer while separating callback responsiveness from vacancy discovery. Temporary callback errors do not prevent a scheduled vacancy scan from running.
- Minimum vacancy score: **80/100**. Scores below 80 are rejected; 80–89 are accepted matches and 90–100 are highest-priority matches.
- Sources currently integrated: Arbeitnow, RemoteOK, Remotive, Himalayas, We Work Remotely RSS, DOU, Djinni, Work.ua, Robota.ua, ZipRecruiter and ArtStation Jobs.
- Some HTML sources may return 403 or change their markup. The bot records source failures and continues with available feeds; it does not bypass access controls.
- Target roles: 3D / Blender / modeling, Game Art / game assets, character / environment / prop art, concept art, illustration, book covers, Photobashing and Matte Painting.
- English level and seniority are not automatic rejection filters. The listing's actual requirements are shown for manual review.
- Country-specific locations and explicit country-only requirements are rejected unless the posting clearly allows Ukraine or a broader region. Generic Remote listings still require a manual eligibility check.
- New matches are ranked by title and skill relevance. The bot sends new matches only; already-seen listings are not resent.
- Candidate profile includes a two-year IT Step internship, accurately described as internship experience rather than paid employment.

## Telegram vacancy sources
- Public channel previews are scanned from `t.me/s`: @ingamejob, @ingamejob_art, @young_gamedev, @devjobs, @gamedev_and_tech_vacancy and @devzonegd.
- The collector reads the latest public posts only; it does not join private groups, scrape private chats, or bypass Telegram restrictions.
- Telegram posts are treated as vacancy leads and pass through the same relevance, unpaid-role, remote-work, Ukraine/Europe eligibility, deduplication and user-approval checks as other sources.
- Generic "Remote" posts without Ukraine, Europe/EU/EMEA, worldwide or equivalent eligibility wording are excluded.
- Some channels publish digest posts or posts without direct employer links. In those cases the original Telegram post is preserved as the source link for manual review.

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
- Recommended: `MYSHKA_CONTACT_EMAIL`, `MYSHKA_PHONE`, `MYSHKA_CV_URL`
- Optional: `MYSHKA_CANDIDATE_NAME`, `MYSHKA_PORTFOLIO_URL`, `MYSHKA_PORTFOLIO_3D_URL`, `MYSHKA_PORTFOLIO_GAME_ART_URL`, `MYSHKA_PORTFOLIO_DESIGN_URL`, `MYSHKA_PORTFOLIO_ILLUSTRATION_URL`, `MYSHKA_SALARY_EXPECTATION`

Non-sensitive defaults in `jobs/profile.json` include the candidate's name, ArtStation portfolio, CV page, English level and skills. Contact email and salary preference remain unset unless supplied as secrets.

Never commit secret values or send them in chat.
