const INDEX_KEY = "gallery-index.json";
const ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp", "mp4", "m4v", "webm"];
const STILL_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp"]);
const CLIP_EXTENSIONS = new Set(["gif", "mp4", "m4v", "webm"]);
const VIDEO_EXTENSIONS = new Set(["mp4", "m4v", "webm"]);

let indexCache = { expires: 0, items: [] };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/") return htmlResponse(renderAppHtml(env.CONTACT_EMAIL));
    if (url.pathname === "/api/random") return randomMedia(request, env);

    if (url.pathname.startsWith("/media/")) {
      let key;
      try {
        key = decodeURIComponent(url.pathname.slice("/media/".length));
      } catch {
        return new Response("Bad media key", { status: 400 });
      }

      if (!key.startsWith("gallery/")) return new Response("Not found", { status: 404 });
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
  if (requested === "stills") {
    choices = items.filter((item) => STILL_EXTENSIONS.has(String(item.ext).toLowerCase()));
  } else if (requested === "clips") {
    choices = items.filter((item) => CLIP_EXTENSIONS.has(String(item.ext).toLowerCase()));
  } else if (requested !== "all" && ALLOWED_EXTENSIONS.includes(requested)) {
    choices = items.filter((item) => String(item.ext).toLowerCase() === requested);
  }

  if (!choices.length) return jsonResponse({ error: "No media matches that filter." }, 404);

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
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function escapeHtmlAttribute(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderAppHtml(contactEmail) {
  const email = String(contactEmail || "").trim();
  if (!email) throw new Error("CONTACT_EMAIL secret is missing");
  const escapedEmail = escapeHtmlAttribute(email);
  return APP_HTML
    .replaceAll("__CONTACT_EMAIL_HREF__", `mailto:${escapedEmail}`)
    .replaceAll("__CONTACT_EMAIL_LABEL__", `Email ${escapedEmail}`);
}

const APP_HTML = String.raw`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>GParty</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    * { box-sizing: border-box; }
    html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: #000; }
    body { display: grid; grid-template-rows: 1fr auto; }
    #stage { min-height: 0; overflow: auto; cursor: zoom-in; position: relative; }
    #stage.native { cursor: zoom-out; }
    #media-wrap { min-width: 100%; min-height: 100%; display: grid; place-items: center; }
    #media { display: block; max-width: none; max-height: none; object-fit: contain; }
    #stage.native #media-wrap { width: max-content; height: max-content; }
    #bar { display: flex; gap: .8rem; align-items: center; justify-content: center; padding: .65rem; background: #000; }
    button { font: inherit; padding: .55rem .8rem; border-radius: .45rem; border: 1px solid #555; background: #222; color: #fff; cursor: pointer; font-weight: 700; }
    #footer-controls { width: min(20rem, 100%); display: grid; grid-template-columns: auto 1fr auto auto; align-items: center; column-gap: .85rem; }
    #filter { grid-column: 1; width: 4.5rem; margin: 0; padding: .4rem 0; border: 0; border-radius: 0; appearance: none; -webkit-appearance: none; background: transparent; color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
    #filter::-ms-expand { display: none; }
    .icon-link { width: 2rem; height: 2rem; display: grid; place-items: center; color: #fff; text-decoration: none; background: transparent; border: 0; }
    .icon-link:first-of-type { grid-column: 3; }
    .icon-link:last-of-type { grid-column: 4; }
    .icon-link svg { width: 1.45rem; height: 1.45rem; fill: currentColor; }
    #filter:focus { outline: none; }
    #filter:focus-visible, .icon-link:focus-visible { outline: 2px solid #fff; outline-offset: 4px; border-radius: .2rem; }
    #status { min-width: 8rem; color: #bbb; font-size: .9rem; }
    #hint { display: none; position: absolute; left: 50%; bottom: 1.1rem; transform: translateX(-50%); width: max-content; max-width: calc(100% - 2rem); padding: .55rem .75rem; border-radius: .45rem; background: rgb(0 0 0 / 55%); color: #fff; font-size: .95rem; line-height: 1.35; text-align: center; pointer-events: none; backdrop-filter: blur(4px); }
    #error { position: fixed; inset: 1rem 1rem auto; padding: .75rem; background: #5c1010; display: none; text-align: center; z-index: 10; }

    @media (max-width: 700px) {
      body { grid-template-rows: minmax(0, 1fr) auto; padding-top: env(safe-area-inset-top); padding-bottom: env(safe-area-inset-bottom); }
      #stage { overflow: hidden; cursor: pointer; padding: .35rem .35rem 0; }
      #stage.native { cursor: pointer; }
      #media-wrap { min-width: 0; min-height: 0; width: 100%; height: 100%; }
      #media { width: 100% !important; height: 100% !important; max-width: 100%; max-height: 100%; object-fit: contain; }
      #bar { padding: .7rem .8rem .85rem; min-height: 3.5rem; }
      #next, #status { display: none; }
      #footer-controls { width: min(20rem, 100%); }
      #filter { min-height: 2rem; font-size: 1rem; }
      .icon-link { width: 2rem; height: 2rem; }
      #hint { display: block; }
    }
  </style>
</head>
<body>
  <main id="stage" title="Click media to toggle fit/native size"></main>
  <div id="bar">
    <button id="next" type="button">Next random</button>
    <div id="footer-controls">
      <select id="filter" aria-label="Media filter">
        <option value="all">All</option>
        <option value="stills">Stills</option>
        <option value="clips">Clips</option>
      </select>
      <a class="icon-link" href="https://github.com/polskiftw/gparty" target="_blank" rel="noopener noreferrer" aria-label="Open GitHub repository">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 .7a11.5 11.5 0 0 0-3.64 22.41c.58.11.79-.25.79-.56v-2.03c-3.22.7-3.9-1.37-3.9-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.71.08-.71 1.17.08 1.78 1.2 1.78 1.2 1.04 1.78 2.72 1.27 3.39.97.1-.75.4-1.27.74-1.56-2.57-.29-5.27-1.29-5.27-5.73 0-1.27.45-2.3 1.2-3.11-.12-.3-.52-1.48.11-3.08 0 0 .98-.31 3.16 1.19a10.9 10.9 0 0 1 5.75 0c2.18-1.5 3.16-1.19 3.16-1.19.63 1.6.23 2.78.11 3.08.74.81 1.2 1.84 1.2 3.11 0 4.45-2.71 5.43-5.29 5.72.42.36.79 1.06.79 2.14v3.16c0 .31.21.68.8.56A11.5 11.5 0 0 0 12 .7Z"/></svg>
      </a>
      <a class="icon-link" href="__CONTACT_EMAIL_HREF__" aria-label="__CONTACT_EMAIL_LABEL__">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.75 4.5h18.5A2.75 2.75 0 0 1 24 7.25v9.5a2.75 2.75 0 0 1-2.75 2.75H2.75A2.75 2.75 0 0 1 0 16.75v-9.5A2.75 2.75 0 0 1 2.75 4.5Zm0 1.75a1 1 0 0 0-.64.23L12 14.58l9.89-8.1a1 1 0 0 0-.64-.23H2.75Zm19.5 2.03-6.87 5.63 6.64 4.01c.15-.34.23-.72.23-1.17V8.28ZM1.75 8.28v8.47c0 .45.08.83.23 1.17l6.64-4.01-6.87-5.63Zm8.31 6.8-6.7 4.05c.2.08.42.12.64.12h16c.22 0 .44-.04.64-.12l-6.7-4.05-1.38 1.13a.88.88 0 0 1-1.12 0l-1.38-1.13Z"/></svg>
      </a>
    </div>
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
  const mobileQuery = window.matchMedia('(max-width: 700px)');
  let loading = false;
  let sizeMode = 'fit';
  let showHint = true;

  function intrinsicSize(media) {
    return media.tagName === 'VIDEO'
      ? { width: media.videoWidth, height: media.videoHeight }
      : { width: media.naturalWidth, height: media.naturalHeight };
  }

  function applySizeMode(media, centerNative = false) {
    if (!media) return;

    if (mobileQuery.matches) {
      sizeMode = 'fit';
      stage.classList.remove('native');
      media.style.width = '100%';
      media.style.height = '100%';
      stage.scrollLeft = 0;
      stage.scrollTop = 0;
      return;
    }

    const { width, height } = intrinsicSize(media);
    if (!(width > 0 && height > 0)) return;

    const native = sizeMode === 'native';
    stage.classList.toggle('native', native);

    let renderedWidth = width;
    let renderedHeight = height;
    if (!native) {
      const scale = Math.min(1, Math.max(1, stage.clientWidth) / width, Math.max(1, stage.clientHeight) / height);
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

  function addHint() {
    if (!mobileQuery.matches || !showHint) return;
    const hint = document.createElement('div');
    hint.id = 'hint';
    hint.textContent = 'Tap the image to load the next random item';
    stage.appendChild(hint);
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
      const media = VIDEO_EXTENSIONS.has(ext)
        ? document.createElement('video')
        : document.createElement('img');

      if (media.tagName === 'VIDEO') {
        media.autoplay = true;
        media.loop = true;
        media.muted = true;
        media.playsInline = true;
        media.preload = 'auto';
        media.disablePictureInPicture = true;
        media.controls = false;
      } else {
        media.alt = '';
        media.decoding = 'async';
      }

      media.id = 'media';
      media.src = data.url;

      const mediaWrap = document.createElement('div');
      mediaWrap.id = 'media-wrap';
      mediaWrap.appendChild(media);
      stage.replaceChildren(mediaWrap);
      addHint();
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
  filter.addEventListener('change', () => {
    showHint = false;
    loadRandom();
  });
  stage.addEventListener('click', (event) => {
    if (event.target.id !== 'media') return;

    if (mobileQuery.matches) {
      showHint = false;
      loadRandom();
      return;
    }

    sizeMode = sizeMode === 'fit' ? 'native' : 'fit';
    applySizeMode(event.target, sizeMode === 'native');
  });

  function reapplyCurrentSize() {
    const media = document.getElementById('media');
    if (media) applySizeMode(media, false);
  }

  window.addEventListener('resize', reapplyCurrentSize);
  mobileQuery.addEventListener('change', reapplyCurrentSize);
  document.addEventListener('fullscreenchange', reapplyCurrentSize);
  document.addEventListener('keydown', (event) => {
    if (event.code === 'Space') {
      event.preventDefault();
      showHint = false;
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