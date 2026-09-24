import math, random
src=open("birds.py").read().split("V={}")[0]
ns={}; exec(src, ns)
bird, fit = ns["bird"], ns["fit"]
INK="#2B1F2E"; LAMP="#C8912F"; DINK="#EDE6D9"; DLAMP="#F0C27A"
def seven_final(radius=31, around=12.2, centre=15.5, heading=0.12, jitter=0.025, seed=7):
    """The lit bird and the seven it watches: an even ring, so the outline reads as a circle,
    every bird banking the same small way, as a flock turning together."""
    rnd=random.Random(seed)
    it=[(50,50,centre,heading)]
    for k in range(7):
        a=-math.pi/2+k*2*math.pi/7
        rr=radius*(1+rnd.uniform(-jitter,jitter))
        it.append((50+math.cos(a)*rr, 50+math.sin(a)*rr, around*(1+rnd.uniform(-jitter,jitter)), heading+rnd.uniform(-0.05,0.05)))
    return fit(it, pad=4)
def svg(items, ink, lamp, label="murmur"):
    body="".join(f'<path fill="{lamp if i==0 else ink}" d="{bird(x,y,s,r)}"/>' for i,(x,y,s,r) in enumerate(items))
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="120" height="120" role="img" aria-label="{label}">{body}</svg>'
it=seven_final()
out=""
open(out+"murmur-mark.svg","w").write(svg(it,INK,LAMP))
open(out+"murmur-mark-dusk.svg","w").write(svg(it,DINK,DLAMP))
html=['<html><head><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT,WONK@9..144,300..700,0..100,0..1&display=block"></head><body style="margin:0;font-family:Fraunces">']
for bg,f,col in [("#F7EEDC","murmur-mark.svg","#2B1F2E"),("#FFFFFF","murmur-mark.svg","#2B1F2E"),("#1F1C24","murmur-mark-dusk.svg","#EDE6D9")]:
    html.append(f'<div style="background:{bg};color:{col};display:flex;align-items:center;gap:22px;padding:22px 28px">'
                f'<img src="{out}{f}" width="200"><span style="display:inline-flex;align-items:center;gap:14px"><img src="{out}{f}" width="64"><span style="font:440 48px/1 Fraunces;font-variation-settings:\'SOFT\' 100,\'WONK\' 1,\'opsz\' 72">murmur</span></span>'
                f'<span style="display:inline-flex;align-items:center;gap:8px"><img src="{out}{f}" width="28"><span style="font:480 22px/1 Fraunces;font-variation-settings:\'SOFT\' 100,\'WONK\' 1,\'opsz\' 24">murmur</span></span>'
                f'<img src="{out}{f}" width="32"><img src="{out}{f}" width="16"></div>')
open("final7.html","w").write("".join(html)+"</body></html>")
