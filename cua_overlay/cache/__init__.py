"""Cache module: AgentCache port + Cassette NDJSON format.

Per CONTEXT.md D-17 to D-21: AgentCache provides SHA-256 keyed, disk-persisted
cassette storage; Cassette defines NDJSON format for replay; CassetteReplayEngine
detects mismatches via pHash and falls through to live execution; WriteBack enforces
stable-tier gate and atomic file replacement.
"""
from .agent_cache import AgentCache
from .cassette import Cassette, CassetteStep
from .key import compute_cache_key
from .replay import CassetteReplayEngine
from .writeback import StreamCache, WriteBack

__all__ = [
    "compute_cache_key",
    "Cassette",
    "CassetteStep",
    "AgentCache",
    "CassetteReplayEngine",
    "WriteBack",
    "StreamCache",
]
