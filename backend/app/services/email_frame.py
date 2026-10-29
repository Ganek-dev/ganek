"""Shared frame for candidate and team emails: the branded card, the
paragraph style, the plain-text privacy pointer and the brand colour
maths. The senders in ``email`` and the template renderer in
``email_render`` both build on these."""

DEFAULT_BRAND_PRIMARY = "#18181b"
NEUTRAL_BAR = "#d4d4d8"  # rejections never carry brand accents


def brand_foreground(color: str) -> str:
    """Text color that stays readable on the brand color (WCAG luminance)."""
    raw = color.lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    try:
        channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    except (ValueError, IndexError):
        return "#ffffff"
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#18181b" if luminance > 0.45 else "#ffffff"


def card_html(
    *,
    bar_color: str,
    brand: str,
    brand_fg: str,
    safe_company: str,
    content: str,
    safe_controller: str | None = None,
    privacy_url: str | None = None,
) -> str:
    """Shared email card (handoff 17/22): top bar, logo chip, content, footer.

    The footer names the data controller (legal name when the company set
    one - M5.6 G1) and links their privacy notice on candidate-facing mail.
    """
    footer = f"Sent by Ganek on behalf of {safe_controller or safe_company}"
    if privacy_url:
        footer += (
            f' · <a href="{privacy_url}" style="color: #a1a1aa; '
            f'text-decoration: underline;">privacy notice</a>'
        )
    return (
        f'<div style="margin: 0 auto; max-width: 480px; background: #ffffff; '
        f"border-radius: 12px; border: 1px solid #e4e4e7; overflow: hidden; "
        f"font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; "
        f'color: #18181b;">'
        f'<div style="height: 5px; background: {bar_color};"></div>'
        f'<div style="padding: 28px 32px;">'
        f'<div><span style="display: inline-block; width: 24px; height: 24px; '
        f"border-radius: 7px; background: {brand}; color: {brand_fg}; text-align: center; "
        f'line-height: 24px; font-size: 13px; font-weight: 700;">{safe_company[:1].upper()}</span>'
        f'<span style="margin-left: 9px; font-size: 15px; font-weight: 600;">'
        f"{safe_company}</span></div>"
        f"{content}"
        f"</div></div>"
        f'<div style="margin: 16px auto 0; max-width: 480px; text-align: center; '
        f'font-family: monospace; font-size: 10.5px; color: #a1a1aa; line-height: 17px;">'
        f"{footer}</div>"
    )


def privacy_text(privacy_url: str | None) -> str:
    """Trailing plain-text privacy pointer for candidate emails."""
    return f"\nPrivacy & your data: {privacy_url}\n" if privacy_url else ""


def paragraph(inner: str) -> str:
    return (
        f'<p style="margin: 12px 0 0; font-size: 14.5px; line-height: 22px; '
        f'color: #3f3f46;">{inner}</p>'
    )
