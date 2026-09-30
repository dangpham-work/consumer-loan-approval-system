// Hành vi dùng chung của mục 4.3a: đếm ngược hết phiên, hộp thoại xác nhận, nút "Hiện" dữ liệu che,
// số tiền trả hằng tháng ước tính của M03 bước 1 và DTI tính lại của M06.
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

// M03 bước 1: niên kim theo lãi suất trần (ADR 0001), tính lại mỗi khi đổi số tiền hoặc kỳ hạn. Chỉ
// để tham khảo; máy chủ tính lại bằng Decimal và hiển thị ở các bước sau.
function wireEstimate() {
  document.querySelectorAll("form[data-estimate]").forEach((form) => {
    const output = form.querySelector("[data-estimate-output]");
    const monthlyRate = Number(form.dataset.ceilingRate) / 12;
    const update = () => {
      const amount = Number(form.elements.requested_amount.value);
      const months = Number(form.elements.term_months.value);
      if (!(amount > 0 && months > 0)) {
        output.textContent = "—";
        return;
      }
      const payment = amount * monthlyRate / (1 - Math.pow(1 + monthlyRate, -months));
      output.textContent = Math.round(payment).toLocaleString("vi-VN") + " đ";
    };
    form.addEventListener("input", update);
    update();
  });
}

// M06: DTI và số tiền trả hằng tháng tính lại (ở máy chủ, theo lãi suất của Hạng) mỗi khi chuyên
// viên đổi hạn mức hoặc kỳ hạn đề xuất. Không có JavaScript thì dùng nút "Tính lại DTI".
function wireDtiPreview() {
  document.querySelectorAll("form[data-dti-url]").forEach((form) => {
    const dti = form.querySelector("[data-dti-output]");
    const payment = form.querySelector("[data-payment-output]");
    let timer;
    let latest = 0;  // chỉ hiển thị kết quả của lần gọi mới nhất, bỏ phản hồi đến muộn
    const unknown = () => {
      dti.textContent = "—";
      payment.textContent = "—";
    };
    const update = async () => {
      const amount = form.elements.proposed_amount.value;
      const term = form.elements.proposed_term.value;
      const request = ++latest;
      if (!amount || !term) {
        unknown();
        return;
      }
      const url = `${form.dataset.dtiUrl}?amount=${encodeURIComponent(amount)}&term=${encodeURIComponent(term)}`;
      let body;
      try {
        const response = await fetch(url, { credentials: "same-origin" });
        body = response.ok ? await response.json() : null;
      } catch {
        body = null;
      }
      if (request !== latest) return;
      if (!body) {
        unknown();
        return;
      }
      const percent = (Number(body.dti) * 100).toLocaleString("vi-VN", {
        minimumFractionDigits: 2, maximumFractionDigits: 2,
      });
      dti.textContent = percent + "%" + (body.within_limit ? "" : " (vượt 50%)");
      payment.textContent = Math.round(Number(body.monthly_payment)).toLocaleString("vi-VN") + " đ";
    };
    ["proposed_amount", "proposed_term"].forEach((name) => {
      form.elements[name].addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(update, 300);
      });
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  startIdleCountdown();
  wireConfirmDialogs();
  wireRevealButtons();
  wireEstimate();
  wireDtiPreview();
});
