"""Station-owned message state; replacement semantics and causal watermarks."""

from __future__ import annotations
from dataclasses import replace
import hashlib
import numpy as np
from .records import Exposure, Packet, Request, StationObservation, StationSnapshot


class InformationStore:
    def __init__(
        self,
        station: int,
        priors: tuple[StationSnapshot, ...],
        request_rates: tuple[float, ...],
        p2p: bool,
    ):
        self.station = station
        self.priors = priors
        self.prior_rates = request_rates
        self.p2p = p2p
        self.received: dict[int, Packet] = {}
        self.local: dict[tuple, Exposure] = {}
        self.request_times: list[float] = []
        self.sequence = 0
        self.duplicates = 0
        self.stale = 0

    def receive(self, packet: Packet, at: float) -> bool:
        if not self.p2p:
            raise ValueError("No-P2P cannot receive peer information")
        if packet.issued_at > at + 1e-10:
            raise ValueError("Packet from future")
        if packet.snapshot.issued_at > packet.issued_at or any(
            x.issuer != packet.sender or x.issued_at > packet.issued_at
            for x in packet.exposure
        ):
            raise ValueError("Peer payload has invalid provenance/future timestamp")
        previous = self.received.get(packet.sender)
        if previous and packet.sequence <= previous.sequence:
            self.duplicates += 1
            return False
        self.received[packet.sender] = packet
        return True

    def record_request(self, at: float) -> None:
        self.request_times = [t for t in self.request_times if t > at - 5.0]
        self.request_times.append(at)

    def record_exposure(
        self, request: Request, recommended: int, travel: tuple[float, ...], ttl: float
    ) -> Exposure:
        bucket = tuple(-1 if t < 0 else int(t // 5) for t in travel)
        context = hashlib.blake2b(
            repr((bucket, int(request.energy_kwh // 5), request.max_kw)).encode(),
            digest_size=8,
        ).hexdigest()
        key = self.station, recommended, context, int(request.issued_at // 5)
        previous = self.local.get(key)
        count = 1 if previous is None else previous.count + 1
        issued = (
            request.issued_at
            if previous is None
            else (previous.issued_at * previous.count + request.issued_at) / count
        )
        energy = (
            request.energy_kwh
            if previous is None
            else (previous.energy * previous.count + request.energy_kwh) / count
        )
        if previous is not None:
            travel = tuple(
                (a * previous.count + b) / count
                for a, b in zip(previous.travel, travel)
            )
        record = Exposure(
            self.station,
            recommended,
            context,
            key[-1],
            count,
            issued,
            request.issued_at + ttl,
            count,
            travel,
            energy,
            request.max_kw,
        )
        self.local[key] = record
        return record

    def packet(self, snapshot: StationSnapshot, at: float) -> Packet:
        self.sequence += 1
        self.local = {k: x for k, x in self.local.items() if x.expires_at > at}
        return Packet(
            self.station,
            self.sequence,
            at,
            snapshot,
            tuple(self.local.values()),
            len([t for t in self.request_times if t > at - 5]) / 5.0,
        )

    def observe(
        self, local_snapshot: StationSnapshot, at: float, max_age: float = 180.0
    ) -> StationObservation:
        count = len(self.priors)
        snapshots = list(self.priors)
        marks = [0.0] * count
        rates = list(self.prior_rates)
        available = [False] * count
        exposure = {k: x for k, x in self.local.items() if x.expires_at > at}
        for sender, packet in self.received.items():
            if at - packet.issued_at > max_age:
                marks[sender] = packet.issued_at
                self.stale += 1
                continue
            snapshots[sender] = packet.snapshot
            marks[sender] = packet.issued_at
            rates[sender] = 0.5 * (packet.request_rate + self.prior_rates[sender])
            available[sender] = True
            for x in packet.exposure:
                if x.expires_at > at:
                    exposure[x.key] = x
        snapshots[self.station] = local_snapshot
        marks[self.station] = at
        rates[self.station] = 0.5 * (
            len([t for t in self.request_times if t > at - 5]) / 5.0
            + self.prior_rates[self.station]
        )
        available[self.station] = True
        return StationObservation(
            self.station,
            at,
            tuple(snapshots),
            tuple(exposure.values()),
            tuple(marks),
            tuple(rates),
            len([t for t in self.request_times if t > at - 5]),
            tuple(available),
        )
