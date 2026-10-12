/* Componentes Alpine (build CSP: sin eval; las expresiones solo nombran propiedades y métodos). */
document.addEventListener("alpine:init", () => {
  // Menú del botón flotante "+ Registrar".
  Alpine.data("menu", () => ({
    open: false,
    toggle() { this.open = !this.open; },
    close() { this.open = false; },
  }));

  // Dictado por voz: graba, envía al servidor para transcribir y escribe el texto en un campo.
  Alpine.data("voiceRecorder", () => ({
    recording: false,
    busy: false,
    error: "",
    recorder: null,
    chunks: [],
    get supported() { return !!(navigator.mediaDevices && window.MediaRecorder); },
    get label() {
      if (this.busy) return "Transcribiendo…";
      return this.recording ? "Detener y transcribir" : "Dictar";
    },
    async toggle() {
      if (this.recording) { this.recorder.stop(); return; }
      this.error = "";
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.chunks = [];
        this.recorder = new MediaRecorder(stream);
        this.recorder.ondataavailable = (e) => this.chunks.push(e.data);
        this.recorder.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          this.recording = false;
          this.send();
        };
        this.recorder.start();
        this.recording = true;
      } catch (e) {
        this.error = "No pudimos usar el micrófono.";
      }
    },
    async send() {
      this.busy = true;
      const blob = new Blob(this.chunks, { type: this.recorder.mimeType || "audio/webm" });
      const body = new FormData();
      body.append("audio", blob, "nota.webm");
      try {
        const response = await fetch(this.$el.dataset.url, {
          method: "POST",
          body,
          headers: { "X-CSRFToken": window.crecenta.csrf() },
          credentials: "same-origin",
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Error");
        const target = document.getElementById(this.$el.dataset.target);
        target.value = data.texto;
        const via = document.getElementById(this.$el.dataset.via || "");
        if (via) via.value = "voz";
        target.dispatchEvent(new Event("input"));
      } catch (e) {
        this.error = e.message || "No se pudo transcribir.";
      } finally {
        this.busy = false;
      }
    },
  }));
});

window.crecenta = {
  csrf() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  },
};

// htmx envía el token CSRF en cada petición.
document.addEventListener("htmx:configRequest", (event) => {
  event.detail.headers["X-CSRFToken"] = window.crecenta.csrf();
});

/* ---------------------------------------------------------------- PWA y modo sin conexión */
(function () {
  const sw = "serviceWorker" in navigator ? navigator.serviceWorker : null;

  if (sw) {
    window.addEventListener("load", () => {
      sw.register("/sw.js", { scope: "/" }).catch(() => {});
    });
  }

  // Un client_uuid nuevo cada vez que se muestra un formulario (también al volver atrás):
  // dos movimientos distintos nunca comparten id; un doble toque sí, y no se duplica.
  function refreshClientIds() {
    if (!(window.crypto && crypto.randomUUID)) return;
    document.querySelectorAll('input[name="client_uuid"]').forEach((input) => {
      input.value = crypto.randomUUID();
    });
  }

  async function pendingCount() {
    try {
      return await self.CrecentaQueue.count();
    } catch (e) {
      return 0;
    }
  }

  function setBanner(text) {
    const banner = document.getElementById("estado-red");
    if (!banner) return;
    banner.textContent = text;
    banner.classList.toggle("hidden", !text);
  }

  async function refreshStatus(extra) {
    const pending = await pendingCount();
    document.querySelectorAll("[data-pending-count]").forEach((el) => { el.textContent = pending; });
    if (!navigator.onLine) {
      setBanner("Sin conexión: tus gastos se guardan en el teléfono y se enviarán al reconectar."
        + (pending ? ` Pendientes: ${pending}.` : ""));
    } else if (extra) {
      setBanner(extra);
    } else if (pending) {
      setBanner(`Enviando ${pending} movimiento(s) guardado(s) sin conexión…`);
    } else {
      setBanner("");
    }
  }

  function requestFlush() {
    if (sw && sw.controller && navigator.onLine) {
      sw.controller.postMessage({ type: "flush", csrf: window.crecenta.csrf() });
    }
  }

  window.addEventListener("pageshow", () => {
    refreshClientIds();
    refreshStatus();
    requestFlush();
  });
  window.addEventListener("online", () => { refreshStatus(); requestFlush(); });
  window.addEventListener("offline", () => refreshStatus());

  if (sw) {
    sw.addEventListener("message", (event) => {
      const data = event.data || {};
      if (data.type === "synced" && data.count) {
        refreshStatus(`Listo: enviamos ${data.count} movimiento(s) que guardaste sin conexión.`);
      } else {
        refreshStatus();
      }
    });
    sw.addEventListener("controllerchange", requestFlush);
  }

  // Al cerrar sesión se borran las páginas guardadas para uso sin conexión.
  document.addEventListener("submit", (event) => {
    if (event.target.matches("form[data-logout]") && sw && sw.controller) {
      sw.controller.postMessage({ type: "logout" });
    }
  });
})();
