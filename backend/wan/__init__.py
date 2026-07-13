"""Wan2.2 Image-to-Video prompt agent (agent #4).

Turns a user's still image + concept / script / mood into Wan2.2-ready image-to-video
prompts. Each "scene" is a self-contained one-shot prompt engineered so Wan generates a
single ~5-second clip with a strong, unambiguous camera move; stitched together the clips
form a coherent sequence. Built around the 50 camera-move vocabulary in camera_moves.json.

The format/structure knowledge (how ads / short films / docs / podcasts are paced, scene
lengths, etc.) is a tuning-phase enrichment. We expose HOOKS for it (format presets,
sequence_length) so the background agents can later inject structure from a knowledge base
without changing this code.
"""
