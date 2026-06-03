const App = {
  _settings: {},
  _pollTimers: {},
  _useLocalTts: false,
  _currentProjectId: null,
  _segments: [],
  _batchRunning: false,

  async init() {
    try { this._settings = await API.getSettings(); } catch (_) {}
    this._useLocalTts = !!this._settings.use_local_tts;
    try { document.getElementById('version-badge').textContent = 'v' + ((await API.version()).version || ''); } catch (_) {}
    // Task panel lazy scroll
    const tpBody = document.getElementById('task-panel-body');
    if (tpBody) {
      tpBody.addEventListener('scroll', function() {
        if (this.scrollTop + this.clientHeight >= this.scrollHeight - 10) {
          App._taskPage++;
          App._applyTaskPage();
        }
      });
    }
    // Hash-based routing
    window.addEventListener('hashchange', () => this._routeFromHash());
    this._routeFromHash();
  },
  _routeFromHash() {
    const hash = location.hash.replace('#', '') || 'projects';
    if (hash.startsWith('project/')) {
      this.navigate('project', hash.split('/')[1]);
    } else if (hash === 'projects' || hash === 'voices') {
      this.navigate(hash);
    }
  },

  // === Nav ===
  async navigate(page, params) {
    // Update URL hash
    const hash = page === 'project' ? `project/${params}` : page;
    if (location.hash !== '#' + hash) location.hash = hash;

    document.querySelectorAll('#topbar nav button').forEach(b => b.classList.remove('active'));
    const nb = document.getElementById('nav-' + page); if (nb) nb.classList.add('active');
    const main = document.getElementById('main-content');
    try {
      if (page === 'projects') await this._renderProjects(main);
      else if (page === 'project') { this._currentProjectId = params; await this._renderProject(main, params); }
      else if (page === 'voices') await this._renderVoices(main);
    } catch (e) { main.innerHTML = '<p style="color:var(--danger);padding:40px;text-align:center">加载失败: ' + this._esc(e.message) + '</p>'; }
  },

  // === Settings ===
  openSettings() {
    const s = this._settings;
    document.getElementById('setting-api-url').value = s.rh_api_url || 'http://localhost:8188';
    document.getElementById('setting-api-key').value = s.rh_api_key || '';
    document.getElementById('setting-rh-workflow').value = s.rh_workflow_id || '';
    document.getElementById('setting-rh-clone-workflow').value = s.rh_clone_workflow_id || '';
    document.getElementById('setting-hf-token').value = s.hf_token || '';
    this._updateTtsUI();
    document.getElementById('settings-modal').classList.remove('hidden');
  },
  closeSettings() { document.getElementById('settings-modal').classList.add('hidden'); },
  async saveSettings() {
    this._settings.rh_api_url = document.getElementById('setting-api-url').value.trim();
    this._settings.rh_api_key = document.getElementById('setting-api-key').value.trim();
    this._settings.rh_workflow_id = document.getElementById('setting-rh-workflow').value.trim();
    this._settings.rh_clone_workflow_id = document.getElementById('setting-rh-clone-workflow').value.trim();
    this._settings.hf_token = document.getElementById('setting-hf-token').value.trim();
    try { await API.saveSettings(this._settings); Components.showToast('设置已保存', 'success'); this.closeSettings(); }
    catch (e) { Components.showToast('保存失败: ' + e.message, 'error'); }
  },
  setTtsMode(m) {
    this._useLocalTts = (m === 'local');
    this._settings.use_local_tts = this._useLocalTts;
    this._updateTtsUI();
    API.saveSettings({ use_local_tts: this._useLocalTts }).catch(() => {});
  },
  _updateTtsUI() {
    const cloud = document.getElementById('tts-mode-cloud'), local = document.getElementById('tts-mode-local');
    const status = document.getElementById('local-tts-status');
    if (!cloud || !local) return;
    cloud.className = this._useLocalTts ? 'btn-sm' : 'btn-sm primary';
    local.className = this._useLocalTts ? 'btn-sm primary' : 'btn-sm';
    status.classList.toggle('hidden', !this._useLocalTts);
    if (this._useLocalTts) this._checkLocalStatus();
  },
  async _checkLocalStatus() {
    try {
      const s = await API.indexttsStatus();
      document.getElementById('local-tts-status-text').textContent = s.running ? '状态: 已就绪' : '状态: 未启动';
      const btn = document.getElementById('btn-start-local-tts');
      btn.textContent = s.running ? '停止本地模型' : '启动本地模型';
      btn.disabled = false;
    } catch (_) {}
  },
  async toggleLocalTts() {
    const btn = document.getElementById('btn-start-local-tts');
    btn.disabled = true; btn.textContent = '请稍候...';
    try {
      const s = await API.indexttsStatus().catch(() => ({}));
      if (s.running) { await API.stopIndextts(); Components.showToast('本地模型已停止', 'success'); }
      else { await API.startIndextts(); Components.showToast('本地模型已启动', 'success'); }
    } catch (e) { Components.showToast('操作失败: ' + e.message, 'error'); }
    this._checkLocalStatus();
  },

  // === Projects ===
  async _renderProjects(main) {
    main.innerHTML = '<p style="text-align:center;padding:60px;color:var(--text-muted)">加载中...</p>';
    const [list, modelStatus] = await Promise.all([
      API.getProjects(),
      API.modelsStatus().catch(() => null),
    ]);

    // 模型完整性检查
    let modelBanner = '';
    if (modelStatus) {
      const missing = [];
      const checks = {
        whisper: 'Whisper 转录模型',
        speaker: '说话人分离模型',
        nltk_punkt: 'NLTK 文本处理',
        funasr_punkt: '中文标点模型',
      };
      const installed = modelStatus.installed || {};
      for (const [key, label] of Object.entries(checks)) {
        if (!installed[key]) missing.push(label);
      }
      if (missing.length) {
        const critical = missing.filter(m => m !== '中文标点模型');
        const isCritical = critical.length > 0;
        modelBanner = `<div style="margin-bottom:18px;padding:12px 16px;border-radius:var(--radius);font-size:12.5px;font-weight:450;letter-spacing:-.01em;display:flex;align-items:center;justify-content:space-between;background:${isCritical?'var(--warning-lo)':'var(--subtle)'};border:1px solid ${isCritical?'#FDE68A':'var(--border)'};color:${isCritical?'var(--warning)':'var(--text2)'}">
          <span>⚠ ${missing.join('、')} 未安装，${isCritical?'上传音频将失败':'标点恢复将不可用'}</span>
          <button class="btn-sm primary" onclick="App.openModelManager()">查看模型</button>
        </div>`;
      }
    }

    let h = '<div class="page-header flex-between"><h2>项目列表</h2><button class="btn-primary" onclick="App._showCreateProject()">创建项目</button></div>';
    h += modelBanner;
    if (list.length) {
      list.forEach(p => {
        h += `<div class="project-card" onclick="App.navigate('project','${p.id}')" style="display:flex;align-items:center;justify-content:space-between">
          <div><h3>${this._esc(p.name)}</h3><div class="meta">${p.created_at||''} · ${p.status||''}</div></div>
          <button class="btn-sm" style="color:var(--danger)" onclick="event.stopPropagation();App._deleteProject('${p.id}')">删除</button>
        </div>`;
      });
    } else {
      h += '<p class="text-center" style="padding:40px;color:var(--text-muted)">还没有项目，创建一个开始吧</p>';
    }
    main.innerHTML = h;
  },
  _showCreateProject() {
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    const name = `配音项目_${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
    document.getElementById('create-project-name').value = name;
    document.getElementById('create-project-modal').classList.remove('hidden');
  },
  closeCreateProject() { document.getElementById('create-project-modal').classList.add('hidden'); },
  async _createProject() {
    const n = document.getElementById('create-project-name').value.trim();
    if (!n) return Components.showToast('请输入项目名称', 'error');
    this.closeCreateProject();
    const p = await API.createProject(n);
    this.navigate('project', p.id);
  },
  async _deleteProject(id) {
    if (!confirm('确定删除？')) return;
    await API.deleteProject(id);
    this.navigate('projects');
  },

  // === Project Detail ===
  async _renderProject(main, pid) {
    main.innerHTML = '<p style="text-align:center;padding:60px;color:var(--text-muted)">加载中...</p>';
    const proj = await API.getProject(pid);
    let h = `<div class="page-header flex-between"><span class="back-link" onclick="App.navigate('projects')">← 返回</span><h2>${this._esc(proj.name)}</h2><div></div></div>`;

    if (proj.status === 'new') {
      h += `<div class="upload-zone" onclick="document.getElementById('file-upload').click()"><h3>上传音频文件</h3><p>mp3 / wav / m4a / flac</p><input id="file-upload" type="file" accept="audio/*" style="display:none" onchange="App._upload('${pid}',this)"></div>`;
    } else if (proj.status === 'processing') {
      h += Components.renderProcessing();
      setTimeout(() => this.navigate('project', pid), 3000);
    } else if (proj.status === 'done') {
      const segs = await API.getSegments(pid);
      this._segments = segs;
      // Auto-reset orphaned processing segments (only on page load)
      for (const seg of segs) {
        if (seg.dub_status === 'processing') {
          try { await API.resetDub(seg.id); } catch (_) {}
        }
      }
      h += `<div class="status-bar"><div style="display:flex;gap:8px;flex-wrap:wrap">
        <button id="btn-batch-dub" class="btn-sm primary" onclick="App._batchDub('${pid}')">批量配音</button>
        <button class="btn-sm primary" onclick="App._batchCloneDub('${pid}')">批量克隆</button>
        <button class="btn-sm" onclick="App._exportAudio('${pid}')">导出音频</button>
        <button class="btn-sm" onclick="App._exportSubtitle('${pid}','srt')">SRT</button>
        <button class="btn-sm" onclick="App._exportSubtitle('${pid}','ass')">ASS</button>
      </div></div>`;
      h += Components.renderWorkspace(segs, pid);
    } else {
      h += '<p style="color:var(--danger);text-align:center;padding:40px">处理失败，请删除项目重试</p>';
    }
    main.innerHTML = h;
  },
  async _upload(pid, input) {
    if (!input.files[0]) return;
    try {
      Components.showToast('上传中...', 'info');
      await API.uploadAudio(pid, input.files[0]);
      const main = document.getElementById('main-content');
      main.innerHTML = Components.renderProcessing();
      const es = new EventSource(API.processUrl(pid));
      es.addEventListener('step', (e) => {
        const d = JSON.parse(e.data);
        Components.updateProgress(d.step || '', d.detail || '');
      });
      es.addEventListener('tick', () => {});
      es.addEventListener('done', (e) => {
        es.close();
        const d = JSON.parse(e.data);
        Components.showToast(`处理完成: ${d.segments}段, ${d.speakers}位说话人`, 'success');
        this.navigate('project', pid);
      });
      es.addEventListener('fail', (e) => {
        es.close();
        let msg = '处理失败';
        try { const d = JSON.parse(e.data); msg = d.message || msg; } catch (_) {}
        Components.showToast(msg, 'error');
      });
      es.onerror = () => { es.close(); Components.showToast('处理连接中断', 'error'); };
    } catch (e) { Components.showToast('上传失败: ' + e.message, 'error'); }
  },
  async refreshWorkspace() {
    if (!this._currentProjectId) return;
    const segs = await API.getSegments(this._currentProjectId);
    this._segments = segs;
    const fresh = segs;
    const container = document.getElementById('segments-container');
    if (container) {
      container.innerHTML = Components._renderSegmentList(fresh, this._currentProjectId);
    }
    this._checkBatchReady();
  },

  // === Dubbing ===
  async dubSegment(segId) {
    if (this._useLocalTts) {
      const s = await API.indexttsStatus().catch(() => ({}));
      if (!s.running) return Components.showToast('本地模型未启动，请先在系统设置中启动本地模型', 'error');
    }
    Components.setDubButtonState(segId, 'processing');
    this._addTask(segId, (this._useLocalTts ? '（本地）' : '（云端）') + '配音');
    try { await API.dubSegment(segId); this._pollDub(segId); }
    catch (e) { Components.setDubButtonState(segId); this._updateTask(segId, 'error'); Components.showToast('配音失败: ' + (e.message || '未知错误'), 'error'); }
  },
  async cloneDubSegment(segId) {
    if (this._useLocalTts) {
      const s = await API.indexttsStatus().catch(() => ({}));
      if (!s.running) return Components.showToast('本地模型未启动，请先在系统设置中启动本地模型', 'error');
    }
    Components._showVoicePicker(async (voiceAudioPath) => {
      const btn = document.getElementById('clone-btn-' + segId);
      if (btn) { btn.disabled = true; btn.textContent = '处理中...'; }
      this._addTask(segId, (this._useLocalTts ? '（本地）' : '（云端）') + '克隆配音');
      try {
        await API.cloneDubSegment(segId, voiceAudioPath);
        this._pollClone(segId);
      } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = '克隆配音'; }
        this._updateTask(segId, 'error');
        Components.showToast('克隆失败: ' + (e.message || '未知错误'), 'error');
      }
    });
  },

  _pollDub(segId) {
    if (this._pollTimers[segId]) return;
    this._pollTimers[segId] = setInterval(async () => {
      try {
        const seg = await API.getSegment(segId);
        if (seg.dub_status === 'done') { clearInterval(this._pollTimers[segId]); delete this._pollTimers[segId]; Components.setDubButtonState(segId, 'done'); this._showDubResult(segId); this._updateTask(segId, 'done'); this._checkBatchReady(); }
        else if (seg.dub_status === 'error') { clearInterval(this._pollTimers[segId]); delete this._pollTimers[segId]; Components.setDubButtonState(segId, 'error'); this._updateTask(segId, 'error'); this._checkBatchReady(); }
      } catch (_) {}
    }, 3000);
  },
  _pollClone(segId) {
    if (this._pollTimers[segId]) return;
    this._pollTimers[segId] = setInterval(async () => {
      try {
        const seg = await API.getSegment(segId);
        const btn = document.getElementById('clone-btn-' + segId);
        if (seg.dub_status === 'done') { clearInterval(this._pollTimers[segId]); delete this._pollTimers[segId]; if (btn) { btn.disabled = false; btn.textContent = '克隆配音'; } this._showDubResult(segId); this._updateTask(segId, 'done'); Components.showToast('克隆配音完成', 'success'); }
        else if (seg.dub_status === 'error') { clearInterval(this._pollTimers[segId]); delete this._pollTimers[segId]; if (btn) { btn.disabled = false; btn.textContent = '克隆配音'; } this._updateTask(segId, 'error'); Components.showToast('克隆配音失败', 'error'); }
      } catch (_) {}
    }, 3000);
  },
  _showDubResult(segId) {
    const url = API.dubAudioUrl(segId);
    const row = document.getElementById('seg-' + segId);
    if (!row) return;

    // Show dub play icon
    let icon = document.getElementById('play-dub-icon-' + segId);
    if (icon) {
      icon.style.visibility = 'visible';
      icon.setAttribute('onclick', "Components.toggleAudio('"+segId+"','dub','"+url+"')");
    } else {
      // Create icon if it doesn't exist (for dubs done before page load)
      const editRow = row.querySelector('.text-row:last-child');
      if (editRow) {
        icon = document.createElement('span');
        icon.id = 'play-dub-icon-' + segId;
        icon.className = 'seg-play-btn seg-play-dub';
        icon.title = '试听配音';
        icon.innerHTML = '<svg viewBox="0 0 24 24" style="width:10px;height:10px;fill:currentColor"><polygon points="5,3 19,12 5,21"/></svg>';
        icon.setAttribute('onclick', "Components.toggleAudio('"+segId+"','dub','"+url+"')");
        editRow.insertBefore(icon, editRow.firstChild);
      }
    }

    // Add download button if not present
    const actionsDiv = row.querySelector('.segment-header .actions');
    if (actionsDiv && !document.getElementById('dl-dub-' + segId)) {
      const dlBtn = document.createElement('button');
      dlBtn.id = 'dl-dub-' + segId;
      dlBtn.className = 'btn-sm success seg-dl-btn';
      dlBtn.textContent = '下载新配音';
      dlBtn.title = '下载配音文件';
      dlBtn.onclick = () => Components.downloadFile(url, 'dub_' + segId + '.wav');
      actionsDiv.appendChild(dlBtn);
    }

    // Add badge next to time if not present
    if (!row.querySelector('.dub-badge')) {
      const badge = document.createElement('span');
      badge.className = 'dub-badge';
      badge.textContent = '已配音';
      const timeSpan = row.querySelector('.segment-header .time');
      if (timeSpan) timeSpan.after(badge);
    }
  },

  // === Batch ===
  async _batchDub(pid) {
    if (this._useLocalTts) {
      const s = await API.indexttsStatus().catch(() => ({}));
      if (!s.running) return Components.showToast('本地模型未启动，请先在系统设置中启动本地模型', 'error');
    }
    const cbs = document.querySelectorAll('.seg-checkbox:checked');
    if (!cbs.length) return Components.showToast('请勾选段', 'error');
    const ids = Array.from(cbs).map(c => c.dataset.segId);
    const label = (this._useLocalTts ? '（本地）' : '（云端）') + '批量配音';
    ids.forEach(id => { Components.setDubButtonState(id, 'processing'); this._addTask(id, label); });
    this._batchRunning = true; this._checkBatchReady();
    const es = API.batchDubSSE(pid, ids);
    es.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.status === 'done') { Components.setDubButtonState(d.segment_id, 'done'); this._showDubResult(d.segment_id); this._updateTask(d.segment_id, 'done'); }
      else if (d.status === 'error') { Components.setDubButtonState(d.segment_id, 'error'); this._updateTask(d.segment_id, 'error'); }
      if (d.progress >= d.total) { es.close(); this._batchRunning = false; this._checkBatchReady(); }
    };
  },
  async _batchCloneDub(pid) {
    if (this._useLocalTts) {
      const s = await API.indexttsStatus().catch(() => ({}));
      if (!s.running) return Components.showToast('本地模型未启动，请先在系统设置中启动本地模型', 'error');
    }
    const cbs = document.querySelectorAll('.seg-checkbox:checked');
    if (!cbs.length) return Components.showToast('请勾选段', 'error');
    Components._showVoicePicker((voiceAudioPath) => {
      const ids = Array.from(cbs).map(c => c.dataset.segId);
      this._batchRunning = true; this._checkBatchReady();
      const es = API.batchCloneDubSSE(pid, ids, voiceAudioPath);
      es.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.status === 'done') { this._showDubResult(d.segment_id); this._updateTask(d.segment_id, 'done'); }
        else if (d.status === 'error') { this._updateTask(d.segment_id, 'error'); }
        if (d.progress >= d.total) { es.close(); this._batchRunning = false; this._checkBatchReady(); }
      };
    });
  },

  // === Export ===
  async _exportAudio(pid) {
    try { Components.showToast('导出中...', 'info'); await API.exportAudio(pid, 'stretch'); window.open(API.exportAudioDL(pid)); Components.showToast('导出完成', 'success'); }
    catch (e) { Components.showToast('导出失败: ' + e.message, 'error'); }
  },
  async _exportSubtitle(pid, fmt) {
    try {
      const data = await API.exportSubtitle(pid, fmt);
      const blob = new Blob([data.content || ''], { type: 'text/plain;charset=utf-8' });
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'subtitles.' + fmt; a.click();
    } catch (e) { Components.showToast('导出失败: ' + e.message, 'error'); }
  },

  // === Voices ===
  async _renderVoices(main) {
    const voices = await API.getVoices();
    let h = '<div class="page-header"><h2>音色库</h2></div>';
    h += `<div style="display:flex;gap:8px;margin-bottom:16px"><input id="voice-name-input" placeholder="音色名称" style="flex:1"><input id="voice-file-input" type="file" accept="audio/*" style="display:none" onchange="App._uploadVoice()"><button class="btn-primary" onclick="document.getElementById('voice-file-input').click()">上传音色</button></div>`;
    if (!voices.length) {
      h += '<p class="text-center" style="padding:40px;color:var(--text-muted)">暂无音色</p>';
    } else {
      h += '<div class="voice-grid">';
      voices.forEach(v => {
        h += `<div class="voice-card"><div class="voice-info">${this._esc(v.name)}</div><div class="voice-actions"><button class="btn-sm" onclick="Components.toggleAudio('v${v.id}','orig','${API.voiceAudioUrl(v.id)}')">试听</button><button class="btn-sm" style="color:var(--danger)" onclick="App._deleteVoice('${v.id}')">删除</button></div></div>`;
      });
      h += '</div>';
    }
    main.innerHTML = h;
  },
  async _uploadVoice() {
    const f = document.getElementById('voice-file-input').files[0]; if (!f) return;
    const n = document.getElementById('voice-name-input').value.trim() || f.name.replace(/\.[^.]+$/, '');
    try { await API.uploadVoice(n, f); Components.showToast('上传成功', 'success'); this.navigate('voices'); }
    catch (e) { Components.showToast('上传失败: ' + e.message, 'error'); }
  },
  async _deleteVoice(id) { if (!confirm('确定删除？')) return; await API.deleteVoice(id); this.navigate('voices'); },

  // === Models ===
  _modelHelp: {
    'speaker-diarization': [
      '1. 注册 HuggingFace 账号: https://huggingface.co/join',
      '2. 访问 https://hf.co/pyannote/speaker-diarization-3.1 点击 "Agree and access repository"',
      '3. 访问 https://hf.co/pyannote/segmentation-3.0 同样点击同意',
      '4. 在 https://huggingface.co/settings/tokens 创建 Access Token',
      '5. 在下方填入 Token 后点击下载按钮',
    ],
    'funasr-punctuation': [
      '国内用户可直接从 ModelScope 下载，速度快',
      '地址: https://modelscope.cn/models/iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch',
      '下载后将 model.pt 和 tokens.json 放入 model/punctuation_funasr/',
    ],
  },

  async openModelManager() {
    document.getElementById('models-modal').classList.remove('hidden');
    const list = document.getElementById('models-list');
    list.innerHTML = '<p class="text-center" style="padding:20px;color:var(--text-muted)">加载中...</p>';
    try {
      const data = await API.modelsStatus();
      let h = '';

      // Runtime info
      const rt = data.runtime || {};
      h += `<div style="margin-bottom:16px;padding:12px;background:var(--border-light);border-radius:8px;font-size:12px">
        <div><strong>运行环境</strong></div>
        <div style="color:var(--text-secondary);margin-top:4px">${rt.variant||'?'} · Torch ${rt.torch_version||'?'} · ${rt.gpu_name||'无GPU'}</div>
        <div style="color:var(--text-muted);font-size:10px;margin-top:2px">CUDA 12.8 · 支持 RTX 30/40/50 系列 · 建议 ≥8GB 显存</div>
      </div>`;

      // Downloadable models
      const dl = data.downloadable || [];
      if (dl.length) {
        h += '<div style="font-weight:600;font-size:12px;margin-bottom:8px">可自动下载</div>';
        dl.forEach(m => {
          h += `<div class="model-item">
            <div><strong>${this._esc(m.name)}</strong><span style="font-size:10px;color:var(--text-muted);margin-left:8px">${m.size||''}</span></div>
            <div style="font-size:11px;color:var(--text-secondary);margin:4px 0">${this._esc(m.desc||'')}</div>
            <div>${m.installed ? '<span style="color:var(--success);font-size:11px">✓ 已安装</span>' : `<button class="btn-sm primary" onclick="App._downloadModel('${m.id}')">下载</button>`}</div>
          </div>`;
        });
      }

      // Manual models
      const manual = data.manual || [];
      if (manual.length) {
        h += '<div style="font-weight:600;font-size:12px;margin:16px 0 8px">需手动下载</div>';
        h += '<p style="font-size:10px;color:var(--text-muted);margin-bottom:8px">以下模型需许可授权，点击 ? 查看步骤</p>';
        manual.forEach(m => {
          const help = this._modelHelp[m.id] || [];
          h += `<div class="model-item">
            <div style="display:flex;align-items:center;gap:6px">
              <strong>${this._esc(m.name)}</strong><span style="font-size:10px;color:var(--text-muted)">${m.size||''}</span>
              <span onclick="App._toggleModelHelp(event,'${m.id}')" title="下载说明" style="display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;background:var(--primary);color:#fff;font-size:11px;cursor:pointer;font-weight:600">?</span>
            </div>
            <div style="font-size:11px;color:var(--text-secondary);margin:4px 0">${this._esc(m.desc||'')}</div>
            <div id="model-help-${m.id}" style="display:none;font-size:10px;color:var(--text-secondary);background:var(--border-light);padding:8px 10px;border-radius:6px;margin:6px 0;line-height:1.6">${help.map(s => `<div>${this._esc(s)}</div>`).join('')}</div>
            <div>${m.installed ? '<span style="color:var(--success);font-size:11px">✓ 已安装</span>' :
              `<button class="btn-sm primary" onclick="App._downloadModel('${m.id}')">下载</button>`}
            </div>
          </div>`;
        });
      }

      // HF Token
      h += `<div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border)">
        <label for="setting-hf-token-inline" style="font-size:12px;font-weight:600">HuggingFace Token</label>
        <p style="font-size:10px;color:var(--text-muted);margin:4px 0">下载 HuggingFace 模型需要 Access Token（免费注册即可获取）</p>
        <div style="display:flex;gap:6px">
          <input id="setting-hf-token-inline" type="password" value="${this._settings.hf_token||''}" placeholder="hf_xxx" style="flex:1;font-size:12px;padding:6px 10px">
          <button class="btn-sm primary" onclick="App._saveHfToken()">保存</button>
        </div>
      </div>`;

      list.innerHTML = h;
    } catch (_) { list.innerHTML = '<p style="color:var(--danger)">加载失败</p>'; }
  },
  _toggleModelHelp(e, id) {
    e.stopPropagation();
    const el = document.getElementById('model-help-' + id);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
  },
  async _saveHfToken() {
    const tok = document.getElementById('setting-hf-token-inline').value.trim();
    this._settings.hf_token = tok;
    try { await API.saveSettings({ hf_token: tok }); Components.showToast('Token 已保存', 'success'); }
    catch (e) { Components.showToast('保存失败', 'error'); }
  },
  closeModelManager() { document.getElementById('models-modal').classList.add('hidden'); },
  async _downloadModel(id) {
    Components.showToast('开始下载，请耐心等待...', 'info');
    try {
      await API.downloadModel(id);
      Components.showToast('下载完成', 'success');
      this.openModelManager();
    } catch (e) { Components.showToast('下载失败: ' + e.message, 'error'); }
  },

  // === Segment Ops ===
  async deleteSegment(id) { await API.deleteSegment(id); this.refreshWorkspace(); },
  async resetDub(id) { await API.resetDub(id); this.refreshWorkspace(); },
  async mergeSegments(ids) {
    if (ids.length < 2) return;
    try {
      await API.mergeSegments({ segment_ids: ids });
      this.refreshWorkspace();
      Components.showToast('合并完成', 'success');
    } catch (e) { Components.showToast('合并失败: ' + e.message, 'error'); }
  },

  // === Task Panel ===
  _taskPage: 0,
  _taskPageSize: 10,
  toggleTaskPanel() {
    const b = document.getElementById('task-panel-body');
    b.style.display = b.style.display === 'none' ? 'block' : 'none';
  },
  _addTask(segId, label) {
    const body = document.getElementById('task-panel-body');
    const now = new Date();
    const time = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
    const div = document.createElement('div');
    div.id = 'task-' + segId;
    div.className = 'task-item';
    div.innerHTML = `<div style="display:flex;justify-content:space-between;margin-bottom:2px"><span style="font-weight:600">${label}</span><div style="display:flex;align-items:center;gap:6px"><span style="color:var(--text-muted);font-size:10px;white-space:nowrap">${time}</span><button class="task-del-btn" onclick="App._deleteTask('${segId}')" title="删除此任务并恢复段状态" style="display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border:none;background:transparent;color:var(--text-muted);cursor:pointer;font-size:14px;padding:0;line-height:1;border-radius:3px" onmouseenter="this.style.background='#FEE2E2';this.style.color='var(--danger)'" onmouseleave="this.style.background='transparent';this.style.color='var(--text-muted)'">&times;</button></div></div>
      <div class="task-text" style="color:var(--text-secondary)">加载中...</div>
      <div class="task-status" style="color:var(--text-muted);margin-top:2px">处理中...</div>`;
    body.prepend(div);
    document.getElementById('task-count').textContent = body.children.length;
    body.style.display = 'block';
    API.getSegment(segId).then(seg => {
      const txt = div.querySelector('.task-text');
      if (txt && seg) txt.textContent = (seg.edited_text || seg.original_text || '').slice(0, 40);
    }).catch(() => {});
    this._applyTaskPage();
  },
  async _deleteTask(segId) {
    try {
      await API.resetDub(segId);
    } catch (_) {}
    const el = document.getElementById('task-' + segId);
    if (el) el.remove();
    const body = document.getElementById('task-panel-body');
    document.getElementById('task-count').textContent = body ? body.children.length : 0;
    this.refreshWorkspace();
  },
  _updateTask(segId, status) {
    const el = document.getElementById('task-' + segId); if (!el) return;
    const st = el.querySelector('.task-status');
    API.getSegment(segId).then(seg => {
      const txt = el.querySelector('.task-text');
      if (txt && seg) txt.textContent = (seg.edited_text || seg.original_text || '').slice(0, 40);
      if (st) {
        const t = parseFloat(seg.dub_time || 0);
        const ts = t > 0 ? ` (${t.toFixed(1)}s)` : '';
        st.textContent = (status === 'done' ? '✓ 完成' : '✗ 失败') + ts;
        st.style.color = status === 'done' ? 'var(--success)' : 'var(--danger)';
      }
    }).catch(() => {});
  },
  _applyTaskPage() {
    const body = document.getElementById('task-panel-body');
    if (!body) return;
    const items = body.querySelectorAll('.task-item');
    const show = Math.min(items.length, this._taskPage * this._taskPageSize + this._taskPageSize);
    items.forEach((item, i) => {
      item.style.display = i < show ? '' : 'none';
    });
  },

  _checkBatchReady() {
    const btn = document.getElementById('btn-batch-dub');
    if (btn) btn.disabled = this._batchRunning || document.querySelectorAll('.seg-dub-btn:disabled').length > 0;
  },
  _esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); },
};
document.addEventListener('DOMContentLoaded', () => App.init());
