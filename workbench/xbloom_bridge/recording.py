"""Append-only evidence; summaries can be regenerated from the JSONL journal."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from .observation import BrewWindow


class Journal:
    def __init__(self, root, *, operation, address=None, recipe=None):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                            + '-' + uuid.uuid4().hex[:12] + '.jsonl')
        self._file = self.path.open('x', encoding='utf-8')
        self._start = time.monotonic_ns()
        self._seq = 0
        self.append('session', operation=operation, address=address,
                    recipe=recipe, recipe_sha256=recipe_digest(recipe) if recipe else None)

    def elapsed(self):
        return (time.monotonic_ns() - self._start) / 1e9

    def append(self, kind, **data):
        event = dict(seq=self._seq, wall_utc=datetime.now(timezone.utc).isoformat(),
                     elapsed_s=self.elapsed(),
                     kind=kind, **data)
        # Encoding and flush errors propagate: a command must never be sent unlogged.
        self._file.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
        self._file.flush()
        os.fsync(self._file.fileno())
        self._seq += 1
        return event

    def close(self):
        self._file.close()


def recipe_digest(recipe):
    return hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def read_events(path):
    with open(path, encoding='utf-8') as stream:
        for line in stream:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # A killed process can leave an unfinished final write. Keep earlier evidence.
                yield {'kind': 'journal_damage', 'raw_text': line}


def summarize(path):
    """No terminal candidate/plateau becomes confirmed completion automatically."""
    counts = Counter()
    states = Counter()
    types = Counter()
    latest_info = None
    machine_info_observed_s = None
    state_history = []
    device_information = {}
    water, coffee = [], []
    candidates = []
    evidence = []
    last_time = 0
    session = {}
    window = BrewWindow()
    for event in read_events(path):
        window.accept(event)
        kind = event['kind']
        counts[kind] += 1
        last_time = max(last_time, event.get('elapsed_s', 0))
        if kind == 'session':
            session = event
        if kind == 'device_information':
            device_information[event['field']] = event['text']
        if kind in ('error', 'journal_damage') or (kind == 'disconnected' and not event.get('expected')):
            evidence.append(event)
        if kind != 'decoded':
            continue
        d = event['data']
        observed_s = event.get('received_elapsed_s', event['elapsed_s'])
        types[str(d.get('code'))] += 1
        if d.get('kind') == 'machine_info':
            latest_info = d
            machine_info_observed_s = observed_s
        if d.get('state'):
            states[d['state']] += 1
            state_history.append({'elapsed_s': observed_s, 'wall_utc': event.get('received_wall_utc', event.get('wall_utc')),
                                  'state': d['state'], 'evidence_seq': event.get('seq')})
        for name, series in [('water_g', water), ('coffee_g', coffee)]:
            if d.get(name) is not None and not (window.started and window.reason):
                series.append([observed_s, d[name]])
        if d.get('kind') == 'completion_candidate' or d.get('state') in ('ready', 'complete'):
            candidates.append({'elapsed_s': observed_s, 'data': d})
    return dict(journal=str(path), session=session, event_counts=dict(counts),
                frame_codes=dict(types), states_observed=dict(states), machine_info=latest_info,
                machine_info_observed_s=machine_info_observed_s, state_history=state_history,
                device_information=device_information,
                water_curve=water, coffee_curve=coffee, completion_candidates=candidates,
                completion='unconfirmed', machine_brew_duration_s=None,
                capture_duration_s=round(last_time, 3), interruptions=evidence,
                interpretation='machine_info is a timestamped snapshot; weight units and state meanings are provisional',
                clock_definition='host elapsed from capture creation, NOT machine brew timer')
