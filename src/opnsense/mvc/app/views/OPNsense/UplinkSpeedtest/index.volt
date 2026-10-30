{#
 # Copyright (c) 2026 Uplink IT. All rights reserved.
 # SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).
 #}

<script src="{{ cache_safe('/ui/js/chart.umd.min.js') }}"></script>

<style>
    .speedtest-tile { text-align: center; padding: 10px 5px; }
    .speedtest-tile .speedtest-value { font-size: 26px; font-weight: 600; line-height: 1.1; }
    .speedtest-tile .speedtest-label { text-transform: uppercase; font-size: 11px; opacity: 0.7; }
    .speedtest-tile .speedtest-range { font-size: 11px; opacity: 0.7; }
    #speedtest-chart-holder { height: 260px; }
</style>

<script>
    $(document).ready(function () {
        const HISTORY_ROWS = 50;
        const PROVIDERS = {'cloudflare': 'Cloudflare', 'ookla': 'Ookla', 'iperf3': 'iperf3'};
        let chart = null;
        let pollUntil = 0;

        function providerName(key) {
            return PROVIDERS[key] || key || '-';
        }

        /* '' means every provider, which is why the chart defaults to one */
        function filtered() {
            return $('#speedtest-provider-filter').val() || '';
        }

        function mbit(bits) {
            return (bits === null || bits === undefined) ? '-' : (bits / 1000000).toFixed(1);
        }

        function ms(value) {
            return (value === null || value === undefined) ? '-' : Number(value).toFixed(1);
        }

        function localTime(stamp) {
            if (!stamp) {
                return '-';
            }
            const parsed = new Date(stamp);
            return isNaN(parsed) ? stamp : parsed.toLocaleString();
        }

        function serverOf(row) {
            return [row.server_sponsor, row.server_name, row.server_country].filter(Boolean).join(' - ');
        }

        function tile(id, value, stat, unit, format) {
            $('#speedtest-' + id + ' .speedtest-value').text(value);
            $('#speedtest-' + id + ' .speedtest-range').text(
                stat === null ? '' : 'min ' + format(stat.min) + ' / avg ' + format(stat.avg) + ' / max ' + format(stat.max) + ' ' + unit
            );
        }

        function drawChart(rows) {
            const points = rows.slice().reverse();
            const labels = points.map(function (row) { return localTime(row.timestamp); });
            const datasets = [
                {label: '{{ lang._("Download (Mbit/s)") }}', data: points.map(function (r) { return r.download / 1000000; })},
                {label: '{{ lang._("Upload (Mbit/s)") }}', data: points.map(function (r) { return r.upload / 1000000; })}
            ];
            const palette = (window.Chart && Chart.colorschemes) ? Chart.colorschemes.tableau.Classic10 : ['#1f77b4', '#ff7f0e'];
            datasets.forEach(function (set, index) {
                set.borderColor = palette[index];
                set.backgroundColor = palette[index];
                set.tension = 0.3;
                set.pointRadius = 2;
            });
            if (chart !== null) {
                chart.data.labels = labels;
                chart.data.datasets.forEach(function (set, index) { set.data = datasets[index].data; });
                chart.update();
                return;
            }
            chart = new Chart($('#speedtest-chart')[0].getContext('2d'), {
                type: 'line',
                data: {labels: labels, datasets: datasets},
                options: {
                    maintainAspectRatio: false,
                    scales: {y: {beginAtZero: true, title: {display: true, text: 'Mbit/s'}}},
                    plugins: {legend: {position: 'bottom'}}
                }
            });
        }

        function drawTable(rows) {
            const $body = $('#speedtest-history-body').empty();
            rows.forEach(function (row) {
                $body.append($('<tr/>').append(
                    $('<td/>').text(localTime(row.timestamp)),
                    $('<td/>').text(providerName(row.provider)),
                    $('<td/>').text(mbit(row.download)),
                    $('<td/>').text(mbit(row.upload)),
                    $('<td/>').text(ms(row.ping)),
                    $('<td/>').text(ms(row.jitter)),
                    $('<td/>').text(serverOf(row) + (row.server_id ? ' (' + row.server_id + ')' : ''))
                ));
            });
        }

        function refresh() {
            return ajaxGet('/api/uplink_speedtest/service/history', {'limit': HISTORY_ROWS, 'provider': filtered()}, function (data) {
                const rows = (data && data.rows) ? data.rows : [];
                $('#speedtest-total').text(data && data.total ? data.total : 0);
                if (rows.length === 0) {
                    $('#speedtest-empty').show();
                    $('#speedtest-results').hide();
                    return;
                }
                $('#speedtest-empty').hide();
                $('#speedtest-results').show();
                const latest = rows[0];
                const stats = data.stats || {};
                tile('download', mbit(latest.download), stats.download || null, 'Mbit/s', mbit);
                tile('upload', mbit(latest.upload), stats.upload || null, 'Mbit/s', mbit);
                tile('ping', ms(latest.ping), stats.ping || null, 'ms', ms);
                tile('jitter', ms(latest.jitter), stats.jitter || null, 'ms', ms);
                $('#speedtest-when').text(localTime(latest.timestamp));
                $('#speedtest-provider').text(providerName(latest.provider));
                $('#speedtest-server').text(
                    serverOf(latest) + (latest.server_id ? ' (id ' + latest.server_id + ')' : '')
                );
                drawChart(rows);
                drawTable(rows);
            });
        }

        function setBusy(busy, message) {
            $('#speedtest-run, #speedtest-run-with').prop('disabled', busy);
            $('#speedtest-run-spinner').toggleClass('fa-spin', busy).toggle(busy);
            $('#speedtest-run-message').text(message || '');
        }

        function poll() {
            ajaxGet('/api/uplink_speedtest/service/status', {}, function (state) {
                if (state && state.running && Date.now() < pollUntil) {
                    setTimeout(poll, 3000);
                    return;
                }
                refresh();
                if (state && state.last_status === 'failed') {
                    setBusy(false, '{{ lang._("Last run failed:") }} ' + (state.last_message || ''));
                    return;
                }
                if (state && state.running) {
                    setBusy(false, '{{ lang._("Still running, the page will catch up on the next refresh.") }}');
                    return;
                }
                setBusy(false, '');
            });
        }

        /* empty provider = whatever the settings say, which is also what cron uses */
        function start(provider) {
            setBusy(true, '{{ lang._("Measuring with") }} ' + (provider ? providerName(provider) : '{{ lang._("the default provider") }}') + '{{ lang._(", this takes up to a minute...") }}');
            ajaxCall('/api/uplink_speedtest/service/run', {'provider': provider}, function (data) {
                if (!data || data.status !== 'started') {
                    setBusy(false, (data && data.message) ? data.message : '{{ lang._("Could not start the test.") }}');
                    return;
                }
                if (data.provider) {
                    $('#speedtest-provider-filter').val(data.provider);
                }
                pollUntil = Date.now() + 300000;
                setTimeout(poll, 5000);
            });
        }

        $('#speedtest-run').click(function () {
            start('');
        });

        $('.speedtest-run-provider').click(function (event) {
            event.preventDefault();
            start($(this).data('provider'));
        });

        $('#speedtest-provider-filter').change(function () {
            refresh();
        });

        $('#speedtest-servers-load').click(function () {
            const $button = $(this).prop('disabled', true);
            $('#speedtest-servers-message').text('{{ lang._("Fetching the server list...") }}');
            ajaxGet('/api/uplink_speedtest/service/servers', {}, function (data) {
                $button.prop('disabled', false);
                if (!data || data.status !== 'ok') {
                    $('#speedtest-servers-message').text((data && data.message) ? data.message : '{{ lang._("Could not fetch the server list.") }}');
                    return;
                }
                $('#speedtest-servers-message').text('');
                const $body = $('#speedtest-servers-body').empty();
                data.rows.forEach(function (row) {
                    const $use = $('<button type="button" class="btn btn-xs btn-default"/>')
                        .text('{{ lang._("Use") }}')
                        .click(function () {
                            $('#general\\.server').val(row.id);
                            $('#speedtest-servers-message').text('{{ lang._("Server filled in below, press Save to keep it.") }}');
                        });
                    $body.append($('<tr/>').append(
                        $('<td/>').text(row.id),
                        $('<td/>').text(row.sponsor),
                        $('<td/>').text([row.name, row.country].filter(Boolean).join(', ')),
                        $('<td/>').text(row.distance + ' km'),
                        $('<td/>').append($use)
                    ));
                });
                $('#speedtest-servers-table').show();
            });
        });

        $('#speedtest-save').click(function () {
            saveFormToEndpoint('/api/uplink_speedtest/settings/set', 'frm_general', function () {
                $('#speedtest-save-message').text('{{ lang._("Saved.") }}');
            }, true);
        });

        mapDataToFormUI({'frm_general': '/api/uplink_speedtest/settings/get'});

        /* start on the default provider so the chart compares like with like */
        ajaxGet('/api/uplink_speedtest/service/providers', {}, function (data) {
            if (data && data.default) {
                $('#speedtest-provider-filter').val(data.default);
            }
            refresh();
            poll();
        });
    });
</script>

<div class="content-box" style="padding-bottom: 1.5em;">
    <div class="col-md-12">
        <h2>{{ lang._('Uplink speedtest') }}</h2>
        <p id="speedtest-empty" style="display: none;">
            {{ lang._('No results for this provider yet. Press "Run now", pick another provider in the filter, or add the "Run uplink speedtest (Uplink)" job under System - Settings - Cron.') }}
        </p>
        <div id="speedtest-results" style="display: none;">
            <div class="row">
                <div class="col-xs-6 col-md-3 speedtest-tile" id="speedtest-download">
                    <div class="speedtest-value">-</div>
                    <div class="speedtest-label">{{ lang._('Download (Mbit/s)') }}</div>
                    <div class="speedtest-range"></div>
                </div>
                <div class="col-xs-6 col-md-3 speedtest-tile" id="speedtest-upload">
                    <div class="speedtest-value">-</div>
                    <div class="speedtest-label">{{ lang._('Upload (Mbit/s)') }}</div>
                    <div class="speedtest-range"></div>
                </div>
                <div class="col-xs-6 col-md-3 speedtest-tile" id="speedtest-ping">
                    <div class="speedtest-value">-</div>
                    <div class="speedtest-label">{{ lang._('Latency (ms)') }}</div>
                    <div class="speedtest-range"></div>
                </div>
                <div class="col-xs-6 col-md-3 speedtest-tile" id="speedtest-jitter">
                    <div class="speedtest-value">-</div>
                    <div class="speedtest-label">{{ lang._('Jitter (ms)') }}</div>
                    <div class="speedtest-range"></div>
                </div>
            </div>
            <p>
                <strong>{{ lang._('Last test') }}:</strong> <span id="speedtest-when">-</span>
                &nbsp;&nbsp;<strong>{{ lang._('Provider') }}:</strong> <span id="speedtest-provider">-</span>
                &nbsp;&nbsp;<strong>{{ lang._('Server') }}:</strong> <span id="speedtest-server">-</span>
                &nbsp;&nbsp;<strong>{{ lang._('Results shown') }}:</strong> <span id="speedtest-total">0</span>
            </p>
        </div>
        <div class="btn-group">
            <button class="btn btn-primary" id="speedtest-run" type="button">
                <i class="fa fa-tachometer"></i>&nbsp;{{ lang._('Run now') }}
                <i class="fa fa-spinner" id="speedtest-run-spinner" style="display: none;"></i>
            </button>
            <button class="btn btn-primary dropdown-toggle" id="speedtest-run-with" type="button" data-toggle="dropdown" aria-expanded="false">
                <span class="caret"></span>
                <span class="sr-only">{{ lang._('Run now with another provider') }}</span>
            </button>
            <ul class="dropdown-menu">
                <li><a href="#" class="speedtest-run-provider" data-provider="cloudflare">{{ lang._('Run now with Cloudflare') }}</a></li>
                <li><a href="#" class="speedtest-run-provider" data-provider="ookla">{{ lang._('Run now with Ookla') }}</a></li>
                <li><a href="#" class="speedtest-run-provider" data-provider="iperf3">{{ lang._('Run now with iperf3') }}</a></li>
            </ul>
        </div>
        <span id="speedtest-run-message" style="margin-left: 10px;"></span>
    </div>
</div>

<div class="content-box" style="padding-bottom: 1.5em;">
    <div class="col-md-12">
        <h2>{{ lang._('History') }}</h2>
        <div class="form-inline" style="margin-bottom: 10px;">
            <label for="speedtest-provider-filter">{{ lang._('Provider') }}</label>
            <select class="form-control" id="speedtest-provider-filter">
                <option value="cloudflare">Cloudflare</option>
                <option value="ookla">Ookla</option>
                <option value="iperf3">iperf3</option>
                <option value="">{{ lang._('All providers (not comparable)') }}</option>
            </select>
        </div>
        <div id="speedtest-chart-holder"><canvas id="speedtest-chart"></canvas></div>
        <div class="table-responsive">
            <table class="table table-striped table-condensed">
                <thead>
                    <tr>
                        <th>{{ lang._('Time') }}</th>
                        <th>{{ lang._('Provider') }}</th>
                        <th>{{ lang._('Download (Mbit/s)') }}</th>
                        <th>{{ lang._('Upload (Mbit/s)') }}</th>
                        <th>{{ lang._('Latency (ms)') }}</th>
                        <th>{{ lang._('Jitter (ms)') }}</th>
                        <th>{{ lang._('Server') }}</th>
                    </tr>
                </thead>
                <tbody id="speedtest-history-body"></tbody>
            </table>
        </div>
    </div>
</div>

<div class="content-box" style="padding-bottom: 1.5em;">
    <div class="col-md-12">
        <h2>{{ lang._('Settings') }}</h2>
        {{ partial("layout_partials/base_form", ['fields': generalForm, 'id': 'frm_general']) }}
        <button class="btn btn-primary" id="speedtest-save" type="button">{{ lang._('Save') }}</button>
        <span id="speedtest-save-message" style="margin-left: 10px;"></span>
        <hr/>
        <button class="btn btn-default" id="speedtest-servers-load" type="button">
            {{ lang._('Show nearest Ookla servers') }}
        </button>
        <span id="speedtest-servers-message" style="margin-left: 10px;"></span>
        <div class="table-responsive" id="speedtest-servers-table" style="display: none;">
            <table class="table table-striped table-condensed">
                <thead>
                    <tr>
                        <th>{{ lang._('ID') }}</th>
                        <th>{{ lang._('Sponsor') }}</th>
                        <th>{{ lang._('Location') }}</th>
                        <th>{{ lang._('Distance') }}</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody id="speedtest-servers-body"></tbody>
            </table>
        </div>
    </div>
</div>
