const INDEX_KEY = "gallery-index.json";
const ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp", "mp4", "m4v", "webm"];
const VIDEO_EXTENSIONS = new Set(["mp4", "m4v", "webm"]);

let indexCache = { expires: 0, items: [] };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/") {
      return htmlResponse(APP_HTML);
    }

    if (url.pathname === "/api/random") {
      return randomMedia(request, env);
    }

    if (url.pathname.startsWith("/media/")) {
      const encodedKey = url.pathname.slice("/media/".length);
      let key;
      try {
        key = decodeURIComponent(encodedKey);
      } catch {
        return new Response("Bad media key", { status: 400 });
      }
      if (!key.startsWith("gallery/")) {
        return new Response("Not found", { status: 404 });
      }
      return serveMedia(request, env, key);
    }

    return new Response("Not found", { status: 404 });
  },
};

async function loadIndex(env) {
  const now = Date.now();
  if (indexCache.expires > now && indexCache.items.length) return indexCache.items;

  const object = await env.MEDIA_BUCKET.get(INDEX_KEY);
  if (!object) return [];

  let payload;
  try {
    payload = JSON.parse(await object.text());
  } catch {
    return [];
  }

  const rawItems = Array.isArray(payload) ? payload : payload.items;
  const items = Array.isArray(rawItems)
    ? rawItems.filter((item) => item && typeof item.key === "string" && item.key.startsWith("gallery/"))
    : [];

  indexCache = { expires: now + 60_000, items };
  return items;
}

async function randomMedia(request, env) {
  const url = new URL(request.url);
  const requested = (url.searchParams.get("ext") || "all").toLowerCase();
  const items = await loadIndex(env);

  let choices = items;
  if (requested === "images") {
    choices = items.filter((item) => !VIDEO_EXTENSIONS.has(String(item.ext).toLowerCase()));
  } else if (requested === "videos") {
    choices = items.filter((item) => VIDEO_EXTENSIONS.has(String(item.ext).toLowerCase()));
  } else if (requested !== "all" && ALLOWED_EXTENSIONS.includes(requested)) {
    choices = items.filter((item) => String(item.ext).toLowerCase() === requested);
  }

  if (!choices.length) {
    return jsonResponse({ error: "No media matches that filter." }, 404);
  }

  const item = choices[Math.floor(Math.random() * choices.length)];
  return jsonResponse({
    key: item.key,
    ext: item.ext,
    url: `/media/${encodeURIComponent(item.key)}`,
    total: choices.length,
  });
}

async function serveMedia(request, env, key) {
  const range = request.headers.get("Range");
  const object = await env.MEDIA_BUCKET.get(key, range ? { range: request.headers } : undefined);
  if (!object) return new Response("Not found", { status: 404 });

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("cache-control", "private, max-age=86400");
  headers.set("accept-ranges", "bytes");

  const status = object.range ? 206 : 200;
  if (object.range) {
    const offset = object.range.offset ?? 0;
    const length = object.range.length ?? object.size;
    headers.set("content-range", `bytes ${offset}-${offset + length - 1}/${object.size}`);
    headers.set("content-length", String(length));
  }

  return new Response(object.body, { status, headers });
}

function htmlResponse(body) {
  return new Response(body, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
    },
  });
}

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

const APP_HTML = String.raw`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Media Gallery</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    * { box-sizing: border-box; }
    html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }
    body { display: grid; grid-template-rows: 1fr auto; }
    #stage { min-height: 0; overflow: auto; cursor: zoom-in; }
    #stage.native { cursor: zoom-out; }
    #media-wrap { min-width: 100%; min-height: 100%; display: grid; place-items: center; }
    #media { display: block; max-width: none; max-height: none; object-fit: contain; }
    #stage.native #media-wrap { width: max-content; height: max-content; }
    #bar { display: flex; gap: .6rem; align-items: center; justify-content: center; padding: .65rem; background: #101010; }
    button, select { font: inherit; padding: .55rem .8rem; border-radius: .45rem; border: 1px solid #555; background: #222; color: #fff; }
    button { cursor: pointer; font-weight: 700; }
    #status { min-width: 8rem; color: #bbb; font-size: .9rem; }
    #error { position: fixed; inset: 1rem 1rem auto; padding: .75rem; background: #5c1010; display: none; text-align: center; }
  </style>
</head>
<body>
  <main id="stage" title="Click media to toggle fit/native size"></main>
  <div id="bar">
    <button id="next" type="button">Next random</button>
    <label>Filter
      <select id="filter">
        <option value="all">All</option>
        <option value="images">Images</option>
        <option value="videos">Videos</option>
        <option value="jpg">JPG</option>
        <option value="jpeg">JPEG</option>
        <option value="png">PNG</option>
        <option value="gif">GIF</option>
        <option value="webp">WEBP</option>
        <option value="mp4">MP4</option>
        <option value="m4v">M4V</option>
        <option value="webm">WEBM</option>
      </select>
    </label>
    <span id="status"></span>
  </div>
  <div id="error"></div>
<script>
(() => {
  const stage = document.getElementById('stage');
  const next = document.getElementById('next');
  const filter = document.getElementById('filter');
  const status = document.getElementById('status');
  const error = document.getElementById('error');
  let loading = false;
  let sizeMode = 'fit';

  function intrinsicSize(media) {
    return media.tagName === 'VIDEO'
      ? { width: media.videoWidth, height: media.videoHeight }
      : { width: media.naturalWidth, height: media.naturalHeight };
  }

  function applySizeMode(media, centerNative = false) {
    if (!media) return;

    const { width, height } = intrinsicSize(media);
    if (!(width > 0 && height > 0)) return;

    const native = sizeMode === 'native';
    stage.classList.toggle('native', native);

    let renderedWidth = width;
    let renderedHeight = height;

    if (!native) {
      const availableWidth = Math.max(1, stage.clientWidth);
      const availableHeight = Math.max(1, stage.clientHeight);
      const scale = Math.min(1, availableWidth / width, availableHeight / height);
      renderedWidth = Math.max(1, Math.round(width * scale));
      renderedHeight = Math.max(1, Math.round(height * scale));
    }

    media.style.width = renderedWidth + 'px';
    media.style.height = renderedHeight + 'px';

    requestAnimationFrame(() => {
      if (native && centerNative) {
        stage.scrollLeft = Math.max(0, (stage.scrollWidth - stage.clientWidth) / 2);
        stage.scrollTop = Math.max(0, (stage.scrollHeight - stage.clientHeight) / 2);
      } else if (!native) {
        stage.scrollLeft = 0;
        stage.scrollTop = 0;
      }
    });
  }

  async function loadRandom() {
    if (loading) return;
    loading = true;
    next.disabled = true;
    error.style.display = 'none';
    status.textContent = 'Loading…';
    try {
      const response = await fetch('/api/random?ext=' + encodeURIComponent(filter.value), { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not load media.');

      const ext = String(data.ext || '').toLowerCase();
      let media;
      if (ext === 'mp4' || ext === 'm4v' || ext === 'webm') {
        media = document.createElement('video');
        media.autoplay = true;
        media.loop = true;
        media.muted = true;
        media.playsInline = true;
        media.preload = 'auto';
        media.disablePictureInPicture = true;
        media.controls = false;
      } else {
        media = document.createElement('img');
        media.alt = '';
        media.decoding = 'async';
      }
      media.id = 'media';
      media.src = data.url;
      const mediaWrap = document.createElement('div');
      mediaWrap.id = 'media-wrap';
      mediaWrap.appendChild(media);
      stage.replaceChildren(mediaWrap);
      stage.scrollLeft = 0;
      stage.scrollTop = 0;
      status.textContent = data.total + ' matching';

      const readyEvent = media.tagName === 'VIDEO' ? 'loadedmetadata' : 'load';
      media.addEventListener(readyEvent, () => applySizeMode(media, sizeMode === 'native'), { once: true });
      if ((media.tagName === 'IMG' && media.complete && media.naturalWidth > 0) ||
          (media.tagName === 'VIDEO' && media.readyState >= 1 && media.videoWidth > 0)) {
        applySizeMode(media, sizeMode === 'native');
      }
      if (media.tagName === 'VIDEO') media.play().catch(() => {});
    } catch (problem) {
      error.textContent = problem.message;
      error.style.display = 'block';
      status.textContent = 'Error';
    } finally {
      loading = false;
      next.disabled = false;
    }
  }

  next.addEventListener('click', loadRandom);
  filter.addEventListener('change', loadRandom);
  stage.addEventListener('click', (event) => {
    if (event.target.id !== 'media') return;
    sizeMode = sizeMode === 'fit' ? 'native' : 'fit';
    applySizeMode(event.target, sizeMode === 'native');
  });
  function reapplyCurrentSize() {
    const media = document.getElementById('media');
    if (media) applySizeMode(media, false);
  }

  window.addEventListener('resize', reapplyCurrentSize);
  document.addEventListener('fullscreenchange', reapplyCurrentSize);

  document.addEventListener('keydown', (event) => {
    if (event.code === 'Space') {
      event.preventDefault();
      loadRandom();
    } else if (event.key.toLowerCase() === 'f') {
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      else document.documentElement.requestFullscreen().catch(() => {});
    }
  });

  loadRandom();
})();
</script>
</body>
</html>`;