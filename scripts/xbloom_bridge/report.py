"""Offline, standard-library brew reports. Never imports transport or changes evidence."""
from __future__ import annotations

from datetime import datetime
from html import escape
import json
import math
from pathlib import Path
import tempfile


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def build_report(path):
    """One journal is one attempt. Missing signals remain missing, never inferred."""
    rows, warnings = [], []
    for line_no, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('not an object')
            rows.append(row)
        except (ValueError, TypeError):
            warnings.append(f'日志第 {line_no} 行损坏，已跳过，原文保留。')
    sessions = [r for r in rows if r.get('kind') == 'session']
    if len(sessions) > 1:
        raise ValueError('一个报告只接受一个会话，不能合并多次冲煮')
    session = sessions[0] if sessions else {}
    recipe = session.get('recipe') or {}
    settings = recipe.get('recipe') or {}
    context = next((r for r in rows if r.get('kind') == 'report_context'), {})
    decoded = []
    for row in rows:
        if row.get('kind') != 'decoded':
            continue
        t = row.get('received_elapsed_s', row.get('elapsed_s'))
        if not number(t) or t < 0 or not isinstance(row.get('data'), dict):
            warnings.append('跳过时间或数据无效的解码记录。')
            continue
        decoded.append((t, row['data']))
    if decoded != sorted(decoded, key=lambda item: item[0]):
        warnings.append('接收时间非递增，绘图按接收时间排序。')
    decoded.sort(key=lambda item: item[0])
    start = next((t for t, d in decoded if d.get('code') == 40510), None)
    active = [(t, d) for t, d in decoded if start is not None and t >= start]
    idle = next((t for t, d in active if d.get('state') == 'idle'), None)
    active = [(t, d) for t, d in active if idle is None or t < idle]
    stages = [t - start for t, d in active if d.get('code') == 40510]
    stop = next((t - start for t, d in active if d.get('code') == 40511), None)
    candidate = next((t - start for t, d in active if d.get('code') == 40512), None)
    candidate_source = '40512' if candidate is not None else None
    if candidate is None:
        candidate = next((t - start for t, d in active if d.get('state') == 'ready'), None)
        if candidate is not None:
            candidate_source = 'ready'

    def series(field):
        points = {}
        for t, d in active:
            value = d.get(field)
            if value is not None:
                if number(value) and 0 <= value <= 2000:
                    points[t - start] = value
                else:
                    warnings.append(f'{field} 出现无效读数，未绘制。')
        return list(points.items())

    coffee_raw = series('coffee_g')
    removed = []
    for i in range(1, len(coffee_raw) - 1):
        left, mid, right = coffee_raw[i-1:i+2]
        # A local isolated rise, never remove broad peaks or endpoints.
        if (right[0] - left[0] <= 2 and abs(left[1] - right[1]) < 1
                and mid[1] - max(left[1], right[1]) > 8):
            removed.append(i)
    coffee = [point for i, point in enumerate(coffee_raw) if i not in set(removed)]
    if removed:
        warnings.append(f'绘图排除 {len(removed)} 个孤立向上尖峰（相邻跨度≤2秒、两侧差<1g、尖峰高出>8g），原始日志未改。')
    water = series('water_g')
    if water:
        # Stop drawing at the first maximum so an idle/reset is not shown as negative pouring.
        peak = max(v for _, v in water)
        water = water[:next(i for i, (_, v) in enumerate(water) if v == peak) + 1]
        if any(b[1] < a[1] for a, b in zip(water, water[1:])):
            warnings.append('注水计数发生回退，曲线保留，不能当作实际累计出水量。')
    if candidate_source == 'ready':
        warnings.append('未收到40512；结束候选采用ready接收时刻，不代表屏显计时或物理末滴。')
    errors = [str(r.get('error', '日志异常')) for r in rows if r.get('kind') == 'error']
    unexpected = any(r.get('kind') == 'disconnected' and not r.get('expected') for r in rows)
    warnings.extend(errors)
    if unexpected:
        warnings.append('发生意外断线，后续过程可能缺失。')
    if start is None:
        warnings.append('未记录首段注水，无法建立冲煮时间轴。')
    pours = settings.get('pours') or []
    if len(stages) != len(pours):
        warnings.append('注水事件数与配方段数不一致，不保证事件与段号一一对应。')
    if not coffee:
        warnings.append('未记录有效杯中液重。')
    try:
        clock = datetime.fromisoformat(session['wall_utc']).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
    except (KeyError, ValueError, TypeError):
        clock = '时间未记录'
    return dict(session=session, recipe=recipe, settings=settings, context=context,
                clock=clock, stages=stages, stop=stop, candidate=candidate, candidate_source=candidate_source,
                coffee=coffee, water=water, idle=idle,
                warnings=list(dict.fromkeys(warnings)),
                status=('异常记录' if errors or unexpected else '记录不完整' if start is None
                        else '已回待机 · 完成待核对' if idle is not None else '完成待核对'))


def display(value, suffix=''):
    if value is None:
        return '未记录'
    return (f'{value:g}' if number(value) else str(value)) + suffix


def duration(value):
    if value is None:
        return '未记录'
    seconds = round(value)
    return f'{seconds // 60}:{seconds % 60:02d}'


def render_svg(data, *, title=None, brewer=None):
    """Entire report is SVG, also embeddable in the self-contained HTML."""
    settings, recipe = data['settings'], data['recipe']
    pours, stages = settings.get('pours') or [], data['stages']
    coffee, water = data['coffee'], data['water']
    dose, through = recipe.get('doseGrams'), settings.get('grandWater')
    bypass = recipe.get('bypassMl', 0)
    bypass_enabled = number(bypass) and bypass > 0
    total = through + bypass if number(through) and number(bypass) and bypass >= 0 else None
    title = title or data['context'].get('title') or 'xBloom 冲煮记录'
    brewer = brewer or data['context'].get('brewer') or '实物滤杯未记录'
    notes = [
        '时间轴从首段注水起算；结束候选事件间隔不等于屏显计时，屏显及最后一滴仍待核对。',
        '液重是回待机前（或采集截止前）末次有效读数，不能据此确认稳定出杯重量。',
        '注水计数沿用解码字段 water_g，物理单位待校准；配方水量单位为 ml。',
        '浅蓝柱为相邻液重读数变化率（g/s），仅显示间隔≤2秒的非负值，不是注水流速。',
        '曲线不补零；采样间隔超过5秒时断线显示。研磨、RPM、温度和振动均为配方设定。',
    ] + data['warnings']
    if bypass_enabled:
        notes += [f'水量设定：过粉 {display(through, " ml")} ＋ 原生旁通 {display(bypass, " ml")} '
                  f'＝ 合计 {display(total, " ml")}；粉水比按合计计算。',
                  '旁通行仅代表配方设定；尚未单独识别旁通事件、实际出水量及温度，不按事件序号推定旁通完成。']
    # Split long notes to keep SVG viewBox/export from clipping text.
    lines = [note[i:i+53] for note in notes for i in range(0, len(note), 53)]
    footer_y = 700 + (len(pours) + int(bypass_enabled))*36
    height = footer_y + 52 + 21*len(lines)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 934 {height}" role="img" aria-label="冲煮过程报告">',
           '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans GB",sans-serif;fill:#453020} .muted{fill:#937b62} .axis{fill:#937b62;font-size:11px}</style>',
           f'<rect width="934" height="{height}" fill="#fbf8f1"/>']

    def text(x, y, value, size=14, color=None, weight=None):
        attrs = (f' style="fill:{color}"' if color else '') + (f' font-weight="{weight}"' if weight else '')
        svg.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}"{attrs}>{escape(str(value))}</text>')

    def line(xa, ya, xb, yb, color='#e4d8c8', dash=''):
        svg.append(f'<path d="M{xa:.2f} {ya:.2f}L{xb:.2f} {yb:.2f}" stroke="{color}" stroke-dasharray="{dash}"/>')

    for i in range(0, len(title), 32):
        if i >= 64:
            break
        text(38, 39 + (i//32)*27, title[i:i+32], 23, weight=700)
    text(38, 96, f'{data["clock"]} · {brewer}', 13, '#937b62')
    text(38, 119, data['status'], 12, '#8a5a38')
    line(38, 135, 896, 135)
    ratio = f'1:{total/dose:g}' if number(dose) and dose > 0 and number(total) else '未记录'
    metrics = [('咖啡粉（设定）', display(dose, ' g')), ('总注水（设定）', display(total, ' ml')),
               ('粉水比', ratio), ('首段至结束候选事件', duration(data['candidate'])),
               ('末次液重读数', f'{coffee[-1][1]:.1f} g' if coffee else '未记录'),
               ('屏显计时 / 最后一滴', '待核对')]
    for i, (label, value) in enumerate(metrics):
        xx, yy = 38+(i%3)*286, 162+(i//3)*65
        text(xx, yy, label, 12, '#937b62')
        text(xx, yy+30, value, 26, weight=650)
    line(38, 278, 896, 278)
    text(40, 305, '━━ 杯中液重（机器读数）', 12, '#794c31')
    text(275, 305, '┄ 累计注水（机器计数）', 12, '#bb8b46')
    text(520, 305, '▥ 液重变化率', 12, '#6691a9')
    x0, x1, y0, y1 = 76, 844, 345, 535
    end = max([t for t, _ in coffee + water] + stages + [data['candidate'] or 0, 30])
    xmax = math.ceil(end/30)*30
    ymax = max(50, math.ceil(max([v for _, v in coffee+water] + [total if number(total) else 0])/50)*50)
    rates = [(b[0], (b[1]-a[1])/(b[0]-a[0])) for a, b in zip(coffee, coffee[1:])
             if 0 < b[0]-a[0] <= 2 and b[1] >= a[1]]
    rmax = max(8, math.ceil(max([v for _, v in rates]+[0])/2)*2)
    x = lambda t: x0+t/xmax*(x1-x0)
    y = lambda value: y1-value/ymax*(y1-y0)
    for i in range(6):
        value = ymax*i/5
        line(x0, y(value), x1, y(value))
        text(38, y(value)+4, f'{value:g}', 11, '#937b62')
    for i in range(5):
        text(854, y1-i/4*(y1-y0)+4, f'{rmax*i/4:g}', 11, '#6691a9')
    text(40, 329, 'g / 注水计数（单位待校准）', 11, '#937b62')
    text(854, 329, 'g/s', 11, '#6691a9')
    tick = max(30, math.ceil(xmax/8/30)*30)
    for t in range(0, xmax+1, tick):
        text(x(t)-8, y1+23, f'{t}s', 11, '#937b62')
    for t, rate in rates:
        h = rate/rmax*(y1-y0)
        svg.append(f'<rect x="{x(t):.2f}" y="{y1-h:.2f}" width="2" height="{h:.2f}" fill="#c9dce6"/>')
    for i, t in enumerate(stages):
        line(x(t), y0, x(t), y1, '#c8ad8e', '3 4')
        caption = f'事件{i+1}'
        if len(stages) == len(pours) and not bypass_enabled:
            caption = f'{i+1}段 {display(pours[i].get("temperature"), "℃")}'
        text(x(t)+3, y1-9, caption, 10, '#937b62')
    for points, color, dash in [(water, '#bb8b46', '5 4'), (coffee, '#794c31', '')]:
        for a, b in zip(points, points[1:]):
            if b[0]-a[0] <= 5:
                line(x(a[0]), y(a[1]), x(b[0]), y(b[1]), color, dash)
        if points:
            t, value = points[-1]
            svg.append(f'<circle cx="{x(t):.2f}" cy="{y(value):.2f}" r="3" fill="{color}"/>')
            text(min(x(t), x1)-65, y(value)-10, f'{value:.1f}', 12, color)
    if data['candidate'] is not None:
        px = x(data['candidate'])
        line(px, y0, px, y1, '#a7a095', '2 4')
        text(max(x0, px-92), y0-7, f'候选 {duration(data["candidate"])}', 11, '#937b62')
    if not coffee and not water:
        text(310, 440, '暂无可绘制的冲煮采样', 20, '#937b62')
    grinder_off = settings.get('grindEnabled') is False
    fields = [('研磨（设定）', 'OFF' if grinder_off else display(settings.get('grinderSize'), ' 档')),
              ('磨豆转速（设定）', '不适用' if grinder_off else display(settings.get('rpm'), ' RPM')),
              ('注水事件 / 过粉段数' if bypass_enabled else '注水事件 / 配方段数', f'{len(stages)} / {len(pours)}'),
              ('首段至停止事件', duration(data['stop']))]
    for i, (label, value) in enumerate(fields):
        xx, yy = 38+(i%2)*440, 600+(i//2)*35
        text(xx, yy, label, 13, '#937b62')
        text(xx+240, yy, value, 14, weight=650)
        line(xx, yy+9, xx+410, yy+9, dash='2 3')
    columns = [38, 145, 252, 360, 490, 585, 690, 795]
    for xx, label in zip(columns, ['分段', '水量', '水温', '流速', '路径', '段后停顿', '段前振动', '段后振动']):
        text(xx, 681, label, 12, '#937b62')
    for i, pour in enumerate(pours):
        yy = 716+i*36
        vibration = lambda key: '开' if pour.get(key) is True else '关' if pour.get(key) is False else '未记录'
        values = [f'第{i+1}段', display(pour.get('volume'), ' ml'), display(pour.get('temperature'), '℃'),
                  display(pour.get('flowRate'), ' ml/s'), {0:'中心', 1:'环绕', 2:'螺旋'}.get(pour.get('pattern'), '未知'),
                  display(pour.get('pausing'), ' s'), vibration('vibBefore'), vibration('vibAfter')]
        for xx, value in zip(columns, values):
            text(xx, yy, value, 13)
        line(38, yy+10, 896, yy+10)
    if bypass_enabled:
        yy = 716 + len(pours)*36
        values = ['原生旁通', display(bypass, ' ml'), display(recipe.get('bypassTempC'), '℃'),
                  '—', '—', '—', '—', '—']
        for xx, value in zip(columns, values):
            text(xx, yy, value, 13)
        line(38, yy+10, 896, yy+10)
    text(38, footer_y+20, '记录口径与异常', 13, weight=650)
    for i, value in enumerate(lines):
        text(38, footer_y+44+i*21, value, 12, '#796957')
    svg.append('</svg>')
    return ''.join(svg)


def _write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(text)
            stream.flush()
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def generate_report(journal, *, output=None, title=None, brewer=None):
    source = Path(journal).resolve()
    data = build_report(source)
    svg = render_svg(data, title=title, brewer=brewer)
    root = Path(output).resolve() if output else source.parent / 'reports'
    svg_path, html_path = root / (source.stem+'.svg'), root / (source.stem+'.html')
    page_title = title or data['context'].get('title') or 'xBloom 冲煮记录'
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(page_title)}</title><style>body{{margin:0;background:#fbf8f1}}'
            'main{max-width:934px;margin:auto}svg{display:block;width:100%;height:auto}'
            'footer{padding:20px;overflow-wrap:anywhere;color:#796957}</style><main>' + svg +
            f'<footer>来源日志 {escape(source.name)}<br>配方指纹 '
            f'{escape(str(data["session"].get("recipe_sha256") or "未记录"))}</footer></main></html>')
    _write_atomic(svg_path, svg)
    _write_atomic(html_path, html)
    return dict(html=str(html_path), svg=str(svg_path), warnings=data['warnings'],
                hardware_access=False, completion='unconfirmed')
