"""IC box-symbol generator in the house style.

House conventions (``docs/entwicklung/recherche/user-lib-style.md`` §3.2/§8):

* one rectangle, top-left corner at the origin, growing to +x/-y (Altium default colours,
  line width "smallest"); pins 200 mil long on a fixed 100 mil pitch (independent of the
  snap grid); first row 100 mil below the top edge, last row 100 mil above the bottom edge;
  names and numbers shown;
* supplies first on the left, then inputs/control; outputs and regulator feedback/control
  pins (FB, COMP, SS, RT, PG, ...) on the right; switch nodes (SW, BST, LX) on the top edge;
  grounds, NC and exposed pads on the bottom edge; bidirectional/passive pins by name,
  otherwise balanced between left and right. Regulator pin names win over the electrical
  type (the datasheet import often types FB or BST as "input"); ambiguous short names
  (SS, RT, BOOT, CB, ...) only do so when the IC has regulator pins (SW, LX, BST, FB, COMP);
* function groups separated by one empty row; natural ordering inside a group;
* active-low names keep Altium's overbar syntax verbatim (``R\\E\\S\\E\\T\\``).

Body width follows the longest pin names (estimated glyph widths of the house font) and is
rounded up to 100 mil; top/bottom pins are placed between the left and right name columns
or below/above them, whichever gives the smaller body.

Large ICs can be split into parts (``parts="auto"`` or a part count): signal pins are
re-balanced and packed per side, supplies/grounds/exposed pads go to their own power
part(s) with the same per-side capacity. Every automatically split part gets its own body
size; user-defined multi-part symbols (``IcPin.part``) keep one body size for all parts.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ..geometry.model import SymbolSpec, SymPin
from ..workspace import SymbolStyle
from .builder import SymbolBuilder
from .errors import SymbolError
from .models import IcPin
from .style import StyleKit
from .text import display_text
from .util import MAX_PART_COUNT, check_name, check_prefix, natural_key

log = logging.getLogger(__name__)

__all__ = [
    "MAX_PINS_PER_SIDE",
    "PIN_PITCH",
    "ROLE_LABELS",
    "IcLayout",
    "Role",
    "auto_assign_sides",
    "build_ic",
    "classify_pin",
    "ic_default_name",
    "ic_symbol",
    "is_regulator",
]

Side = Literal["left", "right", "top", "bottom"]
Role = Literal["supply", "ground", "switch", "nc", "ep", "input", "output", "free"]
Order = Literal["name", "designator", "input"]

SIDES: tuple[Side, ...] = ("left", "right", "top", "bottom")
MAX_PINS_PER_SIDE = 40


def ic_default_name(pin_count: int) -> str:
    """Name of an IC symbol without an explicit name (``IC 8-Pin``)."""
    return f"IC {int(pin_count)}-Pin"

PIN_PITCH = 100  # mil between neighbouring pins (house: 10 units), whatever the snap grid
NAME_MARGIN = 50  # pin name starts this far inside the body edge
NAME_GAP = 100  # minimum gap between left and right name columns
MIN_BODY_WIDTH = 400
MAX_PINS = 2000

ROLE_SIDE: dict[Role, Side] = {
    "supply": "left",
    "input": "left",
    "output": "right",
    "switch": "top",
    "ground": "bottom",
    "nc": "bottom",
    "ep": "bottom",
}
ROLE_LABELS: dict[Role, str] = {
    "supply": "Versorgung",
    "ground": "Masse",
    "switch": "Schaltknoten",
    "nc": "Nicht verbunden",
    "ep": "Thermal-Pad",
    "input": "Eingänge",
    "output": "Ausgänge",
    "free": "Signale",
}
_POWER_ROLES: frozenset[str] = frozenset({"supply", "ground", "ep"})
# block order on a side: supplies first, explicit groups next, grounds/NC/EP last
_ROLE_RANK: dict[Role, int] = {
    "supply": 0,
    "input": 2,
    "free": 3,
    "output": 4,
    "switch": 5,
    "ground": 6,
    "nc": 7,
    "ep": 8,
}
_GROUP_RANK = 1
# order of roles inside an explicit group: supplies first, grounds last
_IN_GROUP_RANK: dict[Role, int] = {
    "supply": 0,
    "input": 1,
    "free": 1,
    "output": 1,
    "switch": 1,
    "ground": 2,
    "nc": 3,
    "ep": 4,
}

# ---------------------------------------------------------------------------------- names
_LO_PRE = r"(?:[/~!#]|N_?)?"
_LO_POST = r"(?:_?N|_?B|#|\*)?"
_NC_RE = re.compile(r"^(?:NC|N\.C\.?|N/C|DNC|NU|N\.U\.?|RSVD|RESERVED|NOCONNECT|NOTCONNECTED|DONOTCONNECT)\d*$")
_GROUND_RE = re.compile(
    r"^(?:(?:[ADPSCRLE]|IO|PLL|USB|RF|PWR|SIG|CORE)?(?:GND|VSS|VEE|GROUND)[A-Z0-9_\-]*"
    r"|0V|V-|-V|VS-|-VS|VCC-|VNEG|V_NEG|NEG)$"
)
_EP_RE = re.compile(r"^(?:EP|EPAD|E-PAD|E\.P\.|PAD|EXPOSEDPAD|THERMALPAD|THERMAL|HS|HEATSINK|TAB|SLUG)\d*$")
_SUPPLY_RE = re.compile(
    r"^(?:[A-Z]{0,4}V(?:DD|CC)[A-Z0-9_]*"
    r"|[AP]?VIN\d*"
    r"|V(?:BAT|BATT|BUS|SUP|SUPPLY|SYS|PP|PWR|BB|M|MOT|LED|S|CHG|CHRG|DRV|IO)\d*"
    r"|V\+|\+V|VS\+|\+VS|VCC\+"
    r"|\+\d+V\d*"
    r"|BATT?\+?)$"
)
# switch nodes: always on the top edge, whatever the electrical type
_SWITCH_STRONG_RE = re.compile(r"^(?:SW\d*|LX\d*|SW[NPABX]|BST\d*|VBST|BTST|CBOOT|VBOOT)$")
# short/ambiguous switch names: top edge unless typed "input" outside a regulator (BOOT on an
# MCU module, CB, PH ...); numbered BOOT0/BOOT1 are MCU boot pins unless the IC is a regulator
_SWITCH_WEAK_RE = re.compile(r"^(?:BOOT|BOOST|BS|CB|PH\d*)$")
_SWITCH_CONTEXT_RE = re.compile(r"^(?:BOOT\d+|BS\d+|CB\d+)$")
# regulator feedback/control pins: right side (house: "outputs, FB, SW"), also when typed "input"
_RIGHT_STRONG_RE = re.compile(r"^(?:V?FB\d*|FB[+-]|COMP\d*)$")
# ... and these only on ICs with regulator pins (SS = SPI slave select elsewhere, RT, PG ...)
_RIGHT_CONTEXT_RE = re.compile(
    r"^(?:SS\d*|TRK|SS/TRK|TRK/SS|SS/TR|TR/SS|RT|RT/SYNC|RT/CLK|ILIM\d*|ISET|IMON|VOS|PG|PGOOD|PWRGD|POK|PGD)$"
)
# pin names that only occur on switching/linear regulators
_REGULATOR_RE = re.compile(r"^(?:SW\d*|LX\d*|BST\d*|VBST|V?FB\d*|COMP)$")
_OUTPUT_RE = re.compile(
    rf"^{_LO_PRE}(?:[ADV]?OUT[A-Z0-9_+\-]*|SDO|DOUT\d*|MISO|CIPO|SO|TXD?\d*|TXO|INT\d*|IRQ\d*|ALERT|ALRT|"
    r"FAULT|FLT|ERR|ERROR|PG|PGOOD|PWRGD|POK|PGD|RDY|READY|BUSY|DRDY|DONE|CLKOUT|CLKO|OSCOUT|OSC2|XOUT|"
    r"XTAL2|XO|TDO|SWO|Q\d*|Q[A-H]|LED\d*|BUZ|PWM\d*|STAT\d*|CHG|CHRG|STDBY|FB\d*|VFB|COMP|ILIM|ISET|IMON|"
    rf"ISNS|SNS\d*|SS|TRK|SS/TRK|RT|REFOUT|VREFOUT|BYP|BYPASS|VCAP|VREG|VLDO|CAP){_LO_POST}$"
)
_INPUT_RE = re.compile(
    rf"^{_LO_PRE}(?:[AV]?IN[A-Z0-9_+\-]*|AIN\d*|DIN\d*|SDI|SI|MOSI|COPI|RXD?\d*|RXI|SCL|SCLK|SCK|SPCK|"
    r"CLK\d*|CLKIN|CLKI|XIN|XI|XTAL1|OSC1|OSCIN|EN\d*|ENA|ENB|ENABLE|CE|CS\d*|CSN|NSS|RESET|RST|NRST|MR|"
    r"SHDN|SDN|SD|SLEEP|SLP|STBY|STANDBY|MODE\d*|SEL\d*|S\d|A\d+|ADDR\d*|AD\d|SYNC|TRIG|THR|THRESH|CV|SET|"
    rf"CTRL\d*|CTL|ON|OFF|ON/OFF|ONOFF|UVLO|INH|INHIBIT|DIR|STEP|PWMIN|SDA|WP|HOLD|LE|OE|LATCH|LOAD|LD|"
    rf"START|STOP|TEST|TCK|TMS|TDI|TRST|SWCLK|SWDIO|NMI|WAKE|WKUP|WAKEUP|PROG|PGM|ADJ|RSET|VSET|FREQ|MS){_LO_POST}$"
)
_BUS_RE = re.compile(r"^(.*?[A-Za-z_./\-])(\d+)$")


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", display_text(name)).upper()


def is_regulator(pins: Iterable[IcPin]) -> bool:
    """True when the pin list has regulator-only pins (SW, LX, BST, FB, VFB, COMP)."""
    return any(_REGULATOR_RE.match(_norm(p.name)) for p in pins)


def classify_pin(pin: IcPin, *, regulator: bool = False) -> Role:
    """Functional role of a pin from its name and electrical type (house conventions).

    ``regulator`` (see :func:`is_regulator`) lets ambiguous regulator names (SS, RT, PG,
    BOOT, CB ...) win over the electrical type ``input``.
    """
    n = _norm(pin.name)
    el = pin.electrical
    if _NC_RE.match(n):
        return "nc"
    if _GROUND_RE.match(n):
        return "ground"
    if _EP_RE.match(n):
        return "ep"
    if _SUPPLY_RE.match(n):
        return "supply"
    if (
        _SWITCH_STRONG_RE.match(n)
        or (_SWITCH_WEAK_RE.match(n) and (el != "input" or regulator))
        or (regulator and _SWITCH_CONTEXT_RE.match(n))
    ):
        return "switch"
    if _RIGHT_STRONG_RE.match(n) or (regulator and _RIGHT_CONTEXT_RE.match(n)):
        return "output"
    if el == "input":
        return "input"
    if el == "power":
        return "output" if _OUTPUT_RE.match(n) else "supply"
    if el in ("output", "open_collector", "open_emitter", "hiz"):
        return "output"
    if _OUTPUT_RE.match(n):
        return "output"
    if _INPUT_RE.match(n):
        return "input"
    return "free"


def _bus_prefix(name: str) -> str | None:
    m = _BUS_RE.match(display_text(name).strip())
    return m.group(1).upper() if m else None


def _majority(sides: Iterable[str]) -> Side | None:
    counts = Counter(sides)
    if not counts:
        return None
    best = max(counts.values())
    return next(s for s in SIDES if counts.get(s) == best)


def auto_assign_sides(pins: Sequence[IcPin], *, regulator: bool | None = None) -> list[IcPin]:
    """Return copies of ``pins`` with every missing ``side`` filled in (explicit sides are kept).

    Pins of one explicit ``group`` end up on one side (explicit sides of group members win,
    otherwise the majority of the members' roles). Pins without a clear role (bidirectional
    or passive with unknown names) are balanced between left and right; buses such as
    ``PA0..PA15`` stay together unless they have to be cut to balance the sides.
    ``regulator=None`` detects the regulator context from ``pins`` (:func:`is_regulator`).
    """
    items = [p.model_copy() for p in pins]
    context = is_regulator(items) if regulator is None else regulator
    roles = [classify_pin(p, regulator=context) for p in items]
    sides: list[Side | None] = [p.side for p in items]
    units: list[tuple[list[int], bool]] = []  # (pin indices, may be split)

    def name_key(i: int) -> tuple[Any, ...]:
        return natural_key(display_text(items[i].name)), natural_key(items[i].designator)

    groups: dict[str, list[int]] = {}
    for i, p in enumerate(items):
        if p.group:
            groups.setdefault(p.group, []).append(i)
    grouped: set[int] = set()
    for idxs in groups.values():
        explicit = [s for i in idxs if (s := sides[i]) is not None]
        side = (
            _majority(explicit)
            if explicit
            else _majority(s for i in idxs if (s := ROLE_SIDE.get(roles[i])) is not None)
        )
        pending = [i for i in idxs if sides[i] is None]
        grouped.update(idxs)
        if side is None:
            if pending:
                units.append((pending, False))  # explicit groups are never split
            continue
        for i in pending:
            sides[i] = side

    free: list[int] = []
    for i in range(len(items)):
        if i in grouped or sides[i] is not None:
            continue
        role_side = ROLE_SIDE.get(roles[i])
        if role_side is not None:
            sides[i] = role_side
        elif items[i].hidden:
            sides[i] = "left"  # hidden pins take no space
        else:
            free.append(i)

    buses: dict[str, list[int]] = {}
    for i in free:
        prefix = _bus_prefix(items[i].name)
        buses.setdefault(prefix if prefix else f"#{i}", []).append(i)
    for idxs in buses.values():
        units.append((sorted(idxs, key=name_key), True))

    def visible(idxs: Iterable[int]) -> int:
        return sum(1 for i in idxs if not items[i].hidden)

    counts = {
        "left": visible(i for i, s in enumerate(sides) if s == "left"),
        "right": visible(i for i, s in enumerate(sides) if s == "right"),
    }
    # balance: fill the shorter side up to half of all left/right pins; a bus is only cut
    # where it would overflow that target (explicit groups stay whole)
    target = math.ceil((counts["left"] + counts["right"] + sum(visible(u) for u, _ in units)) / 2)
    for unit, splittable in sorted(units, key=lambda u: min(name_key(i) for i in u[0])):
        short: Side = "left" if counts["left"] <= counts["right"] else "right"
        other: Side = "right" if short == "left" else "left"
        room = target - counts[short]
        head, tail = (unit[:room], unit[room:]) if splittable and 0 < room < len(unit) else (unit, [])
        for i in head:
            sides[i] = short
        for i in tail:
            sides[i] = other
        counts[short] += visible(head)
        counts[other] += visible(tail)

    return [p.model_copy(update={"side": s}) for p, s in zip(items, sides, strict=True)]


# ---------------------------------------------------------------------------------- blocks
@dataclass
class _Block:
    key: tuple[Any, ...]
    rank: tuple[Any, ...]
    pins: list[IcPin] = field(default_factory=list)
    label: str = ""


def _pin_sort_key(pin: IcPin, role: Role, index: int, order: Order, in_group: bool) -> tuple[Any, ...]:
    head: tuple[Any, ...] = (_IN_GROUP_RANK[role],) if in_group else ()
    if order == "designator":
        return (*head, natural_key(pin.designator), index)
    if order == "input":
        return (*head, index)
    return (*head, natural_key(display_text(pin.name)), natural_key(pin.designator), index)


def _make_blocks(
    pins: Sequence[IcPin],
    index: dict[int, int],
    roles: dict[int, Role],
    order: Order,
    side_of: Mapping[int, Side] | None = None,
) -> dict[Side, list[_Block]]:
    """Split the pins of one side set into ordered blocks (explicit groups / role blocks / buses).

    ``side_of`` overrides the side of individual pins (keyed by ``id(pin)``).
    """
    by_side: dict[Side, list[IcPin]] = {s: [] for s in SIDES}
    for p in pins:
        side = side_of.get(id(p), p.side) if side_of is not None else p.side
        assert side is not None
        by_side[side].append(p)

    out: dict[Side, list[_Block]] = {}
    for side, side_pins in by_side.items():
        blocks: dict[tuple[Any, ...], _Block] = {}
        # bus prefixes that occur at least twice within one role on this side
        prefix_count: Counter[tuple[Role, str]] = Counter()
        for p in side_pins:
            role = roles[id(p)]
            if not p.group and role in ("input", "output", "free"):
                prefix = _bus_prefix(p.name)
                if prefix:
                    prefix_count[(role, prefix)] += 1
        for p in side_pins:
            role = roles[id(p)]
            if p.group:
                key: tuple[Any, ...] = ("g", p.group)
                rank: tuple[Any, ...] = (_GROUP_RANK, index[id(p)], ())
                label = p.group
            else:
                prefix = _bus_prefix(p.name) if role in ("input", "output", "free") else None
                if prefix and prefix_count[(role, prefix)] >= 2:
                    key = ("r", role, prefix)
                    rank = (_ROLE_RANK[role], 1, natural_key(prefix))
                else:
                    key = ("r", role, "")
                    rank = (_ROLE_RANK[role], 0, ())
                label = ROLE_LABELS[role]
            block = blocks.get(key)
            if block is None:
                block = blocks[key] = _Block(key=key, rank=rank, label=label)
            else:  # explicit groups: rank by first appearance
                block.rank = min(block.rank, rank)
            block.pins.append(p)
        ordered = sorted(blocks.values(), key=lambda b: b.rank)
        for block in ordered:
            in_group = block.key[0] == "g"
            block.pins.sort(key=lambda p: _pin_sort_key(p, roles[id(p)], index[id(p)], order, in_group))
        out[side] = ordered
    return out


def _rows(blocks: Sequence[_Block]) -> int:
    if not blocks:
        return 0
    return sum(len(b.pins) for b in blocks) + len(blocks) - 1


def _side_sequence(blocks: Sequence[_Block]) -> list[IcPin | None]:
    """Pins of a side in order, ``None`` = empty gap row between blocks."""
    seq: list[IcPin | None] = []
    for i, block in enumerate(blocks):
        if i:
            seq.append(None)
        seq.extend(block.pins)
    return seq


# ---------------------------------------------------------------------------------- split
def _chunk_blocks(blocks: Sequence[_Block], capacity: int) -> list[list[list[IcPin]]]:
    """Pack blocks into chunks of at most ``capacity`` rows (gap rows count); big blocks are cut."""
    chunks: list[list[list[IcPin]]] = []
    current: list[list[IcPin]] = []
    used = 0
    for block in blocks:
        pieces = [block.pins[i : i + capacity] for i in range(0, len(block.pins), capacity)]
        for piece in pieces:
            need = len(piece) + (1 if current else 0)
            if current and used + need > capacity:
                chunks.append(current)
                current, used, need = [], 0, len(piece)
            current.append(list(piece))
            used += need
    if current:
        chunks.append(current)
    return chunks


def _split_even(items: Sequence[IcPin], n: int) -> list[list[IcPin]]:
    """``n`` contiguous chunks whose sizes differ by at most one (order kept)."""
    base, extra = divmod(len(items), n)
    out: list[list[IcPin]] = []
    pos = 0
    for k in range(n):
        size = base + (1 if k < extra else 0)
        out.append(list(items[pos : pos + size]))
        pos += size
    return out


@dataclass(frozen=True)
class _SplitPlan:
    part_of: dict[int, int]  # id(pin) -> part
    side_of: dict[int, Side]  # id(pin) -> side within its part
    count: int


@dataclass(frozen=True)
class _SplitInput:
    """Pins of :func:`build_ic` prepared for splitting (keyed by ``id`` of the work copies)."""

    pins: Sequence[IcPin]  # work copies, sides filled
    explicit: dict[int, Side | None]  # id(pin) -> side given by the user (None = automatic)
    originals: dict[int, IcPin]  # id(pin) -> the user's pin (for re-balancing)
    roles: dict[int, Role]
    index: dict[int, int]
    order: Order
    regulator: bool


def _plan_power(inp: _SplitInput, power: Sequence[IcPin], capacity: int) -> tuple[list[list[IcPin]], dict[int, Side]]:
    """Supplies, grounds and exposed pads on as few power parts as possible.

    Home sides: supplies left, grounds/EP bottom (explicit sides of the user are kept). Every
    pool is spread evenly over the parts; whatever exceeds ``capacity`` rows on its home side
    moves to the right side of the same part. The part count grows until every side fits.
    """
    roles, index = inp.roles, inp.index

    def home(p: IcPin) -> Side:
        explicit = inp.explicit.get(id(p))
        if explicit is not None:
            return explicit
        return "left" if roles[id(p)] == "supply" else "bottom"

    def sort_key(p: IcPin) -> tuple[Any, ...]:
        role = roles[id(p)]
        return (_ROLE_RANK[role], *_pin_sort_key(p, role, index[id(p)], inp.order, False))

    pools: dict[Side, list[IcPin]] = {s: [] for s in SIDES}
    for p in power:
        pools[home(p)].append(p)
    for members in pools.values():
        members.sort(key=sort_key)
    largest = max((len(m) for m in pools.values()), default=0)
    if not largest:
        return [], {}

    for n in range(1, largest + 1):
        parts: list[list[IcPin]] = [[] for _ in range(n)]
        sides: dict[int, Side] = {}
        for side, members in pools.items():
            for k, chunk in enumerate(_split_even(members, n)):
                parts[k].extend(chunk)
                for p in chunk:
                    sides[id(p)] = side
        feasible = True
        for members in parts:
            blocks = _make_blocks(members, index, roles, inp.order, sides)
            for side in ("left", "bottom", "top"):
                sequence = _side_sequence(blocks[side])
                for p in sequence[capacity:]:
                    if p is not None:
                        sides[id(p)] = "right"  # overflow to the right side of the same part
            blocks = _make_blocks(members, index, roles, inp.order, sides)
            if any(_rows(blocks[s]) > capacity for s in SIDES):
                feasible = False
                break
        if feasible:
            return [p for p in parts if p], sides
    raise AssertionError("unreachable: one pin per part always fits")  # pragma: no cover


def _plan_split(inp: _SplitInput, capacity: int) -> _SplitPlan:
    """Signal pins packed per side into parts of ``capacity`` rows; supplies/grounds/EP in power part(s).

    The signal pins are re-balanced between left and right without the power pins, so the
    parts are filled on both sides; the power parts follow the signal parts.
    """
    pins, roles, index = inp.pins, inp.roles, inp.index
    visible = [p for p in pins if not p.hidden]
    power = [p for p in visible if roles[id(p)] in _POWER_ROLES]
    signal = [p for p in visible if roles[id(p)] not in _POWER_ROLES]
    use_power_parts = len(power) >= 2 and bool(signal)
    side_of: dict[int, Side] = {}
    for p in pins:
        assert p.side is not None
        side_of[id(p)] = p.side
    if use_power_parts:
        rebalanced = auto_assign_sides([inp.originals[id(p)] for p in signal], regulator=inp.regulator)
        for p, q in zip(signal, rebalanced, strict=True):
            assert q.side is not None
            side_of[id(p)] = q.side
    blocks = _make_blocks(signal if use_power_parts else visible, index, roles, inp.order, side_of)
    part_of: dict[int, int] = {}
    n_signal = 1
    for side in SIDES:
        chunks = _chunk_blocks(blocks[side], capacity)
        n_signal = max(n_signal, len(chunks))
        for k, chunk in enumerate(chunks, start=1):
            for piece in chunk:
                for p in piece:
                    part_of[id(p)] = k
    count = n_signal
    if use_power_parts:
        power_parts, power_sides = _plan_power(inp, power, capacity)
        side_of.update(power_sides)
        for k, members in enumerate(power_parts, start=n_signal + 1):
            for p in members:
                part_of[id(p)] = k
        count += len(power_parts)
        for p in pins:  # hidden supplies join the first power part
            if p.hidden and roles[id(p)] in _POWER_ROLES:
                part_of[id(p)] = n_signal + 1
    for p in pins:
        part_of.setdefault(id(p), 1)  # hidden signal pins stay in part 1
    return _SplitPlan(part_of, side_of, count)


def _apply_split(pins: Sequence[IcPin], plan: _SplitPlan) -> list[IcPin]:
    return [p.model_copy(update={"part": plan.part_of[id(p)], "side": plan.side_of[id(p)]}) for p in pins]


def _choose_capacity(inp: _SplitInput, target: int) -> _SplitPlan:
    """Smallest per-side capacity whose split needs at most ``target`` parts (binary search)."""
    blocks = _make_blocks([p for p in inp.pins if not p.hidden], inp.index, inp.roles, inp.order)
    hi = max(max((_rows(b) for b in blocks.values()), default=1), 1)
    lo = 1
    best = _plan_split(inp, hi)
    while lo < hi:
        mid = (lo + hi) // 2
        plan = _plan_split(inp, mid)
        if plan.count <= target:
            best, hi = plan, mid
        else:
            lo = mid + 1
    return best if best.count <= target else _plan_split(inp, hi)


# ---------------------------------------------------------------------------------- layout
@dataclass(frozen=True)
class _Geometry:
    width: int
    height: int
    top_margin: int
    x0: int  # first top/bottom pin position


def _ceil_pitch(value: float) -> int:
    return math.ceil(round(value, 6) / PIN_PITCH) * PIN_PITCH


def _floor_pitch(value: float) -> int:
    return math.floor(round(value, 6) / PIN_PITCH) * PIN_PITCH


def _geometry(
    kit: StyleKit,
    *,
    w_left: float,
    w_right: float,
    w_top: float,
    w_bottom: float,
    has_left: bool,
    has_right: bool,
    n_top: int,
    n_bottom: int,
    rows: int,
) -> _Geometry:
    g = PIN_PITCH
    nm = NAME_MARGIN
    clearance = kit.cap_height / 2 + 20
    if has_left or has_right:
        content = (nm + w_left if has_left else 0) + (nm + w_right if has_right else 0)
        content += NAME_GAP if (has_left and has_right) else nm
    else:
        content = 0
    base_w = max(MIN_BODY_WIDTH, _ceil_pitch(content))
    rows = max(rows, 1)
    side_h = (rows + 1) * g
    n_tb = max(n_top, n_bottom)
    if not n_tb:
        return _Geometry(base_w, side_h, g, 0)

    # option A: top/bottom pins between the left and right name columns
    def zone(width: int) -> tuple[int, int]:
        xl = nm + w_left + clearance if has_left else g
        xr = width - nm - w_right - clearance if has_right else width - g
        return _ceil_pitch(xl), _floor_pitch(xr)

    w_a = max(base_w, (n_tb + 1) * g)
    while True:
        first, last = zone(w_a)
        if last >= first and (last - first) // g + 1 >= n_tb:
            break
        w_a += g
    slots = (last - first) // g + 1
    x0_a = first + ((slots - n_tb) // 2) * g
    # vertical names of top and bottom pins must fit above each other
    name_h = (nm + w_top + NAME_GAP + w_bottom + nm) if (n_top and n_bottom) else (nm + (w_top or w_bottom) + nm)
    h_a = max(side_h, _ceil_pitch(name_h))
    option_a = _Geometry(w_a, h_a, g, x0_a)

    # option B: rows start below the top names / end above the bottom names
    w_b = max(base_w, (n_tb + 1) * g)
    top_m = _ceil_pitch(nm + w_top + clearance) if n_top else g
    bot_m = _ceil_pitch(nm + w_bottom + clearance) if n_bottom else g
    h_b = max(top_m + (rows - 1) * g + bot_m, _ceil_pitch(name_h))
    x0_b = _floor_pitch((w_b - (n_tb - 1) * g) / 2)
    option_b = _Geometry(w_b, h_b, top_m, x0_b)

    return option_a if option_a.width * option_a.height <= option_b.width * option_b.height else option_b


@dataclass(frozen=True)
class _PartPlan:
    part: int
    blocks: dict[Side, list[_Block]]


def _plans_geometry(kit: StyleKit, plans: Sequence[_PartPlan]) -> _Geometry:
    """One body geometry that holds every part in ``plans``."""
    members = [p for pl in plans for side in SIDES for block in pl.blocks[side] for p in block.pins]

    def widths(side: Side) -> float:
        return max((kit.text_width(p.name) for p in members if p.side == side), default=0.0)

    has = {s: any(p.side == s for p in members) for s in SIDES}
    rows = max((max(_rows(pl.blocks["left"]), _rows(pl.blocks["right"])) for pl in plans), default=1)
    return _geometry(
        kit,
        w_left=widths("left"),
        w_right=widths("right"),
        w_top=widths("top"),
        w_bottom=widths("bottom"),
        has_left=has["left"],
        has_right=has["right"],
        n_top=max((_rows(pl.blocks["top"]) for pl in plans), default=0),
        n_bottom=max((_rows(pl.blocks["bottom"]) for pl in plans), default=0),
        rows=rows,
    )


@dataclass(frozen=True)
class _Layout:
    pins: list[SymPin]
    geometries: list[_Geometry]  # per part (index 0 = part 1)
    has_top: bool
    has_bottom: bool

    @property
    def part_count(self) -> int:
        return len(self.geometries)


def _layout(
    kit: StyleKit,
    pins: list[IcPin],
    roles: dict[int, Role],
    index: dict[int, int],
    order: Order,
    *,
    uniform: bool,
) -> _Layout:
    """Place all pins; ``uniform`` = one body size for every part (user-defined or shared pins)."""
    part_count = max((p.part for p in pins), default=1) or 1
    visible = [p for p in pins if not p.hidden]
    shared = [p for p in visible if p.part == 0]
    shared_blocks = _make_blocks(shared, index, roles, order)
    plans: list[_PartPlan] = []
    for part in range(1, part_count + 1):
        own = _make_blocks([p for p in visible if p.part == part], index, roles, order)
        plans.append(_PartPlan(part, {s: shared_blocks[s] + own[s] for s in SIDES}))

    if uniform or shared:
        common = _plans_geometry(kit, plans)
        geometries = [common] * part_count
    else:
        geometries = [_plans_geometry(kit, [pl]) for pl in plans]

    g = PIN_PITCH
    length = kit.ic_pin_length
    placed: dict[int, SymPin] = {}
    block_label: dict[int, str] = {}
    for pl in plans:
        for side in SIDES:
            for block in pl.blocks[side]:
                for p in block.pins:
                    block_label[id(p)] = block.label

    def make(p: IcPin, x: int, y: int, orientation: str) -> SymPin:
        return SymPin(
            designator=p.designator,
            name=p.name,
            x=x,
            y=y,
            orientation=orientation,  # type: ignore[arg-type]
            length=length,
            electrical=p.electrical,
            part=p.part,
            show_name=True,
            show_designator=True,
            hidden=p.hidden,
            description=p.description,
            group=block_label.get(id(p)) or p.group or ROLE_LABELS[roles[id(p)]],
        )

    for pl, geo in zip(plans, geometries, strict=True):
        for side in SIDES:
            for k, item in enumerate(_side_sequence(pl.blocks[side])):
                if item is None or id(item) in placed:
                    continue  # gap row, or a shared pin already placed by an earlier part
                if side == "left":
                    placed[id(item)] = make(item, 0, -(geo.top_margin + k * g), "left")
                elif side == "right":
                    placed[id(item)] = make(item, geo.width, -(geo.top_margin + k * g), "right")
                elif side == "top":
                    placed[id(item)] = make(item, geo.x0 + k * g, 0, "up")
                else:
                    placed[id(item)] = make(item, geo.x0 + k * g, -geo.height, "down")
    out: list[SymPin] = []
    for p in pins:
        if p.hidden:
            out.append(make(p, 0, 0, "left"))
        else:
            out.append(placed[id(p)])
    return _Layout(
        pins=out,
        geometries=geometries,
        has_top=any(pl.blocks["top"] for pl in plans),
        has_bottom=any(pl.blocks["bottom"] for pl in plans),
    )


# ---------------------------------------------------------------------------------- public
def _validate_pins(pins: Sequence[IcPin]) -> None:
    if not pins:
        raise SymbolError("Für ein IC-Symbol werden Pins benötigt.")
    if len(pins) > MAX_PINS:
        raise SymbolError(f"Zu viele Pins ({len(pins)}); höchstens {MAX_PINS} sind möglich.")
    seen: set[str] = set()
    for p in pins:
        des = (p.designator or "").strip()
        if not des:
            raise SymbolError(f"Pin {p.name!r} hat keine Pin-Nummer.")
        if des != p.designator:
            raise SymbolError(f"Pin-Nummer {p.designator!r} darf keine Leerzeichen am Anfang oder Ende haben.")
        if des in seen:
            raise SymbolError(f"Pin-Nummer {des} ist doppelt vergeben.")
        seen.add(des)
        if p.part < 0:
            raise SymbolError(f"Pin {des}: Teil {p.part} ist ungültig (0 = alle Teile, 1, 2, …).")


@dataclass(frozen=True)
class IcLayout:
    """Body geometry handed to a ``decorate`` callback of :func:`build_ic` (part 1)."""

    width: int
    height: int
    part_count: int


def build_ic(
    kit: StyleKit,
    name: str,
    pins: Sequence[IcPin],
    *,
    parts: int | Literal["auto"] | None = None,
    description: str = "",
    designator_prefix: str = "U",
    order: Order = "name",
    max_pins_per_side: int = MAX_PINS_PER_SIDE,
    generator: dict[str, Any] | None = None,
    decorate: Callable[[SymbolBuilder, IcLayout], None] | None = None,
) -> SymbolSpec:
    """Generate an IC box symbol with an already sanitised style (see :func:`ic_symbol`).

    ``decorate`` may add extra graphics once the body size is known (e.g. the wave glyph
    of the oscillator symbol).
    """
    check_name(name)
    check_prefix(designator_prefix)
    _validate_pins(pins)
    if order not in ("name", "designator", "input"):
        raise SymbolError(f"Unbekannte Sortierung {order!r} (name, designator oder input).")
    if not 4 <= int(max_pins_per_side) <= 500:
        raise SymbolError("Pins je Seite muss zwischen 4 und 500 liegen.")
    if isinstance(parts, bool) or (isinstance(parts, str) and parts != "auto"):
        raise SymbolError(f"Ungültige Teileangabe {parts!r} (Zahl oder 'auto').")

    regulator = is_regulator(pins)
    work = auto_assign_sides(pins, regulator=regulator)
    user_parts = any(p.part != 1 for p in work)
    if isinstance(parts, int):
        if parts < 1 or parts > MAX_PART_COUNT:
            raise SymbolError(f"Die Teileanzahl muss zwischen 1 und {MAX_PART_COUNT} liegen.")
        if user_parts and parts != 1:
            raise SymbolError(
                "Die Pins sind bereits Teilen zugeordnet; die Teileanzahl kann nicht zusätzlich gesetzt werden."
            )

    index = {id(p): i for i, p in enumerate(work)}
    roles = {id(p): classify_pin(p, regulator=regulator) for p in work}
    if not user_parts and parts is not None and parts != 1:
        inp = _SplitInput(
            pins=work,
            explicit={id(w): orig.side for w, orig in zip(work, pins, strict=True)},
            originals={id(w): orig for w, orig in zip(work, pins, strict=True)},
            roles=roles,
            index=index,
            order=order,
            regulator=regulator,
        )
        plan: _SplitPlan | None = None
        if parts == "auto":
            blocks = _make_blocks([p for p in work if not p.hidden], index, roles, order)
            if any(_rows(blocks[s]) > max_pins_per_side for s in SIDES):
                plan = _plan_split(inp, int(max_pins_per_side))
        else:
            plan = _choose_capacity(inp, int(parts))
        if plan is not None:
            work = _apply_split(work, plan)
            index = {id(p): i for i, p in enumerate(work)}
            roles = {id(p): classify_pin(p, regulator=regulator) for p in work}

    part_count = max((p.part for p in work), default=1) or 1
    if part_count > MAX_PART_COUNT:
        raise SymbolError(f"Zu viele Teile ({part_count}); höchstens {MAX_PART_COUNT} sind möglich.")
    has_shared = any(p.part == 0 for p in work)
    for part in range(1, part_count + 1):
        if not has_shared and not any(p.part == part for p in work):
            raise SymbolError(f"Teil {part} hat keine Pins. Bitte die Teile lückenlos ab 1 nummerieren.")

    layout = _layout(kit, work, roles, index, order, uniform=user_parts)
    part_count = layout.part_count
    b = SymbolBuilder(kit, part_count=part_count, graphic=kit.ic_body)
    for part, geo in enumerate(layout.geometries, start=1):
        b.rect(0, -geo.height, geo.width, 0, part=part, filled=True)
    b.pins = layout.pins
    first = layout.geometries[0]
    if decorate is not None:
        decorate(b, IcLayout(first.width, first.height, part_count))
    cap = math.ceil(kit.em)  # text cell height of the Comment
    top_extent = kit.ic_pin_length if layout.has_top else 0
    bottom_extent = kit.ic_pin_length if layout.has_bottom else 0
    max_width = max(geo.width for geo in layout.geometries)
    max_height = max(geo.height for geo in layout.geometries)
    gen = dict(generator or {})
    gen.setdefault("kind", "ic")
    gen["text_positions"] = {
        "designator": {"x": 0, "y": top_extent + 50, "justify": "bottom_left"},
        "comment": {"x": 0, "y": -(max_height + bottom_extent + 50 + cap), "justify": "bottom_left"},
    }
    gen["layout"] = {
        "width": max_width,
        "height": max_height,
        "parts": part_count,
        "sizes": [[geo.width, geo.height] for geo in layout.geometries],
    }
    log.debug(
        "IC-Symbol %s: %d Pins, %d Teile, Körper bis %dx%d mil", name, len(b.pins), part_count, max_width, max_height
    )
    return b.build(name=name, description=description, prefix=designator_prefix, generator=gen)


def ic_symbol(
    name: str,
    pins: list[IcPin],
    *,
    parts: int | Literal["auto"] | None = None,
    style: SymbolStyle | None = None,
    description: str = "",
    designator_prefix: str = "U",
    order: Order = "name",
    max_pins_per_side: int = MAX_PINS_PER_SIDE,
) -> SymbolSpec:
    """Box symbol for an IC with automatic pin placement (house style).

    ``parts``: ``None`` = use :attr:`IcPin.part` as given (0 = pin in all parts),
    ``"auto"`` = split into several parts when a side would exceed ``max_pins_per_side``
    (signal pins per side, supplies/grounds/exposed pads in separate last part(s) with the
    same limit), an integer = split into (at most) that many parts. ``order`` sorts the
    pins inside a group by ``name`` (natural order, default), ``designator`` or keeps the
    ``input`` order. ``style=None`` uses the open workspace's symbol style (or the defaults).
    """
    kit = StyleKit.from_style(style)
    default_name = ic_default_name(len(pins))
    generator: dict[str, Any] = {
        "kind": "ic",
        "version": 1,
        "request": {
            "kind": "ic",
            "name": name,
            "description": description or None,
            "designator_prefix": designator_prefix,
            "params": {"parts": parts, "order": order, "max_pins_per_side": max_pins_per_side},
            "pins": [p.model_dump(mode="json") for p in pins],
        },
        "style": kit.as_dict(),
        "default_name": default_name,
    }
    if name.strip().casefold() != default_name.casefold():
        generator["name"] = name
    return build_ic(
        kit,
        name,
        pins,
        parts=parts,
        description=description,
        designator_prefix=designator_prefix,
        order=order,
        max_pins_per_side=max_pins_per_side,
        generator=generator,
    )
