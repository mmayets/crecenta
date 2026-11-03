(() => {
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
    if (window.matchMedia("(min-width: 768px)").matches) new bootstrap.Tooltip(el);
  });

  const modalEl = document.getElementById("cmdk");
  if (!modalEl) return;
  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  const input = document.getElementById("cmdk-input");
  const box = document.getElementById("cmdk-results");
  let activo = -1, timer;

  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); modal.show(); }
  });
  modalEl.addEventListener("shown.bs.modal", () => input.focus());

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const pintar = (items) => {
    activo = -1;
    if (!items.length) { box.innerHTML = '<div class="empty px-2">Sin resultados.</div>'; return; }
    box.innerHTML = items.map((r) => {
      const tag = r.url ? `a href="${esc(r.url)}" target="_blank" rel="noopener"` : "div";
      return `<${tag} class="cmdk-item"><span class="rail-app bg-app-${esc(r.color)}"><i class="bi bi-${esc(r.icono)}"></i></span>
        <span class="flex-grow-1"><span class="d-block fw-medium">${esc(r.titulo)}</span><span class="task-app">${esc(r.detalle)}</span></span>
        <span class="task-app">${esc(r.tipo)}</span></${tag.split(" ")[0]}>`;
    }).join("");
  };

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) { box.innerHTML = '<div class="empty px-2">Escribe para buscar.</div>'; return; }
    timer = setTimeout(async () => {
      const r = await fetch(`${box.dataset.url}?q=${encodeURIComponent(q)}`, { headers: { Accept: "application/json" } });
      if (r.ok) pintar((await r.json()).resultados);
    }, 150);
  });

  input.addEventListener("keydown", (e) => {
    const items = box.querySelectorAll(".cmdk-item");
    if (!items.length || !["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) return;
    if (e.key === "Enter" && activo >= 0) { e.preventDefault(); items[activo].click(); return; }
    if (e.key === "Enter") return;
    e.preventDefault();
    activo = (activo + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((el, i) => el.classList.toggle("active", i === activo));
    items[activo].scrollIntoView({ block: "nearest" });
  });
})();
