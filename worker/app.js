(() => {
  const stage = document.getElementById("stage");
  const next = document.getElementById("next");
  const filter = document.getElementById("filter");
  const status = document.getElementById("status");
  const error = document.getElementById("error");
  const mobileQuery = window.matchMedia("(max-width: 700px)");
  let loading = false;
  let sizeMode = "fit";
  let showHint = true;

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
      media.style.width = "100%";
      media.style.height = "100%";
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
      const response = await fetch(`/api/random?ext=${encodeURIComponent(filter.value)}`, {
        cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load media.");

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
      error.textContent = problem.message;
      error.style.display = "block";
      status.textContent = "Error";
    } finally {
      loading = false;
      next.disabled = false;
    }
  }

  next.addEventListener("click", loadRandom);
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

  window.addEventListener("resize", reapplyCurrentSize);
  mobileQuery.addEventListener("change", reapplyCurrentSize);
  document.addEventListener("fullscreenchange", reapplyCurrentSize);
  document.addEventListener("keydown", (event) => {
    if (event.code === "Space") {
      event.preventDefault();
      showHint = false;
      loadRandom();
    } else if (event.key.toLowerCase() === "f") {
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      else document.documentElement.requestFullscreen().catch(() => {});
    }
  });

  loadRandom();
})();
