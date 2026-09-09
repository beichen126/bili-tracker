let modelRequest = null;
let modelEpoch = 0;
let modelTimer = null;

const api = (path, options = {}) => fetch(`/api/v1${path}`, {
  headers: { "Content-Type": "application/json" },
  ...options,
}).then(async response => {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.code || "request_failed");
  return data;
});
const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
}[ch]));
const formatBytes = value => value > 1e9
  ? `${(value / 1e9).toFixed(1)} GB`
  : `${(value / 1e6).toFixed(0)} MB`;
const formatSpeed = value => value > 1e6
  ? `${(value / 1e6).toFixed(1)} MB/s`
  : `${(value / 1e3).toFixed(0)} KB/s`;

function loadModels() {
  if (modelRequest) return modelRequest;
  const epoch = ++modelEpoch;
  modelRequest = api("/models").then(({ models }) => {
    if (epoch !== modelEpoch) return models;
    document.querySelector("#models").innerHTML = models.map(model => `<article class="card">
      <h3>${esc(model.id)}</h3>
      <div class="meta">${esc(model.license.id)} · ${formatBytes(model.size_bytes)} · ${esc(model.runtime)}</div>
      <div class="meta">来源：<a href="${esc(model.sources[0])}" target="_blank" rel="noreferrer">模型文件</a> · <a href="${esc(model.license.url)}" target="_blank" rel="noreferrer">许可证</a> · 磁盘占用 ${formatBytes(model.disk_footprint_bytes)}</div>
      <div class="meta">设备建议：${esc(Object.values(model.resource_hints).join(" · "))}</div>
      <div class="progress" aria-label="安装进度"><i style="width:${Math.round(model.progress * 100)}%"></i></div>
      <div class="meta">状态：${esc(model.state)} · ${Math.round(model.progress * 100)}% · 剩余 ${formatBytes(model.remaining_bytes)} · ${formatSpeed(model.speed_bytes_per_sec)}</div>
      <button data-model="${esc(model.id)}" ${model.state === "ready" || model.state === "downloading" ? "disabled" : ""}>${model.state === "awaiting_license" ? "接受许可证并安装" : "安装 / 修复"}</button>
    </article>`).join("");
    document.querySelectorAll("[data-model]").forEach(button => button.addEventListener("click", async () => {
      button.disabled = true;
      document.querySelector("#model-live").textContent = "安装任务已启动";
      try {
        await api(`/models/${button.dataset.model}/install`, {
          method: "POST", body: JSON.stringify({ accept_license: true }),
        });
        scheduleModelRefresh();
      } catch (error) {
        document.querySelector("#model-live").textContent = `安装失败：${error.message}`;
        button.disabled = false;
      }
    }));
    return models;
  }).finally(() => { modelRequest = null; });
  return modelRequest;
}

function scheduleModelRefresh() {
  clearTimeout(modelTimer);
  modelTimer = setTimeout(async () => {
    try {
      const models = await loadModels();
      if (models?.some(model => ["checking", "downloading", "verifying", "deploying", "validating"].includes(model.state))) {
        scheduleModelRefresh();
      }
    } catch (_) { /* the next explicit refresh can recover */ }
  }, document.hidden ? 5000 : 1200);
}

async function loadJobs() {
  const { jobs } = await api("/jobs?limit=50");
  document.querySelector("#jobs").innerHTML = jobs.length ? jobs.map(job => `<div class="job" tabindex="0" role="button" data-job="${esc(job.id)}">
    <div><strong>${esc(job.source.display_locator)}</strong><br><small>${esc(job.id)} · ${esc(job.artifacts.map(a => a.kind).join(" / ") || "暂无产物")}</small></div>
    <span class="status">${esc(job.state)} · ${Math.round(job.progress * 100)}%${job.degraded ? " · degraded" : ""}</span>
  </div>`).join("") : "<p class='hint'>还没有任务。</p>";
  document.querySelectorAll("[data-job]").forEach(item => {
    item.addEventListener("click", () => loadJobDetail(item.dataset.job));
    item.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") loadJobDetail(item.dataset.job); });
  });
}

async function loadJobDetail(jobId) {
  const { job } = await api(`/jobs/${jobId}`);
  const detail = document.querySelector("#job-detail");
  detail.hidden = false;
  document.querySelector("#delete-job").dataset.jobId = job.id;
  document.querySelector("#job-detail-meta").textContent = `${job.id} · ${job.state}${job.degraded ? " · degraded" : ""}${job.error_code ? ` · ${job.error_code}` : ""}`;
  const textKinds = ["raw", "refined", "final"];
  const blocks = await Promise.all(textKinds.map(async kind => {
    const artifact = job.artifacts.find(item => item.kind === kind);
    if (!artifact) return "";
    const response = await fetch(artifact.download_url);
    const value = response.ok ? await response.text() : "读取失败";
    return `<article class="artifact"><h3>${kind} <a href="${esc(artifact.download_url)}">下载</a></h3><pre>${esc(value)}</pre></article>`;
  }));
  document.querySelector("#job-artifacts").innerHTML = blocks.join("") || "<p class='hint'>暂无文本产物。</p>";
}

async function loadSettings() {
  const { settings } = await api("/settings");
  document.querySelector("#enable-bilibili").checked = !!settings.enable_bilibili;
  document.querySelector("#enable-remote-text").checked = !!settings.enable_remote_text;
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    const health = await api("/health");
    document.querySelector("#health").textContent = `在线 · ${health.version}`;
    await Promise.all([loadModels(), loadJobs(), loadSettings()]);
  } catch (error) {
    document.querySelector("#health").textContent = "服务不可用";
  }
  document.querySelector("#refresh").addEventListener("click", () => loadJobs());
  document.querySelector("#close-detail").addEventListener("click", () => { document.querySelector("#job-detail").hidden = true; });
  document.querySelector("#delete-job").addEventListener("click", async event => {
    const jobId = event.currentTarget.dataset.jobId;
    if (!jobId || !confirm("确认删除任务及其产物？此操作不可撤销。")) return;
    try {
      await api(`/jobs/${jobId}`, { method: "DELETE" });
      document.querySelector("#job-detail").hidden = true;
      await loadJobs();
    } catch (error) { document.querySelector("#job-detail-meta").textContent = `删除失败：${error.message}`; }
  });
  document.querySelector("#job-form").addEventListener("submit", async event => {
    event.preventDefault();
    const kind = document.querySelector("#source-kind").value;
    const locator = document.querySelector("#source-locator").value;
    const result = document.querySelector("#submit-result");
    try {
      const probe = await api("/sources/probe", { method: "POST", body: JSON.stringify({ kind, locator }) });
      if (!confirm(`确认加入：${probe.source.title || probe.source.display_locator || "该来源"}？`)) return;
      await api("/jobs", { method: "POST", body: JSON.stringify({ items: [{ source: { kind, locator } }] }) });
      result.textContent = "已加入队列";
      event.target.reset();
      await loadJobs();
    } catch (error) { result.textContent = `未提交：${error.message}`; }
  });
  document.querySelector("#save-settings").addEventListener("click", async () => {
    const result = document.querySelector("#settings-result");
    try {
      await api("/settings", { method: "PATCH", body: JSON.stringify({
        enable_bilibili: document.querySelector("#enable-bilibili").checked,
        enable_remote_text: document.querySelector("#enable-remote-text").checked,
      }) });
      result.textContent = "设置已保存；需要重启的适配器将在下一次启动生效。";
    } catch (error) { result.textContent = `保存失败：${error.message}`; }
  });
});
