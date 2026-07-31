(() => {
  const stage = document.getElementById("stage");
  const next = document.getElementById("next");
  const filter = document.getElementById("filter");
  const status = document.getElementById("status");
  const error = document.getElementById("error");
  const addSourceOpen = document.getElementById("add-source-open");
  const sourceDialog = document.getElementById("source-dialog");
  const sourceInput = document.getElementById("source-input");
  const sourceFeedback = document.getElementById("source-feedback");
  const sourceForm = document.getElementById("source-dialog-body");
  const sourceClose = document.getElementById("source-close");
  const sourceAdd = document.getElementById("source-add");
  const mobileQuery = window.matchMedia("(max-width: 700px)");
  let loading = false;
  let sizeMode = "fit";
  let showHint = true;
  let resizeFrame = 0;

  const RANDOM_ATTEMPTS = 3;
  const RANDOM_TIMEOUT_MS = 12_000;

  function wait(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  function requestProblem(message, retryable) {
    const problem = new Error(message);
    problem.retryable = retryable;
    return problem;
  }

  function isTransientStatus(statusCode) {
    return [408, 425, 429].includes(statusCode) || statusCode >= 500;
  }

  async function fetchRandomOnce(extension) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), RANDOM_TIMEOUT_MS);

    try {
      const response = await fetch(`/api/random?ext=${encodeURIComponent(extension)}`, {
        cache: "no-store",
        headers: { accept: "application/json" },
        signal: controller.signal,
      });
      const contentType = response.headers.get("content-type") || "";
      const body = await response.text();

      if (!contentType.toLowerCase().includes("application/json")) {
        throw requestProblem(
          "The random-media service returned an invalid response.",
          true,
        );
      }

      let data;
      try {
        data = body ? JSON.parse(body) : null;
      } catch {
        throw requestProblem(
          "The random-media service returned unreadable data.",
          true,
        );
      }

      if (!response.ok) {
        const message =
          data && typeof data.error === "string"
            ? data.error
            : `The random-media service returned error ${response.status}.`;
        throw requestProblem(message, isTransientStatus(response.status));
      }

      if (
        !data ||
        typeof data.url !== "string" ||
        typeof data.ext !== "string" ||
        !Number.isFinite(Number(data.total))
      ) {
        throw requestProblem(
          "The random-media service returned incomplete data.",
          true,
        );
      }

      let mediaUrl;
      try {
        mediaUrl = new URL(data.url, window.location.href);
      } catch {
        throw requestProblem(
          "The random-media service returned an invalid media address.",
          true,
        );
      }
      if (
        mediaUrl.origin !== window.location.origin ||
        !mediaUrl.pathname.startsWith("/media/")
      ) {
        throw requestProblem(
          "The random-media service returned an unsafe media address.",
          true,
        );
      }

      return {
        ...data,
        url: `${mediaUrl.pathname}${mediaUrl.search}`,
      };
    } catch (problem) {
      if (problem && problem.retryable !== undefined) throw problem;
      if (problem && problem.name === "AbortError") {
        throw requestProblem("The random-media request timed out.", true);
      }
      throw requestProblem("The random-media service could not be reached.", true);
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function fetchRandom(extension) {
    let lastProblem;
    for (let attempt = 1; attempt <= RANDOM_ATTEMPTS; attempt += 1) {
      try {
        return await fetchRandomOnce(extension);
      } catch (problem) {
        lastProblem = problem;
        if (!problem.retryable || attempt === RANDOM_ATTEMPTS) throw problem;
        status.textContent = `Retrying… ${attempt + 1}/${RANDOM_ATTEMPTS}`;
        await wait(300 * attempt);
      }
    }
    throw lastProblem;
  }

  function intrinsicSize(media) {
    return media.tagName === "VIDEO"
      ? { width: media.videoWidth, height: media.videoHeight }
      : { width: media.naturalWidth, height: media.naturalHeight };
  }

  function applySizeMode(media, centerNative = false) {
    if (!media) return;
    if (mobileQuery.matches) {
      sizeMode = "fit";
      stage.classList.remove("native");
      media.style.removeProperty("width");
      media.style.removeProperty("height");
      stage.scrollLeft = 0;
      stage.scrollTop = 0;
      return;
    }

    const { width, height } = intrinsicSize(media);
    if (!(width > 0 && height > 0)) return;
    const native = sizeMode === "native";
    stage.classList.toggle("native", native);

    let renderedWidth = width;
    let renderedHeight = height;
    if (!native) {
      const scale = Math.min(
        1,
        Math.max(1, stage.clientWidth) / width,
        Math.max(1, stage.clientHeight) / height,
      );
      renderedWidth = Math.max(1, Math.round(width * scale));
      renderedHeight = Math.max(1, Math.round(height * scale));
    }

    media.style.width = `${renderedWidth}px`;
    media.style.height = `${renderedHeight}px`;
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
    const hint = document.createElement("div");
    hint.id = "hint";
    hint.textContent = "Tap the image to load the next random item";
    stage.appendChild(hint);
  }

  async function loadRandom() {
    if (loading) return;
    loading = true;
    next.disabled = true;
    error.style.display = "none";
    status.textContent = "Loading…";

    try {
      const data = await fetchRandom(filter.value);

      const ext = String(data.ext || "").toLowerCase();
      const media = ["mp4", "m4v", "webm"].includes(ext)
        ? document.createElement("video")
        : document.createElement("img");

      if (media.tagName === "VIDEO") {
        media.autoplay = true;
        media.loop = true;
        media.muted = true;
        media.playsInline = true;
        media.preload = "auto";
        media.disablePictureInPicture = true;
        media.controls = false;
      } else {
        media.alt = "";
        media.decoding = "async";
      }

      media.id = "media";
      media.src = data.url;
      const mediaWrap = document.createElement("div");
      mediaWrap.id = "media-wrap";
      mediaWrap.appendChild(media);
      stage.replaceChildren(mediaWrap);
      addHint();
      stage.scrollLeft = 0;
      stage.scrollTop = 0;
      status.textContent = `${data.total} matching`;

      const readyEvent = media.tagName === "VIDEO" ? "loadedmetadata" : "load";
      media.addEventListener(
        readyEvent,
        () => applySizeMode(media, sizeMode === "native"),
        { once: true },
      );
      if (
        (media.tagName === "IMG" && media.complete && media.naturalWidth > 0) ||
        (media.tagName === "VIDEO" && media.readyState >= 1 && media.videoWidth > 0)
      ) {
        applySizeMode(media, sizeMode === "native");
      }
      if (media.tagName === "VIDEO") media.play().catch(() => {});
    } catch (problem) {
      error.textContent = `${problem.message} Tap Next random to try again.`;
      error.style.display = "block";
      status.textContent = "Error";
    } finally {
      loading = false;
      next.disabled = false;
    }
  }


  function setSourceBusy(busy) {
    sourceAdd.disabled = busy;
    sourceClose.disabled = busy;
    sourceAdd.textContent = busy ? "Adding…" : "Add";
  }

  function openSourceDialog() {
    sourceFeedback.textContent = "";
    sourceInput.value = "";
    sourceDialog.showModal();
    window.setTimeout(() => sourceInput.focus(), 0);
  }

  function closeSourceDialog() {
    if (sourceDialog.open) sourceDialog.close();
  }

  const SOURCE_RESULT_MESSAGES = Object.freeze({
    added: "Added. Yoink will use it next run.",
    exists: "That subreddit is already added.",
    invalid: "Enter a subreddit name such as pics, r/pics, or a Reddit subreddit URL.",
    full: "The private source list is full.",
    conflict: "The source list changed at the same moment. Please tap Add once more.",
    unavailable: "The private source list is temporarily unavailable.",
    security: "The page security token was refreshed. Tap Add once more.",
  });

  function showSourceResult() {
    const currentUrl = new URL(window.location.href);
    const result = currentUrl.searchParams.get("source_result");
    if (!Object.hasOwn(SOURCE_RESULT_MESSAGES, result)) return;

    currentUrl.searchParams.delete("source_result");
    window.history.replaceState(
      null,
      "",
      `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`,
    );
    sourceFeedback.textContent = SOURCE_RESULT_MESSAGES[result];
    sourceInput.value = "";
    sourceDialog.showModal();
  }

  function prepareSourceSubmission(event) {
    const subreddit = sourceInput.value.trim();
    if (!subreddit) {
      event.preventDefault();
      sourceFeedback.textContent = "Type a subreddit name first.";
      sourceInput.focus();
      return;
    }

    sourceInput.value = subreddit;
    sourceFeedback.textContent = "Adding…";
    setSourceBusy(true);
  }

  next.addEventListener("click", loadRandom);
  addSourceOpen.addEventListener("click", openSourceDialog);
  sourceClose.addEventListener("click", closeSourceDialog);
  sourceForm.addEventListener("submit", prepareSourceSubmission);
  sourceDialog.addEventListener("click", (event) => {
    if (event.target === sourceDialog) closeSourceDialog();
  });
  filter.addEventListener("change", () => {
    showHint = false;
    loadRandom();
  });
  stage.addEventListener("click", (event) => {
    if (event.target.id !== "media") return;
    if (mobileQuery.matches) {
      showHint = false;
      loadRandom();
      return;
    }
    sizeMode = sizeMode === "fit" ? "native" : "fit";
    applySizeMode(event.target, sizeMode === "native");
  });

  function reapplyCurrentSize() {
    const media = document.getElementById("media");
    if (media) applySizeMode(media, false);
  }

  function scheduleSizeRefresh() {
    if (resizeFrame) window.cancelAnimationFrame(resizeFrame);
    resizeFrame = window.requestAnimationFrame(() => {
      resizeFrame = 0;
      reapplyCurrentSize();
    });
  }

  window.addEventListener("resize", scheduleSizeRefresh);
  window.addEventListener("orientationchange", scheduleSizeRefresh);
  window.addEventListener("pageshow", () => {
    setSourceBusy(false);
    scheduleSizeRefresh();
  });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", scheduleSizeRefresh);
  }
  if ("ResizeObserver" in window) {
    new ResizeObserver(scheduleSizeRefresh).observe(stage);
  }
  mobileQuery.addEventListener("change", scheduleSizeRefresh);
  document.addEventListener("fullscreenchange", scheduleSizeRefresh);
  document.addEventListener("keydown", (event) => {
    if (sourceDialog.open) return;
    if (event.code === "Space") {
      event.preventDefault();
      showHint = false;
      loadRandom();
    } else if (event.key.toLowerCase() === "f") {
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      else document.documentElement.requestFullscreen().catch(() => {});
    }
  });

  showSourceResult();
  loadRandom();
})();
