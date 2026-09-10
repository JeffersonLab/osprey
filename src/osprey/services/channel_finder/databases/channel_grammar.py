"""The channel grammar a hierarchical database declares.

A hierarchical channel database already states its own address grammar: the
``hierarchy`` block names the levels every address is composed of and the
``naming_pattern`` that joins them. This module reads the one further thing a
consumer of that grammar needs and the database alone can state -- **which
level tells a setpoint from its readback, and by which token pairs** -- so
that nothing downstream has to assume the reference facility's spelling.

The reference facility spells it ``{ring}:{system}:{family}:{device}:{field}:
{subfield}`` with ``SP`` and ``RB`` in the last level. Other facilities do not:
one may carry ``.S`` and ``M`` on its magnets, ``GSET`` and ``GMES`` on its RF,
``Preset_Volt`` and ``HVPSkVolts`` on its gun, all in the same last level.
Such a database declares its pairs beside its levels::

    "hierarchy": {
      "levels": [...],
      "naming_pattern": "{system}{family}{sector}{device}{property}",
      "pairing": {
        "level": "property",
        "pairs": [
          {"setpoint": ".S", "readback": "M", "where": {"system": ["M"]}},
          {"setpoint": "GSET", "readback": "GMES"},
          {"setpoint": "Preset_Volt", "readback": "HVPSkVolts"}
        ]
      }
    }

``level`` defaults to the last declared level. ``where`` restricts a pair to
the channels whose path takes one of the listed values at each named level;
a pair with no ``where`` applies to every channel. A database that declares no
``pairing`` block gets the reference convention only when it declares a level
named ``subfield`` (``SP``/``RB`` in it); otherwise it declares no pairs, and
nothing is invented for it -- every channel is then served without a
setpoint/readback relation, which the build says in so many words.

Two channels are the two halves of one pair when they share a **pair key** --
the values of every level except the pairing level, plus the declared pair's
setpoint token, so a device carrying several pairs (``GSET``/``GMES`` and
``PSET``/``PMES`` on one cavity) keys each apart -- and their pairing-level
tokens are the two sides of that pair. The key is what the virtual
accelerator pairs on and the manifest carries; the tokens are how each half
learns its **role**.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: The reference facility's six levels, in order. A database declaring exactly
#: these is the one the built-in facility spec describes.
BUILTIN_LEVELS: tuple[str, ...] = ("ring", "system", "family", "device", "field", "subfield")

#: The reference convention: ``SP`` and ``RB`` in a level named ``subfield``.
BUILTIN_PAIRING_LEVEL = "subfield"
BUILTIN_SETPOINT_TOKEN = "SP"
BUILTIN_READBACK_TOKEN = "RB"

#: A channel's role in a setpoint/readback pair. ``ROLE_NONE`` is the empty
#: string so a manifest entry can carry it as a plain JSON value.
ROLE_SETPOINT = "setpoint"
ROLE_READBACK = "readback"
ROLE_NONE = ""
ROLES = frozenset({ROLE_SETPOINT, ROLE_READBACK, ROLE_NONE})

#: What joins the identity values and the pair's setpoint token into a pair
#: key. Chosen for legibility: the reference facility's key reads
#: ``SR:MAG:HCM:01:CURRENT:SP``, the setpoint's own address.
PAIR_KEY_SEPARATOR = ":"


@dataclass(frozen=True)
class Pairing:
    """One channel's place in a declared setpoint/readback pair.

    Attributes:
        role: ``ROLE_SETPOINT`` or ``ROLE_READBACK``.
        pair_key: The key both halves of the pair share.
        counterpart: The pairing-level token of the other half.
    """

    role: str
    pair_key: str
    counterpart: str


class GrammarError(ValueError):
    """A ``hierarchy.pairing`` block is malformed, or names a token ambiguously.

    A ``ValueError`` like the database loader's other schema refusals, so a
    bad block fails ``load_database()`` (and ``osprey channel-finder validate``)
    with a named cause instead of surfacing as a bare ``KeyError`` from a
    consumer.
    """


@dataclass(frozen=True)
class TokenPair:
    """One declared setpoint/readback token pair.

    Attributes:
        setpoint: The pairing-level token that marks the setpoint half.
        readback: The pairing-level token that marks the readback half.
        where: Per-level value restriction; empty means every channel. A
            channel matches when, at every level named here, its path takes
            one of the listed values.
    """

    setpoint: str
    readback: str
    where: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def applies_to(self, path: Mapping[str, str]) -> bool:
        """Whether this pair's ``where`` restriction admits ``path``."""
        return all(path.get(level, "") in values for level, values in self.where.items())

    def as_json(self) -> dict[str, Any]:
        """The pair as it would be declared in the database."""
        declared: dict[str, Any] = {"setpoint": self.setpoint, "readback": self.readback}
        if self.where:
            declared["where"] = {level: sorted(values) for level, values in self.where.items()}
        return declared


@dataclass(frozen=True)
class ChannelGrammar:
    """The levels a database declares, and how its setpoints pair with readbacks.

    Attributes:
        levels: The declared hierarchy levels, in order.
        pairing_level: The level whose token distinguishes a setpoint from its
            readback.
        pairs: The declared token pairs, in declaration order.
        declared: Whether the database carried a ``pairing`` block of its own
            (``False`` when the pairs are the reference convention's default,
            or there are none).
    """

    levels: tuple[str, ...]
    pairing_level: str
    pairs: tuple[TokenPair, ...] = ()
    declared: bool = False

    @classmethod
    def from_hierarchy(
        cls, levels: Sequence[str], pairing: Mapping[str, Any] | None = None
    ) -> ChannelGrammar:
        """Build the grammar from a database's declared levels and ``pairing`` block.

        Args:
            levels: The ``hierarchy.levels`` names, in order.
            pairing: The ``hierarchy.pairing`` block, or ``None`` when the
                database declares none.

        Raises:
            GrammarError: if the block is not an object, names a level the
                database does not declare, or carries a malformed pair.
        """
        levels = tuple(levels)
        if not levels:
            raise GrammarError("a channel grammar needs at least one hierarchy level")
        if pairing is None:
            if BUILTIN_PAIRING_LEVEL in levels:
                return cls(
                    levels=levels,
                    pairing_level=BUILTIN_PAIRING_LEVEL,
                    pairs=(TokenPair(BUILTIN_SETPOINT_TOKEN, BUILTIN_READBACK_TOKEN),),
                )
            return cls(levels=levels, pairing_level=levels[-1])

        if not isinstance(pairing, Mapping):
            raise GrammarError("'hierarchy.pairing' must be an object with a 'pairs' list")
        unknown = set(pairing) - {"level", "pairs"}
        if unknown:
            raise GrammarError(
                f"'hierarchy.pairing' has unknown key(s) {sorted(unknown)}; "
                "it takes 'level' and 'pairs'"
            )
        pairing_level = pairing.get("level", levels[-1])
        if pairing_level not in levels:
            raise GrammarError(
                f"'hierarchy.pairing.level' names {pairing_level!r}, which is not a declared "
                f"hierarchy level {list(levels)}"
            )
        raw_pairs = pairing.get("pairs")
        if not isinstance(raw_pairs, list) or not raw_pairs:
            raise GrammarError("'hierarchy.pairing.pairs' must be a non-empty list of pairs")
        pairs = tuple(_parse_pair(index, raw, levels) for index, raw in enumerate(raw_pairs))
        return cls(levels=levels, pairing_level=pairing_level, pairs=pairs, declared=True)

    @property
    def is_builtin(self) -> bool:
        """Whether these are exactly the reference facility's six levels."""
        return self.levels == BUILTIN_LEVELS

    @property
    def identity_levels(self) -> tuple[str, ...]:
        """Every level but the pairing level: what the two halves of a pair share."""
        return tuple(level for level in self.levels if level != self.pairing_level)

    @property
    def qualifier_level(self) -> str | None:
        """The level just before the pairing level, or ``None`` at the top.

        The reference facility's ``field`` (``CURRENT``, ``STATUS``): the
        token that qualifies what the pairing-level token is a setpoint or
        readback *of*, which record-type derivation reads.
        """
        index = self.levels.index(self.pairing_level)
        return self.levels[index - 1] if index > 0 else None

    def identity(self, path: Mapping[str, str]) -> str:
        """The values of every level but the pairing level, as one string.

        What a device's channels share: the two halves of every pair on it,
        and every other channel of it too.
        """
        return PAIR_KEY_SEPARATOR.join(path.get(level, "") for level in self.identity_levels)

    def token(self, path: Mapping[str, str]) -> str:
        """The channel's pairing-level token."""
        return path.get(self.pairing_level, "")

    def pairing(self, path: Mapping[str, str]) -> Pairing | None:
        """The channel's place in a declared pair, or ``None`` when it is in none.

        The pair key is the channel's identity plus the pair's setpoint token,
        so each declared pair on one device has a key of its own.

        Raises:
            GrammarError: if more than one declared pair claims the token for
                this channel -- an ambiguity the database has to resolve with
                ``where``, never one guessed through here.
        """
        token = self.token(path)
        claims: list[Pairing] = []
        identity = self.identity(path)
        for pair in self.pairs:
            if not pair.applies_to(path):
                continue
            pair_key = identity + PAIR_KEY_SEPARATOR + pair.setpoint
            if token == pair.setpoint:
                claims.append(Pairing(ROLE_SETPOINT, pair_key, pair.readback))
            elif token == pair.readback:
                claims.append(Pairing(ROLE_READBACK, pair_key, pair.setpoint))
        if not claims:
            return None
        if len(claims) > 1:
            raise GrammarError(
                f"pairing token {token!r} at level {self.pairing_level!r} is claimed by "
                f"{len(claims)} declared pairs for path {dict(path)}; restrict them with 'where'"
            )
        return claims[0]

    def as_json(self) -> dict[str, Any]:
        """The grammar as manifest metadata."""
        return {
            "levels": list(self.levels),
            "pairing_level": self.pairing_level,
            "pairs": [pair.as_json() for pair in self.pairs],
            "pairing_declared": self.declared,
        }


#: The reference facility's grammar: six levels, ``SP``/``RB`` in ``subfield``.
BUILTIN_GRAMMAR = ChannelGrammar.from_hierarchy(BUILTIN_LEVELS)


def _parse_pair(index: int, raw: Any, levels: tuple[str, ...]) -> TokenPair:
    """Validate one entry of ``hierarchy.pairing.pairs``."""
    where_it_is = f"'hierarchy.pairing.pairs[{index}]'"
    if not isinstance(raw, Mapping):
        raise GrammarError(f"{where_it_is} must be an object with 'setpoint' and 'readback'")
    unknown = set(raw) - {"setpoint", "readback", "where"}
    if unknown:
        raise GrammarError(
            f"{where_it_is} has unknown key(s) {sorted(unknown)}; "
            "a pair takes 'setpoint', 'readback' and optionally 'where'"
        )
    tokens = {}
    for side in ("setpoint", "readback"):
        value = raw.get(side)
        if not isinstance(value, str) or not value:
            raise GrammarError(f"{where_it_is} needs a non-empty string {side!r}")
        tokens[side] = value
    if tokens["setpoint"] == tokens["readback"]:
        raise GrammarError(
            f"{where_it_is} names the same token {tokens['setpoint']!r} as setpoint and readback"
        )
    where: dict[str, frozenset[str]] = {}
    raw_where = raw.get("where", {})
    if not isinstance(raw_where, Mapping):
        raise GrammarError(f"{where_it_is}.where must be an object mapping a level to values")
    for level, values in raw_where.items():
        if level not in levels:
            raise GrammarError(
                f"{where_it_is}.where names {level!r}, which is not a declared "
                f"hierarchy level {list(levels)}"
            )
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(v, str) for v in values)
        ):
            raise GrammarError(
                f"{where_it_is}.where[{level!r}] must be a non-empty list of strings"
            )
        where[level] = frozenset(values)
    return TokenPair(setpoint=tokens["setpoint"], readback=tokens["readback"], where=where)


__all__ = [
    "BUILTIN_GRAMMAR",
    "BUILTIN_LEVELS",
    "BUILTIN_PAIRING_LEVEL",
    "BUILTIN_READBACK_TOKEN",
    "BUILTIN_SETPOINT_TOKEN",
    "ChannelGrammar",
    "GrammarError",
    "PAIR_KEY_SEPARATOR",
    "Pairing",
    "ROLE_NONE",
    "ROLE_READBACK",
    "ROLE_SETPOINT",
    "ROLES",
    "TokenPair",
]
