import os, re, sys
from pathlib import Path

import httpx

MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"
MARK = "sf-mermaid-patch"

# Patch EVERY npx-cached copy of the TrueForge frontend. The CLI launches
# (or reuses) one of these via npx but does not know which hash npx resolves,
# and a re-fetch can create a new cache entry while an older one still
# serves — so selecting "the newest" is wrong. Patching all copies is
# idempotent and cheap, and always covers the served one.
def discover_frontends():
    roots = sorted(
        Path(os.path.expanduser("~/.npm/_npx")).glob("*/node_modules/@truefoundry/trueforge"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    return [r / "dist" / "_frontend" for r in roots if (r / "dist" / "_frontend" / "index.html").exists()]


_mermaid_bytes = None

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

def patch_frontend(frontend: Path) -> None:
    global _mermaid_bytes
    index = frontend / "index.html"
    mermaid = frontend / "assets" / "mermaid.min.js"
    if not index.exists():
        return
    html = index.read_text()
    if MARK in html:
        print(f"already patched — removing previous patch to re-apply fresh ({frontend})")
        html = re.sub(r'<script src="/assets/mermaid\.min\.js"></script>\n<script>\n\(function\(\)\{var sfMermaid=.*?;\n</script>\n', "", html, flags=re.S)

    if not mermaid.exists():
        if _mermaid_bytes is None:
            print("downloading mermaid.min.js ...")
            r = httpx.get(MERMAID_URL, timeout=60, follow_redirects=True)
            r.raise_for_status()
            _mermaid_bytes = r.content
        mermaid.parent.mkdir(parents=True, exist_ok=True)
        mermaid.write_bytes(_mermaid_bytes)
        print(f"  saved {len(_mermaid_bytes)} bytes")
    else:
        print("mermaid.min.js already present")

    html = html.replace('<script type="module" crossorigin src="/assets/',
                         observer + '<script type="module" crossorigin src="/assets/', 1)
    index.write_text(html)
    print(f"index.html patched ({frontend})")

    for variant in ("index.html.br", "index.html.gz"):
        p = frontend / variant
        if p.exists():
            p.unlink()
            print(f"removed {variant} (server will serve patched html + compress on the fly)")


frontends = discover_frontends()
if not frontends:
    sys.exit("no @truefoundry/trueforge _frontend found under ~/.npm/_npx — npx cache path changed?")
for f in frontends:
    patch_frontend(f)
print("DONE")
