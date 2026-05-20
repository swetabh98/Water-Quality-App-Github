let charts = {};

const chartColors = {
    blue: "rgba(56, 189, 248, 0.82)",
    blueSoft: "rgba(56, 189, 248, 0.18)",
    green: "rgba(34, 197, 94, 0.82)",
    greenSoft: "rgba(34, 197, 94, 0.18)",
    yellow: "rgba(250, 204, 21, 0.82)",
    yellowSoft: "rgba(250, 204, 21, 0.18)",
    red: "rgba(251, 113, 133, 0.82)",
    redSoft: "rgba(251, 113, 133, 0.18)",
    purple: "rgba(167, 139, 250, 0.82)",
    purpleSoft: "rgba(167, 139, 250, 0.18)",
    orange: "rgba(251, 146, 60, 0.82)",
    orangeSoft: "rgba(251, 146, 60, 0.18)",
    slate: "rgba(148, 163, 184, 0.65)"
};

const palette = [
    chartColors.blue,
    chartColors.green,
    chartColors.yellow,
    chartColors.purple,
    chartColors.orange,
    chartColors.red,
    "rgba(45, 212, 191, 0.82)",
    "rgba(129, 140, 248, 0.82)",
    "rgba(244, 114, 182, 0.82)",
    "rgba(132, 204, 22, 0.82)"
];

Chart.defaults.color = "rgba(226, 232, 240, 0.78)";
Chart.defaults.borderColor = "rgba(148, 163, 184, 0.13)";
Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";
Chart.defaults.plugins.tooltip.backgroundColor = "rgba(15, 23, 42, 0.95)";
Chart.defaults.plugins.tooltip.titleColor = "#f8fafc";
Chart.defaults.plugins.tooltip.bodyColor = "#e2e8f0";
Chart.defaults.plugins.tooltip.borderColor = "rgba(148, 163, 184, 0.22)";
Chart.defaults.plugins.tooltip.borderWidth = 1;

async function fetchJSON(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
        throw new Error(`API failed: ${url}`);
    }
    return response.json();
}

function formatNumber(value) {
    const number = Number(value || 0);
    return number.toLocaleString("en-IN", {
        maximumFractionDigits: 2
    });
}

function formatPercent(value) {
    const number = Number(value || 0);
    return `${number.toFixed(2)}%`;
}

function destroyChart(id) {
    if (charts[id]) {
        charts[id].destroy();
        delete charts[id];
    }
}

function createChart(id, config) {
    const canvas = document.getElementById(id);
    if (!canvas) return;

    destroyChart(id);

    charts[id] = new Chart(canvas, {
        ...config,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 900,
                easing: "easeOutQuart"
            },
            plugins: {
                legend: {
                    display: true,
                    labels: {
                        usePointStyle: true,
                        pointStyle: "circle",
                        padding: 18,
                        boxWidth: 8,
                        boxHeight: 8
                    }
                },
                tooltip: {
                    mode: "index",
                    intersect: false
                },
                ...(config.options && config.options.plugins ? config.options.plugins : {})
            },
            scales: config.type === "doughnut" || config.type === "pie"
                ? {}
                : {
                    x: {
                        grid: {
                            color: "rgba(148, 163, 184, 0.08)"
                        },
                        ticks: {
                            maxRotation: 45,
                            minRotation: 0
                        }
                    },
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: "rgba(148, 163, 184, 0.11)"
                        }
                    },
                    ...(config.options && config.options.scales ? config.options.scales : {})
                },
            ...(config.options || {})
        }
    });
}

function buildRecordsTable(records) {
    const tbody = document.getElementById("recordsTable");
    if (!tbody) return;

    if (!records || records.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8">No records found</td></tr>`;
        return;
    }

    tbody.innerHTML = records.map(row => `
        <tr>
            <td>${row.sn ?? ""}</td>
            <td><strong>${row.line}</strong></td>
            <td><span class="badge">${row.frequency}</span></td>
            <td>${row.unit}</td>
            <td>${formatNumber(row.new)}</td>
            <td>${formatNumber(row.previous)} ${row.previous_period ? `(${row.previous_period})` : ""}</td>
            <td>${formatNumber(row.difference)}</td>
            <td>${formatPercent(row.rise)}</td>
        </tr>
    `).join("");
}

function updateKpis(summary, lastUpdated) {
    document.getElementById("lastUpdated").innerText = lastUpdated || "--";

    document.getElementById("totalNew").innerText = formatNumber(summary.total_new);
    document.getElementById("totalPrevious").innerText = formatNumber(summary.total_previous);
    document.getElementById("totalGain").innerText = formatNumber(summary.total_gain);
    document.getElementById("avgRise").innerText = formatPercent(summary.avg_rise);

    document.getElementById("bestRise").innerText =
        `${summary.best_rise_line} • ${formatPercent(summary.best_rise_value)}`;

    document.getElementById("bestVolume").innerText =
        `${summary.best_volume_line} • ${formatNumber(summary.best_volume_value)}`;

    document.getElementById("recordCount").innerText = formatNumber(summary.record_count);
}

function renderDashboard(payload) {
    const main = payload.main;
    const frequency = payload.frequency;
    const lineGrouped = payload.line_grouped;
    const topVolume = payload.top_volume;
    const topRise = payload.top_rise;

    updateKpis(payload.summary, payload.last_updated);
    buildRecordsTable(payload.records);

    createChart("comparisonChart", {
        type: "bar",
        data: {
            labels: main.labels,
            datasets: [
                {
                    label: "New Milestone",
                    data: main.new,
                    backgroundColor: chartColors.blue,
                    borderColor: "rgba(125, 211, 252, 1)",
                    borderWidth: 1,
                    borderRadius: 8
                },
                {
                    label: "Previous Milestone",
                    data: main.previous,
                    backgroundColor: chartColors.purple,
                    borderColor: "rgba(196, 181, 253, 1)",
                    borderWidth: 1,
                    borderRadius: 8
                }
            ]
        }
    });

    createChart("riseChart", {
        type: "line",
        data: {
            labels: main.labels,
            datasets: [
                {
                    label: "Rise %",
                    data: main.rise,
                    borderColor: "rgba(34, 197, 94, 1)",
                    backgroundColor: chartColors.greenSoft,
                    pointBackgroundColor: "rgba(34, 197, 94, 1)",
                    pointBorderColor: "#ffffff",
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    tension: 0.36,
                    fill: true
                }
            ]
        }
    });

    createChart("gainChart", {
        type: "bar",
        data: {
            labels: main.labels,
            datasets: [
                {
                    label: "Gain",
                    data: main.difference,
                    backgroundColor: main.difference.map(value =>
                        value >= 0 ? chartColors.green : chartColors.red
                    ),
                    borderRadius: 8
                }
            ]
        }
    });

    createChart("frequencyBarChart", {
        type: "bar",
        data: {
            labels: frequency.labels,
            datasets: [
                {
                    label: "New Milestone",
                    data: frequency.new,
                    backgroundColor: palette,
                    borderRadius: 10
                }
            ]
        }
    });

    createChart("frequencyDoughnutChart", {
        type: "doughnut",
        data: {
            labels: frequency.labels,
            datasets: [
                {
                    label: "Frequency Share",
                    data: frequency.new,
                    backgroundColor: palette,
                    borderColor: "rgba(15, 23, 42, 0.95)",
                    borderWidth: 3,
                    hoverOffset: 8
                }
            ]
        },
        options: {
            cutout: "68%"
        }
    });

    createChart("topVolumeChart", {
        type: "bar",
        data: {
            labels: topVolume.labels,
            datasets: [
                {
                    label: "Top New Milestone",
                    data: topVolume.values,
                    backgroundColor: chartColors.blue,
                    borderRadius: 10
                }
            ]
        },
        options: {
            indexAxis: "y"
        }
    });

    createChart("topRiseChart", {
        type: "bar",
        data: {
            labels: topRise.labels,
            datasets: [
                {
                    label: "Top Rise %",
                    data: topRise.values,
                    backgroundColor: chartColors.green,
                    borderRadius: 10
                }
            ]
        },
        options: {
            indexAxis: "y"
        }
    });

    createChart("lineTotalChart", {
        type: "bar",
        data: {
            labels: lineGrouped.labels,
            datasets: [
                {
                    label: "New Total",
                    data: lineGrouped.new,
                    backgroundColor: chartColors.blue,
                    borderRadius: 8
                },
                {
                    label: "Previous Total",
                    data: lineGrouped.previous,
                    backgroundColor: chartColors.orange,
                    borderRadius: 8
                }
            ]
        }
    });

    createChart("newTrendChart", {
        type: "line",
        data: {
            labels: main.labels,
            datasets: [
                {
                    label: "New Milestone Trend",
                    data: main.new,
                    borderColor: "rgba(56, 189, 248, 1)",
                    backgroundColor: chartColors.blueSoft,
                    pointBackgroundColor: "rgba(56, 189, 248, 1)",
                    pointBorderColor: "#ffffff",
                    pointRadius: 5,
                    tension: 0.32,
                    fill: true
                }
            ]
        }
    });

    createChart("areaChart", {
        type: "line",
        data: {
            labels: main.labels,
            datasets: [
                {
                    label: "New",
                    data: main.new,
                    borderColor: "rgba(56, 189, 248, 1)",
                    backgroundColor: chartColors.blueSoft,
                    tension: 0.35,
                    fill: true
                },
                {
                    label: "Previous",
                    data: main.previous,
                    borderColor: "rgba(251, 146, 60, 1)",
                    backgroundColor: chartColors.orangeSoft,
                    tension: 0.35,
                    fill: true
                }
            ]
        }
    });

    const ratioValues = main.new.map((value, index) => {
        const previous = Number(main.previous[index] || 0);
        if (previous === 0) return 0;
        return Number((value / previous).toFixed(3));
    });

    createChart("ratioChart", {
        type: "line",
        data: {
            labels: main.labels,
            datasets: [
                {
                    label: "Performance Ratio",
                    data: ratioValues,
                    borderColor: "rgba(250, 204, 21, 1)",
                    backgroundColor: chartColors.yellowSoft,
                    pointBackgroundColor: "rgba(250, 204, 21, 1)",
                    pointBorderColor: "#ffffff",
                    pointRadius: 5,
                    tension: 0.34,
                    fill: true
                }
            ]
        }
    });
}

async function loadDashboard() {
    try {
        const payload = await fetchJSON("/CRM_Records/api/dashboard");

        if (payload.status !== "success") {
            console.error("Dashboard API error:", payload);
            alert("No data received from Google Sheet. Please check /CRM_Records/api/dashboard.");
            return;
        }

        renderDashboard(payload);

    } catch (error) {
        console.error(error);
        alert("Unable to load dashboard data. Please check Flask terminal and API.");
    }
}

loadDashboard();

setInterval(loadDashboard, 60000);