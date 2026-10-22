# Reference material

- `nailong_laugh.png`: the canonical 大笑奶龙 (奶龙捧腹大笑) image, from Moegirlpedia,
  [File:奶龙捧腹大笑.png](https://zh.moegirl.org.cn/File:%E5%A5%B6%E9%BE%99%E6%8D%A7%E8%85%B9%E5%A4%A7%E7%AC%91.png).
- Facts in `bench/rubric.toml` come from the Moegirlpedia article
  [奶龙 § 大笑奶龙/奶蛙](https://zh.moegirl.org.cn/%E5%A5%B6%E9%BE%99#%E5%A4%A7%E7%AC%91%E5%A5%B6%E9%BE%99/%E5%A5%B6%E8%9B%99)
  (text under CC BY-NC-SA 3.0 CN), as of October 2026. Background notes and the frog-like 奶蛙 variant are
  cross-checked against Chinese Wikipedia, [奶龙](https://zh.wikipedia.org/wiki/%E5%A5%B6%E9%BE%99).
- `../stimuli/naiwa_glance.png` (「惊鸿一瞥」) and `../stimuli/angry_variant.png` (「切换愤怒模式」): circulating
  sticker variants of the meme family, provided by the project author; their original posters are unknown.
- The 奶蛙 origin (an AI agent created on 星野 on 2024-10-02) and the frog-like look behind the name are
  corroborated by Lost Media Wiki CN, [奶蛙](https://lostmedia.wikidot.com/naiwa-cx) (revision of 2026-10-08).
- `../stimuli/laughing_panda.jpg`: a panda variant generated with Codex's built-in `image_gen` tool from the
  reference tier prompt (`参考这张图，画一个同样风格的熊猫版本`). It is used as a recognition stimulus.
- `../stimuli/naiwa_facepalm.jpg`, `../stimuli/naiwa_smug.jpg`, and `../stimuli/naiwa_folded_arms.jpg`:
  images 3, 4, and 8 in 明星表情包's [邪恶变异奶龙表情包 collection](https://www.sina.cn/news/detail/5297308469036271.html),
  posted on 2026-05-11 and verified on 2026-10-21. Direct image URLs:
  [facepalm](https://wx4.sinaimg.cn/middle/006fbYi5gy1id18ktw7sqj30e00d0go3.jpg),
  [smug](https://wx3.sinaimg.cn/middle/006fbYi5gy1id18ku627gj30e00e0wgu.jpg), and
  [folded arms](https://wx1.sinaimg.cn/middle/006fbYi5gy1id18kvg8t8j30e00dsq2z.jpg).
  The collection establishes circulation as mutated-Nailong stickers, not authorship or generation method.
- `../stimuli/nailong_official.png`: unmodified character artwork from the creator 第七印象's
  [official Nailong page](https://www.nailoong.com/ipStar/Nailong/), verified on 2026-10-21;
  [direct image](https://www.nailoong.com/_ipx/q_85/img/ipStar/image_nailoong.png).
  This is the official-art negative control and the source for the `official_art` fact.

The images are included for non-commercial research use only.

## State-transfer references

The optional suite uses neutral attachment filenames so the filename does not reveal the expected label:

- `../states/01.png`: the top 260 × 220 pixels of the supplied `../stimuli/angry_variant.png`, made with
  `magick bench/stimuli/angry_variant.png -crop 260x220+0+0 +repage bench/states/01.png`.
  This removes the 「切换愤怒模式」 caption and emoji. No character features were synthesized or retouched.
- `../states/02.jpg`: an unchanged copy of `../stimuli/naiwa_facepalm.jpg` from the sourced collection above.
- `../states/03.jpg`: an unchanged copy of `../stimuli/naiwa_smug.jpg` from the same collection.

The labels `angry`, `facepalm`, and `smug` describe visible expressions or actions for this suite, not
verified inner feelings or an official emotion taxonomy. These references and labels need human review
before publishing calibrated state-recognition or transfer-accuracy claims.
