"""Single-owner BLE session; writes are explicit, logged once, never retried."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import os
import fcntl
import hashlib
import tempfile

from . import protocol as p
from .recording import recipe_digest


class BridgeError(RuntimeError):
    pass


class DeviceLock:
    """Prevent two copies of this bridge from controlling one device."""
    def __init__(self, address):
        name = hashlib.sha256(address.encode()).hexdigest()[:24]
        self.path = Path(tempfile.gettempdir()) / ('testcoffee-xbloom-' + name + '.lock')
        self.file = None

    def acquire(self):
        self.file = self.path.open('a')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            self.file = None
            raise BridgeError('Another bridge owns this device') from None

    def close(self):
        if self.file:
            self.file.close()
            self.file = None


class Session:
    def __init__(self, address, journal, *, client_factory=None):
        self.address, self.journal = address, journal
        self.factory = client_factory
        self.client = None
        self.lock = DeviceLock(address)
        self.assembler = p.FrameAssembler()
        self.changed = asyncio.Event()
        self.events = []
        self.failure = None
        self.loaded_digest = None
        self.start_attempted = False
        self._closing = False

    async def __aenter__(self):
        self.lock.acquire()
        try:
            if self.factory is None:
                from bleak import BleakClient
                self.factory = BleakClient
            self.client = self.factory(self.address, disconnected_callback=self._disconnected,
                                       timeout=20)
            self.journal.append('connecting', address=self.address)
            await self.client.connect()
            self.journal.append('connected')
            services = [{'uuid': s.uuid, 'characteristics': [
                {'uuid': c.uuid, 'properties': list(c.properties)} for c in s.characteristics
            ]} for s in self.client.services]
            self.journal.append('services', services=services)
            await self.client.start_notify(p.CHAR_STATUS, self._notify)
            self.journal.append('subscribed', characteristic=p.CHAR_STATUS)
            return self
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        self._closing = True
        try:
            self.journal.append('framing_tail', pending_hex=bytes(self.assembler.buffer).hex(),
                                discarded_bytes=self.assembler.discarded_bytes)
        finally:
            await self._disconnect_and_unlock()

    async def _disconnect_and_unlock(self):
        try:
            if self.client and self.client.is_connected:
                await self.client.disconnect()
        finally:
            self.lock.close()

    def _disconnected(self, _):
        self.loaded_digest = None
        try:
            self.journal.append('disconnected', expected=self._closing)
        except Exception as exc:
            self.failure = exc
        if not self._closing and self.failure is None:
            self.failure = BridgeError('Disconnected; execution state unknown. No retry.')
        self.changed.set()

    def _notify(self, sender, data):
        try:
            received = self.journal.append('rx', characteristic=str(getattr(sender, 'uuid', sender)),
                                           raw_hex=bytes(data).hex())
            for packet in self.assembler.feed(bytes(data)):
                try:
                    decoded = p.decode_frame(packet)
                except ValueError as exc:
                    self.journal.append('decode_error', raw_hex=packet.hex(), error=str(exc))
                    continue
                event = self.journal.append('decoded', data=decoded, received_seq=received['seq'],
                                            received_elapsed_s=received['elapsed_s'],
                                            received_wall_utc=received['wall_utc'])
                self.events.append(event)
        except Exception as exc:
            self.failure = exc
        self.changed.set()

    def _healthy(self):
        if self.failure:
            raise BridgeError(str(self.failure)) from self.failure
        if not self.client or not self.client.is_connected:
            raise BridgeError('Not connected')

    async def _send(self, label, packet):
        self._healthy()
        try:
            self.journal.append('tx_intent', label=label, raw_hex=packet.hex())
        except BaseException as exc:
            self.failure = exc
            raise
        try:
            await self.client.write_gatt_char(p.CHAR_COMMAND, packet, response=False)
            self.journal.append('tx_returned', label=label, meaning='host write returned; NOT machine acceptance')
        except BaseException as exc:
            self.loaded_digest = None
            self.failure = BridgeError('Write outcome unknown; reconnect/review required, no retry')
            self.journal.append('write_uncertain', label=label, error=repr(exc))
            raise

    async def wait_for(self, predicate, *, since, timeout):
        deadline = asyncio.get_running_loop().time() + timeout
        cursor = since
        while True:
            self._healthy()
            self.changed.clear()
            for event in self.events[cursor:]:
                if predicate(event['data']):
                    return event
            cursor = len(self.events)
            left = deadline - asyncio.get_running_loop().time()
            if left <= 0:
                raise BridgeError('No matching machine evidence within observation window')
            try:
                await asyncio.wait_for(self.changed.wait(), left)
            except asyncio.TimeoutError:
                raise BridgeError('No matching machine evidence within observation window') from None

    async def handshake(self, timeout=8):
        # A fresh CoreBluetooth connection can lose its first immediate write.
        # Settle BEFORE the single handshake; never automatically retransmit it.
        self.journal.append('connection_settle', seconds=2.0)
        await asyncio.sleep(2.0)
        since = len(self.events)
        await self._send('handshake', p.handshake_frame())
        return await self.wait_for(lambda d: d.get('kind') == 'machine_info',
                                   since=since, timeout=timeout)

    async def read_device_information(self):
        """Read only standard Device Information GATT values if advertised."""
        names = {'2a29': 'manufacturer', '2a24': 'model', '2a25': 'serial',
                 '2a27': 'hardware_revision', '2a26': 'firmware_revision',
                 '2a28': 'software_revision'}
        for service in self.client.services:
            if service.uuid.lower() != '0000180a-0000-1000-8000-00805f9b34fb':
                continue
            for char in service.characteristics:
                short = char.uuid.lower()[4:8]
                if short not in names or 'read' not in char.properties:
                    continue
                self._healthy()
                self.journal.append('gatt_read_intent', characteristic=char.uuid)
                try:
                    raw = bytes(await asyncio.wait_for(self.client.read_gatt_char(char.uuid), 5))
                except Exception as exc:
                    self.journal.append('gatt_read_error', characteristic=char.uuid, error=str(exc))
                    continue
                self.journal.append('device_information', field=names[short],
                                    raw_hex=raw.hex(), text=raw.decode('utf-8', errors='replace').strip('\0'))

    async def observe(self, seconds):
        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            self._healthy()
            self.changed.clear()
            try:
                await asyncio.wait_for(self.changed.wait(),
                                       max(0.001, deadline - asyncio.get_running_loop().time()))
            except asyncio.TimeoutError:
                break
        self._healthy()

    async def load(self, recipe, *, timeout=10):
        """Load from observed idle; unknown mode/grind snapshots are diagnostics only.

        Armed status after configuration is the acceptance evidence. A mode field
        whose meaning is unverified must not become an invented execution gate.
        """
        self._healthy()
        if self.loaded_digest or self.start_attempted:
            raise BridgeError('This session already staged or started a recipe')
        recipe = deepcopy(recipe)
        frames = p.build_recipe_frames(recipe)
        infos = [e['data'] for e in self.events if e['data'].get('kind') == 'machine_info']
        mode = infos[-1].get('mode') if infos else None
        self.journal.append('load_mode_observation', mode=mode, meaning='diagnostic, not acceptance evidence')
        states = [e['data'].get('state') for e in self.events if e['data'].get('state')]
        if not states or states[-1] in ('loading',):
            await self.wait_for(lambda d: bool(d.get('state')) and d['state'] != 'loading',
                                since=len(self.events), timeout=timeout)
            states = [e['data'].get('state') for e in self.events if e['data'].get('state')]
        if states[-1] != 'idle':
            raise BridgeError('Machine is not observed idle; no configuration was sent')
        self.journal.append('recipe_snapshot', recipe=recipe, sha256=recipe_digest(recipe))
        since = len(self.events)
        for label, frame in frames:
            await self._send(label, frame)
            await asyncio.sleep(0.4)
        try:
            await self.wait_for(lambda d: d.get('state') == 'armed', since=since, timeout=timeout)
        except BaseException:
            self.failure = BridgeError('Load unconfirmed; do not retry in this session')
            raise
        self.loaded_digest = recipe_digest(recipe)
        self.journal.append('load_observed', sha256=self.loaded_digest, evidence='armed state')

    async def start(self, reviewed_digest, *, authorized=False, timeout=10):
        self._healthy()
        if not authorized or reviewed_digest != self.loaded_digest or not self.loaded_digest:
            raise BridgeError('Explicit start authorization and this session recipe digest required')
        states = [e['data'].get('state') for e in self.events if e['data'].get('state')]
        if self.start_attempted or not states or states[-1] != 'armed':
            raise BridgeError('Already attempted or machine no longer armed; no start sent')
        self.start_attempted = True
        since = len(self.events)
        await self._send('start_commit', p.start_frame())
        try:
            event = await self.wait_for(lambda d: d.get('state') in (
                'starting', 'brewing', 'no_water', 'no_beans'), since=since, timeout=timeout)
        except BaseException:
            self.journal.append('start_unconfirmed', completion='unconfirmed')
            raise
        if event['data']['state'] in ('no_water', 'no_beans'):
            raise BridgeError('Machine refused start: ' + event['data']['state'])
        self.journal.append('start_observed', evidence=event['seq'])

    async def cancel(self, *, authorized=False, timeout=10):
        if not authorized:
            raise BridgeError('Explicit cancel authorization required')
        self.loaded_digest = None
        since = len(self.events)
        await self._send('cancel', p.cancel_frame())
        await self.wait_for(lambda d: d.get('state') == 'idle', since=since, timeout=timeout)
        self.journal.append('idle_after_cancel', meaning='observed idle; no automatic restart')
