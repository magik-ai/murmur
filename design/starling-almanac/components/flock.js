/* @ds-bundle: {"format":4,"namespace":"Murmur","components":[{"name":"Button"},{"name":"Segmented"},{"name":"IconButton"},{"name":"Status"},{"name":"Tag"},{"name":"LimitBar"},{"name":"Tile"},{"name":"Table"},{"name":"Card"},{"name":"Field"},{"name":"Choices"},{"name":"ChoiceCard"},{"name":"Command"},{"name":"Banner"},{"name":"Steps"},{"name":"Drawer"},{"name":"Nav"},{"name":"Tabs"},{"name":"Text"},{"name":"EmptyState"},{"name":"Wordmark"},{"name":"Flock"},{"name":"Gather"},{"name":"Ribbon"}]} */
/* murmur, Starling Almanac: the two pieces of the system that move.

   Murmur.flock(canvas, options) draws a murmuration the way real starlings make one, after
   the StarDisplay model (Hildenbrandt, Carere and Hemelrijk 2010) and the field measurements
   behind it (Ballerini et al. 2008, Attanasi et al. 2014, Hemelrijk et al. 2015):
   - a bird never changes direction by being pushed. It keeps a heading, a speed and a bank,
     and every rule only sets the bank it rolls toward, at a limited roll rate, so turns are
     banked arcs of two or three seconds rather than twitches;
   - speed relaxes back to one cruising speed, and birds avoid each other by turning, not
     braking;
   - each bird watches its SEVEN nearest neighbours (the topological rule), ignoring the ones
     behind it, keeps clear of the closest, copies their heading and drifts toward them,
     harder at the border of the flock than inside it;
   - a bird reacts about every fifteenth of a second, not every frame, so a turn travels
     across the flock neighbour by neighbour, at about twice the flock's speed;
   - the only randomness is a slow drift in the bank each bird wants, and the roost the flock
     wheels around drifts on a minute-long loop;
   - a banked bird shows more wing and reads darker, so every turn sends the dark band of a
     real murmuration rolling across the flock. Wings beat in short bursts and glide between.
   Colours come from the system's tokens (--ink, --lamp), so the flock follows the theme. It
   runs on a fixed clock (the same pace on every screen), stops when the canvas leaves the
   page, and draws one still frame when the reader asks for reduced motion.

   Options: count, speed (1 is an unhurried dusk flock), seed, spacing (1 dense, 2 airy),
   birdScale, roostX, roostY, roostReach (where the flock wheels, as fractions of the canvas),
   hold (how tightly it keeps to that place: 0.3 wheels wide, 2 stays close),
   avoid ({x0, y0, x1, y1} fractions the flock flies around, or a list of them), inspect
   (point at a bird to see the seven it watches). The handle can pause and play.

   Murmur.mount(root) starts every <canvas data-mm-flock> under root, reading data-count,
   data-speed, data-seed, data-spacing, data-bird-scale, data-roost-x, data-roost-y,
   data-roost-reach and data-inspect. */
(function () {
  "use strict";

  var NEIGHBOURS = 7;
  var TICK = 1000 / 60;
  /* Reaction: a bird rethinks its steering every fourth tick, staggered across the flock. */
  var REACT = 4;
  var MAX_TURN = 0.014;
  var ROLL_IN = 1 / 24;
  var ROLL_OUT = 1 / 48;
  var BLIND = -0.707;
  var ALPHAS = [0.46, 0.62, 0.78, 0.94];

  function readToken(element, name, fallback) {
    var value = getComputedStyle(element).getPropertyValue(name).trim();
    return value || fallback;
  }

  function seeded(seed) {
    var state = seed >>> 0 || 1;
    return function () {
      state ^= state << 13; state >>>= 0;
      state ^= state >>> 17;
      state ^= state << 5; state >>>= 0;
      return state / 4294967296;
    };
  }

  function smootherstep(x) {
    var t = Math.max(0, Math.min(1, x));
    return t * t * t * (t * (t * 6 - 15) + 10);
  }

  function flock(canvas, options) {
    var opts = options || {};
    var count = Math.max(40, Math.min(1400, Number(opts.count) || 420));
    var speed = Number(opts.speed) || 1;
    var random = seeded(Number(opts.seed) || 7);
    var context = canvas.getContext("2d");
    var ratio = Math.min(2, window.devicePixelRatio || 1);
    var width = 0;
    var height = 0;
    var birds = [];
    var ticks = 0;
    var running = false;
    var handle = 0;
    var last = 0;
    var owed = 0;
    var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var inspected = -1;
    var roostCX = opts.roostX != null ? Number(opts.roostX) : 0.5;
    var roostCY = opts.roostY != null ? Number(opts.roostY) : 0.5;
    var roostRX = opts.roostReach != null ? Number(opts.roostReach) : 0.3;
    /* How tightly the flock keeps to its roost: 0.3 lets it wheel wide, 2 holds it close, for a
       hero whose flock must stay clear of the page's edges. */
    var hold = opts.hold != null ? Number(opts.hold) : 0.3;
    var holdRamp = 150 / Math.max(1, hold * 2.5);
    /* How far apart the birds keep: 1 is a dense winter flock, 2 an airy one over a page. */
    var spacing = opts.spacing != null ? Number(opts.spacing) : 1;
    var birdScale = opts.birdScale != null ? Number(opts.birdScale) : 1;
    /* Places the flock flies around, as a flock banks around a tower: one box or a list. */
    var avoid = !opts.avoid ? [] : Array.isArray(opts.avoid) ? opts.avoid : [opts.avoid];
    var onInspect = typeof opts.onInspect === "function" ? opts.onInspect : null;
    var cruise = 0.9 * speed;
    var separation = 14 * spacing;
    var reach = 40 * spacing;
    var SEP_W = 0.4, ALIGN_W = 1, COH_W = 0.3;
    var AVOID_ROOM = 150;
    var cell = Math.round(40 * spacing);

    function gauss() {
      var u = random() || 1e-9, v = random();
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(6.2832 * v);
    }

    function resize() {
      var box = canvas.getBoundingClientRect();
      width = Math.max(1, box.width);
      height = Math.max(1, box.height);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    }

    /* The roost the flock wheels around: an ellipse whose centre drifts on a slow loop. */
    function roost() {
      var t = ticks / 60;
      var rx = roostRX * width;
      return {
        x: width * (roostCX + roostRX * 0.28 * Math.sin(t * 6.2832 / 52)),
        y: height * roostCY + rx * 0.16 * Math.sin(t * 6.2832 / 37 + 1.1),
        rx: rx,
        ry: Math.min(height * 0.3, rx * 0.62)
      };
    }

    function seed() {
      birds = [];
      var home = roost();
      var heading = random() * 6.2832;
      for (var i = 0; i < count; i += 1) {
        var angle = random() * 6.2832;
        var radius = Math.sqrt(random());
        birds.push({
          x: home.x + Math.cos(angle) * radius * home.rx * 0.5,
          y: home.y + Math.sin(angle) * radius * home.ry * 0.35,
          h: heading + (random() - 0.5) * 0.6,
          v: cruise * (0.9 + random() * 0.2),
          b: 0,
          want: 0,
          drift: 0,
          side: 0,
          ahead: 0,
          z: random(),
          size: 2.2 + random() * 1.6,
          beat: random() * 6.2832,
          flapping: random() < 0.5,
          left: Math.floor(random() * 80),
          lit: i === Math.floor(count * 0.61)
        });
      }
    }

    function buildGrid() {
      var columns = Math.ceil(width / cell) + 3;
      var grid = {};
      for (var i = 0; i < birds.length; i += 1) {
        var key = (Math.floor(birds[i].x / cell) + 1) + (Math.floor(birds[i].y / cell) + 1) * columns;
        (grid[key] || (grid[key] = [])).push(i);
      }
      return { grid: grid, columns: columns };
    }

    /* One bird thinks: it finds its seven nearest, sums what each rule asks of it, and keeps
       only two numbers, how hard to bank and whether to speed up. */
    function think(i, index, home) {
      var bird = birds[i];
      var gx = Math.floor(bird.x / cell) + 1, gy = Math.floor(bird.y / cell) + 1;
      var near = [];
      for (var dy = -1; dy <= 1; dy += 1) {
        for (var dx = -1; dx <= 1; dx += 1) {
          var bucket = index.grid[(gx + dx) + (gy + dy) * index.columns];
          if (!bucket) continue;
          for (var j = 0; j < bucket.length; j += 1) {
            if (bucket[j] === i) continue;
            var other = birds[bucket[j]];
            var ox = other.x - bird.x, oy = other.y - bird.y;
            near.push({ d: ox * ox + oy * oy, o: other, ox: ox, oy: oy });
          }
        }
      }
      near.sort(function (one, two) { return one.d - two.d; });
      var n = Math.min(NEIGHBOURS, near.length);
      var hx = Math.cos(bird.h), hy = Math.sin(bird.h);
      var fx = 0, fy = 0;
      var ax = 0, ay = 0, cx = 0, cy = 0, ux = 0, uy = 0, seen = 0;
      for (var k = 0; k < n; k += 1) {
        var m = near[k];
        var d = Math.sqrt(m.d) || 0.001;
        var rx = m.ox / d, ry = m.oy / d;
        /* Keep clear of the nearest bird only; pushing against all seven makes a flock boil. */
        if (k === 0 && d < separation) {
          var push = SEP_W * (1 - d / separation);
          fx -= rx * push; fy -= ry * push;
        }
        if (rx * hx + ry * hy < BLIND) continue;
        seen += 1;
        ax += Math.cos(m.o.h); ay += Math.sin(m.o.h);
        cx += m.ox; cy += m.oy;
        ux += rx; uy += ry;
      }
      if (seen) {
        fx += ALIGN_W * (ax / seen - hx); fy += ALIGN_W * (ay / seen - hy);
        var centrality = Math.sqrt(ux * ux + uy * uy) / seen;
        cx /= seen; cy /= seen;
        var cd = Math.sqrt(cx * cx + cy * cy) || 0.001;
        var pull = COH_W * smootherstep(cd / reach) * (0.5 + centrality);
        fx += cx / cd * pull; fy += cy / cd * pull;
      }
      var gx = 0, gy = 0;
      /* Outside the roost's ellipse a bird is turned back toward it, harder the more it heads
         away: this is what keeps the flock wheeling instead of leaving. */
      var ex = (bird.x - home.x) / home.rx, ey = (bird.y - home.y) / home.ry;
      var er = Math.sqrt(ex * ex + ey * ey);
      if (er > 1) {
        var ix = -(bird.x - home.x), iy = -(bird.y - home.y);
        var il = Math.sqrt(ix * ix + iy * iy) || 1;
        ix /= il; iy /= il;
        var outward = -(ix * hx + iy * hy);
        var strength = hold * Math.min(1, (er - 1) * home.rx / holdRamp) * (0.5 + 0.5 * outward);
        gx += ix * strength; gy += iy * strength;
      }
      /* The words are a tower the flock banks around: the pull away from them starts well
         before the edge, because a bird that can only bank needs room to turn. */
      for (var w = 0; w < avoid.length; w += 1) {
        var zone = avoid[w];
        var x0 = zone.x0 * width, x1 = zone.x1 * width, y0 = zone.y0 * height, y1 = zone.y1 * height;
        var px = Math.max(x0, Math.min(x1, bird.x)), py = Math.max(y0, Math.min(y1, bird.y));
        var ox2 = bird.x - px, oy2 = bird.y - py;
        var gap = Math.sqrt(ox2 * ox2 + oy2 * oy2);
        if (gap < AVOID_ROOM) {
          var away = 1.6 * (1 - smootherstep(gap / AVOID_ROOM));
          if (gap < 0.001) { ox2 = 1; oy2 = 0; gap = 1; }
          gx += ox2 / gap * away; gy += oy2 / gap * away;
        }
      }
      /* The sky has edges: near one a bird banks back, the way a flock turns at a treeline. */
      var margin = Math.min(220, 0.3 * Math.min(width, height));
      if (bird.x < margin) gx += (margin - bird.x) / margin;
      else if (bird.x > width - margin) gx -= (bird.x - width + margin) / margin;
      if (bird.y < margin) gy += (margin - bird.y) / margin;
      else if (bird.y > height - margin) gy -= (bird.y - height + margin) / margin;
      /* A pull from the world straight behind a bird (the roost, the words, the edge) has no
         sideways part, so the bird picks a side and turns. Its neighbours never do this: a
         bird close ahead is followed, not turned away from. */
      var back = gx * hx + gy * hy;
      var side = (fx + gx) * -hy + (fy + gy) * hx, ahead = fx * hx + fy * hy + back;
      if (back < 0) side += (side < 0 ? -1 : 1) * -back * 0.5;
      bird.side = side;
      bird.ahead = ahead;
    }

    function step() {
      var home = roost();
      var index = buildGrid();
      var phase = ticks % REACT;
      for (var i = 0; i < birds.length; i += 1) {
        var bird = birds[i];
        if (i % REACT === phase) think(i, index, home);
        /* The one randomness: a slow wander in the bank a bird wants. */
        bird.drift += -bird.drift / 120 + 0.08 * Math.sqrt(2 / 120) * gauss();
        bird.want = Math.max(-1, Math.min(1, 2 * bird.side + bird.drift));
        var rollingIn = Math.abs(bird.want) > Math.abs(bird.b) && bird.want * bird.b >= 0;
        var rate = rollingIn ? ROLL_IN : ROLL_OUT;
        bird.b += Math.max(-rate, Math.min(rate, bird.want - bird.b));
        bird.h += MAX_TURN * bird.b;
        bird.v += (cruise - bird.v) / 60 + 0.02 * bird.ahead;
        bird.v = Math.max(cruise * 0.72, Math.min(cruise * 1.3, bird.v));
        bird.x += Math.cos(bird.h) * bird.v;
        bird.y += Math.sin(bird.h) * bird.v;
        bird.z += (0.5 - bird.z) / 300 + 0.02 * gauss();
        bird.z = Math.max(0, Math.min(1, bird.z));
        /* Flap in short bursts, glide between; a slow bird flaps sooner. */
        bird.left -= 1;
        if (bird.flapping) bird.beat += 6.2832 / 20;
        if (bird.left <= 0) {
          bird.flapping = !bird.flapping;
          bird.left = bird.flapping ? Math.round(20 * (3 + random())) :
            Math.round((bird.v < cruise * 0.95 ? 40 : 50) + random() * 40);
          if (!bird.flapping) bird.beat = 0;
        }
      }
      ticks += 1;
    }

    /* A bird, not a dot: two crescent wings meeting at a small body. The wings rise and fall
       while it flaps and hold still while it glides; a banked bird shows more of its wing. */
    function traceBird(b, scale) {
      var lift = b.flapping ? 0.18 + 0.42 * (0.5 + 0.5 * Math.sin(b.beat)) : 0.3;
      var bank = Math.abs(b.b);
      var body = 0.28 + 0.26 * bank;
      var facing = Math.cos(b.h) >= 0 ? 1 : -1;
      var tilt = Math.atan2(Math.sin(b.h), Math.abs(Math.cos(b.h))) * 0.45 + b.b * 0.22 * facing;
      var s = b.size * scale * birdScale * (0.8 + 0.35 * b.z);
      var c = Math.cos(tilt), n = Math.sin(tilt);
      function x(px, py) { return b.x + (px * c - py * n) * s; }
      function y(px, py) { return b.y + (px * n + py * c) * s; }
      context.moveTo(x(-1, 0), y(-1, 0));
      context.quadraticCurveTo(x(-0.5, -lift), y(-0.5, -lift), x(0, 0.12), y(0, 0.12));
      context.quadraticCurveTo(x(0.5, -lift), y(0.5, -lift), x(1, 0), y(1, 0));
      context.quadraticCurveTo(x(0.5, -lift + body), y(0.5, -lift + body), x(0, 0.5), y(0, 0.5));
      context.quadraticCurveTo(x(-0.5, -lift + body), y(-0.5, -lift + body), x(-1, 0), y(-1, 0));
    }

    function drawOne(b, scale) {
      context.beginPath();
      traceBird(b, scale);
      context.fill();
    }

    function nearestSeven(index) {
      var me = birds[index];
      var ranked = [];
      for (var i = 0; i < birds.length; i += 1) {
        if (i === index) continue;
        var dx = birds[i].x - me.x, dy = birds[i].y - me.y;
        ranked.push({ i: i, d: dx * dx + dy * dy });
      }
      ranked.sort(function (a, b) { return a.d - b.d; });
      return ranked.slice(0, NEIGHBOURS).map(function (r) { return r.i; });
    }

    /* Four shades, drawn as four paths: a bird's shade is its bank and its depth, so the
       dark band of a turn rolls across the flock. */
    function draw() {
      var ink = readToken(canvas, "--ink", "#2B1F2E");
      var lamp = readToken(canvas, "--lamp", "#C8912F");
      context.clearRect(0, 0, width, height);
      context.fillStyle = ink;
      for (var shade = 0; shade < ALPHAS.length; shade += 1) {
        context.globalAlpha = ALPHAS[shade];
        context.beginPath();
        for (var i = 0; i < birds.length; i += 1) {
          var b = birds[i];
          if (b.lit) continue;
          var level = Math.min(3, Math.floor((0.55 * Math.abs(b.b) + 0.45 * b.z) * 4.4));
          if (level === shade) traceBird(b, 1);
        }
        context.fill();
      }
      context.globalAlpha = 1;
      context.fillStyle = lamp;
      for (var l = 0; l < birds.length; l += 1) {
        if (birds[l].lit) drawOne(birds[l], 1.45);
      }
      if (inspected >= 0 && inspected < birds.length) {
        var me = birds[inspected];
        var accent = readToken(canvas, "--accent", "#5B4A8A");
        var near = nearestSeven(inspected);
        context.strokeStyle = lamp;
        context.lineWidth = 1;
        context.globalAlpha = 0.85;
        for (var q = 0; q < near.length; q += 1) {
          context.beginPath();
          context.moveTo(me.x, me.y);
          context.lineTo(birds[near[q]].x, birds[near[q]].y);
          context.stroke();
        }
        context.globalAlpha = 1;
        context.fillStyle = accent;
        for (var r = 0; r < near.length; r += 1) drawOne(birds[near[r]], 1.3);
        context.fillStyle = lamp;
        drawOne(me, 1.7);
      }
    }

    /* A fixed clock: the flock takes the same number of steps a second on a 60 Hz and a
       120 Hz screen, and a stalled tab does not come back in a rush. */
    function loop(now) {
      if (!running) return;
      owed += Math.min(100, now - last);
      last = now;
      while (owed >= TICK) { step(); owed -= TICK; }
      draw();
      handle = window.requestAnimationFrame(loop);
    }

    function start() {
      if (running || reduced) return;
      running = true;
      last = performance.now();
      owed = 0;
      handle = window.requestAnimationFrame(loop);
    }

    function stop() {
      running = false;
      window.cancelAnimationFrame(handle);
    }

    resize();
    seed();
    /* A still frame first, the flock gathered at the middle of its roost and just beginning
       to wheel: a long warm-up let it drift to an edge before anyone saw it. */
    for (var warm = 0; warm < 60; warm += 1) step();
    draw();

    /* A pause the reader asked for holds until they ask again: coming back into view does not
       undo it. */
    var held = false, visible = true;
    var watcher = null;
    if ("IntersectionObserver" in window) {
      watcher = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) { visible = entry.isIntersecting; if (visible && !held) start(); else stop(); });
      });
      watcher.observe(canvas);
    } else {
      start();
    }
    window.addEventListener("resize", function () { resize(); draw(); });

    /* Point at a bird to see the seven it watches. Off unless asked for: the inspector is for
       the landing page and the docs, not for a flock that sits behind work. */
    if (opts.inspect) {
      canvas.addEventListener("pointermove", function (event) {
        var box = canvas.getBoundingClientRect();
        var px = event.clientX - box.left, py = event.clientY - box.top;
        var best = -1, bestD = 40 * 40;
        for (var i = 0; i < birds.length; i += 1) {
          var dx = birds[i].x - px, dy = birds[i].y - py, d = dx * dx + dy * dy;
          if (d < bestD) { bestD = d; best = i; }
        }
        inspected = best;
        if (onInspect) onInspect(best >= 0);
        if (!running) draw();
      });
      canvas.addEventListener("pointerleave", function () {
        inspected = -1;
        if (onInspect) onInspect(false);
        if (!running) draw();
      });
    }

    return {
      pause: function () { held = true; stop(); },
      play: function () { held = false; if (visible) start(); },
      running: function () { return running; },
      stop: function () { stop(); if (watcher) watcher.disconnect(); },
      birds: function () { return birds.length; },
      neighbours: NEIGHBOURS
    };
  }

  function mount(root) {
    var scope = root || document;
    var started = [];
    var canvases = scope.querySelectorAll("canvas[data-mm-flock]");
    for (var i = 0; i < canvases.length; i += 1) {
      var c = canvases[i];
      var num = function (name) { var v = c.getAttribute(name); return v == null ? undefined : Number(v); };
      started.push(flock(c, { count: num("data-count"), speed: num("data-speed"), seed: num("data-seed"),
        spacing: num("data-spacing"), birdScale: num("data-bird-scale"), roostX: num("data-roost-x"),
        roostY: num("data-roost-y"), roostReach: num("data-roost-reach"), inspect: c.hasAttribute("data-inspect") }));
    }
    return started;
  }

  window.Murmur = { flock: flock, mount: mount, NEIGHBOURS: NEIGHBOURS, version: "2" };
})();
