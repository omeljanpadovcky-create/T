/* Simple Crypto Myshka page: only static offline photo scanner. */
const VERSION='myshka-photo-v1';
const STATIC=['./myshka-app.html','./app/photo-scan.js','./app/simple-photo-assistant.js'];
self.addEventListener('install',event=>{
  event.waitUntil(caches.open(VERSION).then(cache=>cache.addAll(STATIC)).catch(()=>{}));
  self.skipWaiting();
});
self.addEventListener('activate',event=>{
  event.waitUntil(caches.keys().then(keys=>Promise.all(
    keys.filter(key=>(key.startsWith('myshka-app-shell-')||key.startsWith('myshka-photo-'))&&key!==VERSION)
      .map(key=>caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url);
  if(url.origin!==self.location.origin)return;
  if(!STATIC.some(file=>url.pathname.endsWith('/'+file.replace(/^\.\//,''))))return;
  const key=new Request(url.origin+url.pathname);
  event.respondWith(fetch(event.request,{cache:'no-store'}).then(response=>{
    if(response.ok)event.waitUntil(caches.open(VERSION)
      .then(cache=>cache.put(key,response.clone())).catch(()=>{}));
    return response;
  }).catch(async()=>{
    const cache=await caches.open(VERSION);
    return await cache.match(key)||Response.error();
  }));
});
