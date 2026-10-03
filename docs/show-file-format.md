# AION Show File Format — Specification v1

**Audience:** developers building a show authoring tool (an Unreal Engine plugin
is the expected first host) that reads and writes AION show files.

**Status:** describes the format as implemented and shipping. The normative
reference implementation is
[`src/aion_show_system/show/timeline.py`](../src/aion_show_system/show/timeline.py);
where this document and that file disagree, the file is right and this document
is a bug.

A show file is the **only** thing the playback system knows about a show. There
is no companion database, no per-venue patch file and no side-car metadata: what
the authoring tool exports is what plays. That makes the file the whole contract
between the two tools, which is why this document is as long as it is.

---

## 1. Conformance language

**MUST** / **MUST NOT** — required for the file to load and play correctly.
**SHOULD** — required for the file to behave the way an operator expects; the
runtime will not stop you. **MAY** — permitted, no opinion.

"The runtime" means the AION Show System playback application. "The authoring
tool" means the exporter this spec is written for.

---

## 2. File identity, encoding and discovery

| Property | Requirement |
| --- | --- |
| Format | JSON, a single object at the top level |
| Encoding | UTF-8, **no BOM** — a BOM makes the file unparseable |
| Extension | `.show.json` (preferred) or `.json` |
| Line endings | LF preferred; irrelevant to the parser |
| Size | No hard limit; see §7.5 for practical guidance |

The runtime discovers shows by scanning its configured `shows_dir`
(`ShowLibrary.files`). Two things about that scan matter to an exporter:

- **The scan is not recursive.** Files in subdirectories of `shows_dir` are
  invisible to triggers. Export flat.
- **Files are visited in sorted filename order**, and the first match wins for
  every kind of lookup. Duplicate show names resolve arbitrarily but stably —
  see §3.1.

### 2.1 How a show is referenced

Triggers (a schedule entry, a WebSocket frame, `--trigger` on the command line,
or another show's `next_show`) all carry one string, resolved by
`ShowLibrary.find` in this order:

1. an absolute or working-directory-relative **path** to a file;
2. a **file name** inside `shows_dir`, with or without `.show.json` / `.json`;
3. the **`name` field inside the file**, matched case-insensitively;
4. failing all of those, the trigger is refused and logged.

Consequence for the authoring tool: `name` is not decoration, it is an
addressable identifier. See §3.1.

---

## 3. Document structure

```jsonc
{
  "version": 1,                                  // integer, always 1
  "name": "Act One",                             // string
  "media": { "path": "...", "start_ms": 0 },     // object | null
  "duration_ms": 60000,                          // integer ms
  "loop": false,                                 // boolean
  "allow_override": true,                        // boolean
  "next_show": "Act Two",                        // string | null
  "tracks": [ /* §5 */ ]                         // array
}
```

| Field | Type | Required | Default when absent | Notes |
| --- | --- | --- | --- | --- |
| `version` | integer | SHOULD | — | Always write `1`. See §3.2. |
| `name` | string | SHOULD | `"Untitled Show"` | Addressable identifier, §3.1 |
| `media` | object \| null | no | `null` (timeline-only show) | §4 |
| `duration_ms` | integer | no | `0` → derived, §6.2 | Milliseconds |
| `loop` | boolean | no | `false` | §6.4 |
| `allow_override` | boolean | no | `true` | §6.5 |
| `next_show` | string \| null | no | `null` | §6.6 |
| `tracks` | array | no | `[]` | §5 |

All fields are read by `Show.from_dict`; every one of them has a working
default, so the minimal legal show file is `{}`. That is a real, loadable show:
no media, no tracks, zero duration. Exporters SHOULD still write every field
explicitly, because an explicit file survives a reader that changes its
defaults.

### 3.1 `name`

`name` is what an operator types into a trigger and what appears in the show
list in the UI. Therefore:

- `name` **SHOULD be unique** across everything in `shows_dir`. Two files with
  the same `name` are both loadable, but a trigger naming it will always
  resolve to whichever sorts first, silently.
- `name` **SHOULD be stable** once a show ships. Scheduled triggers in
  `config.json` and `next_show` in other show files reference it by string;
  renaming a show breaks those references with no error until the trigger fires
  and is refused.
- The authoring tool SHOULD warn on rename and SHOULD offer to update
  `next_show` references it can see.
- Filename and `name` need not match, but keeping them aligned
  (`act-one.show.json` ↔ `"Act One"`) makes both lookup routes work.

### 3.2 `version`

The writer emits `"version": 1`. **The reader ignores it entirely** — there is
no version check in `Show.from_dict`. A future v2 document handed to a v1
runtime is not rejected; it is silently misread, with unknown fields dropped
(§8.1). Exporters MUST write `1` and MUST NOT invent higher version numbers
before the runtime learns to check.

---

## 4. `media`

```json
{ "path": "D:/shows/media/act-one.wav", "start_ms": 0 }
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `path` | string | **yes** | Path to an audio or video file |
| `start_ms` | integer | no | **Reserved — currently ignored**, §9.1 |

- If `media` is absent, `null`, or an **empty object**, the show is
  *timeline-only*: it runs on a free-running clock with no media (§6.1).
- If `media` is a non-empty object with **no `path`**, loading raises and the
  whole show fails to load. The authoring tool MUST NOT emit `{"start_ms": 0}`
  without a path — emit `null` instead.

### 4.1 Path handling — read this twice

The runtime resolves `media.path` with `Path(path).expanduser().resolve()`,
which is relative to the **process working directory of the playback
application**, not to the location of the show file. A show file that says
`"media/act-one.wav"` will find its media only if the operator happens to have
launched the app from the right directory.

- Exporters **SHOULD write absolute paths**, using the deployment's own layout
  (`/opt/aion/media/...`, `D:/shows/media/...`).
- `~` is expanded, so `~/media/act-one.wav` is a portable alternative when the
  show runs as a known user.
- On Windows, **use forward slashes**. They work everywhere in Qt and avoid a
  class of JSON escaping bugs (`"D:\\shows"` is legal JSON; `"D:\shows"` is
  not, and `\s` will make the file unparseable).
- The authoring tool SHOULD offer a "media root" setting and export
  `<media root>/<file>` so a project can be re-pointed at the show machine's
  layout without re-authoring.

### 4.2 What happens when the media is missing

If `media.path` does not exist when the show loads, the runtime logs the error,
surfaces it in the UI — and **the show then sits frozen at t = 0 with DMX
live**, holding the first frame indefinitely. It does not fall back to
timeline-only playback, and it never finishes, so `next_show` never fires.

This is the single most expensive authoring mistake the format allows. The
authoring tool SHOULD validate that every exported `media.path` exists at export
time, and SHOULD provide a "verify against target machine" step if it can.

### 4.3 Supported media

Playback goes through Qt Multimedia's bundled FFmpeg backend on every target
platform, so support is consistent across Windows, macOS, Linux and Raspberry
Pi: H.264 / H.265 / MPEG-4 video, MP3 / AAC / FLAC / WAV audio. Prefer WAV or
FLAC for anything cue-critical: uncompressed audio has no decoder priming delay
to steal the first moments of the show.

---

## 5. `tracks` and `keyframes`

```json
{
  "name": "Wash",
  "universe": 1,
  "keyframes": [
    { "time_ms": 0,    "values": { "1": 0,   "2": 0 } },
    { "time_ms": 2500, "values": { "1": 255, "2": 128 } }
  ]
}
```

### 5.1 Track object

| Field | Type | Required | Default | Notes |
| --- | --- | --- | --- | --- |
| `name` | string | no | `"Track"` | Display only; not addressable, need not be unique |
| `universe` | integer | no | `1` | §5.2 |
| `keyframes` | array | no | `[]` | §5.3 |
| `wide` | array | no | `[]` | §5.4 |

A track is a **rendering layer**, not a fixture and not a channel group. Several
tracks MAY drive the same channels in the same universe; they merge
highest-takes-precedence (§6.3.4). A track with no keyframes is legal and
contributes nothing except its universe to the output set (§6.3.1).

### 5.2 `universe`

The value is used verbatim as the wire universe number. It is **not validated at
load time** — an illegal value fails later, at send time, when the rig is
already live.

| Protocol | Legal range | Notes |
| --- | --- | --- |
| sACN (E1.31) | **1–63999** | Universe 0 raises at send time |
| Art-Net | 0–32767 | Packed into SubUni/Net |

**Export universes ≥ 1.** Universe 0 is legal Art-Net and illegal sACN, and a
show authored on an Art-Net rig that lands on an sACN venue will fail. The
runtime default of `1` exists for exactly this reason. The authoring tool SHOULD
reject universe numbers outside 1–63999 and SHOULD warn above 32767.

### 5.3 Keyframe object

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `time_ms` | integer | **yes** | Milliseconds from the start of the show |
| `values` | object | no | Map of channel → level; defaults to `{}` |

- `values` **keys are decimal channel numbers as JSON strings**: `"1"`, not `1`
  (JSON has no integer keys) and not `"ch1"`. A non-numeric key raises and the
  show fails to load.
- **Channels are 1-based, 1–512 inclusive.** A channel outside that range raises
  `ValueError` and the show fails to load. This is the one hard validation in
  the format — use it: it is cheaper to fail at load than to play a show with a
  silently dropped cue.
- **Levels are integers 0–255.** Out-of-range values are silently clamped; JSON
  floats are truncated toward zero, then clamped. The authoring tool SHOULD
  clamp and round itself rather than relying on that, so what it previews is
  what plays.
- `time_ms` MUST be a non-negative integer. Floats are truncated toward zero
  (`1000.9` → `1000`, `-1000.9` → `-1000`). **Negative times are accepted
  without complaint** and behave as "already applied at every time in the show"
  — never emit them.
- Keyframes MAY appear in any order in the file; the loader sorts them by
  `time_ms` on load, **stably**, so the file order of same-time keyframes is
  preserved and is significant (§6.3.3). Exporters SHOULD write them sorted
  anyway, because a sorted file is diffable and reviewable.
- Channel keys within one `values` object MUST be unique. JSON allows duplicate
  keys; the parser keeps the last, silently.
- `NaN`, `Infinity` and `-Infinity` MUST NOT be emitted. Python's JSON parser
  accepts them and they will corrupt a level or a time downstream.

### 5.4 `wide`

```json
{
  "name": "Head 1",
  "universe": 1,
  "wide": [[1, 2], [3, 4]],
  "keyframes": [
    { "time_ms": 0,    "values": { "1": 1, "2": 255, "3": 0, "4": 0 } },
    { "time_ms": 1000, "values": { "1": 2, "2": 0,   "3": 0, "4": 0 } }
  ]
}
```

Groups of channels that together carry **one value, most significant channel
first** — a 16-bit pan on channels 1 (coarse) and 2 (fine) is `[1, 2]`; a 24-bit
value is a three-element group. A group fades as one number and is split back
into bytes afterwards (§6.3), so the example above passes through `1/255 →
2/0` cleanly instead of kicking the fine channel to 128 at the midpoint.

- Every channel in a group MUST be within 1–512, a group MUST have at least two
  channels, and a channel MUST NOT appear in more than one group. Any of these
  raises `ValueError` and the show fails to load.
- A group only fades as a unit when the **next keyframe names every channel in
  it**. A keyframe that names only some of them fades those on their own, as
  if the group were not declared. Exporters that write every channel at every
  keyframe (§6.3.2) never hit this.
- Grouping is per track. The same channels MAY be grouped differently, or not
  at all, in another track on the same universe; merging (§6.3.4) is still
  per channel.
- Omit the field, or write `[]`, for a track with no multi-byte parameters.

---

## 6. Playback semantics (normative)

This section defines what the file *means*. An authoring tool that renders a
preview MUST implement this algorithm exactly, or the preview will lie.

### 6.1 The time base

`time_ms` is measured from **zero at the start of the media file** (or from the
start of the free-running clock, for a timeline-only show). It is not offset by
`media.start_ms` (§9.1) and there is no per-track time offset.

The runtime holds a media-anchored master clock that interpolates between the
media transport's coarse (~93 ms) position reports and slews rather than jumps
to correct drift, so cue times resolve to sub-millisecond precision even though
the transport is coarse. DMX frames are rendered from that clock at a fixed rate
— **40 Hz by default** (`dmx.fps` in the machine config), i.e. one frame every
25 ms.

Practical consequences:

- Authored times are honoured with sub-millisecond precision, but **observed
  output is quantised to the frame rate**. A snap lands on the next frame
  boundary, up to 25 ms late. This is inaudible against music and invisible on a
  rig; it matters only if the tool claims frame-exact preview.
- There is no benefit to authoring keyframes closer together than one frame
  (25 ms); intermediate keyframes between two rendered frames are still
  evaluated correctly, but nothing is transmitted between frames.

### 6.2 `duration_ms` and the end of the show

`effective_duration_ms` = `duration_ms` if non-zero, otherwise the `time_ms` of
the **last keyframe in any track**.

What that value is used for depends on whether the show has media:

| Show type | What ends it | Role of `duration_ms` |
| --- | --- | --- |
| With media | End of the media file | Display and UI only; does **not** end the show |
| Timeline-only | Clock reaching `effective_duration_ms` | **Authoritative** — the show's whole length |

So for a media-backed show, keyframes past the end of the media are simply never
reached, and a `duration_ms` shorter than the media does not truncate anything.
For a timeline-only show, `duration_ms` *is* the show. Exporters SHOULD always
write an explicit `duration_ms`: relying on "last keyframe" means a show whose
final cue is a blackout at 58 s silently becomes a 58 s show, losing its last
two seconds of intended hold.

Timeline-only completion is polled at 50 ms, so the end (and the loop point) has
±50 ms of slop.

### 6.3 Rendering — the exact algorithm

For a timeline position `t` (float milliseconds), the show renders to one
512-byte frame per universe:

```text
render(show, t):
    universes = sorted(set(track.universe for track in show.tracks))
    frames    = { u: bytes[512] all zero  for u in universes }

    for track in show.tracks:
        frame = frames[track.universe]
        for (channel, level) in levels_at(track, t):
            i = channel - 1
            if level > frame[i]:            # highest takes precedence
                frame[i] = level

    return frames
```

```text
levels_at(track, t):                        # keyframes sorted ascending, stable
    state = {}                              # channel -> level
    prev  = null
    idx   = 0
    for kf in track.keyframes:
        if kf.time_ms > t: break
        state.update(kf.values)             # later keyframes overwrite earlier
        prev = kf
        idx += 1

    next = track.keyframes[idx] if idx < len(track.keyframes) else null
    if next == null or prev == null:
        return state                        # holding, or before the first keyframe

    span     = next.time_ms - prev.time_ms  # always > 0 here
    fraction = (t - prev.time_ms) / span

    out = copy(state)
    for (channel, target) in next.values:
        start = state.get(channel, 0)       # NOTE: defaults to 0, see §6.3.2
        out[channel] = clamp(round_half_even(start + (target - start) * fraction))

    for group in track.wide:                # §5.4; skipped unless fully named
        if not all(channel in next.values for channel in group): continue
        start  = pack(group, state)         # bytes -> one integer, MSB first,
        target = pack(group, next.values)   #   missing channels read as 0
        packed = clamp_to_width(round_half_even(start + (target - start) * fraction))
        out.update(unpack(group, packed))   # one integer -> bytes, MSB first
    return out
```

Rounding is **round-half-to-even** (Python's `round`): `127.5 → 128`,
`128.5 → 128`. Implement that exactly for a bit-identical preview; C-style
`floor(x + 0.5)` differs on exact halves.

#### 6.3.1 Universes, blackouts, and what a show owns

- **A show owns every universe it names, completely.** Each frame starts at all
  zeros, so any channel not driven by a keyframe is actively sent as 0 — not
  left alone, not merged with anything else on the network. There is no
  "release" or "passthrough" concept.
- **A universe with no track is never transmitted at all.** Fixtures on it hold
  their last received values or fall back to their own failsafe. If a show is
  meant to black out a universe, it MUST contain a track on that universe.
- Stopping a show sends an explicit all-zero frame to every universe the show
  names, then drops the output.

#### 6.3.2 The fade-start rule — the most important gotcha in the format

A fade toward a channel's next value **starts at the previous keyframe in the
track, whatever that keyframe was about**, and starts from 0 if the channel has
no value yet. The previous keyframe does not have to mention the channel.

```jsonc
// WRONG: channel 2 fades up slowly across the whole first six seconds,
// because the previous keyframe in the track is the one at t=0.
"keyframes": [
  { "time_ms": 0,    "values": { "1": 255 } },
  { "time_ms": 6000, "values": { "2": 255 } }
]
// levels_at(2500) -> { "1": 255, "2": 106 }   <-- channel 2 is already up

// RIGHT: anchor channel 2 at its start value where the fade should begin.
"keyframes": [
  { "time_ms": 0,    "values": { "1": 255 } },
  { "time_ms": 5000, "values": { "1": 255, "2": 0 } },
  { "time_ms": 6000, "values": { "2": 255 } }
]
// levels_at(2500) -> { "1": 255 }
// levels_at(5500) -> { "1": 255, "2": 128 }
```

**Exporters MUST emit an explicit anchor keyframe at the start of every fade.**
An authoring tool almost certainly models a fade as a segment with its own start
time; the export step has to flatten that model into anchor + target pairs. Do
not assume the runtime knows where a fade was supposed to begin — it only knows
the previous keyframe.

The safe general rule: **at every keyframe time, write the value of every
channel the track is currently animating**, not just the ones that changed. It
costs bytes and removes the entire class of bug. A track that touches a few
dozen channels can afford to be fully explicit at every keyframe.

#### 6.3.3 Snaps, holds and same-time keyframes

- **Hold:** a channel keeps its last value until another keyframe names it, and
  after the last keyframe in a track it holds forever (or until the show ends).
- **Before the first keyframe** a track contributes nothing, which — because
  frames start at zero — means dark.
- **Fade:** any two keyframes naming the same channel.
- **Snap:** two keyframes with the same `time_ms`, where the *first* carries the
  pre-snap value and the *second* the post-snap value. Interpolation up to that
  moment targets the **first** of the pair, then at `t == time_ms` both are
  applied in file order and the second wins.

  ```jsonc
  { "time_ms": 0,    "values": { "1": 0 } },
  { "time_ms": 1000, "values": { "1": 0 } },     // hold flat up to the snap
  { "time_ms": 1000, "values": { "1": 255 } }    // snap at exactly 1000 ms
  ```

  Because same-time ordering is preserved but subtle, exporters MAY prefer the
  equivalent and more legible **1 ms pair** (`999` → `0`, `1000` → `255`), which
  produces an identical result on a 40 Hz output and survives any tool that
  re-sorts keyframes unstably. Pick one convention and apply it everywhere.

#### 6.3.4 Merging

Tracks sharing a universe merge **highest-takes-precedence** — the convention
every lighting desk uses for stacked playbacks. The consequences an authoring
tool must surface to its users:

- **A track cannot pull a channel down** below the level another track is
  holding on the same universe. Layering a "blackout" track over a live track
  does nothing.
- Merge order is irrelevant; the result is the max over all tracks.
- Two tracks fading the same channel in opposite directions produce a V, not a
  crossfade.

If the authoring tool offers a layered timeline UI, it SHOULD show the merged
result, because HTP is not what a compositing UI trains people to expect.

### 6.4 `loop`

- **With media:** looping happens in the media backend, which wraps without
  tearing down the decoder — gapless at the seam. The timeline wraps with the
  media.
- **Timeline-only:** the clock is seeked back to 0 when it reaches
  `effective_duration_ms`, polled at 50 ms.

**Rendering is stateless per frame, so nothing carries across the seam.** The
"hold last value" behaviour does not survive a wrap: at t = 0 every channel is
back to whatever the first keyframe of its track says, and any channel with no
keyframe at 0 is dark until its first keyframe.

Exporters SHOULD, for any looping show, **emit a keyframe at `time_ms: 0`
carrying every channel the show uses**, and SHOULD make the state at
`duration_ms` match the state at 0 — otherwise the loop point flashes. The
authoring tool is well placed to check this automatically and warn.

A looping show never finishes, so `next_show` on a looping show is dead
configuration. Warn on it.

### 6.5 `allow_override`

`false` means: while this show is **actually playing**, incoming triggers are
refused, logged, reported in the UI and returned to the caller. Once it
finishes, or is stopped by an operator, triggers land again. Default `true`.

Use it for content that must not be interrupted — a scheduled announcement, a
safety message, a sponsor spot with contractual runtime. A trigger naming the
show that is already playing is not refused.

### 6.6 `next_show`

Names the show to trigger when this one ends, resolved by the same rules as any
other trigger (§2.1). This is how a running order is chained without anything
outside the show files knowing about it.

- Chaining is a trigger, so it depends on the *next* show existing; a dangling
  `next_show` is logged and refused at the moment it fires, not at load. The
  authoring tool SHOULD validate chains across the whole project and SHOULD
  detect cycles (a cycle is legal and runs forever, which is sometimes intended
  — warn, do not block).
- `next_show` on a looping show never fires (§6.4).
- The chain fires exactly once per run, and it loads synchronously — the next
  show is already loading before the previous one has finished tearing down.
  There is no gap to schedule anything into.

---

## 7. Exporter requirements

### 7.1 Hard requirements (violations fail to load or misplay)

1. Emit UTF-8 without a BOM.
2. Emit channel keys as decimal strings, `"1"`–`"512"`, in range.
3. Emit integer `time_ms` ≥ 0 and integer levels 0–255.
4. Emit `media: null` for a timeline-only show, never a media object without
   `path`.
5. Emit an anchor keyframe at the start of every fade (§6.3.2).
6. Never emit `NaN` / `Infinity`.
7. Emit universes ≥ 1 (§5.2).

### 7.2 Strong recommendations

1. Write every top-level field explicitly, including `"version": 1`.
2. Write an explicit `duration_ms` (§6.2).
3. Write keyframes pre-sorted by `time_ms`.
4. Write absolute media paths with forward slashes (§4.1).
5. Write the full animated channel set at every keyframe of a track (§6.3.2).
6. For looping shows, make t = 0 and t = `duration_ms` agree (§6.4).
7. Validate that media files exist at export time (§4.2).
8. Keep `name` unique and stable, and update `next_show` references on rename
   (§3.1).

### 7.3 Validation the authoring tool SHOULD perform

The runtime's error handling is deliberately forgiving — a show machine that
boots unattended must come up and play whatever it can — which means most
authoring mistakes are silent. This table is what the runtime does, and
therefore what the authoring tool has to catch instead.

| Condition in the file | Runtime behaviour |
| --- | --- |
| Channel < 1 or > 512 | **Raises** — show fails to load, trigger refused, logged |
| `values` key not numeric | **Raises** — show fails to load |
| `media` object without `path` | **Raises** — show fails to load |
| Malformed JSON | Logged; show fails to load |
| Level > 255 or < 0 | Silently clamped |
| Level is a JSON float | Silently truncated toward zero, then clamped |
| `time_ms` is a float | Silently truncated toward zero |
| `time_ms` negative | Silently accepted; applies at every t |
| Keyframes unsorted | Silently sorted (stable) |
| Duplicate channel key in one `values` | Last wins, silently |
| Universe illegal for the protocol | Fails at **send** time, mid-show (sACN), or goes to the wrong rig (Art-Net) |
| Unknown fields anywhere | Silently ignored, and dropped on re-save (§8.1) |
| `media.path` missing on disk | Logged; **show freezes at t = 0 with DMX live** (§4.2) |
| Dangling `next_show` | Logged and refused when the chain fires |
| Duplicate `name` in `shows_dir` | First file in sorted order wins, silently |
| `duration_ms` absent | Derived from the last keyframe (§6.2) |

### 7.4 Building a preview in the editor

An in-editor preview that disagrees with the rig is worse than no preview. To
match the runtime exactly:

- Implement §6.3 verbatim, including round-half-to-even and the
  `state.get(channel, 0)` default.
- Sample at 40 Hz (or whatever the target machine's `dmx.fps` is) rather than at
  the editor's frame rate, if the goal is to show what the rig will receive.
- Render per universe, zero-filled, HTP-merged — do not preview tracks
  independently without also showing the merge.
- Preview the loop seam by rendering `duration_ms - 1` and `0` adjacently.

### 7.5 Size and shape guidance

There is no limit in the format, and the whole show is parsed into memory at
load. The cost that matters is per-frame: `levels_at` is a **linear scan of the
track's keyframes on every rendered frame**, 40 times a second, per track. A few
thousand keyframes across a show is unremarkable; a few hundred thousand — which
is what naive per-frame baking of a 30-minute show produces — will not hold
cadence on a Raspberry Pi.

Export **keyframes, not baked frames**. If the authoring tool's internal model is
curve-based (§9.2), sample each curve to a tolerance rather than at the editor
frame rate: a linear ramp needs two keyframes, not 1200.

---

## 8. Extensibility and round-tripping

### 8.1 Unknown fields are dropped, not preserved

`Show.from_dict` reads only the fields in §3 and `Show.to_dict` writes only those
fields. Any extra key — at any level — is ignored on load and **absent from the
file if the runtime ever re-saves it**. The runtime re-saves a show only on an
explicit operator save action, so this is not a routine data-loss path, but it is
a real one.

Therefore:

- The authoring tool MAY add its own keys (an `"authoring"` object at the top
  level is the suggested home) and MUST tolerate them being gone.
- The authoring tool MUST NOT store anything it cannot reconstruct — source
  project references, curve definitions, fixture patch, track colours — **only**
  in the show file. The show file is an export target; the authoring project is
  the source of truth.
- A re-import path (reading a show file back into the editor) MUST be able to
  work from the §3 fields alone.

### 8.2 Adding to the format

New fields require a runtime change; they cannot be adopted unilaterally by the
authoring tool, since the reader ignores what it does not know. Coordinate
additions against §9, and bump `version` only when the runtime learns to check
it.

---

## 9. Known gaps — v1 limits and v2 candidates

These are deliberate statements of what v1 does **not** have, so the authoring
tool does not model something the runtime will silently discard.

### 9.1 `media.start_ms` is reserved and currently ignored

It is parsed, round-tripped and never applied — media always starts at 0 and the
timeline is always anchored to media position 0. **Emit `0`.** Do not build a
"start the media at an offset" feature on it until the runtime implements it.

### 9.2 Interpolation is linear only

There are no easing curves, no bezier handles, no per-segment interpolation
mode, and no step/hold mode other than the same-time snap. An authoring tool
that offers curves MUST bake them to linear segments on export, to a tolerance
it chooses (see §7.5).

### 9.3 No per-track state

No mute, no solo, no enable flag, no intensity master, no time offset, no
colour, no grouping, no folders. `name` is the only track metadata that
survives. Mute and solo are editor-side concepts: resolve them at export by
omitting the track.

### 9.4 No fixture or patch model

Channels are raw DMX addresses. There is no fixture library, no channel roles
and no colour model. The one piece of fixture knowledge the file carries is the
`wide` grouping (§5.4), which exists because a coarse/fine pair interpolated as
two independent channels kicks the value half a coarse step every time the fine
channel wraps — an exporter with a multi-byte parameter MUST declare it.

The authoring tool is expected to hold the rest of the fixture model and
flatten it. That flattening is one-way: the show file cannot describe it.

### 9.5 No merge mode selection

HTP is the only merge, and it is not configurable per track or per show. LTP,
additive and priority-based merging do not exist.

### 9.6 Other absences

- No cue list, cue numbers, labels, markers, or tempo/beat grid.
- No per-show DMX output configuration — protocol, host and port live in the
  machine's `config.json`, not in the show. A show is portable across rigs
  precisely because it names universes and channels only.
- No conditional or interactive behaviour beyond `next_show`.
- No embedded media; `media.path` is always an external reference.
- No signing, checksums or provenance fields.
- No explicit end-of-show cue: a show's final DMX state is whatever holds until
  the blackout frame at stop (§6.3.1). Author an explicit blackout keyframe if
  the last look should not linger.

---

## 10. Complete reference example

A two-track, media-backed show that fades a wash up, snaps a strobe on, chases
two channels, blacks out, and chains to the next show.

```json
{
  "version": 1,
  "name": "Act One",
  "media": {
    "path": "D:/shows/media/act-one.wav",
    "start_ms": 0
  },
  "duration_ms": 12000,
  "loop": false,
  "allow_override": true,
  "next_show": "Act Two",
  "tracks": [
    {
      "name": "Wash",
      "universe": 1,
      "keyframes": [
        { "time_ms": 0,     "values": { "1": 0,   "2": 0 } },
        { "time_ms": 3000,  "values": { "1": 255, "2": 180 } },
        { "time_ms": 9000,  "values": { "1": 255, "2": 180 } },
        { "time_ms": 11500, "values": { "1": 0,   "2": 0 } }
      ]
    },
    {
      "name": "Strobe and chase",
      "universe": 1,
      "keyframes": [
        { "time_ms": 0,    "values": { "10": 0, "11": 0, "12": 0 } },
        { "time_ms": 4000, "values": { "10": 0, "11": 0, "12": 0 } },
        { "time_ms": 4000, "values": { "10": 255 } },
        { "time_ms": 5000, "values": { "10": 255, "11": 0,   "12": 255 } },
        { "time_ms": 5500, "values": { "10": 255, "11": 255, "12": 0 } },
        { "time_ms": 6000, "values": { "10": 0,   "11": 0,   "12": 0 } }
      ]
    }
  ]
}
```

Reading it against §6: the wash fades up over 0–3 s, holds to 9 s and fades out
by 11.5 s. The strobe track anchors its channels at 0 and holds them flat to 4 s
(§6.3.2), snaps channel 10 on at exactly 4 s with a same-time pair (§6.3.3),
crossfades 11 and 12 against each other, and blacks its own channels at 6 s.
Both tracks land on universe 1 and merge HTP (§6.3.4); channels 3–9 and 13–512
are transmitted as 0 for the whole show (§6.3.1).

---

## 11. Test vectors

An exporter or preview implementation can assert against these directly. All
values are produced by the reference implementation.

**A. Linear fade** — `[{0, {1:0}}, {1000, {1:255}}]`

| t (ms) | levels |
| --- | --- |
| 0 | `{1: 0}` |
| 250 | `{1: 64}` |
| 500 | `{1: 128}` |
| 750 | `{1: 191}` |
| 1000 | `{1: 255}` |
| 1500 | `{1: 255}` (holds) |

**B. Fade-start rule** — `[{0, {1:255}}, {5000, {1:255}}, {6000, {2:255}}]`

| t (ms) | levels |
| --- | --- |
| 0 | `{1: 255, 2: 0}` |
| 2500 | `{1: 255}` |
| 5000 | `{1: 255, 2: 0}` |
| 5500 | `{1: 255, 2: 128}` |
| 6000 | `{1: 255, 2: 255}` |

Channel 2 appears as an explicit `0` whenever it is the target of an in-progress
interpolation, and is absent otherwise. Both render identically into a
zero-filled frame, so a preview MAY treat absent as 0.

**C. Same-time snap** — `[{0, {1:0}}, {1000, {1:0}}, {1000, {1:255}}]`

| t (ms) | levels |
| --- | --- |
| 0 | `{1: 0}` |
| 500 | `{1: 0}` |
| 999 | `{1: 0}` |
| 1000 | `{1: 255}` |
| 1001 | `{1: 255}` |

**D. Untouched channels hold** — `[{0, {1:255, 2:100}}, {1000, {1:0}}]`

| t (ms) | levels |
| --- | --- |
| 500 | `{1: 128, 2: 100}` |

**E. Before the first keyframe** — `[{1000, {1:255}}]`

| t (ms) | levels |
| --- | --- |
| 0 | `{}` (dark) |

**F. HTP merge** — two tracks on universe 1, one at `{1: 100}`, one at
`{1: 200}`, both at t = 0: rendered channel 1 is **200**.

**G. Clamping and rounding** — level `300` → `255`; level `-20` → `0`; level
`200.7` in JSON → `200`; interpolated `127.5` → `128`; interpolated `128.5` →
`128` (round-half-to-even).

---

## 12. Reference implementation map

| Concern | File |
| --- | --- |
| Data model, JSON schema, interpolation, HTP merge | `src/aion_show_system/show/timeline.py` |
| Show discovery and name resolution | `src/aion_show_system/show/library.py` |
| Transport, end of show, looping, chaining | `src/aion_show_system/show/engine.py` |
| Master clock and media sync | `src/aion_show_system/show/clock.py` |
| Trigger policy and `allow_override` | `src/aion_show_system/triggers/manager.py` |
| Machine config (`shows_dir`, DMX, schedule) | `src/aion_show_system/config.py` |
| Programmatic show construction (worked example) | `src/aion_show_system/show/demo.py` |
| Behavioural tests, worth reading as a second spec | `tests/test_timeline.py`, `tests/test_engine.py` |
