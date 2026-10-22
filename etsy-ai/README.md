# MYSHKA ETSY AI

A separate Etsy research and listing-draft app, isolated from the crypto tools in the parent repository.

## What is included
- Etsy Open API v3 active-listing keyword search.
- Market snapshot from returned listings (prices and favorites where supplied); this is not sales volume or verified demand.
- Editable profit estimator with assumptions clearly exposed.
- Saved niche ideas in the browser.
- AI listing-copy drafts through an optional server endpoint.
- Etsy policy checklist, human approval gate, and no auto-publishing.
- Health endpoint that exposes only whether required secrets are configured, never their values.

## Deploy on Vercel
Create a separate Vercel project linked to this repository with Root Directory set to etsy-ai. Do not change the root project: its existing crypto routes and redirect are unrelated.

Environment variables:
- ETSY_API_KEY: approved Etsy API keystring and shared secret in the required keystring:shared_secret format. Store this as a sensitive/encrypted environment variable, never in browser code or Git.
- OPENAI_API_KEY: optional key for AI draft generation; keep server-side.
- OPENAI_MODEL: optional; defaults to gpt-4.1-mini.

The Etsy API app must be approved/active and permitted to search active marketplace listings. If Etsy returns 401/403, check approval, key format, and access level. Do not infer demand or sales volume from the number of active listings.

## Safety and policy
This app only researches the market and creates editable drafts. It does not create, edit, renew, or publish Etsy listings. A person must review and submit every listing. Keep at least one genuine, unedited photo of the actual physical item where Etsy requires it; ensure all images accurately represent what buyers receive; disclose AI use in the listing description where required. Functional guide content (such as patterns, recipes, and instructions) must be the seller's own work, not AI-generated. Apply any category-specific exceptions or requirements from Etsy's current policy.

## Endpoints
- GET /api/health
- GET /api/etsy/search?keywords=personalized%20dog%20collar&limit=40
- POST /api/ai/draft

No keys are committed here. No endpoint for listing publication is implemented.
