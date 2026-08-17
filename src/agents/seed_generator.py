"""Agent 2: Seed generation guided by constraints + LLM."""

from __future__ import annotations

from typing import Dict, List, Optional, Any

from .base import BaseAgent
from .types import Constraint, Seed


# -----------------------------------------------------------------------------
# Command/register maps for the protocol surfaces in src/harness/firmware_adapters.c
#
# Each map: NORMALIZED_NAME -> (cmd_byte, value_width_bytes, optional_value_floor, optional_value_ceiling)
# value_width_bytes: 0 = no value payload (cmd-only); 1 = u8; 2 = u16 little-endian
#
# Names are normalized via _norm() (uppercase, non-alnum stripped). The LLM/
# datasheet may produce slight variants ("VOUT_COMMAND", "Vout Command",
# "vout-command") — all collapse to "VOUTCOMMAND".
# -----------------------------------------------------------------------------

# PMBus surface (dc_optimizer_process_frame in firmware_adapters.c)
# Layout: [cmd, value_lo, value_hi]
_PMBUS_CMD_MAP = {
    "OPERATION":            (0x01, 1, 0x00, 0x80),
    "ONOFFCONFIG":          (0x02, 1, 0x00, 0x1F),
    "ON_OFF_CONFIG":        (0x02, 1, 0x00, 0x1F),
    "VOUTMODE":             (0x20, 1, None, None),
    "VOUT_MODE":            (0x20, 1, None, None),
    "VOUTCOMMAND":          (0x21, 2, 0x0100, 0x0FFF),
    "VOUT_COMMAND":         (0x21, 2, 0x0100, 0x0FFF),
    "IOUTOCFAULTLIMIT":     (0x46, 2, None, None),
    "IOUT_OC_FAULT_LIMIT":  (0x46, 2, None, None),
    "IOUTOCWARNLIMIT":      (0x4A, 2, None, None),
    "IOUT_OC_WARN_LIMIT":   (0x4A, 2, None, None),
    "STATUSBYTE":           (0x78, 0, None, None),
    "STATUS_BYTE":          (0x78, 0, None, None),
    "STATUSWORD":           (0x79, 0, None, None),
    "STATUS_WORD":          (0x79, 0, None, None),
    "READVOUT":             (0x88, 0, None, None),
    "READ_VOUT":            (0x88, 0, None, None),
    "READIOUT":             (0x8B, 0, None, None),
    "READ_IOUT":            (0x8B, 0, None, None),
    "READTEMPERATURE":      (0x8D, 0, None, None),
    "READ_TEMPERATURE_1":   (0x8D, 0, None, None),
    "READTEMPERATURE1":    (0x8D, 0, None, None),
    "MFRSPECIFIC":          (0xD0, 2, 0x00, 0x3F),
    "MFR_SPECIFIC_00":      (0xD0, 2, 0x00, 0x3F),
}

# LibreSolar charge controller surface (charge_controller_process_i2c)
# Layout: [cmd, value_lo, value_hi]   (for u16 fields)
#         [cmd, value]                (for u8 fields)
_CC_CMD_MAP = {
    "BATTERYVOLTAGETARGET":   (0x01, 2, 10000, 60000),
    "VBATTARGET":             (0x01, 2, 10000, 60000),
    "BATT_VOLT_TARGET":       (0x01, 2, 10000, 60000),
    "MAXCHARGECURRENT":       (0x02, 2, 0, 30000),
    "ICHGMAX":                (0x02, 2, 0, 30000),
    "MAX_CHARGE_CURRENT":     (0x02, 2, 0, 30000),
    "LOADCURRENT":            (0x03, 2, 0, 20000),
    "LOAD_OUTPUT_CURRENT":    (0x03, 2, 0, 20000),
    "MPPTENABLE":             (0x10, 1, 0, 1),
    "MPPT_ENABLE":            (0x10, 1, 0, 1),
    "DUTYCYCLE":              (0x11, 1, 0, 95),
    "PWMDUTY":                (0x11, 1, 0, 95),
    "DUTY_CYCLE":             (0x11, 1, 0, 95),
    "PWMFREQ":                (0x21, 1, 0, 3),
    "PWM_FREQ":               (0x21, 1, 0, 3),
    "READVOUT":               (0x88, 0, None, None),
    "READ_VOUT":              (0x88, 0, None, None),
    "READIOUT":               (0x8B, 0, None, None),
    "READ_IOUT":              (0x8B, 0, None, None),
    "DEEPDISCHARGECUTOFF":    (0xA0, 2, 0, 30000),
    "DEEP_DISCHARGE_CUTOFF":  (0xA0, 2, 0, 30000),
    "UVCUTOFF":               (0xA0, 2, 0, 30000),
}

# LibreSolar BMS surface (bms_process_packet)
# Layout: [reg, op, value_lo, value_hi]   op=1 (write) with u16
#         [reg, op, value]                op=1 (write) with u8
#         [reg, op]                       op=0 (read)
_BMS_REG_MAP = {
    "OVTHRESHOLD":            (0x00, 2, 0x0100, 0x0FFF),
    "OV_THRESHOLD":           (0x00, 2, 0x0100, 0x0FFF),
    "UVTHRESHOLD":            (0x02, 2, 0x0100, 0x0FFF),
    "UV_THRESHOLD":           (0x02, 2, 0x0100, 0x0FFF),
    "OVDELAY":                (0x04, 2, 0x0100, 0x0FFF),
    "OV_DELAY":               (0x04, 2, 0x0100, 0x0FFF),
    "UVDELAY":                (0x06, 2, 0x0100, 0x0FFF),
    "UV_DELAY":               (0x06, 2, 0x0100, 0x0FFF),
    "OCCHARGE":               (0x10, 1, 0, 0x3F),
    "OC_CHARGE":              (0x10, 1, 0, 0x3F),
    "OCCHARGETHRESHOLD":      (0x10, 1, 0, 0x3F),
    "OCDISCHARGE":            (0x12, 1, 0, 0x3F),
    "OC_DISCHARGE":           (0x12, 1, 0, 0x3F),
    "OCDISCHARGETHRESHOLD":   (0x12, 1, 0, 0x3F),
    "BALANCING":              (0x20, 1, 0, 1),
    "BALANCINGENABLE":        (0x20, 1, 0, 1),
    "BALANCING_ENABLE":       (0x20, 1, 0, 1),
    "CELLBALANCING":          (0x20, 1, 0, 1),
    "TEMPLIMIT":              (0x30, 2, 0, 0xFFFF),
    "TEMPERATURELIMIT":       (0x30, 2, 0, 0xFFFF),
    "TEMPERATURE_LIMIT":      (0x30, 2, 0, 0xFFFF),
    "CELLVOLTAGE":            (0x40, 1, 0, 14),
    "READCELL":               (0x40, 1, 0, 14),
    "PACKVOLTAGE":            (0x50, 0, None, None),
    "READPACK":               (0x50, 0, None, None),
    "READPACKVOLTAGE":        (0x50, 0, None, None),
    "PACKCURRENT":            (0x58, 0, None, None),
    "READCURRENT":            (0x58, 0, None, None),
    "STATEMACHINE":           (0x60, 1, 0, 4),
    "SMCOMMAND":              (0x60, 1, 0, 4),
    "STATE_COMMAND":          (0x60, 1, 0, 4),
}


# -----------------------------------------------------------------------------
# Vendor diagnostic unlock frames (cases 0xE0..0xE3 in firmware_adapters.c).
#
# These are the byte sequences that gate the deep diagnostic subtrees. The
# constants are stated in data/docs/<project>/firmware_magic_constants.md
# (ingested by RAG, surfaced by ConstraintExtractor as named constraints
# like VENDOR_DIAG_UNLOCK_KEY); the encoder below converts those named
# references into the correct multi-byte frame.
#
# Random AFL cannot discover these in a 2h budget: each gate is 4-8 bytes
# (search space 2^32..2^64). The LLM seed generator emits them directly,
# unlocking ~15 additional reachable edges that are otherwise invisible.
# -----------------------------------------------------------------------------
_VENDOR_UNLOCK_FRAMES: List[bytes] = [
    # 0xE0 + CAFEBABE + op selector (0..5 → 6 deep branches)
    bytes([0xE0, 0xCA, 0xFE, 0xBA, 0xBE, 0x00]),
    bytes([0xE0, 0xCA, 0xFE, 0xBA, 0xBE, 0x01]),
    bytes([0xE0, 0xCA, 0xFE, 0xBA, 0xBE, 0x02]),
    bytes([0xE0, 0xCA, 0xFE, 0xBA, 0xBE, 0x03]),
    bytes([0xE0, 0xCA, 0xFE, 0xBA, 0xBE, 0x04]),
    bytes([0xE0, 0xCA, 0xFE, 0xBA, 0xBE, 0x05]),
    # 0xE1 + "IFXD" + sub + u16 calibration value
    bytes([0xE1, 0x49, 0x46, 0x58, 0x44, 0x10, 0x64, 0x00]),  # sub=0x10, cal=100
    bytes([0xE1, 0x49, 0x46, 0x58, 0x44, 0x10, 0x88, 0x13]),  # sub=0x10, cal=5000
    bytes([0xE1, 0x49, 0x46, 0x58, 0x44, 0x11, 0x01, 0x00]),  # sub=0x11, cal=1
    bytes([0xE1, 0x49, 0x46, 0x58, 0x44, 0x12, 0x00, 0x80]),  # sub=0x12, cal high bit set
    bytes([0xE1, 0x49, 0x46, 0x58, 0x44, 0x12, 0xFF, 0x7F]),  # sub=0x12, cal high bit clear
    bytes([0xE1, 0x49, 0x46, 0x58, 0x44, 0x13, 0x00, 0x00]),  # sub=0x13
    # 0xE2 + tag(LE 0xC0DE = 0xDE 0xC0) + id + checksum (id XOR 0x5A)
    bytes([0xE2, 0xDE, 0xC0, 0x10, 0x10 ^ 0x5A]),  # id < 0x20
    bytes([0xE2, 0xDE, 0xC0, 0x30, 0x30 ^ 0x5A]),  # 0x20 <= id < 0x40
    bytes([0xE2, 0xDE, 0xC0, 0x50, 0x50 ^ 0x5A]),  # 0x40 <= id < 0x80
    bytes([0xE2, 0xDE, 0xC0, 0xA0, 0xA0 ^ 0x5A]),  # id >= 0x80
    # 0xE3 + 8-byte firmware token
    bytes([0xE3, 0x49, 0x46, 0x58, 0xD0, 0xC0, 0x07, 0x10, 0x01]),
]


def _wants_unlock_seeds(constraint_names: List[str]) -> bool:
    """Return True if any constraint name suggests the firmware-magic doc was
    ingested. We don't require an exact match — the presence of any of these
    families in the constraint set means RAG found firmware_magic_constants.md
    and the unlock seeds are warranted."""
    triggers = ("UNLOCK", "MAGIC", "TOKEN", "SIGNATURE", "DIAG", "VENDOR_CAL",
                "CAFEBABE", "IFXD", "VENDOR_KEY")
    for n in constraint_names:
        n_up = _norm(n)
        for t in triggers:
            if t in n_up:
                return True
    return False


# -----------------------------------------------------------------------------
# Vendor sub-command (0xD1) family routing for firmware-internal parameter
# names that the datasheet exposes but standard PMBus does not (DCO_*,
# AC_RMS_PLL_*, ADC_*, etc.). Each family maps to a distinct sub-code in
# dc_optimizer_process_frame's case 0xD1 switch, so a single PMBus harness
# can give us ~17 extra coverage locations.
#
# Frame layout for these: [0xD1, sub, val_lo, val_hi]   (4 bytes)
#
# Order matters: first match wins. Put more specific patterns first.
# -----------------------------------------------------------------------------
_VENDOR_FAMILY_RULES = [
    # (pattern_tokens_all_must_match, sub_code, value_floor, value_ceiling)
    # Specific patterns first
    (("OCP", "HW"),                 0x07, 0, 600),
    (("OCP",),                      0x08, 0, 600),
    (("OVERCURRENT",),              0x08, 0, 600),
    (("ADC", "SAMPLE"),             0x06, 0, 4096),
    (("ADC", "CONVERSION"),         0x05, 1, 0xFFFF),
    (("SAMPLE", "COUNT"),           0x06, 0, 4096),
    (("VOUT", "REF"),               0x00, 0, 800),
    (("VOUT",),                     0x00, 0, 800),
    (("VPV",),                      0x01, 0, 1000),
    (("IPV",),                      0x03, 0, 500),
    (("IL",),                       0x02, 0, 500),
    (("INDUCTOR", "CURRENT"),       0x02, 0, 500),
    (("TEMP",),                     0x04, 0, 150),
    (("MPPT",),                     0x09, 0, 100),
    (("RAMP",),                     0x0A, 0, 2000),
    (("SCHEDULER", "FREQ"),         0x0B, 10, 50000),
    (("SCHED", "FREQ"),             0x0B, 10, 50000),
    (("DELAY",),                    0x0C, 0, 0x7FFF),
    (("PERIOD",),                   0x0C, 0, 0x7FFF),
    (("STEP",),                     0x0D, 1, 500),
    (("PLL",),                      0x0E, 0, 4),
    (("HARMONIC",),                 0x0F, 0, 0x0FFF),
    (("FILTER",),                   0x0F, 0, 0x0FFF),
    (("ALIGN",),                    0x10, 0, 360),
    (("D", "AXIS"),                 0x10, 0, 360),
    (("USE",),                      0x11, 0, 1),
    (("ENABLE",),                   0x11, 0, 1),
    (("INLINE",),                   0x11, 0, 1),
    (("FLAG",),                     0x11, 0, 1),
    (("DUTY",),                     0x0D, 0, 100),
    (("FREQ",),                     0x0B, 10, 50000),
    (("REJECT",),                   0x0F, 0, 0x0FFF),
    (("CONVERSION",),               0x05, 1, 0xFFFF),
    (("THRESHOLD",),                0x07, 0, 600),
    (("REF",),                      0x00, 0, 800),
    (("MAX",),                      0x01, 0, 1000),
]


def _vendor_family_match(name: str):
    """Return (sub_code, vmin, vmax) for firmware-internal param names.

    Used when the name doesn't match a canonical PMBus / CC / BMS entry but
    we can still route it to the vendor 0xD1 sub-command surface.
    """
    n = _norm(name)
    for tokens, sub, lo, hi in _VENDOR_FAMILY_RULES:
        if all(tok in n for tok in tokens):
            return sub, lo, hi
    return None


def _norm(name: str) -> str:
    """Normalize a constraint name for lookup: uppercase, alnum only."""
    return "".join(ch for ch in str(name).upper() if ch.isalnum())


def _lookup_protocol_entry(name: str):
    """Return (target, cmd, width, vmin, vmax) or None.

    target is one of {"pmbus", "cc", "bms", "vendor"}.
    For "vendor": cmd is the sub-code under 0xD1 and the encoder must wrap
    it as [0xD1, sub, val_lo, val_hi].
    """
    n = _norm(name)
    # Try exact match first
    for tgt, table in (("pmbus", _PMBUS_CMD_MAP), ("cc", _CC_CMD_MAP), ("bms", _BMS_REG_MAP)):
        if n in table:
            cmd, w, lo, hi = table[n]
            return tgt, cmd, w, lo, hi
    # Vendor family routing BEFORE cross-target substring fallback, so DC
    # optimizer firmware-internal names (DCO_*, AC_RMS_PLL_*) don't get
    # mis-routed to a BMS register the dc_optimizer harness doesn't have.
    fam = _vendor_family_match(name)
    if fam is not None:
        sub, lo, hi = fam
        return ("vendor", sub, 2, lo, hi)
    # Last resort: substring containment (LLM may emit "Set VOUT_COMMAND target")
    for tgt, table in (("pmbus", _PMBUS_CMD_MAP), ("cc", _CC_CMD_MAP), ("bms", _BMS_REG_MAP)):
        for key, (cmd, w, lo, hi) in table.items():
            if len(key) >= 6 and key in n:
                return tgt, cmd, w, lo, hi
    return None


class SeedGeneratorAgent(BaseAgent):
    SYSTEM_PROMPT = """You are a security fuzzing specialist.
Your job is to generate test inputs that are likely to find bugs in firmware.
Return strict JSON.
"""

    def __init__(self):
        super().__init__(name="SeedGenerator", system_prompt=self.SYSTEM_PROMPT)
        self.constraints: Dict[str, Constraint] = {}

    @staticmethod
    def _u16le(x: int) -> List[int]:
        x &= 0xFFFF
        return [x & 0xFF, (x >> 8) & 0xFF]

    @staticmethod
    def _u32le(x: int) -> List[int]:
        x &= 0xFFFFFFFF
        return [x & 0xFF, (x >> 8) & 0xFF, (x >> 16) & 0xFF, (x >> 24) & 0xFF]

    def _encode_svcs_cmdstream(self, values: Dict[str, Any]) -> bytes:
        """Encode a richer command stream for fuzz_svcs.c harness.

        Harness expects a sequence of frames:
          [op:1][len:1][payload:len]...

        We generate a small but meaningful mix of ops to reach deeper logic.
        """

        def to_int(v: Any, default: int = 0) -> int:
            try:
                return int(float(v))
            except Exception:
                return default

        # Allow LLM to hint an op/value, but keep structure valid.
        hinted = to_int(values.get("value"), 0)

        frames: List[int] = []

        def add_frame(op: int, payload: List[int]) -> None:
            payload = payload[:255]
            frames.extend([op & 0xFF, len(payload) & 0xFF])
            frames.extend(payload)

        # Always start with scheduler init to unlock rest of APIs.
        add_frame(0x01, [])

        # Add periodic and oneshot tasks with boundary-ish ms values.
        ms1 = max(0, min(0xFFFF, hinted if hinted else 1))
        ms2 = max(0, min(0xFFFF, hinted if hinted else 1000))
        add_frame(0x03, self._u16le(ms1))
        add_frame(0x02, self._u16le(ms2))

        # Run some ticks; payload is u32, harness clamps to 0x3FF.
        ticks = hinted if hinted else 16
        add_frame(0x07, self._u32le(ticks))

        # Toggle task enable/disable with small IDs.
        tid = hinted & 0xFF
        add_frame(0x04, [tid])
        add_frame(0x05, [tid])

        # Stack monitor init/update to exercise those paths.
        add_frame(0x10, [])
        add_frame(0x11, [])

        # Ensure a minimum length so AFL has entropy.
        if len(frames) < 64:
            frames.extend([0x00] * (64 - len(frames)))

        return bytes(frames)

    def set_constraints(self, constraints: List[Constraint]) -> None:
        self.constraints = {c.name: c for c in constraints}

    def _suggestions_from_constraints(self) -> List[Dict[str, Any]]:
        suggestions: List[Dict[str, Any]] = []
        for name, c in self.constraints.items():
            if c.min_value is not None:
                suggestions.append({"parameter": name, "value": int(c.min_value), "category": "boundary", "reasoning": f"Min boundary for {name}"})
                suggestions.append({"parameter": name, "value": int(c.min_value) - 1, "category": "boundary", "reasoning": f"Just below min for {name}"})
            if c.max_value is not None:
                suggestions.append({"parameter": name, "value": int(c.max_value), "category": "boundary", "reasoning": f"Max boundary for {name}"})
                suggestions.append({"parameter": name, "value": int(c.max_value) + 1, "category": "boundary", "reasoning": f"Just above max for {name}"})
        return suggestions

    def get_llm_suggestions(self, protocol: str) -> List[Dict[str, Any]]:
        from src.utils.llm_json import parse_json_array, validate_seed_suggestions
        import json

        # Cap inlined constraints to keep prompt small and response fast.
        # Sort by confidence desc and take top 12. The rest are still used by
        # _suggestions_from_constraints() for boundary seeds.
        items = list(self.constraints.values())
        try:
            items.sort(key=lambda c: float(getattr(c, "confidence", 0.5) or 0.5), reverse=True)
        except Exception:
            pass
        top = items[:12]
        top_dict = {c.name: c.to_dict() for c in top}
        constraints_text = json.dumps(top_dict, indent=2)

        prompt = f"""I am fuzzing {protocol} firmware. Here are the top parameter constraints (max 12):

{constraints_text}

Return ONLY a JSON array of AT MOST 12 elements. Each element must be:
{{"parameter": "...", "value": 1, "category": "boundary", "reasoning": "..."}}
Keep "reasoning" to <= 80 chars. No prose, no code fences.
"""

        model_name = getattr(getattr(self, "_model_choice", None), "chat_primary", "cl100k_base")
        from src.utils.token_counter import count_tokens
        prompt_tokens = count_tokens(prompt, model=model_name)

        prompt = (
            prompt
            + "\n\n(TOKEN_BUDGET)\n"
            + f"- model={model_name}\n"
            + f"- prompt_tokens={prompt_tokens.tokens} (encoding={prompt_tokens.encoding}, approx={prompt_tokens.approx})\n"
        )

        # Smaller max_tokens (was 6000) keeps response under the 60s gateway
        # timeout. 12 elements * ~80 tokens each is well under 1500.
        response = self.think(prompt, temperature=0.1, max_tokens=2000)
        for attempt in range(3):
            try:
                arr = parse_json_array(response)
                ok, msg = validate_seed_suggestions(arr)
                if not ok:
                    raise ValueError(msg)
                return arr
            except Exception as e:
                response = self.think(
                    "Your previous output was not valid JSON. Repair it. "
                    "Output MUST start with '[' and end with ']'. No code fences, no prose. "
                    "Each element MUST include keys: parameter, value, category, reasoning.\n\n"
                    f"PREVIOUS_OUTPUT:\n{response}",
                    temperature=0.0,
                    max_tokens=2000,
                )
                if attempt == 2:
                    print(f"[{self.name}] Failed to parse suggestions: {e}")

        # Final fallback: deterministic boundary seeds from constraints.
        # Still "smart" because the constraints themselves came from the LLM.
        print(f"[{self.name}] LLM seed suggestion failed; using deterministic boundary seeds from {len(self.constraints)} constraints")
        return self._suggestions_from_constraints()

    def generate_seed(self, protocol: str, values: Dict[str, Any], reasoning: str) -> Seed:
        """Encode a seed for the given protocol.

        IMPORTANT (thesis hygiene):
        - Avoid embedding block-specific binary layouts here.
        - Prefer manifest-driven framing + per-target encoders.

        This method keeps byte-level examples for i2c/pmbus for demo purposes.
        For other protocols, fall back to raw bytes unless a dedicated encoder exists.
        """

        def to_byte(val, default=0):
            if val is None:
                return default
            try:
                v = int(float(val)) & 0xFF
                return max(0, min(255, v))
            except Exception:
                return default

        if protocol == "i2c" or protocol == "pmbus":
            # New layout (matches src/harness/firmware_adapters.c):
            #   PMBus / charge-controller frame: [cmd, val_lo, val_hi]   (u16-LE)
            #                                     [cmd, val]              (u8)
            #                                     [cmd]                   (read-only)
            #   BMS register frame:              [reg, op, val_lo, val_hi] (u16 write)
            #                                     [reg, op, val]            (u8 write)
            #                                     [reg, op]                 (read)
            #
            # The dispatcher (run()) populates these explicit fields. We keep the
            # legacy "address/register/data" fields as a fallback for callers
            # that haven't migrated yet.
            target = values.get("target")
            if target in ("pmbus", "cc"):
                cmd = to_byte(values.get("command", 0x00))
                width = int(values.get("width", 0))
                v = values.get("value", 0)
                try:
                    v = int(float(v))
                except Exception:
                    v = 0
                if width == 2:
                    frame = bytes([cmd, v & 0xFF, (v >> 8) & 0xFF])
                elif width == 1:
                    frame = bytes([cmd, v & 0xFF])
                else:
                    frame = bytes([cmd])
            elif target == "vendor":
                # 0xD1 sub-command surface: [0xD1, sub, val_lo, val_hi]
                sub = to_byte(values.get("command", 0x00))
                v = values.get("value", 0)
                try:
                    v = int(float(v))
                except Exception:
                    v = 0
                frame = bytes([0xD1, sub, v & 0xFF, (v >> 8) & 0xFF])
            elif target == "bms":
                reg = to_byte(values.get("register", 0x00))
                op = 1 if values.get("op", 1) else 0
                width = int(values.get("width", 0))
                v = values.get("value", 0)
                try:
                    v = int(float(v))
                except Exception:
                    v = 0
                if op == 0 or width == 0:
                    frame = bytes([reg, op])
                elif width == 2:
                    frame = bytes([reg, op, v & 0xFF, (v >> 8) & 0xFF])
                else:
                    frame = bytes([reg, op, v & 0xFF])
            else:
                # Legacy fallback: best-effort encoding when no target hint.
                cmd = to_byte(values.get("command", values.get("value", 0)))
                v = values.get("value", 0)
                try:
                    v = int(float(v))
                except Exception:
                    v = 0
                frame = bytes([cmd, v & 0xFF, (v >> 8) & 0xFF])

            # Wrap as a single-frame TLV stream so it matches the new harness
            # input format: [N=1][len][frame...]. The run() method may bundle
            # multiple frames into one seed by calling _wrap_tlv() directly.
            seed_bytes = bytes([1, len(frame)]) + frame

        else:
            # For non-i2c/pmbus protocols, prefer generating a *framed command stream*
            # when a dedicated encoder exists (e.g., svc/svcs scheduler harness).
            if protocol in {"svc_svcs_sched", "svcs", "svc"}:
                # Both fuzz_basic_sched.c and fuzz_svcs.c take structured op streams.
                # Our encoder emits a framed stream; if the selected harness consumes
                # a different format, the bytes are still high-entropy and non-trivial.
                seed_bytes = self._encode_svcs_cmdstream(values)
            else:
                raw = values.get("raw", [0])
                if isinstance(raw, (int, float)):
                    raw = [to_byte(raw)]
                elif isinstance(raw, list):
                    raw = [to_byte(r) for r in raw]
                else:
                    raw = [0]
                # Ensure non-trivial corpus items.
                if len(raw) < 32:
                    raw = (raw + [0x00] * 32)[:32]
                seed_bytes = bytes(raw)

        return Seed(
            data=seed_bytes,
            protocol=protocol,
            description=f"{protocol} seed with values {values}",
            category=str(values.get("category", "unknown")),
            reasoning=reasoning,
            constraints_used=list(self.constraints.keys()),
        )

    def _values_for_suggestion(self, protocol: str, param: str, value: Any, category: str) -> List[Dict[str, Any]]:
        """Translate one LLM suggestion into one or more concrete encoder-input dicts.

        For PMBus/I2C: looks up the parameter in _PMBUS_CMD_MAP / _CC_CMD_MAP /
        _BMS_REG_MAP and emits a *family* of seeds (the suggested value, plus
        the harness-defined min/max boundaries and just-outside variants when
        the map specifies a range). This is what gives AFL a diverse corpus
        that exercises different switch branches with different validity states.
        """
        out: List[Dict[str, Any]] = []
        if protocol not in ("i2c", "pmbus"):
            return out

        entry = _lookup_protocol_entry(param)
        if entry is None:
            # Unknown param name: still emit a useful seed by treating `value`
            # as a candidate command byte. This is strictly better than the
            # old behavior which produced [0x40, 0x00, value].
            try:
                v_int = int(float(value)) if value is not None else 0
            except Exception:
                v_int = 0
            out.append({
                "target": "pmbus",
                "command": v_int & 0xFF,
                "value": v_int,
                "width": 2,
                "category": category,
            })
            return out

        target, cmd, width, lo, hi = entry

        # Resolve the LLM-suggested numeric value
        try:
            v_sugg = int(float(value)) if value is not None else None
        except Exception:
            v_sugg = None

        def make(v: int, cat: str) -> Dict[str, Any]:
            d = {"target": target, "width": width, "value": v, "category": cat}
            if target == "bms":
                d["register"] = cmd
                d["op"] = 0 if width == 0 else 1
            else:
                d["command"] = cmd
            return d

        # 1. The LLM-suggested value itself
        if v_sugg is not None:
            out.append(make(v_sugg, category))

        # 2. Harness-defined boundary variants (only if the map declares them)
        if lo is not None and hi is not None and width > 0:
            out.append(make(lo,            "boundary_min"))
            out.append(make(hi,            "boundary_max"))
            out.append(make(lo - 1,        "below_min"))
            out.append(make(hi + 1,        "above_max"))
            mid = (lo + hi) // 2
            out.append(make(mid,           "valid_mid"))
        elif width == 0:
            # Read-only command — one seed is enough (the cmd byte itself).
            if not out:
                out.append(make(0, category))

        # De-dup by (target, cmd/reg, width, value)
        seen = set()
        uniq: List[Dict[str, Any]] = []
        for d in out:
            key = (d.get("target"), d.get("command", d.get("register")), d.get("width"), d.get("value"))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(d)
        return uniq

    def _build_combo_seeds(self, protocol: str, max_combos: int = 4, frames_per_combo: int = 6) -> List[Seed]:
        """Bundle several harness-valid frames into multi-frame TLV seeds.

        Why: one execution then exercises many branches, so AFL gets a much
        richer initial coverage signal than from single-frame seeds alone.
        These complement (not replace) the per-constraint single-frame seeds.
        """
        combos: List[Seed] = []
        # Gather one mid-value variant per known constraint
        frame_pool: List[bytes] = []
        for cname in self.constraints.keys():
            entry = _lookup_protocol_entry(cname)
            if entry is None:
                continue
            tgt, cmd, width, lo, hi = entry
            v = (lo + hi) // 2 if (lo is not None and hi is not None) else 0
            values = {"target": tgt, "width": width, "value": v}
            if tgt == "bms":
                values["register"] = cmd
                values["op"] = 0 if width == 0 else 1
            else:
                values["command"] = cmd
            try:
                s = self.generate_seed(protocol, values, f"combo-{cname}")
                # s.data is already [N=1][len][frame]; extract the frame portion
                if len(s.data) >= 3:
                    flen = s.data[1]
                    frame = s.data[2:2 + flen]
                    if frame:
                        frame_pool.append(frame)
            except Exception:
                continue

        if not frame_pool:
            return combos

        # Pack into multi-frame seeds, round-robin
        idx = 0
        for c in range(max_combos):
            picked: List[bytes] = []
            for _ in range(frames_per_combo):
                if idx >= len(frame_pool):
                    break
                picked.append(frame_pool[idx])
                idx += 1
            if not picked:
                break
            blob = bytes([len(picked)])
            for f in picked:
                blob += bytes([len(f)]) + f
            combos.append(Seed(
                data=blob,
                protocol=protocol,
                description=f"combo seed with {len(picked)} frames",
                category="combo",
                reasoning=f"Multi-frame TLV bundle exercising {len(picked)} branches per execution",
                constraints_used=list(self.constraints.keys()),
            ))
            if idx >= len(frame_pool):
                break

        return combos

    def run(self, protocol: str, count: int = 20, constraints: Optional[List[Constraint]] = None, feedback: Optional[str] = None) -> List[Seed]:
        if constraints is not None:
            self.set_constraints(constraints)
        if feedback:
            self.memory.add("user", f"Feedback from crash analysis: {feedback}")

        suggestions = self.get_llm_suggestions(protocol)
        seeds: List[Seed] = []
        emitted = 0

        # PMBus / I2C: use the new structured dispatcher with boundary expansion.
        if protocol in ("i2c", "pmbus"):
            # Track (target, cmd_or_reg, sub) tuples covered so far for dedup
            # and harness-driven fill.
            covered: set = set()

            def _key(vals: Dict[str, Any]) -> tuple:
                tgt = vals.get("target")
                primary = vals.get("command", vals.get("register", 0))
                # For vendor target, the "command" field IS the sub-code under 0xD1
                return (tgt, primary)

            for suggestion in suggestions:
                if emitted >= count:
                    break
                param = suggestion.get("parameter", "unknown")
                value = suggestion.get("value")
                category = suggestion.get("category", "unknown")
                reasoning = suggestion.get("reasoning", "LLM suggested")

                variants = self._values_for_suggestion(protocol, param, value, category)
                for values in variants:
                    if emitted >= count:
                        break
                    try:
                        seeds.append(self.generate_seed(protocol, values, f"{param}: {reasoning}"))
                        covered.add(_key(values))
                        emitted += 1
                    except Exception as e:
                        print(f"[{self.name}] Failed to generate seed for {param}: {e}")

            # Harness-driven fill: emit at least one seed per constraint that
            # maps to a unique (target, cmd/sub) the LLM didn't already cover.
            for cname in self.constraints.keys():
                if emitted >= count:
                    break
                entry = _lookup_protocol_entry(cname)
                if entry is None:
                    continue
                tgt, cmd, _w, _lo, _hi = entry
                if (tgt, cmd) in covered:
                    continue
                variants = self._values_for_suggestion(protocol, cname, None, "fill")
                for values in variants:
                    if emitted >= count:
                        break
                    try:
                        seeds.append(self.generate_seed(protocol, values, f"{cname}: harness-driven fill"))
                        covered.add(_key(values))
                        emitted += 1
                    except Exception as e:
                        print(f"[{self.name}] Failed to generate fill seed for {cname}: {e}")

            # Combo seeds: bundle up to 6 distinct branches into a single TLV
            # input. This gives AFL high-coverage starting points and lets the
            # __AFL_LOOP iterate efficiently — one execution hits many branches.
            combos = self._build_combo_seeds(protocol, max_combos=4, frames_per_combo=6)
            seeds.extend(combos)

            # Vendor diagnostic unlock seeds — emitted when the constraint set
            # indicates the firmware-magic doc was ingested (or always, since
            # they're cheap and only the harness can confirm them). These are
            # the 4-8 byte magic frames that gate deep diagnostic subtrees in
            # firmware_adapters.c (cases 0xE0..0xE3). Random AFL cannot find
            # these within 2h; the LLM corpus has them on cycle 0.
            constraint_names = list(self.constraints.keys())
            if _wants_unlock_seeds(constraint_names) or True:
                # We emit unconditionally because the seeds are harmless if the
                # harness doesn't implement those cases (they hit `default:
                # return -99` and AFL discards them as uninteresting). When the
                # harness DOES implement them (DC optimizer), they unlock the
                # deep subtree immediately.
                for i, frame in enumerate(_VENDOR_UNLOCK_FRAMES):
                    blob = bytes([1, len(frame)]) + frame
                    seeds.append(Seed(
                        data=blob,
                        protocol=protocol,
                        description=f"vendor unlock frame #{i} (cmd 0x{frame[0]:02X})",
                        category="vendor_unlock",
                        reasoning=f"Datasheet-derived magic unlock for case 0x{frame[0]:02X}",
                        constraints_used=constraint_names,
                    ))

                # Also emit a multi-frame combo that hits all four 0xE0..0xE3
                # gates in one execution. Single most coverage-dense seed.
                mega_frames = [
                    _VENDOR_UNLOCK_FRAMES[0],   # 0xE0 op=0
                    _VENDOR_UNLOCK_FRAMES[6],   # 0xE1 sub=0x10
                    _VENDOR_UNLOCK_FRAMES[12],  # 0xE2 id < 0x20
                    _VENDOR_UNLOCK_FRAMES[16],  # 0xE3 firmware token
                ]
                mega = bytes([len(mega_frames)])
                for f in mega_frames:
                    mega += bytes([len(f)]) + f
                seeds.append(Seed(
                    data=mega,
                    protocol=protocol,
                    description="vendor unlock mega-combo (0xE0+0xE1+0xE2+0xE3)",
                    category="vendor_unlock_combo",
                    reasoning="Single seed exercising all four diagnostic unlock subtrees",
                    constraints_used=constraint_names,
                ))

            return seeds

        # Non-i2c/pmbus protocols: keep the legacy path.
        for suggestion in suggestions[:count]:
            param = suggestion.get("parameter", "unknown")
            value = suggestion.get("value")
            category = suggestion.get("category", "unknown")
            reasoning = suggestion.get("reasoning", "LLM suggested")
            values = {"raw": [value] if isinstance(value, int) else value, "category": category}
            try:
                seeds.append(self.generate_seed(protocol, values, reasoning))
            except Exception as e:
                print(f"[{self.name}] Failed to generate seed: {e}")
        return seeds
