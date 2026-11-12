"""Offline index scoped to one explicit directory, with no repository discovery."""
from __future__ import annotations

from html import escape
import json
from pathlib import Path
from urllib.parse import quote

from .report import _write_atomic, generate_report


STYLE = '''body{max-width:960px;margin:40px auto;padding:0 20px;background:#fbf8f1;
color:#453020;font:16px/1.7 -apple-system,BlinkMacSystemFont,sans-serif}
a{color:#8a5634}table{width:100%;border-collapse:collapse}td,th{padding:12px 8px;
border-bottom:1px solid #e4d8c8;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}
small{color:#796957}@media(max-width:650px){table,tbody,tr,td{display:block}thead{display:none}}'''


def _files(root):
    """Do not traverse symlinked directories or symlinked source files."""
    for item in sorted(root.iterdir()):
        if item.is_symlink():
            continue
        if item.is_dir():
            if item.name not in ('reports', '.git', '.venv', '__pycache__'):
                yield from _files(item)
        elif item.suffix == '.jsonl' and item.is_file():
            yield item


def build_history(directory):
    requested = Path(directory)
    if requested.is_symlink():
        raise ValueError('History root must not be a symlink')
    root = requested.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('History root must be a directory')
    entries, warnings = [], []
    for path in _files(root):
        rows = []
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except ValueError:
                warnings.append(f'损坏行保留于 {path.relative_to(root)}')
        sessions = [r for r in rows if r.get('kind') == 'session']
        if len(sessions) != 1 or sessions[0].get('operation') != 'brew':
            continue
        context = next((r for r in rows if r.get('kind') == 'report_context'), {})
        started = any(r.get('kind') == 'start_observed' for r in rows)
        sent = any(r.get('kind') == 'tx_intent' and r.get('label') == 'start_commit' for r in rows)
        status = '有启动记录 · 完成待核对' if started else '启动已发 · 执行待核对' if sent else '未发启动'
        if any(r.get('kind') == 'error' for r in rows):
            status += ' · 异常'
        title = str(context.get('title') or '豆子未注明')
        stamp = str(sessions[0].get('wall_utc') or '时间未知')
        # Rebuild derived HTML/SVG from this journal only; never overwrite evidence.
        try:
            result = generate_report(path)
            report = Path(result['html'])
            page = report.read_text(encoding='utf-8')
            candidates = [path.parent/'record.md']
            if path.parent.name == 'logs':
                candidates.append(path.parent.parent/'record.md')
            record = next((p for p in candidates if p.is_file() and not p.is_symlink()), None)
            if record:
                note = ('<details style="padding:20px"><summary>本杯条件、审核与品饮反馈</summary>'
                        '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
                        + escape(record.read_text(encoding='utf-8')) + '</pre></details>')
                page = page.replace('</main>', note+'</main>', 1)
                _write_atomic(report, page)
            target = report.relative_to(root)
        except Exception as exc:
            warnings.append(f'{path.relative_to(root)}: {exc}')
            target = path.relative_to(root)
            status += ' · 报告失败，链接原始日志'
        entries.append((stamp, title, status, target))
    entries.sort(key=lambda item: (item[0], str(item[3])), reverse=True)
    body = ''.join('<tr><td>'+escape(stamp)+'</td><td><a href="'+quote(target.as_posix(), safe='/')
                   +'">'+escape(title)+'</a></td><td>'+escape(status)+'</td></tr>'
                   for stamp, title, status, target in entries)
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>冲煮总账</title><style>'+STYLE+'</style><h1>冲煮总账</h1>'
            f'<p>{len(entries)}次尝试，包含失败与重试。时间为日志UTC，状态不代替物理出杯确认。</p>'
            '<table><thead><tr><th>采集时间</th><th>本次报告</th><th>状态</th></tr></thead><tbody>'
            +body+'</tbody></table>'
            +''.join('<p>'+escape(w)+'</p>' for w in warnings)+'</html>')
    _write_atomic(root/'index.html', page)
    return {'index': str(root/'index.html'), 'entries': len(entries), 'warnings': warnings,
            'hardware_access': False}
