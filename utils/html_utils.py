import html
import re


ALLOWED_TAG_RE = re.compile(
    r"""
    <
    (?:
        /?(?:b|strong|i|em|u|s|code|pre|blockquote|a)
        |
        a\s+href\s*=\s*(?:"[^"]*"|'[^']*')
        |
        tg-emoji\s+emoji-id\s*=\s*(?:"[^"]*"|'[^']*')
        |
        /tg-emoji
    )
    \s*/?>
    """,
    re.IGNORECASE | re.VERBOSE,
)


def sanitize_html(text: str) -> str:
    if not text:
        return ""

    protected = []

    def protect(match):
        protected.append(match.group(0))
        return f"\x00TAG{len(protected) - 1}\x00"

    text = ALLOWED_TAG_RE.sub(protect, text)

    text = html.escape(text, quote=False)

    for i, tag in enumerate(protected):
        text = text.replace(
            f"\x00TAG{i}\x00",
            tag
        )

    return text