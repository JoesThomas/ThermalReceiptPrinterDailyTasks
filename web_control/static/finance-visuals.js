// Local SVG rendering only. Forecast calculations stay on the server.
(() => {
    const NS = 'http://www.w3.org/2000/svg';
    const money = new Intl.NumberFormat('en-GB', {
        style: 'currency',
        currency: 'GBP',
        maximumFractionDigits: 0
    });
    const shortDate = new Intl.DateTimeFormat('en-GB', {
        month: 'short',
        year: 'numeric',
        timeZone: 'UTC'
    });
    const fullDate = new Intl.DateTimeFormat('en-GB', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        timeZone: 'UTC'
    });

    function element(tag, attrs = {}, text = '') {
        const node = document.createElementNS(NS, tag);
        for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
        if (text) node.textContent = text;
        return node;
    }

    function numeric(point) {
        return Number(point.raw !== undefined ? point.raw : String(point.value).replace(/[^0-9.\-]/g, ''));
    }

    function nice(low, high) {
        const range = Math.max(.01, high - low),
            rough = range / 5,
            magnitude = 10 ** Math.floor(Math.log10(rough));
        const step = [1, 2, 2.5, 5, 10].map(n => n * magnitude).find(n => n >= rough) || magnitude * 10;
        return {
            low: Math.floor(low / step) * step,
            high: Math.ceil(high / step) * step,
            step
        };
    }

    function axisLabel(value) {
        const n = Math.abs(value);
        if (n >= 1e9) return (value < 0 ? '-' : '') + '£' + (n / 1e9).toLocaleString('en-GB', {
            maximumFractionDigits: 1
        }) + 'bn';
        if (n >= 1e6) return (value < 0 ? '-' : '') + '£' + (n / 1e6).toLocaleString('en-GB', {
            maximumFractionDigits: 1
        }) + 'm';
        return money.format(value);
    }
    document.querySelectorAll('[data-finance-line-chart]').forEach(panel => {
        const source = panel.querySelector('.chart-model'),
            svg = panel.querySelector('svg');
        if (!source || !svg) return;
        let root;
        try {
            root = JSON.parse(source.textContent);
        } catch (_) {
            return;
        }
        const mode = panel.querySelector('[data-chart-mode]'),
            period = panel.querySelector('[data-chart-period]'),
            legend = panel.querySelector('.chart-legend'),
            reading = panel.querySelector('.chart-reading');
        let selected = 0,
            hidden = new Set(),
            current = [],
            bounds = null,
            cursor = null,
            lastWidth = 0;
        svg.setAttribute('tabindex', '0');
        svg.setAttribute('aria-label', root.title + '. Use left and right arrow keys to inspect dates.');

        function model() {
            return mode && mode.value !== root.mode ? root.alt_model : root;
        }

        function announce(index) {
            const dates = [...new Set(current.filter(s => !hidden.has(s.name) && !s.reference).flatMap(s => s.data.map(p => p.date)))].sort();
            if (!dates.length) return;
            selected = Math.max(0, Math.min(dates.length - 1, index));
            const stamp = dates[selected];
            const text = [fullDate.format(new Date(stamp)), ...current.filter(s => !hidden.has(s.name)).map(s => {
                const point = s.data.find(p => p.date === stamp) || (s.reference ? s.data[0] : null);
                return point ? s.name + ': ' + point.value : null;
            }).filter(Boolean)].join(' · ');
            if (reading.textContent !== text) reading.textContent = text;
            if (cursor && bounds) {
                const x = bounds.x(Date.parse(stamp));
                cursor.setAttribute('x1', x);
                cursor.setAttribute('x2', x);
                cursor.style.display = '';
            }
        }

        function exactValues() {
            const details = panel.querySelector(':scope > details');
            if (!details) return;
            details.replaceChildren();
            const summary = document.createElement('summary');
            summary.textContent = 'Exact values for the displayed view';
            details.append(summary);
            for (const series of current) {
                const wrap = document.createElement('details'),
                    title = document.createElement('summary'),
                    region = document.createElement('div'),
                    table = document.createElement('table'),
                    caption = document.createElement('caption'),
                    head = document.createElement('thead'),
                    body = document.createElement('tbody');
                title.textContent = series.name;
                region.className = 'chart-data';
                region.tabIndex = 0;
                region.setAttribute('role', 'region');
                region.setAttribute('aria-label', root.title + ' · ' + series.name + ' exact values');
                caption.textContent = series.name + ' · GBP';
                const header = document.createElement('tr');
                for (const name of ['Date', 'Balance']) {
                    const th = document.createElement('th');
                    th.scope = 'col';
                    th.textContent = name;
                    header.append(th);
                }
                head.append(header);
                for (const point of series.data) {
                    const row = document.createElement('tr');
                    for (const value of [point.date, point.value]) {
                        const cell = document.createElement('td');
                        cell.textContent = value;
                        row.append(cell);
                    }
                    body.append(row);
                }
                table.append(caption, head, body);
                region.append(table);
                wrap.append(title, region);
                details.append(wrap);
            }
        }

        function draw(rebuild = true) {
            const data = model();
            if (!data) return;
            const width = Math.max(280, Math.round(svg.getBoundingClientRect().width) || 730),
                height = 280,
                left = 74,
                right = width - 18,
                top = 22,
                bottom = 230;
            lastWidth = width;
            svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
            svg.replaceChildren(element('title', {}, root.title));
            const start = Date.parse(data.start);
            let end = Date.parse(data.end);
            if (period && period.value !== 'all') {
                const first = new Date(start),
                    cutoff = Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + Number(period.value), 0);
                end = Math.min(end, cutoff);
            }
            current = data.series.map(s => ({
                ...s,
                reference: s.reference || Boolean(s.dash),
                data: s.reference || s.dash ? [{
                    ...s.data[0],
                    date: new Date(start).toISOString().slice(0, 10)
                }, {
                    ...s.data[s.data.length - 1],
                    date: new Date(end).toISOString().slice(0, 10)
                }] : s.data.filter(p => Date.parse(p.date) >= start && Date.parse(p.date) <= end)
            }));
            const visible = current.filter(s => !hidden.has(s.name)),
                numbers = visible.flatMap(s => s.data.map(numeric)).filter(Number.isFinite);
            if (!numbers.length) {
                numbers.push(...current.flatMap(s => s.data.map(numeric)).filter(Number.isFinite));
                reading.textContent = 'Select a line to view its values.';
            }
            const floor = data.band_value === null || data.band_value === undefined ? null : Number(data.band_value),
                axis = nice(Math.min(0, ...numbers, floor || 0), Math.max(1, ...numbers, floor || 0));
            if (axis.high === axis.low) axis.high = axis.low + axis.step;
            const x = stamp => left + (right - left) * (stamp - start) / Math.max(86400000, end - start),
                y = value => bottom - (value - axis.low) / (axis.high - axis.low) * (bottom - top);
            bounds = {
                x
            };
            if (floor !== null) svg.append(element('rect', {
                x: left,
                y: y(floor),
                width: right - left,
                height: Math.max(0, bottom - y(floor)),
                fill: '#e9c991',
                opacity: '.28'
            }));
            for (let value = axis.low; value <= axis.high + axis.step / 100; value += axis.step) {
                svg.append(element('line', {
                    x1: left,
                    x2: right,
                    y1: y(value),
                    y2: y(value),
                    stroke: '#9aa8a1',
                    'stroke-dasharray': '3 5'
                }));
                svg.append(element('text', {
                    x: left - 8,
                    y: y(value) + 4,
                    'text-anchor': 'end',
                    'font-size': 12,
                    fill: 'currentColor'
                }, axisLabel(value)));
            }
            const tickCount = width < 500 ? 3 : 5;
            for (let i = 0; i < tickCount; i++) {
                const stamp = start + (end - start) * i / (tickCount - 1);
                svg.append(element('text', {
                    x: x(stamp),
                    y: 258,
                    'text-anchor': i === 0 ? 'start' : i === tickCount - 1 ? 'end' : 'middle',
                    'font-size': 12,
                    fill: 'currentColor'
                }, shortDate.format(new Date(stamp))));
            }
            if (data.range_band && visible.length >= 2) {
                const low = visible.find(s => s.name === 'Monthly lowest balance'),
                    high = visible.find(s => s.name === 'Monthly highest balance');
                if (low && high) svg.append(element('polygon', {
                    points: [...low.data.map(p => `${x(Date.parse(p.date))},${y(numeric(p))}`), ...high.data.slice().reverse().map(p => `${x(Date.parse(p.date))},${y(numeric(p))}`)].join(' '),
                    fill: '#176b59',
                    opacity: '.12'
                }));
            }
            for (const marker of data.markers || []) {
                const stamp = Date.parse(marker.date);
                if (stamp < start || stamp > end) continue;
                const line = element('line', {
                    x1: x(stamp),
                    x2: x(stamp),
                    y1: top,
                    y2: bottom,
                    stroke: '#798a80',
                    'stroke-dasharray': '2 6'
                });
                line.append(element('title', {}, marker.label + ' · ' + marker.date));
                svg.append(line);
            }
            current.forEach((s, index) => {
                const line = element('polyline', {
                    id: root.key + '-series-' + index,
                    points: s.data.map(p => `${x(Date.parse(p.date))},${y(numeric(p))}`).join(' '),
                    fill: 'none',
                    stroke: s.color,
                    'stroke-width': s.reference ? 2 : 2.5,
                    'stroke-dasharray': s.dash || '',
                    'vector-effect': 'non-scaling-stroke'
                });
                line.append(element('title', {}, s.name));
                line.style.display = hidden.has(s.name) ? 'none' : '';
                svg.append(line);
            });
            cursor = element('line', {
                x1: left,
                x2: left,
                y1: top,
                y2: bottom,
                stroke: 'currentColor',
                'stroke-dasharray': '2 3'
            });
            cursor.style.display = 'none';
            svg.append(cursor);
            if (rebuild) {
                legend.replaceChildren();
                current.forEach((s, index) => {
                    const label = document.createElement('label'),
                        input = document.createElement('input'),
                        name = document.createElement('span');
                    input.type = 'checkbox';
                    input.checked = !hidden.has(s.name);
                    input.dataset.chartSeries = root.key + '-series-' + index;
                    input.setAttribute('aria-controls', root.key + '-series-' + index);
                    name.textContent = s.name;
                    name.style.borderBottom = '3px solid ' + s.color;
                    input.addEventListener('change', () => {
                        input.checked ? hidden.delete(s.name) : hidden.add(s.name);
                        draw(false);
                    });
                    label.append(input, name);
                    legend.append(label);
                });
                exactValues();
            }
        }
        mode?.addEventListener('change', () => {
            hidden = new Set();
            draw();
            panel.querySelector('.chart-note').textContent = model().note;
            reading.textContent = 'Showing ' + mode.selectedOptions[0].textContent.toLowerCase() + '.';
        });
        period?.addEventListener('change', () => {
            draw();
            reading.textContent = 'Showing ' + period.selectedOptions[0].textContent.toLowerCase() + '.';
        });
        const inspectPointer = event => {
            const dates = [...new Set(current.filter(s => !s.reference && !hidden.has(s.name)).flatMap(s => s.data.map(p => p.date)))].sort();
            if (!dates.length || !bounds) return;
            const position = event.clientX - svg.getBoundingClientRect().left;
            let index = 0,
                best = Infinity;
            dates.forEach((d, i) => {
                const delta = Math.abs(bounds.x(Date.parse(d)) - position);
                if (delta < best) {
                    index = i;
                    best = delta;
                }
            });
            announce(index);
        };
        svg.addEventListener('pointermove', inspectPointer);
        svg.addEventListener('pointerdown', inspectPointer);
        svg.addEventListener('focus', () => announce(selected));
        svg.addEventListener('keydown', event => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            announce(event.key === 'Home' ? 0 : event.key === 'End' ? Number.MAX_SAFE_INTEGER : selected + (event.key === 'ArrowRight' ? 1 : -1));
        });
        new ResizeObserver(() => {
            if (Math.round(svg.getBoundingClientRect().width) !== lastWidth) draw(false);
        }).observe(svg);
        panel.addEventListener('toggle', () => {
            if (panel.open) draw(false);
        });
        draw();
    });
})();
