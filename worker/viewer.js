import APP_SCRIPT from "./app.js";
import APP_STYLE from "./style.css";

const INDEX_KEY = "gallery-index.json";
const SOURCE_CONFIG_KEY = "_internal/reddit-sources.json";
const SUBREDDIT_NAME_PATTERN = /^[A-Za-z0-9_]{3,21}$/;
const MAX_MANAGED_SOURCES = 500;
const ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp", "mp4", "m4v", "webm"];
const STILL_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp"]);
const CLIP_EXTENSIONS = new Set(["gif", "mp4", "m4v", "webm"]);

let indexCache = { expires: 0, items: [] };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/robots.txt") return robotsResponse();
    if (url.pathname === "/") return htmlResponse(renderAppHtml(env.CONTACT_EMAIL));
    if (url.pathname === "/style.css") return assetResponse(APP_STYLE, "text/css; charset=utf-8");
    if (url.pathname === "/app.js") return assetResponse(APP_SCRIPT, "text/javascript; charset=utf-8");
    if (url.pathname === "/api/random") return randomMedia(request, env);
    if (url.pathname === "/api/sources") {
      if (request.method !== "POST") {
        return new Response(JSON.stringify({ error: "Method not allowed." }), {
          status: 405,
          headers: {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
            allow: "POST",
          },
        });
      }
      return addManagedSource(request, env);
    }

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


function normalizeSubredditName(value) {
  let candidate = String(value || "").trim();
  if (!candidate) return "";

  if (/^https?:\/\//i.test(candidate)) {
    let parsed;
    try {
      parsed = new URL(candidate);
    } catch {
      return "";
    }
    const hostname = parsed.hostname.toLowerCase();
    if (!["reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com"].includes(hostname)) {
      return "";
    }
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (parts.length < 2 || parts[0].toLowerCase() !== "r") return "";
    candidate = parts[1];
  } else {
    candidate = candidate.replace(/^\/+|\/+$/g, "");
    if (candidate.toLowerCase().startsWith("r/")) candidate = candidate.slice(2);
    candidate = candidate.split("/")[0];
  }

  return SUBREDDIT_NAME_PATTERN.test(candidate) ? candidate : "";
}

function hasVerifiedClientCertificate(request) {
  return request.cf?.tlsClientAuth?.certPresented === "1"
    && request.cf?.tlsClientAuth?.certVerified === "SUCCESS";
}

async function readManagedSources(env) {
  const object = await env.MEDIA_BUCKET.get(SOURCE_CONFIG_KEY);
  if (!object) return { object: null, sources: [] };

  let payload;
  try {
    payload = JSON.parse(await object.text());
  } catch {
    throw new Error("Private source configuration is unreadable.");
  }

  const sources = Array.isArray(payload) ? payload : payload?.sources;
  if (!Array.isArray(sources)) {
    throw new Error("Private source configuration has an invalid shape.");
  }

  const cleaned = [];
  const seen = new Set();
  for (const value of sources) {
    const name = normalizeSubredditName(value);
    const key = name.toLowerCase();
    if (!name || seen.has(key)) continue;
    seen.add(key);
    cleaned.push(name);
  }
  return { object, sources: cleaned };
}

async function addManagedSource(request, env) {
  const url = new URL(request.url);
  if (!hasVerifiedClientCertificate(request)) {
    return jsonResponse({ error: "A verified client certificate is required." }, 403);
  }
  if (request.headers.get("origin") !== url.origin) {
    return jsonResponse({ error: "This request must come from the GParty viewer." }, 403);
  }
  const contentType = (request.headers.get("content-type") || "").toLowerCase();
  if (!contentType.startsWith("application/json")) {
    return jsonResponse({ error: "Expected a JSON request." }, 415);
  }
  const declaredLength = Number(request.headers.get("content-length") || "0");
  if (declaredLength > 1024) {
    return jsonResponse({ error: "That request is too large." }, 413);
  }

  let payload;
  try {
    payload = await request.json();
  } catch {
    return jsonResponse({ error: "The subreddit request was unreadable." }, 400);
  }

  const name = normalizeSubredditName(payload?.subreddit);
  if (!name) {
    return jsonResponse(
      { error: "Enter a subreddit name such as pics, r/pics, or a Reddit subreddit URL." },
      400,
    );
  }

  const wanted = name.toLowerCase();
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const { object, sources } = await readManagedSources(env);
    if (sources.some((source) => source.toLowerCase() === wanted)) {
      return jsonResponse({ added: false, alreadyExists: true, count: sources.length });
    }
    if (sources.length >= MAX_MANAGED_SOURCES) {
      return jsonResponse({ error: "The private source list is full." }, 409);
    }

    sources.push(name);
    const body = JSON.stringify({
      version: 1,
      updated_at: new Date().toISOString(),
      sources,
    }, null, 2) + "\n";
    const onlyIf = new Headers(
      object
        ? { "If-Match": object.httpEtag }
        : { "If-None-Match": "*" },
    );
    const stored = await env.MEDIA_BUCKET.put(SOURCE_CONFIG_KEY, body, {
      onlyIf,
      httpMetadata: {
        contentType: "application/json; charset=utf-8",
        cacheControl: "no-store",
      },
      customMetadata: {
        private: "true",
        purpose: "reddit-sources",
      },
    });
    if (stored) {
      return jsonResponse({ added: true, alreadyExists: false, count: sources.length }, 201);
    }
  }

  return jsonResponse(
    { error: "The source list changed at the same moment. Please tap Add once more." },
    409,
  );
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

function robotsResponse() {
  return new Response("User-agent: *\nDisallow: /\n", {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=86400",
    },
  });
}

function htmlResponse(body) {
  return new Response(body, {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function assetResponse(body, contentType) {
  return new Response(body, {
    headers: {
      "content-type": contentType,
      "cache-control": "public, max-age=3600",
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
  <link rel="stylesheet" href="/style.css">
  <script src="/app.js" defer></script>
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
      <button id="add-source-open" class="icon-action" type="button" aria-label="Add a subreddit">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
      </button>
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
  <dialog id="source-dialog" aria-labelledby="source-dialog-title">
    <div id="source-dialog-body">
      <div id="source-dialog-title">Add subreddit</div>
      <label for="source-input">Subreddit name</label>
      <input id="source-input" type="text" maxlength="128" placeholder="pics" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false">
      <div id="source-feedback" aria-live="polite"></div>
      <div id="source-actions">
        <button id="source-close" type="button">Cancel</button>
        <button id="source-add" type="button">Add</button>
      </div>
    </div>
  </dialog>
</body>
</html>`;
