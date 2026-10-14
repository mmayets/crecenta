/* Componentes Alpine (build CSP: sin eval; las expresiones solo nombran propiedades y métodos). */
document.addEventListener("alpine:init", () => {
  // Menú del botón flotante "+ Registrar".
  Alpine.data("menu", () => ({
    open: false,
    toggle() { this.open = !this.open; },
    close() { this.open = false; },
  }));

  // Precios de la página de inicio: mensual o anual.
  Alpine.data("precios", () => ({
    periodo: "mensual",
    get esMensual() { return this.periodo === "mensual"; },
    get esAnual() { return this.periodo === "anual"; },
    get mensualClase() { return this.esMensual ? "bg-marca-700 text-white" : "text-slate-600"; },
    get anualClase() { return this.esAnual ? "bg-marca-700 text-white" : "text-slate-600"; },
    mensual() { this.periodo = "mensual"; },
    anual() { this.periodo = "anual"; },
  }));

  // Activar o desactivar las notificaciones push (Configuración).
  Alpine.data("notificacionesPush", () => ({
    estado: "cargando",
    mensaje: "",
    async init() { this.estado = await window.crecenta.push.estado(); },
    get activo() { return this.estado === "activo"; },
    get inactivo() { return this.estado === "inactivo"; },
    get bloqueado() { return this.estado === "bloqueado"; },
    get noSoportado() { return this.estado === "no_soportado"; },
    async activar() {
      this.mensaje = "";
      try {
        await window.crecenta.push.activar(this.$root.dataset);
        this.mensaje = "Listo: te avisaremos en este dispositivo.";
      } catch (e) {
        this.mensaje = e.message || "No se pudieron activar.";
      }
      this.estado = await window.crecenta.push.estado();
    },
    async desactivar() {
      await window.crecenta.push.desactivar(this.$root.dataset);
      this.mensaje = "Desactivadas en este dispositivo.";
      this.estado = await window.crecenta.push.estado();
    },
    async probar() {
      const ok = await window.crecenta.push.probar(this.$root.dataset);
      this.mensaje = ok ? "Te enviamos una notificación de prueba." : "No se pudo enviar la prueba.";
    },
  }));

  // Escanear el QR de una factura con la cámara (BarcodeDetector o, si no existe, jsQR).
  Alpine.data("lectorQR", () => ({
    abierto: false,
    error: "",
    stream: null,
    detector: null,
    buscando: false,
    get soportado() { return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia); },
    async abrir() {
      this.error = "";
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      } catch (e) {
        this.error = "No pudimos usar la cámara. Revisa el permiso o sube una foto de la factura.";
        return;
      }
      this.abierto = true;
      this.detector = window.crecenta.qrDetector();
      const video = this.$refs.video;
      video.srcObject = this.stream;
      try { await video.play(); } catch (e) { /* algunos navegadores ya reproducen */ }
      this.buscando = true;
      this.buscar();
    },
    cerrar() {
      this.buscando = false;
      this.abierto = false;
      if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    },
    async buscar() {
      if (!this.buscando) return;
      const texto = await window.crecenta.leerQR(this.$refs.video, this.detector);
      if (texto) {
        this.cerrar();
        this.$refs.texto.value = texto;
        this.$refs.formulario.submit();
        return;
      }
      setTimeout(() => this.buscar(), 250);
    },
  }));

  // Al elegir la foto de una factura, busca su QR para leer número y total sin errores.
  Alpine.data("fotoConQR", () => ({
    aviso: "",
    async revisar() {
      const archivo = this.$refs.archivo.files && this.$refs.archivo.files[0];
      this.aviso = "";
      this.$refs.qr.value = "";
      if (!archivo || !archivo.type.startsWith("image/")) return;
      const texto = await window.crecenta.leerQRDeArchivo(archivo);
      if (texto) {
        this.$refs.qr.value = texto;
        this.aviso = "Encontramos el código QR de la factura: lo usaremos para el número y el total.";
      }
    },
  }));

  // Tira del asistente bajo la cabecera: se puede ocultar hasta que cambie la recomendación.
  Alpine.data("tira", () => ({
    hidden: false,
    init() {
      try { this.hidden = sessionStorage.getItem("asistente-tira") === this.$el.dataset.key; } catch (e) { /* sin almacenamiento */ }
    },
    get shown() { return !this.hidden; },
    dismiss() {
      this.hidden = true;
      try { sessionStorage.setItem("asistente-tira", this.$el.dataset.key); } catch (e) { /* sin almacenamiento */ }
    },
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
  qrDetector() {
    if (!("BarcodeDetector" in window)) return null;
    try { return new window.BarcodeDetector({ formats: ["qr_code"] }); } catch (e) { return null; }
  },
  // Devuelve el texto del primer QR que encuentre en un video, imagen o ImageBitmap ("" si no hay).
  async leerQR(fuente, detector) {
    try {
      if (detector) {
        const codigos = await detector.detect(fuente);
        return codigos.length ? codigos[0].rawValue : "";
      }
      if (!window.jsQR) return "";
      const ancho = fuente.videoWidth || fuente.width;
      const alto = fuente.videoHeight || fuente.height;
      if (!ancho || !alto) return "";
      const escala = Math.min(1, 1000 / Math.max(ancho, alto));
      const lienzo = document.createElement("canvas");
      lienzo.width = Math.round(ancho * escala);
      lienzo.height = Math.round(alto * escala);
      const ctx = lienzo.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(fuente, 0, 0, lienzo.width, lienzo.height);
      const imagen = ctx.getImageData(0, 0, lienzo.width, lienzo.height);
      const codigo = window.jsQR(imagen.data, imagen.width, imagen.height);
      return codigo ? codigo.data : "";
    } catch (e) {
      return "";
    }
  },
  push: {
    clave() {
      const meta = document.querySelector('meta[name="vapid-key"]');
      return meta ? meta.content : "";
    },
    soportado() {
      return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window
        && !!this.clave();
    },
    async enviar(url, datos) {
      return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": window.crecenta.csrf() },
        body: JSON.stringify(datos || {}),
      });
    },
    bytes(base64) {
      const relleno = "=".repeat((4 - (base64.length % 4)) % 4);
      const crudo = atob((base64 + relleno).replace(/-/g, "+").replace(/_/g, "/"));
      return Uint8Array.from(crudo, (c) => c.charCodeAt(0));
    },
    async estado() {
      if (!this.soportado()) return "no_soportado";
      if (Notification.permission === "denied") return "bloqueado";
      const registro = await navigator.serviceWorker.ready;
      return (await registro.pushManager.getSubscription()) ? "activo" : "inactivo";
    },
    async activar(urls) {
      if ((await Notification.requestPermission()) !== "granted") {
        throw new Error("No diste permiso para mostrar notificaciones.");
      }
      const registro = await navigator.serviceWorker.ready;
      const suscripcion = await registro.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: this.bytes(this.clave()),
      });
      const respuesta = await this.enviar(urls.suscribir, suscripcion.toJSON());
      if (!respuesta.ok) throw new Error("No pudimos guardar la suscripción.");
    },
    async desactivar(urls) {
      const registro = await navigator.serviceWorker.ready;
      const suscripcion = await registro.pushManager.getSubscription();
      if (!suscripcion) return;
      await this.enviar(urls.cancelar, { endpoint: suscripcion.endpoint });
      await suscripcion.unsubscribe();
    },
    async probar(urls) {
      return (await this.enviar(urls.prueba)).ok;
    },
  },
  async leerQRDeArchivo(archivo) {
    let imagen = null;
    try { imagen = await createImageBitmap(archivo); } catch (e) { return ""; }
    return this.leerQR(imagen, this.qrDetector());
  },
};

// htmx envía el token CSRF en cada petición.
document.addEventListener("htmx:configRequest", (event) => {
  event.detail.headers["X-CSRFToken"] = window.crecenta.csrf();
});

// Chat del asistente: muestra siempre el último mensaje y deja el cursor listo para escribir.
function scrollChats(event) {
  document.querySelectorAll("[data-scroll-bottom]").forEach((el) => { el.scrollTop = el.scrollHeight; });
  // Solo tras un turno del propio chat (otros intercambios de htmx no deben mover el cursor).
  const chat = event && event.type === "htmx:afterSettle" && event.target.closest
    ? event.target.closest("#asistente, #sophia")
    : null;
  const input = chat ? chat.querySelector("textarea") : null;
  if (input) input.focus();
}
// Cualquier control con data-open-assistant abre el panel flotante del asistente.
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-open-assistant]")) {
    window.dispatchEvent(new CustomEvent("abrir-asistente"));
  }
});

// Formularios que se vacían al enviarse bien (la pregunta al asistente).
document.addEventListener("htmx:afterRequest", (event) => {
  const form = event.target;
  if (form.matches && form.matches("form[data-reset]") && event.detail.successful) form.reset();
});
document.addEventListener("DOMContentLoaded", scrollChats);
document.addEventListener("htmx:afterSettle", scrollChats);

/* ---------------------------------------------------------------- PWA y modo sin conexión */
// La app instalada no muestra la página de inicio pública: va directo a iniciar sesión.
(function () {
  const landing = document.querySelector("[data-landing]");
  if (landing && window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) {
    window.location.replace(landing.dataset.loginUrl);
  }
})();

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
      setBanner(`Enviando ${pending} registro(s) guardado(s) sin conexión…`);
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
