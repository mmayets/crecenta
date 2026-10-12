/* Gráficos con ApexCharts. Los datos vienen de <script type="application/json"> (compatible con
   la CSP: no hay JavaScript en línea). */
(function () {
  function render() {
    document.querySelectorAll("[data-chart]").forEach((el) => {
      if (el.dataset.rendered) return;
      const source = document.getElementById(el.dataset.chart);
      if (!source || !window.ApexCharts) return;
      const data = JSON.parse(source.textContent);
      if (!data.series || !data.series.length) return;
      const currency = el.dataset.currency === "USD" ? "US$" : "RD$";
      const chart = new ApexCharts(el, {
        chart: { type: "donut", height: 220, fontFamily: "inherit" },
        series: data.series,
        labels: data.labels,
        colors: ["#0f766e", "#f59e0b", "#6366f1", "#ef4444"],
        legend: { position: "bottom" },
        dataLabels: { enabled: false },
        tooltip: {
          y: { formatter: (v) => currency + v.toLocaleString("es-DO", { minimumFractionDigits: 2 }) },
        },
      });
      chart.render();
      el.dataset.rendered = "1";
    });
  }
  document.addEventListener("DOMContentLoaded", render);
  document.addEventListener("htmx:afterSettle", render);
})();
