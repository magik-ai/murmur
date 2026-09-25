/* murmur.farm: the page's small behaviours. The flock starts after the words have painted,
   stops off screen, and draws one still frame under reduced motion. */
(function () {
  "use strict";

  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var narrow = window.matchMedia && window.matchMedia("(max-width: 720px)").matches;

  /* One switch for every moving thing on the page (WCAG 2.2.2). There is no separate pause
     button: each animation is its own control. A click, a tap, Enter or Space on any of them
     pauses them all, until the reader asks again. Coming back into view does not undo it. */
  var motion = {
    paused: false,
    parts: [],
    controls: [],
    add: function (part) { this.parts.push(part); if (this.paused && part.pause) part.pause(); },
    set: function (paused) {
      this.paused = paused;
      this.parts.forEach(function (part) { if (paused) part.pause(); else part.play(); });
      this.controls.forEach(function (node) {
        node.setAttribute("aria-pressed", String(paused));
        node.setAttribute("aria-label", paused ? "Play the animations" : "Pause the animations");
      });
    },
    control: function (node) {
      if (!node || reduced) return;
      node.setAttribute("role", "button");
      node.setAttribute("tabindex", "0");
      node.setAttribute("aria-pressed", "false");
      node.setAttribute("aria-label", "Pause the animations");
      node.removeAttribute("aria-hidden");
      node.addEventListener("click", function () { motion.set(!motion.paused); });
      node.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); motion.set(!motion.paused); }
      });
      this.controls.push(node);
    },
  };

  /* ------------------------------------------------------------ install tabs */
  Array.prototype.forEach.call(document.querySelectorAll("[data-install]"), function (box) {
    var tabs = box.querySelectorAll('[role="tab"]');
    function choose(tab) {
      Array.prototype.forEach.call(tabs, function (other) {
        var on = other === tab;
        other.setAttribute("aria-selected", String(on));
        other.tabIndex = on ? 0 : -1;
        var panel = document.getElementById(other.getAttribute("aria-controls"));
        /* Both panels keep their place, the one not chosen is only invisible: the box is as tall
           as its tallest panel either way, so switching moves nothing on the page. */
        if (panel) {
          panel.classList.toggle("is-off", !on);
          panel.setAttribute("aria-hidden", String(!on));
          panel.inert = !on;
        }
      });
      var which = /farm/.test(tab.id) ? "farm" : "plugin";
      Array.prototype.forEach.call(box.querySelectorAll("[data-foot]"), function (foot) {
        foot.hidden = foot.getAttribute("data-foot") !== which;
      });
    }
    Array.prototype.forEach.call(tabs, function (tab, index) {
      tab.addEventListener("click", function () { choose(tab); });
      tab.addEventListener("keydown", function (event) {
        if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
        var next = tabs[(index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        choose(next);
        next.focus();
      });
    });
  });

  /* -------------------------------------------------------------------- copy */
  var said = document.getElementById("copied");
  function announce(words) {
    if (!said) return;
    /* Emptied first, so a second copy in a row is read out too, not taken for old news. */
    said.textContent = "";
    setTimeout(function () { said.textContent = words; }, 50);
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-copy]"), function (button) {
    var back = 0;
    button.addEventListener("click", function () {
      var text = button.getAttribute("data-copy");
      function done() {
        button.textContent = "Copied";
        announce("Copied to the clipboard");
        clearTimeout(back);
        back = setTimeout(function () { button.textContent = "Copy"; }, 1600);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { select(button); });
      } else {
        select(button);
      }
    });
  });
  function select(button) {
    var pre = button.parentNode.querySelector("pre");
    if (!pre) return;
    var range = document.createRange();
    range.selectNodeContents(pre);
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  /* ---------------------------------------------------------------- journey */
  /* One change goes through the five steps: a lamp bird flies the dotted track, rests at each
     step while its column lights up, and flies on. Under reduced motion it rests at the first
     step. */
  (function journey() {
    var svg = document.getElementById("journeyTrack");
    var list = document.querySelector(".journey");
    if (!svg || !list) return;
    var NS = "http://www.w3.org/2000/svg";
    var steps = list.querySelectorAll("li");
    var ticks = [], stops = [], bird = null, width = 0, y = 44;
    function el(name, attrs) {
      var node = document.createElementNS(NS, name);
      for (var key in attrs) node.setAttribute(key, attrs[key]);
      svg.appendChild(node);
      return node;
    }
    function layout() {
      var box = svg.getBoundingClientRect();
      if (!box.width) return;
      width = box.width;
      svg.setAttribute("viewBox", "0 0 " + width + " 72");
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      stops = Array.prototype.map.call(steps, function (li) {
        var r = li.getBoundingClientRect();
        return r.left - box.left + 6;
      });
      el("path", { class: "track", d: "M 0 " + y + " L " + width + " " + y });
      ticks = stops.map(function (x) { return el("line", { class: "tick", x1: x, y1: y - 7, x2: x, y2: y + 7 }); });
      bird = el("path", { class: "bird", d: "M-10 0Q-5 -6 0 1Q5 -6 10 0Q5 -1.6 0 4.5Q-5 -1.6 -10 0Z" });
    }
    var TRAVEL = 1800, REST = 2600, LEG = TRAVEL + REST;
    function ease(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }
    function place(now) {
      if (!bird || !stops.length) return;
      var n = stops.length;
      var cycle = LEG * (n + 1);
      var t = now % cycle;
      var leg = Math.floor(t / LEG), into = t - leg * LEG;
      var from, to, here = -1, x, lift = 0;
      if (leg < n) {
        from = leg === 0 ? -24 : stops[leg - 1];
        to = stops[leg];
        if (into < TRAVEL) { var k = ease(into / TRAVEL); x = from + (to - from) * k; lift = Math.sin(k * Math.PI) * 10; }
        else { x = to; here = leg; }
      } else {
        from = stops[n - 1]; to = width + 24;
        var k2 = ease(Math.min(1, into / TRAVEL)); x = from + (to - from) * k2; lift = Math.sin(k2 * Math.PI) * 10;
      }
      var flap = here >= 0 ? 1 : 0.85 + 0.25 * Math.sin(now / 90);
      bird.setAttribute("transform", "translate(" + x.toFixed(1) + " " + (y - 12 - lift).toFixed(1) + ") scale(1 " + flap.toFixed(2) + ")");
      for (var i = 0; i < n; i += 1) {
        var on = i === here;
        ticks[i].classList.toggle("is-here", on);
        steps[i].classList.toggle("is-here", on);
      }
    }
    var running = false, raf = 0, origin = 0, seen = false, kept = 0;
    function frame(now) { if (!running) return; kept = now - origin; place(kept); raf = requestAnimationFrame(frame); }
    function go() { if (running || motion.paused || !seen) return; running = true; origin = performance.now() - kept; raf = requestAnimationFrame(frame); }
    function halt() { running = false; cancelAnimationFrame(raf); }
    layout();
    window.addEventListener("resize", layout);
    if (reduced) { place(TRAVEL + 10); return; }
    motion.control(svg.closest(".journey-figure") || svg);
    motion.add({ pause: halt, play: go });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) { seen = entry.isIntersecting; if (seen) go(); else halt(); });
      }).observe(svg);
    }
  })();

  /* ----------------------------------------------------------------- pieces */
  /* The three parts, told by the scroll: the section is several screens tall and its stage
     holds still, so how far the reader has scrolled through it picks the part that is lit and
     the screen that shows. A narrow or short window gets a plain list instead (CSS), and this
     leaves it alone. */
  (function pieces() {
    var section = document.getElementById("pieces");
    if (!section) return;
    var steps = section.querySelectorAll(".piece");
    var frames = section.querySelectorAll(".screen-frame");
    var pips = section.querySelectorAll(".pip");
    var n = steps.length, active = -1, queued = 0;
    var pinned = window.matchMedia("(min-width: 1025px) and (min-height: 561px)");
    function through() {
      var box = section.getBoundingClientRect();
      var room = section.offsetHeight - window.innerHeight;
      return room > 0 ? Math.max(0, Math.min(1, -box.top / room)) : 0;
    }
    function show(i) {
      if (i === active) return;
      active = i;
      for (var k = 0; k < n; k += 1) {
        steps[k].classList.toggle("is-on", k === i);
        frames[k].classList.toggle("is-on", k === i);
        frames[k].setAttribute("aria-hidden", k === i ? "false" : "true");
      }
    }
    function update() {
      queued = 0;
      if (!pinned.matches) return;
      var p = through();
      show(Math.min(n - 1, Math.floor(p * n)));
      for (var k = 0; k < pips.length; k += 1) {
        var fill = Math.max(0, Math.min(1, p * n - k));
        pips[k].firstChild.style.transform = "scaleX(" + fill.toFixed(3) + ")";
        pips[k].setAttribute("aria-current", k === active ? "step" : "false");
      }
    }
    function later() { if (!queued) queued = requestAnimationFrame(update); }
    Array.prototype.forEach.call(pips, function (pip, k) {
      pip.addEventListener("click", function () {
        var room = section.offsetHeight - window.innerHeight;
        var top = section.getBoundingClientRect().top + window.pageYOffset + ((k + 0.5) / n) * room;
        window.scrollTo({ top: top, behavior: reduced ? "auto" : "smooth" });
      });
    });
    window.addEventListener("scroll", later, { passive: true });
    window.addEventListener("resize", later);
    update();
  })();

  /* -------------------------------------------------------------------- sky */
  /* A whole day in forty-eight seconds: the sun crosses and sets, the sky goes rose and then
     violet, the stars and the moon come out and the farm's window stays lit while the lanes
     work, then the sun comes back up with the report. The flock flies through all of it, dark
     against the day and pale under the moon. */
  function mix(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]; }
  function rgb(c, alpha) { return "rgba(" + Math.round(c[0]) + "," + Math.round(c[1]) + "," + Math.round(c[2]) + "," + (alpha == null ? 1 : alpha) + ")"; }
  function hex(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
  function smooth(e0, e1, x) { var t = Math.max(0, Math.min(1, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); }

  var SKY = {
    day:   { top: hex("#C9CEF0"), low: hex("#F7EEDC"), far: hex("#CDBFD6"), near: hex("#A897B8"), bird: hex("#2B1F2E") },
    dusk:  { top: hex("#5B4A8A"), low: hex("#EDB49C"), far: hex("#7A5F86"), near: hex("#4A3854"), bird: hex("#2B1F2E") },
    dawn:  { top: hex("#8C86C4"), low: hex("#F3D2B4"), far: hex("#9C8AAE"), near: hex("#66557A"), bird: hex("#2B1F2E") },
    night: { top: hex("#15131B"), low: hex("#2E2840"), far: hex("#231F2C"), near: hex("#15121A"), bird: hex("#D9D0E6") }
  };
  var PERIOD = 48000;
  var CAPTIONS = [
    [0.00, "Morning, and the report is waiting over breakfast"],
    [0.12, "Day, you pick the work and the lanes take it"],
    [0.40, "Evening, you say night mode and close the lid"],
    [0.58, "Night, the farm keeps working while you sleep"],
    [0.94, "Morning, and the report is waiting over breakfast"]
  ];

  function startSky() {
    var canvas = document.getElementById("skyCanvas");
    var birdsCanvas = document.getElementById("skyFlock");
    var caption = document.getElementById("skyCaption");
    if (!canvas) return;
    var context = canvas.getContext("2d");
    var ratio = Math.min(2, window.devicePixelRatio || 1);
    var width = 0, height = 0, stars = [], said = "";
    var random = (function (seed) { return function () { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }; })(20260923);
    for (var i = 0; i < 110; i += 1) stars.push({ x: random(), y: random() * 0.62, r: 0.5 + random() * 1.1, p: random() * 6.28 });
    function resize() {
      var box = canvas.getBoundingClientRect();
      width = Math.max(1, box.width); height = Math.max(1, box.height);
      canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    }
    function hill(base, amp, phase, color) {
      context.fillStyle = color;
      context.beginPath();
      context.moveTo(0, height);
      for (var x = 0; x <= width + 8; x += 8) {
        var u = x / width;
        context.lineTo(x, base - amp * (0.6 * Math.sin(u * 5.2 + phase) + 0.4 * Math.sin(u * 11.7 + phase * 2.3)));
      }
      context.lineTo(width, height);
      context.closePath();
      context.fill();
      return function (u) { return base - amp * (0.6 * Math.sin(u * 5.2 + phase) + 0.4 * Math.sin(u * 11.7 + phase * 2.3)); };
    }
    /* The farm: a small house and its silo on the near hill, the window lit whenever the sun
       is down, because that is when the lanes are working. */
    function barn(x, ground, color, glow) {
      context.fillStyle = color;
      context.strokeStyle = color;
      context.lineJoin = "round";
      context.lineWidth = 3;
      context.beginPath();
      context.moveTo(x - 17, ground + 6);
      context.lineTo(x - 17, ground - 16);
      context.lineTo(x - 22, ground - 14);
      context.lineTo(x, ground - 33);
      context.lineTo(x + 22, ground - 14);
      context.lineTo(x + 17, ground - 16);
      context.lineTo(x + 17, ground + 6);
      context.closePath();
      context.fill();
      context.stroke();
      context.beginPath();
      context.moveTo(x + 21, ground + 6);
      context.lineTo(x + 21, ground - 30);
      context.arc(x + 29, ground - 30, 8, Math.PI, 0);
      context.lineTo(x + 37, ground + 6);
      context.closePath();
      context.fill();
      if (glow > 0.01) {
        var halo = context.createRadialGradient(x, ground - 8, 0, x, ground - 8, 40);
        halo.addColorStop(0, "rgba(240,194,122," + (0.32 * glow) + ")");
        halo.addColorStop(1, "rgba(240,194,122,0)");
        context.fillStyle = halo;
        context.fillRect(x - 44, ground - 52, 88, 88);
        context.fillStyle = "rgba(240,194,122," + glow + ")";
        roundRect(x - 6, ground - 13, 12, 10, 2.5);
      }
    }
    function roundRect(x, y, w, h, r) {
      context.beginPath();
      context.moveTo(x + r, y);
      context.arcTo(x + w, y, x + w, y + h, r); context.arcTo(x + w, y + h, x, y + h, r);
      context.arcTo(x, y + h, x, y, r); context.arcTo(x, y, x + w, y, r);
      context.closePath(); context.fill();
    }
    var shown = 0;
    function draw(t) {
      /* t in [0, 1): 0 is sunrise on the left, 0.5 is sunset on the right. */
      shown = t;
      var angle = t * Math.PI * 2;
      var alt = Math.sin(angle);
      var day = smooth(0.04, 0.42, alt), night = smooth(0.04, 0.36, -alt);
      var twilight = Math.max(0, 1 - day - night);
      var evening = Math.cos(angle) < 0 ? 1 : 0;
      var edge = evening ? SKY.dusk : SKY.dawn;
      function pick(key) {
        var c = mix(SKY.day[key], SKY.night[key], night / Math.max(0.0001, day + night));
        if (day + night < 0.0001) c = edge[key];
        return mix(c, edge[key], twilight);
      }
      var top = pick("top"), low = pick("low");
      var horizon = height * 0.74;
      var sky = context.createLinearGradient(0, 0, 0, horizon);
      sky.addColorStop(0, rgb(top)); sky.addColorStop(1, rgb(low));
      context.fillStyle = sky;
      context.fillRect(0, 0, width, height);

      var cx = width / 2, rx = width * 0.46, ry = height * 0.62;
      var sun = { x: cx - rx * Math.cos(angle), y: horizon - ry * alt };
      var moon = { x: cx + rx * Math.cos(angle), y: horizon + ry * alt };
      if (night > 0.01) {
        for (var s = 0; s < stars.length; s += 1) {
          var st = stars[s];
          var twinkle = 0.6 + 0.4 * Math.sin(t * 90 + st.p);
          context.fillStyle = "rgba(237,230,217," + (night * twinkle * 0.9).toFixed(3) + ")";
          context.beginPath(); context.arc(st.x * width, st.y * height, st.r, 0, 6.2832); context.fill();
        }
      }
      if (sun.y < horizon + 30) {
        var glow = context.createRadialGradient(sun.x, sun.y, 0, sun.x, sun.y, 120);
        glow.addColorStop(0, "rgba(240,194,122," + (0.45 + 0.3 * twilight) + ")");
        glow.addColorStop(1, "rgba(240,194,122,0)");
        context.fillStyle = glow;
        context.fillRect(sun.x - 120, sun.y - 120, 240, 240);
        context.fillStyle = rgb(mix(hex("#F0C27A"), hex("#E59A6B"), twilight));
        context.beginPath(); context.arc(sun.x, sun.y, 20, 0, 6.2832); context.fill();
      }
      if (moon.y < horizon + 20) {
        /* A crescent drawn as its own outline: the far side of the moon's disc, then back along
           the edge of the shadow disc laid over it. */
        var R = 15, ex = moon.x + 7, ey = moon.y - 5;
        var away = Math.atan2(moon.y - ey, moon.x - ex);
        var half = Math.acos(Math.hypot(ex - moon.x, ey - moon.y) / (2 * R));
        context.fillStyle = "rgba(237,230,217," + (0.35 + 0.65 * night).toFixed(3) + ")";
        context.beginPath();
        context.arc(moon.x, moon.y, R, away + Math.PI + half, away + 3 * Math.PI - half, false);
        context.arc(ex, ey, R, away + half, away - half, true);
        context.closePath();
        context.fill();
      }
      hill(horizon + 6, 12, 0.8, rgb(pick("far")));
      var near = hill(horizon + 30, 16, 2.4, rgb(pick("near")));
      var bx = width * 0.8;
      barn(bx, near(0.8), rgb(pick("near")), Math.max(night, twilight * 0.7));
      if (birdsCanvas) birdsCanvas.style.setProperty("--ink", rgb(pick("bird")));
      if (caption) {
        var text = CAPTIONS[0][1];
        for (var c = 0; c < CAPTIONS.length; c += 1) if (t >= CAPTIONS[c][0]) text = CAPTIONS[c][1];
        if (text !== said) { said = text; caption.textContent = text; }
      }
    }
    resize();
    /* A resize clears the canvas, so the sky is drawn again at once, running or not. */
    window.addEventListener("resize", function () { resize(); draw(shown); });
    /* The day starts in the evening: the first thing a reader sees is the sun going down. */
    var START = 0.46;
    if (birdsCanvas && window.Murmur) {
      var flock = window.Murmur.flock(birdsCanvas, { count: narrow ? 160 : 320, speed: 0.8, seed: 29, spacing: 1.2, birdScale: 1, roostX: 0.42, roostY: 0.36, roostReach: 0.22 });
      if (reduced) flock.stop(); else motion.add(flock);
    }
    if (reduced) { draw(0.47); return; }
    var running = false, raf = 0, origin = 0, offset = START;
    function frame(now) {
      if (!running) return;
      draw(((now - origin) / PERIOD + offset) % 1);
      raf = requestAnimationFrame(frame);
    }
    draw(START);
    var seen = false;
    function go() { if (running || motion.paused || !seen) return; running = true; origin = performance.now(); raf = requestAnimationFrame(frame); }
    function halt() {
      if (!running) return;
      running = false; cancelAnimationFrame(raf);
      offset = ((performance.now() - origin) / PERIOD + offset) % 1;
    }
    motion.control(canvas.closest(".sky") || canvas);
    motion.add({ pause: halt, play: go });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) { seen = entry.isIntersecting; if (seen) go(); else halt(); });
      }).observe(canvas);
    }
  }

  /* ------------------------------------------------------------------- flocks */
  function whenIdle(work) {
    if ("requestIdleCallback" in window) window.requestIdleCallback(work, { timeout: 900 });
    else setTimeout(work, 200);
  }

  /* The places in the hero the words take, as fractions of the canvas, so the flock flies around
     them: the headline measured by its letters (it runs on one line past its column), and the
     column of words under it. */
  function textZones(canvas) {
    var words = document.querySelector(".hero__text");
    if (!words) return null;
    var box = canvas.getBoundingClientRect();
    function zone(r) {
      return { x0: (r.left - box.left) / box.width, y0: (r.top - box.top) / box.height,
               x1: (r.right - box.left) / box.width, y1: (r.bottom - box.top) / box.height };
    }
    var zones = [zone(words.getBoundingClientRect())];
    var headline = words.querySelector("h1");
    if (headline && document.createRange) {
      var range = document.createRange();
      range.selectNodeContents(headline);
      zones.push(zone(range.getBoundingClientRect()));
    }
    return zones;
  }

  whenIdle(function () {
    if (!window.Murmur) return;
    var hero = document.getElementById("heroFlock");
    var readout = document.getElementById("readout");
    var restingText = readout ? readout.textContent : "";
    if (hero) {
      /* There is no pause button on the first screen, but motion that runs past five seconds
         needs a way to stop it (WCAG 2.2.2), so the flock itself is the control. A click, a tap,
         Enter or Space pauses it and plays it again. It also stops by itself off screen, and a
         reader who asks the system for less motion gets one still frame. */
      var flock = window.Murmur.flock(hero, {
        count: narrow ? 260 : 600,
        speed: 0.75,
        spacing: narrow ? 1.25 : 1.5,
        birdScale: narrow ? 1.2 : 1.55,
        seed: 11,
        roostX: narrow ? 0.5 : 0.73,
        roostY: narrow ? 0.5 : 0.6,
        roostReach: narrow ? 0.2 : 0.1,
        hold: 2,
        avoid: narrow ? null : textZones(hero),
        inspect: !narrow,
        onInspect: function (on) {
          if (!readout) return;
          readout.textContent = on ? "The lit lines lead to the seven birds this one watches" : restingText;
        }
      });
      if (flock && !reduced) {
        motion.control(hero);
        motion.add(flock);
      } else {
        hero.removeAttribute("role"); hero.removeAttribute("tabindex");
        hero.removeAttribute("aria-pressed"); hero.setAttribute("aria-hidden", "true");
      }
    }
    startSky();
  });
})();
