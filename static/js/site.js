// =====================================================
// Central Library — shared site interactivity
// =====================================================

document.addEventListener("DOMContentLoaded", function () {

    // ---- Dark mode toggle ----
    var themeToggle = document.getElementById("themeToggle");
    if (themeToggle) {
        themeToggle.addEventListener("click", function () {
            var isDark = document.body.getAttribute("data-theme") === "dark";
            if (isDark) {
                document.body.removeAttribute("data-theme");
                try { localStorage.setItem("theme", "light"); } catch (e) {}
            } else {
                document.body.setAttribute("data-theme", "dark");
                try { localStorage.setItem("theme", "dark"); } catch (e) {}
            }
        });
    }

    // ---- Styled delete-confirmation modal (replaces native confirm()) ----
    var confirmModalEl = document.getElementById("confirmActionModal");
    if (confirmModalEl && window.bootstrap) {
        var confirmModal = new bootstrap.Modal(confirmModalEl);
        var confirmMessageEl = document.getElementById("confirmActionMessage");
        var confirmBtn = document.getElementById("confirmActionBtn");
        var pendingHref = null;

        document.querySelectorAll("[data-confirm]").forEach(function (el) {
            el.addEventListener("click", function (e) {
                e.preventDefault();
                pendingHref = el.getAttribute("href");
                confirmMessageEl.textContent = el.getAttribute("data-confirm");
                confirmModal.show();
            });
        });

        confirmBtn.addEventListener("click", function () {
            if (pendingHref) {
                window.location.href = pendingHref;
            }
        });
    }

    // ---- Page-load progress bar: remove once the animation finishes ----
    var bar = document.getElementById("pageLoadBar");
    if (bar) {
        setTimeout(function () {
            bar.remove();
        }, 1100);
    }

    // ---- Back-to-top button ----
    var backToTop = document.getElementById("backToTop");
    if (backToTop) {
        window.addEventListener("scroll", function () {
            if (window.scrollY > 400) {
                backToTop.classList.add("show");
            } else {
                backToTop.classList.remove("show");
            }
        });

        backToTop.addEventListener("click", function () {
            window.scrollTo({ top: 0, behavior: "smooth" });
        });
    }

    // ---- Auto-dismiss flash alerts after a few seconds ----
    document.querySelectorAll(".alert").forEach(function (el, index) {
        setTimeout(function () {
            el.classList.add("alert-fade-out");
            setTimeout(function () {
                if (el.parentNode) {
                    el.remove();
                }
            }, 450);
        }, 5000 + index * 250);
    });

});
