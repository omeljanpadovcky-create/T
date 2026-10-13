/* Pure data-analytics regression test for Crypto Myshka screenshot scanner. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const code=fs.readFileSync(path.join(__dirname,'photo-scan.js'),'utf8');
const scope={window:{}};
vm.runInNewContext(code,scope);
const summarize=scope.window.cryptoMyshkaPhotoScan?.summarizeCandles;
assert.equal(typeof summarize,'function');
const series=[];
for(let i=0;i<53;i++){
  // All 53: 20 green, 33 red; preceding six 1 green, five red;
  // final six five green, one red.
  const color=i<41?(i<14?1:2):i<47?(i===41?1:2):(i<52?1:2);
  series.push({x:i*11+5,color,y:300-i});
}
const data=summarize(series.slice().reverse(),{shortMove:'lower'});
assert.equal(data.total.count,53);
assert.equal(data.total.green,20);
assert.equal(data.total.red,33);
assert.ok(Math.abs(data.total.greenPct-100*20/53)<1e-7);
assert.equal(data.recent12.count,12);
assert.equal(data.previous6.green,1);
assert.equal(data.previous6.red,5);
assert.equal(data.recent6.green,5);
assert.equal(data.recent6.red,1);
assert.ok(Math.abs(data.greenDeltaPp-(100*(5/6-1/6)))<1e-7);
assert.equal(data.contrast,true,
  '5/6 green while recent chart moved lower is a historical contradiction, not a next-minute prediction');
assert.equal(data.thirds.length,3);
assert.equal(data.thirds.reduce((sum,x)=>sum+x.count,0),53);
const insufficient=summarize(series.slice(-8),{shortMove:'lower'});
assert.equal(insufficient.previous6.count,2);
assert.equal(insufficient.greenDeltaPp,null);
assert.equal(insufficient.contrast,false,
  'without 12 observed shapes comparison must be unavailable');
const flat=summarize(series,{shortMove:'flat'});
assert.equal(flat.contrast,false);
console.log('Candle analytics: whole 53 (20/33), 12/6 windows, percentages, partial data and contrary signals OK');
