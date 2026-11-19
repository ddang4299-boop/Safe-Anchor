/* OGK dashboard — tiện ích nhỏ (không inline script để tuân CSP script-src 'self').
   - Vẽ biểu đồ Chart.js (tự lưu trên server) từ <figure class="chart" data-chart='{...}'>: cột/thanh bo tròn đầu,
     tô gradient. Vẽ được => thêm lớp has-chart để ẩn biểu đồ CSS dự phòng; lỗi/không có JS => giữ dự phòng.
   - Đếm ngược mã ghép, chip lời nhắn, tự gửi form chọn người giám hộ, thông báo lỗi thân thiện cho HTMX. */
(function () {
  "use strict";

  var PALETTE = {
    indigo: ["#A5B4FC", "#6366F1"], grape: ["#C4B5FD", "#8B5CF6"], mint: ["#6EE7B7", "#10B981"],
    blue: ["#93C5FD", "#3B82F6"], sun: ["#FDE68A", "#FBBF24"], coral: ["#FDBA74", "#F97362"]
  };
  var TODAY = ["#FFB088", "#FF8E53"];
  var ROUND = { family: "Nunito, Inter, 'Segoe UI', sans-serif", weight: "800", size: 12 };

  function gradient(chart, colors, horizontal) {
    var a = chart.chartArea;
    if (!a) return colors[1];
    var g = horizontal ? chart.ctx.createLinearGradient(a.left, 0, a.right, 0)
                       : chart.ctx.createLinearGradient(0, a.bottom, 0, a.top);
    g.addColorStop(0, colors[0]);
    g.addColorStop(1, colors[1]);
    return g;
  }

  function buildChart(fig, animate) {
    if (!window.Chart) return;
    var cfg;
    try { cfg = JSON.parse(fig.getAttribute("data-chart")); } catch (e) { return; }
    var values = cfg.values || [];
    if (!values.length || !values.some(function (v) { return v > 0; })) return; // không có dữ liệu: giữ phần dự phòng
    var canvas = fig.querySelector("canvas");
    var old = window.Chart.getChart(canvas);
    if (old) old.destroy();

    window.Chart.defaults.font.family = "Inter, 'Segoe UI', system-ui, sans-serif";
    window.Chart.defaults.color = "#64748B";
    var unit = cfg.unit ? " " + cfg.unit : "";
    var base = {
      responsive: true, maintainAspectRatio: false,
      animation: animate ? { duration: 800, easing: "easeOutQuart" } : false,
      layout: { padding: { top: 6 } },
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: "#1E1B4B", padding: 12, cornerRadius: 12, displayColors: false, titleFont: ROUND, bodyFont: ROUND,
                   callbacks: { label: function (c) { return " " + c.formattedValue + unit; } } }
      }
    };
    var type, data, options;
    if (cfg.kind === "doughnut") {
      type = "doughnut";
      data = { labels: cfg.labels, datasets: [{ data: values, backgroundColor: cfg.colors || [], borderWidth: 0,
                                                 borderRadius: 10, spacing: 4, hoverOffset: 8 }] };
      options = Object.assign(base, { cutout: "66%" });
      options.plugins.legend = { display: true, position: "bottom",
        labels: { usePointStyle: true, pointStyle: "circle", boxWidth: 8, padding: 14, font: ROUND, color: "#334155" } };
    } else {
      var horizontal = cfg.kind === "hbar";
      var colors = PALETTE[cfg.palette] || PALETTE.indigo;
      var last = values.length - 1;
      type = "bar";
      data = { labels: cfg.labels, datasets: [{
        data: values, borderRadius: 999, borderSkipped: false,
        maxBarThickness: horizontal ? 20 : 44, barPercentage: horizontal ? 0.72 : 0.62, categoryPercentage: 0.9,
        backgroundColor: function (c) {
          var hl = !horizontal && c.dataIndex === last;   // cột cuối (hôm nay/tuần này) màu cam
          return gradient(c.chart, hl ? TODAY : colors, horizontal);
        }
      }] };
      var grid = { color: "rgba(99, 102, 241, .08)", drawTicks: false };
      var valueAxis = { beginAtZero: true, grid: grid, border: { display: false }, ticks: { padding: 8, maxTicksLimit: 5 } };
      var catAxis = { grid: { display: false }, border: { display: false }, ticks: { font: ROUND, color: "#1E1B4B", padding: 6 } };
      options = Object.assign(base, { indexAxis: horizontal ? "y" : "x",
                                      scales: horizontal ? { x: valueAxis, y: catAxis } : { y: valueAxis, x: catAxis } });
    }
    try {
      new window.Chart(canvas, { type: type, data: data, options: options });
      fig.classList.add("has-chart");
    } catch (e) { /* giữ biểu đồ CSS dự phòng */ }
  }

  function initCharts(root, animate) {
    root.querySelectorAll("figure.chart[data-chart]").forEach(function (f) { buildChart(f, animate); });
  }

  // Đếm ngược mã ghép 10 phút
  function initCountdowns(root) {
    root.querySelectorAll("[data-countdown]:not([data-started])").forEach(function (el) {
      el.setAttribute("data-started", "1");
      var left = parseInt(el.getAttribute("data-countdown"), 10);
      var timer = setInterval(function () {
        left -= 1;
        if (left <= 0) {
          clearInterval(timer);
          el.textContent = "Mã đã hết hạn — bấm “Tạo mã ghép” để lấy mã mới.";
          return;
        }
        var m = Math.floor(left / 60), s = left % 60;
        el.textContent = "Còn " + m + ":" + (s < 10 ? "0" : "") + s;
      }, 1000);
    });
  }

  document.addEventListener("click", function (e) {
    // Gợi ý lời nhắn dịu dàng: bấm chip để điền vào ô lời nhắn
    var chip = e.target.closest("[data-fill]");
    if (chip) {
      var box = document.getElementById(chip.getAttribute("data-fill"));
      if (box) { box.value = chip.textContent.trim(); box.focus(); }
    }
  });
  document.addEventListener("change", function (e) {
    if (e.target.matches("[data-autosubmit]")) e.target.form.submit();
  });

  document.addEventListener("DOMContentLoaded", function () { initCountdowns(document); initCharts(document, true); });
  document.addEventListener("htmx:afterSwap", function (e) { initCountdowns(e.target); initCharts(e.target, false); });
  // Lỗi mạng/HTTP: hiện thông báo thân thiện thay vì im lặng
  document.addEventListener("htmx:responseError", function (e) {
    var t = e.detail.target;
    if (t && e.detail.xhr.status !== 400) {
      t.innerHTML = '<div class="toast warn">Chưa gửi được (mã ' + e.detail.xhr.status + '). Thử lại sau giây lát nhé.</div>';
    }
  });
  document.addEventListener("htmx:beforeSwap", function (e) {
    if (e.detail.xhr.status === 400) { e.detail.shouldSwap = true; e.detail.isError = false; }
  });
})();
