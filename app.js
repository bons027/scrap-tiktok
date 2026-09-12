// State Aplikasi
let currentData = null;
let allRecords = [];
let filteredRecords = [];
let chartSentiment = null;
let chartTopics = null;
let chartCross = null;
let progressInterval = null;

const COLOR_MAP = {
    "Positif": "#10b981",
    "Netral": "#f59e0b",
    "Negatif": "#f43f5e"
};

// DOM Elements
const selectFile = document.getElementById("select-file");
const inputApiKey = document.getElementById("input-api-key");
const btnAnalyze = document.getElementById("btn-analyze");
const btnAnalyzeText = document.getElementById("btn-analyze-text");
const progressBox = document.getElementById("progress-box");
const progressBarFill = document.getElementById("progress-bar-fill");
const progressVal = document.getElementById("progress-val");
const progressLabel = document.getElementById("progress-label");
const progressSub = document.getElementById("progress-sub");

const activeFileTitle = document.getElementById("active-file-title");
const aiSummaryCard = document.getElementById("ai-summary-card");
const aiSummaryText = document.getElementById("ai-summary-text");
const btnExportCsv = document.getElementById("btn-export-csv");

const statTotal = document.getElementById("stat-total");
const statPos = document.getElementById("stat-pos");
const statPosCount = document.getElementById("stat-pos-count");
const statNeu = document.getElementById("stat-neu");
const statNeuCount = document.getElementById("stat-neu-count");
const statNeg = document.getElementById("stat-neg");
const statNegCount = document.getElementById("stat-neg-count");
const statNps = document.getElementById("stat-nps");

const searchInput = document.getElementById("search-input");
const filterSentiment = document.getElementById("filter-sentiment");
const filterTopic = document.getElementById("filter-topic");
const commentsTbody = document.getElementById("comments-tbody");
const tableInfo = document.getElementById("table-info");

// ==========================================
// 1. INIT & LOAD FILES
// ==========================================
async function initApp() {
    await loadFileList();
    setupEventListeners();
}

async function loadFileList(preferredFile = null) {
    try {
        const res = await fetch("/api/files");
        const data = await res.json();
        const files = data.files || [];

        selectFile.innerHTML = "";
        if (files.length === 0) {
            selectFile.innerHTML = '<option value="">Tidak ada file CSV</option>';
            return;
        }

        files.forEach(f => {
            const opt = document.createElement("option");
            opt.value = f.filename;
            const label = f.display_name || f.filename;
            opt.textContent = `${label} ${f.is_analyzed ? "✨ (Sudah Dianalisis)" : ""}`;
            selectFile.appendChild(opt);
        });

        // Pilih file default (prioritaskan preferredFile atau file analyzed pertama)
        if (preferredFile && files.some(f => f.filename === preferredFile)) {
            selectFile.value = preferredFile;
        } else {
            selectFile.selectedIndex = 0;
        }

        await loadData(selectFile.value);
    } catch (err) {
        console.error("Gagal memuat daftar file:", err);
    }
}

// ==========================================
// 2. LOAD DATA DARI FILE
// ==========================================
async function loadData(filename) {
    if (!filename) return;

    activeFileTitle.textContent = filename;
    commentsTbody.innerHTML = '<tr><td colspan="6" class="text-center py-4" style="text-align:center; padding: 20px;">Memuat data...</td></tr>';

    try {
        const res = await fetch(`/api/data?file=${encodeURIComponent(filename)}`);
        const json = await res.json();

        if (json.error) {
            alert(json.error);
            return;
        }

        currentData = json;
        allRecords = json.records || [];
        const stats = json.stats || {};

        // Update Button Label
        if (stats.is_analyzed) {
            btnAnalyzeText.textContent = "🔄 Analisis Ulang dengan Gemini";
            btnExportCsv.disabled = false;
        } else {
            btnAnalyzeText.textContent = "🚀 Mulai Analisis AI (Gemini Flash)";
            btnExportCsv.disabled = true;
        }

        // Update Executive AI Summary
        if (stats.summary && stats.summary.trim()) {
            aiSummaryCard.style.display = "block";
            aiSummaryText.textContent = stats.summary;
        } else {
            aiSummaryCard.style.display = "none";
        }

        // Update KPI Stats
        updateStats(stats);

        // Update Charts
        updateCharts(stats);

        // Update Topic Filter Options
        populateTopicFilter(stats.topic_counts || {});

        // Render Data Table
        applyFilters();

    } catch (err) {
        console.error("Gagal mengambil data:", err);
        commentsTbody.innerHTML = '<tr><td colspan="6" class="text-center py-4" style="text-align:center; color:#ef4444;">Gagal memuat data file.</td></tr>';
    }
}

// ==========================================
// 3. STATS & KPI UPDATE
// ==========================================
function updateStats(stats) {
    const total = stats.total || 0;
    const sent = stats.sentiment_counts || {};

    const pos = sent["Positif"] || 0;
    const neu = sent["Netral"] || 0;
    const neg = sent["Negatif"] || 0;

    const posPct = total > 0 ? (pos / total * 100).toFixed(1) : "0.0";
    const neuPct = total > 0 ? (neu / total * 100).toFixed(1) : "0.0";
    const negPct = total > 0 ? (neg / total * 100).toFixed(1) : "0.0";
    const nps = (parseFloat(posPct) - parseFloat(negPct)).toFixed(1);

    statTotal.textContent = total.toLocaleString("id-ID");
    statPos.textContent = `${posPct}%`;
    statPosCount.textContent = `${pos.toLocaleString("id-ID")} komentar`;
    statNeu.textContent = `${neuPct}%`;
    statNeuCount.textContent = `${neu.toLocaleString("id-ID")} komentar`;
    statNeg.textContent = `${negPct}%`;
    statNegCount.textContent = `${neg.toLocaleString("id-ID")} komentar`;
    statNps.textContent = `${nps >= 0 ? "+" : ""}${nps}`;
}

// ==========================================
// 4. CHARTS (CHART.JS)
// ==========================================
function updateCharts(stats) {
    const sent = stats.sentiment_counts || {};
    const topTopics = stats.topic_counts || {};
    const topicCross = stats.topic_sentiment || [];

    // 1. Donut Chart Sentimen
    const ctxSent = document.getElementById("chart-sentiment").getContext("2d");
    if (chartSentiment) chartSentiment.destroy();

    const sentLabels = ["Positif", "Netral", "Negatif"];
    const sentData = [sent["Positif"] || 0, sent["Netral"] || 0, sent["Negatif"] || 0];

    chartSentiment = new Chart(ctxSent, {
        type: "doughnut",
        data: {
            labels: sentLabels,
            datasets: [{
                data: sentData,
                backgroundColor: [COLOR_MAP.Positif, COLOR_MAP.Netral, COLOR_MAP.Negatif],
                borderWidth: 0,
                hoverOffset: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: "bottom",
                    labels: { color: "#94a3b8", font: { family: "Plus Jakarta Sans", size: 12 }, padding: 15 }
                }
            },
            cutout: "68%"
        }
    });

    // 2. Bar Chart Top Topics
    const ctxTopics = document.getElementById("chart-topics").getContext("2d");
    if (chartTopics) chartTopics.destroy();

    const topicLabels = Object.keys(topTopics);
    const topicValues = Object.values(topTopics);

    chartTopics = new Chart(ctxTopics, {
        type: "bar",
        data: {
            labels: topicLabels,
            datasets: [{
                label: "Jumlah Komentar",
                data: topicValues,
                backgroundColor: "rgba(59, 130, 246, 0.75)",
                borderRadius: 6
            }]
        },
        options: {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8" } },
                y: { grid: { display: false }, ticks: { color: "#cbd5e1", font: { size: 11 } } }
            }
        }
    });

    // 3. Stacked Bar Chart Cross Analysis
    const ctxCross = document.getElementById("chart-cross").getContext("2d");
    if (chartCross) chartCross.destroy();

    const crossLabels = topicCross.map(t => t.topic);
    const posCross = topicCross.map(t => t.Positif);
    const neuCross = topicCross.map(t => t.Netral);
    const negCross = topicCross.map(t => t.Negatif);

    chartCross = new Chart(ctxCross, {
        type: "bar",
        data: {
            labels: crossLabels,
            datasets: [
                { label: "Positif", data: posCross, backgroundColor: COLOR_MAP.Positif, borderRadius: 4 },
                { label: "Netral", data: neuCross, backgroundColor: COLOR_MAP.Netral, borderRadius: 4 },
                { label: "Negatif", data: negCross, backgroundColor: COLOR_MAP.Negatif, borderRadius: 4 }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: "top", labels: { color: "#94a3b8", font: { size: 12 } } }
            },
            scales: {
                x: { stacked: true, grid: { display: false }, ticks: { color: "#cbd5e1", font: { size: 11 } } },
                y: { stacked: true, grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#94a3b8" } }
            }
        }
    });
}

// ==========================================
// 5. FILTER & TABEL DATA
// ==========================================
function populateTopicFilter(topicCounts) {
    filterTopic.innerHTML = '<option value="ALL">Semua Topik Isu</option>';
    Object.keys(topicCounts).forEach(t => {
        const opt = document.createElement("option");
        opt.value = t;
        opt.textContent = `${t} (${topicCounts[t]})`;
        filterTopic.appendChild(opt);
    });
}

function applyFilters() {
    const sVal = filterSentiment.value;
    const tVal = filterTopic.value;
    const q = searchInput.value.toLowerCase().trim();

    filteredRecords = allRecords.filter(r => {
        const rSent = r.sentiment || "Netral";
        const rTopic = r.topic || "Lain-lain";
        const rText = (r.comment_text || r.description || r.post_text || "").toLowerCase();
        const rPoint = (r.key_point || "").toLowerCase();
        const rUser = (r.profile_name || r.username || r.author_name || "").toLowerCase();

        if (sVal !== "ALL" && rSent !== sVal) return false;
        if (tVal !== "ALL" && rTopic !== tVal) return false;
        if (q && !rText.includes(q) && !rPoint.includes(q) && !rUser.includes(q)) return false;

        return true;
    });

    renderTable(filteredRecords);
}

function renderTable(records) {
    const limit = 200;
    const displayed = records.slice(0, limit);
    tableInfo.textContent = records.length > limit 
        ? `Menampilkan ${limit} dari ${records.length.toLocaleString("id-ID")} baris data (Total dataset: ${allRecords.length.toLocaleString("id-ID")})`
        : `Menampilkan ${records.length.toLocaleString("id-ID")} dari ${allRecords.length.toLocaleString("id-ID")} baris data`;

    if (records.length === 0) {
        commentsTbody.innerHTML = '<tr><td colspan="6" class="text-center py-4" style="text-align:center; padding: 20px;">Tidak ada data yang cocok dengan filter.</td></tr>';
        return;
    }

    const rows = displayed.map(r => {
        const sent = r.sentiment || "Netral";
        const sentClass = sent.toLowerCase();
        const topic = r.topic || "-";
        const keyPoint = r.key_point || "-";
        const text = r.comment_text || r.description || r.post_text || "";
        const likes = r.likes || r.reactions_count || 0;
        const user = r.profile_name || r.username || r.author_name || "Anonim";
        const score = r.sentiment_score ? parseFloat(r.sentiment_score) : null;
        const scoreDisplay = score ? ` <span style="font-size:0.72rem; opacity:0.85; font-weight:600;">(${Math.round(Math.abs(score) * 100)}%)</span>` : "";

        return `
            <tr>
                <td><span class="badge-sent ${sentClass}">${sent}${scoreDisplay}</span></td>
                <td><span class="badge-topic">${topic}</span></td>
                <td style="font-weight: 600; color: #e2e8f0;">${keyPoint}</td>
                <td style="max-width: 420px; line-height: 1.4;">${escapeHtml(text)}</td>
                <td style="font-weight: 600; color: #94a3b8;">${likes}</td>
                <td style="color: #60a5fa;">${escapeHtml(user)}</td>
            </tr>
        `;
    }).join("");

    commentsTbody.innerHTML = rows;
}

function escapeHtml(str) {
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ==========================================
// 6. ANALISIS VIA GEMINI & PROGRESS TRACKING
// ==========================================
async function startAnalysis() {
    const filename = selectFile.value;
    if (!filename) return alert("Pilih file komentar terlebih dahulu!");

    const apiKey = inputApiKey.value.trim();

    btnAnalyze.disabled = true;
    progressBox.style.display = "block";
    progressBarFill.style.width = "0%";
    progressVal.textContent = "0%";
    progressLabel.textContent = "Memulai analisis...";
    progressSub.textContent = "Mengirim batch ke Google Gemini...";

    try {
        const res = await fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: jsonStringify({ filename: filename, api_key: apiKey })
        });
        const json = await res.json();

        if (json.error) {
            alert(json.error);
            resetProgressUI();
            return;
        }

        // Start polling progress
        progressInterval = setInterval(pollProgress, 1200);

    } catch (err) {
        alert("Gagal menghubungi server: " + err);
        resetProgressUI();
    }
}

async function pollProgress() {
    try {
        const res = await fetch("/api/progress");
        const p = await res.json();

        if (p.status === "running") {
            progressBarFill.style.width = `${p.percent}%`;
            progressVal.textContent = `${p.percent}%`;
            progressLabel.textContent = `Batch ${p.current_batch}/${p.total_batches}`;
            progressSub.textContent = p.message;
        } else if (p.status === "completed") {
            clearInterval(progressInterval);
            progressBarFill.style.width = "100%";
            progressVal.textContent = "100%";
            progressLabel.textContent = "Selesai!";
            progressSub.textContent = p.message;

            setTimeout(async () => {
                resetProgressUI();
                await loadFileList(p.result_file);
            }, 1500);
        } else if (p.status === "error") {
            clearInterval(progressInterval);
            alert("Terjadi kesalahan saat analisis: " + p.error);
            resetProgressUI();
        }
    } catch (err) {
        console.error("Error polling progress:", err);
    }
}

function resetProgressUI() {
    if (progressInterval) clearInterval(progressInterval);
    btnAnalyze.disabled = false;
    progressBox.style.display = "none";
}

function jsonStringify(obj) {
    return JSON.stringify(obj);
}

// ==========================================
// 7. EXPORT CSV
// ==========================================
function exportToCsv() {
    if (filteredRecords.length === 0) return alert("Tidak ada data untuk diekspor!");

    const headers = Object.keys(filteredRecords[0]);
    const csvRows = [];
    csvRows.push(headers.join(","));

    for (const r of filteredRecords) {
        const values = headers.map(h => {
            const val = ("" + (r[h] ?? "")).replace(/"/g, '""');
            return `"${val}"`;
        });
        csvRows.push(values.join(","));
    }

    const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `hasil_filter_${selectFile.value || "data"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

// ==========================================
// 8. EVENT LISTENERS
// ==========================================
const btnUploadColab = document.getElementById("btn-upload-colab");
const fileUploader = document.getElementById("file-uploader");

function setupEventListeners() {
    selectFile.addEventListener("change", () => loadData(selectFile.value));
    btnAnalyze.addEventListener("click", startAnalysis);
    filterSentiment.addEventListener("change", applyFilters);
    filterTopic.addEventListener("change", applyFilters);
    searchInput.addEventListener("input", applyFilters);
    btnExportCsv.addEventListener("click", exportToCsv);

    if (btnUploadColab && fileUploader) {
        btnUploadColab.addEventListener("click", () => fileUploader.click());
        fileUploader.addEventListener("change", async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = async () => {
                const base64 = reader.result.split(",")[1];
                try {
                    const res = await fetch("/api/upload", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ filename: file.name, content: base64 })
                    });
                    const json = await res.json();
                    if (json.status === "success") {
                        await loadFileList(json.filename);
                        alert(`Berhasil mengupload dan menampilkan ${json.filename}!`);
                    } else {
                        alert("Upload gagal: " + json.error);
                    }
                } catch (err) {
                    alert("Gagal mengupload file: " + err);
                }
            };
            reader.readAsDataURL(file);
        });
    }
}

document.addEventListener("DOMContentLoaded", initApp);

