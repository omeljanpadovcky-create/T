import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parsePocketVision} from '../api/pocket-vision.js';
const request={pair:'EUR/USD OTC',chart_timeframe_seconds:60,expiry_seconds:60};
const valid={readable:true,direction:'UP',visible_pair:'unknown',
  observations:['Є щонайменше кілька послідовних зелених свічок, видимих на фото.',
    'Нахил ковзної середньої на зображенні змінився вгору.'],
  reason:'На фото видно дві узгоджені ознаки короткострокового відскоку, проте напрям наступної свічки невідомий.',
  risk:'OTC ціна може розвернутися до експірації, можна втратити всю ставку.'};
test('No screenshot model schema means STOP',()=>{
  assert.equal(parsePocketVision('',request).direction,'STOP');
  assert.equal(parsePocketVision('{"readable":false}',request).direction,'STOP');
  assert.equal(parsePocketVision('{}',request).direction,'STOP');
});
test('Two visible observations permit labelled unverified hypothesis',()=>{
  const value=parsePocketVision(JSON.stringify(valid),request);
  assert.equal(value.direction,'UP');
  assert.equal(value.mode,'screenshot_hypothesis');
  assert.equal(value.quotes_verified,false);
  assert.equal(value.signal_validated,false);
  assert.equal(value.probability,null);
  assert.equal(value.orders_enabled,false);
  assert.equal(value.broker_verified,false);
});
test('Misidentified pair or weak evidence forces STOP',()=>{
  assert.equal(parsePocketVision(JSON.stringify({...valid,visible_pair:'GBP/USD OTC'}),request).direction,'STOP');
  assert.equal(parsePocketVision(JSON.stringify({...valid,observations:[]}),request).direction,'STOP');
  assert.equal(parsePocketVision(JSON.stringify({...valid,risk:'Too short'}),request).direction,'STOP');
});
test('Expiry below candle timeframe never becomes a direction',()=>{
  assert.equal(parsePocketVision(JSON.stringify(valid),{...request,expiry_seconds:30}).direction,'STOP');
});
test('Pocket endpoints are mirrored and do not fetch external quote feeds',()=>{
  const main=readFileSync(new URL('../../api/pocket-vision.js',import.meta.url),'utf8');
  const mirror=readFileSync(new URL('../api/pocket-vision.js',import.meta.url),'utf8');
  assert.equal(main,mirror);
  assert.doesNotMatch(main,/api\.bybit\.com|api\.binance\.com|pocketoption\.com\/api/);
});
