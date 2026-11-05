"""Rendered public UI regressions in isolated Chromium; no remote provider calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import base64
import io
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import authoring
from studio.server import serve
from studio.montage.engine import locate
from montage_testkit import make_clip

SCRIPT = r'''
import {createRequire} from 'node:module';
const cfg=JSON.parse(process.argv[2]);
const require=createRequire(cfg.modules+'/entry.cjs');
const puppeteer=require('puppeteer-core');
const browser=await puppeteer.launch({executablePath:cfg.browser,headless:true,userDataDir:cfg.profile,args:process.platform==='linux'?['--no-sandbox']:[]});
try {
 const page=await browser.newPage(); await page.goto(cfg.url+'/?project=p');
 await page.waitForFunction(()=>document.body.dataset.ui==='v2');
 const result=await page.evaluate(async({videoUrl,imageUrl})=>{
  const {renderAssemblyScreen}=await import('/static/ui/v2/screen-assembly.js');
  const {renderMontageFamily}=await import('/static/ui/v2/montage-family.js');
  const {renderOverlayEditor}=await import('/static/ui/v2/overlay-editor.js');
  const {renderCanvas}=await import('/static/ui/v2/viewer-canvas.js');
  const {loadFamilyData}=await import('/static/ui/v2/family-data.js');
  const {framesZone}=await import('/static/ui/v2/scene-zones.js');
  const {slotOptions}=await import('/static/ui/v2/viewer-canvas.js');
  const root=document.createElement('div'); root.id='f1-rendered-check'; document.body.append(root);
  const checks=[]; const check=(name,ok)=>checks.push({name,ok:Boolean(ok)});
  document.documentElement.lang='en';
  const photoResult={result_id:'result:scene:s1:image',version_id:'result:scene:s1:image-v1',asset_url:imageUrl,status:'ready'};
  const photoScene={scene_id:'s1',links:{image_result_id:photoResult.version_id}};
  const photo={id:'photo-card',type:'photo',scenes:[photoScene],image_results:[photoResult],positions:[{kind:'image',scene_id:'s1',position_id:'pos:scene:s1:image',result_group_id:photoResult.result_id}]};
  root.append(framesZone(photo,1,photoScene));
  const image=root.querySelector('img'); if(image)await image.decode().catch(()=>{});
  check('photo canonical image appears in card and viewer slot',image?.naturalWidth===8&&slotOptions(photo,photoScene)[0]?.slot==='image'&&!root.textContent.includes('undefined'));
  root.replaceChildren();
  const project={id:'p',title:'Авторский текст',type:'video',stage:'assembly',assembly_mode:'materials',assembly:{kind:'materials',status:'ready',asset_ids:['asset-one'],summary:'Авторская заметка'},scenes:[],history:[]};
  const snapshot={revision:1,active_project:project,view_stage:{current_stage:'assembly',gate_status:'approved',allowed_actions:[],completed_stages:[]},actions:[]};
  renderAssemblyScreen(root,{state:{snapshot},screen:'assembly'});
  check('materials truthful completion',root.textContent.includes('Materials')&&!root.textContent.includes('ещё не собран')&&!root.querySelector('.v2-final-preview'));
  check('EN system copy keeps author bytes',!root.textContent.includes('Ролик принят')&&root.textContent.includes('Авторская заметка'));
  check('materials export control',Boolean([...root.querySelectorAll('button')].find(x=>/Export|Download/.test(x.textContent))));
  const montage={...project,assembly_mode:'montage',montage:{current_version:'v001',versions:[{id:'v001',asset_url:videoUrl}]}};
  const format=renderMontageFamily({project:montage,revision:1,status:{engine:{state:'installed'}},model:null,finished:true});
  check('finished montage delivery and improve',format&&/Export/.test(format.textContent)&&/Improve/.test(format.textContent));
  root.replaceChildren();
  await loadFamilyData('p');
  const originalFetch=window.fetch; const posts=[];
  window.fetch=async(path,options={})=>{
   if(path==='/api/operator') return new Response(JSON.stringify({available:true,status:'ready'}));
   if(path==='/api/library') return new Response(JSON.stringify({entries:[]}));
   if(String(path).endsWith('/routes')) return new Response(JSON.stringify({routes:[{position_id:'pos:scene:s1:image',status:'selected',route_id:'route-synthetic',provider:'magnific',model:'imagen-nano-banana-2-1'}]}));
   if(path==='/api/actions') {posts.push(JSON.parse(options.body));return new Response(JSON.stringify({action_id:'action-synthetic',status:'succeeded'}),{status:202});}
   return originalFetch(path,options);
  };
  await loadFamilyData('p',{force:true});
  const creative={...snapshot,active_project:{...project,positions:[{position_id:'pos:scene:s1:image',kind:'scene',scene_id:'s1',slot:'image'}]},view_stage:{current_stage:'image_results',allowed_actions:['generate']}};
  root.append(renderCanvas({strip:{items:[],total:0},shownIndex:1,mediaKind:'image',caption:'',addRequest:{title:'Exact fallback',prompt:'p/s1 exact'},generation:{project:creative.active_project,snapshot:creative,positionId:'pos:scene:s1:image'},onShow:()=>{}}));
  let confirms=0; window.confirm=()=>{confirms++;return true;};
  root.querySelector('button').click(); await new Promise(r=>setTimeout(r,100));
  check('primary rendered button dispatches exactly once',posts.length===1&&posts[0].target_id==='pos:scene:s1:image'&&posts[0].payload.spending.route_id==='route-synthetic');
  check('no duplicate paid confirmation',confirms===0);
  window.fetch=originalFetch;
  const formatting=()=>renderMontageFamily({project:montage,revision:1,status:{engine:{state:'installed'}},model:null,finished:true});
  window.fetch=async(path,options={})=>String(path).endsWith('/montage/preview')||String(path).endsWith('/montage/export')
    ?new Response(JSON.stringify({url:videoUrl}),{status:200}):String(path).endsWith('/montage/styles')?new Response(JSON.stringify({styles:[]})):originalFetch(path,options);
  root.replaceChildren(formatting());
  const button=(text)=>[...root.querySelectorAll('button')].find(x=>x.textContent===text);
  root.querySelector('select').value='cinematic'; root.querySelector('select').dispatchEvent(new Event('change'));
  button('Preview').click(); await new Promise(r=>setTimeout(r,80));
  button('Export project').click(); await new Promise(r=>setTimeout(r,80));
  const oldPreview=root.querySelector('video');
  root.replaceChildren(formatting());
  check('preview and export survive own repaint',root.querySelector('video')===oldPreview&&!oldPreview.hidden&&oldPreview.getAttribute('src')===videoUrl&&Boolean(root.querySelector('a[download]'))&&root.querySelector('select').value==='cinematic');
  window.fetch=originalFetch;
  root.replaceChildren();
  const editor=renderOverlayEditor({project:montage,snapshot,model:{model_hash:'hash',duration:5,layers:[{layer:'overlays',clips:[{id:'o-1',start:2,duration:1,overlay:{type:'rect',canvas:{width:108,height:192},geometry:{x:10,y:20,width:30,height:50},color:'#36C66B',stroke_width:6,opacity:1}}]}]},status:{exists:true,canvas:{width:108,height:192}}});
  root.append(editor);
  check('overlay time control exists',Boolean(root.querySelector('input[type=range]')));
  check('overlay respects interval at time zero',!root.querySelector('.am-overlay-existing'));
  return checks;
 },{videoUrl:cfg.videoUrl,imageUrl:cfg.imageUrl});
 await page.waitForFunction(()=>document.querySelector('#f1-rendered-check video')?.readyState>=2);
 await page.$eval('#f1-rendered-check input[type=range]',node=>{node.value='2.25';node.dispatchEvent(new Event('input'));});
 result.push({name:'overlay appears at actual interval',ok:await page.$eval('#f1-rendered-check',root=>Boolean(root.querySelector('.am-overlay-existing')))});
 await page.click('#f1-rendered-check .am-overlay-playback button'); await new Promise(r=>setTimeout(r,300));
 result.push({name:'pointer play works with drawing canvas',ok:await page.$eval('#f1-rendered-check video',video=>!video.paused&&video.currentTime>2.25)});
 await page.click('#f1-rendered-check .am-overlay-playback button');
 await page.$eval('#f1-rendered-check input[type=range]',node=>{node.value='3.5';node.dispatchEvent(new Event('input'));});
 result.push({name:'seek hides expired overlay',ok:await page.$eval('#f1-rendered-check',root=>!root.querySelector('.am-overlay-existing'))});
 await page.evaluate(async()=>{
  const prefs=await import('/static/ui/v2/preferences.js');
  prefs.saveFamilyPreference({locale:'en',theme:'dark',view:'overview'});
 });
 await new Promise(r=>setTimeout(r,200));
 const second=await browser.newPage(); await second.goto(cfg.url2+'/?project=p');
 await second.waitForFunction(()=>document.body.dataset.ui==='v2'); await new Promise(r=>setTimeout(r,200));
 result.push({name:'preferences survive a new localhost origin',ok:await second.evaluate(()=>document.documentElement.lang==='en'&&document.documentElement.dataset.theme==='dark'&&document.documentElement.dataset.view==='overview')});
 console.log(JSON.stringify(result)); if(result.some(x=>!x.ok))process.exitCode=1;
} finally {await browser.close();}
'''

MATERIALS_SCRIPT = r'''
import {createRequire} from 'node:module';
const cfg=JSON.parse(process.argv[2]); const require=createRequire(cfg.modules+'/entry.cjs');
const browser=await require('puppeteer-core').launch({executablePath:cfg.browser,headless:true,userDataDir:cfg.profile,args:process.platform==='linux'?['--no-sandbox']:[]});
try {
 const page=await browser.newPage();await page.goto(cfg.url+'/?project=photo');
 await page.waitForSelector('.am-format-actions button');
 const before=await page.evaluate(()=>document.querySelector('.v2-screen-assembly')?.textContent||'');
 if(!before.includes('Materials')||before.includes('video has not been assembled'))throw Error('incorrect materials layout');
 await page.locator('.am-format-actions button').click();
 await page.waitForSelector('.am-format-downloads a[download]');
 const result=await page.evaluate(async()=>{
  const url=document.querySelector('.am-format-downloads a[download]').getAttribute('href');
  const response=await fetch(url); const bytes=new Uint8Array(await response.arrayBuffer());
  if(!response.ok||bytes[0]!==80||bytes[1]!==75)throw Error('invalid exported ZIP');
  return {url,body:btoa(String.fromCharCode(...bytes))};
 });
 await page.evaluate(()=>document.dispatchEvent(new Event('studio:family-preference')));
 if(!await page.$('.am-format-downloads a[download]'))throw Error('delivery link lost after repaint');
 console.log(JSON.stringify(result));
} finally {await browser.close();}
'''


class FamilyUIBrowserTests(unittest.TestCase):
    def test_completed_materials_exports_real_packet_without_engine_or_state_reopen(self):
        import test_family_foundation as fixtures
        from test_library import cli
        engine,reason=locate()
        if not engine or not engine.browser:self.skipTest(reason or 'browser unavailable')
        fixture=fixtures.MaterialsCompletionTests('test_accepting_older_result_selects_it_for_materials')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        pid,asset,contents=fixture.at_assembly('photo')
        cli('assembly','materials',fixture.ws,pid,'--expected-revision',fixture.rev(pid))
        cli('stage','approve',fixture.ws,pid,'--expected-revision',fixture.rev(pid))
        before=fixture.store.load(pid)
        server=serve(fixture.ws);self.addCleanup(server.close)
        server.application.montage.family_state_dir=fixture.root/'family-state'
        cfg={'modules':str(engine.prefix/'node_modules'),'browser':engine.browser,'profile':str(fixture.root/'browser-profile'),'url':server.base_url}
        result=subprocess.run([engine.node,'--input-type=module','-',json.dumps(cfg)],input=MATERIALS_SCRIPT,text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr[-2000:])
        packet=json.loads(result.stdout)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(packet['body']))) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['kind'],'materials')
            self.assertEqual([item['asset_id'] for item in manifest['assets']],[asset])
            self.assertEqual(archive.read(manifest['assets'][0]['path']),contents)
        self.assertEqual(fixture.store.load(pid),before)

    def test_rendered_primary_materials_finished_locale_and_overlay(self):
        engine, reason = locate()
        if not engine or not engine.browser:
            self.skipTest(reason or "browser unavailable")
        with tempfile.TemporaryDirectory(prefix="aimaster-f1-browser-") as directory:
            root = Path(directory).resolve(); ws = root / "workspace"; ws.mkdir()
            authoring.create_project(authoring.open_store(ws), "p", "Synthetic", "photo", "guided")
            (ws/'media').mkdir(exist_ok=True)
            make_clip(ws/'media/playback.mp4',5,size=(108,192),color='blue')
            video=authoring.open_assets(ws).register('media/playback.mp4','result')
            from test_library import png_bytes
            (ws/'media/photo.png').write_bytes(png_bytes())
            photo=authoring.open_assets(ws).register('media/photo.png','result')
            server = serve(ws)
            second = serve(ws)
            try:
                config = {"modules":str(engine.prefix / "node_modules"),"browser":engine.browser,
                    "profile":str(root / "browser-profile"),"url":server.base_url,"url2":second.base_url,"videoUrl":"/assets/"+video['asset_id'],"imageUrl":"/assets/"+photo['asset_id']}
                result = subprocess.run([engine.node,"--input-type=module","-",json.dumps(config)],input=SCRIPT,
                                        text=True,capture_output=True,timeout=60)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr[-2000:])
            finally:
                server.close(); second.close()


if __name__ == "__main__":
    unittest.main()
