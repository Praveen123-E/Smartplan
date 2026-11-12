/**
 * PlantOps Application Shell Controller
 * Handles SPA navigation across all 17 modules, JWT Login/Register,
 * Global Search, Notifications, Sidebar Collapsing, and Breadcrumbs.
 */
(function (window) {
    "use strict";

    const api = window.PlantOpsApi;
    const esc = api.escapeHtml;

    const appState = {
        currentPage: "overview",
        selectedRunId: null,
    };

    function showAuthModal(message = "") {
        const overlay = document.getElementById("authOverlay");
        const alertBox = document.getElementById("authAlertBox");
        if (!overlay) return;
        if (message && alertBox) {
            alertBox.textContent = message;
            alertBox.classList.remove("d-none");
        } else if (alertBox) {
            alertBox.classList.add("d-none");
        }
        overlay.style.display = "flex";
    }

    function hideAuthModal() {
        const overlay = document.getElementById("authOverlay");
        if (overlay) overlay.style.display = "none";
    }

    function updateUserBadge() {
        const user = api.getCurrentUser();
        document.getElementById("navUserName").textContent = user ? user.full_name || user.username : "Guest";
        document.getElementById("navUserRole").textContent = user?.roles?.length ? user.roles[0] : "Sign In";
        document.getElementById("navUserEmail").textContent = user ? `${user.username} (${user.email || ""})` : "Not authenticated";
    }

    async function refreshNotifications() {
        try {
            const data = await api.get("/api/notifications");
            const badge = document.getElementById("notifBadge");
            const list = document.getElementById("notifDropdownList");
            if (data.unread_count > 0) {
                badge.textContent = data.unread_count;
                badge.style.display = "inline-flex";
            } else {
                badge.style.display = "none";
            }
            const items = data.items || [];
            list.innerHTML = items.length
                ? items
                      .slice(0, 10)
                      .map(
                          (n) => `<div class="p-2 border-bottom small ${n.is_read ? "opacity-75" : "bg-light"}" style="cursor:pointer" data-notif-id="${n.id}">
                              <div class="fw-semibold">${esc(n.title)}</div>
                              <div class="text-muted">${esc(n.message)}</div>
                          </div>`
                      )
                      .join("")
                : `<div class="small text-muted p-2">No notifications yet.</div>`;

            list.querySelectorAll("[data-notif-id]").forEach((el) =>
                el.addEventListener("click", async () => {
                    await api.patch(`/api/notifications/${el.getAttribute("data-notif-id")}/read`, {});
                    refreshNotifications();
                })
            );
        } catch (_err) {
            // Silent fail when backend is offline or unauthenticated
        }
    }

    async function navigate(pageName) {
        appState.currentPage = pageName;
        const link = document.querySelector(`.nav-item-link[data-page="${pageName}"]`);
        document.querySelectorAll(".nav-item-link").forEach((el) => el.classList.remove("active"));
        if (link) {
            link.classList.add("active");
            document.getElementById("crumbSection").textContent = link.getAttribute("data-section") || "Module";
            document.getElementById("crumbPage").textContent = link.getAttribute("data-title") || pageName;
        }

        // Close mobile drawer after selection
        document.getElementById("sidebar")?.classList.remove("mobile-open");

        const loader = document.getElementById("pageLoadingIndicator");
        const contentEl = document.getElementById("pageContent");
        if (loader) loader.style.display = "flex";
        contentEl.innerHTML = "";

        try {
            const resp = await fetch(`/ui/pages/${pageName}.html`);
            if (!resp.ok) throw new Error(`Page fragment ${pageName}.html not found`);
            contentEl.innerHTML = await resp.text();
            const initFn = window.PlantOpsPages?.[pageName];
            if (typeof initFn === "function") {
                await initFn();
            }
        } catch (err) {
            contentEl.innerHTML = `<div class="alert alert-danger">${esc(err.message)}</div>`;
        } finally {
            if (loader) loader.style.display = "none";
        }
    }

    function bindShellEvents() {
        // Sidebar navigation clicks
        document.querySelectorAll(".nav-item-link[data-page]").forEach((link) => {
            link.addEventListener("click", (evt) => {
                evt.preventDefault();
                navigate(link.getAttribute("data-page"));
            });
        });

        // Collapsible sidebar toggle (desktop collapse / mobile slide-in)
        document.getElementById("sidebarToggleBtn")?.addEventListener("click", () => {
            const sidebar = document.getElementById("sidebar");
            if (window.innerWidth < 992) {
                sidebar.classList.toggle("mobile-open");
            } else {
                sidebar.classList.toggle("collapsed");
            }
        });

        // Auth tabs
        document.getElementById("tabLoginBtn")?.addEventListener("click", () => {
            document.getElementById("tabLoginBtn").classList.add("active");
            document.getElementById("tabRegisterBtn").classList.remove("active");
            document.getElementById("loginForm").style.display = "block";
            document.getElementById("registerForm").style.display = "none";
        });
        document.getElementById("tabRegisterBtn")?.addEventListener("click", () => {
            document.getElementById("tabRegisterBtn").classList.add("active");
            document.getElementById("tabLoginBtn").classList.remove("active");
            document.getElementById("registerForm").style.display = "block";
            document.getElementById("loginForm").style.display = "none";
        });

        // Login form
        document.getElementById("loginForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                const res = await api.post(
                    "/api/auth/login",
                    {
                        username: document.getElementById("loginUsername").value.trim(),
                        password: document.getElementById("loginPassword").value,
                    },
                    { skipAuthRedirect: true }
                );
                api.setSession(res.access_token, res.user);
                updateUserBadge();
                hideAuthModal();
                api.notify(`Signed in as ${res.user.username}`, "success");
                refreshNotifications();
                navigate(appState.currentPage);
            } catch (err) {
                showAuthModal(err.message);
            }
        });

        // Register form
        document.getElementById("registerForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                const res = await api.post(
                    "/api/auth/register",
                    {
                        username: document.getElementById("regUsername").value.trim(),
                        full_name: document.getElementById("regFullName").value.trim(),
                        email: document.getElementById("regEmail").value.trim(),
                        role_name: document.getElementById("regRole").value,
                        password: document.getElementById("regPassword").value,
                    },
                    { skipAuthRedirect: true }
                );
                api.setSession(res.access_token, res.user);
                updateUserBadge();
                hideAuthModal();
                api.notify(`Registered & signed in as ${res.user.username}`, "success");
                navigate(appState.currentPage);
            } catch (err) {
                showAuthModal(err.message);
            }
        });

        document.getElementById("btnSwitchAccount")?.addEventListener("click", (e) => {
            e.preventDefault();
            showAuthModal();
        });
        document.getElementById("btnLogout")?.addEventListener("click", (e) => {
            e.preventDefault();
            api.clearSession();
            updateUserBadge();
            showAuthModal("You have signed out.");
        });

        // Global Search Popover
        const searchInput = document.getElementById("globalSearchInput");
        const popover = document.getElementById("globalSearchResults");
        let searchTimer = null;
        searchInput?.addEventListener("input", () => {
            clearTimeout(searchTimer);
            const q = searchInput.value.trim();
            if (q.length < 2) {
                popover.classList.remove("show");
                return;
            }
            searchTimer = setTimeout(async () => {
                try {
                    const res = await api.get("/api/search", { q });
                    const rows = [];
                    (res.orders || []).forEach((o) => rows.push({ page: "orders", type: "Order", label: o.label }));
                    (res.products || []).forEach((p) => rows.push({ page: "products", type: "Product", label: p.label }));
                    (res.machines || []).forEach((m) => rows.push({ page: "machines", type: "Machine", label: m.label }));
                    (res.materials || []).forEach((m) => rows.push({ page: "materials", type: "Material", label: m.label }));

                    popover.innerHTML = rows.length
                        ? rows
                              .map(
                                  (r) => `<div class="search-result-item" data-goto="${r.page}">
                                      <span class="small fw-semibold">${esc(r.label)}</span>
                                      <span class="badge bg-light text-dark">${r.type}</span>
                                  </div>`
                              )
                              .join("")
                        : `<div class="p-3 small text-muted">No matches for "${esc(q)}"</div>`;
                    popover.classList.add("show");
                    popover.querySelectorAll("[data-goto]").forEach((el) =>
                        el.addEventListener("click", () => {
                            popover.classList.remove("show");
                            navigate(el.getAttribute("data-goto"));
                        })
                    );
                } catch (_err) {
                    popover.classList.remove("show");
                }
            }, 260);
        });

        document.addEventListener("click", (evt) => {
            if (!evt.target.closest(".global-search-wrap")) {
                popover?.classList.remove("show");
            }
        });

        // Live plant clock
        const updateClock = () => {
            const el = document.getElementById("topClockLabel");
            if (el) el.textContent = new Date().toLocaleString();
        };
        updateClock();
        setInterval(updateClock, 30000);
    }

    window.PlantOpsApp = {
        navigate,
        showAuthModal,
        get selectedRunId() {
            return appState.selectedRunId;
        },
        set selectedRunId(val) {
            appState.selectedRunId = val;
        },
    };

    document.addEventListener("DOMContentLoaded", () => {
        bindShellEvents();
        updateUserBadge();
        refreshNotifications();
        if (!api.getToken()) {
            showAuthModal("Sign in with a PlantOps account (demo credentials shown below).");
        }
        navigate("overview");
    });
})(window);

