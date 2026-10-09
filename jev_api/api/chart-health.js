/* Cloud JEV readiness: requires a per-user access code, never exposes API secrets. */
import { timingSafeEqual } from 'node:crypto';
const ALLOWED_ORIGINS = new Set([
  'https://omeljanpadovcky-create.github.io',
  'http://127.0.0.1:18765',
  'http://localhost:18765'
]);
export default async function handler(req,res) {
  const origin = req.headers.origin;
  if (ALLOWED_ORIGINS.has(origin)) res.setHeader('Access-Control-Allow-Origin',origin);
  res.setHeader('Vary','Origin');
  res.setHeader('Access-Control-Allow-Headers','X-JEV-Access,Content-Type');
  res.setHeader('Access-Control-Allow-Methods','GET,OPTIONS');
  res.setHeader('Cache-Control','no-store');
  if (req.method==='OPTIONS') return res.status(204).end();
  if (req.method!=='GET') return res.status(405).json({error:'GET only'});
  if (!ALLOWED_ORIGINS.has(origin)) return res.status(403).json({ready:false,error:'Недозволений сайт.'});
  const apinexKey = (process.env.APINEX_API_KEY || '').trim();
  const geminiKey = (process.env.GEMINI_API_KEY || '').trim();
  if ((!apinexKey && !geminiKey) || !process.env.JEV_ACCESS_TOKEN || process.env.JEV_ACCESS_TOKEN.length<24)
    return res.status(503).json({ready:false,error:'Немає APINEX_API_KEY або GEMINI_API_KEY та/або JEV_ACCESS_TOKEN у змінних серверного проєкту.'});
  const supplied=req.headers['x-jev-access'] || '';
  const expected=process.env.JEV_ACCESS_TOKEN;
  if (typeof supplied!=='string'||supplied.length!==expected.length||
      !timingSafeEqual(Buffer.from(supplied),Buffer.from(expected)))
    return res.status(401).json({ready:false,error:'Неправильний код доступу.'});
  // GitHub Actions secrets are NOT automatically available to Vercel functions.
  // This check only sees environment variables configured for THIS backend.
  const provider = apinexKey ? 'apinex' : 'gemini';
  const model = provider === 'apinex'
    ? (process.env.JEV_APINEX_MODEL || 'gemini-3.8-flash')
    : (process.env.JEV_CLOUD_MODEL || 'gemini-2.5-flash');
  try {
    const upstream = provider === 'apinex'
      ? await fetch('https://api.apinex.bond/v1/models', {
          headers:{Authorization:'Bearer ' + apinexKey},
          signal:AbortSignal.timeout(8000)
        })
      : await fetch('https://generativelanguage.googleapis.com/v1beta/models/' +
          encodeURIComponent(model), {
          headers:{'x-goog-api-key':geminiKey},
          signal:AbortSignal.timeout(6000)
        });
    if (!upstream.ok && provider === 'apinex' && upstream.status === 403) {
      // APInex may deny model catalog access even when chat completions work.
      // Do NOT label the key invalid. Authorize a photo test without claiming
      // actual inference has been verified by this health check.
      return res.status(200).json({ready:true,provider,model,cloud:true,
        verified:false,probe:'model_catalog_denied',
        notice:'API-ключ налаштовано; каталог моделей повернув 403. Роботу моделі перевірить запит аналізу фото.'});
    }
    if (!upstream.ok) return res.status(503).json({
      ready:false,error:upstream.status===429?'Ліміт APInex/Gemini вичерпано.':
        'API-ключ або сервер моделі недоступний (HTTP ' + upstream.status + ').'
    });
    return res.status(200).json({ready:true,provider,model,cloud:true,
      verified:true,
      notice:'API відповів; це не перевірка точності аналізу чи реальної торгівлі.'});
  } catch {
    return res.status(503).json({ready:false,error:'Немає зв’язку з сервером APInex/Gemini. Спробуй пізніше.'});
  }
}
