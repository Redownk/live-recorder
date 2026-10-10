const baseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

async function request(path, { body, ...options } = {}) {
  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error('无法连接服务，请检查后端是否运行');
  }
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data.detail === 'string') message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((item) => item.msg).join('；');
    } catch { /* Proxy errors may return plain text. */ }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function query(values = {}) {
  const params = new URLSearchParams(
    Object.entries(values).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  );
  return params.size ? `?${params}` : '';
}

export const api = {
  settings: () => request('/api/settings'),
  saveSettings: (body) => request('/api/settings', { method: 'PUT', body }),
  previewSettings: (body) => request('/api/settings/preview', { method: 'POST', body }),
  rooms: (params) => request(`/api/rooms${query(params)}`),
  recordingStatuses: () => request('/api/recording-status'),
  addRoom: (body) => request('/api/rooms', { method: 'POST', body }),
  editRoom: (id, body) => request(`/api/rooms/${id}`, { method: 'PUT', body }),
  monitor: (id, enabled) => request(`/api/rooms/${id}/monitor`, { method: 'PATCH', body: { monitor_enabled: enabled } }),
  deleteRoom: (id) => request(`/api/rooms/${id}`, { method: 'DELETE' }),
  liveStatus: (id) => request(`/api/rooms/${id}/live-status`),
  logs: (params) => request(`/api/logs${query({ limit: 100, ...params })}`),
  videos: (params) => request(`/api/videos${query({ limit: 100, ...params })}`),
  videoFileUrl: (id) => `${baseUrl}/api/videos/${id}/file`,
  crawlerStatus: () => request('/crawler/status'),
  crawler: (action) => request(`/crawler/${action}`, { method: 'POST' }),
};
