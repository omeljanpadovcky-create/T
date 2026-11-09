# ТРЕЙДМИШКА — Job Radar

The GitHub Actions workflow polls Telegram buttons every 5 minutes and scans for new vacancies every 15 minutes. The minimum vacancy score is 80/100.

## Search profile
- Remote work: Ukraine, Europe and worldwide where the listing clearly permits it.
- Roles: 3D / Blender / modeling, Game Art / game assets, character / environment / prop art, concept art, illustration, book covers, Photobashing and Matte Painting.
- English level and seniority are not automatic rejection filters.
- Country-specific locations and explicit country-only requirements are filtered out unless Ukraine or a broader eligible region is explicitly allowed.
- Some public sources can return 403 or change their markup. The radar records failures and continues with sources that respond.

## Telegram workflow
Each vacancy card contains the original listing link and actions to prepare an application, generate a cover letter, save for later, skip, or view status. Selecting a vacancy generates an editable application package. The user reviews and approves the package, then submits manually on the employer's website. The bot never submits an application automatically.

## Deployment
GitHub Actions is the primary scheduler and Telegram callback processor. The Vercel API is optional and is not required for vacancy scans or Telegram buttons.
