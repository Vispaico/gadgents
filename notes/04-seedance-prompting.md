# The Seedance 2.0 Prompting Bible

## Human‑Readable Summary
The Seedance 2.0 Prompting Bible ( https://x.com/EXM7777/status/2044072293383712878?s=20 )
Seedance 2.0 is a multimodal film set, not a simple text‑to‑video box. In a single generation it can take up to 9 images, 3 video clips, 3 audio tracks, plus a text prompt, and generate synchronized 4–15s video with stereo audio in one pass. To get strong results you must speak its own “language”: a 5‑layer prompt stack (subject, action, camera, style, constraints) plus explicit `@` roles for each reference file. Camera and lighting keywords act as primary controls, while constraints like “avoid jitter” and “avoid bent limbs” are critical to avoid AI‑looking artifacts. You can even time‑code multi‑shot sequences inside one 15‑second clip using timestamps, effectively turning Seedance into a mini editor that obeys your shot breakdown.

For AI agents, treat Seedance prompting as a small DSL: a fixed template with slots for each layer, a controlled vocabulary of camera/lighting/constraint keywords, and an iteration loop that changes only one variable per pass. Agents should always tag all reference assets with `@` roles, and can use “first frame” / “last frame” images so the model interpolates between them. This document is structured so an LLM can parse, learn, and programmatically generate Seedance prompts for production‑grade video agents.

---

## 1. Model Capabilities

- Inputs per generation: 9 reference images, 3 video clips, 3 audio tracks, and 1 text prompt.
- Output: 4–15 seconds of video up to 1080p with dual‑channel stereo audio generated in a single pass.
- Multilingual lip‑sync: supports English, Mandarin, Japanese, Korean, Spanish, French, German, Portuguese and Chinese dialects.
- Compared to Sora 2, Kling 3.0, Veo 3.1 (text+image models), Seedance uses text + images + video + audio simultaneously.

## 2. The 5‑Layer Prompt Stack

Canonical order:

> subject > action > camera > style > constraints

- Subject: defines the main entity, identity and focus.
- Action: describes specific physical movement in present tense.
- Camera: locks framing, lens feel and motion pattern.
- Style: covers lighting, grade and film aesthetics.
- Constraints: guardrails to suppress artifacts and enforce stability.

Generic template:

```text
[SUBJECT].
[ACTION].
[CAMERA].
[STYLE].
[CONSTRAINTS].
```

## 3. Layer 1 – Subject

Goal: define one clear subject with strong identity.

- Bad: `a woman`
- Better: `a young woman with brown hair`
- Best: `a woman in her late 20s, tight dark curls at ear length, small silver hoop in left ear, wearing a fitted black turtleneck, neutral expression`

Identity markers to specify:
- Approximate age.
- Hair length, color and texture.
- Clothing type, color and texture.
- Accessories (earrings, glasses, hats, etc.).
- Posture and facial expression.

Subject count:
- 1 subject: maximally stable.
- 2 subjects: workable if tagged and spatially separated (`@Character_A`, `@Character_B`).
- 3+ subjects: quality and consistency drop sharply.

Agent rules:
- Prefer one main subject; if multiple, ensure each has its own reference image and tag.
- Include at least 3–5 concrete identity markers per key subject.

## 4. Layer 2 – Action

Goal: describe visible, physical actions, not abstract feelings.

- Bad: `she looks happy and is enjoying the sunset`.
- Good: `she slowly turns toward the camera, breeze lifting the hem of her skirt, eyes narrowing against the light`.

Rules:
- Use present tense.
- One primary movement per shot.
- Avoid purely emotional adjectives without visual correlates.

Separate subject and camera motion:
- Bad: `spinning camera around a dancing person` (ambiguous who spins).
- Good: `the dancer spins slowly, camera holds fixed framing`.

Agent rules:
- Generate a single, focused action description for each shot.
- Ensure camera behavior is described in its own clause, not mixed into the subject action.

## 5. Layer 3 – Camera

Camera instructions are first‑class and strongly influence results.

### 5.1 Static shots

- `fixed` / `locked-off` – no camera movement.
- `static wide` – wide establishing shot with fixed camera.
- `locked tripod` – fully stabilized camera, no shake.

### 5.2 Movement types

- `push-in` / `dolly in` – camera moves toward subject.
- `pull-out` / `dolly out` – camera moves away.
- `pan left` / `pan right` – rotation around tripod.
- `tracking shot` / `follow` – camera moves with subject.
- `orbit` / `arc` / `360 orbit` – camera circles the subject.
- `aerial` / `drone shot` – high, overhead view.
- `handheld` – subtle, natural shake.
- `crane up` / `crane down` – vertical camera movement.
- `gimbal` – smooth, stabilised motion.
- `steadicam walk` – polished following movement.
- `whip pan` – rapid pan for energy/transitions.
- `dolly zoom` – subject size stable, background warps.
- `rack focus` – focus shifts between planes.

### 5.3 Speed modifiers

- `imperceptible` / `barely` – extremely slow.
- `slow` / `gentle` / `gradual` – safe defaults.
- `smooth` / `controlled` – stable rhythm.
- `dynamic` / `swift` – strong movement, use sparingly.

Danger keyword:
- `fast` alone tends to accelerate all motion (camera, subject, environment), causing jitter and artifacts.

### 5.4 Compound motion

Describe phases instead of stacking moves:

```text
start: slow dolly-in, then: gentle pan right for the final 2 seconds
```

Agent rules:
- Use a controlled vocabulary of moves plus speed modifiers.
- Default to slow, smooth movement unless the user explicitly wants intensity.
- For complex shots, sequence motion in time instead of combining many moves at once.

## 6. Layer 4 – Style (Lighting, Color, Film)

Lighting is the highest‑leverage control for quality.

### 6.1 Lighting

High‑impact lighting terms:
- `golden hour` – warm, directional, flattering light.
- `rim light` / `dramatic rim light against dark background` – strong edge separation.
- `soft key from 45 degrees` – flattering face lighting.
- `overcast daylight` / `even overcast diffused light` – stable, low‑flicker outdoor light.
- `backlit silhouette at sunset` – dramatic, graphic look.
- `motivated lighting from practical source` – light apparently coming from visible lamps/windows.
- `volumetric fog` – visible light beams and depth.
- `chiaroscuro` – high‑contrast dramatic lighting.

### 6.2 Color grading

- `teal and orange` – standard Hollywood grade.
- `bleach bypass` – desaturated, gritty contrast.
- `warm tone` / `amber-tinted` – nostalgic feel.
- `crushed blacks` – deep shadows.
- `pastel` – soft, stylized palette.

### 6.3 Film style anchors

- `cinematic film tone, 35mm` – robust, general cinematic look.
- `16mm film, handheld camera` – grainy, indie documentary.
- `anamorphic lens flare` – widescreen blockbuster aesthetic.
- `national geographic quality` – realistic nature documentary.
- `documentary-style handheld framing` – observational realism.

Notes:
- `cinematic` alone is too vague; pair it with specific film and lighting descriptors.
- `glow`, `glimmer`, `glints` can cause flicker; prefer `soft diffuse light` or `steady intensity`.

Agent rules:
- Always specify lighting, even minimally.
- Use combinations like `cinematic film tone, 35mm, golden hour rim lighting` rather than single adjectives.

## 7. Layer 5 – Constraints

Constraints act as guardrails against common artifacts.

### 7.1 Core constraints

For character shots, add:
- `avoid jitter`
- `avoid bent limbs`
- `avoid identity drift`
- `avoid temporal flicker`
- `no distortion, no stretching`
- `maintain face consistency`

### 7.2 Quality suffix

Append a standard tail:

```text
sharp clarity, natural colors, stable picture, no blur, no ghosting, no flickering
```

Agent rules:
- Maintain a default constraint bundle for all prompts.
- Always include limb, jitter and face‑consistency constraints when people appear.

## 8. Keywords to Avoid or Rewrite

These often harm outputs and should be rewritten:
- `fast` (unqualified).
- `cinematic` (by itself).
- `epic`, `amazing`, `beautiful`, `stunning`.
- `lots of movement`.
- `glow`, `glimmer`, `glints` (replace with `soft diffuse light` / `steady intensity`).

Principle: convert viewer emotions into concrete visuals (camera, lighting, composition).

## 9. Time‑Coded Multi‑Shot Prompting

Seedance can follow time‑coded shot breakdowns within one 15‑second generation.

### 9.1 Format examples

Range brackets format:

```text
[0-4s]: wide establishing shot, static camera, misty bamboo forest at dawn, golden hour light filtering through leaves
[4-9s]: medium shot, slow push-in, the fighter steps forward, white silk kimono billowing, determined expression
[9-15s]: close-up, orbit shot, the fighter strikes, slow motion, impact visible in the fabric ripple
```

Parenthetical seconds format:

```text
(0-3s) macro shot of perfume bottle among pink flowers, shallow depth of field, petals floating
(3-7s) camera glides closer, a feminine hand enters frame, touches the bottle
(7-12s) slow-motion spray, mist diffuses in air, particles catching rim light
(12-15s) pull-out to hero frame, product centered, volumetric lighting, minimal background
```

### 9.2 15s climax arc template

```text
[0-4s]: wide shot, static, world established, ambient sound
[4-8s]: medium shot, slow push-in, tension building, subject prepares
[8-12s]: close-up, emotional peak approaching, one specific detail in sharp focus
[12-15s]: extreme close-up or dramatic reveal, climax action, slow motion or static hold, silence
```

Agent rules:
- Use time‑coding for sequences > 6 seconds or multi‑beat arcs.
- Keep each segment’s camera, action and lighting explicit.

## 10. The `@` Reference System

Every reference file should be tagged in the text prompt.

Syntax:
- Images: `@Image1`, `@Character_A`.
- Video: `@Video1`.
- Audio: `@Audio1`.

Files without `@` tags are interpreted ambiguously.

### 10.1 First–last frame technique

- Provide `@Image1` as the first frame and `@Image2` as the last frame.
- Describe the motion that connects them in text.
- Seedance interpolates motion from start to end.

### 10.2 Example mapping

```text
@Image1 as character reference (maintain exact facial features and outfit)
@Image2 as environment reference (match lighting and color palette)
@Video1 for camera motion reference (replicate the slow orbit movement)
@Audio1 as background music (sync scene transitions to beat positions)
```

Agent rules:
- Auto‑assign semantic roles to assets and emit corresponding `@` tags.
- Propose the first–last frame pattern when exactly two keyframes are provided.

## 11. Canonical Prompt Examples

### 11.1 Talking head / UGC

```text
15 seconds UGC style review video, filmed on smartphone, natural bedroom
window lighting, casual handheld selfie angle, a young woman with brown
hair pulled back, natural skin with visible texture, wearing a casual grey
t-shirt, in her cozy bedroom, she holds a product up to the camera with
genuine excitement, quick jump cut slightly closer angle, she applies it
showing the texture, jump cut she leans into the camera with a natural
smile, the lighting is soft natural daylight no ring light no filters,
direct phone mic audio room ambience natural voice
```

### 11.2 Luxury product commercial

```text
ultra cinematic 15-second luxury product commercial, smooth continuous
sequence elegant pacing, fluid cinematic glide macro dolly plus soft
orbit plus gentle push-ins, seamless transitions masked by depth blur and
motion continuity no hard cuts everything flows organically, (0-3s) macro
shot of product on dark surface shallow depth of field rim light catching
edges, (3-7s) camera glides closer warm light rakes across surface
revealing texture, (7-11s) slow motion detail moment volumetric lighting,
(11-15s) pull-out to centered hero frame product isolated premium
minimalist background, sharp clarity no jitter stable picture
```

### 11.3 Cinematic character scene

```text
cinematic film tone 35mm warm golden hour lighting, a man in his 40s
with weathered features sits at a wooden desk in a sun-drenched workshop
carefully carving walnut wood, slow push-in from medium shot to close-up
on his hands, dust motes float in the light beams from the window,
shallow depth of field background softly blurred, earthy color palette,
quiet ambient sound of wood shavings, avoid jitter avoid bent limbs,
stable picture no temporal flicker
```

### 11.4 Action sequence (time-coded)

```text
high-intensity cinematic fight in a misty bamboo forest 15 seconds
photorealistic, [0-4s]: wide establishing shot static camera mist
rolling between bamboo stalks golden hour light two fighters face each
other, [4-8s]: medium tracking shot the fighter in white lunges forward
with a spinning strike fluid orbital tracking follows the motion,
[8-12s]: low-angle power shot impact moment slow motion bamboo leaves
scatter, [12-15s]: pull-out wide shot the fighter in white stands
victorious rim light separating figure from mist, film grain anamorphic
texture, avoid bent limbs maintain face consistency
```

### 11.5 Full multimodal sequence

```text
15-second cinematic sequence 16:9 2K resolution, character from @Image1
walks through the environment from @Image2, camera performs slow orbit
matching @Video1's motion arc, scene transitions align with beat positions
of @Audio1, golden hour rim lighting shallow depth of field, maintain
character identity across all frames, avoid identity drift avoid jitter
avoid temporal flicker, sharp clarity stable picture
```

## 12. Iteration Strategy for Agents

Controlled iteration loop:
1. Construct a 5‑layer prompt with constraints and any time‑coding.
2. Generate 2–3 baseline outputs.
3. Score them for continuity and adherence.
4. Select the best candidate.
5. Modify exactly one dimension (camera, lighting, speed, style, or constraints).
6. Repeat until the score plateaus or the user is satisfied.

Global motion intensity modifiers:
- `dynamic motion`
- `vibrant energy`

These amplify existing motion patterns without inventing new ones.

## 13. Minimal Internal Schema

A simple internal schema LLMs can fill and render to Seedance text:

```json
{
  "subject": {
    "description": "woman in her late 20s, tight dark curls at ear length, small silver hoop in left ear, wearing a fitted black turtleneck, neutral expression",
    "count": 1
  },
  "action": {
    "primary": "she slowly turns toward the camera, breeze lifting the hem of her skirt, eyes narrowing against the light",
    "secondary": null
  },
  "camera": {
    "movement": "slow push-in",
    "speed": "gentle",
    "phases": [
      {"start": 0, "end": 4, "instruction": "static wide"},
      {"start": 4, "end": 10, "instruction": "slow push-in"}
    ]
  },
  "style": {
    "lighting": "golden hour rim light",
    "color_grade": "warm tone",
    "film_reference": "cinematic film tone, 35mm"
  },
  "constraints": {
    "base": [
      "avoid jitter",
      "avoid bent limbs",
      "avoid identity drift",
      "avoid temporal flicker",
      "no distortion, no stretching",
      "maintain face consistency"
    ],
    "quality_suffix": "sharp clarity, natural colors, stable picture, no blur, no ghosting, no flickering"
  },
  "time_coded": false,
  "references": {
    "images": ["@Image1", "@Image2"],
    "videos": ["@Video1"],
    "audio": ["@Audio1"]
  }
}
```
