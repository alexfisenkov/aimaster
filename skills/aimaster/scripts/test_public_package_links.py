"""Installed entry/reference links resolve without a repository above the skill."""
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]


class StandaloneLinksTests(unittest.TestCase):
    def test_entry_and_reference_paths_and_fragments_stay_inside_package(self):
        errors=[]
        for source in [ROOT/'SKILL.md',ROOT/'README.md',*(ROOT/'references').rglob('*.md')]:
            text=re.sub(r'```.*?```','',source.read_text(encoding='utf-8'),flags=re.S)
            for href in re.findall(r'\]\(([^)]+)\)',text):
                href=href.split(' "',1)[0]; parsed=urlsplit(href)
                if parsed.scheme or '<' in href:continue
                target=(source.parent/unquote(parsed.path)).resolve() if parsed.path else source
                if not target.is_relative_to(ROOT) or not target.exists():
                    errors.append(f'{source.relative_to(ROOT)} -> {href}: outside/missing');continue
                if parsed.fragment and target.suffix=='.md':
                    content=target.read_text(encoding='utf-8')
                    headings=re.findall(r'^#{1,6}\s+(.+?)\s*#*$',content,re.M)
                    anchors={re.sub(r'[^\w\- ]','',heading.lower()).replace(' ','-') for heading in headings}
                    anchors.update(re.findall(r'(?:id|name)=["\x27]([^"\x27]+)',content))
                    if unquote(parsed.fragment) not in anchors:errors.append(f'{source.relative_to(ROOT)} -> {href}: absent fragment')
        self.assertEqual(errors,[])


if __name__=='__main__':unittest.main()
