"""Rende index.html e regia.html compatibili con telefoni vecchi (iPhone con iOS 11-14, Android vecchi).
- JS: ricompilato in ES2017 con esbuild (niente ?. ?? campi di classe ecc.)
- CSS: inset -> top/right/bottom/left, clamp() con valore di riserva, aspect-ratio con altezza di riserva,
       gap nei flex con margini di riserva (solo dove il browser non lo supporta), -webkit-backdrop-filter.
"""
import re, sys, subprocess, hashlib, base64, os, json
D = os.path.dirname(os.path.abspath(__file__))
ESB = os.path.join(D, "node_modules/.bin/esbuild")
TARGET = "es2017,safari11,ios11,chrome61,firefox60,edge18"

def transpile(js):
    p = subprocess.run([ESB, "--loader=js", "--target=" + TARGET, "--charset=utf8", "--log-level=error", "--minify-whitespace", "--minify-syntax"],
                       input=js.encode(), capture_output=True)
    if p.returncode: raise SystemExit(p.stderr.decode())
    out = p.stdout.decode()
    chk = subprocess.run(["node", "-e", "const a=require('acorn');a.parse(require('fs').readFileSync(0,'utf8'),{ecmaVersion:2017});"],
                         input=out.encode(), capture_output=True, cwd=D)
    if chk.returncode: raise SystemExit("ancora sintassi troppo nuova: " + chk.stderr.decode()[:300])
    return out

def px_at(expr, vw=375):
    """valuta grossolanamente un valore CSS a 375px di larghezza (per il valore di riserva di clamp)"""
    e = expr.strip()
    m = re.fullmatch(r"(-?[\d.]+)(px|vw|vh|rem|em)?", e)
    if not m: return None
    n = float(m.group(1)); u = m.group(2) or "px"
    return {"px": n, "vw": n * vw / 100, "vh": n * 667 / 100, "rem": n * 16, "em": n * 16}[u]

def split_args(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(": depth += 1
        if ch == ")": depth -= 1
        if ch == "," and depth == 0: out.append(cur); cur = ""
        else: cur += ch
    out.append(cur); return [x.strip() for x in out]

def find_call(s, name, start):
    i = s.find(name + "(", start)
    if i < 0: return None
    j = i + len(name) + 1; depth = 1
    while depth:
        if s[j] == "(": depth += 1
        elif s[j] == ")": depth -= 1
        j += 1
    return i, j

def clamp_fallback(val):
    """sostituisce ogni clamp(a,b,c) nel valore con un numero fisso ragionevole (o None se non si riesce)"""
    out = val; pos = 0
    while True:
        r = find_call(out, "clamp", pos)
        if not r: break
        i, j = r
        a, b, c = split_args(out[i + 6:j - 1])
        va, vb, vc = px_at(a), px_at(b), px_at(c)
        if va is not None and vc is not None:
            v = vb if vb is not None else va
            rep = "%gpx" % round(max(va, min(v, vc)), 1)
        elif va is not None: rep = a
        else: return None
        out = out[:i] + rep + out[j:]; pos = i + len(rep)
    return out

def fix_css(css):
    extra = []
    def fix_block(m):
        sel, body = m.group(1), m.group(2)
        if sel.strip().startswith("@") or "base64" in body[:200]: return m.group(0)
        decls = []
        flexcol = "flex-direction:column" in body.replace(" ", "")
        for d in re.split(r";(?![^(]*\))", body):
            if not d.strip(): continue
            if ":" not in d: decls.append(d); continue
            prop, val = d.split(":", 1); p = prop.strip()
            if p == "inset":
                v = val.replace("!important", "").strip(); imp = " !important" if "!important" in val else ""
                parts = v.split()
                if len(parts) == 1: t = r_ = b = l = parts[0]
                elif len(parts) == 2: t = b = parts[0]; r_ = l = parts[1]
                elif len(parts) == 3: t, r_, b = parts; l = parts[1]
                else: t, r_, b, l = parts[:4]
                decls += ["top:%s%s" % (t, imp), "right:%s%s" % (r_, imp), "bottom:%s%s" % (b, imp), "left:%s%s" % (l, imp)]
                continue
            if "clamp(" in val:
                fb = clamp_fallback(val)
                if fb: decls.append("%s:%s" % (prop, fb))
            if p == "backdrop-filter": decls.append("-webkit-backdrop-filter:" + val)
            if p == "aspect-ratio":
                wm = re.search(r"(?:^|;)\s*width:\s*(?:min\([^,]*,\s*)?([\d.]+)px", body)
                rm = re.fullmatch(r"\s*([\d.]+)\s*(?:/\s*([\d.]+))?\s*", val.replace("!important", ""))
                if wm and rm:
                    w = float(wm.group(1)); ratio = float(rm.group(1)) / float(rm.group(2) or 1)
                    extra.append("@supports not (aspect-ratio:1/1){%s{height:%dpx}}" % (sel.strip(), round(w / ratio)))
            if p == "gap":
                g = val.replace("!important", "").split()[0]
                kids = ",".join(".nogap %s>*+*" % x.strip() for x in sel.split(","))
                extra.append("%s{%s:%s}" % (kids, "margin-top" if flexcol else "margin-left", g))
            decls.append(d)
        return sel + "{" + ";".join(decls) + "}"
    # solo regole semplici (selettore{dichiarazioni}), anche dentro @media
    css2 = re.sub(r"([^{}@][^{}]*)\{([^{}]*)\}", fix_block, css)
    return css2 + "\n/* riserve per telefoni vecchi */\n" + "\n".join(extra) + "\n"

GAP_JS = """(function(){try{var d=document.createElement('div');d.style.cssText='display:flex;flex-direction:column;row-gap:1px;position:absolute;visibility:hidden';d.appendChild(document.createElement('div'));d.appendChild(document.createElement('div'));document.documentElement.appendChild(d);var ok=d.scrollHeight===1;d.parentNode.removeChild(d);if(!ok)document.documentElement.className+=' nogap';}catch(e){}})();"""

def process(path):
    s = open(path, encoding="utf-8").read()
    # CSS
    s = re.sub(r"(<style[^>]*>)(.*?)(</style>)", lambda m: m.group(1) + fix_css(m.group(2)) + m.group(3), s, flags=re.S)
    # JS: ricompila ogni script inline; il primo script dell'app riceve il controllo del gap
    scripts = list(re.finditer(r"(<script(?![^>]*\bsrc=)[^>]*>)(.*?)(</script>)", s, re.S))
    out, last = [], 0
    for k, m in enumerate(scripts):
        js = m.group(2)
        if len(js) > 200: js = transpile(js)
        if k == len(scripts) - 1: js = GAP_JS + "\n" + js
        out.append(s[last:m.start(2)]); out.append(js); last = m.end(2)
    out.append(s[last:]); s = "".join(out)
    hs = ["'sha256-%s'" % base64.b64encode(hashlib.sha256(x.group(1).encode()).digest()).decode()
          for x in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", s, re.S)]
    s = re.sub(r"script-src [^;]*;", "script-src " + " ".join(hs) + ";", s, count=1)
    open(path, "w", encoding="utf-8").write(s)
    print(path, "ok", len(s))

for p in sys.argv[1:]: process(p)
