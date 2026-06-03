/**
 * Canvas waveform renderer + Audio Editor singleton.
 */
class WaveformRenderer {
  constructor(canvas, peaks, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.peaks = peaks;
    this.color = options.color || '#2563EB';
    this.bgColor = options.bgColor || '#F1F5F9';
    this.duration = options.duration || 0;
    this._dpr = window.devicePixelRatio || 1;
    this._resize();
  }

  _resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.width = rect.width;
    this.height = rect.height;
    this.canvas.width = this.width * this._dpr;
    this.canvas.height = this.height * this._dpr;
    this.ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);
  }

  draw(highlightStart, highlightEnd) {
    this._resize();
    const { ctx, width, height, peaks } = this;
    const mid = height / 2;
    const n = peaks.length;
    ctx.fillStyle = this.bgColor;
    ctx.fillRect(0, 0, width, height);
    if (n === 0) return;
    const barW = width / n;
    for (let i = 0; i < n; i++) {
      const x = i * barW;
      const h = Math.max(1, peaks[i] * mid * 0.85);
      const inHL = (highlightStart == null) ? true : (x >= highlightStart && x <= highlightEnd);
      ctx.fillStyle = inHL ? this.color : '#CBD5E1';
      ctx.fillRect(x, mid - h, Math.max(1, barW - 0.5), h * 2);
    }
  }

  xToTime(x) { return (x / this.width) * this.duration; }
  timeToX(t) { return (t / this.duration) * this.width; }
}


const AudioEditor = {
  _seg: null, _splitR: null, _trimR: null,
  _splitPks: [], _splitDur: 0,
  _ctxPks: [], _ctxDur: 0, _ctxSegS: 0, _ctxSegE: 0,
  _splitAt: null, _trimS: null, _trimE: null,
  _audio: null, _stopTmr: null, _origS: 0, _origE: 0, _text: '',

  async open(segId) {
    // segId can be a segment ID string or a full segment object (from dblclick)
    const sid = typeof segId === 'string' ? segId : segId.id;
    try {
      const seg = await API.getSegment(sid);
      if (!seg) return Components.showToast('片段不存在', 'error');
      await this._init(seg);
    } catch (e) { Components.showToast('加载失败: ' + e.message, 'error'); }
  },

  async openInsert(projectId, prevId, nextId) {
    try {
      let startT = 0, endT = 0;
      if (prevId) {
        const prev = await API.getSegment(prevId);
        if (prev) startT = prev.end_time;
      }
      if (nextId) {
        const next = await API.getSegment(nextId);
        if (next) endT = next.start_time;
      }
      // Only extend window when inserting after the last segment (no next)
      if (!nextId && prevId && endT <= startT) {
        endT = startT + 5;
      }
      // Validate real gap — must have room between segments
      if (endT - startT < 0.1) {
        return Components.showToast('目标位置没有足够的空隙可插入新段（段间距需 >= 0.1秒）', 'error');
      }

      const dur = endT - startT;
      let peaks = [];
      try {
        const rawData = await API.get(`/api/projects/${projectId}/waveform?start=${startT}&end=${endT}`);
        peaks = rawData.peaks || [];
      } catch (_) {}

      // Hide split panel (not needed for insert)
      document.getElementById('ae-split-wrap').style.display = 'none';
      document.getElementById('ae-split-sub').style.display = 'none';
      document.getElementById('ae-split-info').style.display = 'none';
      document.getElementById('ae-split-play-btn').style.display = 'none';
      document.getElementById('ae-split-btn').style.display = 'none';
      document.getElementById('ae-cursor').style.display = 'none';

      document.getElementById('audio-editor-modal').classList.remove('hidden');
      document.getElementById('audio-editor-title').textContent = '插入新段';
      this._seg = { id: null, start_time: startT, end_time: endT, speaker: 'NEW', original_text: '', edited_text: '', project_id: projectId };
      this._insertPrevId = prevId || null;
      this._insertNextId = nextId || null;
      this._splitAt = null; this._trimS = null; this._trimE = null;
      this._stopAudio();
      this._text = '';
      this._origS = startT; this._origE = endT;

      // Show trim panel for selecting exact range
      document.getElementById('ae-trim-wrap').style.display = '';
      document.getElementById('ae-trim-sub').style.display = '';
      document.getElementById('ae-trim-info').style.display = '';
      document.getElementById('ae-trim-play-btn').style.display = '';
      document.getElementById('ae-trim-apply').style.display = '';
      document.getElementById('ae-trim-apply').textContent = '确认插入';
      document.getElementById('ae-trim-apply').disabled = false;
      document.getElementById('ae-trim-apply').onclick = () => this._applyInsert(projectId);
      document.getElementById('ae-trim-info').textContent =
        `选中范围: ${startT.toFixed(1)}s – ${endT.toFixed(1)}s (拖动把手调整)`;
      document.getElementById('ae-trim-play-btn').disabled = false;

      this._ctxPks = peaks;
      this._ctxDur = dur;
      this._ctxSegS = 0;
      this._ctxSegE = dur;
      this._renderTrim();
      this._bindTrim();
    } catch (e) {
      Components.showToast('加载波形失败: ' + (e.message || '未知错误'), 'error');
    }
  },

  async _applyInsert(projectId) {
    try {
      // Auto-detect speaker from adjacent segments
      let speaker = 'A';
      const prevId = this._insertPrevId;
      const nextId = this._insertNextId;
      if (prevId) {
        const segs = App._segments || [];
        const prev = segs.find(s => s.id === prevId);
        if (prev && prev.speaker) speaker = prev.speaker;
      }
      if (!speaker && nextId) {
        const segs = App._segments || [];
        const next = segs.find(s => s.id === nextId);
        if (next && next.speaker) speaker = next.speaker;
      }
      const absS = this._trimAbsS != null ? this._trimAbsS : this._origS;
      const absE = this._trimAbsE != null ? this._trimAbsE : this._origE;
      if (absE - absS < 0.1) {
        return Components.showToast('选中范围太短（需 >= 0.1秒）', 'error');
      }
      await API.insertSegment({
        project_id: projectId,
        start_time: absS,
        end_time: absE,
        speaker: speaker,
      });
      Components.showToast('插入完成', 'success');
      this.close();
      App.refreshWorkspace();
    } catch (e) {
      Components.showToast('插入失败: ' + (e.message || '未知错误'), 'error');
    }
  },

  async _init(seg) {
    this._seg = seg;
    this._splitAt = null; this._trimS = null; this._trimE = null;
    this._stopAudio();
    this._text = seg.edited_text || seg.original_text || '';

    document.getElementById('audio-editor-modal').classList.remove('hidden');
    document.getElementById('audio-editor-title').textContent =
      `音频编辑 · 说话人 ${seg.speaker} · ${seg.start_time?.toFixed(1)||0}s – ${seg.end_time?.toFixed(1)||0}s`;
    document.getElementById('ae-split-play-btn').disabled = true;
    document.getElementById('ae-trim-play-btn').disabled = true;
    document.getElementById('ae-split-info').textContent = '鼠标移动到波形上设定切割位置';
    document.getElementById('ae-cursor').style.display = 'none';
    // Restore panels hidden in insert mode
    document.getElementById('ae-split-wrap').style.display = '';
    document.getElementById('ae-split-sub').style.display = '';
    document.getElementById('ae-split-info').style.display = '';
    document.getElementById('ae-split-play-btn').style.display = '';
    const splitBtn = document.getElementById('ae-split-btn');
    splitBtn.style.display = '';
    splitBtn.textContent = '确认切割';
    splitBtn.disabled = true;
    splitBtn.onclick = () => this.confirmSplit();
    document.getElementById('ae-trim-wrap').style.display = '';
    document.getElementById('ae-trim-sub').style.display = '';
    document.getElementById('ae-trim-info').style.display = '';
    document.querySelectorAll('#ae-trim-play-btn, #ae-trim-apply').forEach(b => { b.style.display = ''; b.textContent = b.id === 'ae-trim-apply' ? '确认修剪' : b.textContent; });
    const trimApply = document.getElementById('ae-trim-apply');
    trimApply.onclick = () => this.applyTrim();
    trimApply.disabled = true;

    this._origS = seg.start_time || 0;
    this._origE = seg.end_time || 0;

    try {
      // Calculate context from adjacent segments
      let ctxBefore = 5, ctxAfter = 5;
      if (seg.project_id) {
        try {
          const allSegs = await API.getSegments(seg.project_id);
          const idx = allSegs.findIndex(s => s.id === seg.id);
          if (idx > 0) ctxBefore = seg.start_time - allSegs[idx - 1].end_time;
          if (idx >= 0 && idx < allSegs.length - 1) ctxAfter = allSegs[idx + 1].start_time - seg.end_time;
        } catch (_) {}
      }
      const data = await API.segWaveform(seg.id, ctxBefore, ctxAfter);
      this._splitPks = data.segment_peaks || data.peaks || [];
      this._splitDur = data.duration || (this._origE - this._origS);

      this._ctxPks = data.context_peaks || this._splitPks;
      this._ctxDur = data.context_total_duration || this._splitDur;
      this._ctxSegS = data.segment_start_in_context || 0;
      this._ctxSegE = data.segment_end_in_context || this._splitDur;

      this._renderSplit();
      this._renderTrim();
      this._bindSplit();
      this._bindTrim();
    } catch (e) {
      Components.showToast('加载波形失败: ' + e.message, 'error');
    }
  },

  close() {
    document.getElementById('audio-editor-modal').classList.add('hidden');
    this._stopAudio();
    this._seg = null;
    // Restore panels for next use
    document.getElementById('ae-split-wrap').style.display = '';
    document.getElementById('ae-split-sub').style.display = '';
    document.getElementById('ae-split-info').style.display = '';
    document.getElementById('ae-split-play-btn').style.display = '';
    const sb = document.getElementById('ae-split-btn');
    sb.style.display = '';
    sb.textContent = '确认切割';
    sb.onclick = () => this.confirmSplit();
    sb.disabled = true;
    document.getElementById('ae-trim-wrap').style.display = '';
    document.getElementById('ae-trim-sub').style.display = '';
    document.getElementById('ae-trim-info').style.display = '';
    document.querySelectorAll('#ae-trim-play-btn, #ae-trim-apply').forEach(b => b.style.display = '');
    const ta = document.getElementById('ae-trim-apply');
    ta.textContent = '确认修剪';
    ta.onclick = () => this.applyTrim();
    ta.disabled = true;
  },

  _stopAudio() { if (this._audio) { this._audio.pause(); this._audio = null; } if (this._stopTmr) { clearInterval(this._stopTmr); this._stopTmr = null; } },

  _escHtml(s) { const d = document.createElement('div'); d.textContent = s||''; return d.innerHTML; },

  // ===== Split =====
  _renderSplit() {
    const cv = document.getElementById('ae-split-canvas');
    this._splitR = new WaveformRenderer(cv, this._splitPks, { duration: this._splitDur });
    this._splitR.draw();
    this._renderSplitSub(null);
    document.getElementById('ae-split-info').textContent = '鼠标移动到波形上设定切割位置';
  },

  _renderSplitSub(at) {
    const el = document.getElementById('ae-split-sub');
    if (!el) return;
    const t = this._text || '(无台词)';
    if (at == null || this._splitDur <= 0) { el.innerHTML = this._escHtml(t); return; }
    const r = Math.max(0, Math.min(1, at / this._splitDur));
    const pos = Math.round(t.length * r);
    el.innerHTML = `<span style="color:#94A3B8">${this._escHtml(t.slice(0,pos))}</span><span style="display:inline-block;width:2px;height:14px;background:#DC2626;vertical-align:middle;margin:0 1px"></span>${this._escHtml(t.slice(pos))}`;
  },

  _bindSplit() {
    const wrap = document.getElementById('ae-split-wrap');
    const cursor = document.getElementById('ae-cursor');
    const info = document.getElementById('ae-split-info');
    const sBtn = document.getElementById('ae-split-btn');
    const pBtn = document.getElementById('ae-split-play-btn');
    const self = this;

    wrap.onmousemove = (e) => {
      if (!self._splitR) return;
      const r = wrap.getBoundingClientRect();
      const x = e.clientX - r.left;
      const t = self._splitR.xToTime(x);
      if (t < 0.05 || t > self._splitDur - 0.05) { cursor.style.display = 'none'; return; }
      cursor.style.display = 'block'; cursor.style.left = x + 'px';
      info.textContent = '切割点: ' + t.toFixed(2) + 's';
      if (self._splitAt == null) self._renderSplitSub(t);
    };
    wrap.onmouseleave = () => { cursor.style.display = 'none'; if (self._splitAt == null) self._renderSplitSub(null); };
    wrap.onclick = (e) => {
      if (!self._splitR) return;
      const r = wrap.getBoundingClientRect();
      const x = e.clientX - r.left;
      const t = self._splitR.xToTime(x);
      if (t < 0.1 || t > self._splitDur - 0.1) return;
      self._splitAt = t;
      info.textContent = '切割点: ' + t.toFixed(2) + 's (已设定)';
      sBtn.disabled = false; pBtn.disabled = false;
      self._renderSplitSub(t);
      self._splitR.draw();
      const c = self._splitR.ctx;
      const dpr = window.devicePixelRatio || 1;
      c.strokeStyle = '#DC2626'; c.lineWidth = 2; c.setLineDash([4,4]);
      c.beginPath(); c.moveTo(x*dpr, 0); c.lineTo(x*dpr, self._splitR.height*dpr); c.stroke(); c.setLineDash([]);
    };
  },

  async confirmSplit() {
    if (this._splitAt == null || !this._seg) return;
    const sid = this._seg.id;
    if (!sid) return Components.showToast('当前模式不支持切割', 'error');
    try {
      await API.splitSegment(sid, { split_at: this._splitAt });
      Components.showToast('切割完成', 'success');
      this.close();
      App.refreshWorkspace();
    } catch (e) { Components.showToast('切割失败: ' + e.message, 'error'); }
  },

  playSplitFromCursor() { if (this._splitAt != null) this._playFrom(this._splitAt); },

  // ===== Trim =====
  _renderTrim() {
    const cv = document.getElementById('ae-trim-canvas');
    this._trimR = new WaveformRenderer(cv, this._ctxPks, { duration: this._ctxDur });
    const sx = this._trimR.timeToX(this._ctxSegS);
    const ex = this._trimR.timeToX(this._ctxSegE);
    this._trimS = sx; this._trimE = ex;
    this._trimR.draw(sx, ex);
    this._updateTrimOverlay(sx, ex);
    this._updateTrimInfo();
    this._renderTrimSub();
  },

  _renderTrimSub() {
    const el = document.getElementById('ae-trim-sub');
    if (!el || !this._trimR) return;
    const t = this._text || '(无台词)';
    const cs = this._trimR.xToTime(this._trimS);
    const ce = this._trimR.xToTime(this._trimE);
    const len = t.length; if (!len) { el.textContent = t; return; }
    const l = Math.max(0, Math.round((cs / this._ctxDur) * len));
    const r = Math.min(len, Math.round((ce / this._ctxDur) * len));
    el.innerHTML = `<span style="color:#94A3B8">${this._escHtml(t.slice(0,l))}</span><span style="font-weight:600;color:#2563EB">${this._escHtml(t.slice(l,r))}</span><span style="color:#94A3B8">${this._escHtml(t.slice(r))}</span>`;
  },

  _updateTrimOverlay(sx, ex) {
    const wrap = document.getElementById('ae-trim-wrap');
    wrap.querySelectorAll('.ae-trim-ghost,.ae-trim-region,.ae-trim-handle').forEach(el => el.remove());
    if (sx > 0) { const g = document.createElement('div'); g.className = 'ae-trim-ghost'; g.style.left = '0'; g.style.width = sx + 'px'; wrap.appendChild(g); }
    const ww = wrap.getBoundingClientRect().width;
    if (ex < ww) { const g = document.createElement('div'); g.className = 'ae-trim-ghost'; g.style.left = ex + 'px'; g.style.right = '0'; wrap.appendChild(g); }
    const rg = document.createElement('div'); rg.className = 'ae-trim-region'; rg.style.left = sx + 'px'; rg.style.width = (ex - sx) + 'px'; wrap.appendChild(rg);
    const h1 = document.createElement('div'); h1.className = 'ae-trim-handle start'; h1.style.left = (sx - 6) + 'px'; h1.dataset.handle = 'start'; wrap.appendChild(h1);
    const h2 = document.createElement('div'); h2.className = 'ae-trim-handle end'; h2.style.left = (ex - 6) + 'px'; h2.dataset.handle = 'end'; wrap.appendChild(h2);
  },

  _bindTrim() {
    const wrap = document.getElementById('ae-trim-wrap');
    const self = this;
    let drag = null;

    wrap.addEventListener('mousedown', (e) => {
      const h = e.target.closest('.ae-trim-handle');
      if (h) { drag = h.dataset.handle; e.preventDefault(); }
    });
    document.addEventListener('mousemove', (e) => {
      if (!drag || !self._trimR) return;
      const r = wrap.getBoundingClientRect();
      const x = Math.max(0, Math.min(r.width, e.clientX - r.left));
      if (drag === 'start') self._trimS = Math.min(x, self._trimE - 5);
      else self._trimE = Math.max(x, self._trimS + 5);
      self._trimR.draw(self._trimS, self._trimE);
      self._updateTrimOverlay(self._trimS, self._trimE);
      self._updateTrimInfo();
      self._renderTrimSub();
    });
    document.addEventListener('mouseup', () => {
      if (drag) { drag = null; document.getElementById('ae-trim-apply').disabled = false; document.getElementById('ae-trim-play-btn').disabled = false; }
    });
  },

  _updateTrimInfo() {
    if (!this._trimR) return;
    const t0 = this._trimR.xToTime(this._trimS);
    const t1 = this._trimR.xToTime(this._trimE);
    const absS = this._origS + (t0 - this._ctxSegS);
    const absE = this._origE + (t1 - this._ctxSegE);
    document.getElementById('ae-trim-info').textContent = `新范围: ${absS.toFixed(1)}s – ${absE.toFixed(1)}s (原: ${this._origS.toFixed(1)}–${this._origE.toFixed(1)}s)`;
    this._trimAbsS = absS; this._trimAbsE = absE;
  },

  async applyTrim() {
    if (!this._seg || this._trimAbsS == null) return;
    try {
      await API.trimSegment(this._seg.id, { start_time: this._trimAbsS, end_time: this._trimAbsE });
      Components.showToast('修剪完成', 'success');
      this.close();
      App.refreshWorkspace();
    } catch (e) { Components.showToast('修剪失败: ' + e.message, 'error'); }
  },

  // ===== Playback =====
  _playFrom(offset, stop) {
    if (!this._seg) return;
    this._stopAudio();
    let url;
    if (this._seg.id) {
      url = API.audioUrl(this._seg.id);
    } else if (this._seg.project_id) {
      // Insert mode: use raw project audio, offset by gap start time
      url = API.rawAudioUrl(this._seg.project_id);
      offset += (this._origS || 0);
      if (stop != null) stop += (this._origS || 0);
    } else {
      return;
    }
    this._audio = new Audio(url);
    this._audio.currentTime = Math.max(0, offset);
    if (stop != null && stop > offset) {
      this._stopTmr = setInterval(() => { if (this._audio && this._audio.currentTime >= stop) { this._audio.pause(); clearInterval(this._stopTmr); } }, 50);
    }
    this._audio.onended = () => { this._stopAudio(); };
    this._audio.play().catch(() => {});
  },

  playTrimPreview() {
    if (!this._trimR) return;
    const s = this._trimR.xToTime(this._trimS);
    const e = this._trimR.xToTime(this._trimE);
    this._playFrom(s, e);
  },
};
