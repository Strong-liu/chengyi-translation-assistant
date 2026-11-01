import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {chromium} from 'playwright';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'build','e2e-results');await fs.mkdir(output,{recursive:true});
const base=process.argv[2] || 'http://127.0.0.1:8766';
let python=process.env.PAPER_TRANSLATOR_PYTHON;
if(!python){
 const candidates=[path.join(root,'.venv','Scripts','python.exe'),path.join(root,'.venv','bin','python')];
 for(const candidate of candidates){try{await fs.access(candidate);python=candidate;break;}catch{}}
 python ||= 'python';
}
let fixture=process.env.E2E_PDF_PATH;
const synthetic=!fixture;
const expected=JSON.parse(process.env.E2E_EXPECTED_TERMS || (synthetic?'["Alex Gray","Jamie Stone","Journal of Neural Engineering"]':'[]'));
if(synthetic){
 const fixtureDir=path.join(root,'build','e2e-fixtures');await fs.mkdir(fixtureDir,{recursive:true});
 fixture=path.join(fixtureDir,'synthetic-paper.pdf');
 execFileSync(python,['-c',"import pymupdf,sys; d=pymupdf.open(); d.set_metadata({'author':'Alex Gray; Jamie Stone'}); p=d.new_page(); p.insert_text((50,40),'Journal of Neural Engineering'); p.insert_text((50,110),'Synthetic software test paper',fontsize=16); p.insert_text((50,150),'Alex Gray and Jamie Stone'); p.insert_textbox(pymupdf.Rect(50,235,545,380),'Abstract: This is a synthetic document for software testing. EEGNet and Transformer are model names. The software translates this text while keeping author names and journal names in English.',fontsize=11); p.insert_text((50,550),'References'); p.insert_text((50,580),'1. Gray, A. Synthetic software fixture. 2026.'); d.save(sys.argv[1]); d.close()",fixture],{encoding:'utf8'});
}
const browser=await chromium.launch({...(process.env.PLAYWRIGHT_CHROME_PATH?{executablePath:process.env.PLAYWRIGHT_CHROME_PATH}:{}),headless:true});
const context=await browser.newContext({viewport:{width:1280,height:1000},acceptDownloads:true});
const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
try {
 await page.goto(base,{waitUntil:'networkidle'});
 const settings=await (await context.request.get(base+'/api/settings')).json();
 assert.equal(settings.api_key_configured,true);
 assert.equal(settings.service_mode,'llm');
 assert.equal(settings.api_key,undefined);
 await page.locator('#file-input').setInputFiles(fixture);
 const pending=page.waitForResponse(r=>r.url().endsWith('/api/jobs')&&r.request().method()==='POST');
 await page.locator('#upload-button').click();
 const response=await pending;assert.equal(response.status(),201);const job=await response.json();
 const card=page.locator('.job-card').filter({has:page.locator(`#terms-${job.id}`)});
 await card.locator('.terms-editor').waitFor();
 const terms=await card.locator('.terms-editor').inputValue();assert.ok(terms.includes('EEGNet'));
 for(const term of expected)assert.ok(terms.includes(term),`Missing protected term: ${term}`);
 assert.equal(await card.locator('.preserve-references').textContent(),'参考文献列表自动跳过，整体保留原文。');
 await page.screenshot({path:path.join(output,'review-desktop.png'),fullPage:true});
 await card.getByRole('button',{name:'核对完成，开始翻译',exact:true}).click();
 console.log(JSON.stringify({stage:'translating',job_id:job.id,pages:job.pages,protected_terms:job.terms.length}));
 const deadline=Date.now()+Number(process.env.E2E_TIMEOUT_MS || 8*60*1000);let result;
 while(Date.now()<deadline){
  result=await(await context.request.get(`${base}/api/jobs/${job.id}`)).json();
  if(['failed','succeeded'].includes(result.status))break;
  await new Promise(resolve=>setTimeout(resolve,2000));
 }
 assert.equal(result.status,'succeeded',result.message);
 await page.reload({waitUntil:'networkidle'});
 const completed=page.locator('.job-card').filter({hasText:path.basename(fixture)}).first();
 const downloads=[];
 for(const [kind,label]of[['mono','下载中文 PDF'],['dual','下载中英对照 PDF']]){
  const event=page.waitForEvent('download');await completed.getByRole('link',{name:label,exact:true}).click();
  const file=await event;assert.equal(await file.failure(),null);
  const target=path.join(output,kind+'.pdf');await file.saveAs(target);
  const bytes=await fs.readFile(target);assert.equal(bytes.subarray(0,5).toString(),'%PDF-');
  downloads.push({kind,bytes:bytes.length});
 }
 const pdfValidation=execFileSync(python,['-c',
  "import pymupdf,sys,re,unicodedata,json; d=pymupdf.open(sys.argv[1]); t=unicodedata.normalize('NFKC',d[0].get_text(clip=pymupdf.Rect(0,0,d[0].rect.width,200))); norm=lambda x:re.sub('[^A-Za-z0-9]','',x).lower(); expected=json.loads(sys.argv[2]); assert all(norm(x) in norm(t) for x in expected),repr(t); print('Names and journal preserved in page header')",
  path.join(output,'mono.pdf'),JSON.stringify(expected)],{encoding:'utf8'});
 console.log(pdfValidation.trim());
 await page.screenshot({path:path.join(output,'completed-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.screenshot({path:path.join(output,'completed-mobile.png'),fullPage:true});
 assert.deepEqual(errors,[]);
 const report={result:'PASS',base_url:base,job_id:job.id,synthetic_fixture:synthetic,real_baidu_api:true,downloaded:downloads};
 await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await context.close();await browser.close();}
