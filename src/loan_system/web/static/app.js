// Hành vi dùng chung của mục 4.3a: đếm ngược hết phiên, hộp thoại xác nhận, nút "Hiện" dữ liệu che.
"use strict";

// Đếm ngược cảnh báo hết phiên (SR11). Máy chủ gia hạn phiên ở mỗi yêu cầu, nên mỗi lần tải trang
// là đếm lại từ đầu; "Tiếp tục làm việc" gọi /auth/session để gia hạn mà không rời trang.
function startIdleCountdown() {
  const idleSeconds = Number(document.body.dataset.idleSeconds);
  if (!idleSeconds) return;
  const warnBefore = Math.min(120, idleSeconds);
  const warning = document.getElementById("idle-warning");
  const remaining = document.getElementById("idle-remaining");
  let deadline = Date.now() + idleSeconds * 1000;

  document.getElementById("idle-extend").addEventListener("click", async () => {
    const response = await fetch("/auth/session", { credentials: "same-origin" });
    if (!response.ok) {
      window.location.href = "/app/login?notice=expired";
      return;
    }
    deadline = Date.now() + idleSeconds * 1000;
    warning.hidden = true;
  });

  setInterval(() => {
    const left = Math.ceil((deadline - Date.now()) / 1000);
    if (left <= 0) {
      window.location.href = "/app/login?notice=expired";
    } else if (left <= warnBefore) {
      remaining.textContent = String(left);
      warning.hidden = false;
    }
  }, 1000);
}

// Hộp thoại xác nhận cho thao tác không thể hoàn tác: <form data-confirm="Câu hỏi?">.
function wireConfirmDialogs() {
  const dialog = document.getElementById("confirm-dialog");
  const message = document.getElementById("confirm-message");
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.confirmed === "yes") return;
      event.preventDefault();
      message.textContent = form.dataset.confirm;
      dialog.returnValue = "";
      dialog.showModal();
      dialog.addEventListener("close", () => {
        if (dialog.returnValue !== "ok") return;
        form.dataset.confirmed = "yes";
        form.requestSubmit(event.submitter);
      }, { once: true });
    });
  });
}

// Nút "Hiện": endpoint của REST API ghi log rồi trả dữ liệu đầy đủ.
function wireRevealButtons() {
  document.querySelectorAll("button[data-reveal-url]").forEach((button) => {
    button.addEventListener("click", async () => {
      const response = await fetch(button.dataset.revealUrl, {
        method: "POST",
        credentials: "same-origin",
      });
      const target = button.parentElement.querySelector(".masked-value");
      if (!response.ok) {
        target.textContent = "Không hiển thị được";
        return;
      }
      const body = await response.json();
      target.textContent = body[button.dataset.revealField];
      button.remove();
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  startIdleCountdown();
  wireConfirmDialogs();
  wireRevealButtons();
});
