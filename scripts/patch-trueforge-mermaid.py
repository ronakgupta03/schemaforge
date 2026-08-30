#!/usr/bin/env python3
"""Patch the TrueForge local UI to render mermaid code blocks as diagrams.

The built-in UI's markdown renderer (marked + Prism) only *highlights*
```mermaid blocks. This injects the real mermaid runtime + a DOM observer
that replaces highlighted mermaid code blocks with rendered SVG.

Idempotent: safe to re-run. Re-run after `npx` re-fetches the package
(or npx cache invalidation).

Streaming-safe: mermaid blocks stream in token by token; a render attempt on
a partial block fails with a "Syntax error" toast and the old patch never
retried (the block stayed broken). This patch releases the render lock on
failure and re-scans until the block text is stable and parses.
"""
import os, re, sys
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
  var lastTry = {};
  function renderBlock(code){
    var pre = code.closest('pre');
    if (!pre || pre.getAttribute('data-sf-mermaid')) return;
    var src = code.textContent || '';
    if (!src.trim()) return;
    /* Streaming guard: if a previous attempt failed, wait until the block
       stops growing before retrying (a partial block always fails). */
    var prev = lastTry[pre];
    if (prev && prev.text === src && !prev.ready) {
      if (Date.now() - prev.at < 700) return;  /* stable but recent failure: wait */
      /* stale stable failure: fall through and retry now */
    }
    lastTry[pre] = { text: src, at: Date.now(), ready: false };
    pre.setAttribute('data-sf-mermaid','1');
    var id = 'sf-mmd-' + (++seen);
    mermaid.render(id, src).then(function(r){
      lastTry[pre].ready = true;
      var div = document.createElement('div');
      div.className = 'sf-mermaid-render';
      div.setAttribute('style', 'max-height:70vh;overflow:auto');
      div.innerHTML = r.svg;
      pre.parentNode.replaceChild(div, pre);
    }).catch(function(e){
      /* Partial/streamed block — release the lock so the MutationObserver
         retries once the full text lands. Keep a transient error hint. */
      lastTry[pre].ready = true;
      pre.removeAttribute('data-sf-mermaid');
      var old = pre.querySelector('.sf-mermaid-error');
      if (old) old.remove();
      var note = document.createElement('span');
      note.className = 'sf-mermaid-error';
      note.textContent = 'mermaid: ' + ((e && e.message) ? e.message : e) + ' (retrying…)';
      pre.appendChild(note);
      setTimeout(function(){ if (pre.isConnected) { var n = pre.querySelector('.sf-mermaid-error'); if (n) n.remove(); } }, 1500);
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
  setInterval(scan, 1500);
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