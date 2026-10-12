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
