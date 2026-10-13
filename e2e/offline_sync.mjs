// Prueba E2E del criterio de aceptación de la PWA:
// "registrar un gasto sin conexión que se sincroniza al reconectar sin duplicarse", y lo mismo
// con las ventas de una vendedora (Fase 4).
//
// Uso: make e2e   (prepara el usuario, levanta el servidor en :8766 y ejecuta esta prueba)
import { spawn } from "node:child_process";
import { createRequire } from "node:module";

// Permite que Playwright vea (y corte) la red del service worker, no solo la de la página.
process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS = "1";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const BASE = process.env.E2E_BASE || "http://localhost:8766";
const { email, password, ws, seller, business } = JSON.parse(process.argv[2]);

function check(condition, message) {
  if (!condition) throw new Error("FALLA: " + message);
  console.log("ok -", message);
}

async function waitForServer() {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(BASE + "/salud/")).ok) return;
    } catch (e) { /* aún no arranca */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("El servidor no respondió");
}

const server = process.env.E2E_BASE
  ? null
  : spawn("uv", ["run", "python", "manage.py", "runserver", "8766", "--noreload"], {
      stdio: "ignore",
    });

let browser;
try {
  await waitForServer();
  browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  // 1. Inicio de sesión y primera visita en línea (instala el service worker y guarda la página).
  await page.goto(BASE + "/cuenta/login/");
  await page.fill("input[name=login]", email);
  await page.fill("input[name=password]", password);
  await page.click("button[type=submit]");
  await page.waitForLoadState("networkidle");
  const newUrl = `${BASE}/e/${ws}/movimientos/nuevo/`;
  await page.goto(newUrl);
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload(); // ahora la página está controlada por el service worker
  await page.waitForLoadState("networkidle");
  check(await page.evaluate(() => !!navigator.serviceWorker.controller), "service worker activo");

  // 2. Sin conexión: la página abre desde la caché y el gasto se guarda en el teléfono.
  //    Se corta la red de la página y la del service worker.
  const cutNetwork = (route) => route.abort("internetdisconnected");
  await context.route("**/*", cutNetwork);
  await context.setOffline(true);
  await page.reload();
  check((await page.textContent("#estado-red")).includes("Sin conexión"), "aviso de sin conexión");

  async function registrar(amount, note) {
    await page.goto(newUrl);
    await page.fill("input[name=amount]", amount);
    await page.selectOption("select[name=category]", { label: "Alimentación · Esenciales variables" });
    await page.fill("input[name=description]", note);
    await Promise.all([page.waitForURL("**/sin-conexion/guardado/"), page.click("button:has-text('Guardar')")]);
  }
  await registrar("275", "Colmado sin señal");
  check((await page.textContent("h1")).includes("Lo guardamos en tu teléfono"), "confirmación offline");
  await registrar("125", "Guagua sin señal");
  const queued = await page.evaluate(() => self.CrecentaQueue.all());
  check(queued.length === 2, "dos movimientos en la cola local");
  check(queued[0].client_uuid !== queued[1].client_uuid, "cada movimiento tiene su propio client_uuid");

  // 3. Reconexión: la cola se envía sola y queda vacía.
  await context.unroute("**/*", cutNetwork);
  await context.setOffline(false);
  await page.goto(`${BASE}/e/${ws}/`);
  await page.waitForFunction(async () => (await self.CrecentaQueue.count()) === 0, null, { timeout: 15000 });
  check(true, "la cola se vació al reconectar");

  // 4. Reenviar lo mismo (p. ej. un reintento) no duplica.
  await page.evaluate(async (item) => {
    await self.CrecentaQueue.add(item);
    navigator.serviceWorker.controller.postMessage({
      type: "flush",
      csrf: document.querySelector('meta[name="csrf-token"]').content,
    });
  }, queued[0]);
  await page.waitForFunction(async () => (await self.CrecentaQueue.count()) === 0, null, { timeout: 15000 });

  await page.goto(`${BASE}/e/${ws}/movimientos/`);
  const html = await page.content();
  const times = (text) => html.split(text).length - 1;
  check(times("Colmado sin señal") === 1, "el gasto de RD$275 aparece una sola vez");
  check(times("Guagua sin señal") === 1, "el gasto de RD$125 aparece una sola vez");

  // 5. Ventas sin conexión de una vendedora.
  const sellerContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const sp = await sellerContext.newPage();
  sp.on("pageerror", (e) => errors.push(e.message));
  await sp.goto(BASE + "/cuenta/login/");
  await sp.fill("input[name=login]", seller);
  await sp.fill("input[name=password]", password);
  await sp.click("button[type=submit]");
  await sp.waitForLoadState("networkidle");
  const saleUrl = `${BASE}/e/${business}/ventas/nueva/`;
  await sp.goto(saleUrl);
  await sp.evaluate(() => navigator.serviceWorker.ready);
  await sp.reload();
  await sp.waitForLoadState("networkidle");
  check(await sp.evaluate(() => !!navigator.serviceWorker.controller), "service worker de la vendedora");
  await sellerContext.route("**/*", cutNetwork);
  await sellerContext.setOffline(true);

  async function vender(qty, note) {
    await sp.goto(saleUrl);
    await sp.selectOption("select[name=producto_1]", { label: "Refresco" });
    await sp.fill("input[name=cantidad_1]", qty);
    await sp.fill("input[name=note]", note);
    await Promise.all([sp.waitForURL("**/sin-conexion/guardado/"), sp.click("button:has-text('Guardar venta')")]);
  }
  await vender("2", "Venta sin señal A");
  await vender("3", "Venta sin señal B");
  const sales = await sp.evaluate(() => self.CrecentaQueue.all());
  check(sales.length === 2 && sales.every((i) => i.form), "dos ventas en la cola local");

  await sellerContext.unroute("**/*", cutNetwork);
  await sellerContext.setOffline(false);
  await sp.goto(`${BASE}/e/${business}/`);
  await sp.waitForFunction(async () => (await self.CrecentaQueue.count()) === 0, null, { timeout: 15000 });
  check(true, "las ventas se enviaron al reconectar");
  await sp.evaluate(async (item) => {
    await self.CrecentaQueue.add(item);
    navigator.serviceWorker.controller.postMessage({
      type: "flush",
      csrf: document.querySelector('meta[name="csrf-token"]').content,
    });
  }, sales[0]);
  await sp.waitForFunction(async () => (await self.CrecentaQueue.count()) === 0, null, { timeout: 15000 });
  await sp.goto(`${BASE}/e/${business}/ventas/`);
  const salesHtml = await sp.content();
  check(salesHtml.split("2 Refresco").length - 1 === 1, "la venta de 2 aparece una sola vez");
  check(salesHtml.split("3 Refresco").length - 1 === 1, "la venta de 3 aparece una sola vez");
  check(salesHtml.includes("RD$375.00"), "el total del mes cuadra (5 × RD$75)");

  check(errors.length === 0, "sin errores de JavaScript: " + errors.join("; "));
  console.log("\nPRUEBA E2E SUPERADA");
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  if (server) server.kill();
}
