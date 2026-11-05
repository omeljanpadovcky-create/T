# MYSHKA JOB RADAR — applications with your approval

## Existing search
- Daily search through GitHub Actions.
- Sources: Arbeitnow, RemoteOK, Remotive and Himalayas.
- Up to 10 new matches per run.
- No English-level filter: English requirements never automatically exclude a vacancy.
- No experience-level filter: internship, entry-level, junior, mid-level and senior roles can be considered.
- Candidate profile includes a two-year IT Step internship, represented as internship experience rather than paid employment.
- Search targets include 3D / Blender / Game Art, illustration, graphic and UI/UX design, Shopify / E-commerce, product listings, digital marketing and content roles.
- Telegram callbacks are polled every 5 minutes.

## Application preparation flow
1. **Відібрати вакансію** marks a job as selected; it does not submit anything.
2. **Підготувати повну заявку** creates an editable package in the Telegram conversation:
   - cover letter;
   - email subject and body;
   - short introduction;
   - suggested answers for common form questions;
   - salary wording based on the listing, or a request for the employer's range if salary is missing;
   - destination URL, extracted employer email (only if present in the listing), and field-by-field instructions.
3. Review the text and edit the cover letter if needed.
4. **ПІДТВЕРДЖУЮ ПАКЕТ** records your approval for that version.
5. Open the employer page and submit manually. Then press **Я ВЖЕ ВІДПРАВИВ ЗАЯВКУ** to update the tracker.

## Important safety and privacy rules
- This version does not automatically submit forms or send emails. It prepares the material and guides you to the employer's destination. Email/ATS submission integrations can be added later.
- A vacancy is never marked submitted just because it was selected or approved. The final status is recorded only after you explicitly confirm that you submitted it.
- Generated application text is sent to your private Telegram chat and is not written to the public repository.
- jobs/statuses.json stores workflow state only, not cover letters or answers.
- Do not add private contact details, portfolio URLs, CV links, or salary preferences to tracked JSON files. Configure them as GitHub Actions repository secrets instead.

## Optional candidate profile secrets
Repository → Settings → Secrets and variables → Actions:
- MYSHKA_CANDIDATE_NAME
- MYSHKA_PORTFOLIO_URL
- MYSHKA_PORTFOLIO_3D_URL
- MYSHKA_PORTFOLIO_GAME_ART_URL
- MYSHKA_PORTFOLIO_DESIGN_URL
- MYSHKA_PORTFOLIO_ILLUSTRATION_URL
- MYSHKA_CV_URL
- MYSHKA_CONTACT_EMAIL
- MYSHKA_SALARY_EXPECTATION

The non-sensitive defaults in jobs/profile.json describe the candidate's design practice, two-year IT Step internship, English level, approximate portfolio size and toolset. English level is retained for truthful application answers only; it is not a vacancy filter.

## Required existing secrets
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

Never commit secret values or send them in chat.
