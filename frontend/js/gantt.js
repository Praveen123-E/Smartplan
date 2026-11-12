/**
 * PlantOps Interactive Gantt Chart Component
 * Renders machine rows, operation schedule bars, changeover setups,
 * machine downtime blocks, and shift boundary markers without external frameworks.
 */
(function (window) {
    "use strict";

    class PlantOpsGantt {
        constructor(containerId, options = {}) {
            this.container = document.getElementById(containerId);
            this.onTaskClick = options.onTaskClick || null;
            this.zoomMode = "day"; // "hour" | "day" | "week"
            this.data = null;
            this.tooltipEl = this._ensureTooltip();
        }

        _ensureTooltip() {
            let el = document.getElementById("plantopsGanttTooltip");
            if (!el) {
                el = document.createElement("div");
                el.id = "plantopsGanttTooltip";
                el.className = "gantt-tooltip";
                document.body.appendChild(el);
            }
            return el;
        }

        setZoom(mode) {
            this.zoomMode = mode || "day";
            if (this.data) {
                this.render(this.data);
            }
        }

        _pxPerMinute() {
            if (this.zoomMode === "hour") return 1.8;
            if (this.zoomMode === "week") return 0.14;
            return 0.45; // default "day" zoom: ~27px per hour
        }

        _priorityClass(task) {
            if (task.is_urgent || Number(task.priority) === 1) return "gantt-op-urgent";
            if (Number(task.priority) === 2) return "gantt-op-high";
            if (Number(task.priority) <= 4) return "gantt-op-medium";
            return "gantt-op-low";
        }

        render(ganttPayload) {
            this.data = ganttPayload;
            if (!this.container) return;

            const escapeHtml = window.PlantOpsApi.escapeHtml;
            const tasks = Array.isArray(ganttPayload?.tasks) ? ganttPayload.tasks : [];
            const machines = Array.isArray(ganttPayload?.machines) ? ganttPayload.machines : [];
            const downtimes = Array.isArray(ganttPayload?.downtimes) ? ganttPayload.downtimes : [];
            const shiftWindows = Array.isArray(ganttPayload?.shift_windows) ? ganttPayload.shift_windows : [];

            if (!tasks.length && !downtimes.length) {
                this.container.innerHTML = `
                    <div class="empty-state-box">
                        <i class="bi bi-bar-chart-steps"></i>
                        <h6 class="fw-semibold text-dark">No Scheduled Operations Found</h6>
                        <p class="small mb-0">Run the CP-SAT scheduler or adjust filters to inspect the Gantt chart.</p>
                    </div>
                `;
                return;
            }

            // Compute timeline bounds from tasks and downtimes
            const allTimestamps = [];
            tasks.forEach((t) => {
                if (t.changeover_start_time) allTimestamps.push(new Date(t.changeover_start_time).getTime());
                allTimestamps.push(new Date(t.start_time).getTime());
                allTimestamps.push(new Date(t.end_time).getTime());
            });
            downtimes.forEach((d) => {
                allTimestamps.push(new Date(d.start_time).getTime());
                allTimestamps.push(new Date(d.end_time).getTime());
            });

            const validTimes = allTimestamps.filter((ts) => !Number.isNaN(ts));
            const rawMin = validTimes.length ? Math.min(...validTimes) : Date.now();
            const rawMax = validTimes.length ? Math.max(...validTimes) : rawMin + 8 * 3600 * 1000;

            // Snap start down to the nearest hour and add 2-hour tail padding
            const minDate = new Date(rawMin);
            minDate.setMinutes(0, 0, 0);
            const minMs = minDate.getTime();
            const totalMinutes = Math.max(240, Math.ceil((rawMax - minMs) / 60000) + 120);

            const pxPerMin = this._pxPerMinute();
            const trackWidth = Math.max(900, Math.round(totalMinutes * pxPerMin));

            // Group items by machine_id
            const tasksByMachine = new Map();
            tasks.forEach((t) => {
                if (!tasksByMachine.has(t.machine_id)) tasksByMachine.set(t.machine_id, []);
                tasksByMachine.get(t.machine_id).push(t);
            });

            const dtByMachine = new Map();
            downtimes.forEach((d) => {
                if (!dtByMachine.has(d.machine_id)) dtByMachine.set(d.machine_id, []);
                dtByMachine.get(d.machine_id).push(d);
            });

            const shiftsByMachine = new Map();
            shiftWindows.forEach((s) => {
                if (!shiftsByMachine.has(s.machine_id)) shiftsByMachine.set(s.machine_id, []);
                shiftsByMachine.get(s.machine_id).push(s);
            });

            // Only show machines that have tasks or explicit downtimes unless machine list is short
            let visibleMachines = machines.filter(
                (m) => tasksByMachine.has(m.machine_id) || dtByMachine.has(m.machine_id)
            );
            if (!visibleMachines.length) {
                visibleMachines = machines.slice(0, 20);
            }

            // Build time axis ticks
            const tickStepMinutes = this.zoomMode === "hour" ? 60 : this.zoomMode === "week" ? 720 : 240;
            let ticksHtml = "";
            for (let m = 0; m <= totalMinutes; m += tickStepMinutes) {
                const tickDate = new Date(minMs + m * 60000);
                const leftPx = Math.round(m * pxPerMin);
                const label =
                    this.zoomMode === "week"
                        ? tickDate.toLocaleDateString(undefined, { month: "short", day: "numeric" })
                        : tickDate.toLocaleString(undefined, {
                              month: "short",
                              day: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                          });
                ticksHtml += `<div class="gantt-tick" style="left:${leftPx}px">${escapeHtml(label)}</div>`;
            }

            // Build machine rows
            let rowsHtml = "";
            visibleMachines.forEach((mach) => {
                const mTasks = tasksByMachine.get(mach.machine_id) || [];
                const mDowntimes = dtByMachine.get(mach.machine_id) || [];
                const mShifts = shiftsByMachine.get(mach.machine_id) || [];

                let trackElements = "";

                // Shift boundary dashed lines
                mShifts.forEach((sw) => {
                    if (!sw.is_working_day || sw.is_holiday) return;
                    const shiftStartIso = `${sw.date}T${sw.shift_start}`;
                    const ms = new Date(shiftStartIso).getTime();
                    if (Number.isNaN(ms) || ms < minMs || ms > minMs + totalMinutes * 60000) return;
                    const left = ((ms - minMs) / 60000) * pxPerMin;
                    trackElements += `<div class="gantt-shift-line" style="left:${left}px" title="Shift Start ${escapeHtml(sw.date)} ${escapeHtml(sw.shift_start)}"></div>`;
                });

                // Downtime blocks
                mDowntimes.forEach((dt) => {
                    const sMs = new Date(dt.start_time).getTime();
                    const eMs = new Date(dt.end_time).getTime();
                    if (Number.isNaN(sMs) || Number.isNaN(eMs) || eMs <= minMs) return;
                    const clampedStart = Math.max(sMs, minMs);
                    const left = ((clampedStart - minMs) / 60000) * pxPerMin;
                    const width = Math.max(6, ((eMs - clampedStart) / 60000) * pxPerMin);
                    trackElements += `
                        <div class="gantt-downtime-band"
                             style="left:${left}px;width:${width}px"
                             data-downtime="${escapeHtml(JSON.stringify(dt))}">
                        </div>
                    `;
                });

                // Operation bars & changeover strips
                mTasks.forEach((task) => {
                    const sMs = new Date(task.start_time).getTime();
                    const eMs = new Date(task.end_time).getTime();
                    const left = Math.max(0, ((sMs - minMs) / 60000) * pxPerMin);
                    const width = Math.max(18, ((eMs - sMs) / 60000) * pxPerMin);

                    if (task.changeover_minutes > 0 && task.changeover_start_time) {
                        const coStartMs = new Date(task.changeover_start_time).getTime();
                        const coLeft = Math.max(0, ((coStartMs - minMs) / 60000) * pxPerMin);
                        const coWidth = Math.max(4, left - coLeft);
                        trackElements += `
                            <div class="gantt-changeover-bar"
                                 style="left:${coLeft}px;width:${coWidth}px"
                                 title="Changeover Setup: ${task.changeover_minutes} min">
                                ${coWidth > 26 ? `CO ${task.changeover_minutes}m` : ""}
                            </div>
                        `;
                    }

                    const priorityCls = this._priorityClass(task);
                    const lateCls = task.is_late ? "gantt-op-late" : "";
                    const encodedTask = escapeHtml(JSON.stringify(task));

                    trackElements += `
                        <div class="gantt-op-bar ${priorityCls} ${lateCls}"
                             style="left:${left}px;width:${width}px"
                             data-task="${encodedTask}">
                            <span class="text-truncate">${escapeHtml(task.order_id)} (${escapeHtml(task.operation_code || "OP")})</span>
                            ${task.is_late ? '<i class="bi bi-exclamation-circle-fill"></i>' : ""}
                        </div>
                    `;
                });

                rowsHtml += `
                    <div class="gantt-row">
                        <div class="gantt-machine-label">
                            <div class="fw-semibold text-navy small">${escapeHtml(mach.machine_id)}</div>
                            <div class="text-muted" style="font-size:0.72rem">${escapeHtml(mach.name)} · ${escapeHtml(mach.machine_type)}</div>
                        </div>
                        <div class="gantt-track" style="width:${trackWidth}px">
                            ${trackElements}
                        </div>
                    </div>
                `;
            });

            this.container.innerHTML = `
                <div class="gantt-viewport">
                    <div style="min-width:${trackWidth + 190}px">
                        <div class="gantt-header-row">
                            <div class="gantt-machine-col-head">Machine (${visibleMachines.length})</div>
                            <div class="gantt-time-axis" style="width:${trackWidth}px">${ticksHtml}</div>
                        </div>
                        ${rowsHtml}
                    </div>
                </div>
            `;

            this._bindInteractions();
        }

        _bindInteractions() {
            const tooltip = this.tooltipEl;
            const fmt = window.PlantOpsApi.formatDateTime;
            const escapeHtml = window.PlantOpsApi.escapeHtml;

            this.container.querySelectorAll(".gantt-op-bar").forEach((bar) => {
                const raw = bar.getAttribute("data-task");
                if (!raw) return;
                const task = JSON.parse(raw);

                bar.addEventListener("mouseenter", (evt) => {
                    tooltip.innerHTML = `
                        <div class="fw-bold mb-1">${escapeHtml(task.order_id)} · ${escapeHtml(task.operation_id)}</div>
                        <div>Product: <strong>${escapeHtml(task.product_id || "-")}</strong></div>
                        <div>Machine: <strong>${escapeHtml(task.machine_id)}</strong> | Seq #${task.sequence_number || "-"}</div>
                        <div>Start: ${escapeHtml(fmt(task.start_time))}</div>
                        <div>End: ${escapeHtml(fmt(task.end_time))}</div>
                        <div>Duration: ${task.duration_minutes} min | Changeover: ${task.changeover_minutes} min</div>
                        <div>Status: ${task.is_late ? `<span class="text-danger fw-bold">Late (+${task.lateness_minutes}m)</span>` : '<span class="text-success">On Time</span>'}</div>
                    `;
                    tooltip.style.display = "block";
                    tooltip.style.left = `${Math.min(window.innerWidth - 310, evt.clientX + 14)}px`;
                    tooltip.style.top = `${Math.min(window.innerHeight - 190, evt.clientY + 14)}px`;
                });

                bar.addEventListener("mousemove", (evt) => {
                    tooltip.style.left = `${Math.min(window.innerWidth - 310, evt.clientX + 14)}px`;
                    tooltip.style.top = `${Math.min(window.innerHeight - 190, evt.clientY + 14)}px`;
                });

                bar.addEventListener("mouseleave", () => {
                    tooltip.style.display = "none";
                });

                bar.addEventListener("click", () => {
                    tooltip.style.display = "none";
                    if (typeof this.onTaskClick === "function") {
                        this.onTaskClick(task);
                    }
                });
            });

            this.container.querySelectorAll(".gantt-downtime-band").forEach((band) => {
                const raw = band.getAttribute("data-downtime");
                if (!raw) return;
                const dt = JSON.parse(raw);
                band.addEventListener("mouseenter", (evt) => {
                    tooltip.innerHTML = `
                        <div class="fw-bold text-warning mb-1">Downtime (${escapeHtml(dt.downtime_type)})</div>
                        <div>Machine: ${escapeHtml(dt.machine_id)}</div>
                        <div>From: ${escapeHtml(fmt(dt.start_time))}</div>
                        <div>To: ${escapeHtml(fmt(dt.end_time))}</div>
                        <div>Reason: ${escapeHtml(dt.reason || "Scheduled Maintenance")}</div>
                    `;
                    tooltip.style.display = "block";
                    tooltip.style.left = `${Math.min(window.innerWidth - 300, evt.clientX + 14)}px`;
                    tooltip.style.top = `${Math.min(window.innerHeight - 160, evt.clientY + 14)}px`;
                });
                band.addEventListener("mouseleave", () => {
                    tooltip.style.display = "none";
                });
            });
        }
    }

    window.PlantOpsGantt = PlantOpsGantt;
})(window);

