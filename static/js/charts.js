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
      const money = (v) => currency + v.toLocaleString("es-DO", { minimumFractionDigits: 2 });
      // data-type="bar": series = [{name, data: [...]}, ...] por mes (reportes del negocio).
      const options = el.dataset.type === "bar"
        ? {
            chart: { type: "bar", height: 260, fontFamily: "inherit", toolbar: { show: false }, animations: { enabled: false } },
            series: data.series,
            xaxis: { categories: data.labels },
            colors: ["#1f3a73", "#1a9c8f", "#d9a441"],
            plotOptions: { bar: { columnWidth: "60%" } },
            yaxis: { labels: { formatter: (v) => currency + Math.round(v).toLocaleString("es-DO") } },
            legend: { position: "bottom" },
            dataLabels: { enabled: false },
            tooltip: { y: { formatter: money } },
          }
        : {
            chart: { type: "donut", height: 220, fontFamily: "inherit" },
            series: data.series,
            labels: data.labels,
            colors: ["#1f3a73", "#1a9c8f", "#4fba8a", "#d9a441", "#d2553f"],
            legend: { position: "bottom" },
            dataLabels: { enabled: false },
            tooltip: { y: { formatter: money } },
          };
      const chart = new ApexCharts(el, options);
      chart.render();
      el.dataset.rendered = "1";
    });
  }
  document.addEventListener("DOMContentLoaded", render);
  document.addEventListener("htmx:afterSettle", render);
})();
