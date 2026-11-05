"""Rendered regression for pending brief questions in both family views."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import authoring
from studio.montage.engine import locate
from studio.server import serve


SCRIPT = r'''
import {createRequire} from 'node:module';
const cfg=JSON.parse(process.argv[2]);
const require=createRequire(cfg.modules+'/entry.cjs');
const browser=await require('puppeteer-core').launch({executablePath:cfg.browser,headless:true,userDataDir:cfg.profile,args:process.platform==='linux'?['--no-sandbox']:[]});
try {
  const page=await browser.newPage();
  await page.goto(cfg.url+'/?project=p');
  await page.waitForSelector('[data-question-id="brief-format"]');
  const questionTexts=async()=>page.$$eval('[data-hook="question-open"]',rows=>rows.map(row=>row.textContent));
  const click=selector=>page.evaluate(selector=>document.querySelector(selector)?.click(),selector);
  if((await questionTexts()).join('|')!=='Choose format|What are we creating?') throw Error('pending questions missing in Stages');
  await click('[data-hook="family-overview"]');
  await page.waitForSelector('[data-hook="am-overview"]');
  if((await questionTexts()).join('|')!=='Choose format|What are we creating?') throw Error('pending questions missing in Overview');
  await page.evaluate(async()=>{const prefs=await import('/static/ui/v2/preferences.js');prefs.saveFamilyPreference({...prefs.readFamilyPreference(),locale:'ru'},false);document.dispatchEvent(new Event('studio:family-preference'));});
  await click('[data-question-id="brief-format"]');
  if(await page.$eval('[data-hook="question-modal-submit"]',node=>node.textContent)!=='Продолжить') throw Error('RU dialog unavailable');
  await click('[data-hook="question-modal-defer"]');
  await click('[data-hook="family-language"]');
  await new Promise(resolve=>setTimeout(resolve,200));
  if(await page.evaluate(()=>document.documentElement.lang)!=='en') throw Error('language toggle did not switch to EN');
  const en=await page.evaluate(()=>({path:document.querySelector('[data-hook="v2-path"]')?.getAttribute('aria-label'),
    title:document.querySelector('.v2-topbar-title')?.textContent,
    questions:document.querySelector('[data-hook="questions-panel"] h2')?.textContent}));
  if(en.title!=='Авторский текст'||en.questions!=='Questions') throw Error('EN copy changed author text or left question heading untranslated');
  await click('[data-hook="family-stages"]');
  await page.waitForSelector('[data-hook="v2-path"]');
  if(await page.$eval('[data-hook="v2-path"]',node=>node.getAttribute('aria-label'))!=='Project path') throw Error('project path untranslated');
  await page.click('[data-question-id="brief-format"]');
  await page.waitForSelector('[data-hook="question-modal-option"] input');
  if(await page.$eval('#question-modal-title',node=>node.textContent)!=='Choose format') throw Error('question text changed');
  if(await page.$eval('[data-hook="question-modal-submit"]',node=>node.textContent)!=='Continue') throw Error('reopened dialog did not switch to EN');
  await page.click('[data-hook="question-modal-option"] input');
  await page.click('[data-hook="question-modal-submit"]');
  await page.waitForFunction(()=>!document.querySelector('[data-question-id="brief-format"]'));
  await page.click('[data-question-id="brief-idea"]');
  await page.type('[data-hook="question-modal-free-text"]','Synthetic answer');
  await page.click('[data-hook="question-modal-submit"]');
  await page.waitForFunction(()=>!document.querySelector('[data-hook="question-open"]'));
  const snapshot=await page.evaluate(async()=>await (await fetch('/api/projects/p/snapshot')).json());
  if(snapshot.questions.length!==0) throw Error('answer did not persist');
  console.log(JSON.stringify({en,remaining:snapshot.questions.length}));
} finally {await browser.close();}
'''


class FamilyBlindUI(unittest.TestCase):
    def test_questions_render_and_answers_persist(self):
        engine, reason = locate()
        if not engine or not engine.browser:
            self.skipTest(reason or "browser unavailable")
        with tempfile.TemporaryDirectory(prefix="aimaster-blind-ui-") as directory:
            root = Path(directory).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            with patch.dict(os.environ, {"AIMASTER_CONFIG_HOME": str(root / "config")}):
                store = authoring.open_store(workspace)
                authoring.create_project(store, "p", "Авторский текст", "video", "guided")
                questions = authoring.open_questions(workspace)
                for question_id, text, kind, options, required in (
                    ("brief-format", "Choose format", "single", [
                        {"id": "short", "label": "Short video", "description": "Under one minute"},
                        {"id": "long", "label": "Long video", "description": "Over one minute"},
                    ], True),
                    ("brief-idea", "What are we creating?", "free_text", [], False),
                ):
                    authoring.create_question(store, questions, "p", question_id=question_id,
                        text=text, kind=kind, options=options, allow_custom=False, required=required)
                server = serve(workspace)
                try:
                    config = {"modules": str(engine.prefix / "node_modules"), "browser": engine.browser,
                        "profile": str(root / "browser-profile"), "url": server.base_url}
                    result = subprocess.run([engine.node, "--input-type=module", "-", json.dumps(config)],
                        input=SCRIPT, text=True, capture_output=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr[-2000:])
                    self.assertEqual(questions.pending("p"), [])
                finally:
                    server.close()


if __name__ == "__main__":
    unittest.main()
