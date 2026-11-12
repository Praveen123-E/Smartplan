/**
 * PlantOps Chart.js Helper Module
 * Creates responsive Chart.js visualizations and safely destroys previous instances.
 */
(function (window) {
    "use strict";

    const chartRegistry = {};

    const PALETTE = [
        "#4338ca", // Indigo
        "#0f766e", // Teal
        "#16a34a", // Green
        "#d97706", // Amber
        "#dc2626", // Red
        "#0284c7", // Sky
        "#1e293b", // Slate Navy
        "#7c3aed", // Violet
        "#64748b", // Muted Gray
    ];

    function renderChart(canvasId, config) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || !window.Chart) return null;

        if (chartRegistry[canvasId]) {
            chartRegistry[canvasId].destroy();
            delete chartRegistry[canvasId];
        }

        const ctx = canvas.getContext("2d");
        const instance = new window.Chart(ctx, config);
        chartRegistry[canvasId] = instance;
        return instance;
    }

    function renderDoughnut(canvasId, labels, values, colors) {
        return renderChart(canvasId, {
            type: "doughnut",
            data: {
                labels: labels || [],
                datasets: [
                    {
                        data: values || [],
                        backgroundColor: colors || PALETTE,
                        borderWidth: 2,
                        borderColor: "#ffffff",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "62%",
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { boxWidth: 12, padding: 12, font: { size: 11 } },
                    },
                },
            },
        });
    }

    function renderBar(canvasId, labels, values, datasetLabel, color = "#4338ca", horizontal = false) {
        return renderChart(canvasId, {
            type: "bar",
            data: {
                labels: labels || [],
                datasets: [
                    {
                        label: datasetLabel || "Value",
                        data: values || [],
                        backgroundColor: color,
                        borderRadius: 6,
                        maxBarThickness: 36,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: horizontal ? "y" : "x",
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    y: { beginAtZero: true, grid: { color: "#f1f5f9" } },
                    x: { grid: { display: false } },
                },
            },
        });
    }

    function renderLine(canvasId, labels, values, datasetLabel = "Units Produced") {
        return renderChart(canvasId, {
            type: "line",
            data: {
                labels: labels || [],
                datasets: [
                    {
                        label: datasetLabel,
                        data: values || [],
                        borderColor: "#4338ca",
                        backgroundColor: "rgba(67, 56, 202, 0.12)",
                        fill: true,
                        tension: 0.32,
                        pointRadius: 3,
                        pointBackgroundColor: "#112240",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    y: { beginAtZero: true, grid: { color: "#f1f5f9" } },
                    x: { grid: { display: false } },
                },
            },
        });
    }

    window.PlantOpsCharts = {
        renderDoughnut,
        renderBar,
        renderLine,
    };
})(window);

