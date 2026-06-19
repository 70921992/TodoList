// C/D 阶段：同步状态条（4 态轮询 + UI 更新）
// 依赖：window.syncApi / window.networkApi (D 阶段)

(function() {
    'use strict';

    class SyncStatusManager {
        constructor() {
            this.status = { groupCount: 0, onlineCount: 0, connectedPeers: [] };
            this.peers = [];   // D 阶段：远端节点详情列表
            this.events = [];  // D 阶段：网络事件日志
            this.timer = null;
            this.intervalMs = 10000;
            this._listeners = new Set();
        }

        on(event, fn) {
            this._listeners.add(fn);
            return () => this._listeners.delete(fn);
        }

        _emit(event, data) {
            for (const fn of this._listeners) {
                try { fn(event, data); } catch (e) { /* 忽略单点错误 */ }
            }
        }

        async refresh() {
            try {
                const r = await window.syncApi.status();
                if (r && r.success) {
                    this.status = r.status || this.status;
                    this._updateUI();
                    this._emit('updated', this.status);
                }
            } catch (e) {
                // 静默失败
            }
            // D 阶段：拉取对端节点 + 事件
            try {
                if (window.networkApi && window.networkApi.listPeers) {
                    const pr = await window.networkApi.listPeers();
                    if (pr && pr.success) this.peers = pr.peers || [];
                }
                if (window.networkApi && window.networkApi.eventLog) {
                    const er = await window.networkApi.eventLog({ limit: 30 });
                    if (er && er.success) this.events = er.events || [];
                }
                this._emit('networkUpdated', { peers: this.peers, events: this.events });
            } catch (e) {
                // 静默失败
            }
            return this.status;
        }

        startPolling(intervalMs) {
            this.stopPolling();
            if (intervalMs) this.intervalMs = intervalMs;
            this.refresh(); // 立即拉一次
            this.timer = setInterval(() => this.refresh(), this.intervalMs);
        }

        stopPolling() {
            if (this.timer) {
                clearInterval(this.timer);
                this.timer = null;
            }
        }

        getStatusText() {
            const s = this.status;
            if (s.groupCount === 0) return '○ 未加入协作组';
            if (s.onlineCount === 0) return `⚠ 已加入 ${s.groupCount} 组（离线）`;
            if (s.onlineCount < s.groupCount) {
                return `⟳ ${s.onlineCount}/${s.groupCount} 组在线`;
            }
            return `● ${s.groupCount} 组已同步`;
        }

        getPeerBadge(status) {
            // 🟢 在线 / 🟡 同步中 / ⚫ 离线
            if (status === 'online') return '🟢';
            if (status === 'syncing') return '🟡';
            return '⚫';
        }

        getOnlinePeers() {
            return this.peers.filter(p => p.status === 'online');
        }

        getOfflinePeers() {
            return this.peers.filter(p => p.status === 'offline');
        }

        getRecentEvents(n = 10) {
            return (this.events || []).slice(0, n);
        }

        _updateUI() {
            const el = document.getElementById('sync-status-text');
            if (el) el.textContent = this.getStatusText();
        }
    }

    window.syncStatusManager = new SyncStatusManager();
})();
