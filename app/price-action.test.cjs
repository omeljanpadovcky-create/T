/* Price Action tests: real OHLC rules, closed-candle backtest invariants. */
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const core=require('./price-action-core.js');
const make=(n=170,step=60000)=>{
  const start=1700000000000,rows=[];
  for(let i=0;i<n;i++){
    const value=100+2.9*Math.sin(i*.25)+.015*i;
    const previous=100+2.9*Math.sin((i-1)*.25)+.015*(i-1);
    const open=i?previous:value-.17,close=value;
    rows.push({start:start+i*step,open,close,high:Math.max(open,close)+.45,
      low:Math.min(open,close)-.45});
  }
  return rows;
};
test('fails closed on invalid candle values or chronological order',()=>{
  const source=make();
  assert.throws(()=>core.analyze([...source.slice(0,100),{...source[100],high:1}]),/OHLC/);
  assert.throws(()=>core.backtest([...source.slice(0,100),source[98]]),/впорядковані/);
  assert.throws(()=>core.backtest(source,{payout:0}),/Виплата/);
});
test('short histories are explicitly WAIT, not invented calls',()=>{
  const a=core.analyze(make(48));
  assert.equal(a.bias,'wait');
  assert.ok(a.reasons.some(x=>x.includes('55')));
  assert.equal(core.backtest(make(75)).trades,0);
  assert.equal(core.backtest(make(75)).accuracy,null);
});
test('levels, trend and patterns are derived from valid historical OHLC',()=>{
  const a=core.analyze(make());
  assert.ok(['up','down','wait'].includes(a.bias));
  assert.ok(['up','down','sideways'].includes(a.trend));
  assert.ok(a.levels&&a.pattern&&Array.isArray(a.reasons));
  assert.ok(a.reasons.some(x=>x.includes('Підтримка')));
  assert.equal(Object.hasOwn(a,'confidence'),false,'no invented probability');
});
test('adding a future candle does not change past historical signals',()=>{
  const source=make(205),short=core.backtest(source.slice(0,180));
  const extended=core.backtest(source);
  const known=new Map(extended.records.map(x=>[x.start,x]));
  for(const item of short.records){
    const later=known.get(item.start);
    assert.ok(later);
    assert.equal(later.bias,item.bias);
    assert.equal(later.won,item.won);
    assert.equal(later.entry,item.entry);
    assert.equal(later.exit,item.exit);
  }
});
test('backtest includes no lookahead, no betting ladders, and bounded accuracy',()=>{
  const r=core.backtest(make(250),{payout:.92});
  assert.equal(r.trades,r.wins+r.losses);
  assert.ok(r.wait+r.trades+r.ties<=250-1-80);
  assert.equal(r.records.length,r.trades);
  assert.equal(r.accuracy===null||r.trades>=30,true);
  if(r.accuracy!==null)assert.ok(r.accuracy>=0&&r.accuracy<=100);
  const expected=r.wins*.92-r.losses;
  assert.ok(Math.abs(r.netUnits-expected)<1e-7);
  assert.ok(!Object.hasOwn(r,'martingale'));
});
test('multi-timeframe history uses only fully closed past M5 candles',()=>{
  const m1=make(420,60000),m5=make(145,300000);
  const full=core.backtestMulti(m1,m5,{payout:.92});
  assert.ok(full.trades>=0&&full.wait>=0);
  assert.equal(full.records.length,full.trades);
  for(const t of full.records)
    assert.ok(t.m5LastClosedAt<=t.start+60000,
      'M5 candle was not yet closed at M1 decision');
  const previous=core.backtestMulti(m1.slice(0,400),m5,{payout:.92});
  const known=new Map(full.records.map(r=>[r.start,r]));
  for(const row of previous.records){
    assert.equal(known.get(row.start)?.won,row.won);
    assert.equal(known.get(row.start)?.m5LastClosedAt,row.m5LastClosedAt);
  }
  assert.throws(()=>core.backtestMulti(
    [...m1.slice(0,200),{...m1[200],start:m1[200].start+360000}],
    m5),/пропуски/);
});
test('photo review is descriptive and refuses low quality contours',()=>{
  assert.match(core.photoSummary({reliable:false})[0],/ненадійні/);
  const sample=make(25).map((x,i)=>({
    x:i*15,y:45+i%4,h:21,color:i%2?1:2
  }));
  const a=core.photoSummary({reliable:true,shapes:sample,structure:{
    highShape:'higher',lowShape:'higher'
  }});
  assert.equal(a.length,3);
  assert.ok(a.join(' ').includes('пікселі'));
  assert.ok(a.join(' ').includes('OHLC'));
});
test('published page wires all three methods to existing assistant',()=>{
  const html=fs.readFileSync(path.resolve(__dirname,'../myshka-app.html'),'utf8');
  assert.ok(html.includes('id="price-action-live"'));
  for(const asset of ['price-action-core.js','price-action-ui.js','simple-photo-assistant.js'])
    assert.ok(html.includes(asset),asset);
  assert.ok(html.indexOf('price-action-core.js')<html.indexOf('price-action-ui.js'));
  assert.ok(!html.includes('id="ticket-buy"')&&!html.includes('id="ticket-sell"'));
});
