/* Cola de movimientos registrados sin conexión (IndexedDB). La usan la página y el service worker.
   Cada movimiento se guarda con su client_uuid como clave: guardarlo dos veces no lo duplica. */
(function (scope) {
  const DB = "crecenta";
  const STORE = "pendientes";

  function open() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB, 1);
      request.onupgradeneeded = () => {
        request.result.createObjectStore(STORE, { keyPath: "client_uuid" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function run(mode, action) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const result = action(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(result && "result" in result ? result.result : undefined);
      tx.onerror = () => reject(tx.error);
    });
  }

  scope.CrecentaQueue = {
    add: (item) => run("readwrite", (s) => s.put(item)),
    all: () => run("readonly", (s) => s.getAll()),
    count: () => run("readonly", (s) => s.count()),
    remove: (id) => run("readwrite", (s) => s.delete(id)),
    async markError(id, errors) {
      const items = await scope.CrecentaQueue.all();
      const item = items.find((i) => i.client_uuid === id);
      if (item) {
        item.error = errors;
        await scope.CrecentaQueue.add(item);
      }
    },
  };
})(self);
