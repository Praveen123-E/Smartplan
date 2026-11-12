/**
 * PlantOps API Client & UI Utilities
 * Handles authenticated HTTP requests to FastAPI, toast alerts, and formatting helpers.
 */
(function (window) {
    "use strict";

    // Automatically resolve API base URL whether served via FastAPI (/ui) or separately on port 8000.
    const defaultOrigin =
        window.location.port === "8000" || window.location.pathname.startsWith("/ui")
            ? window.location.origin
            : "http://127.0.0.1:8000";

    const API_BASE = window.PLANTOPS_API_BASE || defaultOrigin;
    const TOKEN_KEY = "plantops_jwt_token";
    const USER_KEY = "plantops_current_user";

    function getToken() {
        return window.localStorage.getItem(TOKEN_KEY) || "";
    }

    function setSession(token, user) {
        if (token) {
            window.localStorage.setItem(TOKEN_KEY, token);
        }
        if (user) {
            window.localStorage.setItem(USER_KEY, JSON.stringify(user));
        }
    }

    function clearSession() {
        window.localStorage.removeItem(TOKEN_KEY);
        window.localStorage.removeItem(USER_KEY);
    }

    function getCurrentUser() {
        try {
            const raw = window.localStorage.getItem(USER_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (_err) {
            return null;
        }
    }

    /**
     * Execute a JSON API request against the FastAPI backend.
     */
    async function request(path, options = {}) {
        const headers = Object.assign(
            { "Content-Type": "application/json" },
            options.headers || {}
        );
        const token = getToken();
        if (token) {
            headers["Authorization"] = `Bearer ${token}`;
        }

        const fetchOptions = Object.assign({}, options, { headers });
        const response = await fetch(`${API_BASE}${path}`, fetchOptions);

        if (response.status === 401 && !options.skipAuthRedirect) {
            clearSession();
            if (typeof window.PlantOpsApp?.showAuthModal === "function") {
                window.PlantOpsApp.showAuthModal("Session expired. Please sign in again.");
            }
        }

        const contentType = response.headers.get("content-type") || "";
        if (!response.ok) {
            let errMsg = `HTTP ${response.status}`;
            if (contentType.includes("application/json")) {
                const payload = await response.json().catch(() => ({}));
                errMsg = payload.detail || payload.message || errMsg;
            } else {
                errMsg = (await response.text().catch(() => "")) || errMsg;
            }
            throw new Error(typeof errMsg === "string" ? errMsg : JSON.stringify(errMsg));
        }

        if (contentType.includes("application/json")) {
            return response.json();
        }
        return response.text();
    }

    function get(path, params) {
        let url = path;
        if (params && typeof params === "object") {
            const qs = new URLSearchParams();
            Object.entries(params).forEach(([k, v]) => {
                if (v !== undefined && v !== null && String(v).trim() !== "") {
                    qs.append(k, String(v));
                }
            });
            const queryString = qs.toString();
            if (queryString) {
                url += (url.includes("?") ? "&" : "?") + queryString;
            }
        }
        return request(url, { method: "GET" });
    }

    function post(path, body, options = {}) {
        return request(
            path,
            Object.assign({ method: "POST", body: JSON.stringify(body || {}) }, options)
        );
    }

    function put(path, body) {
        return request(path, { method: "PUT", body: JSON.stringify(body || {}) });
    }

    function patch(path, body) {
        return request(path, { method: "PATCH", body: JSON.stringify(body || {}) });
    }

    /**
     * Show Bootstrap toast notification at the top-right corner.
     */
    function notify(message, variant = "success") {
        const container = document.getElementById("toastContainer");
        if (!container) return;

        const bgClass =
            variant === "error" || variant === "danger"
                ? "text-bg-danger"
                : variant === "warning"
                  ? "text-bg-warning"
                  : variant === "info"
                    ? "text-bg-info"
                    : "text-bg-success";

        const toastEl = document.createElement("div");
        toastEl.className = `toast align-items-center ${bgClass} border-0 shadow`;
        toastEl.setAttribute("role", "alert");
        toastEl.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${escapeHtml(message)}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;
        container.appendChild(toastEl);
        const toast = new window.bootstrap.Toast(toastEl, { delay: 4200 });
        toast.show();
        toastEl.addEventListener("hidden.bs.toast", () => toastEl.remove());
    }

    function escapeHtml(text) {
        if (text === null || text === undefined) return "";
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function statusBadge(status) {
        const val = String(status || "Unknown");
        const upper = val.toUpperCase();
        let cls = "pill-muted";
        if (["COMPLETED", "AVAILABLE", "ACTIVE", "IN STOCK", "SUFFICIENT", "RESOLVED", "OPTIMAL", "FEASIBLE", "PASSED", "TP", "TN"].includes(upper)) {
            cls = "pill-success";
        } else if (["SCHEDULED", "PLANNED", "RUNNING", "IN PROGRESS", "IN_PROGRESS", "RELEASED", "OPEN", "IN REVIEW", "MEDIUM", "LOW"].includes(upper)) {
            cls = "pill-indigo";
        } else if (["DELAYED", "MAINTENANCE", "LOW STOCK", "LOW_STOCK", "HIGH", "PARTIAL", "WARNING", "ACKNOWLEDGED"].includes(upper)) {
            cls = "pill-warning";
        } else if (["INFEASIBLE", "DOWN", "OUT OF STOCK", "OUT_OF_STOCK", "CRITICAL", "URGENT", "CANCELLED", "FAILED", "RETIRED", "FP", "FN"].includes(upper)) {
            cls = "pill-danger";
        }
        return `<span class="status-pill ${cls}">${escapeHtml(val)}</span>`;
    }

    function formatDateTime(isoStr) {
        if (!isoStr) return "-";
        const d = new Date(isoStr);
        if (Number.isNaN(d.getTime())) return String(isoStr);
        return d.toLocaleString(undefined, {
            year: "numeric",
            month: "short",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
    }

    function downloadCsv(path) {
        const token = getToken();
        fetch(`${API_BASE}${path}`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
            .then((res) => {
                if (!res.ok) throw new Error(`Export failed (${res.status})`);
                return res.blob();
            })
            .then((blob) => {
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = "plantops_export.csv";
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(url);
                notify("CSV report downloaded.", "success");
            })
            .catch((err) => notify(err.message, "error"));
    }

    window.PlantOpsApi = {
        API_BASE,
        getToken,
        setSession,
        clearSession,
        getCurrentUser,
        get,
        post,
        put,
        patch,
        notify,
        escapeHtml,
        statusBadge,
        formatDateTime,
        downloadCsv,
    };
})(window);
