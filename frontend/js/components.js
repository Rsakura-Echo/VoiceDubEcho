const Components = {
  _currentAudio: null,
  _currentIconId: null,
  _textTimers: {},
  _emoOpen: null,

  // Standard IndexTTS2 emotions
  EMOTIONS: ['happy','angry','sad','fear','hate','low','surprise','neutral'],

  showToast(msg, type) {
    if (!msg) { console.warn('[showToast] suppressed empty toast', type); return; }
    const c = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = 'toast' + (type ? ' ' + type : '');
    el.textContent = msg;
    c.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; setTimeout(() => el.remove(), 300); }, 3000);
  },

  renderProcessing() {
    this._currentStepIdx = 0;
    const steps = this._processSteps || [];
    let dots = '';
    steps.forEach((s, i) => {
      dots += `<div class="progress-step-dot" id="step-dot-${i}"><div class="dot"></div><span>${s.label}</span></div>`;
    });
    return `<div class="progress-panel">
      <div class="progress-title">音频处理中</div>
      <div class="progress-steps-row">${dots}</div>
      <div class="progress-bar-track"><div class="progress-bar-fill" id="progress-fill" style="width:0%"></div></div>
      <div class="progress-detail-text" id="progress-detail">准备中...</div>
    </div>`;
  },
  _processSteps: [
    {key:'load_model', label:'加载模型', icon:'1'},
    {key:'load_audio', label:'读取音频', icon:'2'},
    {key:'transcribe', label:'语音识别', icon:'3'},
    {key:'align', label:'文字对齐', icon:'4'},
    {key:'diarize', label:'人声分离', icon:'5'},
    {key:'punctuation', label:'标点恢复', icon:'6'},
    {key:'segment', label:'导出片段', icon:'7'},
  ],
  _currentStepIdx: 0,
  updateProgress(stepName, detail) {
    const idx = this._processSteps.findIndex(s => stepName.startsWith(s.key));
    if (idx >= 0) {
      this._currentStepIdx = idx;
      for (let i = 0; i < this._processSteps.length; i++) {
        const dot = document.getElementById('step-dot-' + i);
        if (dot) dot.className = 'progress-step-dot' + (i < idx ? ' done' : i === idx ? ' active' : '');
      }
    }
    const fill = document.getElementById('progress-fill');
    if (fill) fill.style.width = Math.min(100, ((this._currentStepIdx + 1) / this._processSteps.length) * 100) + '%';
    const detailEl = document.getElementById('progress-detail');
    if (detailEl) detailEl.textContent = detail || stepName;
  },

  // === Project Header ===
  renderProjectHeader(project) {
    return `<div class="page-header flex-between">
      <span class="back-link" onclick="App.navigate('projects')">← 返回</span>
      <h2>${this._esc(project.name)}</h2>
      <div></div>
    </div>
    <div class="status-bar mt-16">
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button id="btn-batch-dub" class="btn-sm primary" onclick="App._batchDub('${project.id}')">批量配音</button>
        <button class="btn-sm primary" onclick="App._batchCloneDub('${project.id}')">批量克隆</button>
        <button class="btn-sm" onclick="App._exportAudio('${project.id}')">导出音频</button>
        <button class="btn-sm" onclick="App._exportSubtitle('${project.id}','srt')">SRT</button>
        <button class="btn-sm" onclick="App._exportSubtitle('${project.id}','ass')">ASS</button>
      </div>
    </div>`;
  },

  // === Upload ===
  renderUploadZone(projectId) {
    return `<div class="upload-zone" onclick="document.getElementById('file-upload').click()">
      <h3>上传音频文件</h3><p>mp3 / wav / m4a / flac</p>
      <input id="file-upload" type="file" accept="audio/*" style="display:none" onchange="App._upload('${projectId}',this)">
    </div>`;
  },

  // === Workspace ===
  renderWorkspace(segments, projectId) {
    return this.renderSpeakerFilter(segments) + '<div id="segments-container">' + this._renderSegmentList(segments, projectId) + '</div>';
  },

  renderSpeakerFilter(segments) {
    const speakers = [...new Set(segments.map(s => s.speaker).filter(Boolean))];
    if (speakers.length < 2) {
      return `<div style="margin-bottom:8px;display:flex;gap:8px;align-items:center">
        <label style="display:flex;align-items:center;gap:4px;font-size:12px;cursor:pointer;margin:0"><input type="checkbox" id="select-all-segs" onchange="Components._toggleSelectAll(this)"> 全选</label>
      </div>`;
    }
    const colors = ['#3B82F6','#EF4444','#10B981','#F59E0B','#8B5CF6','#EC4899','#F97316','#6366F1'];
    let html = '<div style="margin-bottom:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">';
    html += '<label style="display:flex;align-items:center;gap:4px;font-size:12px;cursor:pointer;margin:0"><input type="checkbox" id="select-all-segs" onchange="Components._toggleSelectAll(this)"> 全选</label>';
    html += '<span class="label-hint">说话人:</span>';
    speakers.forEach((spk, i) => {
      html += `<label style="display:flex;align-items:center;gap:2px;font-size:11px;cursor:pointer;margin:0;color:${colors[i%colors.length]}"><input type="checkbox" class="speaker-cb" data-speaker="${this._esc(spk)}" onchange="Components._toggleSpeaker('${this._esc(spk)}',this)">${this._esc(spk)}</label>`;
    });
    html += '</div>';
    return html;
  },
  _toggleSelectAll(cb) {
    document.querySelectorAll('.seg-checkbox').forEach(c => c.checked = cb.checked);
    document.querySelectorAll('.speaker-cb').forEach(c => c.checked = cb.checked);
  },
  _toggleSpeaker(spk, cb) {
    document.querySelectorAll('.seg-checkbox').forEach(c => {
      if (c.closest('.segment-row')?.dataset.speaker === spk) c.checked = cb.checked;
    });
    document.getElementById('select-all-segs').checked = document.querySelectorAll('.speaker-cb:checked').length === document.querySelectorAll('.speaker-cb').length;
  },

  // === Segment List ===
  _renderSegmentList(segments, projectId) {
    if (!segments.length) return '<p class="text-center" style="padding:60px;color:var(--text-muted)">暂无段数据</p>';
    const speakers = [...new Set(segments.map(s => s.speaker).filter(Boolean))];
    const colors = ['#3B82F6','#EF4444','#10B981','#F59E0B','#8B5CF6','#EC4899','#F97316','#6366F1'];
    const cmap = {}; speakers.forEach((s, i) => cmap[s] = colors[i % colors.length]);

    let html = '';
    // Insert before first
    html += this._renderBetweenZone(projectId, null, segments[0]);

    segments.forEach((seg, idx) => {
      const clr = cmap[seg.speaker] || '#94A3B8';
      const origUrl = API.audioUrl(seg.id);
      const hasDub = !!seg.dubbed_audio_path;
      const dubUrl = hasDub ? API.dubAudioUrl(seg.id) : '';
      const origText = seg.original_text || '';
      const editText = seg.edited_text || origText;
      const busy = seg.dub_status === 'processing';
      const emo = this._parseEmotion(seg.emotion);

      html += `<div class="segment-row" id="seg-${seg.id}" data-speaker="${this._esc(seg.speaker)}" data-seg-id="${seg.id}" ondblclick="AudioEditor.open('${seg.id}')">
        <button class="seg-delete-btn" onclick="event.stopPropagation();App.deleteSegment('${seg.id}')" title="删除此段">×</button>`;

      // Header
      html += '<div class="segment-header">';
      html += `<input type="checkbox" class="seg-checkbox" data-seg-id="${seg.id}" onchange="document.getElementById('select-all-segs').checked = document.querySelectorAll('.seg-checkbox:checked').length === document.querySelectorAll('.seg-checkbox').length">`;
      html += `<span class="speaker-badge" style="background:${clr}20;color:${clr}">${this._esc(seg.speaker||'SPK'+(idx+1))}</span>`;
      html += `<span class="time">${(seg.start_time||0).toFixed(1)}s – ${(seg.end_time||0).toFixed(1)}s</span>`;
      if (seg.duration) html += `<span class="time">${seg.duration.toFixed(1)}s</span>`;
      if (hasDub) html += '<span class="dub-badge">已配音</span>';

      html += '<div style="flex:1"></div>';
      html += '<div class="actions">';

      // Emotion dropdown
      const hasEmo = Object.values(emo).some(v => v > 0);
      html += `<div class="emo-panel" id="emo-panel-${seg.id}">`;
      html += `<button class="emo-trigger${hasEmo?' active':''}" id="emo-trigger-${seg.id}" onclick="Components._toggleEmo('${seg.id}',event)">情绪${hasEmo?' ●':''}</button>`;
      html += `<div class="emo-dropdown" id="emo-drop-${seg.id}">`;
      this.EMOTIONS.forEach(e => {
        const val = emo[e] || 0;
        html += `<div class="emo-item"><label>${e}</label><input type="range" min="0" max="1.4" step="0.05" value="${val}" oninput="Components._emoChange('${seg.id}','${e}',this.value)"><span class="emo-val">${parseFloat(val).toFixed(2)}</span></div>`;
      });
      html += `<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border)"><button class="btn-sm" onclick="Components._emoReset('${seg.id}')">重置</button></div>`;
      html += '</div></div>';

      // Dub buttons
      if (busy) {
        html += `<span style="display:inline-flex;align-items:center;gap:6px"><button id="dub-btn-${seg.id}" class="btn-sm seg-dub-btn" disabled>处理中...</button><button class="btn-sm" style="color:var(--danger);padding:4px 8px;font-size:10px" onclick="App.resetDub('${seg.id}')" title="取消并重置此段配音状态">✕</button></span>`;
      } else {
        html += `<button id="dub-btn-${seg.id}" class="btn-sm primary seg-dub-btn" onclick="App.dubSegment('${seg.id}')">开始配音</button>`;
      }
      html += `<button id="clone-btn-${seg.id}" class="btn-sm primary" onclick="App.cloneDubSegment('${seg.id}')">克隆配音</button>`;
      if (hasDub) {
        html += `<button id="dl-dub-${seg.id}" class="btn-sm success seg-dl-btn" onclick="Components.downloadFile('${dubUrl}','dub_${seg.id}.wav')" title="下载配音文件">下载新配音</button>`;
      }
      html += '</div></div>';

      // Body: each text row with its own play button
      html += '<div class="segment-body">';
      html += '<div class="text-row">';
      html += `<span id="play-orig-icon-${seg.id}" class="seg-play-btn seg-play-orig" onclick="Components.toggleAudio('${seg.id}','orig','${origUrl}')" title="试听原音"><svg viewBox="0 0 24 24"><polygon points="5,3 19,12 5,21"/></svg></span>`;
      html += `<div class="text-orig" style="flex:1">${this._esc(origText)}</div>`;
      html += '</div>';
      html += '<div class="text-row">';
      if (hasDub) html += `<span id="play-dub-icon-${seg.id}" class="seg-play-btn seg-play-dub" onclick="Components.toggleAudio('${seg.id}','dub','${dubUrl}')" title="试听配音"><svg viewBox="0 0 24 24"><polygon points="5,3 19,12 5,21"/></svg></span>`;
      else html += `<span id="play-dub-icon-${seg.id}" class="seg-play-btn seg-play-dub" style="visibility:hidden"><svg viewBox="0 0 24 24"><polygon points="5,3 19,12 5,21"/></svg></span>`;
      html += `<textarea id="text-${seg.id}" class="text-edit" onchange="Components._onTextChange('${seg.id}')" placeholder="编辑台词..." style="flex:1">${this._esc(editText)}</textarea>`;
      html += '</div></div>';
      html += '</div>';

      // Insert/Merge between this and next segment
      const next = idx + 1 < segments.length ? segments[idx + 1] : null;
      html += this._renderBetweenZone(projectId, seg, next);
    });

    return html;
  },

  _renderBetweenZone(projectId, prev, next) {
    if (!prev && !next) return '';
    let btns = '';
    // Insert always shown
    const posData = prev ? {after: prev.id, project_id: projectId} : {before: next.id, project_id: projectId};
    btns += `<button class="btn-sm" onclick="AudioEditor.openInsert('${projectId}','${prev?.id||''}','${next?.id||''}')">+ 插入</button>`;
    // Merge only between two segments
    if (prev && next) {
      btns += `<button class="btn-sm" onclick="App.mergeSegments(['${prev.id}','${next.id}'])">⇅ 合并</button>`;
    }
    return `<div class="seg-between"><div class="seg-between-inner">${btns}</div></div>`;
  },

  _parseEmotion(emoStr) {
    if (!emoStr) return {};
    try { return JSON.parse(emoStr); } catch (_) { return {}; }
  },
  _toggleEmo(segId, e) {
    if (e) e.stopPropagation();
    const dd = document.getElementById('emo-drop-' + segId);
    if (!dd) return;
    if (this._emoOpen && this._emoOpen !== segId) {
      const prev = document.getElementById('emo-drop-' + this._emoOpen);
      if (prev) prev.classList.remove('open');
    }
    dd.classList.toggle('open');
    this._emoOpen = dd.classList.contains('open') ? segId : null;
  },
  _emoChange(segId, emo, val) {
    document.querySelectorAll(`#emo-drop-${segId} .emo-val`).forEach(el => {
      const range = el.previousElementSibling;
      if (range) el.textContent = parseFloat(range.value).toFixed(2);
    });
    // Update trigger button visual
    this._updateEmoTrigger(segId);
    // Save
    clearTimeout(this._emoTimers ? this._emoTimers[segId] : null);
    if (!this._emoTimers) this._emoTimers = {};
    this._emoTimers[segId] = setTimeout(async () => {
      const ranges = document.querySelectorAll(`#emo-drop-${segId} input[type=range]`);
      const emoObj = {};
      ranges.forEach(r => { emoObj[r.parentElement.querySelector('label').textContent] = parseFloat(r.value); });
      try { await API.updateSegment(segId, { emotion: JSON.stringify(emoObj) }); } catch (_) {}
    }, 300);
  },
  _emoReset(segId) {
    document.querySelectorAll(`#emo-drop-${segId} input[type=range]`).forEach(r => { r.value = 0; });
    document.querySelectorAll(`#emo-drop-${segId} .emo-val`).forEach(el => { el.textContent = '0.00'; });
    this._updateEmoTrigger(segId);
    try { API.updateSegment(segId, { emotion: '{}' }); } catch (_) {}
  },
  _updateEmoTrigger(segId) {
    const trigger = document.getElementById('emo-trigger-' + segId);
    if (!trigger) return;
    const ranges = document.querySelectorAll(`#emo-drop-${segId} input[type=range]`);
    let hasVal = false;
    ranges.forEach(r => { if (parseFloat(r.value) > 0) hasVal = true; });
    if (hasVal) {
      trigger.classList.add('active');
      trigger.textContent = '情绪 ●';
    } else {
      trigger.classList.remove('active');
      trigger.textContent = '情绪';
    }
  },

  _onTextChange(segId) {
    const el = document.getElementById('text-' + segId);
    if (!el) return;
    if (!this._textTimers) this._textTimers = {};
    clearTimeout(this._textTimers[segId]);
    this._textTimers[segId] = setTimeout(async () => {
      try { await API.updateSegment(segId, { edited_text: el.value }); } catch (_) {}
    }, 500);
  },

  setDubButtonState(segId, state) {
    const btn = document.getElementById('dub-btn-' + segId);
    if (!btn) return;
    btn.disabled = (state === 'processing');
    btn.textContent = state === 'processing' ? '处理中...' : state === 'done' ? '重新配音' : state === 'error' ? '重试' : '开始配音';
  },

  // === Audio ===
  toggleAudio(segId, type, url) {
    const iconId = (type === 'orig' ? 'play-orig-icon-' : 'play-dub-icon-') + segId;
    const icon = document.getElementById(iconId);
    if (!icon) return;
    if (this._currentAudio && this._currentIconId === iconId && !this._currentAudio.paused) {
      this._currentAudio.pause(); return;
    }
    if (this._currentAudio) { this._currentAudio.pause(); this._restoreIcon(); }
    const a = new Audio(url); this._currentAudio = a; this._currentIconId = iconId;
    // Show pause icon
    icon.innerHTML = '<svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
    a.play().catch(e => { if (e.name !== 'AbortError') Components.showToast('播放失败', 'error'); this._restoreIcon(); });
    a.addEventListener('ended', () => this._restoreIcon());
    a.addEventListener('pause', () => this._restoreIcon());
  },
  _restoreIcon() {
    if (this._currentIconId) {
      const i = document.getElementById(this._currentIconId);
      if (i) i.innerHTML = '<svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor"><polygon points="5,3 19,12 5,21"/></svg>';
      this._currentIconId = null;
    }
  },

  downloadFile(url, name) { const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); document.body.removeChild(a); },

  _esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); },

  // === Voice Selection Modal ===
  _voiceCallback: null,
  async _showVoicePicker(callback) {
    this._voiceCallback = callback;
    await this._renderVoicePickerContent();
    document.getElementById('voice-pick-modal').classList.remove('hidden');
  },
  async _renderVoicePickerContent() {
    try {
      const voices = await API.getVoices();
      let html = '<h2>选择音色</h2>';
      // Upload row
      html += '<div style="display:flex;gap:6px;margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid var(--border)">';
      html += '<input id="vp-voice-name" placeholder="音色名称" style="flex:1;font-size:12px;padding:6px 10px">';
      html += '<input id="vp-voice-file" type="file" accept="audio/*" style="display:none" onchange="Components._uploadVoiceFromPicker()">';
      html += '<button class="btn-sm primary" onclick="document.getElementById(\'vp-voice-file\').click()">上传</button>';
      html += '</div>';
      // Voice list
      if (!voices.length) {
        html += '<p style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px">暂无音色，请上传</p>';
      } else {
        html += '<div style="max-height:260px;overflow-y:auto">';
        voices.forEach(v => {
          var sp = (v.audio_path || '').replace(/\\/g, '/');
          html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border:1px solid var(--border);border-radius:6px;margin-bottom:6px;cursor:pointer" data-vpath="' + sp + '" data-vid="' + v.id + '" onclick="Components._pickVoice(this.dataset.vpath,this.dataset.vid)">';
          html += '<div><strong style="font-size:13px">' + this._esc(v.name) + '</strong></div>';
          html += '</div>';
        });
      }
      html += '<div class="modal-actions"><button class="btn-secondary" onclick="Components._closeVoicePicker()">取消</button></div>';
      document.getElementById('voice-pick-modal').querySelector('.modal-panel').innerHTML = html;
      document.getElementById('voice-pick-modal').querySelector('.modal-panel').style.width = '480px';
    } catch (e) { Components.showToast('加载音色失败', 'error'); }
  },
  async _uploadVoiceFromPicker() {
    const file = document.getElementById('vp-voice-file')?.files?.[0];
    if (!file) return;
    const name = document.getElementById('vp-voice-name')?.value?.trim() || file.name.replace(/\.[^.]+$/,'');
    try {
      await API.uploadVoice(name, file);
      Components.showToast('上传成功', 'success');
      await this._renderVoicePickerContent();
    } catch (e) { Components.showToast('上传失败: ' + e.message, 'error'); }
  },
  _pickVoice(audioPath, voiceId) {
    document.getElementById('voice-pick-modal').classList.add('hidden');
    if (this._voiceCallback) { const cb = this._voiceCallback; this._voiceCallback = null; cb(audioPath, voiceId); }
  },
  _closeVoicePicker() {
    document.getElementById('voice-pick-modal').classList.add('hidden');
    this._voiceCallback = null;
  },
};

// Global click to close emo dropdowns
document.addEventListener('click', (e) => {
  if (!e.target.closest('.emo-panel')) {
    document.querySelectorAll('.emo-dropdown.open').forEach(d => d.classList.remove('open'));
    Components._emoOpen = null;
  }
});
