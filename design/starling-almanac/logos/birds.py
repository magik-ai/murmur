import math, random
INK="#2B1F2E"; LAMP="#C8912F"; DINK="#EDE6D9"; DLAMP="#F0C27A"

def bird(x,y,s,rot=0.0,lift=0.44,thick=0.48):
    c,sn=math.cos(rot),math.sin(rot)
    T=lambda px,py:(x+(px*c-py*sn)*s, y+(px*sn+py*c)*s)
    a=T(-1,0.04); b=T(-0.5,-lift); m=T(0,0.1); d=T(0.5,-lift); e=T(1,0.04)
    bl=T(0.52,-lift+thick); bo=T(0,0.55); al=T(-0.52,-lift+thick)
    f=lambda p:f"{p[0]:.2f} {p[1]:.2f}"
    return f"M{f(a)}Q{f(b)} {f(m)}Q{f(d)} {f(e)}Q{f(bl)} {f(bo)}Q{f(al)} {f(a)}Z"

def inside(p,poly):
    x,y=p; c=False; n=len(poly)
    for i in range(n):
        x1,y1=poly[i]; x2,y2=poly[(i+1)%n]
        if (y1>y)!=(y2>y) and x < (x2-x1)*(y-y1)/(y2-y1)+x1: c=not c
    return c
def edge_dist(p,poly):
    best=1e9
    for i in range(len(poly)):
        x1,y1=poly[i]; x2,y2=poly[(i+1)%len(poly)]
        dx,dy=x2-x1,y2-y1; L=dx*dx+dy*dy or 1
        u=max(0,min(1,((p[0]-x1)*dx+(p[1]-y1)*dy)/L))
        best=min(best,math.hypot(p[0]-x1-u*dx,p[1]-y1-u*dy))
    return best
def resample(poly, step):
    L=[0]
    for i in range(1,len(poly)+1):
        a=poly[i-1]; b=poly[i%len(poly)]; L.append(L[-1]+math.hypot(b[0]-a[0],b[1]-a[1]))
    out=[]; s=0; k=0; total=L[-1]
    n=max(3,round(total/step)); step=total/n
    for j in range(n):
        s=j*step
        while L[k+1]<s: k+=1
        a=poly[k]; b=poly[(k+1)%len(poly)]; u=(s-L[k])/max(1e-9,L[k+1]-L[k])
        out.append((a[0]+(b[0]-a[0])*u, a[1]+(b[1]-a[1])*u))
    return out
def fill(poly, size, border=True, gap=2.25, seed=1, tilt=0.0, jitter=0.18, inset=0.7):
    """Birds shoulder to shoulder along the outline, then a jittered hex grid inside, looser
    toward the middle the way a real flock is."""
    rnd=random.Random(seed); birds=[]
    if border:
        cx=sum(p[0] for p in poly)/len(poly); cy=sum(p[1] for p in poly)/len(poly)
        for (x,y) in resample(poly, size*gap):
            # push inward along the local normal by testing both sides
            best=None
            for ang in range(0,360,15):
                dx,dy=math.cos(math.radians(ang))*size*inset, math.sin(math.radians(ang))*size*inset
                q=(x+dx,y+dy)
                if inside(q,poly):
                    dd=edge_dist(q,poly)
                    if best is None or dd>best[0]: best=(dd,q)
            if best: birds.append([best[1][0],best[1][1],size])
    step=size*gap*1.08
    xs=[p[0] for p in poly]; ys=[p[1] for p in poly]
    row=0; y=min(ys)
    while y<max(ys):
        x=min(xs)+(step/2 if row%2 else 0)
        while x<max(xs):
            q=(x+rnd.uniform(-1,1)*step*jitter, y+rnd.uniform(-1,1)*step*jitter)
            if inside(q,poly) and edge_dist(q,poly)>size*1.5 and all(math.hypot(q[0]-b[0],q[1]-b[1])>size*gap*0.92 for b in birds):
                birds.append([q[0],q[1],size*rnd.uniform(0.86,1.0)])
            x+=step
        y+=step*0.866; row+=1
    return [(b[0],b[1],b[2],tilt+rnd.uniform(-0.12,0.12)) for b in birds]

def fit(items, pad=5, box=100):
    xs=[]; ys=[]
    for x,y,s,*_ in items: xs+= [x-s,x+s]; ys+=[y-s*0.6,y+s*0.7]
    w=max(xs)-min(xs); h=max(ys)-min(ys); side=max(w,h)+pad*2; k=box/side
    cx=(max(xs)+min(xs))/2; cy=(max(ys)+min(ys))/2
    return [((x-cx)*k+box/2,(y-cy)*k+box/2,s*k,*rest) for x,y,s,*rest in items]

def to_svg(items, lit, ink, lamp, extra=""):
    body=[]
    for i,(x,y,s,r) in enumerate(items):
        body.append(f'<path fill="{lamp if i in lit else ink}" d="{bird(x,y,s,r)}"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{extra}{"".join(body)}</svg>'

def nearest(items, pt):
    return min(range(len(items)), key=lambda i:(items[i][0]-pt[0])**2+(items[i][1]-pt[1])**2)

V={}
# 1. Seven neighbours: the rule itself, one lit bird and the seven it watches
def seven():
    it=[(50,52,15,0.0)]
    for k in range(7):
        a=-math.pi/2+k*2*math.pi/7
        x=50+math.cos(a)*33; y=52+math.sin(a)*31
        it.append((x,y,11.5,math.sin(a*1.0)*0.18))
    return it,{0}
# 2. The flock that draws a bird: a big bird's silhouette filled with small ones
def bigbird():
    poly=[]
    lift=0.42; thick=0.46
    # trace the big crescent as a polygon from the same curves as the glyph
    def q(p0,p1,p2,n=40):
        return [((1-t)**2*p0[0]+2*(1-t)*t*p1[0]+t*t*p2[0], (1-t)**2*p0[1]+2*(1-t)*t*p1[1]+t*t*p2[1]) for t in [i/n for i in range(n)]]
    S=46; cx,cy=50,56
    P=lambda px,py:(cx+px*S, cy+py*S)
    a=P(-1,0.04); b=P(-0.5,-lift); m=P(0,0.1); d=P(0.5,-lift); e=P(1,0.04); bl=P(0.52,-lift+thick); bo=P(0,0.55); al=P(-0.52,-lift+thick)
    poly=q(a,b,m)+q(m,d,e)+q(e,bl,bo)+q(bo,al,a)
    it=fill(poly,3.3,gap=2.3,seed=4)
    return it,{nearest(it,(50,64))}
# 3. The drop
def drop():
    R=31; poly=[]
    for k in range(260):
        t=2*math.pi*k/260; x=math.cos(t)*R; y=math.sin(t)*R*0.9
        w=max(0,math.cos(t))**6; x+=w*R*0.95
        ang=-0.75; poly.append((50+x*math.cos(ang)-y*math.sin(ang), 50+x*math.sin(ang)+y*math.cos(ang)))
    it=fill(poly,6.6,gap=2.15,seed=3)
    return it,{nearest(it,(44,55))}
# 4. The roost: a flock pouring down a funnel into the one lit bird
def funnel():
    poly=[]
    for k in range(120):
        t=k/119; y=12+t*70; w=40*(1-t)**1.15+3
        poly.append((50+w*math.sin(t*2.2)*0.18+w, y))
    right=poly
    left=[(2*50-x+ (x-50)*0 , y) for x,y in right]
    left=[(100-x+ (8*math.sin(y/70*2.2)), y) for x,y in right]
    poly=right+left[::-1]
    it=fill(poly,5.2,gap=2.2,seed=6)
    it=[p for p in it if p[1]<76]
    it.append((50+2,90,8.5,0.0))
    return it,{len(it)-1}
# 5. The ribbon: a murmuration stretched into an S
def ribbon():
    pts=[]
    def c(t):
        # a cubic S from lower left to upper right
        p0,p1,p2,p3=(8,74),(40,108),(60,-8),(92,26)
        x=(1-t)**3*p0[0]+3*(1-t)**2*t*p1[0]+3*(1-t)*t*t*p2[0]+t**3*p3[0]
        y=(1-t)**3*p0[1]+3*(1-t)**2*t*p1[1]+3*(1-t)*t*t*p2[1]+t**3*p3[1]
        return x,y
    N=160; top=[]; bot=[]
    for k in range(N+1):
        t=k/N; x,y=c(t); x2,y2=c(min(1,t+0.001)); x1,y1=c(max(0,t-0.001))
        dx,dy=x2-x1,y2-y1; L=math.hypot(dx,dy) or 1; nx,ny=-dy/L,dx/L
        w=3+15*math.sin(math.pi*t)**0.9
        top.append((x+nx*w,y+ny*w)); bot.append((x-nx*w,y-ny*w))
    poly=top+bot[::-1]
    it=fill(poly,4.6,gap=2.2,seed=8)
    return it,{nearest(it,(50,50))}
# 6. The moon: a crescent of birds with the lit one as its star
def moon():
    poly=[]; R=36; cx,cy=46,54; ox,oy=15,-10
    for k in range(200):
        t=2*math.pi*k/200; p=(cx+math.cos(t)*R, cy+math.sin(t)*R)
        if math.hypot(p[0]-cx-ox,p[1]-cy-oy)>R*0.86: poly.append(p)
    # close along the inner arc
    inner=[]
    for k in range(200):
        t=2*math.pi*k/200; p=(cx+ox+math.cos(t)*R*0.86, cy+oy+math.sin(t)*R*0.86)
        if math.hypot(p[0]-cx,p[1]-cy)<R: inner.append(p)
    # order: outer arc points by angle around the outer centre, inner arc reversed
    def ang(p,c): return math.atan2(p[1]-c[1],p[0]-c[0])
    ref=math.atan2(oy,ox)
    outer=sorted(poly,key=lambda p:(ang(p,(cx,cy))-ref)%(2*math.pi))
    inn=sorted(inner,key=lambda p:(ang(p,(cx+ox,cy+oy))-ref)%(2*math.pi))
    poly=outer+inn[::-1]
    it=fill(poly,5.0,gap=2.2,seed=9)
    it.append((80,22,8.5,0.1))
    return it,{len(it)-1}
# 7. The orbit: nine birds wheeling round the lit one, seen a little from the side
def orbit():
    it=[(50,50,12,0.0)]
    for k in range(9):
        a=k*2*math.pi/9+0.35
        x=50+math.cos(a)*38; y=50+math.sin(a)*19
        depth=(math.sin(a)+1)/2
        it.append((x,y,7.5+6*depth,0.0))
    return it,{0}
# 8. The loop: a murmuration folding into a figure of eight
def loop():
    it=[]; N=16
    for k in range(N):
        t=2*math.pi*k/N+0.1
        d=1+math.sin(t)**2
        x=50+40*math.cos(t)/d; y=50+30*math.sin(t)*math.cos(t)/d
        it.append((x,y,7.2+2.2*math.cos(t)**2,0.0))
    it.append((50,50,9.5,0.0))
    return it,{len(it)-1}
# 9. The spiral: nine birds winding inward, each a little smaller
def spiral():
    it=[]; n=9; sizes=[15-i*1.05 for i in range(n)]
    t=0.2; b=0.22
    pts=[]
    tt=0.0; last=None
    samples=[]
    for k in range(4000):
        u=k/4000*2.1*math.pi
        r=38*math.exp(-b*u)
        samples.append((50+math.cos(u+2.6)*r, 50+math.sin(u+2.6)*r*0.94))
    L=[0]
    for k in range(1,len(samples)): L.append(L[-1]+math.hypot(samples[k][0]-samples[k-1][0],samples[k][1]-samples[k-1][1]))
    pos=0; j=0
    for i in range(n):
        while j<len(L)-1 and L[j]<pos: j+=1
        x,y=samples[j]; it.append((x,y,sizes[i],0.0))
        if i<n-1: pos+= (sizes[i]+sizes[i+1])*1.3
    return it,{n-1}
# 10. One leaves the flock: a round flock, and the lit bird taking its own lane
def leaves():
    poly=[(44+math.cos(2*math.pi*k/200)*32, 56+math.sin(2*math.pi*k/200)*30) for k in range(200)]
    it=fill(poly,5.0,gap=2.2,seed=12)
    it.append((86,16,8.5,-0.25))
    return it,{len(it)-1}

# 2 (again): a gull's silhouette, chunky enough to read as one bird, made of small birds
def bigbird():
    def q(p0,p1,p2,n=50):
        return [((1-t)**2*p0[0]+2*(1-t)*t*p1[0]+t*t*p2[0], (1-t)**2*p0[1]+2*(1-t)*t*p1[1]+t*t*p2[1]) for t in [i/n for i in range(n)]]
    S=46; cx,cy=50,58; lift=0.78; thick=0.62
    P=lambda px,py:(cx+px*S, cy+py*S)
    a=P(-1,0.02); b=P(-0.5,-lift); m=P(0,0.12); d=P(0.5,-lift); e=P(1,0.02); bl=P(0.54,-lift+thick); bo=P(0,0.62); al=P(-0.54,-lift+thick)
    poly=q(a,b,m)+q(m,d,e)+q(e,bl,bo)+q(bo,al,a)
    it=fill(poly,3.1,gap=2.02,seed=4,inset=0.6)
    return it,{nearest(it,(50,70))}
# 4 (again): the roost, a funnel that bends as it pours down into the one lit bird
def funnel():
    N=140; L=[]; R=[]
    for k in range(N+1):
        t=k/N; y=10+t*72
        cxl=50+10*math.sin(t*math.pi*1.1)
        w=36*(1-t)**1.5+2.2
        L.append((cxl-w,y)); R.append((cxl+w,y))
    cap=[(50+10*math.sin(0)+36*math.cos(u), 10-9*math.sin(u)) for u in [math.pi*i/30 for i in range(31)]]
    poly=cap+L[1:]+R[::-1][:-1]
    it=fill(poly,4.3,gap=2.2,seed=6,inset=0.65)
    it.append((50+10*math.sin(math.pi*1.1)+1,92,7.5,0.0))
    return it,{len(it)-1}
# 5 (again): a real murmuration's outline, two lobes pinched at the waist
def bean():
    poly=[]
    for k in range(300):
        t=2*math.pi*k/300
        r=31*(1+0.46*math.cos(2*t))*(1+0.2*math.cos(t))
        x=r*math.cos(t)*1.05; y=r*math.sin(t)*1.0
        ang=-0.38
        poly.append((50+x*math.cos(ang)-y*math.sin(ang), 50+x*math.sin(ang)+y*math.cos(ang)))
    it=fill(poly,4.0,gap=2.1,seed=10,inset=0.65)
    return it,{nearest(it,(50,50))}
# 7 (again): the orbit, eight birds on a flattened ring, larger in front, none touching
def orbit():
    it=[(50,48,11.5,0.0)]
    for k in range(8):
        a=k*2*math.pi/8+math.pi/8
        depth=(math.sin(a)+1)/2
        x=50+math.cos(a)*40; y=50+math.sin(a)*22
        it.append((x,y,6.5+5.5*depth,0.0))
    return it,{0}
# 8 (again): the loop, birds along a figure of eight with the crossing left open for the lit one
def loop():
    it=[]; N=18
    for k in range(N):
        t=2*math.pi*(k+0.5)/N
        d=1+math.sin(t)**2
        x=50+42*math.cos(t)/d; y=50+32*math.sin(t)*math.cos(t)/d
        if math.hypot(x-50,y-50)<11: continue
        it.append((x,y,6.6+2.4*math.cos(t)**2,0.0))
    it.append((50,50,9.5,0.0))
    return it,{len(it)-1}
# 9 (again): the spiral, twenty birds winding inward to the lit one, dense enough to read as a curl
def spiral():
    n=21; sizes=[8.6-i*0.24 for i in range(n)]
    samples=[]
    for k in range(8000):
        u=k/8000*2.35*math.pi
        r=42*math.exp(-0.3*u)
        samples.append((50+math.cos(u+2.3)*r, 50+math.sin(u+2.3)*r))
    L=[0]
    for k in range(1,len(samples)): L.append(L[-1]+math.hypot(samples[k][0]-samples[k-1][0],samples[k][1]-samples[k-1][1]))
    it=[]; pos=0; j=0
    for i in range(n):
        while j<len(L)-1 and L[j]<pos: j+=1
        x,y=samples[j]
        x2,y2=samples[min(j+5,len(samples)-1)]
        head=math.atan2(y2-y,x2-x)
        tilt=math.atan2(math.sin(head),abs(math.cos(head)))*0.35*(1 if math.cos(head)>=0 else -1)
        it.append((x,y,sizes[i],tilt))
        if i<n-1: pos+=(sizes[i]+sizes[i+1])*1.12
    return it,{n-1}
V=[("Seven neighbours",seven),("A bird made of the flock",bigbird),("The drop",drop),("The roost",funnel),("The murmuration",bean),
   ("The moon",moon),("The orbit",orbit),("The loop",loop),("The spiral",spiral),("One leaves the flock",leaves)]
import json
out=[]
for i,(name,fn) in enumerate(V,1):
    it,lit=fn(); it=fit(it)
    light=to_svg(it,lit,INK,LAMP); dark=to_svg(it,lit,DINK,DLAMP)
    open(f"i{i}.svg","w").write(light); open(f"i{i}-dark.svg","w").write(dark)
    out.append((i,name,len(it)))
json.dump(out,open("index.json","w"))
html=['<html><body style="margin:0;background:#F7EEDC;font:13px system-ui;color:#555;padding:16px">']
for i,name,n in out:
    html.append(f'<div style="display:flex;align-items:center;gap:16px;margin-bottom:10px"><b style="width:170px">{i} {name} ({n})</b>'+"".join(f'<img src="i{i}.svg" width="{w}">' for w in (16,24,32,64,140))+f'<span style="background:#1F1C24;padding:8px;border-radius:8px;display:inline-flex;gap:10px;align-items:center"><img src="i{i}-dark.svg" width="16"><img src="i{i}-dark.svg" width="32"><img src="i{i}-dark.svg" width="64"></span></div>')
open("sheet.html","w").write("".join(html)+"</body></html>")
