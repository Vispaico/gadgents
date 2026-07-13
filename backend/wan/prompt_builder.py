"""Camera-move vocabulary loader + one-shot Wan2.2 prompt contract builder."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

_DATA = Path(__file__).parent / "camera_moves.json"

# Each scene is engineered for ONE Wan2.2 image-to-video generation = ~5 seconds of
# motion with a single dominant camera move. These constraints keep each clip clean.
SHOT_CONTRACT = (
    "OUTPUT CONTRACT — you produce a sequence of shots. EACH shot is a ONE-SHOT Wan2.2 "
    "image-to-video prompt. Rules per shot:\n"
    "- Exactly ONE dominant camera move (use the supplied vocabulary verbatim).\n"
    "- Designed for ~5 seconds of generated video; keep motion contained and unambiguous.\n"
    "- Reference the SOURCE IMAGE as the first frame / seed; describe what changes during the shot.\n"
    "- Add cinematography: lens (e.g. 35mm, 85mm), lighting, color grade, motion blur where apt.\n"
    "- One concrete, filmable sentence of action. No contradictory moves in one shot.\n"
    "- If a shot needs no camera move, use 'STATIC LOCKED FRAME'."
)


@lru_cache(maxsize=1)
def load_camera_moves() -> List[dict]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def format_vocabulary(max_entries: Optional[int] = None) -> str:
    moves = load_camera_moves()
    if max_entries:
        moves = moves[:max_entries]
    lines = [f"{m['id']:>2}. {m['name']}: {m['camera_prompt']}" for m in moves]
    return "\n".join(lines)


# Tuning-phase hook: format presets (ad / short film / doc / podcast clip / reel).
# Empty for now; the format-structure knowledge base fills these during tuning.
FORMAT_PRESETS: dict[str, dict] = {}


def format_preset_block(format_kind: str) -> str:
    preset = FORMAT_PRESETS.get(format_kind)
    if not preset:
        return ""
    # e.g. typical scene count, per-shot length, pacing, structural beats
    beats = preset.get("beats")
    if not beats:
        return f"FORMAT NOTE: {format_kind} — apply its conventional pacing and structure."
    lines = [f"FORMAT PRESET ({format_kind}):"]
    for b in beats:
        lines.append(f"  - {b}")
    return "\n".join(lines)


def build_system_prompt(format_kind: str = "", include_all_moves: bool = True) -> str:
    vocab = format_vocabulary() if include_all_moves else format_vocabulary(15)
    fmt = format_preset_block(format_kind)
    return (
        "You are a senior cinematographer and AI-video prompt engineer specializing in "
        "Wan2.2 image-to-video. You turn a SOURCE IMAGE + a concept, script, or mood into a "
        "sequence of Wan2.2-ready image-to-video prompts. Wan2.2 takes an image as the first "
        "frame and generates motion from your prompt; the camera-move vocabulary below is the "
        "canonical language to use so the model produces clean, intended motion.\n\n"
        "CAMERA-MOVE VOCABULARY (use these names/phrasing verbatim in each shot's CAMERA line):\n"
        f"{vocab}\n\n"
        f"{SHOT_CONTRACT}\n\n"
        f"{fmt}\n\n"
        "STRUCTURE: number the shots in playback order (1, 2, 3...). For each, give: shot #, "
        "CAMERA (one move from vocabulary), FRAME (what's in frame / composition), ACTION "
        "(one filmable sentence), LOOK (lens, light, grade, blur), and a ready-to-paste "
        "WAN_PROMPT string. Keep WAN_PROMPT under ~280 characters, prefixed with the camera "
        "vocabulary line. Output valid JSON: {\"title\": str, \"summary\": str, "
        "\"shots\": [{\"shot\": int, \"camera\": str, \"frame\": str, \"action\": str, "
        "\"look\": str, \"wan_prompt\": str}], \"stitching_notes\": str}."
    )
