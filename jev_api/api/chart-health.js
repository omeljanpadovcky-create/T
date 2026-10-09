/* Cloud JEV readiness: requires a per-user access code, never exposes API secrets. */
import { timingSafeEqual } from 'node:crypto';
const ALLOWED_ORIGINS = new Set([
  'https://omeljanpadovcky-create.github.io',
  'http://127.0.0.1:18765',
  'http://localhost:18765'
]);
export default function handler(req,res) {
  const origin = req.headers.origin;
  if (ALLOWED_ORIGINS.has(origin)) res.setHeader('Access-Control-Allow-Origin',origin);
  res.setHeader('Vary','Origin');
  res.setHeader('Access-Control-Allow-Headers','X-JEV-Access,Content-Type');
  res.setHeader('Access-Control-Allow-Methods','GET,OPTIONS');
  res.setHeader('Cache-Control','no-store');
  if (req.method==='OPTIONS') return res.status(204).end();
  if (req.method!=='GET') return res.status(405).json({error:'GET only'});
  if (!ALLOWED_ORIGINS.has(origin)) return res.status(403).json({ready:false,error:'Недозволений сайт.'});
  if (!process.env.GEMINI_API_KEY || !process.env.JEV_ACCESS_TOKEN || process.env.JEV_ACCESS_TOKEN.length<24)
    return res.status(503).json({ready:false,error:'Хмарний JEV не налаштовано.'});
  const supplied=req.headers['x-jev-access'] || '';
  const expected=process.env.JEV_ACCESS_TOKEN;
  if (typeof supplied!=='string'||supplied.length!==expected.length||
      !timingSafeEqual(Buffer.from(supplied),Buffer.from(expected)))
    return res.status(401).json({ready:false,error:'Неправильний код доступу.'});
  return res.status(200).json({ready:true,provider:'gemini',model:process.env.JEV_CLOUD_MODEL||'gemini-2.5-flash',cloud:true});
}
