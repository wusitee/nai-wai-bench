"""Language switching for the bilingual site.

Pages carry both languages: Chinese text is marked `class=zh`, English text `class=en`, and unmarked text
(numbers, model names, code) belongs to both. A head script sets `data-lang` on the root element from the
reader's saved choice or browser language, and the CSS hides the other language. Without scripts both
languages show side by side."""

from html import escape


def bi(zh: str, en: str, br: bool = False) -> str:
    """Inline text in both languages; the arguments are HTML. When both languages show, a space or a line
    break separates them."""
    return f"<span class=zh>{zh}</span><span class=en>{'<br>' if br else ' '}{en}</span>"


def bie(pair: tuple[str, str], br: bool = False) -> str:
    """`bi` for a plain-text (zh, en) pair."""
    return bi(escape(pair[0]), escape(pair[1]), br)


CSS = """
html[data-lang=zh] .en,html[data-lang=en] .zh{display:none}
html[data-lang=en] .en{color:inherit}html[data-lang=en] .en>br:first-child{display:none}
.lang{display:flex;border:1px solid var(--line);border-radius:4px;overflow:hidden;flex:none}
.lang button{all:unset;cursor:pointer;padding:2px 9px;font:600 11px var(--mono);letter-spacing:.06em;color:var(--muted)}
.lang button:hover{color:var(--fg)}.lang button:focus-visible{outline:2px solid var(--yellow);outline-offset:-2px}
html[data-lang=zh] .lang [data-lang=zh],html[data-lang=en] .lang [data-lang=en]{color:var(--bg);background:var(--yellow)}
"""

# Runs in <head>, before the body renders, so the page never flashes the other language.
SCRIPT = """<script>(function(){var d=document.documentElement,t=d.dataset;
function set(l){t.lang=l;d.lang=l=='zh'?'zh-CN':'en';if(t['title'+l])document.title=t['title'+l];
document.querySelectorAll('.lang button').forEach(function(b){b.setAttribute('aria-pressed',b.dataset.lang==l)})}
var l;try{l=localStorage.getItem('nwb-lang')}catch(e){}
if(l!='zh'&&l!='en')l=/^zh\\b/i.test(navigator.language||'')?'zh':'en';set(l);
document.addEventListener('DOMContentLoaded',function(){set(t.lang)});
document.addEventListener('click',function(ev){var b=ev.target.closest&&ev.target.closest('.lang button');if(!b)return;
set(b.dataset.lang);try{localStorage.setItem('nwb-lang',b.dataset.lang)}catch(e){}})})()</script>"""

SWITCH = ("<div class=lang role=group aria-label='语言 Language'><button type=button data-lang=zh lang=zh-CN>中文</button>"
          "<button type=button data-lang=en lang=en>EN</button></div>")
