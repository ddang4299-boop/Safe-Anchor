/* Lưới lịch tuần 7×48 (ô 30 phút): chạm/kéo để tô bằng Pointer Events (chuột + cảm ứng + bút).
   Giá trị thật nằm trong <input type="hidden"> dạng chuỗi 336 ký tự '0'/'1'; server kiểm tra lại. */
(function () {
  "use strict";
  var DAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
  var DAY_FULL = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"];

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function slotLabel(i) { var m = (i % 48) * 30; return pad(Math.floor(m / 60)) + ":" + pad(m % 60); }

  function build(grid) {
    var input = document.getElementById(grid.getAttribute("data-schedule-for"));
    var bits = (input.value || "").split("");
    if (bits.length !== 336) bits = new Array(337).join("0").split("");
    grid.innerHTML = "";
    grid.appendChild(document.createElement("div"));
    for (var h = 0; h < 24; h++) {
      var hd = document.createElement("div");
      hd.className = "h"; hd.textContent = h % 3 === 0 ? h + "h" : "";
      grid.appendChild(hd);
    }
    var cells = [];
    for (var d = 0; d < 7; d++) {
      var dl = document.createElement("div");
      dl.className = "d"; dl.textContent = DAYS[d];
      grid.appendChild(dl);
      for (var s = 0; s < 48; s++) {
        var idx = d * 48 + s;
        var c = document.createElement("div");
        c.className = "c" + (bits[idx] === "1" ? " on" : "");
        c.setAttribute("data-i", idx);
        c.setAttribute("role", "gridcell");
        c.setAttribute("tabindex", idx === 0 ? "0" : "-1");
        c.setAttribute("aria-label", DAY_FULL[d] + " " + slotLabel(idx));
        c.setAttribute("aria-selected", bits[idx] === "1" ? "true" : "false");
        grid.appendChild(c);
        cells.push(c);
      }
    }

    function sync() {
      input.value = cells.map(function (c) { return c.classList.contains("on") ? "1" : "0"; }).join("");
    }
    function setCell(c, on) {
      c.classList.toggle("on", on);
      c.setAttribute("aria-selected", on ? "true" : "false");
    }

    var painting = false, paintValue = true;
    grid.addEventListener("pointerdown", function (e) {
      var c = e.target.closest(".c");
      if (!c) return;
      painting = true;
      paintValue = !c.classList.contains("on");
      setCell(c, paintValue);
      e.preventDefault();
    });
    // Cảm ứng không phát pointerenter khi kéo => dùng elementFromPoint để biết ngón tay đang ở ô nào.
    grid.addEventListener("pointermove", function (e) {
      if (!painting) return;
      var el = document.elementFromPoint(e.clientX, e.clientY);
      if (el && el.classList && el.classList.contains("c")) setCell(el, paintValue);
    });
    window.addEventListener("pointerup", function () { if (painting) { painting = false; sync(); } });
    window.addEventListener("pointercancel", function () { if (painting) { painting = false; sync(); } });

    // Bàn phím: mũi tên di chuyển (roving tabindex), Space/Enter để bật/tắt ô
    grid.addEventListener("keydown", function (e) {
      var c = e.target.closest(".c");
      if (!c) return;
      var i = parseInt(c.getAttribute("data-i"), 10), j = i;
      if (e.key === "ArrowRight") j = Math.min(335, i + 1);
      else if (e.key === "ArrowLeft") j = Math.max(0, i - 1);
      else if (e.key === "ArrowDown") j = Math.min(335, i + 48);
      else if (e.key === "ArrowUp") j = Math.max(0, i - 48);
      else if (e.key === " " || e.key === "Enter") { setCell(c, !c.classList.contains("on")); sync(); e.preventDefault(); return; }
      else return;
      e.preventDefault();
      c.setAttribute("tabindex", "-1");
      cells[j].setAttribute("tabindex", "0");
      cells[j].focus();
    });

    document.querySelectorAll("[data-sched-template]").forEach(function (b) {
      b.addEventListener("click", function () {
        var t = b.getAttribute("data-sched-template");
        cells.forEach(function (c, k) { setCell(c, t.charAt(k) === "1"); });
        sync();
      });
    });
    document.querySelectorAll("[data-sched-fill]").forEach(function (b) {
      b.addEventListener("click", function () {
        var v = b.getAttribute("data-sched-fill");
        var a = 0, z = 0;
        if (v !== "clear") {
          var p = v.split("-"), s = p[0].split(":"), t = p[1].split(":");
          a = parseInt(s[0], 10) * 2 + Math.floor(parseInt(s[1], 10) / 30);
          z = parseInt(t[0], 10) * 2 + Math.floor(parseInt(t[1], 10) / 30);
        }
        cells.forEach(function (c, k) { var slot = k % 48; setCell(c, slot >= a && slot < z); });
        sync();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-schedule-for]").forEach(build);
  });
})();
