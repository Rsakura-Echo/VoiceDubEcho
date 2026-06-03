const API = {
  _av: 0,

  async _fetch(method, path, body) {
    const opts = { method };
    if (body instanceof FormData) {
      opts.body = body;
    } else if (body !== undefined) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error((await res.text()).slice(0, 200));
    return res.json();
  },
  get: function(p) { return this._fetch('GET', p); },
  post: function(p, b) { return this._fetch('POST', p, b); },
  put: function(p, b) { return this._fetch('PUT', p, b); },
  del: function(p) { return this._fetch('DELETE', p); },

  // Settings
  getSettings: () => API.get('/api/settings'),
  saveSettings: (d) => API.put('/api/settings', d),

  // Projects
  getProjects: () => API.get('/api/projects'),
  createProject: (name) => API.post('/api/projects', { name }),
  getProject: (id) => API.get(`/api/projects/${id}`),
  deleteProject: (id) => API.del(`/api/projects/${id}`),
  uploadAudio: (pid, file) => { const fd = new FormData(); fd.append('file', file); return API.post(`/api/projects/${pid}/upload`, fd); },
  processUrl: (pid) => `/api/projects/${pid}/process`,

  // Segments
  getSegments: (pid) => API.get(`/api/projects/${pid}/segments`),
  getSegment: (id) => API.get(`/api/segments/${id}`),
  updateSegment: (id, d) => API.put(`/api/segments/${id}`, d),
  deleteSegment: (id) => API.del(`/api/segments/${id}`),
  insertSegment: (d) => API.post('/api/segments/insert', d),
  mergeSegments: (d) => API.post('/api/segments/merge', d),
  splitSegment: (id, d) => API.post(`/api/segments/${id}/split`, d),
  trimSegment: (id, d) => API.post(`/api/segments/${id}/trim`, d),
  resetDub: (id) => API.post(`/api/segments/${id}/reset-dub`),

  // Dubbing
  dubSegment: (id) => API.post(`/api/segments/${id}/dub`),
  cloneDubSegment: (id, voice_audio) => API.post(`/api/segments/${id}/clone-dub`, { voice_audio }),
  batchDubSSE: (pid, ids) => new EventSource(`/api/segments/batch-dub?project_id=${pid}&segment_ids=${ids.join(',')}`),
  batchCloneDubSSE: (pid, ids, va) => new EventSource(`/api/segments/batch-clone-dub?project_id=${pid}&segment_ids=${ids.join(',')}&voice_audio=${encodeURIComponent(va)}`),

  // Audio
  audioUrl: function(sid) { this._av++; return `/api/audio/${sid}?_=${this._av}`; },
  dubAudioUrl: function(sid) { this._av++; return `/api/audio/${sid}/dub?_=${this._av}`; },
  rawAudioUrl: function(pid) { this._av++; return `/api/audio/raw?project_id=${pid}&_=${this._av}`; },
  segWaveform: (sid, ctxBefore, ctxAfter) => API.get(`/api/segments/${sid}/waveform?context_before=${ctxBefore||0}&context_after=${ctxAfter||0}`),
  projWaveform: (pid) => API.get(`/api/projects/${pid}/waveform`),

  // Export
  exportAudio: (pid, mode) => API.post(`/api/projects/${pid}/export-audio`, { mode }),
  exportAudioDL: (pid) => `/api/projects/${pid}/export-audio/download`,
  exportSubtitle: (pid, fmt) => API.get(`/api/projects/${pid}/export/subtitle?format=${fmt}`),

  // Voices
  getVoices: () => API.get('/api/voices'),
  uploadVoice: (name, file) => { const fd = new FormData(); fd.append('name', name); fd.append('file', file); return API.post('/api/voices', fd); },
  deleteVoice: (id) => API.del(`/api/voices/${id}`),
  voiceAudioUrl: (id) => `/api/voices/${id}/audio`,

  // IndexTTS
  startIndextts: () => API.post('/api/indextts/start'),
  stopIndextts: () => API.post('/api/indextts/stop'),
  indexttsStatus: () => { API._av++; return API.get(`/api/indextts/status?_=${API._av}`); },

  // Misc
  health: () => API.get('/api/health'),
  version: () => API.get('/api/version'),
  modelsStatus: () => API.get('/api/models/status'),
  downloadModel: (id) => API.post(`/api/models/download/${id}`),
  taskLog: (pid) => API.get(`/api/projects/${pid}/task-log`),
};
