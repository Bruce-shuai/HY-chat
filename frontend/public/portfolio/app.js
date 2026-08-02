(() => {
  "use strict";

  const root = document.querySelector(".world");
  const canvas = document.getElementById("world-canvas");
  const ctx = canvas.getContext("2d", { alpha: false, desynchronized: true });
  const textCanvas = document.getElementById("world-text-canvas");
  const textCtx = textCanvas.getContext("2d", { alpha: true, desynchronized: true });
  const track = document.getElementById("scroll-track");
  const progressBar = document.getElementById("progress-bar");
  const hint = document.querySelector(".scroll-hint");
  const cards = [...document.querySelectorAll("[data-story]")];
  const jumpButtons = [...document.querySelectorAll("[data-scene-jump]")];
  const navButtons = [...document.querySelectorAll(".chapter-nav [data-scene-jump]")];
  const routeButtons = [...document.querySelectorAll(".route [data-scene-jump]")];
  const poseSprites = [...document.querySelectorAll(".character-sprite")];
  const poseMap = new Map(poseSprites.map(sprite => [sprite.dataset.pose, sprite]));
  const poseFrames = new Map(poseSprites.map(sprite => [
    sprite.dataset.pose,
    [...sprite.querySelectorAll("[data-frame]")]
  ]));
  const idlePoseFrames = new Map(poseSprites.map(sprite => [
    sprite.dataset.pose,
    [...sprite.querySelectorAll("[data-idle-frame]")]
  ]));
  const frameLoadPromises = new WeakMap();
  const poseReadyPromises = new Map();

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const coarsePointer = window.matchMedia("(hover: none) and (pointer: coarse)").matches;

  const SCENES = [
    { id: "start", anchor: 0, accent: "#5ee6c4", sky: "#152c46", horizon: "#244968", ground: "#172739" },
    { id: "work", anchor: 0.23, accent: "#62b7ff", sky: "#17294b", horizon: "#2f4c72", ground: "#162538" },
    { id: "ai", anchor: 0.48, accent: "#b47cff", sky: "#111833", horizon: "#262552", ground: "#121a30" },
    { id: "life", anchor: 0.72, accent: "#ffb84d", sky: "#28445b", horizon: "#cf7555", ground: "#213c3a" },
    { id: "next", anchor: 1, accent: "#ff6fae", sky: "#0b1530", horizon: "#332a55", ground: "#121a2c" }
  ];

  const WORLD_TRAVEL = 5400;
  const CHARACTER_FRAME_DISTANCE = 18;
  const IDLE_CHARACTER_FRAME_MS = 220;
  const INTRO_GREETING_DURATION_MS = IDLE_CHARACTER_FRAME_MS * 8;
  const POSES = [
    { id: "intro", end: 0.13 },
    { id: "work", end: 0.39 },
    { id: "ai", end: 0.65 },
    { id: "cycling", end: 0.71 },
    { id: "boxing", end: 0.77 },
    { id: "travel", end: 0.845 },
    { id: "finale", end: 1 }
  ];

  let logicalW = 480;
  let logicalH = 270;
  let groundY = 216;
  let targetProgress = 0;
  let renderProgress = 0;
  let activeScene = -1;
  let lastTime = 0;
  let lastDraw = 0;
  let lastScrollAt = performance.now();
  let lastCharacterProgress = 0;
  let characterTravelDistance = 0;
  let characterWalkFrame = 0;
  let renderedCharacterPose = "intro";
  let renderedCharacterFrame = 0;
  let renderedCharacterMode = "walk";
  let renderedCharacterWalking = false;
  let lastTextProgress = Number.NaN;
  let drawTextThisFrame = true;
  let lastWidth = window.innerWidth;
  let needsDraw = true;
  let pageVisible = !document.hidden;
  let rafId = 0;
  let idleCharacterTimer = 0;
  let introGreetingStartedAt = 0;
  let hasUserScrolled = false;
  let lastObservedScrollY = window.scrollY || window.pageYOffset || 0;
  let activePose = "intro";
  let desiredPose = "intro";
  let characterFrame = 0;
  let hasReadied = false;

  const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
  const lerp = (a, b, t) => a + (b - a) * t;
  const smoothstep = value => {
    const x = clamp(value);
    return x * x * (3 - 2 * x);
  };

  function colorToRgb(color) {
    if (color.startsWith("#")) {
      const value = Number.parseInt(color.slice(1), 16);
      return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
    }
    const channels = color.match(/[\d.]+/g)?.slice(0, 3).map(Number);
    return channels?.length === 3 ? channels : [0, 0, 0];
  }

  function mixColor(a, b, t) {
    const ca = colorToRgb(a);
    const cb = colorToRgb(b);
    return `rgb(${Math.round(lerp(ca[0], cb[0], t))} ${Math.round(lerp(ca[1], cb[1], t))} ${Math.round(lerp(ca[2], cb[2], t))})`;
  }

  function sceneBlend(progress) {
    for (let i = 0; i < SCENES.length - 1; i += 1) {
      const current = SCENES[i];
      const next = SCENES[i + 1];
      if (progress <= next.anchor) {
        const local = smoothstep((progress - current.anchor) / (next.anchor - current.anchor));
        return { current, next, local, index: local > 0.55 ? i + 1 : i };
      }
    }
    const last = SCENES[SCENES.length - 1];
    return { current: last, next: last, local: 0, index: SCENES.length - 1 };
  }

  function resize(force = false) {
    const width = window.innerWidth;
    if (!force && coarsePointer && width === lastWidth) return;
    lastWidth = width;

    const pixelSize = width <= 720 ? 3 : 3;
    logicalW = Math.max(120, Math.round(width / pixelSize));
    logicalH = Math.max(180, Math.round(window.innerHeight / pixelSize));
    canvas.width = logicalW;
    canvas.height = logicalH;
    ctx.imageSmoothingEnabled = false;
    const textDpr = Math.min(coarsePointer ? 1.5 : 2, window.devicePixelRatio || 1);
    textCanvas.width = Math.round(width * textDpr);
    textCanvas.height = Math.round(window.innerHeight * textDpr);
    textCtx.setTransform(textDpr, 0, 0, textDpr, 0, 0);
    textCtx.imageSmoothingEnabled = true;
    lastTextProgress = Number.NaN;
    groundY = Math.round(logicalH * (width <= 720 ? 0.48 : 0.8));
    updateScroll();
    needsDraw = true;
  }

  function maxScroll() {
    return Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
  }

  function updateScroll() {
    lastScrollAt = performance.now();
    targetProgress = clamp((window.scrollY || window.pageYOffset) / maxScroll());
    progressBar.style.transform = `scaleX(${targetProgress.toFixed(4)})`;
    hint.style.opacity = String(clamp(1 - targetProgress / 0.055));
    needsDraw = true;
    ensureLoop();
  }

  function jumpTo(index) {
    const scene = SCENES[clamp(index, 0, SCENES.length - 1)];
    window.scrollTo({
      top: scene.anchor * maxScroll(),
      behavior: reduceMotion ? "auto" : "smooth"
    });
  }

  function cardOpacity(index, progress) {
    if (index === 0) return 1 - smoothstep((progress - 0.095) / 0.075);
    if (index === SCENES.length - 1) return smoothstep((progress - 0.84) / 0.1);

    const center = SCENES[index].anchor;
    const prev = SCENES[index - 1].anchor;
    const next = SCENES[index + 1].anchor;
    const enter = smoothstep((progress - lerp(prev, center, 0.58)) / (center - prev) * 2.38);
    const leave = 1 - smoothstep((progress - lerp(center, next, 0.38)) / (next - center) * 2.45);
    return clamp(enter * leave);
  }

  function loadFrame(frame) {
    if (!frame) return Promise.resolve(null);
    if (frameLoadPromises.has(frame)) return frameLoadPromises.get(frame);
    if (!frame.getAttribute("src") && frame.dataset.src) frame.src = frame.dataset.src;
    const decode = () => {
      if (typeof frame.decode !== "function") return Promise.resolve(frame);
      return frame.decode().catch(() => undefined).then(() => frame);
    };
    const pending = frame.complete && frame.naturalWidth
      ? decode()
      : new Promise(resolve => {
        const finish = () => decode().then(resolve);
        frame.addEventListener("load", finish, { once: true });
        frame.addEventListener("error", () => resolve(frame), { once: true });
      });
    frameLoadPromises.set(frame, pending);
    return pending;
  }

  function ensurePose(id) {
    if (poseReadyPromises.has(id)) return poseReadyPromises.get(id);
    const sprite = poseMap.get(id);
    if (!sprite) return Promise.resolve(null);
    const frames = poseFrames.get(id) || [];
    const idleFrames = idlePoseFrames.get(id) || [];
    const primary = frames[0];
    const motionFrames = frames.slice(1);

    if (!reduceMotion && motionFrames.length) {
      Promise.all(motionFrames.map(loadFrame)).then(loadedFrames => {
        if (loadedFrames.every(frame => frame?.naturalWidth)) {
          sprite.classList.add("has-motion-frame");
          if (sprite.dataset.pose === activePose) updateCharacter(renderProgress);
        }
      });
    }

    if (idleFrames.length) {
      const idleFramesToLoad = reduceMotion ? idleFrames.slice(0, 1) : idleFrames;
      Promise.all(idleFramesToLoad.map(loadFrame)).then(loadedFrames => {
        if (loadedFrames.every(frame => frame?.naturalWidth)) {
          sprite.classList.add("has-idle-frame");
          if (
            id === "intro"
            && !reduceMotion
            && !hasUserScrolled
            && !introGreetingStartedAt
            && targetProgress < 0.001
          ) {
            introGreetingStartedAt = performance.now();
          }
          if (sprite.dataset.pose === activePose) {
            updateCharacter(renderProgress);
            needsDraw = true;
            ensureLoop();
          }
        }
      });
    }

    const ready = loadFrame(primary).then(() => sprite);
    poseReadyPromises.set(id, ready);
    return ready;
  }

  function requestPose(id) {
    if (id === activePose) {
      desiredPose = id;
      return;
    }
    if (id === desiredPose) return;
    desiredPose = id;
    ensurePose(id).then(sprite => {
      if (!sprite || desiredPose !== id) return;
      poseMap.get(activePose)?.classList.remove("is-walking");
      poseSprites.forEach(node => node.classList.toggle("is-active", node === sprite));
      activePose = id;
      root.dataset.pose = id;

      const index = POSES.findIndex(pose => pose.id === id);
      [POSES[index - 1], POSES[index + 1]].filter(Boolean).forEach(pose => ensurePose(pose.id));
    });
  }

  function updateCharacter(progress, time = performance.now()) {
    const pose = POSES.find(item => progress <= item.end) || POSES[POSES.length - 1];
    requestPose(pose.id);
    const activeSprite = poseMap.get(activePose);
    const walkingFrames = poseFrames.get(activePose) || [];
    const idleFrames = idlePoseFrames.get(activePose) || [];
    const isWalking = !reduceMotion && (
      time - lastScrollAt < 220 || Math.abs(targetProgress - renderProgress) > 0.00002
    );
    const useIdleFrames = activePose === "intro"
      && !isWalking
      && idleFrames.length > 0
      && activeSprite?.classList.contains("has-idle-frame");
    const isGreetingAnimating = useIdleFrames && isIntroGreetingActive(time);
    const activeFrames = useIdleFrames ? idleFrames : walkingFrames;
    const activeFrameCount = activeFrames.length || 1;
    const progressDelta = Math.abs(progress - lastCharacterProgress);
    if (!reduceMotion && Number.isFinite(progressDelta) && progressDelta < 0.12) {
      characterTravelDistance += progressDelta * WORLD_TRAVEL;
    }
    lastCharacterProgress = progress;

    if (isWalking) {
      characterWalkFrame = Math.floor(characterTravelDistance / CHARACTER_FRAME_DISTANCE);
    }
    const requestedFrame = reduceMotion
      ? 0
      : isWalking
        ? characterWalkFrame % activeFrameCount
        : isGreetingAnimating
          ? Math.floor((time - introGreetingStartedAt) / IDLE_CHARACTER_FRAME_MS) % activeFrameCount
          : 0;

    const readyFrameIndexes = activeFrames.reduce((indexes, frame, index) => {
      if (frame?.complete && frame.naturalWidth) indexes.push(index);
      return indexes;
    }, []);
    const requestedFrameIsReady = activeFrames[requestedFrame]?.complete
      && activeFrames[requestedFrame]?.naturalWidth;
    const selectedFrame = requestedFrameIsReady
      ? requestedFrame
      : readyFrameIndexes[requestedFrame % readyFrameIndexes.length] ?? 0;
    const poseChanged = renderedCharacterPose !== activePose;
    const frameMode = useIdleFrames ? "idle" : "walk";
    const frameModeChanged = renderedCharacterMode !== frameMode;

    const isCharacterAnimating = isWalking || isGreetingAnimating;
    if (activeSprite && (poseChanged || renderedCharacterWalking !== isCharacterAnimating)) {
      activeSprite.classList.toggle("is-walking", isCharacterAnimating);
      renderedCharacterWalking = isCharacterAnimating;
    }

    if (activeSprite && (poseChanged || frameModeChanged || renderedCharacterFrame !== selectedFrame)) {
      if (poseChanged || frameModeChanged) {
        [...walkingFrames, ...idleFrames].forEach(frame => {
          frame.classList.toggle("is-current-frame", frame === activeFrames[selectedFrame]);
        });
      } else {
        activeFrames[renderedCharacterFrame]?.classList.remove("is-current-frame");
        activeFrames[selectedFrame]?.classList.add("is-current-frame");
      }
      activeSprite.dataset.activeFrame = String(selectedFrame);
      activeSprite.dataset.frameMode = frameMode;
      renderedCharacterPose = activePose;
      renderedCharacterFrame = selectedFrame;
      renderedCharacterMode = frameMode;
    }

    characterFrame = selectedFrame;
    if (root.dataset.characterFrame !== String(characterFrame)) {
      root.dataset.characterFrame = String(characterFrame);
    }
  }

  function updateInterface(progress, time = performance.now()) {
    updateCharacter(progress, time);
    let strongest = 0;
    let strongestOpacity = -1;
    const mobile = window.innerWidth <= 720;

    cards.forEach((card, index) => {
      const opacity = cardOpacity(index, progress);
      if (opacity > strongestOpacity) {
        strongestOpacity = opacity;
        strongest = index;
      }
      const nextOpacity = opacity.toFixed(3);
      if (card.style.opacity !== nextOpacity) card.style.opacity = nextOpacity;
      const travel = reduceMotion ? 0 : Math.round((0.5 - opacity) * 30);
      const nextTransform = mobile
        ? `translate3d(0, ${travel}px, 0)`
        : `translate3d(0, calc(-50% + ${travel}px), 0)`;
      if (card.style.transform !== nextTransform) card.style.transform = nextTransform;
    });

    if (strongest !== activeScene) {
      activeScene = strongest;
      const accent = SCENES[strongest].accent;
      root.style.setProperty("--accent", accent);
      cards.forEach((card, index) => {
        const selected = index === strongest;
        card.classList.toggle("is-visible", selected);
        card.setAttribute("aria-hidden", selected ? "false" : "true");
      });
      navButtons.forEach(button => button.classList.toggle("is-active", Number(button.dataset.sceneJump) === strongest));
      routeButtons.forEach(button => {
        const selected = Number(button.dataset.sceneJump) === strongest;
        button.classList.toggle("is-active", selected);
        button.setAttribute("aria-current", selected ? "step" : "false");
      });
    }
  }

  function hash(value) {
    const x = Math.sin(value * 12.9898) * 43758.5453;
    return x - Math.floor(x);
  }

  function screenX(worldX, cameraX, parallax = 1) {
    return Math.round((worldX - cameraX) * parallax);
  }

  function isVisible(x, width = 100) {
    return x > -width && x < logicalW + width;
  }

  function rect(x, y, width, height, color) {
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x), Math.round(y), Math.round(width), Math.round(height));
  }

  function pixelText(text, x, y, color = "#eef7ff", size = 8, align = "left") {
    if (!drawTextThisFrame) return;
    const scaleX = window.innerWidth / logicalW;
    const scaleY = window.innerHeight / logicalH;
    const fontSize = Math.max(11, Math.round(size * Math.min(scaleX, scaleY) * 0.92));
    const usesChinese = /[\u3400-\u9fff]/.test(text);
    textCtx.save();
    textCtx.fillStyle = color;
    textCtx.font = usesChinese
      ? `800 ${fontSize}px "PingFang SC", "Microsoft YaHei", sans-serif`
      : `800 ${fontSize}px "SFMono-Regular", "Cascadia Code", ui-monospace, monospace`;
    textCtx.textAlign = align;
    textCtx.textBaseline = "top";
    textCtx.fontKerning = "none";
    textCtx.shadowColor = "rgba(2, 7, 14, 0.72)";
    textCtx.shadowOffsetX = 1;
    textCtx.shadowOffsetY = 1;
    textCtx.fillText(text, Math.round(x * scaleX), Math.round(y * scaleY));
    textCtx.restore();
  }

  function drawSky(cameraX, progress, time) {
    const blend = sceneBlend(progress);
    const sky = mixColor(blend.current.sky, blend.next.sky, blend.local);
    const horizon = mixColor(blend.current.horizon, blend.next.horizon, blend.local);
    const ground = mixColor(blend.current.ground, blend.next.ground, blend.local);

    rect(0, 0, logicalW, groundY, sky);
    const gradientTop = Math.round(groundY * 0.38);
    const gradientHeight = Math.max(1, groundY - gradientTop);
    const bands = 12;
    for (let band = 0; band < bands; band += 1) {
      const y = gradientTop + Math.floor((gradientHeight * band) / bands);
      const nextY = gradientTop + Math.ceil((gradientHeight * (band + 1)) / bands);
      const amount = Math.pow((band + 1) / bands, 1.28) * 0.86;
      rect(0, y, logicalW, nextY - y + 1, mixColor(sky, horizon, amount));
    }

    const haze = mixColor(horizon, "#d6d9c6", 0.16);
    rect(0, groundY - 3, logicalW, 1, haze);
    for (let i = 0; i < 92; i += 1) {
      const x = ((Math.floor(hash(i + 911) * logicalW * 2) - Math.floor(cameraX * 0.08)) % logicalW + logicalW) % logicalW;
      const y = gradientTop + Math.floor(hash(i + 331) * Math.max(1, gradientHeight - 5));
      const amount = hash(i + 1201);
      if (amount < 0.44) continue;
      rect(x, y, amount > 0.82 ? 2 : 1, 1, amount > 0.72 ? mixColor(sky, horizon, 0.72) : mixColor(sky, horizon, 0.38));
    }
    rect(0, groundY, logicalW, logicalH - groundY, ground);

    const starAlpha = smoothstep((progress - 0.42) / 0.38);
    if (starAlpha > 0.02) {
      ctx.globalAlpha = starAlpha * 0.85;
      for (let i = 0; i < 34; i += 1) {
        const sx = Math.floor(hash(i + 91) * logicalW);
        const sy = Math.floor(hash(i + 17) * Math.max(30, groundY - 35));
        const twinkle = hash(i + Math.floor(time * 0.0015)) > 0.72;
        rect(sx, sy, twinkle ? 2 : 1, 1, i % 5 === 0 ? "#ffd9a0" : "#d7e8ff");
      }
      ctx.globalAlpha = 1;
    }

    const sunX = screenX(4050, cameraX, 0.12);
    if (isVisible(sunX, 80)) {
      const sunY = Math.round(logicalH * 0.17);
      ctx.globalAlpha = 0.12;
      ctx.fillStyle = "#ffcf72";
      ctx.beginPath();
      ctx.arc(sunX, sunY, 18, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 0.24;
      ctx.beginPath();
      ctx.arc(sunX, sunY, 13, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      rect(sunX - 8, sunY - 10, 16, 20, "#ffd783");
      rect(sunX - 11, sunY - 7, 22, 14, "#ffd783");
      rect(sunX - 5, sunY - 7, 10, 14, "#ffe8ad");
    }

    drawClouds(cameraX, time);
  }

  function drawClouds(cameraX, time) {
    const drift = reduceMotion ? 0 : time * 0.0011;
    for (let i = 0; i < 22; i += 1) {
      const layer = i % 2;
      const wx = i * 286 - 260 + (drift % 286);
      const x = screenX(wx, cameraX, layer ? 0.16 : 0.24);
      if (!isVisible(x, 62)) continue;
      const y = 18 + Math.floor(hash(i + 4) * Math.max(20, groundY * (layer ? 0.34 : 0.48)));
      const width = 25 + Math.floor(hash(i + 31) * 24);
      const color = layer ? "rgba(133,166,189,.18)" : "rgba(198,219,231,.30)";
      const shade = layer ? "rgba(73,104,132,.16)" : "rgba(91,124,151,.24)";
      rect(x + 3, y + 5, width, 4, shade);
      rect(x, y + 2, Math.round(width * 0.38), 5, color);
      rect(x + Math.round(width * 0.22), y, Math.round(width * 0.36), 7, color);
      rect(x + Math.round(width * 0.52), y + 2, Math.round(width * 0.4), 5, color);
      rect(x + 5, y + 7, Math.max(5, width - 7), 1, "rgba(222,235,241,.14)");
    }
  }

  function drawCity(cameraX, time) {
    const layers = [
      { parallax: 0.31, step: 48, minH: 20, rangeH: 48, base: "#17283d", side: "#122236", window: "#324b61", alpha: 0.68 },
      { parallax: 0.48, step: 61, minH: 32, rangeH: 72, base: "#1b3047", side: "#13263a", window: "#3b5d78", alpha: 0.9 },
      { parallax: 0.68, step: 74, minH: 38, rangeH: 92, base: "#203950", side: "#162c42", window: "#4b718b", alpha: 1 }
    ];

    layers.forEach((layer, layerIndex) => {
      ctx.globalAlpha = layer.alpha;
      for (let i = -6; i < 52; i += 1) {
        const wx = i * layer.step + layerIndex * 23;
        if (wx > 2820) break;
        const x = screenX(wx, cameraX, layer.parallax);
        const width = 18 + Math.floor(hash(i + 20 + layerIndex * 73) * (layer.step * 0.48));
        if (!isVisible(x, width + 8)) continue;
        const height = layer.minH + Math.floor(hash(i + 60 + layerIndex * 41) * layer.rangeH);
        const y = groundY - height;
        rect(x, y, width, height, layer.base);
        rect(x + Math.max(4, Math.round(width * 0.68)), y + 2, Math.max(3, Math.round(width * 0.32)), height - 2, layer.side);
        rect(x + 2, y - 3, Math.max(6, width - 4), 3, mixColor(layer.base, "#71859a", 0.2));
        if (hash(i + layerIndex * 19) > 0.68) {
          rect(x + Math.round(width * 0.58), y - 10, 1, 7, "#3e566d");
          rect(x + Math.round(width * 0.58) - 1, y - 10, 3, 1, "#71869b");
        }
        for (let wy = y + 7; wy < groundY - 5; wy += 8) {
          for (let wx2 = x + 4; wx2 < x + width - 3; wx2 += 7) {
            const on = hash(i * 17 + wx2 * 0.3 + wy + Math.floor(time / 1800)) > 0.66;
            rect(wx2, wy, 2, 2, on ? (layerIndex === 2 ? "#f2c96f" : "#9fb5c3") : layer.window);
          }
        }
      }
      ctx.globalAlpha = 1;
    });

    const railOffset = -((Math.floor(cameraX * 0.72) % 34) + 34) % 34;
    rect(0, groundY - 7, logicalW, 2, "#263d51");
    for (let x = railOffset; x < logicalW + 34; x += 34) rect(x, groundY - 14, 2, 9, "#263d51");
  }

  function drawMountains(cameraX) {
    const ranges = [
      { base: 3060, step: 96, parallax: 0.27, color: "#263b50", facet: "#1e3145", height: 70, alpha: 0.76 },
      { base: 3200, step: 78, parallax: 0.43, color: "#2b4a51", facet: "#213e47", height: 60, alpha: 0.9 },
      { base: 3380, step: 62, parallax: 0.62, color: "#315951", facet: "#294c48", height: 44, alpha: 1 }
    ];
    ranges.forEach((range, layer) => {
      ctx.globalAlpha = range.alpha;
      for (let i = -2; i < 38; i += 1) {
        const wx = range.base + i * range.step;
        const x = screenX(wx, cameraX, range.parallax);
        if (!isVisible(x, range.step * 2)) continue;
        const peak = groundY - range.height - Math.round(hash(i + 72 + layer) * 22);
        ctx.fillStyle = range.color;
        ctx.beginPath();
        ctx.moveTo(x - range.step, groundY);
        ctx.lineTo(x, peak);
        ctx.lineTo(x + range.step, groundY);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = range.facet;
        ctx.beginPath();
        ctx.moveTo(x, peak);
        ctx.lineTo(x + Math.round(range.step * 0.24), groundY - Math.round(range.height * 0.45));
        ctx.lineTo(x + range.step, groundY);
        ctx.lineTo(x, groundY);
        ctx.closePath();
        ctx.fill();
        if (layer < 2 && hash(i + 406) > 0.32) {
          ctx.fillStyle = layer === 0 ? "#b6c8c6" : "#9eb7b4";
          ctx.beginPath();
          ctx.moveTo(x, peak);
          ctx.lineTo(x - 9, peak + 13);
          ctx.lineTo(x - 2, peak + 10);
          ctx.lineTo(x + 3, peak + 15);
          ctx.lineTo(x + 11, peak + 14);
          ctx.closePath();
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
    });
  }

  function drawPineForest(cameraX, progress) {
    const visibility = smoothstep((progress - 0.5) / 0.16);
    if (visibility < 0.02) return;
    const layers = [
      { parallax: 0.7, step: 42, color: "#193b3d", alpha: 0.42, minH: 18, rangeH: 22 },
      { parallax: 0.88, step: 34, color: "#173330", alpha: 0.75, minH: 14, rangeH: 24 }
    ];

    layers.forEach((layer, layerIndex) => {
      ctx.globalAlpha = visibility * layer.alpha;
      for (let i = -3; i < 76; i += 1) {
        const wx = 3100 + i * layer.step + layerIndex * 17;
        const x = screenX(wx, cameraX, layer.parallax);
        if (!isVisible(x, 30)) continue;
        const height = layer.minH + Math.floor(hash(i + layerIndex * 89 + 710) * layer.rangeH);
        const baseY = groundY;
        rect(x, baseY - Math.round(height * 0.48), 2, Math.round(height * 0.48), "#182827");
        ctx.fillStyle = layer.color;
        ctx.beginPath();
        ctx.moveTo(x + 1, baseY - height);
        ctx.lineTo(x - Math.round(height * 0.24), baseY - Math.round(height * 0.38));
        ctx.lineTo(x - Math.round(height * 0.1), baseY - Math.round(height * 0.42));
        ctx.lineTo(x - Math.round(height * 0.3), baseY - 6);
        ctx.lineTo(x + Math.round(height * 0.3), baseY - 6);
        ctx.lineTo(x + Math.round(height * 0.1), baseY - Math.round(height * 0.42));
        ctx.lineTo(x + Math.round(height * 0.24), baseY - Math.round(height * 0.38));
        ctx.closePath();
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    });
  }

  function drawCircuitField(cameraX, time) {
    const tick = reduceMotion ? 0 : Math.floor(time / 620);
    ctx.globalAlpha = 0.34;
    for (let i = 0; i < 20; i += 1) {
      const wx = 2140 + i * 78;
      const x = screenX(wx, cameraX, 0.82);
      if (!isVisible(x, 90)) continue;
      const y = 34 + Math.floor(hash(i + 811) * Math.max(24, groundY - 92));
      const width = 18 + Math.floor(hash(i + 91) * 32);
      const color = i % 3 === 0 ? "#b47cff" : i % 3 === 1 ? "#5ee6c4" : "#62b7ff";
      rect(x, y, width, 1, color);
      rect(x + width, y, 1, 10 + Math.floor(hash(i + 552) * 18), color);
      rect(x - 2, y - 2, 5, 5, "#1a2748");
      rect(x - 1, y - 1, 3, 3, (tick + i) % 4 === 0 ? "#eef7ff" : color);
    }
    ctx.globalAlpha = 1;
  }

  function drawTrailDetails(cameraX) {
    for (let i = 0; i < 18; i += 1) {
      const wx = 3420 + i * 118;
      const x = screenX(wx, cameraX);
      if (!isVisible(x, 70)) continue;
      rect(x, groundY - 13, 2, 13, "#6d604c");
      rect(x + 48, groundY - 13, 2, 13, "#6d604c");
      rect(x, groundY - 10, 50, 2, "#806f54");
      rect(x + 8, groundY - 5, 18, 1, "rgba(226,190,112,.24)");
    }
  }

  function drawGround(cameraX, progress) {
    const blend = sceneBlend(progress);
    const ground = mixColor(blend.current.ground, blend.next.ground, blend.local);
    const rim = progress > 0.58 ? "#52775e" : "#3d566b";
    const paving = mixColor(ground, "#52677a", progress > 0.58 ? 0.08 : 0.2);
    const lower = mixColor(ground, "#050b17", 0.42);
    const tile = 22;
    const offset = -((Math.floor(cameraX) % tile) + tile) % tile;

    rect(0, groundY, logicalW, 2, rim);
    rect(0, groundY + 2, logicalW, 13, paving);
    rect(0, groundY + 15, logicalW, 2, mixColor(paving, "#91a0a8", 0.13));
    rect(0, groundY + 17, logicalW, logicalH - groundY - 17, lower);
    for (let x = offset; x < logicalW + tile; x += tile) {
      rect(x, groundY + 3, 1, 12, "rgba(205,224,230,.11)");
      const notch = hash(Math.floor((cameraX + x) / tile));
      if (notch > 0.62) rect(x + 6, groundY + 7 + Math.floor(notch * 4), 3, 1, "rgba(230,239,235,.13)");
    }

    const lowerOffset = -((Math.floor(cameraX * 1.08) % 54) + 54) % 54;
    for (let x = lowerOffset; x < logicalW + 54; x += 54) {
      rect(x, groundY + 25, 1, Math.max(1, logicalH - groundY - 25), "rgba(110,139,154,.09)");
      rect(x + 18, groundY + 28, 4, 2, "rgba(130,160,170,.12)");
    }

    const dashOffset = -((Math.floor(cameraX * 0.94) % 68) + 68) % 68;
    for (let x = dashOffset; x < logicalW + 68; x += 68) {
      rect(x + 8, groundY + 18, 14, 1, "rgba(196,211,212,.08)");
    }

    if (progress > 0.58) {
      for (let i = 0; i < 68; i += 1) {
        const wx = 3220 + i * 43;
        const x = screenX(wx, cameraX);
        if (!isVisible(x, 10)) continue;
        const height = 3 + Math.floor(hash(i + 550) * 5);
        rect(x, groundY - height, 1, height, i % 2 ? "#6fa463" : "#85bb6c");
        rect(x - 2, groundY - height + 2, 2, 1, "#6fa463");
        rect(x + 1, groundY - height + 1, 2, 1, "#85bb6c");
      }
    }
  }

  function drawStreetLight(wx, cameraX, color = "#ffd26d") {
    const x = screenX(wx, cameraX);
    if (!isVisible(x, 30)) return;
    rect(x, groundY - 54, 3, 54, "#25374b");
    rect(x - 3, groundY - 56, 16, 3, "#25374b");
    rect(x + 8, groundY - 55, 7, 7, color);
    rect(x + 10, groundY - 53, 3, 3, "#fff0b1");
  }

  function drawIntro(cameraX, time) {
    drawStreetLight(120, cameraX);
    drawStreetLight(610, cameraX);

    const terminalX = screenX(450, cameraX);
    if (isVisible(terminalX, 100)) {
      rect(terminalX, groundY - 82, 92, 82, "#1b2c3e");
      rect(terminalX + 7, groundY - 75, 78, 47, "#07121f");
      rect(terminalX + 11, groundY - 70, 42, 3, "#5ee6c4");
      rect(terminalX + 11, groundY - 61, 60, 2, "#2b5b5f");
      rect(terminalX + 11, groundY - 53, 52, 2, "#2b5b5f");
      rect(terminalX + 11, groundY - 45, 36 + ((Math.floor(time / 500) % 2) * 10), 2, "#2b5b5f");
      pixelText("你好，世界", terminalX + 11, groundY - 22, "#9ff9df", 7);
    }

    const arrowX = screenX(820, cameraX);
    if (isVisible(arrowX, 80)) {
      rect(arrowX, groundY - 35, 70, 35, "#1c3044");
      pixelText("开始  >", arrowX + 12, groundY - 23, "#5ee6c4", 8);
    }
  }

  function drawOfficeBuilding(wx, cameraX, label, sublabel, accent) {
    const x = screenX(wx, cameraX);
    const width = 132;
    const height = 118;
    if (!isVisible(x, width)) return;
    const y = groundY - height;
    rect(x, y, width, height, "#17283d");
    rect(x + 6, y + 7, width - 12, height - 7, "#20364e");
    rect(x + 6, y + 7, 3, height - 7, "#35516a");
    rect(x + width - 10, y + 7, 4, height - 7, "#13273b");
    rect(x + 14, y + 17, 48, 32, "#0b1727");
    rect(x + 70, y + 17, 48, 32, "#0b1727");
    rect(x + 14, y + 58, 48, 25, "#0b1727");
    rect(x + 70, y + 58, 48, 25, "#0b1727");
    for (let row = 0; row < 2; row += 1) {
      for (let col = 0; col < 3; col += 1) {
        rect(x + 20 + col * 15, y + 23 + row * 15, 8, 5, col === 1 ? accent : "#31516b");
        rect(x + 76 + col * 15, y + 23 + row * 15, 8, 5, col === 2 ? accent : "#31516b");
      }
    }
    rect(x + 13, y + 51, 106, 2, "#38536a");
    rect(x + 13, y + 86, 106, 2, "#14273b");
    for (let col = 0; col < 5; col += 1) {
      rect(x + 17 + col * 22, y + 91, 11, 3, col % 2 ? "#314b61" : "#273f55");
    }
    rect(x + 46, y + 91, 40, 27, "#0a1524");
    rect(x + 50, y + 96, 14, 22, "#142c43");
    rect(x + 67, y + 96, 14, 22, "#17364e");
    rect(x + 64, y + 96, 2, 22, accent);
    rect(x + 20, y + 2, 18, 4, "#293f55");
    rect(x + 24, y - 6, 2, 8, "#334e65");
    rect(x, y - 23, width, 23, "#0b1727");
    rect(x, y - 1, width, 2, accent);
    pixelText(label, x + 8, y - 18, accent, 9);
    pixelText(sublabel, x + width - 8, y - 17, "#8fa4b8", 6, "right");
  }

  function drawWorkstation(wx, cameraX, time, accent, dualScreen = false) {
    const x = screenX(wx, cameraX);
    const width = dualScreen ? 122 : 96;
    if (!isVisible(x, width)) return;

    const floor = groundY - 2;
    const screenY = floor - 82;
    const tick = reduceMotion ? 0 : Math.floor(time / 360);
    const screens = dualScreen ? 2 : 1;
    const screenWidth = dualScreen ? 52 : 72;

    rect(x - 5, screenY - 7, width + 10, 66, "rgba(5, 13, 26, 0.34)");
    for (let index = 0; index < screens; index += 1) {
      const sx = x + 7 + index * 57;
      rect(sx, screenY, screenWidth, 43, "#091321");
      rect(sx + 3, screenY + 3, screenWidth - 6, 34, "#10283b");
      rect(sx + 7, screenY + 8, 14 + ((tick + index) % 3) * 5, 2, accent);
      rect(sx + 7, screenY + 14, screenWidth - 19, 2, "#41647c");
      rect(sx + 11, screenY + 20, screenWidth - 26, 2, "#294b62");
      rect(sx + 7, screenY + 26, 18 + ((tick + index + 1) % 4) * 4, 2, "#d5bb69");
      rect(sx + 7, screenY + 32, 3, 2, (tick + index) % 2 ? accent : "#10283b");
      rect(sx + Math.floor(screenWidth / 2) - 2, screenY + 43, 4, 7, "#31495d");
      rect(sx + Math.floor(screenWidth / 2) - 9, screenY + 49, 18, 3, "#3b5365");
    }

    rect(x, floor - 29, width, 5, "#3a5061");
    rect(x + 5, floor - 24, 5, 24, "#233748");
    rect(x + width - 10, floor - 24, 5, 24, "#233748");
    rect(x + 25, floor - 22, dualScreen ? 51 : 40, 4, "#162737");
    for (let key = 0; key < (dualScreen ? 9 : 7); key += 1) {
      rect(x + 28 + key * 5, floor - 21, 3, 1, key === tick % 7 ? accent : "#587080");
    }
    rect(x + width - 25, floor - 22, 5, 4, "#506a7a");

    rect(x + 13, floor - 24, 16, 22, "#0a1421");
    rect(x + 16, floor - 21, 10, 3, "#24394c");
    rect(x + 17, floor - 14, 3, 2, tick % 2 ? accent : "#3b5569");
    rect(x + 22, floor - 14, 3, 2, "#d5bb69");
    rect(x + 14, floor - 2, 14, 2, "#1b2d3c");

    rect(x + width - 13, floor - 36, 8, 8, "#172938");
    rect(x + width - 12, floor - 39, 2, 3, "#627d8d");
    rect(x + width - 6, floor - 38, 4, 2, "#627d8d");
  }

  function drawWork(cameraX, time) {
    drawOfficeBuilding(1260, cameraX, "社交之城", "2023 — 2025", "#62b7ff");
    drawOfficeBuilding(1840, cameraX, "全球骑手履约", "2025 — 至今", "#5ee6c4");
    drawWorkstation(1110, cameraX, time, "#62b7ff", true);
    drawWorkstation(1450, cameraX, time, "#5ee6c4", false);
    drawWorkstation(2115, cameraX, time, "#62b7ff", true);

    const billboard = screenX(1545, cameraX);
    if (isVisible(billboard, 160)) {
      rect(billboard, groundY - 91, 156, 66, "#0a1422");
      rect(billboard + 4, groundY - 87, 148, 58, "#13283e");
      pixelText("千万级  日均 PV", billboard + 12, groundY - 76, "#f1d06d", 9);
      pixelText("0 起线上事故", billboard + 12, groundY - 56, "#62b7ff", 7);
      pixelText("覆盖 8 个国家和地区", billboard + 12, groundY - 42, "#5ee6c4", 7);
      rect(billboard + 20, groundY - 25, 4, 25, "#263b50");
      rect(billboard + 130, groundY - 25, 4, 25, "#263b50");
    }
  }

  function drawServerRack(wx, cameraX, time, accent) {
    const x = screenX(wx, cameraX);
    if (!isVisible(x, 44)) return;
    const y = groundY - 102;
    rect(x, y, 42, 102, "#090f22");
    rect(x + 4, y + 5, 34, 92, "#18203d");
    for (let row = 0; row < 6; row += 1) {
      rect(x + 8, y + 11 + row * 14, 26, 8, "#090f22");
      const blink = (Math.floor(time / 420) + row + Math.floor(wx)) % 3;
      rect(x + 11, y + 14 + row * 14, 3, 2, blink ? accent : "#344060");
      rect(x + 17, y + 14 + row * 14, 11, 2, "#293454");
    }
  }

  function drawAI(cameraX, time) {
    drawCircuitField(cameraX, time);
    const gate = screenX(2260, cameraX);
    if (isVisible(gate, 130)) {
      rect(gate, groundY - 132, 130, 132, "#10172e");
      rect(gate + 14, groundY - 116, 102, 116, "#070c1d");
      rect(gate + 22, groundY - 108, 86, 108, "#131b36");
      pixelText("AI 工坊", gate + 65, groundY - 126, "#b47cff", 9, "center");
    }

    drawServerRack(2530, cameraX, time, "#b47cff");
    drawServerRack(2600, cameraX, time + 300, "#5ee6c4");
    drawServerRack(3180, cameraX, time + 600, "#62b7ff");

    const coreX = screenX(2870, cameraX);
    if (isVisible(coreX, 220)) {
      rect(coreX - 104, groundY - 16, 208, 16, "#0b1128");
      const pulse = reduceMotion ? 0 : Math.sin(time * 0.004) * 2;
      const cy = groundY - 78 + pulse;
      ctx.strokeStyle = "#b47cff";
      ctx.lineWidth = 1;
      [[-72, -32], [-40, -70], [42, -64], [76, -26]].forEach(([dx, dy]) => {
        ctx.beginPath();
        ctx.moveTo(coreX, cy);
        ctx.lineTo(coreX + dx, cy + dy);
        ctx.stroke();
        rect(coreX + dx - 5, cy + dy - 5, 10, 10, "#1e2a4f");
        rect(coreX + dx - 2, cy + dy - 2, 4, 4, dx > 0 ? "#5ee6c4" : "#62b7ff");
      });
      rect(coreX - 17, cy - 17, 34, 34, "#362560");
      rect(coreX - 11, cy - 11, 22, 22, "#b47cff");
      rect(coreX - 5, cy - 5, 10, 10, "#f4dfff");
      pixelText("智能体核心", coreX, groundY - 29, "#d8c1ff", 7, "center");
    }

    const flowX = screenX(3380, cameraX);
    if (isVisible(flowX, 160)) {
      rect(flowX, groundY - 76, 150, 76, "#0a1124");
      pixelText("探索 > 动手 > 创造", flowX + 12, groundY - 65, "#b47cff", 7);
      for (let i = 0; i < 4; i += 1) {
        rect(flowX + 14 + i * 32, groundY - 45, 20, 16, i === Math.floor(time / 700) % 4 ? "#5ee6c4" : "#243253");
        if (i < 3) rect(flowX + 34 + i * 32, groundY - 38, 12, 2, "#7182a8");
      }
    }
  }

  function drawBike(wx, cameraX, time) {
    const x = screenX(wx, cameraX);
    if (!isVisible(x, 100)) return;
    const y = groundY - 18;
    ctx.strokeStyle = "#ffb84d";
    ctx.lineWidth = 2;
    [x, x + 56].forEach(cx => {
      ctx.beginPath();
      ctx.arc(cx, y, 14, 0, Math.PI * 2);
      ctx.stroke();
      for (let i = 0; i < 4; i += 1) {
        const phase = reduceMotion ? 0 : time * 0.003;
        ctx.beginPath();
        ctx.moveTo(cx, y);
        ctx.lineTo(cx + Math.cos(phase + i * Math.PI / 2) * 12, y + Math.sin(phase + i * Math.PI / 2) * 12);
        ctx.stroke();
      }
    });
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 19, y - 25);
    ctx.lineTo(x + 39, y);
    ctx.lineTo(x + 10, y);
    ctx.lineTo(x + 30, y - 23);
    ctx.lineTo(x + 56, y);
    ctx.moveTo(x + 19, y - 25);
    ctx.lineTo(x + 33, y - 25);
    ctx.stroke();
  }

  function drawBoxingGym(wx, cameraX, time) {
    const x = screenX(wx, cameraX);
    if (!isVisible(x, 150)) return;
    rect(x, groundY - 112, 146, 112, "#3c242b");
    rect(x + 7, groundY - 103, 132, 103, "#5a3031");
    for (let row = 0; row < 7; row += 1) {
      const brickOffset = row % 2 ? 7 : 0;
      for (let col = -1; col < 8; col += 1) {
        rect(x + 9 + brickOffset + col * 19, groundY - 97 + row * 11, 13, 1, "rgba(232,137,103,.12)");
      }
    }
    rect(x + 12, groundY - 108, 122, 4, "#2c1c28");
    rect(x + 17, groundY - 105, 32, 2, "#d75b49");
    rect(x + 98, groundY - 105, 29, 2, "#d75b49");
    rect(x + 18, groundY - 82, 110, 58, "#141723");
    rect(x + 22, groundY - 78, 102, 3, "#2b2635");
    rect(x + 22, groundY - 31, 102, 3, "#080c16");
    pixelText("第一回合", x + 73, groundY - 98, "#ffb84d", 8, "center");
    const sway = reduceMotion ? 0 : Math.sin(time * 0.003) * 3;
    rect(x + 70 + sway, groundY - 76, 7, 14, "#d8b47b");
    rect(x + 59 + sway, groundY - 62, 29, 38, "#a72836");
    rect(x + 62 + sway, groundY - 25, 23, 3, "#d9c2aa");
    rect(x + 20, groundY - 15, 106, 2, "#ffb84d");
    rect(x + 20, groundY - 8, 106, 2, "#ffb84d");
    for (let post = 0; post < 4; post += 1) rect(x + 20 + post * 35, groundY - 19, 2, 19, "#d3b06d");
  }

  function drawSignpost(wx, cameraX) {
    const x = screenX(wx, cameraX);
    if (!isVisible(x, 100)) return;
    rect(x, groundY - 72, 4, 72, "#75533a");
    rect(x - 42, groundY - 67, 46, 14, "#a96b3f");
    rect(x, groundY - 47, 54, 14, "#8e5b3b");
    pixelText("骑行", x - 36, groundY - 64, "#ffe1a0", 6);
    pixelText("旅行", x + 7, groundY - 44, "#ffe1a0", 6);
  }

  function drawLife(cameraX, time) {
    drawTrailDetails(cameraX);
    const rideLabel = screenX(3590, cameraX);
    if (isVisible(rideLabel, 100)) pixelText("一直向前", rideLabel, groundY - 61, "#ffcf72", 8);
    drawBoxingGym(4050, cameraX, time);
    drawSignpost(4540, cameraX);

    const tentX = screenX(4760, cameraX);
    if (isVisible(tentX, 90)) {
      ctx.fillStyle = "#d76a45";
      ctx.beginPath();
      ctx.moveTo(tentX, groundY);
      ctx.lineTo(tentX + 38, groundY - 49);
      ctx.lineTo(tentX + 78, groundY);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = "#723c38";
      ctx.beginPath();
      ctx.moveTo(tentX + 38, groundY - 49);
      ctx.lineTo(tentX + 38, groundY);
      ctx.lineTo(tentX + 78, groundY);
      ctx.closePath();
      ctx.fill();
    }
  }

  function drawFinale(cameraX, time) {
    const campX = screenX(5160, cameraX);
    if (isVisible(campX, 100)) {
      rect(campX - 20, groundY - 3, 52, 3, "#5d4334");
      const flicker = reduceMotion ? 0 : Math.floor(time / 140) % 3;
      rect(campX, groundY - 20 - flicker, 12, 20 + flicker, "#ff7a46");
      rect(campX + 3, groundY - 28 + flicker, 6, 19, "#ffcf72");
      rect(campX - 7, groundY - 3, 25, 3, "#b06a46");
    }

    const screen = screenX(5480, cameraX);
    if (isVisible(screen, 170)) {
      rect(screen, groundY - 112, 168, 112, "#080d1d");
      rect(screen + 7, groundY - 105, 154, 76, "#101c35");
      pixelText("准备好", screen + 16, groundY - 93, "#b0bfd6", 7);
      pixelText("奔赴下一段", screen + 16, groundY - 75, "#ff6fae", 13);
      pixelText("旅程了吗？", screen + 16, groundY - 56, "#ff6fae", 13);
      rect(screen + 16, groundY - 35, 66 + (Math.floor(time / 500) % 2) * 8, 3, "#5ee6c4");
    }
  }

  function drawForeground(cameraX, time) {
    for (let i = 0; i < 45; i += 1) {
      const wx = i * 137 + 40;
      const x = screenX(wx, cameraX, 1.15);
      if (!isVisible(x, 20)) continue;
      const h = 8 + Math.floor(hash(i + 230) * 18);
      rect(x, logicalH - h, 5 + Math.floor(hash(i) * 6), h, i > 23 ? "#111f28" : "#0c1827");
    }
  }

  function draw(time) {
    drawTextThisFrame = !Number.isFinite(lastTextProgress) || Math.abs(renderProgress - lastTextProgress) > 0.000001;
    if (drawTextThisFrame) textCtx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    const cameraX = renderProgress * WORLD_TRAVEL;
    drawSky(cameraX, renderProgress, time);
    drawCity(cameraX, time);
    drawMountains(cameraX);
    drawPineForest(cameraX, renderProgress);
    drawGround(cameraX, renderProgress);
    drawIntro(cameraX, time);
    drawWork(cameraX, time);
    drawAI(cameraX, time);
    drawLife(cameraX, time);
    drawFinale(cameraX, time);
    drawForeground(cameraX, time);
    if (drawTextThisFrame) lastTextProgress = renderProgress;
  }

  function loop(time) {
    rafId = 0;
    if (!pageVisible) return;

    const dt = Math.min(50, time - lastTime || 16.7);
    lastTime = time;
    const delta = targetProgress - renderProgress;
    const ease = reduceMotion ? 1 : 1 - Math.pow(0.001, dt / 1000);
    renderProgress += delta * ease;
    if (Math.abs(delta) < 0.00002) renderProgress = targetProgress;

    const moving = Math.abs(delta) > 0.00002;
    const interval = moving ? 16 : 42;
    if (needsDraw || time - lastDraw >= interval) {
      draw(time);
      updateInterface(renderProgress, time);
      lastDraw = time;
      needsDraw = false;
    }

    const interactionActive = time - lastScrollAt < 260;
    if (!moving && !interactionActive && renderedCharacterWalking) {
      updateInterface(renderProgress, time);
    }
    if (moving || interactionActive || needsDraw) ensureLoop();
    else scheduleIdleCharacterFrame();
  }

  function ensureLoop() {
    if (!rafId && pageVisible) rafId = window.requestAnimationFrame(loop);
  }

  function isIntroGreetingActive(time = performance.now()) {
    return !reduceMotion
      && !hasUserScrolled
      && activePose === "intro"
      && introGreetingStartedAt > 0
      && time - introGreetingStartedAt < INTRO_GREETING_DURATION_MS
      && poseMap.get("intro")?.classList.contains("has-idle-frame");
  }

  function scheduleIdleCharacterFrame() {
    if (idleCharacterTimer || !isIntroGreetingActive() || !pageVisible) return;
    idleCharacterTimer = window.setTimeout(() => {
      idleCharacterTimer = 0;
      needsDraw = true;
      ensureLoop();
    }, IDLE_CHARACTER_FRAME_MS);
  }

  function ready() {
    if (hasReadied) return;
    hasReadied = true;
    root.dataset.loading = "false";
    resize(true);
    updateInterface(renderProgress);
    ensurePose("intro");
    const warmNextPose = () => {
      ensurePose("work");
    };
    if ("requestIdleCallback" in window) window.requestIdleCallback(warmNextPose, { timeout: 1500 });
    else window.setTimeout(warmNextPose, 500);
    ensureLoop();
  }

  jumpButtons.forEach(button => {
    button.addEventListener("click", () => jumpTo(Number(button.dataset.sceneJump)));
  });

  window.addEventListener("scroll", () => {
    const nextScrollY = window.scrollY || window.pageYOffset || 0;
    if (Math.abs(nextScrollY - lastObservedScrollY) > 1) {
      hasUserScrolled = true;
      ensurePose(activePose);
      if (idleCharacterTimer) {
        window.clearTimeout(idleCharacterTimer);
        idleCharacterTimer = 0;
      }
    }
    lastObservedScrollY = nextScrollY;
    updateScroll();
  }, { passive: true });
  window.addEventListener("resize", () => resize(false), { passive: true });
  window.addEventListener("orientationchange", () => resize(true), { passive: true });
  document.addEventListener("visibilitychange", () => {
    pageVisible = !document.hidden;
    if (pageVisible) {
      lastTime = performance.now();
      needsDraw = true;
      ensureLoop();
    } else {
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = 0;
      }
      if (idleCharacterTimer) {
        window.clearTimeout(idleCharacterTimer);
        idleCharacterTimer = 0;
      }
    }
  });

  const introSprite = poseMap.get("intro");
  const introFrame = introSprite.querySelector('[data-frame="0"]');
  introFrame.addEventListener("load", ready, { once: true });
  introFrame.addEventListener("error", ready, { once: true });

  if (introFrame.complete) ready();
  else window.setTimeout(ready, 1800);

  track.style.height = coarsePointer ? "680vh" : "760vh";
  resize(true);
  updateScroll();

  window.__pixelWorld = {
    scenes: SCENES.map(({ id, anchor }) => ({ id, anchor })),
    getState: () => ({
      targetProgress,
      renderProgress,
      activeScene,
      activePose,
      characterFrame,
      characterFrameMode: renderedCharacterMode,
      loadedPoses: poseSprites.filter(sprite => {
        const frame = sprite.querySelector('[data-frame="0"]');
        return frame?.complete && frame.naturalWidth;
      }).map(sprite => sprite.dataset.pose),
      loadedMotionFrames: poseSprites.filter(sprite => sprite.classList.contains("has-motion-frame")).map(sprite => sprite.dataset.pose),
      canvas: { width: canvas.width, height: canvas.height },
      renderLoopActive: Boolean(rafId),
      idleAnimationActive: Boolean(idleCharacterTimer),
      introGreetingActive: isIntroGreetingActive(),
      hasUserScrolled,
      reducedMotion: reduceMotion,
      coarsePointer
    })
  };
})();
