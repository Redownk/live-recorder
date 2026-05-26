const state = {
  view: "rooms",
};

const $ = (selector) => document.querySelector(selector);

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  setTimeout(() => {
    el.hidden = true;
  }, 2600);
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail || detail;
    } catch (_) {
      detail = response.statusText;
    }
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

function platformName(value) {
  return { DOUYIN: "抖音", BILIBILI: "哔哩哔哩", DOUYU: "斗鱼" }[value] || value;
}

function formatTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.view === view));
  document.querySelectorAll(".view").forEach((panel) => panel.classList.toggle("active", panel.id === `${view}View`));
  const titles = {
    rooms: ["直播间", "管理需要监控的抖音、哔哩哔哩、斗鱼直播间。"],
    logs: ["录制日志", "查看每次开播、下播与录制时长。"],
    videos: ["视频文件", "查看后处理上传后的录制文件。"],
  };
  $("#viewTitle").textContent = titles[view][0];
  $("#viewSubTitle").textContent = titles[view][1];
  loadCurrentView();
}

function table(headers, rows) {
  const head = headers.map((item) => `<th>${item}</th>`).join("");
  const body = rows.length
    ? rows.join("")
    : `<tr><td colspan="${headers.length}">暂无数据</td></tr>`;
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

async function loadRooms() {
  const keyword = encodeURIComponent($("#keyword").value.trim());
  const rooms = await request(`/api/rooms${keyword ? `?keyword=${keyword}` : ""}`);
  $("#roomsTable").innerHTML = table(
    ["平台", "房间号", "主播", "标题", "监控", "最近开播", "操作"],
    rooms.map(
      (room) => `
      <tr>
        <td><span class="pill">${platformName(room.platform)}</span></td>
        <td>${room.room_id}</td>
        <td>${room.owner || "-"}</td>
        <td>${room.title || "-"}</td>
        <td>${room.monitor_enabled ? "开启" : "关闭"}</td>
        <td>${formatTime(room.last_live_time)}</td>
        <td class="actions">
          <button data-check="${room.id}">检查</button>
          <button data-toggle="${room.id}" data-enabled="${!room.monitor_enabled}">${room.monitor_enabled ? "暂停" : "启用"}</button>
          <button class="danger" data-delete="${room.id}">删除</button>
        </td>
      </tr>`
    )
  );
}

async function loadLogs() {
  const logs = await request("/api/logs?limit=100");
  $("#logsTable").innerHTML = table(
    ["平台", "主播", "标题", "开始", "结束", "时长", "在线峰值"],
    logs.map(
      (log) => `
      <tr>
        <td><span class="pill">${platformName(log.platform)}</span></td>
        <td>${log.owner || "-"}</td>
        <td>${log.title || "-"}</td>
        <td>${formatTime(log.start_live)}</td>
        <td>${formatTime(log.end_live)}</td>
        <td>${log.live_time || 0}s</td>
        <td>${log.user_num || "-"}</td>
      </tr>`
    )
  );
}

async function loadVideos() {
  const videos = await request("/api/videos?limit=100");
  $("#videosTable").innerHTML = table(
    ["文件", "大小", "时长", "创建时间", "地址"],
    videos.map(
      (video) => `
      <tr>
        <td>${video.file_name}</td>
        <td>${video.file_size || 0}</td>
        <td>${video.duration || 0}s</td>
        <td>${formatTime(video.create_time)}</td>
        <td>${video.file_url ? `<a href="${video.file_url}" target="_blank" rel="noreferrer">打开</a>` : "-"}</td>
      </tr>`
    )
  );
}

async function loadCrawlerStatus() {
  const data = await request("/crawler/status");
  $("#crawlerState").classList.toggle("running", data.running);
}

function loadCurrentView() {
  if (state.view === "rooms") return loadRooms().catch((error) => toast(error.message));
  if (state.view === "logs") return loadLogs().catch((error) => toast(error.message));
  return loadVideos().catch((error) => toast(error.message));
}

$("#roomForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formEl = event.currentTarget;
  const form = new FormData(formEl);
  const payload = Object.fromEntries([...form.entries()].filter(([, value]) => String(value).trim() !== ""));
  payload.monitor_enabled = form.get("monitor_enabled") === "on";
  try {
    await request("/api/rooms", { method: "POST", body: JSON.stringify(payload) });
    formEl.reset();
    formEl.monitor_enabled.checked = true;
    toast("直播间已添加");
    await loadRooms();
  } catch (error) {
    toast(error.message);
  }
});

$("#roomsTable").addEventListener("click", async (event) => {
  const toggleId = event.target.dataset.toggle;
  const deleteId = event.target.dataset.delete;
  const checkId = event.target.dataset.check;
  try {
    if (checkId) {
      const status = await request(`/api/rooms/${checkId}/live-status`);
      toast(status.is_live ? `正在直播：${status.title || status.owner || ""}` : "当前未开播");
    }
    if (toggleId) {
      await request(`/api/rooms/${toggleId}/monitor`, {
        method: "PATCH",
        body: JSON.stringify({ monitor_enabled: event.target.dataset.enabled === "true" }),
      });
      await loadRooms();
    }
    if (deleteId) {
      await request(`/api/rooms/${deleteId}`, { method: "DELETE" });
      await loadRooms();
    }
  } catch (error) {
    toast(error.message);
  }
});

$("#refreshBtn").addEventListener("click", loadCurrentView);
$("#keyword").addEventListener("search", loadCurrentView);
$("#startCrawler").addEventListener("click", async () => {
  await request("/crawler/start", { method: "POST" });
  await loadCrawlerStatus();
});
$("#stopCrawler").addEventListener("click", async () => {
  await request("/crawler/stop", { method: "POST" });
  await loadCrawlerStatus();
});

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => setView(btn.dataset.view));
});

loadCrawlerStatus().catch(() => {});
loadRooms().catch((error) => toast(error.message));
