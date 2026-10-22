# MYSHKA ETSY AI

MYSHKA is a research workspace for Etsy sellers. It searches public active listings through Etsy Open API v3, summarizes the available data, estimates unit margin from seller-entered assumptions, drafts listing copy with AI, and provides a human review checklist.

**It does not create, edit, renew, or publish Etsy listings.** Active listings, prices and favorites are not evidence of sales volume, verified demand, conversion rate or profit.

## Vercel setup

The app now lives at the repository root. Use the Vercel project named `myshka-etsy-ai` (or import this repo with Root Directory set to the repository root) and deploy `main`.

Set these as Vercel Environment Variables for Production and Preview as appropriate, then redeploy:

- `ETSY_API_KEY`: the full Etsy API value in `keystring:shared_secret` format.
- `MYSHKA_ACCESS_TOKEN`: a long random private token that gates both Etsy search and AI drafting. Enter the same token into the app's **Private AI access token** field. Do not share it.
- `OPENAI_API_KEY`: optional; enables AI listing draft generation. Keep it server-side only.
- `OPENAI_MODEL`: optional; defaults to `gpt-4.1-mini`.

Do not set `OPENAI_API_KEY` until `MYSHKA_ACCESS_TOKEN` is configured. Both Etsy search and the AI endpoint check the access token before any external API request. Never put API keys in Git or browser code.

Etsy's API requires the `x-api-key` header formatted as `keystring:shared_secret`. The Etsy app must be active/approved and allowed to search marketplace listings. See [Etsy API authentication](https://developer.etsy.com/documentation/essentials/authentication/).

## Safety and policy

- Search results describe active marketplace listings, not verified sales or demand.
- Profit estimates use seller-entered assumptions; verify current platform fees and every real cost.
- AI outputs are drafts. A person must verify all product claims, tags, imagery, authorship and category-specific restrictions.
- The application has no Etsy listing-publishing endpoint.
- Disclose AI use in the item description where Etsy requires it. Keep images accurate, including any required genuine, unedited product photo.
- Functional guides, patterns, recipes and instructions that buyers rely on must be the seller's own work, not AI-generated.
- Review [Etsy Creativity Standards](https://www.etsy.com/legal/creativity/) and current listing image requirements before publishing.

## Saved data

Saved niche ideas and drafts are stored in this browser's local storage and can be exported. Cross-device database sync is not configured. Never save secrets in research notes.

## API routes

- `GET /api/health` — safe configuration status; never returns secrets.
- `GET /api/etsy/test` — protected live connection check using a fixed five-listing read-only Etsy query. Open the app, enter the same `MYSHKA_ACCESS_TOKEN` configured in Vercel, and select **Test Etsy API** in the Connection status panel.
- `GET /api/etsy/search?keywords=personalized%20dog%20collar&limit=40` — protected active-listing search.
- `POST /api/ai/draft` — protected AI drafting; output remains a draft for human review.

The connection test requires both `MYSHKA_ACCESS_TOKEN` and `ETSY_API_KEY` to be set in Vercel. It confirms API access only; it does not measure demand or sales.
