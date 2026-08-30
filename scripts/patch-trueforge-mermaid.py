#!/usr/bin/env python3
"""Patch the TrueForge local UI to render mermaid code blocks as diagrams.

The built-in UI's markdown renderer (marked + Prism) only *highlights*
```mermaid blocks. This injects the real mermaid runtime + a DOM observer
that replaces highlighted mermaid code blocks with rendered SVG.

Idempotent: safe to re-run. Re-run after `npx` re-fetches the package
(or npx cache invalidation).
"""
import gzip, os, re, shutil, sys
from pathlib import Path

import httpx

TF_ROOT = Path(os.path.expanduser(
    "~/.npm/_npx/efcb13bb8fe8f852/node_modules/@truefoundry/trueforge"))
FRONTEND = TF_ROOT / "dist" / "_frontend"
INDEX = FRONTEND / "index.html"
MERMAID = FRONTEND / "assets" / "mermaid.min.js"
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
MARK = "sf-mermaid-patch"

if not INDEX.exists():
    sys.exit(f"index.html not found at {INDEX} — npx cache path changed?")

html = INDEX.read_text()
if MARK in html:
    print("already patched — removing previous patch to re-apply fresh")
    html = re.sub(r'<script src="/assets/mermaid\.min\.js"></script>\n<script>\n\(function\(\)\{var sfMermaid=.*?;\n</script>\n', "", html, flags=re.S)

if not MERMAID.exists():
    print("downloading mermaid.min.js ...")
    r = httpx.get(MERMAID_URL, timeout=60, follow_redirects=True)
    r.raise_for_status()
    MERMAID.write_bytes(r.content)
    print(f"  saved {len(r.content)} bytes")
else:
    print("mermaid.min.js already present")

observer = """
<script src="/assets/mermaid.min.js"></script>
<script>
(function(){var sfMermaid=1;
  if (typeof mermaid === 'undefined') return;   /* offline: leave blocks as code */
  var seen = 0;
  function renderBlock(code){
    var pre = code.closest('pre');
    if (!pre || pre.getAttribute('data-sf-mermaid')) return;
    pre.setAttribute('data-sf-mermaid','1');
    var src = code.textContent;
    var id = 'sf-mmd-' + (++seen);
    mermaid.render(id, src).then(function(r){
      var div = document.createElement('div');
      div.className = 'sf-mermaid-render';
      div.innerHTML = r.svg;
      pre.parentNode.replaceChild(div, pre);
    }).catch(function(e){
      pre.outerHTML = '<pre style="color:#c00">mermaid error: ' +
        ((e && e.message) ? e.message : e) + '</pre>';
    });
  }
  function scan(){
    var codes = document.querySelectorAll('pre code.language-mermaid, pre code.mermaid');
    for (var i=0;i<codes.length;i++) renderBlock(codes[i]);
  }
  mermaid.initialize({ startOnLoad:false, securityLevel:'loose', maxTextSize:2000000, maxEdges:10000 });
  var mo = new MutationObserver(scan);
  mo.observe(document.documentElement, {childList:true, subtree:true});
  scan();
})();
</script>
"""
html = html.replace('<script type="module" crossorigin src="/assets/',
                     observer + '<script type="module" crossorigin src="/assets/', 1)
INDEX.write_text(html)
print("index.html patched")

for variant in ("index.html.br", "index.html.gz"):
    p = FRONTEND / variant
    if p.exists():
        p.unlink()
        print(f"removed {variant} (server will serve patched html + compress on the fly)")
print("DONE")