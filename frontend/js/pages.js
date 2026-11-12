/**
 * PlantOps Page Controllers
 * Initializes each of the 17 dashboard modules using real FastAPI backend endpoints.
 */
(function (window) {
    "use strict";

    const api = window.PlantOpsApi;
    const charts = window.PlantOpsCharts;
    const esc = api.escapeHtml;

    let activeGanttInstance = null;

    function openModal(id) {
        const el = document.getElementById(id);
        if (el) window.bootstrap.Modal.getOrCreateInstance(el).show();
    }

    function closeModal(id) {
        const el = document.getElementById(id);
        if (el) window.bootstrap.Modal.getOrCreateInstance(el).hide();
    }

    function setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    /* =========================================================================
       1. OVERVIEW DASHBOARD
       ========================================================================= */
    async function initOverview() {
        async function loadAll() {
            try {
                const startDate = document.getElementById("ovStartDate")?.value || "";
                const endDate = document.getElementById("ovEndDate")?.value || "";
                const machineId = document.getElementById("ovMachineFilter")?.value || "";

                const [summary, prodCharts, utilData, machinesResp] = await Promise.all([
                    api.get("/api/dashboard/summary"),
                    api.get("/api/dashboard/production", { start_date: startDate, end_date: endDate, machine_id: machineId }),
                    api.get("/api/dashboard/machine-utilization", { machine_id: machineId }),
                    api.get("/api/machines", { page_size: 100 }),
                ]);

                // Populate machine filter dropdown once
                const machSel = document.getElementById("ovMachineFilter");
                if (machSel && machSel.options.length <= 1 && Array.isArray(machinesResp.items)) {
                    machinesResp.items.forEach((m) => {
                        const opt = new Option(`${m.machine_id} - ${m.name}`, m.machine_id);
                        machSel.add(opt);
                    });
                    machSel.value = machineId;
                }

                // 12 KPI Cards
                const k = summary.kpis || {};
                setText("kpiTotalOrders", k.total_orders ?? 0);
                setText("kpiPendingOrders", k.pending_orders ?? 0);
                setText("kpiScheduledOrders", k.scheduled_orders ?? 0);
                setText("kpiCompletedOrders", k.completed_orders ?? 0);
                setText("kpiDelayedOrders", k.delayed_orders ?? 0);
                setText("kpiInfeasibleOrders", k.infeasible_orders ?? 0);
                setText("kpiTotalMachines", k.total_machines ?? 0);
                setText("kpiAvailMachines", k.available_machines ?? 0);
                setText("kpiAvgUtil", `${k.avg_machine_utilization_pct ?? 0}%`);
                setText("kpiTotalMaterials", k.total_materials ?? 0);
                setText("kpiOpenViolations", k.open_constraint_violations ?? 0);
                setText("kpiOtdPct", `${k.on_time_delivery_pct ?? 0}%`);
                setText("ovRunBadge", summary.latest_run_id || "No Runs");

                // 6 Charts
                charts.renderDoughnut("chartOrderStatus", prodCharts.order_status_chart.labels, prodCharts.order_status_chart.values);
                const topMach = (utilData.machines || []).slice(0, 12);
                charts.renderBar(
                    "chartMachineUtil",
                    topMach.map((m) => m.machine_id),
                    topMach.map((m) => m.utilization_pct),
                    "Utilization %",
                    "#4338ca"
                );
                charts.renderLine("chartProductionOutput", prodCharts.production_output_chart.labels, prodCharts.production_output_chart.values, "Scheduled Minutes");
                charts.renderBar("chartOrderPriority", prodCharts.priority_chart.labels, prodCharts.priority_chart.values, "Orders", "#0f766e");
                charts.renderDoughnut("chartViolations", prodCharts.constraint_violations_chart.labels, prodCharts.constraint_violations_chart.values);
                charts.renderDoughnut("chartMachineAvail", utilData.availability_chart.labels, utilData.availability_chart.values);

                // Upcoming Schedule Table
                const upBody = document.getElementById("ovUpcomingBody");
                if (upBody) {
                    upBody.innerHTML = (summary.upcoming_schedule || []).length
                        ? summary.upcoming_schedule
                              .map(
                                  (r) => `<tr>
                                      <td class="fw-semibold">${esc(r.order_id)}</td>
                                      <td>${esc(r.machine_id)}</td>
                                      <td class="small">${esc(api.formatDateTime(r.start_time))}</td>
                                      <td class="small">${esc(api.formatDateTime(r.end_time))}</td>
                                      <td>${api.statusBadge(r.is_late ? "Delayed" : "Scheduled")}</td>
                                  </tr>`
                              )
                              .join("")
                        : `<tr><td colspan="5" class="text-center text-muted py-3">No scheduled operations yet. Run CP-SAT Scheduler.</td></tr>`;
                }

                // Critical Alerts
                const alertsBox = document.getElementById("ovAlertsContainer");
                if (alertsBox) {
                    alertsBox.innerHTML = (summary.critical_alerts || []).length
                        ? summary.critical_alerts
                              .map(
                                  (a) => `<div class="alert ${a.severity === "Critical" ? "alert-danger" : "alert-warning"} py-2 px-3 mb-2 small">
                                      <div class="fw-bold">${esc(a.title)} <span class="badge bg-dark-subtle text-dark ms-1">${esc(a.entity_id)}</span></div>
                                      <div>${esc(a.message)}</div>
                                  </div>`
                              )
                              .join("")
                        : `<div class="text-muted small text-center py-3">No open critical alerts.</div>`;
                }

                // Recent Activities Timeline
                const actBox = document.getElementById("ovActivityTimeline");
                if (actBox) {
                    actBox.innerHTML = (summary.recent_activities || []).length
                        ? summary.recent_activities
                              .map(
                                  (act) => `<li class="activity-item">
                                      <span class="activity-dot"></span>
                                      <div class="small fw-semibold">${esc(act.action)} · ${esc(act.entity_id)}</div>
                                      <div class="text-muted" style="font-size:0.75rem">${esc(act.username)} · ${esc(api.formatDateTime(act.created_at))}</div>
                                  </li>`
                              )
                              .join("")
                        : `<li class="text-muted small">No recent audit activity recorded.</li>`;
                }
            } catch (err) {
                api.notify(`Overview load error: ${err.message}`, "error");
            }
        }

        document.getElementById("ovRefreshBtn")?.addEventListener("click", loadAll);
        await loadAll();
    }

    /* =========================================================================
       2. PRODUCTION ORDERS
       ========================================================================= */
    async function initOrders() {
        let currentPage = 1;

        async function loadProductsDropdown() {
            const sel = document.getElementById("orderProductSelect");
            if (!sel || sel.options.length > 0) return;
            const prods = await api.get("/api/products", { page_size: 100 });
            (prods.items || []).forEach((p) => sel.add(new Option(`${p.product_id} (${p.sku}) - ${p.name}`, p.product_id)));
        }

        async function loadOrders() {
            try {
                const resp = await api.get("/api/orders", {
                    search: document.getElementById("ordersSearch")?.value,
                    status: document.getElementById("ordersStatusFilter")?.value,
                    priority: document.getElementById("ordersPriorityFilter")?.value,
                    sort_by: document.getElementById("ordersSortBy")?.value || "order_id",
                    page: currentPage,
                    page_size: 20,
                });

                const tbody = document.getElementById("ordersTableBody");
                const items = resp.items || [];
                tbody.innerHTML = items.length
                    ? items
                          .map((o) => {
                              const pct = o.quantity > 0 ? Math.min(100, Math.round((o.completed_quantity / o.quantity) * 100)) : 0;
                              return `<tr>
                                  <td class="fw-semibold">${esc(o.order_id)} ${o.is_urgent ? '<span class="badge bg-danger ms-1">URGENT</span>' : ""}</td>
                                  <td>${esc(o.product_id)}</td>
                                  <td>${esc(o.customer_name || "-")}</td>
                                  <td>${o.quantity}</td>
                                  <td>P${o.priority}</td>
                                  <td class="small">${esc(api.formatDateTime(o.release_date))}</td>
                                  <td class="small">${esc(api.formatDateTime(o.due_date))}</td>
                                  <td style="min-width:95px"><div class="progress" style="height:7px"><div class="progress-bar bg-indigo" style="width:${pct}%"></div></div><small class="text-muted">${o.completed_quantity}/${o.quantity}</small></td>
                                  <td>${api.statusBadge(o.status)}</td>
                                  <td class="text-nowrap">
                                      <button class="btn btn-outline-primary btn-sm py-0 px-2" data-view-order="${esc(o.order_id)}">Inspect</button>
                                      <button class="btn btn-outline-secondary btn-sm py-0 px-2" data-edit-order="${esc(JSON.stringify(o))}">Edit</button>
                                  </td>
                              </tr>`;
                          })
                          .join("")
                    : `<tr><td colspan="10" class="text-center text-muted py-4">No orders match your filter.</td></tr>`;

                setText("ordersPageInfo", `Showing page ${resp.page} (${items.length} of ${resp.total} orders)`);

                tbody.querySelectorAll("[data-view-order]").forEach((btn) =>
                    btn.addEventListener("click", () => openOrderDetail(btn.getAttribute("data-view-order")))
                );
                tbody.querySelectorAll("[data-edit-order]").forEach((btn) =>
                    btn.addEventListener("click", () => {
                        const o = JSON.parse(btn.getAttribute("data-edit-order"));
                        document.getElementById("orderEditId").value = o.order_id;
                        document.getElementById("orderModalTitle").textContent = `Edit ${o.order_id}`;
                        document.getElementById("orderProductSelect").value = o.product_id;
                        document.getElementById("orderProductSelect").disabled = true;
                        document.getElementById("orderQuantityInput").value = o.quantity;
                        document.getElementById("orderPriorityInput").value = o.priority;
                        document.getElementById("orderCustomerInput").value = o.customer_name || "";
                        document.getElementById("orderReleaseInput").value = String(o.release_date).slice(0, 16);
                        document.getElementById("orderDueInput").value = String(o.due_date).slice(0, 16);
                        openModal("orderFormModal");
                    })
                );
            } catch (err) {
                api.notify(`Orders load failed: ${err.message}`, "error");
            }
        }

        async function openOrderDetail(orderId) {
            try {
                const detail = await api.get(`/api/orders/${orderId}`);
                const o = detail.order;
                const ops = detail.operations || [];
                const mats = detail.material_requirements || [];
                const sched = detail.schedules || [];

                setText("orderDetailTitle", `${o.order_id} · ${o.status}`);
                document.getElementById("orderDetailBody").innerHTML = `
                    <div class="row g-3 mb-3 small">
                        <div class="col-md-3"><strong>Product:</strong> ${esc(o.product_id)}</div>
                        <div class="col-md-3"><strong>Quantity:</strong> ${o.completed_quantity}/${o.quantity}</div>
                        <div class="col-md-3"><strong>Priority:</strong> P${o.priority}</div>
                        <div class="col-md-3"><strong>Customer:</strong> ${esc(o.customer_name || "-")}</div>
                    </div>
                    <div class="d-flex gap-2 mb-3 align-items-center">
                        <label class="small fw-semibold">Transition Status:</label>
                        <select id="detailNewStatus" class="form-select form-select-sm" style="width:180px">
                            <option>Draft</option><option>Released</option><option>Planned</option>
                            <option>Scheduled</option><option>In Progress</option><option>Completed</option>
                            <option>Delayed</option><option>Cancelled</option>
                        </select>
                        <button class="btn btn-sm btn-indigo" id="btnTransitionStatus">Update Status</button>
                    </div>
                    <h6 class="fw-bold">Operation Sequence</h6>
                    <table class="table table-sm table-enterprise mb-3">
                        <thead><tr><th>Op ID</th><th>Seq</th><th>Code</th><th>Dur (m)</th><th>Setup (m)</th><th>Completed</th><th>Status</th><th>Update Progress</th></tr></thead>
                        <tbody>
                            ${ops
                                .map(
                                    (op) => `<tr>
                                        <td>${esc(op.operation_id)}</td><td>${op.sequence_number}</td><td>${esc(op.operation_code)}</td>
                                        <td>${op.planned_duration_minutes}</td><td>${op.setup_minutes}</td><td>${op.completed_quantity}</td>
                                        <td>${api.statusBadge(op.status)}</td>
                                        <td><button class="btn btn-outline-success btn-sm py-0 px-2" data-complete-op="${esc(op.operation_id)}">Mark Qty Done</button></td>
                                    </tr>`
                                )
                                .join("")}
                        </tbody>
                    </table>
                    <div class="row g-3">
                        <div class="col-md-6">
                            <h6 class="fw-bold">Material Requirements</h6>
                            <ul class="list-group list-group-flush small">
                                ${mats.length ? mats.map((m) => `<li class="list-group-item">${esc(m.material_id)} — ${m.quantity_per_unit} per unit (Total: ${(m.quantity_per_unit * o.quantity).toFixed(1)})</li>`).join("") : '<li class="list-group-item text-muted">None mapped</li>'}
                            </ul>
                        </div>
                        <div class="col-md-6">
                            <h6 class="fw-bold">Assigned Schedule</h6>
                            <ul class="list-group list-group-flush small">
                                ${sched.length ? sched.map((s) => `<li class="list-group-item">${esc(s.machine_id)} | ${esc(api.formatDateTime(s.start_time))} → ${esc(api.formatDateTime(s.end_time))}</li>`).join("") : '<li class="list-group-item text-muted">Not yet scheduled</li>'}
                            </ul>
                        </div>
                    </div>
                `;
                document.getElementById("detailNewStatus").value = o.status;
                document.getElementById("btnTransitionStatus").onclick = async () => {
                    try {
                        await api.patch(`/api/orders/${o.order_id}/status`, {
                            new_status: document.getElementById("detailNewStatus").value,
                            reason: "Status updated from UI Order Inspector",
                        });
                        api.notify("Order status transitioned.", "success");
                        closeModal("orderDetailModal");
                        loadOrders();
                    } catch (err) {
                        api.notify(err.message, "error");
                    }
                };
                document.querySelectorAll("[data-complete-op]").forEach((btn) => {
                    btn.onclick = async () => {
                        try {
                            await api.patch(`/api/operations/${btn.getAttribute("data-complete-op")}/progress`, {
                                completed_quantity: o.quantity,
                                status: "Completed",
                            });
                            api.notify("Operation progress updated.", "success");
                            openOrderDetail(o.order_id);
                            loadOrders();
                        } catch (err) {
                            api.notify(err.message, "error");
                        }
                    };
                });
                openModal("orderDetailModal");
            } catch (err) {
                api.notify(err.message, "error");
            }
        }

        document.getElementById("btnNewOrder")?.addEventListener("click", async () => {
            await loadProductsDropdown();
            document.getElementById("orderEditId").value = "";
            document.getElementById("orderModalTitle").textContent = "Create Production Order";
            document.getElementById("orderProductSelect").disabled = false;
            const now = new Date();
            const due = new Date(now.getTime() + 4 * 86400000);
            document.getElementById("orderReleaseInput").value = now.toISOString().slice(0, 16);
            document.getElementById("orderDueInput").value = due.toISOString().slice(0, 16);
            openModal("orderFormModal");
        });

        document.getElementById("orderForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const editId = document.getElementById("orderEditId").value;
            try {
                if (editId) {
                    await api.put(`/api/orders/${editId}`, {
                        quantity: Number(document.getElementById("orderQuantityInput").value),
                        priority: Number(document.getElementById("orderPriorityInput").value),
                        customer_name: document.getElementById("orderCustomerInput").value,
                        release_date: document.getElementById("orderReleaseInput").value,
                        due_date: document.getElementById("orderDueInput").value,
                    });
                    api.notify(`Order ${editId} updated.`, "success");
                } else {
                    await api.post("/api/orders", {
                        product_id: document.getElementById("orderProductSelect").value,
                        quantity: Number(document.getElementById("orderQuantityInput").value),
                        priority: Number(document.getElementById("orderPriorityInput").value),
                        customer_name: document.getElementById("orderCustomerInput").value,
                        release_date: document.getElementById("orderReleaseInput").value,
                        due_date: document.getElementById("orderDueInput").value,
                    });
                    api.notify("New production order created.", "success");
                }
                closeModal("orderFormModal");
                loadOrders();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });

        document.getElementById("ordersApplyFilterBtn")?.addEventListener("click", () => { currentPage = 1; loadOrders(); });
        document.getElementById("ordersResetFilterBtn")?.addEventListener("click", () => {
            document.getElementById("ordersSearch").value = "";
            document.getElementById("ordersStatusFilter").value = "";
            document.getElementById("ordersPriorityFilter").value = "";
            currentPage = 1;
            loadOrders();
        });
        document.getElementById("ordersPrevBtn")?.addEventListener("click", () => { if (currentPage > 1) { currentPage--; loadOrders(); } });
        document.getElementById("ordersNextBtn")?.addEventListener("click", () => { currentPage++; loadOrders(); });

        await loadProductsDropdown();
        await loadOrders();
    }

    /* =========================================================================
       3. PRODUCTS
       ========================================================================= */
    async function initProducts() {
        async function load() {
            const resp = await api.get("/api/products", {
                search: document.getElementById("prodSearch")?.value,
                status: document.getElementById("prodStatusFilter")?.value,
                page_size: 100,
            });
            const tbody = document.getElementById("productsTableBody");
            tbody.innerHTML = (resp.items || [])
                .map(
                    (p) => `<tr>
                        <td class="fw-semibold">${esc(p.product_id)}</td>
                        <td>${esc(p.sku)}</td>
                        <td>${esc(p.name)}</td>
                        <td>${esc(p.category)}</td>
                        <td>${esc(p.unit_of_measure)}</td>
                        <td>${p.standard_batch_size}</td>
                        <td>${api.statusBadge(p.status)}</td>
                        <td><button class="btn btn-outline-secondary btn-sm py-0 px-2" data-edit-prod="${esc(JSON.stringify(p))}">Edit</button></td>
                    </tr>`
                )
                .join("");

            tbody.querySelectorAll("[data-edit-prod]").forEach((btn) =>
                btn.addEventListener("click", () => {
                    const p = JSON.parse(btn.getAttribute("data-edit-prod"));
                    document.getElementById("prodEditId").value = p.product_id;
                    document.getElementById("productModalTitle").textContent = `Edit ${p.product_id}`;
                    document.getElementById("prodSku").value = p.sku;
                    document.getElementById("prodSku").disabled = true;
                    document.getElementById("prodName").value = p.name;
                    document.getElementById("prodCategory").value = p.category;
                    document.getElementById("prodUom").value = p.unit_of_measure;
                    document.getElementById("prodBatch").value = p.standard_batch_size;
                    document.getElementById("prodStatus").value = p.status;
                    document.getElementById("prodDesc").value = p.description || "";
                    openModal("productModal");
                })
            );
        }

        document.getElementById("btnNewProduct")?.addEventListener("click", () => {
            document.getElementById("prodEditId").value = "";
            document.getElementById("productModalTitle").textContent = "Add Product";
            document.getElementById("prodSku").disabled = false;
            document.getElementById("productForm").reset();
            openModal("productModal");
        });

        document.getElementById("productForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const editId = document.getElementById("prodEditId").value;
            try {
                if (editId) {
                    await api.put(`/api/products/${editId}`, {
                        name: document.getElementById("prodName").value,
                        category: document.getElementById("prodCategory").value,
                        unit_of_measure: document.getElementById("prodUom").value,
                        standard_batch_size: Number(document.getElementById("prodBatch").value),
                        status: document.getElementById("prodStatus").value,
                        description: document.getElementById("prodDesc").value,
                    });
                    api.notify(`Product ${editId} updated.`, "success");
                } else {
                    await api.post("/api/products", {
                        sku: document.getElementById("prodSku").value,
                        name: document.getElementById("prodName").value,
                        category: document.getElementById("prodCategory").value,
                        unit_of_measure: document.getElementById("prodUom").value,
                        standard_batch_size: Number(document.getElementById("prodBatch").value),
                        description: document.getElementById("prodDesc").value,
                    });
                    api.notify("Product added.", "success");
                }
                closeModal("productModal");
                load();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });
        document.getElementById("prodFilterBtn")?.addEventListener("click", load);
        await load();
    }

    /* =========================================================================
       4. ROUTINGS & OPERATIONS
       ========================================================================= */
    async function initRoutings() {
        const [prods, ops] = await Promise.all([
            api.get("/api/products", { page_size: 100 }),
            api.get("/api/operations"),
        ]);

        const prodSel = document.getElementById("routingProductFilter");
        const rtProdSel = document.getElementById("rtProductId");
        (prods.items || []).forEach((p) => {
            prodSel?.add(new Option(`${p.product_id} - ${p.name}`, p.product_id));
            rtProdSel?.add(new Option(`${p.product_id} - ${p.name}`, p.product_id));
        });

        document.getElementById("operationsTableBody").innerHTML = (ops || [])
            .map(
                (o) => `<tr>
                    <td class="fw-semibold">${esc(o.operation_code)}</td>
                    <td>${esc(o.name)}</td>
                    <td>${esc(o.operation_type)}</td>
                    <td>${o.default_run_minutes_per_unit}</td>
                    <td>${o.default_setup_minutes}</td>
                </tr>`
            )
            .join("");

        function renderFlow(routing) {
            setText("routingFlowLabel", `${routing.routing_id} (${routing.product_id})`);
            const container = document.getElementById("routingFlowContainer");
            const steps = (routing.steps || []).sort((a, b) => a.sequence_number - b.sequence_number);
            container.innerHTML = steps
                .map(
                    (s, idx) => `
                        <div class="routing-step-box">
                            <div class="small text-muted fw-bold">Step ${s.sequence_number}</div>
                            <div class="fw-bold text-dark">${esc(s.operation_code)}</div>
                            <div class="small">${esc(s.operation_name || "")}</div>
                            <div class="small text-primary mt-1">Run: ${s.duration_per_unit_minutes}m/u · Setup: ${s.setup_minutes}m</div>
                            <div class="small text-muted">Machines: ${esc((s.eligible_machines || []).join(", ") || "All")}</div>
                        </div>
                        ${idx < steps.length - 1 ? '<span class="routing-arrow"><i class="bi bi-arrow-right"></i></span>' : ""}
                    `
                )
                .join("");
        }

        async function loadRoutings() {
            const list = await api.get("/api/routings", { product_id: prodSel?.value });
            const tbody = document.getElementById("routingsTableBody");
            tbody.innerHTML = (list || [])
                .map(
                    (r) => `<tr>
                        <td class="fw-semibold">${esc(r.routing_id)}</td>
                        <td>${esc(r.product_id)}</td>
                        <td>v${esc(r.version)}</td>
                        <td>${api.statusBadge(r.is_active ? "Active" : "Inactive")}</td>
                        <td>${(r.steps || []).length}</td>
                        <td><button class="btn btn-outline-primary btn-sm py-0 px-2" data-flow-rt="${esc(JSON.stringify(r))}">Inspect Flow</button></td>
                    </tr>`
                )
                .join("");

            tbody.querySelectorAll("[data-flow-rt]").forEach((btn) =>
                btn.addEventListener("click", () => renderFlow(JSON.parse(btn.getAttribute("data-flow-rt"))))
            );
            if (list?.length) renderFlow(list[0]);
        }

        document.getElementById("btnNewRouting")?.addEventListener("click", () => openModal("routingModal"));
        document.getElementById("routingForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                const codes = document.getElementById("rtOperationCodes").value.split(",").map((c) => c.trim()).filter(Boolean);
                await api.post("/api/routings", {
                    product_id: document.getElementById("rtProductId").value,
                    name: document.getElementById("rtName").value,
                    version: document.getElementById("rtVersion").value,
                    steps: codes.map((code, i) => ({
                        operation_code: code,
                        sequence_number: i + 1,
                        duration_per_unit_minutes: 2.0,
                        setup_minutes: 15,
                        labor_required: 1,
                    })),
                });
                api.notify("Routing created.", "success");
                closeModal("routingModal");
                loadRoutings();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });
        prodSel?.addEventListener("change", loadRoutings);
        await loadRoutings();
    }

    /* =========================================================================
       5. MACHINES
       ========================================================================= */
    async function initMachines() {
        async function load() {
            const resp = await api.get("/api/machines", {
                search: document.getElementById("machSearch")?.value,
                status: document.getElementById("machStatusFilter")?.value,
                page_size: 100,
            });
            const tbody = document.getElementById("machinesTableBody");
            tbody.innerHTML = (resp.items || [])
                .map(
                    (m) => `<tr>
                        <td class="fw-semibold">${esc(m.machine_id)}</td>
                        <td>${esc(m.name)}</td>
                        <td>${esc(m.machine_type)}</td>
                        <td>${esc(m.work_center)}</td>
                        <td>${m.capacity_per_hour}</td>
                        <td>$${m.hourly_operating_cost}</td>
                        <td>${api.statusBadge(m.status)}</td>
                        <td><button class="btn btn-outline-secondary btn-sm py-0 px-2" data-edit-mach="${esc(JSON.stringify(m))}">Edit</button></td>
                    </tr>`
                )
                .join("");

            tbody.querySelectorAll("[data-edit-mach]").forEach((btn) =>
                btn.addEventListener("click", () => {
                    const m = JSON.parse(btn.getAttribute("data-edit-mach"));
                    document.getElementById("machEditId").value = m.machine_id;
                    document.getElementById("machineModalTitle").textContent = `Edit ${m.machine_id}`;
                    document.getElementById("machName").value = m.name;
                    document.getElementById("machType").value = m.machine_type;
                    document.getElementById("machWorkcenter").value = m.work_center;
                    document.getElementById("machStatus").value = m.status;
                    document.getElementById("machCap").value = m.capacity_per_hour;
                    document.getElementById("machCost").value = m.hourly_operating_cost;
                    openModal("machineModal");
                })
            );
        }

        document.getElementById("btnNewMachine")?.addEventListener("click", () => {
            document.getElementById("machEditId").value = "";
            document.getElementById("machineModalTitle").textContent = "Add Machine";
            document.getElementById("machineForm").reset();
            openModal("machineModal");
        });

        document.getElementById("machineForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const editId = document.getElementById("machEditId").value;
            const payload = {
                name: document.getElementById("machName").value,
                machine_type: document.getElementById("machType").value,
                work_center: document.getElementById("machWorkcenter").value,
                capacity_per_hour: Number(document.getElementById("machCap").value),
                hourly_operating_cost: Number(document.getElementById("machCost").value),
            };
            try {
                if (editId) {
                    payload.status = document.getElementById("machStatus").value;
                    await api.put(`/api/machines/${editId}`, payload);
                    api.notify(`Machine ${editId} updated.`, "success");
                } else {
                    await api.post("/api/machines", payload);
                    api.notify("Machine added.", "success");
                }
                closeModal("machineModal");
                load();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });
        document.getElementById("machFilterBtn")?.addEventListener("click", load);
        await load();
    }

    /* =========================================================================
       6. MACHINE CALENDARS & DOWNTIME
       ========================================================================= */
    async function initCalendars() {
        const machResp = await api.get("/api/machines", { page_size: 100 });
        const fillMachSelect = (elId) => {
            const sel = document.getElementById(elId);
            if (!sel) return;
            (machResp.items || []).forEach((m) => sel.add(new Option(`${m.machine_id} - ${m.name}`, m.machine_id)));
        };
        fillMachSelect("calMachineFilter");
        fillMachSelect("calMachId");
        fillMachSelect("dtMachId");

        async function loadAll() {
            const machineId = document.getElementById("calMachineFilter")?.value || "";
            const [cals, dts, shifts] = await Promise.all([
                api.get("/api/calendars", { machine_id: machineId }),
                api.get("/api/downtime", { machine_id: machineId }),
                api.get("/api/labor-shifts"),
            ]);
            document.getElementById("calendarsTableBody").innerHTML = (cals || [])
                .slice(0, 60)
                .map(
                    (c) => `<tr>
                        <td class="fw-semibold">${esc(c.machine_id)}</td>
                        <td>${esc(c.calendar_date)}</td>
                        <td class="small">${esc(c.shift_start_time)} - ${esc(c.shift_end_time)}</td>
                        <td class="small">${esc(c.break_start_time || "-")} - ${esc(c.break_end_time || "-")}</td>
                        <td>${c.is_working_day ? "Yes" : "No"}</td>
                        <td>${c.is_holiday ? "Yes" : "No"}</td>
                        <td>${c.available_minutes}</td>
                    </tr>`
                )
                .join("");

            document.getElementById("downtimeTableBody").innerHTML = (dts || [])
                .map(
                    (d) => `<tr>
                        <td class="fw-semibold">${esc(d.machine_id)}</td>
                        <td>${api.statusBadge(d.downtime_type)}</td>
                        <td class="small">${esc(api.formatDateTime(d.start_time))}</td>
                        <td class="small">${esc(api.formatDateTime(d.end_time))}</td>
                        <td class="small">${esc(d.reason)}</td>
                    </tr>`
                )
                .join("");

            document.getElementById("laborShiftsTableBody").innerHTML = (shifts || [])
                .slice(0, 30)
                .map(
                    (s) => `<tr>
                        <td>${s.shift_id}</td><td>${esc(s.shift_name)}</td><td>${esc(s.shift_date)} ${esc(s.start_time)}</td>
                        <td>${esc(s.end_time)}</td><td>${s.available_operators}</td><td>${esc(s.skill_category || "General")}</td>
                    </tr>`
                )
                .join("");
        }

        document.getElementById("btnNewCalendar")?.addEventListener("click", () => openModal("calendarModal"));
        document.getElementById("btnNewDowntime")?.addEventListener("click", () => openModal("downtimeModal"));
        document.getElementById("calMachineFilter")?.addEventListener("change", loadAll);

        document.getElementById("calendarForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                await api.post("/api/calendars", {
                    machine_id: document.getElementById("calMachId").value,
                    calendar_date: document.getElementById("calDate").value,
                    shift_start_time: document.getElementById("calShiftStart").value + ":00",
                    shift_end_time: document.getElementById("calShiftEnd").value + ":00",
                    break_start_time: document.getElementById("calBreakStart").value ? document.getElementById("calBreakStart").value + ":00" : null,
                    break_end_time: document.getElementById("calBreakEnd").value ? document.getElementById("calBreakEnd").value + ":00" : null,
                    is_working_day: document.getElementById("calIsWork").checked,
                    is_holiday: document.getElementById("calIsHol").checked,
                });
                api.notify("Calendar window saved.", "success");
                closeModal("calendarModal");
                loadAll();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });

        document.getElementById("downtimeForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                await api.post("/api/downtime", {
                    machine_id: document.getElementById("dtMachId").value,
                    downtime_type: document.getElementById("dtType").value,
                    start_time: document.getElementById("dtStart").value,
                    end_time: document.getElementById("dtEnd").value,
                    reason: document.getElementById("dtReason").value,
                });
                api.notify("Downtime recorded.", "warning");
                closeModal("downtimeModal");
                loadAll();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });
        await loadAll();
    }

    /* =========================================================================
       7. MATERIALS & INVENTORY
       ========================================================================= */
    async function initMaterials() {
        async function loadAll() {
            const [matsResp, lots, shortages] = await Promise.all([
                api.get("/api/materials", {
                    search: document.getElementById("matSearch")?.value,
                    stock_status: document.getElementById("matStockFilter")?.value,
                    page_size: 100,
                }),
                api.get("/api/inventory", { delayed_only: document.getElementById("lotDelayedOnly")?.checked }),
                api.get("/api/inventory/shortages"),
            ]);

            const lotMatSel = document.getElementById("lotMatId");
            if (lotMatSel && lotMatSel.options.length === 0) {
                (matsResp.items || []).forEach((m) => lotMatSel.add(new Option(`${m.material_id} - ${m.name}`, m.material_id)));
            }

            document.getElementById("materialsTableBody").innerHTML = (matsResp.items || [])
                .map(
                    (m) => `<tr>
                        <td class="fw-semibold">${esc(m.material_id)}</td>
                        <td>${esc(m.name)}</td><td>${esc(m.category)}</td>
                        <td>${m.available_quantity} ${esc(m.unit)}</td>
                        <td>${m.reorder_level}</td>
                        <td>${api.statusBadge(m.stock_status)}</td>
                    </tr>`
                )
                .join("");

            document.getElementById("lotsTableBody").innerHTML = (lots || [])
                .slice(0, 60)
                .map(
                    (l) => `<tr>
                        <td class="small fw-semibold">${esc(l.lot_number)}</td>
                        <td class="small">${esc(l.material_id)}</td>
                        <td>${l.available_quantity}</td>
                        <td class="small">${esc(l.availability_date)}</td>
                        <td>${l.is_delayed ? '<span class="badge bg-danger">Delayed</span>' : '<span class="badge bg-success">On Time</span>'}</td>
                    </tr>`
                )
                .join("");

            const shortArr = shortages.shortages || shortages || [];
            document.getElementById("shortagesTableBody").innerHTML = shortArr.length
                ? shortArr
                      .map(
                          (s) => `<tr>
                              <td class="fw-semibold">${esc(s.material_id)}</td><td>${esc(s.name)}</td>
                              <td>${s.required_quantity}</td><td>${s.available_quantity}</td>
                              <td class="text-danger fw-bold">${s.shortfall}</td>
                          </tr>`
                      )
                      .join("")
                : `<tr><td colspan="5" class="text-center text-muted py-3">No active material shortages detected.</td></tr>`;
        }

        document.getElementById("btnNewMaterial")?.addEventListener("click", () => openModal("materialModal"));
        document.getElementById("btnReceiveLot")?.addEventListener("click", () => {
            document.getElementById("lotAvailDate").value = new Date().toISOString().slice(0, 10);
            openModal("receiveLotModal");
        });
        document.getElementById("matSearch")?.addEventListener("change", loadAll);
        document.getElementById("matStockFilter")?.addEventListener("change", loadAll);
        document.getElementById("lotDelayedOnly")?.addEventListener("change", loadAll);

        document.getElementById("materialForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                await api.post("/api/materials", {
                    name: document.getElementById("matName").value,
                    category: document.getElementById("matCategory").value,
                    unit: document.getElementById("matUnit").value,
                    unit_cost: Number(document.getElementById("matCost").value),
                    reorder_level: Number(document.getElementById("matReorder").value),
                });
                api.notify("Material created.", "success");
                closeModal("materialModal");
                loadAll();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });

        document.getElementById("receiveLotForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                await api.post("/api/inventory/receive", {
                    material_id: document.getElementById("lotMatId").value,
                    lot_number: document.getElementById("lotNumber").value,
                    quantity: Number(document.getElementById("lotQty").value),
                    availability_date: document.getElementById("lotAvailDate").value,
                    supplier_name: document.getElementById("lotSupplierRef").value,
                });
                api.notify("Inventory lot received.", "success");
                closeModal("receiveLotModal");
                loadAll();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });
        await loadAll();
    }

    /* =========================================================================
       8. CHANGEOVER MANAGEMENT
       ========================================================================= */
    async function initChangeovers() {
        const [machResp, prodResp] = await Promise.all([
            api.get("/api/machines", { page_size: 100 }),
            api.get("/api/products", { page_size: 100 }),
        ]);
        const machFilter = document.getElementById("coMachineFilter");
        const coFormMach = document.getElementById("coFormMach");
        (machResp.items || []).forEach((m) => {
            machFilter?.add(new Option(`${m.machine_id} - ${m.name}`, m.machine_id));
            coFormMach?.add(new Option(`${m.machine_id} - ${m.name}`, m.machine_id));
        });
        const fromSel = document.getElementById("coFormFrom");
        const toSel = document.getElementById("coFormTo");
        (prodResp.items || []).forEach((p) => {
            fromSel?.add(new Option(`${p.product_id} (${p.sku})`, p.product_id));
            toSel?.add(new Option(`${p.product_id} (${p.sku})`, p.product_id));
        });

        async function load() {
            const list = await api.get("/api/changeovers", {
                machine_id: machFilter?.value,
                from_product_id: document.getElementById("coFromFilter")?.value,
                to_product_id: document.getElementById("coToFilter")?.value,
                limit: 150,
            });
            document.getElementById("changeoversTableBody").innerHTML = (list || [])
                .map(
                    (c) => `<tr>
                        <td class="fw-semibold">${esc(c.machine_id || "ALL")}</td>
                        <td>${esc(c.from_product_id)}</td>
                        <td>${esc(c.to_product_id)}</td>
                        <td><span class="badge bg-warning-subtle text-dark">${c.changeover_minutes} min</span></td>
                        <td class="small">${esc(c.notes || "Sequence Setup")}</td>
                        <td>${c.cleaning_required ? '<span class="badge bg-info">Yes</span>' : "No"}</td>
                    </tr>`
                )
                .join("");
        }

        document.getElementById("btnNewChangeover")?.addEventListener("click", () => openModal("changeoverModal"));
        document.getElementById("coFilterBtn")?.addEventListener("click", load);
        document.getElementById("changeoverForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                await api.post("/api/changeovers", {
                    machine_id: document.getElementById("coFormMach").value,
                    from_product_id: document.getElementById("coFormFrom").value,
                    to_product_id: document.getElementById("coFormTo").value,
                    changeover_minutes: Number(document.getElementById("coFormMins").value),
                    notes: document.getElementById("coFormType").value,
                });
                api.notify("Changeover rule saved.", "success");
                closeModal("changeoverModal");
                load();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });
        await load();
    }

    /* =========================================================================
       9. PRODUCTION SCHEDULER
       ========================================================================= */
    async function initScheduler() {
        async function loadRuns() {
            const runs = await api.get("/api/scheduling/runs");
            document.getElementById("schedRunsTableBody").innerHTML = (runs || [])
                .map(
                    (r) => `<tr>
                        <td><input type="checkbox" class="form-check-input cmp-run-chk" value="${esc(r.run_id)}"></td>
                        <td class="fw-semibold">${esc(r.run_id)}</td>
                        <td>${esc(r.run_name)}</td>
                        <td>${api.statusBadge(r.solver_status)}</td>
                        <td>${r.makespan_minutes}m</td>
                        <td>${r.total_lateness_minutes}m</td>
                        <td>${r.total_changeover_minutes}m</td>
                        <td><button class="btn btn-outline-primary btn-sm py-0 px-2" data-open-gantt="${esc(r.run_id)}">Gantt</button></td>
                    </tr>`
                )
                .join("");

            document.querySelectorAll("[data-open-gantt]").forEach((btn) =>
                btn.addEventListener("click", () => {
                    window.PlantOpsApp.selectedRunId = btn.getAttribute("data-open-gantt");
                    window.PlantOpsApp.navigate("gantt");
                })
            );
        }

        document.getElementById("schedulerRunForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const btn = document.getElementById("btnRunSolver");
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Solving Schedule...';
            try {
                const res = await api.post("/api/scheduling/run", {
                    run_name: document.getElementById("schedRunName").value,
                    max_orders: Number(document.getElementById("schedMaxOrders").value),
                    solver_time_limit_seconds: Number(document.getElementById("schedTimeLimit").value),
                    weight_makespan: Number(document.getElementById("schedWMakespan").value),
                    weight_lateness: Number(document.getElementById("schedWLateness").value),
                    weight_changeover: Number(document.getElementById("schedWChangeover").value),
                });
                const box = document.getElementById("schedLastResultBox");
                box.innerHTML = `<div class="alert alert-info small mb-0">
                    <strong>Run ${esc(res.run_id)}</strong> finished with status <strong>${esc(res.solver_status)}</strong>.
                    Makespan: ${res.makespan_minutes}m | Lateness: ${res.total_lateness_minutes}m | Scheduled Ops: ${res.scheduled_operation_count}
                    ${res.infeasibility_reasons?.length ? `<div class="text-danger mt-1">${esc(res.infeasibility_reasons.join("; "))}</div>` : ""}
                </div>`;
                api.notify(`Scheduling run ${res.run_id}: ${res.solver_status}`, "success");
                loadRuns();
            } catch (err) {
                api.notify(`Solver error: ${err.message}`, "error");
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<i class="bi bi-cpu-fill me-2"></i>Execute CP-SAT Scheduler';
            }
        });

        document.getElementById("btnCompareSelectedRuns")?.addEventListener("click", async () => {
            const ids = Array.from(document.querySelectorAll(".cmp-run-chk:checked")).map((c) => c.value);
            if (ids.length < 2) {
                api.notify("Select at least 2 runs to compare.", "warning");
                return;
            }
            const cmp = await api.get("/api/scheduling/compare", { run_ids: ids.join(",") });
            document.getElementById("schedCompareCard").style.display = "block";
            document.getElementById("schedCompareBody").innerHTML = (cmp.runs || cmp || [])
                .map(
                    (r) => `<tr>
                        <td class="fw-semibold">${esc(r.run_id)}</td><td>${esc(r.run_name)}</td><td>${api.statusBadge(r.solver_status)}</td>
                        <td>${r.makespan_minutes}</td><td>${r.total_lateness_minutes}</td><td>${r.total_changeover_minutes}</td>
                        <td>${r.delayed_order_count}</td><td>${r.execution_duration_seconds}s</td>
                    </tr>`
                )
                .join("");
        });

        await loadRuns();
    }

    /* =========================================================================
       10. INTERACTIVE GANTT PLANNING
       ========================================================================= */
    async function initGantt() {
        const [runs, machResp] = await Promise.all([
            api.get("/api/scheduling/runs"),
            api.get("/api/machines", { page_size: 100 }),
        ]);

        const runSel = document.getElementById("ganttRunSelect");
        (runs || []).forEach((r) => runSel.add(new Option(`${r.run_id} (${r.solver_status}) - ${r.run_name}`, r.run_id)));
        if (window.PlantOpsApp.selectedRunId) {
            runSel.value = window.PlantOpsApp.selectedRunId;
        }

        const machSel = document.getElementById("ganttMachineFilter");
        (machResp.items || []).forEach((m) => machSel.add(new Option(`${m.machine_id} - ${m.name}`, m.machine_id)));

        activeGanttInstance = new window.PlantOpsGantt("ganttBoardContainer", {
            onTaskClick: (task) => {
                document.getElementById("ganttTaskModalBody").innerHTML = `
                    <table class="table table-sm mb-0 small">
                        <tr><th>Schedule ID</th><td>${esc(task.schedule_id)}</td></tr>
                        <tr><th>Order ID</th><td>${esc(task.order_id)}</td></tr>
                        <tr><th>Operation</th><td>${esc(task.operation_id)} (${esc(task.operation_code)})</td></tr>
                        <tr><th>Machine</th><td>${esc(task.machine_id)}</td></tr>
                        <tr><th>Product</th><td>${esc(task.product_id)}</td></tr>
                        <tr><th>Start</th><td>${esc(api.formatDateTime(task.start_time))}</td></tr>
                        <tr><th>End</th><td>${esc(api.formatDateTime(task.end_time))}</td></tr>
                        <tr><th>Duration / Changeover</th><td>${task.duration_minutes}m / ${task.changeover_minutes}m</td></tr>
                        <tr><th>Lateness</th><td>${task.is_late ? `<span class="text-danger fw-bold">${task.lateness_minutes} min late</span>` : '<span class="text-success">On Time</span>'}</td></tr>
                    </table>
                `;
                openModal("ganttTaskModal");
            },
        });

        async function loadBoard() {
            const runId = runSel.value;
            if (!runId) {
                activeGanttInstance.render({ tasks: [], machines: [], downtimes: [], shift_windows: [] });
                return;
            }
            const data = await api.get(`/api/scheduling/runs/${runId}/gantt`, {
                machine_id: machSel.value,
                order_id: document.getElementById("ganttOrderFilter").value,
            });
            setText("ganttSummaryText", `${data.tasks.length} operations across ${data.machines.length} machines`);
            activeGanttInstance.render(data);
        }

        document.querySelectorAll("[data-gantt-zoom]").forEach((btn) => {
            btn.addEventListener("click", () => {
                document.querySelectorAll("[data-gantt-zoom]").forEach((b) => {
                    b.classList.remove("btn-indigo");
                    b.classList.add("btn-outline-secondary");
                });
                btn.classList.remove("btn-outline-secondary");
                btn.classList.add("btn-indigo");
                activeGanttInstance.setZoom(btn.getAttribute("data-gantt-zoom"));
            });
        });

        document.getElementById("ganttLoadBtn")?.addEventListener("click", loadBoard);
        runSel?.addEventListener("change", loadBoard);
        await loadBoard();
    }

    /* =========================================================================
       11. MACHINE UTILIZATION
       ========================================================================= */
    async function initUtilization() {
        const runs = await api.get("/api/scheduling/runs");
        const runSel = document.getElementById("utilRunSelect");
        runSel.add(new Option("Latest Run", ""));
        (runs || []).forEach((r) => runSel.add(new Option(`${r.run_id} - ${r.run_name}`, r.run_id)));

        async function load() {
            const data = await api.get("/api/dashboard/machine-utilization", { run_id: runSel.value });
            const list = data.machines || [];
            charts.renderBar("utilBarChart", list.map((m) => m.machine_id), list.map((m) => m.utilization_pct), "Utilization %", "#4338ca");
            charts.renderDoughnut("utilFleetChart", data.availability_chart.labels, data.availability_chart.values);
            document.getElementById("utilTableBody").innerHTML = list
                .map(
                    (m) => `<tr>
                        <td class="fw-semibold">${esc(m.machine_id)}</td><td>${esc(m.machine_name)}</td>
                        <td>${api.statusBadge(m.status)}</td><td>${m.scheduled_minutes}</td>
                        <td>${m.available_minutes}</td>
                        <td><div class="d-flex align-items-center gap-2"><div class="progress flex-grow-1" style="height:8px"><div class="progress-bar bg-indigo" style="width:${Math.min(100, m.utilization_pct)}%"></div></div><span class="small fw-semibold">${m.utilization_pct}%</span></div></td>
                    </tr>`
                )
                .join("");
        }
        document.getElementById("utilRefreshBtn")?.addEventListener("click", load);
        runSel?.addEventListener("change", load);
        await load();
    }

    /* =========================================================================
       12. EXCEPTIONS & ANOMALIES
       ========================================================================= */
    async function initExceptions() {
        async function load() {
            const resp = await api.get("/api/exceptions", {
                severity: document.getElementById("excSeverityFilter")?.value,
                resolution_status: document.getElementById("excStatusFilter")?.value,
                entity_id: document.getElementById("excEntityFilter")?.value,
            });
            const items = resp.items || [];
            document.getElementById("exceptionsTableBody").innerHTML = items.length
                ? items
                      .map(
                          (x) => `<tr>
                              <td class="fw-semibold">${esc(x.anomaly_id)}</td>
                              <td>${esc(x.issue_type)}</td>
                              <td>${api.statusBadge(x.severity)}</td>
                              <td>${esc(x.entity_type)}:${esc(x.entity_id)}</td>
                              <td class="small">${esc(x.explanation)}</td>
                              <td>${api.statusBadge(x.resolution_status)}</td>
                              <td>${x.resolution_status !== "Resolved" ? `<button class="btn btn-outline-success btn-sm py-0 px-2" data-resolve-exc="${esc(x.anomaly_id)}">Resolve</button>` : '<span class="text-muted small">Done</span>'}</td>
                          </tr>`
                      )
                      .join("")
                : `<tr><td colspan="7" class="text-center text-muted py-3">No matching exceptions found.</td></tr>`;

            document.querySelectorAll("[data-resolve-exc]").forEach((btn) =>
                btn.addEventListener("click", async () => {
                    try {
                        const actor = api.getCurrentUser()?.username || "planner";
                        await api.put(`/api/exceptions/${btn.getAttribute("data-resolve-exc")}/resolve`, {
                            resolution_status: "Resolved",
                            resolved_by: actor,
                            resolution_reason: "Resolved via PlantOps Exceptions Console",
                        });
                        api.notify("Exception marked as Resolved.", "success");
                        load();
                    } catch (err) {
                        api.notify(err.message, "error");
                    }
                })
            );
        }

        document.getElementById("btnRunAnomalyDetect")?.addEventListener("click", async () => {
            try {
                const res = await api.post("/api/exceptions/detect", {});
                api.notify(`Scan finished: ${res.detected_count} anomalies detected (${res.newly_saved_count} saved).`, "info");
                load();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });
        document.getElementById("excFilterBtn")?.addEventListener("click", load);
        await load();
    }

    /* =========================================================================
       13. GROUND TRUTH & VALIDATION
       ========================================================================= */
    async function initGroundTruth() {
        async function loadValidation(runFresh = false) {
            const rep = runFresh ? await api.post("/api/validation/run", {}) : await api.get("/api/validation/report");
            document.getElementById("valOverallBadge").innerHTML = api.statusBadge(rep.overall_status);
            const issuesByCheck = new Map();
            (rep.issues || []).forEach((i) => {
                if (!issuesByCheck.has(i.check)) issuesByCheck.set(i.check, []);
                issuesByCheck.get(i.check).push(i.message);
            });
            document.getElementById("validationTableBody").innerHTML = (rep.checks || [])
                .map(
                    (c, idx) => `<tr>
                        <td>${idx + 1}</td><td class="fw-semibold">${esc(c.check)}</td>
                        <td>${api.statusBadge(c.status)}</td><td>${c.issue_count}</td>
                        <td class="small text-muted">${esc((issuesByCheck.get(c.check) || []).slice(0, 2).join(" | ") || "Clean")}</td>
                    </tr>`
                )
                .join("");
        }

        async function loadGroundTruth() {
            const gt = await api.get("/api/ground-truth/evaluation");
            setText("gtPrecision", `${Math.round((gt.precision || 0) * 100)}%`);
            setText("gtRecall", `${Math.round((gt.recall || 0) * 100)}%`);
            setText("gtF1", `${Math.round((gt.f1_score || 0) * 100)}%`);
            setText("gtTpFp", `${gt.true_positives ?? 0} / ${gt.false_positives ?? 0}`);
            document.getElementById("gtDetailsTableBody").innerHTML = (gt.comparisons || [])
                .map(
                    (c) => `<tr>
                        <td class="fw-semibold">${esc(c.gt_id)}</td><td>${esc(c.issue_type)}</td>
                        <td>${esc(c.entity_type)}:${esc(c.entity_id)}</td>
                        <td>${c.expected_is_anomaly ? "Anomaly" : "Clean"}</td>
                        <td>${c.actual_detected ? "Detected" : "None"}</td>
                        <td>${api.statusBadge(c.outcome)}</td>
                    </tr>`
                )
                .join("");
        }

        document.getElementById("btnRunValidation")?.addEventListener("click", async () => {
            await loadValidation(true);
            api.notify("14-point validation report refreshed.", "success");
        });
        document.getElementById("btnRefreshGt")?.addEventListener("click", loadGroundTruth);
        await Promise.all([loadValidation(false), loadGroundTruth()]);
    }

    /* =========================================================================
       14. REPORTS & ANALYTICS
       ========================================================================= */
    async function initReports() {
        const [runs, tooling] = await Promise.all([
            api.get("/api/scheduling/runs"),
            api.get("/api/tooling"),
        ]);
        const sel = document.getElementById("repRunSelect");
        (runs || []).forEach((r) => sel.add(new Option(`${r.run_id} (${r.solver_status})`, r.run_id)));

        document.getElementById("repToolingBody").innerHTML = (tooling || [])
            .map(
                (t) => `<tr>
                    <td class="fw-semibold">${esc(t.tooling_id)}</td><td>${esc(t.name)}</td>
                    <td>${esc(t.tooling_type || "-")}</td><td>${t.total_quantity}</td><td>${t.available_quantity}</td>
                </tr>`
            )
            .join("");

        async function loadMetrics() {
            if (!sel.value) return;
            const m = await api.get(`/api/scheduling/runs/${sel.value}/metrics`);
            setText("repMakespan", m.makespan_minutes);
            setText("repLateness", m.total_lateness_minutes);
            setText("repChangeover", m.total_changeover_minutes);
            setText("repAvgUtil", `${m.avg_machine_utilization_pct}%`);
            document.getElementById("repSummaryDetails").innerHTML = `
                <ul class="list-group list-group-flush small">
                    <li class="list-group-item d-flex justify-content-between"><span>Run ID</span><strong>${esc(m.run_id)}</strong></li>
                    <li class="list-group-item d-flex justify-content-between"><span>Solver Status</span><strong>${esc(m.solver_status)}</strong></li>
                    <li class="list-group-item d-flex justify-content-between"><span>Scheduled Orders / Ops</span><strong>${m.scheduled_orders} / ${m.scheduled_operations}</strong></li>
                    <li class="list-group-item d-flex justify-content-between"><span>Average Lateness</span><strong>${m.average_lateness_minutes} min</strong></li>
                    <li class="list-group-item d-flex justify-content-between"><span>On-Time Delivery %</span><strong>${m.on_time_delivery_pct}%</strong></li>
                    <li class="list-group-item d-flex justify-content-between"><span>Execution Duration</span><strong>${m.execution_duration_seconds}s</strong></li>
                </ul>
            `;
        }

        sel?.addEventListener("change", loadMetrics);
        document.getElementById("btnExportCsv")?.addEventListener("click", () => {
            const q = sel.value ? `?run_id=${encodeURIComponent(sel.value)}` : "";
            api.downloadCsv(`/api/analytics/export${q}`);
        });
        await loadMetrics();
    }

    /* =========================================================================
       15. AUDIT LOGS & STATE CHANGES
       ========================================================================= */
    async function initAuditLogs() {
        async function load() {
            const [audits, states] = await Promise.all([
                api.get("/api/audit-logs", { limit: 100 }),
                api.get("/api/state-changes", { limit: 100 }),
            ]);
            document.getElementById("auditLogsBody").innerHTML = (audits || [])
                .map(
                    (a) => `<tr>
                        <td><span class="badge bg-secondary-subtle text-dark">${esc(a.action)}</span></td>
                        <td>${esc(a.entity_type)}</td><td class="fw-semibold">${esc(a.entity_id)}</td>
                        <td>${esc(a.username)}</td><td class="small">${esc(api.formatDateTime(a.created_at))}</td>
                    </tr>`
                )
                .join("");

            document.getElementById("stateChangesBody").innerHTML = (states || [])
                .map(
                    (s) => `<tr>
                        <td>${esc(s.entity_type)}</td><td class="fw-semibold">${esc(s.entity_id)}</td>
                        <td class="small">${esc(s.previous_state)} → <strong>${esc(s.new_state)}</strong></td>
                        <td>${esc(s.changed_by)}</td><td class="small">${esc(s.reason)}</td>
                    </tr>`
                )
                .join("");
        }
        document.getElementById("auditRefreshBtn")?.addEventListener("click", load);
        await load();
    }

    /* =========================================================================
       16. USER MANAGEMENT
       ========================================================================= */
    async function initUsers() {
        async function load() {
            try {
                const users = await api.get("/api/users");
                document.getElementById("usersTableBody").innerHTML = (users || [])
                    .map(
                        (u) => `<tr>
                            <td class="fw-semibold">${esc(u.user_id)}</td><td>${esc(u.username)}</td>
                            <td>${esc(u.full_name)}</td><td>${esc(u.email)}</td>
                            <td>${(u.roles || []).map((r) => `<span class="badge bg-indigo-subtle text-primary-emphasis me-1">${esc(r)}</span>`).join("")}</td>
                            <td>${api.statusBadge(u.is_active ? "Active" : "Inactive")}</td>
                            <td><button class="btn btn-outline-secondary btn-sm py-0 px-2" data-toggle-user="${esc(u.user_id)}">${u.is_active ? "Disable" : "Enable"}</button></td>
                        </tr>`
                    )
                    .join("");

                document.querySelectorAll("[data-toggle-user]").forEach((btn) =>
                    btn.addEventListener("click", async () => {
                        try {
                            await api.patch(`/api/users/${btn.getAttribute("data-toggle-user")}/toggle-active`, {});
                            api.notify("User account status toggled.", "success");
                            load();
                        } catch (err) {
                            api.notify(err.message, "error");
                        }
                    })
                );
            } catch (err) {
                document.getElementById("usersTableBody").innerHTML = `<tr><td colspan="7" class="text-danger text-center py-3">${esc(err.message)} (OT/IT Administrator sign-in required)</td></tr>`;
            }
        }

        document.getElementById("btnNewUser")?.addEventListener("click", () => openModal("userModal"));
        document.getElementById("userForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                await api.post("/api/users", {
                    username: document.getElementById("usrUsername").value,
                    full_name: document.getElementById("usrFullName").value,
                    email: document.getElementById("usrEmail").value,
                    role_name: document.getElementById("usrRole").value,
                    password: document.getElementById("usrPassword").value,
                });
                api.notify("User created.", "success");
                closeModal("userModal");
                load();
            } catch (err) {
                api.notify(err.message, "error");
            }
        });
        await load();
    }

    /* =========================================================================
       17. SETTINGS
       ========================================================================= */
    async function initSettings() {
        const s = await api.get("/api/settings");
        document.getElementById("setPlantName").value = s.plant_name || "";
        document.getElementById("setSolverLimit").value = s.default_solver_time_limit_seconds || 30;
        document.getElementById("setShiftHours").value = s.default_shift_hours || "";
        document.getElementById("setWMakespan").value = s.default_weight_makespan ?? 1.0;
        document.getElementById("setWLateness").value = s.default_weight_lateness ?? 3.0;
        document.getElementById("setWChangeover").value = s.default_weight_changeover ?? 1.5;

        setText("setApiEndpoint", api.API_BASE);
        const curUser = api.getCurrentUser();
        setText("setCurrentActor", curUser ? `${curUser.username} (${(curUser.roles || []).join(", ")})` : "Unauthenticated");

        document.getElementById("settingsForm")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                await api.put("/api/settings", {
                    plant_name: document.getElementById("setPlantName").value,
                    default_solver_time_limit_seconds: Number(document.getElementById("setSolverLimit").value),
                    default_shift_hours: document.getElementById("setShiftHours").value,
                    default_weight_makespan: Number(document.getElementById("setWMakespan").value),
                    default_weight_lateness: Number(document.getElementById("setWLateness").value),
                    default_weight_changeover: Number(document.getElementById("setWChangeover").value),
                });
                api.notify("System settings saved.", "success");
            } catch (err) {
                api.notify(err.message, "error");
            }
        });
    }

    window.PlantOpsPages = {
        overview: initOverview,
        orders: initOrders,
        products: initProducts,
        routings: initRoutings,
        machines: initMachines,
        calendars: initCalendars,
        materials: initMaterials,
        changeovers: initChangeovers,
        scheduler: initScheduler,
        gantt: initGantt,
        utilization: initUtilization,
        exceptions: initExceptions,
        "ground-truth": initGroundTruth,
        reports: initReports,
        "audit-logs": initAuditLogs,
        users: initUsers,
        settings: initSettings,
    };
})(window);

