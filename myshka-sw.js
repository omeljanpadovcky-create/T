/* Scope is /T/ on GitHub Pages. Do not intercept or cache legacy app routes. */
const VERSION = 'myshka-app-shell-v1';
const STATIC = ['./myshka-app.html','./app/myshka.css','./app/myshka.js','./app/myshka-icon.svg','./myshka.webmanifest'];
const JSON_FEEDS = ['crypto_myshka/data/youtube_live.json','crypto_myshka/data/pair_reports.json','crypto_myshka/data/youtube_analysts.json'];
self.addEventListener('install',event=>{
  event.waitUntil(caches.open(VERSION).then(cache=>cache.addAll(STATIC)).catch(()=>{}));
  self.skipWaiting();
});
self.addEventListener('activate',event=>{
  event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('myshka-app-shell-') && key!==VERSION).map(key=>caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener('fetch',event=>{
  const request=event.request;if(request.method!=='GET')return;
  const url=new URL(request.url);if(url.origin!==self.location.origin)return;
  const pathname=url.pathname;
  const allowed=[...STATIC,...JSON_FEEDS].some(relative=>pathname.endsWith('/'+relative.replace(/^\.\//,'')));
  if(!allowed)return;
  const feed=JSON_FEEDS.some(name=>pathname.endsWith('/'+name));
  event.respondWith(
    fetch(request,{cache:'no-store'}).then(response=>{
      if(response.ok){const copy=response.clone();event.waitUntil(caches.open(VERSION).then(cache=>cache.put(request,copy)).catch(()=>{}));}
      return response;
    }).catch(async()=>{
      const cache=await caches.open(VERSION);
      const fallback=await cache.match(request,{ignoreSearch:true});
      if(fallback)return fallback;
      if(feed)return new Response('{}',{status:503,headers:{'Content-Type':'application/json'}});
      return Response.error();
    })
  );
});
