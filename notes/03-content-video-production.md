# AI Video Production System — Implementation Guide

## Human Summary
the ai video production system (complete implementation guide) ( https://x.com/knoxtwts/status/2043091190007107789?s=20 )
This guide turns the X article into a practical system for building an AI agent that can generate scalable UGC-style video ads and short-form videos. The core idea is to stop treating AI video as one model doing everything and instead use a pipeline: generate a consistent character image first, create pose and scene variations from that character, choose the right video model for each shot type, then add audio cleanup and anti-AI realism passes.

In this workflow, Higgsfield is used as the character foundation, especially with structured JSON prompts instead of plain text. Kling v3 Pro is used mainly for talking-head dialogue shots, Veo 3.1 for more cinematic or product-consistent B-roll, and Seedance 2.0 for motion transfer, template replication, and localization using image/video/audio references.

The article also argues that realism comes less from bigger prompts and more from controlling the details that usually look fake in AI output: color grading, minor asymmetry, short shot lengths, natural pauses, room tone, light camera shake, and imperfect speech. For an AI agent project, the important takeaway is to encode these as explicit pipeline rules rather than leaving them to the model.

---

## Source Context

Source article title: **the ai video production system (complete implementation guide)**  
Source URL: https://x.com/knoxtwts/status/2043091190007107789?s=20  
Author handle: `@knoxtwts`  
Published: Apr 12, 2026

This document is a cleaned, implementation-focused rewrite intended for:
- humans who need a readable overview first,
- LLMs or AI agents that need structured instructions,
- developers building agentic pipelines for AI video production.

---

## System Overview

### Main stack

1. **Character engine**: Higgsfield with JSON prompting for consistent, realistic character images.
2. **Character variation engine**: img2img + structured pose/environment prompts to create multiple shots of the same character.
3. **Dialogue video engine**: Kling v3 Pro for talking-head scenes and short multi-shot dialogue clips.
4. **Cinematic/product engine**: Veo 3.1 for visual consistency and B-roll.
5. **Motion transfer/template replication**: Seedance 2.0 using `@Image`, `@Video`, and `@Audio` references.
6. **Voice cleanup stack**: CapCut normalization first, ElevenLabs transformation second.
7. **Post-production realism layer**: film grain, room tone, micro-pauses, natural filler words, and slight camera shake.

### Core principle

Do **not** ask one model to do everything. Split the workflow into specialized stages:
- identity generation,
- scene variation,
- lip-synced dialogue,
- motion/style transfer,
- audio normalization,
- realism finishing.

---

## Agent Architecture

A useful AI agent implementation can be broken into the following modules.

### 1. Campaign planner
Inputs:
- product/offer,
- target demographic,
- platform,
- language,
- desired style or creative references.

Outputs:
- campaign brief,
- shot list,
- character specification,
- script length constraints,
- model routing plan.

### 2. Character generator
Responsibilities:
- create a master character reference in Higgsfield,
- use JSON prompt templates instead of plain natural language,
- maintain campaign-specific demographic settings.

Outputs:
- master reference image,
- saved JSON prompt blueprint,
- optional style/color directives.

### 3. Variation generator
Responsibilities:
- produce 4–6 scene or pose variations from the same character,
- add environmental clutter and asymmetry,
- avoid slideshow-like repetition.

Outputs:
- scene-specific reference images,
- pose-specific prompt set.

### 4. Script and timing controller
Responsibilities:
- enforce speaking-speed limits,
- add filler words and pauses,
- split long scripts into model-safe chunks.

Key rule from article:
- use roughly **2.5 words per second**.

Derived examples:
- 30 seconds ≈ 75 words max,
- 15 seconds ≈ 38 words max.

### 5. Model router
Responsibilities:
- select model per shot type.

Suggested routing:
- **Kling v3 Pro**: talking head, short dialogue, multi-shot same-environment clips.
- **Veo 3.1**: cinematic B-roll, product consistency, environment continuity.
- **Seedance 2.0**: motion transfer, template replication, choreography, localization, reference-driven generation.

### 6. Audio pipeline controller
Responsibilities:
- normalize voice first,
- transform voice second,
- add room tone and pacing fixes.

### 7. Realism finisher
Responsibilities:
- add anti-AI artifacts intentionally,
- ensure imperfect human-like timing and texture,
- reduce “too clean” output.

### 8. Assembler/editor
Responsibilities:
- merge model outputs,
- keep shots under quality limits,
- apply grain/shake/audio layers,
- export final platform-specific variants.

---

## Character Engine

### Why Higgsfield mattered in the article

The article says character generation was the main bottleneck until Higgsfield was used with a structured JSON prompt. Plain-text prompts reportedly led to flatter color range and less consistent quality, while JSON acted more like a visual blueprint.

### Implementation rule

Your agent should treat character generation as a **schema-driven task**, not a freeform prompt task.

### Recommended JSON structure categories

Use keys like:
- `image_type`
- `genre`
- `orientation`
- `aspect_ratio`
- `composition`
- `subject`
- `environment`
- `lighting`
- `color_palette`
- `focus_and_clarity`
- `camera_characteristics`
- `stylistic_notes`
- `recreation_guidelines`

### Important design insight

The exact person can change by campaign, but the **schema should stay stable**. Your agent should:
- preserve the same JSON structure,
- only swap demographic and stylistic fields,
- save the successful prompt as a reusable “character blueprint.”

### Suggested agent data model

```json
{
  "campaign_id": "string",
  "character_id": "string",
  "base_model": "higgsfield-nano-banana-2",
  "prompt_schema_version": "v1",
  "identity_traits": {
    "gender_presentation": "string",
    "approximate_age": "string",
    "ethnicity_or_look": "optional string",
    "hair": {},
    "skin": {},
    "clothing": {}
  },
  "environment_defaults": {},
  "lighting_defaults": {},
  "color_directives": {},
  "recreation_guidelines": {}
}
```

---

## Color Grading Workflow

### Problem

The article claims Nano Banana Pro can oversaturate by default, making images look artificial even when the face is realistic.

### Proposed fix

Use a **reference-image color grading pipeline**:
1. Collect 5–7 aesthetic references from Pinterest.
2. Pass them to Gemini.
3. Ask Gemini to extract color grading characteristics, including shadows, midtones, highlights, and hex values.
4. Add the resulting grading notes to the Higgsfield JSON prompt as a color directive.

### Agent implementation

Your agent can treat color grading as a pre-processing stage.

#### Inputs
- reference images,
- desired mood or aesthetic,
- target platform or brand tone.

#### Processing
- vision model summarizes palette,
- normalize into structured fields,
- inject into image-generation schema.

#### Example intermediate structure

```json
{
  "color_palette": {
    "dominant_colors": ["#hex1", "#hex2", "#hex3"],
    "shadow_tones": ["#hexA"],
    "midtone_tones": ["#hexB"],
    "highlight_tones": ["#hexC"],
    "white_balance": "slightly warm",
    "saturation": "moderate",
    "tone_curve": "soft contrast with lifted shadows"
  }
}
```

### Key insight

Instead of prompting “make it cinematic” or “make it realistic,” use **measured color directives** based on reference imagery.

---

## Character Variation System

### Problem

One anchor image is not enough. Reusing one image across scenes makes the result look like a slideshow.

### VisionStruct method from article

For each variation:
1. Start with the **pose first**.
2. Add specific environment details.
3. Add anti-AI imperfections.
4. Keep total prompt length in the **150–250 word** range.

### Prompt construction order

#### A. Pose first
Examples:
- seated in driver seat,
- left hand on wheel,
- torso turned toward camera,
- leaning onto counter,
- looking down at phone while smiling.

#### B. Environment next
Examples:
- takeout bag in passenger seat,
- concrete parking garage through rear glass,
- morning sun flare at 2 o’clock,
- cluttered kitchen counter,
- half-open laptop on desk.

#### C. Anti-AI details last
Examples:
- slight under-eye circles,
- one flyaway hair crossing eyebrow,
- 2–3% visible skin texture,
- asymmetrical smile,
- minor posture tension.

### Agent rules

Always generate:
- 1 master identity image,
- 4–6 pose/environment variants,
- optional background alternatives.

Never send the same reference image directly into all final scene generations unless the goal is a deliberately static format.

---

## Model Selection Matrix

| Use case | Recommended model | Why |
|---|---|---|
| Talking-head dialogue | Kling v3 Pro | Best current fit in article for lip-synced dialogue and multi-shot clips |
| Cinematic B-roll | Veo 3.1 | Strong for visual consistency and ingredient locking |
| Product + character consistency | Veo 3.1 | Ingredient mode can keep product and character stable |
| Motion transfer | Seedance 2.0 | Can apply movement from reference video to custom image |
| Template replication | Seedance 2.0 | Can borrow camera work and pacing from a winning creative |
| Multi-language localization | Seedance 2.0 | Can align visuals with alternate-language audio |

### Routing heuristic for an agent

```text
if shot_type == "talking_head" or shot_type == "dialogue":
    use Kling v3 Pro
elif shot_type == "cinematic_broll" or requires_product_locking:
    use Veo 3.1
elif requires_motion_transfer or creative_replication or localization:
    use Seedance 2.0
```

---

## Kling v3 Pro Notes

### Best use case

Use Kling for short dialogue scenes, especially talking-head UGC style video.

### Important constraints from article

- Keep prompts under the **512 character limit**.
- Use **maximum 2 prompts/shots per generation**.
- More than 2 reportedly degrades quality.
- Avoid generating more than roughly **10 seconds** if lip sync quality is critical.

### Prompt structure pattern

Kling prompts in the article combine:
- shot framing,
- environment,
- lighting,
- small physical actions,
- spoken line,
- emotion/tone,
- mandatory naturalism footer.

### Mandatory naturalism footer pattern

The article strongly recommends appending guidance like:
- natural blinking,
- no over-reaction,
- no exaggerated facial movements,
- natural hand gestures,
- consistent `Voice_id`,
- tone modifier,
- shot type and camera movement.

### Suggested agent prompt builder

```text
[shot framing], [camera style].
[environment], [lighting].
[subject action].
She says: "[script chunk]"
[naturalism footer]
```

### Example footer template

```text
natural blinking, NO over-reaction, no exaggerated facial movements.
natural hand gestures. Voice_id: Voice_1.
tone: casual, slightly concerned.
Frontal medium shot, cinematic handheld.
```

### Dialogue pacing logic

The article’s rule of thumb should be enforced in code:

```python
max_words = floor(duration_seconds * 2.5)
```

If the script exceeds this threshold, the agent should:
- shorten the line,
- split it into more shots,
- or increase duration.

---

## Seedance 2.0 Notes

### Why it matters

Seedance is the reference-heavy model in this stack. It allows image, video, and audio inputs that get auto-labeled as `@Image1`, `@Video1`, `@Audio1`, etc.

### Input limits mentioned in article

- up to 9 images,
- up to 3 videos,
- up to 3 audio files,
- 12 total inputs,
- output duration 4–15 seconds,
- native 2K resolution mentioned in article.

### Core uses

#### 1. Motion transfer
Prompt pattern:
```text
@Image1 performs the choreography from @Video1.
```

#### 2. Template replication
Prompt pattern:
```text
Replace the person in @Video1 with the character from @Image1.
Reference @Video1's camera work, transitions, and editing rhythm.
Product from @Image2 replaces original product.
```

#### 3. Localization
Prompt pattern:
```text
@Video1 with lip sync matched to @Audio1.
```

### Strong agent use case

This is a great module for **creative cloning with owned assets**:
- detect winning ad format,
- download or ingest it as reference,
- replace actor/product,
- preserve pacing and motion language.

### Suggested abstraction

```json
{
  "mode": "motion_transfer | template_replication | localization",
  "references": {
    "images": [],
    "videos": [],
    "audio": []
  },
  "prompt_template": "string"
}
```

---

## Veo 3.1 Notes

### Best use case from article

Use Veo for:
- cinematic B-roll,
- product consistency,
- character/product ingredient locking,
- first-to-last-frame environment consistency.

### Implementation takeaway

The agent should route Veo jobs when the scene depends more on **visual continuity** than on speech.

### Good fits
- product shots,
- cutaway footage,
- brand atmosphere,
- visual proof scenes,
- consistent environment transitions.

---

## Voice Pipeline

### Problem

The article says AI UGC often fails because cadence is too even, breaths are too clean, and emphasis sounds predictable.

### Two-step fix

#### Step 1: CapCut voice normalization
Use CapCut’s voice-change functionality with a base voice across all spoken sections.

Expected effect according to article:
- removes weird accents,
- removes mismatches,
- reduces robotic artifacts,
- creates a cleaner normalized base.

#### Step 2: ElevenLabs voice transformation
Take the normalized audio into ElevenLabs Voice Transform and apply a realistic voice profile.

### Why this order matters

The article explicitly says:
- CapCut first = normalization,
- ElevenLabs second = character voice transformation.

The claim is that skipping normalization makes ElevenLabs output less consistent because source audio is already uneven.

### Additional realism layer

Add **ambient room tone at -28 dB** beneath the audio before final export.

### Agent implementation stages

1. Extract raw dialogue audio.
2. Normalize via first-pass transform.
3. Run second-pass voice styling.
4. Add room tone bed.
5. Insert micro-pauses where needed.
6. remux with final video.

---

## Anti-AI Detection Layer

This is one of the most implementation-relevant parts of the article because it can become a deterministic post-processing checklist.

### Realism modifiers from article

#### Visual
- add **2–3% film grain**,
- add **2% camera shake** in the first 1–3 seconds,
- include asymmetry in images,
- include visible pore/skin texture,
- avoid perfection.

#### Audio/dialogue
- add filler words like “um,” “like,” “you know,”
- add **0.3–0.5 second micro-pauses** between thoughts,
- add **room tone at -28 dB**,
- avoid perfectly continuous speaking.

### Agent implementation checklist

```yaml
anti_ai_realism:
  film_grain_percent: 2-3
  opening_camera_shake_percent: 2
  opening_camera_shake_duration_sec: 1-3
  room_tone_db: -28
  filler_words: true
  micro_pause_sec: 0.3-0.5
  asymmetry_required: true
  visible_skin_texture: true
```

### Important concept

The article’s realism method is based on adding **controlled imperfection**.

---

## Complete Workflows

## Workflow 1: Solo presenter UGC

Target: 30 seconds, 4 scenes.

1. Generate master character in Higgsfield using JSON blueprint.
2. Create 4 scene variations with img2img.
3. Write script constrained to about 75 words.
4. Split into two Kling generations:
   - video A: scenes 1–2,
   - video B: scenes 3–4.
5. Assemble in editor.
6. Add grain, opening shake, voice pipeline, room tone.

### Agent pseudocode

```text
create_character_blueprint()
generate_master_character()
generate_scene_variants(count=4)
script = build_script(max_words=75, include_fillers=True)
clips = generate_kling_multishot(script_chunks=2x2_shots)
normalized_audio = process_voice_pipeline(clips)
final = assemble(clips, normalized_audio, realism_fx=True)
```

## Workflow 2: Motion transfer ad

1. Find winning creative from TikTok or Instagram.
2. Generate matching character in Higgsfield.
3. Upload winning creative as `@Video1`.
4. Upload character as `@Image1`.
5. Upload product as `@Image2`.
6. Use Seedance template-replication prompt.
7. Run final audio pass.

## Workflow 3: Multi-language campaign

1. Create master English version.
2. For each target language:
   - generate translated target audio,
   - upload original visual as `@Video1`,
   - upload target language audio as `@Audio1`,
   - use Seedance lip-sync/localization prompt.
3. Export language-specific versions.

---

## Failure Modes

The article highlights several recurring problems. These are ideal to convert into agent guardrails.

### 1. Same face in every scene
Fix:
- require 4–6 pose variants before scene generation.

### 2. Too many Kling shots in one generation
Fix:
- hard cap Kling generations at 2 shots.

### 3. Overlong lip-sync generations
Fix:
- keep dialogue scenes short,
- warn above 10 seconds,
- split automatically.

### 4. Perfect audio
Fix:
- inject filler words, pauses, breaths, and room tone.

### 5. Missing ambient noise
Fix:
- automatically add a low-level room tone layer.

### 6. Over-prompting
Fix:
- keep Kling prompts focused on one primary action per shot,
- validate 512-char ceiling before submission.

### 7. Skipping audio normalization
Fix:
- make CapCut-style normalization mandatory before final voice transform.

### 8. Reused background ingredients
Fix:
- vary environments when possible,
- maintain a scene diversity score.

---

## Cost Model From Article

### Unit costs mentioned
- Higgsfield Nano Banana Pro image: about **$0.08–0.09** each.
- Kling v3 Pro 15-second generation: about **$4.70**.
- Seedance generation: about **$0.50–0.80**.
- Veo 3.1: about **$0.75 per second**.

### Standard 30-second UGC ad estimate from article
- 4–6 character images: about **$0.50**,
- 2 Kling generations: about **$9.40**,
- voice pipeline: about **$0.10**,
- total: about **$10 per finished ad**.

### Scale claim in article
The article also claims that at 200+ videos per month, effective per-video cost can drop to about **$0.38–0.50**, with batch generation and voice cloning efficiencies.

### Agent budgeting logic

```json
{
  "image_cost": 0.09,
  "kling_15s_cost": 4.70,
  "seedance_cost_range": [0.50, 0.80],
  "veo_cost_per_second": 0.75,
  "voice_pipeline_cost": 0.10
}
```

Use this to estimate cost before generation and choose lower-cost paths where acceptable.

---

## Demographic Prompt Variants

The article suggests modifying the same Higgsfield schema for different market segments.

### Older woman / health offers
Suggested changes:
- age 55–65,
- salt-and-pepper or silver-grey hair,
- natural age lines and sun spots,
- kitchen setting,
- coffee/pill bottle context,
- more natural “caught on camera” pose.

### Gym guy / fitness offers
Suggested changes:
- male, age 28–35,
- short slightly sweaty hair,
- flushed skin,
- locker room or home gym,
- fitted tank top.

### Professional male / finance-tech offers
Suggested changes:
- male, age 30–45,
- clean-cut professional styling,
- home office with monitor/desk,
- webcam or video-call aesthetic.

### Agent design recommendation

Represent demographic variants as structured config overlays applied to one common base schema.

---

## Recommended Agent Rules

## Hard constraints

- Use JSON for character generation when supported.
- Generate 4–6 character variations per campaign.
- Use 2.5 words/sec script budgeting.
- Cap Kling at 2 shots/generation.
- Keep Kling prompts under 512 characters.
- Prefer short dialogue clips.
- Add room tone, pauses, and grain by default.

## Soft heuristics

- Prefer realistic clutter over sterile environments.
- Prefer slight asymmetry over beauty-filter perfection.
- Prefer references for color and motion rather than descriptive adjectives.
- Prefer specialized models per shot over single-model pipelines.

---

## Suggested Prompt Templates

## Higgsfield character generation template

```text
Use a structured JSON prompt describing:
- image type
- genre
- orientation/aspect ratio
- composition
- subject identity and pose
- environment
- lighting
- color palette
- focus/clarity
- camera characteristics
- stylistic notes
- recreation guidelines
```

## Variation template

```text
[POSE FIRST]
[ENVIRONMENT DETAILS]
[ANTI-AI IMPERFECTIONS]
[LIGHTING + CAMERA CONTEXT]
```

## Kling dialogue template

```text
[Shot framing], [camera style].
[Location/environment], [lighting].
[Physical action].
She says: "[dialogue line]"
Natural blinking, NO over-reaction, no exaggerated facial movements.
Natural hand gestures. Voice_id: [voice_id]. tone: [tone].
[Shot type], [camera movement].
```

## Seedance motion transfer template

```text
@Image1 performs the choreography from @Video1.
[setting/style instructions]
```

## Seedance template replication template

```text
Replace the person in @Video1 with the character from @Image1.
Reference @Video1's camera work, transitions, and editing rhythm.
Product from @Image2 replaces the original product.
Keep the same energy and pacing.
```

## Seedance localization template

```text
@Video1 with lip sync matched to @Audio1.
```

---

## Example Agent Pipeline Spec

```yaml
pipeline:
  - step: plan_campaign
    output: brief

  - step: build_character_schema
    model: higgsfield
    output: master_character

  - step: derive_color_profile
    model: gemini
    input: pinterest_references
    output: color_directives

  - step: generate_variations
    model: higgsfield_img2img
    count: 4-6
    output: scene_references

  - step: write_script
    constraints:
      words_per_second: 2.5
      include_fillers: true
      include_micro_pauses: true

  - step: route_shots
    rules:
      talking_head: kling_v3_pro
      cinematic_broll: veo_3_1
      motion_transfer: seedance_2_0

  - step: generate_dialogue_clips
    constraints:
      kling_max_shots: 2
      kling_max_chars: 512

  - step: normalize_audio
    tool: capcut_like_stage

  - step: transform_voice
    tool: elevenlabs_like_stage

  - step: apply_realism_pass
    settings:
      film_grain_percent: 2-3
      room_tone_db: -28
      opening_camera_shake_percent: 2
      micro_pause_sec: 0.3-0.5

  - step: assemble_export
    output: final_variants
```

---

## Best LLM-Readable Takeaways

If you want an LLM or autonomous agent to reproduce the article’s method well, the most important implementation ideas are:

1. Treat character creation as a **structured schema problem**, not a plain prompt problem.
2. Separate identity generation from scene generation.
3. Generate multiple pose/environment variants before video synthesis.
4. Route shots to different models based on job type.
5. Enforce timing constraints before generation.
6. Add imperfection intentionally as part of post-processing.
7. Use reference-driven color and motion transfer instead of vague style words.
8. Convert failure modes into code-level validation rules.

---

## Cautions

Some claims in the original article are operational opinions or creator heuristics rather than independently verified benchmarks. For an agent project, treat them as **strong starting assumptions to test**, especially:
- model quality comparisons,
- demographic detection claims,
- exact cost efficiency at scale,
- specific output quality rankings.

A robust implementation should log:
- prompt version,
- model version,
- generation settings,
- cost per asset,
- success/failure rate,
- human review score.

---

## Minimal Build Plan

If you wanted to implement the article quickly in an AI agent project, the smallest useful version would be:

1. Build a **character JSON template engine**.
2. Add a **variation generator** that outputs 4–6 pose prompts.
3. Add a **script limiter** using 2.5 words/sec.
4. Add a **model router** for Kling / Veo / Seedance.
5. Add a **realism post-process config** for grain, pauses, room tone, and shake.
6. Add a **campaign compiler** that returns all prompts, settings, and generation sequence in machine-readable form.

That would already capture most of the article’s practical value.
