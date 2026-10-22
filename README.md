# MYSHKA ETSY AI

A seller-facing research workspace for Etsy. It searches public active listings through Etsy Open API v3, summarizes prices in the returned sample, estimates per-item margin from seller-entered costs, and optionally drafts listing copy through OpenAI.

**No listing creation or automatic publishing is implemented.** Search results are active listings, not evidence of sales or proof of demand. Saved research currently lives in this browser's local storage and can be exported.

## Vercel setup

Import the repository from GitHub into Vercel with the repository root as the project Root Directory. Set these as server-side Environment Variables, then redeploy:

- `ETSY_API_KEY`: Etsy keystring, or the combined `keystring:shared_secret`.
- `ETSY_SHARED_SECRET`: required only when `ETSY_API_KEY` contains only the keystring.
- `OPENAI_API_KEY`: optional; enables AI draft generation.
- `OPENAI_MODEL`: optional; defaults to `gpt-4o-mini`.

The Etsy API requires the `x-api-key` request header in `keystring:shared_secret` format. Credentials are read only by serverless functions and are never sent to the browser. Etsy access depends on the app's approval/access level. See [Etsy API authentication](https://developer.etsy.com/documentation/essentials/authentication/).

## GitHub Pages

GitHub Pages can render the static interface but cannot run the `/api` endpoints. Use the Vercel URL directly, or click **API** and configure the Vercel deployment URL in the GitHub Pages copy.

## Guardrails

- The app does not publish, edit, or create Etsy listings.
- Marketplace metrics are not fabricated. Missing fields are shown as unavailable.
- Margin is an estimate based on costs and fee percentage entered by the seller.
- AI-generated copy is a draft and must be reviewed by a person.
- AI prompts are instructed not to invent product claims or generate functional guides, recipes, craft patterns, or instructions buyers rely on.
- For AI-created items, sellers should accurately disclose AI use in the listing description as required by Etsy's current rules.
- Verify category-specific requirements before using a draft.

## Local saves

Ideas are saved to this browser's `localStorage`. Export JSON to back them up. Cross-device database sync is not configured yet; never place a database service key in browser code.

Environment example: `.env.example`. Do not commit actual secrets.