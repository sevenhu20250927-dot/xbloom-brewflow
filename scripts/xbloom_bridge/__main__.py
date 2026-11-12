"""CLI: python -m xbloom_bridge --help. Defaults never start a brew."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .recording import Journal, summarize, read_events, recipe_digest
from .transport import Session, BridgeError
from . import protocol as p


def positive(value):
    number = float(value)
    if not 0 < number <= 3600:
        raise argparse.ArgumentTypeError('must be >0 and <=3600 seconds')
    return number


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('scan', help='discover xBloom advertisements only')
    scan.add_argument('--seconds', type=positive, default=8)
    scan.add_argument('--output', default='ble_runs')
    for name in ('observe', 'load', 'brew', 'cancel'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--address', required=True, help='explicit target, never picks first machine')
        cmd.add_argument('--seconds', type=positive, default=30 if name == 'observe' else 300)
        cmd.add_argument('--output', default='ble_runs')
        if name in ('load', 'brew'):
            cmd.add_argument('--recipe', required=True)
        if name == 'brew':
            cmd.add_argument('--confirm-start', action='store_true', help='physically dispenses hot water')
            cmd.add_argument('--reviewed-sha256', required=True)
            cmd.add_argument('--report-title', help='bean/title supplied by the user, saved with this run')
            cmd.add_argument('--brewer', help='actual physical brewer, not inferred from protocol cupType')
        if name == 'cancel':
            cmd.add_argument('--confirm-cancel', action='store_true')
    preview = sub.add_parser('preview', help='validate/print frames offline')
    preview.add_argument('--recipe', required=True)
    replay = sub.add_parser('replay', help='redecode recorded raw notifications offline')
    replay.add_argument('journal')
    summary = sub.add_parser('summary')
    summary.add_argument('journal')
    report = sub.add_parser('report', help='render HTML + SVG from a journal, without Bluetooth')
    report.add_argument('journal')
    report.add_argument('--output', help='report directory; defaults to journals/reports')
    report.add_argument('--title')
    report.add_argument('--brewer')
    history = sub.add_parser('history', help='index one explicit log directory offline')
    history.add_argument('directory')
    return result


def replay(path):
    assembler = p.FrameAssembler()
    counts = {'raw_chunks': 0, 'frames': 0, 'errors': 0}
    states = set()
    for event in read_events(path):
        if event['kind'] == 'journal_damage':
            counts['errors'] += 1
        if event['kind'] != 'rx':
            continue
        counts['raw_chunks'] += 1
        for packet in assembler.feed(bytes.fromhex(event['raw_hex'])):
            try:
                d = p.decode_frame(packet)
                counts['frames'] += 1
                if d.get('state'):
                    states.add(d['state'])
            except ValueError:
                counts['errors'] += 1
    return dict(counts, states=sorted(states), trailing_bytes=len(assembler.buffer),
                discarded_bytes=assembler.discarded_bytes,
                meaning='offline parsing only, not hardware verification')


async def run(args):
    if args.command == 'history':
        from .history import build_history
        return build_history(args.directory)
    recipe = None
    if hasattr(args, 'recipe'):
        recipe = p.load_recipe(args.recipe)
        frames = p.build_recipe_frames(recipe)
        if args.command == 'preview':
            return {'sha256': recipe_digest(recipe), 'recipe': recipe,
                    'frames': [{'label': l, 'hex': b.hex()} for l, b in frames],
                    'hardware_access': False}
    if args.command == 'summary':
        return summarize(args.journal)
    if args.command == 'replay':
        return replay(args.journal)
    if args.command == 'report':
        from .report import generate_report
        return generate_report(args.journal, output=args.output, title=args.title, brewer=args.brewer)
    # Refuse invalid authorization before scanning, opening a log, or connecting.
    if args.command == 'brew' and (not args.confirm_start or
                                   args.reviewed_sha256 != recipe_digest(recipe)):
        raise BridgeError('Reviewed recipe digest and --confirm-start required')
    if args.command == 'cancel' and not args.confirm_cancel:
        raise BridgeError('--confirm-cancel required')
    journal = Journal(args.output, operation=args.command,
                      address=getattr(args, 'address', None), recipe=recipe)
    print(json.dumps({'journal': str(journal.path)}, ensure_ascii=False), flush=True)
    report_result = None
    try:
        if args.command == 'brew' and (getattr(args, 'report_title', None) or getattr(args, 'brewer', None)):
            journal.append('report_context', title=getattr(args, 'report_title', None),
                           brewer=getattr(args, 'brewer', None))
        if args.command == 'scan':
            from bleak import BleakScanner
            devices = await BleakScanner.discover(timeout=args.seconds, return_adv=True)
            hits = []
            for device, adv in devices.values():
                name = adv.local_name or device.name or ''
                if 'BLOOM' in name.upper() or p.SERVICE_UUID in adv.service_uuids:
                    hits.append(dict(name=name, address=device.address, rssi=adv.rssi,
                                     service_uuids=adv.service_uuids))
            journal.append('scan', devices_seen=len(devices), machines=hits)
            return {'scan_completed': True, 'machines': hits, 'journal': str(journal.path)}
        async with Session(args.address, journal) as session:
            if args.command == 'cancel':
                # A fresh connection needs its session handshake. This is NOT an
                # emergency-stop substitute for the machine's physical controls.
                await session.handshake()
                await session.cancel(authorized=True)
            else:
                await session.read_device_information()
                try:
                    await session.handshake()
                except BridgeError as exc:
                    if session.failure or args.command != 'observe':
                        raise
                    journal.append('handshake_unconfirmed', error=str(exc))
                    # Preserve later unsolicited replies; never retry the handshake.
                if recipe:
                    await session.load(recipe)
                if args.command == 'brew':
                    await session.start(args.reviewed_sha256, authorized=True)
                await session.observe(args.seconds)
            journal.append('observation_ended', reason='requested observation window ended',
                           completion='unconfirmed')
    except BaseException as exc:
        journal.append('error', error=repr(exc), completion='unconfirmed')
        raise
    finally:
        journal.close()
        if args.command == 'brew':
            # Session has disconnected and evidence is closed. Reporting cannot send commands.
            # Keep the original capture exception/exit status if reporting also fails.
            try:
                from .report import generate_report
                report_result = generate_report(journal.path)
                print(json.dumps({'report': report_result}, ensure_ascii=False), flush=True)
            except Exception as exc:
                report_result = {'error': str(exc), 'journal': str(journal.path)}
                print(json.dumps({'report_error': report_result}, ensure_ascii=False),
                      file=sys.stderr, flush=True)
            # Index only the caller-selected log directory. No repository discovery.
            try:
                from .history import build_history
                history = build_history(journal.path.parent)
                print(json.dumps({'history': history}, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(json.dumps({'history_error': str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
    result = summarize(journal.path)
    if report_result is not None:
        result['report'] = report_result
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except KeyboardInterrupt:
        print('Capture interrupted; no stop/restart command sent. Check the machine.', file=sys.stderr)
        return 130
    except Exception as exc:
        print(json.dumps({'error': str(exc), 'type': type(exc).__name__}), file=sys.stderr)
        return 1
    if args.command in ('observe', 'load', 'brew', 'cancel'):
        # Curves remain available via `summary`; do not flood a terminal at capture end.
        for key in ('water_curve', 'coffee_curve'):
            result[key + '_samples'] = len(result.pop(key))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
