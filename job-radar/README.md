# ТРЕЙДМИШКА — Job Radar

The GitHub Actions workflow runs a fresh vacancy scan hourly and polls Telegram buttons every 5 minutes.

## Search profile
- Remote work: Ukraine, Europe and worldwide where the listing clearly permits it.
- Roles: 3D / Blender / modeling, Game Art / game assets, character / environment / prop art, concept art, illustration, book covers, Photobashing and Matte Painting.
- English level and seniority are not automatic rejection filters.
- Country-specific locations and explicit country-only requirements are filtered out unless Ukraine or a broader eligible region is explicitly allowed.
- Some public sources can return 403 or change their markup. The radar records failures and continues with sources that respond.

## Telegram workflow
Each vacancy card contains an original listing link and actions to select or skip it. Selecting a vacancy generates an editable application package. The user reviews and approves the package, then submits manually on the employer's website. The bot never submits an application automatically.

## Deployment
GitHub Actions is the primary scheduler and Telegram callback processor. The Vercel API is optional and is not required for vacancy scans or Telegram buttons.
