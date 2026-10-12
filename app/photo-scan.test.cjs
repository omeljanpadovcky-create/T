/* Real synthetic pixel fixtures for the no-API chart scanner.
   Unlike jsdom mock tests these exercise actual color detection and geometry. */
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const text=fs.readFileSync(path.join(__dirname,'photo-scan.js'),'utf8');
const context={window:{},Uint8Array,Uint8ClampedArray,Int32Array,Set,Math};
vm.runInNewContext(text,context,{timeout:3000});
const scan=context.window.cryptoMyshkaPhotoScan;
function screenshot(kind){
  const width=620,height=350;
  const data=new Uint8ClampedArray(width*height*4);
  for(let p=0;p<data.length;p+=4){
    data[p]=22;data[p+1]=29;data[p+2]=39;data[p+3]=255;
  }
  const draw=(x,y,w,h,color)=>{
    for(let yy=Math.max(0,y);yy<Math.min(height,y+h);yy++)
      for(let xx=Math.max(0,x);xx<Math.min(width,x+w);xx++){
        const i=(yy*width+xx)*4;
        data[i]=color===1?13:236;
        data[i+1]=color===1?201:69;
        data[i+2]=color===1?109:87;
        data[i+3]=255;
      }
  };
  if(kind!=='empty'){
    for(let i=0;i<20;i++){
      const x=38+i*27;
      const y=kind==='up'?242-i*6:kind==='down'?65+i*6:157+(i%2)*2;
      draw(x,y,11,23,i%4===0?2:1);
    }
  }
  return {width,height,data};
}
test('past rising candles have observable higher six-candle structure',()=>{
  const r=scan.analyzePixels(screenshot('up'));
  assert.equal(r.recognized,true);
  assert.equal(r.reliable,true);
  assert.equal(r.visualDirection,'up');
  assert.equal(r.trendState,'up');
  assert.equal(r.structure?.sample,12);
  assert.equal(r.structure?.shortMove,'higher');
  assert.equal(r.structure?.highShape,'higher');
  assert.equal(r.structure?.lowShape,'higher');
  assert.equal(r.structure?.green+r.structure?.red,6);
});
test('past falling candles have observable lower structure',()=>{
  const r=scan.analyzePixels(screenshot('down'));
  assert.equal(r.recognized,true);
  assert.equal(r.reliable,true);
  assert.equal(r.visualDirection,'down');
  assert.equal(r.trendState,'down');
  assert.equal(r.structure?.shortMove,'lower');
  assert.equal(r.structure?.highShape,'lower');
  assert.equal(r.structure?.lowShape,'lower');
});
test('strong contour-quality alone does not invent a trend from sideways candles',()=>{
  const r=scan.analyzePixels(screenshot('sideways'));
  assert.equal(r.recognized,true);
  assert.equal(r.reliable,true);
  assert.equal(r.trendState,'sideways');
  assert.equal(r.visualDirection,'unknown');
  assert.equal(r.structure?.shortMove,'flat');
});
test('no candles means no inferred structure',()=>{
  const r=scan.analyzePixels(screenshot('empty'));
  assert.equal(r.recognized,false);
  assert.equal(r.structure,undefined);
});
