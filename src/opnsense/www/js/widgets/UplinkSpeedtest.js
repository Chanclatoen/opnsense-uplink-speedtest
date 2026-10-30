/*
 * Copyright (c) 2026 Uplink IT. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).
 */

export default class UplinkSpeedtest extends BaseWidget {
    constructor(config) {
        super(config);
        this.tickTimeout = 60; // scheduled tests run a few times a day, the file barely changes
        this.chart = null;
        this.fields = ['download', 'upload', 'ping', 'jitter'];
    }

    getGridOptions() {
        return {
            minW: 2,
            minH: 3,
        };
    }

    /* the dashboard re-creates this markup from its outerHTML, so address elements by id
       afterwards and never bind handlers here */
    getMarkup() {
        const tiles = this.fields.map((field) => `
            <div style="box-sizing: border-box; flex: 1 1 50%; padding: 4px 6px; min-width: 85px;">
                <div id="${this.id}-${field}" style="font-size: 20px; font-weight: 600; line-height: 1.1;">-</div>
                <div style="font-size: 10px; text-transform: uppercase; opacity: 0.7;">
                    ${this.translations[field] ?? field}
                </div>
            </div>
        `).join('');

        return $(`
            <div>
                <div id="${this.id}-empty" style="display: none; padding: 10px;"></div>
                <div id="${this.id}-body" style="display: none;">
                    <div style="display: flex; flex-wrap: wrap;">${tiles}</div>
                    <div style="height: 70px; padding: 0 6px;">
                        <canvas id="${this.id}-spark"></canvas>
                    </div>
                    <div id="${this.id}-footer" style="font-size: 11px; opacity: 0.7; padding: 4px 6px;"></div>
                </div>
            </div>
        `);
    }

    async onWidgetTick() {
        const data = await this.ajaxCall('/api/uplink_speedtest/service/history', {limit: 20});
        const rows = (data && data.rows) ? data.rows : [];

        if (rows.length === 0) {
            $(`#${this.id}-body`).hide();
            $(`#${this.id}-empty`)
                .empty()
                .append($('<a/>', {href: '/ui/uplink_speedtest', text: this.translations.noresults}))
                .show();
            return;
        }

        $(`#${this.id}-empty`).hide();
        $(`#${this.id}-body`).show();

        const latest = rows[0];
        $(`#${this.id}-download`).text(this._mbit(latest.download));
        $(`#${this.id}-upload`).text(this._mbit(latest.upload));
        $(`#${this.id}-ping`).text(this._ms(latest.ping));
        $(`#${this.id}-jitter`).text(this._ms(latest.jitter));

        const server = [latest.server_sponsor, latest.server_name].filter(Boolean).join(' - ');
        $(`#${this.id}-footer`).text(this._when(latest.timestamp) + (server ? ' · ' + server : ''));

        this._drawSparkline(rows);
    }

    onWidgetClose() {
        if (this.chart !== null) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    _mbit(bits) {
        return (bits === null || bits === undefined) ? '-' : (bits / 1000000).toFixed(0);
    }

    _ms(value) {
        return (value === null || value === undefined) ? '-' : Number(value).toFixed(1);
    }

    _when(stamp) {
        const parsed = new Date(stamp);
        return isNaN(parsed) ? String(stamp) : parsed.toLocaleString();
    }

    /* last ~20 tests, oldest first; no axes on purpose, the numbers above carry the values */
    _drawSparkline(rows) {
        const canvas = document.getElementById(`${this.id}-spark`);
        if (canvas === null) {
            return;
        }
        const points = rows.slice().reverse();
        const labels = points.map((row) => this._when(row.timestamp));
        const download = points.map((row) => row.download / 1000000);
        const upload = points.map((row) => row.upload / 1000000);

        if (this.chart !== null) {
            this.chart.data.labels = labels;
            this.chart.data.datasets[0].data = download;
            this.chart.data.datasets[1].data = upload;
            this.chart.update();
            return;
        }

        const palette = (window.Chart && Chart.colorschemes)
            ? Chart.colorschemes.tableau.Classic10 : ['#4E79A7', '#F28E2B'];
        const dataset = (label, data, color) => ({
            label: label,
            data: data,
            borderColor: color,
            backgroundColor: this._setAlpha(color, 0.2),
            borderWidth: 1.5,
            pointRadius: 0,
            fill: true,
            tension: 0.3,
        });

        this.chart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    dataset(this.translations.download, download, palette[0]),
                    dataset(this.translations.upload, upload, palette[1]),
                ],
            },
            options: {
                maintainAspectRatio: false,
                animation: false,
                scales: {
                    x: {display: false},
                    y: {display: false, beginAtZero: true},
                },
                plugins: {legend: {display: false}},
            },
        });
    }
}
