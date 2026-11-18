/* OGK dashboard — tiện ích nhỏ (không inline script để tuân CSP script-src 'self'). */
(function () {
  "use strict";

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
      var ta = document.getElementById(chip.getAttribute("data-fill"));
      if (ta) { ta.value = chip.textContent.trim(); ta.focus(); }
    }
  });

  document.addEventListener("change", function (e) {
    if (e.target.matches("[data-autosubmit]")) e.target.form.submit();
  });

  document.addEventListener("DOMContentLoaded", function () { initCountdowns(document); });
  document.addEventListener("htmx:afterSwap", function (e) { initCountdowns(e.target); });
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
