# Naiwa origins and prompt provenance

Evidence reviewed on **2026-11-05**. The strongest located account connects the early standing 奶蛙
image to a 星野 (Xingye) agent named 奶龙, with a displayed creation date of **2024-10-02**. A later
video by the same researcher substantially updates the investigation linked below. The original
image-generation request and the provenance of every later variant remain unresolved.

## Sources and evidence limits

- **Initial investigation:** 看仙碎, [大名鼎鼎的奶蛙，是以儿童邪典为底色的失传媒体？奶蛙最全起源说法考究][investigation],
  published 2026-07-30, 8:27. Its description notes an August 1 update. The opening discusses circulation;
  01:49–04:21 examines the Douyin account 恐龙世界; 04:35–06:09 discusses competing generation and avatar
  explanations; 08:03–08:25 describes the remaining gaps. These are the researcher's findings and
  inferences, rather than a recovered original generation log.
- **Later discovery:** the initial video's [pinned comment][pinned], posted by 雾蚀心忘症 on 2026-08-04,
  supplies agent ID `zNCvQDKfXy` and two full-resolution screenshots:
  [agent profile][agent-profile] and [full standing image][agent-image]. The profile displays creator
  **纲手［百豪］** and creation time `2024-10-2 23:23`, without an explicit time zone. The screenshot
  shows a creation date for the agent; it does not independently establish when its avatar was attached.
- **Follow-up:** 看仙碎, [奶蛙，出处确认][confirmation], published 2026-08-05, 3:32. At 00:01–00:49,
  the researcher identifies the same agent, credits its creator, and shows a faint AI-generated mark
  revealed by inverting the full image. At 00:51–01:45, the video corrects the earlier assumption that
  the agent had disappeared: it reports finding it through precise search after failed ID/profile
  searches. Its temporary removal and later restoration are the author's reconstruction. At
  02:35–02:59, it shows the agent's roleplay setting, voice, and animal-remix examples.
- **Encyclopedia summary:** [Moegirlpedia's Nailong article][moegirl], checked on 2026-11-05, cites the
  August 5 follow-up for its October 2024 Xingye account. This is a summary of the same evidence, not
  independent corroboration. The previously cited [Lost Media Wiki CN entry][lostmedia] could not be
  rechecked on that date because it returned HTTP 503.

Review covered the burned-in captions and displayed evidence throughout both videos, with frames
sampled every two seconds, plus the original-resolution pinned screenshots and public metadata.
Bilibili required login for a subtitle track. Neither the Xingye app nor the original generation
session was independently inspected. The videos and screenshots are linked rather than redistributed.

## What the evidence supports

The follow-up supports the **Xingye-agent origin account** much more strongly than the first video
alone. It identifies a concrete agent and credits 纲手［百豪］ as its creator. Keep that attribution tied
to the source: it is not a verified real-world identity, and no original generation log is provided.
An agent creation timestamp, an avatar, and an AI-generated mark provide different kinds of evidence;
none alone proves the image's complete editing history, exact model, or first-generation prompt.

The first video treats **恐龙世界** as a leading early Douyin source. Its closing discussion places
the illustrated circulation before December 8, 2024, and mentions a possible November date. Those
dates concern screenshots discussed in that video, not independently authenticated original posts.
The later Xingye discovery predates this account's illustrated circulation and updates the earlier
creator hypothesis. Early redistribution and original generation must remain distinct.

The initial investigation reports dancing/remixed clips in early 2025 and a later wave centered on
the belly-clutching laugh in early 2026. These circulation stages must not all inherit the Xingye
agent's October 2024 date. This review does not establish the exact first publication of the laughing
variant or independently verify the provenance of its added laugh audio.

The title's **lost-media** framing concerns missing generation records and the incomplete early
image collection. The standing image survives, and the follow-up reports locating the agent. The
initial video's **儿童邪典** discussion describes the researcher's characterization of an early
uploader's other fan edits. It does not establish that the avatar was generated with that intent or
that every later 奶蛙 remix shares it.

## What is known about prompts

**No authenticated original image-generation prompt was recovered in these sources.** At
05:17–05:27, the initial video suggests `奶龙怀孕的样子` ("what Nailong looks like pregnant") from
commenters' recollections and an inference about the body shape. It is a hypothesis, not a recovered
request, and the follow-up supplies no original generation transcript to confirm it. Other claims
about Doubao, AI expansion, retouching, costumes, or older foreign-forum images also remain unverified
in the reviewed material.

The agent's visible **roleplay description and greeting** are separate from an image-generation
prompt. They place it in a 胖猫/奶龙 roleplay context; this does not reveal the words used to make its
avatar. The follow-up also shows animal-remix examples, without recovering their exact prompts or
establishing that they came from the same model/settings as the avatar.

Use appearance-based prompts for reproduction, and label them as reconstructions. The examples below
are newly written guidance, not historical prompts or new benchmark generation tiers. They have not
been image-tested.

**Early standing 奶蛙 reconstruction:**

> One full-body yellow creature standing upright with its arms relaxed beside its belly. A bulky
> pear-shaped body, small rounded head merging into the torso, short thick limbs, a large cream oval
> belly patch, dark grey fingertips and toe tips. Two protruding round eyes with bright green rings
> around dark pupils; a small, thin, closed greyish mouth with a blank expression. Smooth, slightly
> glossy, low-budget 3D CGI with soft diffuse lighting on an empty white background. Keep the full
> body in frame. No lettering or watermark.

**Later belly-clutching laugh, transferred to an animal:**

> A single clearly recognizable {animal}, in its natural colors and markings, rendered as a smooth,
> bulky 3D cartoon with a pear-shaped body and short thick limbs. Standing with knees slightly bent
> and torso hunched forward, both hands or paws pressed against its round belly, doubled over with
> laughter. Eyes squeezed shut into curved arcs; an enormous open mouth with a dark interior, teeth,
> and tongue. Soft studio lighting, a plain white to light-grey background, and an absurd exaggerated
> expression. No fur strands, lettering, or watermark.

Use a matching reference image when possible. The open green eyes and relaxed arms describe the
early standing image; closed eyes, a gaping mouth, and belly-clutching describe the benchmark's
canonical laughing reference. Neither pose is a universal requirement for the whole meme family.

## Benchmark integration

The core suite's `origin_evidence_zh` and `origin_evidence_en` tasks test attribution, chronology,
visual distinctions, prompt provenance, and appropriate uncertainty against this review. Their
reference notes are provisional interpretations of the linked evidence, pending human review. They
are text diagnostics outside the Meme ID ranking, Visual detail ranking, and NaiWai Index.

```sh
uv run nwb understand --run origin-evidence-2026-11-05 --suite core \
  --models MODEL --items origin_evidence_zh,origin_evidence_en
uv run nwb judge --run origin-evidence-2026-11-05 --suite core --track understanding
uv run nwb report --run origin-evidence-2026-11-05 --suite core
```

Collection disables retrieval, as for other knowledge tasks. Do not give the source dossier to a
subject during a closed-book run. Judge inputs contain the evidence notes rather than fetching links.

The existing `knowledge_zh`/`knowledge_en` questions and their original checklist remain the historical
broad-lore diagnostics used in retained 0.1.0 runs. Their `xingye_origin` shorthand combines the origin
of the meme family with discussion of its later laughing variant; use the new evidence tasks for the
more precise distinctions above. Diagnostic text means depend on the available task set, so compare
matching item selections. Adding these tasks preserves the ranked image panels, generation prompts,
existing judge-prompt fingerprints, raw results, and release manifest.

[investigation]: https://www.bilibili.com/video/BV1er3x68EZT/
[pinned]: https://www.bilibili.com/video/BV1er3x68EZT/#reply308821531425
[agent-profile]: https://i0.hdslb.com/bfs/new_dyn/43bd46fc1f95165ed648b2a5da661a85671690954.jpg
[agent-image]: https://i0.hdslb.com/bfs/new_dyn/ffc9dc392a56bd81058450caeecb0ae3671690954.jpg
[confirmation]: https://www.bilibili.com/video/BV1ndMk65EwM/
[moegirl]: https://zh.moegirl.org.cn/%E5%A5%B6%E9%BE%99#%E5%A4%A7%E7%AC%91%E5%A5%B6%E9%BE%99/%E5%A5%B6%E8%9B%99
[lostmedia]: https://lostmedia.wikidot.com/naiwa-cx
