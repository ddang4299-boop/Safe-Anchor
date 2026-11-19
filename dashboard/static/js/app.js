/* SafeAnchor dashboard — tiện ích nhỏ (không inline script để tuân CSP script-src 'self').
   - Vẽ biểu đồ Chart.js (tự lưu trên server) từ <figure class="chart" data-chart='{...}'>. Vẽ được => thêm lớp
     has-chart để ẩn biểu đồ CSS dự phòng; lỗi/không có JS => giữ dự phòng.
     Biểu đồ 7 ngày có ĐƯỜNG GIỚI HẠN đứt nét (plugin quotaLine) => thấy ngay ngày nào dùng vượt mức.
   - XEM CHI TIẾT KHI CẦN: bấm thẻ nhóm nội dung hoặc một lát biểu đồ tròn => mở bảng ứng dụng / trang web /
     nhật ký của đúng nhóm đó (mặc định ẩn). Không JS: thẻ là liên kết #cd-..., CSS :target vẫn mở được.
   - Thanh chọn hồ sơ con: đổi nội dung tại chỗ (không tải lại), phím ←/→/Home/End, cập nhật ?con= trên URL.
   - Đếm ngược mã ghép, chip lời nhắn, tự gửi form chọn người giám hộ, thông báo lỗi thân thiện cho HTMX. */
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  // [màu ở gốc cột, màu ở đỉnh cột] — cột thường: xanh SafeAnchor; cột hôm nay: cam (màu nhấn của ảnh mẫu)
  var PALETTE = {
    blue: ["#0070C9", "#3D9BE9"], navy: ["#000056", "#3B3BB0"], mint: ["#2E9E5B", "#6CCB8E"]
  };
  var TODAY = ["#F07A3A", "#F7A465"];
  var INK = "#00004A";
  var DISPLAY = "'Plus Jakarta Sans', Inter, 'Segoe UI', sans-serif";
  var LABEL_FONT = { family: DISPLAY, weight: "700", size: 12 };
  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function hm(m) {  // 260 -> "4h 20p" (giống bộ lọc |hm phía server)
    m = Math.round(m || 0);
    if (m < 60) return m + "p";
    var h = Math.floor(m / 60), r = m % 60;
    return h + "h" + (r ? " " + (r < 10 ? "0" : "") + r + "p" : "");
  }

  // Đường "giới hạn cho phép": một đoạn đứt nét ngang qua TỪNG cột ở mức hạn mức của ngày đó (ngày thường
  // và cuối tuần có thể khác nhau => đường có bậc), kèm nhãn ở mép trái.
  var quotaLine = {
    id: "quotaLine",
    afterDatasetsDraw: function (chart, args, opts) {
      var q = opts && opts.values;
      if (!q || !q.length) return;
      var x = chart.scales.x, y = chart.scales.y, ctx = chart.ctx, area = chart.chartArea;
      var n = q.length, step = (x.getPixelForValue(n - 1) - x.getPixelForValue(0)) / Math.max(n - 1, 1) || area.width;
      ctx.save();
      ctx.setLineDash([6, 5]);
      ctx.lineWidth = 2;
      ctx.strokeStyle = "rgba(0, 0, 86, .7)";
      ctx.beginPath();
      var prev = null;
      for (var i = 0; i < n; i++) {
        if (!q[i]) { prev = null; continue; }
        var cx = x.getPixelForValue(i), py = Math.round(y.getPixelForValue(q[i])) + .5;
        var x0 = Math.max(area.left, cx - step / 2), x1 = Math.min(area.right, cx + step / 2);
        if (prev !== null && prev !== py) { ctx.moveTo(x0, prev); ctx.lineTo(x0, py); }  // bậc nối hai mức
        ctx.moveTo(x0, py); ctx.lineTo(x1, py);
        prev = py;
      }
      ctx.stroke();
      ctx.setLineDash([]);
      var first = q[0];
      if (first) {  // nhãn "Giới hạn 1h 30p" ở mép trái, ngay trên đường (cột hôm nay ở mép phải không bị che)
        var label = "Giới hạn " + hm(first);
        ctx.font = "700 11px " + DISPLAY;
        var w = ctx.measureText(label).width + 14, ly = y.getPixelForValue(first) - 22, lx = area.left + 2;
        ctx.fillStyle = "#000056";
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(lx, ly, w, 18, 5); else ctx.rect(lx, ly, w, 18);
        ctx.fill();
        ctx.fillStyle = "#FFFFFF";
        ctx.textBaseline = "middle";
        ctx.fillText(label, lx + 7, ly + 9.5);
      }
      ctx.restore();
    }
  };

  // Chữ ở giữa biểu đồ tròn: tổng thời gian
  var centerText = {
    id: "centerText",
    afterDraw: function (chart, args, opts) {
      if (!opts || !opts.text) return;
      var meta = chart.getDatasetMeta(0);
      if (!meta.data.length) return;
      var c = meta.data[0], ctx = chart.ctx;
      ctx.save();
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = INK;
      ctx.font = "800 21px " + DISPLAY;
      ctx.fillText(opts.text, c.x, c.y - 8);
      ctx.fillStyle = "#687087";
      ctx.font = "600 11px Inter, sans-serif";
      ctx.fillText(opts.sub || "", c.x, c.y + 13);
      ctx.restore();
    }
  };

  function gradient(chart, colors, horizontal) {
    var a = chart.chartArea;
    if (!a) return colors[0];
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
    window.Chart.defaults.color = "#687087";
    var quota = cfg.quota || null;
    var unit = cfg.unit ? " " + cfg.unit : "";
    var base = {
      responsive: true, maintainAspectRatio: false,
      animation: animate && !REDUCED ? { duration: 800, easing: "easeOutQuart" } : false,
      layout: { padding: { top: 6 } },
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: "#000056", padding: 12, cornerRadius: 8, displayColors: false, titleFont: LABEL_FONT, bodyFont: LABEL_FONT,
                   footerFont: { family: "Inter, sans-serif", weight: "500", size: 11 }, footerColor: "#BFD9F2",
                   callbacks: {
                     label: function (c) { return " " + (cfg.unit === "phút" ? hm(c.raw) : c.formattedValue + unit); },
                     footer: function (items) {
                       if (cfg.kind === "doughnut") return cfg.keys ? "Bấm để xem chi tiết" : "";
                       if (!quota || !items.length) return "";
                       var i = items[0].dataIndex, q = quota[i], v = values[i];
                       if (!q) return "";
                       return v > q ? "Vượt giới hạn " + hm(v - q) + " (giới hạn " + hm(q) + ")" : "Trong giới hạn " + hm(q);
                     }
                   } },
        quotaLine: { values: quota },
        centerText: {}
      }
    };
    var type, data, options;
    if (cfg.kind === "doughnut") {
      type = "doughnut";
      data = { labels: cfg.labels, datasets: [{ data: values, backgroundColor: cfg.colors || [], borderWidth: 2, borderColor: "#FFFFFF",
                                                 borderRadius: 4, hoverOffset: 8 }] };
      var total = values.reduce(function (a, b) { return a + b; }, 0);
      options = Object.assign(base, { cutout: "68%" });
      options.plugins.centerText = { text: hm(total), sub: "7 ngày" };
      options.plugins.legend = { display: true, position: "bottom",
        labels: { usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10, padding: 12, font: { family: "Inter, sans-serif", weight: "500", size: 12 }, color: "#3F4659" } };
      if (cfg.keys && cfg.kid != null) {
        // lát biểu đồ / mục chú thích = lối vào bảng chi tiết của nhóm
        options.onClick = function (evt, els) { if (els.length) openCat(String(cfg.kid), cfg.keys[els[0].index], false); };
        options.onHover = function (evt, els) { evt.native.target.style.cursor = els.length ? "pointer" : "default"; };
        options.plugins.legend.onClick = function (evt, item) { openCat(String(cfg.kid), cfg.keys[item.index], false); };
      }
    } else {
      var horizontal = cfg.kind === "hbar";
      var colors = PALETTE[cfg.palette] || PALETTE.blue;
      var last = values.length - 1;
      type = "bar";
      data = { labels: cfg.labels, datasets: [{
        data: values, borderRadius: { topLeft: 6, topRight: 6, bottomLeft: 2, bottomRight: 2 }, borderSkipped: false,
        maxBarThickness: horizontal ? 18 : 28, barPercentage: horizontal ? 0.72 : 0.62, categoryPercentage: 0.9,
        backgroundColor: function (c) {
          var hl = !horizontal && c.dataIndex === last;   // cột cuối (hôm nay / tuần này) màu cam
          return gradient(c.chart, hl ? TODAY : colors, horizontal);
        }
      }] };
      var grid = { color: "rgba(0, 0, 86, .06)", drawTicks: false };
      var qmax = quota ? Math.max.apply(null, quota.map(function (q) { return q || 0; })) : 0;
      var valueAxis = { beginAtZero: true, grid: grid, border: { display: false }, ticks: { padding: 8, maxTicksLimit: 5 },
                        suggestedMax: qmax ? qmax * 1.18 : undefined };  // chừa chỗ cho đường giới hạn + nhãn
      var catAxis = { grid: { display: false }, border: { display: false }, ticks: { font: LABEL_FONT, color: INK, padding: 6 } };
      options = Object.assign(base, { indexAxis: horizontal ? "y" : "x",
                                      scales: horizontal ? { x: valueAxis, y: catAxis } : { y: valueAxis, x: catAxis } });
    }
    try {
      new window.Chart(canvas, { type: type, data: data, options: options, plugins: [quotaLine, centerText] });
      fig.classList.add("has-chart");
    } catch (e) { /* giữ biểu đồ CSS dự phòng */ }
  }

  function initCharts(root, animate) {
    root.querySelectorAll("figure.chart[data-chart]").forEach(function (f) {
      if (!f.closest("[hidden]")) buildChart(f, animate);  // phần đang ẩn: vẽ khi được chọn (đúng kích thước)
    });
  }

  // ---- xem chi tiết một nhóm nội dung (progressive disclosure) ----
  function closeCats(kid) {
    document.querySelectorAll('.cat-detail[id^="cd-' + kid + '-"]').forEach(function (x) { x.classList.remove("open"); });
    document.querySelectorAll('[data-cat^="' + kid + ':"]').forEach(function (c) { c.setAttribute("aria-expanded", "false"); });
  }
  function openCat(kid, key, toggle) {
    var d = document.getElementById("cd-" + kid + "-" + key);
    if (!d) return;
    var wasOpen = d.classList.contains("open");
    closeCats(kid);
    if (toggle && wasOpen) return;
    d.classList.add("open");
    var card = document.querySelector('[data-cat="' + kid + ":" + key + '"]');
    if (card) card.setAttribute("aria-expanded", "true");
    d.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "nearest" });
    try { d.focus({ preventScroll: true }); } catch (e) { /* bỏ qua */ }
  }

  // ---- thanh chọn hồ sơ con (WAI-ARIA tabs): bật/tắt mọi phần của con đó (dải số liệu + nội dung) ----
  function selectKid(id, focus) {
    var panel = document.getElementById("kid-" + id);
    if (!panel) return false;
    document.querySelectorAll("[data-kid-tab]").forEach(function (t) {
      var on = t.getAttribute("data-kid-tab") === id;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      if (on && focus) t.focus();
    });
    document.querySelectorAll("[data-kid-panel]").forEach(function (p) {
      p.hidden = p.getAttribute("data-kid-panel") !== id;
      if (!p.hidden) initCharts(p, true);
    });
    try { history.replaceState(null, "", "?con=" + encodeURIComponent(id)); } catch (e) { /* bỏ qua */ }
    return true;
  }
  document.addEventListener("keydown", function (e) {
    var tab = e.target.closest && e.target.closest("[data-kid-tab]");
    if (!tab) return;
    var all = Array.prototype.slice.call(document.querySelectorAll("[data-kid-tab]"));
    var i = all.indexOf(tab), next = null;
    if (e.key === "ArrowRight") next = all[(i + 1) % all.length];
    else if (e.key === "ArrowLeft") next = all[(i - 1 + all.length) % all.length];
    else if (e.key === "Home") next = all[0];
    else if (e.key === "End") next = all[all.length - 1];
    if (next) { e.preventDefault(); selectKid(next.getAttribute("data-kid-tab"), true); }
  });

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
    var plain = !e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0;
    var tab = e.target.closest("[data-kid-tab]");
    if (tab && plain) {
      if (selectKid(tab.getAttribute("data-kid-tab"), false)) e.preventDefault();
      return;
    }
    var cat = e.target.closest("[data-cat]");
    if (cat && plain) {
      var p = cat.getAttribute("data-cat").split(":");
      e.preventDefault();
      openCat(p[0], p[1], true);
      return;
    }
    var close = e.target.closest("[data-cat-close]");
    if (close && plain) {
      var q = close.getAttribute("data-cat-close").split(":");
      e.preventDefault();
      closeCats(q[0]);
      var back = document.querySelector('[data-cat="' + q[0] + ":" + q[1] + '"]');
      if (back) back.focus();
      return;
    }
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

  document.addEventListener("DOMContentLoaded", function () {
    initCountdowns(document);
    initCharts(document, true);
    var m = /^#cd-(\d+)-([a-z]+)$/.exec(location.hash);   // mở sẵn nhóm khi tải trang với #cd-<con>-<nhóm>
    if (m) openCat(m[1], m[2], false);
  });
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
