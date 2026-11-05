# Episode videos

Each Bilibili episode in the video list
[nai-wai-bench 奶蛙测试](https://space.bilibili.com/457064547/lists/5185613?type=series) shows how one
model does on the benchmark. This page covers the format, the data rules, the build pipeline, and
publishing.

## Format

- Chinese on-screen text, no voice-over; synthesized background music and sound effects.
- About 1:50–2:00, 1920×1080 at 30 fps.
- Scenes, in this order:

| Scene | Content |
|---|---|
| `term` | Opening: a terminal replaying the subject's `nwb` run |
| `unlock` | A setup quirk needed to run the model; omit it when there is none |
| `setup` | What the three test groups cover |
| `knowledge` | No-image knowledge questions: facts covered, hallucinations the judges flagged |
| `text` | Text-only diagnostics leaderboard, marked 不计入正式排名 |
| `moments` | Image recognition: what the model called the canonical image, the 奶蛙 variants, and official 奶龙 |
| `naihub` | Nai-hub v1 leaderboard |
| `core` | Core-suite visual-understanding leaderboard |
| `efficiency` | Output tokens and estimated cost |
| `review` | A one-line Chinese verdict and a mood image chosen from the Nai-hub v1 images |
| `outro` | Report card and the results-site URL |

When one model is tested at several reasoning efforts, each effort is its own leaderboard row (a
model configuration). Pick one row as the subject, normally the benchmark's standard effort, and
show the others as extra rows.

## Data rules

Accuracy takes priority over everything else.

- Use the release runs of the published results, scored by the same source. Do not mix
  pre-release runs into release tables.
- A data script reads `scores.json`, the answer files, and the judgment files and writes everything
  the video and description show: numbers, ranks, rank ranges, intervals, ticks and crosses, token
  counts, costs, and quotes. Scenes, the cover, and the metadata script contain only layout and
  captions. Quotes are exact substrings of saved answers, asserted by the script.
- Ranks: scores equal at one decimal share a rank. Say "N 个…中第 K", and show rank ranges or
  intervals when ranks are close. Never give a rank to an unranked (mixed-condition) row.
- Score every row with the release's judges, as on the results site. When a judge shares a row's
  vendor, label that row on screen. When it shares the subject's vendor, also score the comparison
  with an independent judge, and show the subject's result among the rows that judge scored
  completely. When only one independent judge scored the subject, say so, and cross-check close text
  results against the same judge's scores for the other models.
- Show the caveats: judges are LLMs; repetitions are few; the Nai-hub answer key is GPT-6-Astra's
  provisional annotation (when Astra ranks near the top or shares the subject's vendor); rows filled
  through a third-party router are labelled; efforts that differ from the standard are labelled.
- Cost is tokens × API list price, labelled 按 API 标价估算，非订阅计费. Record each price with its
  source URL and lookup date, and the release date with an official source. Do not guess either.
- Before release, someone other than the author checks every on-screen claim and every description
  line against the data. Fix, rebuild, and repeat until a round comes back clean.

## Pipeline

Each episode is built in its own Git-ignored working folder; the pipeline scripts are not versioned
in this repository. The folder holds:

| File | Role |
|---|---|
| `make_data.py` | Writes `page/data.js` and `data.json` from the run data; holds all data assertions |
| `page/index.html` | Scenes as JavaScript; `window.init()` returns `{duration, sfx, scenes}` and `window.render(t)` draws time `t` |
| `render.mjs` | `node render.mjs stills T…` writes preview PNGs; `node render.mjs video [WORKERS]` renders 300-frame chunks in parallel, writes `timeline.json`, and reuses finished chunks |
| `mix.py` | Synthesizes the sound effects at the timeline cues and an electric-piano bed at 104 BPM, 48 kHz |
| `build.sh` | Data → frames → mix → mux into `out/<slug>-naiwa-bench.mp4` |
| `page/cover.html`, `cover.mjs` | Cover → `out/cover.png` (1920×1080) |
| `meta.py` | Title, tags, and description → `out/bilibili.md` and `out/desc.txt` |
| `page/assets/` | Reference image, 奶蛙 variants, official 奶龙, Nai-hub v1 images (non-commercial use only) |

Output settings: libx264 CRF 14 `-tune animation`, limited-range BT.709 yuv420p; AAC 192 kb/s
48 kHz with `loudnorm=I=-16:TP=-1.5:LRA=11`; `+faststart`.

Requirements: Node.js with `playwright-core`, Chromium (`--disable-gpu --font-render-hinting=none`),
ffmpeg, uv, and the fonts Noto Sans CJK SC, Noto Color Emoji, and Maple Mono Normal NF CN. Frames
look different without these fonts.

Workflow:

1. Copy the previous episode's folder and update the subject, run paths, short labels, and output names.
2. Run `make_data.py`; spot-check a few values against `scores.json`.
3. Read the subject's answers and judgments to find the story, the verdict, and the mood image.
4. Edit the scenes and check stills at the start, middle, and end of every scene: text fits, nothing
   overlaps, CJK and emoji render. `grep` the scenes and cover for digits; only timings, sizes, and
   image IDs may be literals.
5. Delete `work/seg/` after any scene edit, then run `bash build.sh`. Check the file with `ffprobe`
   and watch it once with sound.
6. Render the cover (readable at 320×180) and run `meta.py`.
7. Fact-check (see above).

## Bilibili metadata

- Title: `<Model> 认得出大笑奶龙吗？奶蛙bench …实测`, adjusted to fit the result.
- Description, at most 2000 characters (`meta.py` asserts this): a one-line summary that mentions
  无配音演示视频; one bullet per result; the verdict; the caveats (repetitions, LLM judges, excluded
  judges, client and effort, no tool use); the results-site and repository links; 上一期 with the
  previous episode's BV; chapter times from `timeline.json`; and the closing line
  素材仅用于非商业研究。背景音乐和音效为程序合成。 `biliup show` displays only the first 250 characters;
  the stored text is not truncated.
- Tags: 大笑奶龙, 奶蛙, 奶龙, the vendor's names in Chinese and English, 大模型, AI评测, benchmark, 多模态, AI.
- Category `tid` 231, copyright 1 (自制), monetization (充电) off.

## Publishing

Each of these steps needs the maintainer's explicit approval, given separately: publishing the
results site, uploading, later edits to title, description, cover, or visibility, and merging,
tagging, or releasing.

- The results site must show the subject before the video goes out, because the description links
  to it. `scripts/publish_site.sh` replaces the `gh-pages` branch.
- Send the MP4, cover, and `bilibili.md` to the maintainer for approval.
- Upload as public directly (`--is-only-self 0`). Never upload privately and switch to public later:
  that skips Bilibili's first recommendation push. To publish at a chosen time, upload public with
  `--dtime` (a Unix timestamp at least 4 hours ahead); the video passes review and then waits for
  that time. If biliup's line probe fails with a TLS EOF, use line `bda2`.
- After review passes (state −40 or open), add the video to the 视频列表 above (series 5185613).
  While the video is still in review (state −30), the add request succeeds but the video is not
  listed. This account cannot create a 合集 (error 20082). Leave other lists unchanged.
- Deleting a video needs a captcha or SMS code; the maintainer does it in 创作中心. Do not fix a
  mistake by uploading again without asking.
- The Bilibili login cookie is a credential: never commit, print, or paste it. Push only named
  branches, never `git push --mirror` or `--all`, so that local tool refs cannot publish ignored files.
