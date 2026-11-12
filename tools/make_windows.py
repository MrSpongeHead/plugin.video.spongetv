# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Writes SpongeTV's three window files (resources/skins/Default/1080i) from the approved mock-ups.

Positions follow the mock-ups at 1920 x 1080. Fonts are Estuary's (the default skin): the *_title fonts are
its bold ones; a skin without them shows its regular font instead.

The button rule, the same in every window:
  focused                 solid amber, dark text (the only solid amber thing: it's what OK will press)
  main action, unfocused  navy, amber outline, amber text
  other, unfocused        navy, blue-grey outline, light text
  disabled                navy, greyed text
"""

import os

OUT = os.path.join(os.path.dirname(__file__), "..", "resources", "skins", "Default", "1080i")

NAVY_DEEP, NAVY, NAVY_LIGHT, BORDER = "FF0A1428", "FF12233F", "FF18304F", "FF24406A"
ROW_FOCUS = "FF1C3A5E"
AMBER, TEAL, MINT = "FFF5A524", "FF2EC4B6", "FFDFFAF6"
TEXT, TEXT2, MUTED = "FFEAF2FB", "FFA9BCD6", "FF8FA6C4"


def prop(name):
    return f"$INFO[Window.Property({name})]"


def item(name):
    return f"$INFO[ListItem.Property({name})]"


def image(x, y, w, h, texture, colour=None, border=None, visible=None, aspect=None, indent="        "):
    attrs = (f' border="{border}"' if border else "") + (f' colordiffuse="{colour}"' if colour else "")
    out = [f'{indent}<control type="image">',
           f"{indent}    <left>{x}</left><top>{y}</top><width>{w}</width><height>{h}</height>",
           f"{indent}    <texture{attrs}>{texture}</texture>"]
    if aspect:
        out.append(f"{indent}    <aspectratio>{aspect}</aspectratio>")
    if visible:
        out.append(f"{indent}    <visible>{visible}</visible>")
    return "\n".join(out + [f"{indent}</control>"])


def label(x, y, w, h, font, colour, text, align=None, aligny="center", visible=None, indent="        ",
          textbox=False):
    kind = "textbox" if textbox else "label"
    out = [f'{indent}<control type="{kind}">',
           f"{indent}    <left>{x}</left><top>{y}</top><width>{w}</width><height>{h}</height>",
           f"{indent}    <font>{font}</font><textcolor>{colour}</textcolor>"
           + (f"<align>{align}</align>" if align else "") + (f"<aligny>{aligny}</aligny>" if aligny and not textbox else ""),
           f"{indent}    <label>{text}</label>"]
    if visible:
        out.append(f"{indent}    <visible>{visible}</visible>")
    return "\n".join(out + [f"{indent}</control>"])


def button(cid, x, y, w, h, text, font, main=False, radius=16, nav="", enable=None, icon=None, indent="        "):
    """A button following the rule above. icon: (texture, colour when not focused) drawn left of the text."""
    shape = {16: ("spongetv-r16.png", "spongetv-r16-line2.png", 16), 32: ("spongetv-pill.png", "spongetv-pill-line2.png", 30)}
    fill, line, border = shape[radius]
    focus_expr = f"Control.HasFocus({cid})"
    parts = [image(x, y, w, h, fill, NAVY, border, indent=indent)]          # navy behind every state
    outline = AMBER if main else BORDER
    if enable:   # the outline only when it can be chosen
        parts.append(image(x, y, w, h, line, outline, border, visible=f"!{focus_expr} + {enable}", indent=indent))
    else:
        parts.append(image(x, y, w, h, line, outline, border, visible=f"!{focus_expr}", indent=indent))
    out = [f'{indent}<control type="button" id="{cid}">',
           f"{indent}    <left>{x}</left><top>{y}</top><width>{w}</width><height>{h}</height>",
           f"{indent}    <font>{font}</font><textcolor>{AMBER if main else TEXT}</textcolor>"
           f"<focusedcolor>{NAVY_DEEP}</focusedcolor><disabledcolor>{MUTED}</disabledcolor>",
           f"{indent}    <align>{'left' if icon else 'center'}</align><aligny>center</aligny>",
           f'{indent}    <texturenofocus border="{border}" colordiffuse="00FFFFFF">{fill}</texturenofocus>',
           f'{indent}    <texturefocus border="{border}" colordiffuse="{AMBER}">{fill}</texturefocus>',
           f"{indent}    <label>{text}</label>"]
    if icon:   # Kodi indents a button's text from both edges, so with an icon the text is drawn separately
        out[-1] = f"{indent}    <label></label>"
    if enable:
        out.append(f"{indent}    <enable>{enable}</enable>")
    out.append(nav)
    out.append(f"{indent}</control>")
    parts.append("\n".join(o for o in out if o))
    if icon:
        texture, colour, icon_x = icon
        size = 24
        tx = x + icon_x + size + 14
        parts.append(image(x + icon_x, y + (h - size) // 2, size, size, texture, colour, visible=f"!{focus_expr}",
                           indent=indent))
        parts.append(image(x + icon_x, y + (h - size) // 2, size, size, texture, NAVY_DEEP, visible=focus_expr,
                           indent=indent))
        parts.append(label(tx, y, x + w - tx - 16, h, font, AMBER if main else TEXT, text, visible=f"!{focus_expr}",
                           indent=indent))
        parts.append(label(tx, y, x + w - tx - 16, h, font, NAVY_DEEP, text, visible=focus_expr, indent=indent))
    return "\n".join(parts)


def window(default, controls, comment, fade=True):
    head = ['<?xml version="1.0" encoding="UTF-8"?>', f"<!-- {comment} Written by tools/make_windows.py. -->",
            "<window>", f'    <defaultcontrol always="true">{default}</defaultcontrol>']
    if fade:
        head += ['    <animation type="WindowOpen" reversible="false">',
                 '        <effect type="fade" start="0" end="100" time="200"/>', "    </animation>",
                 '    <animation type="WindowClose" reversible="false">',
                 '        <effect type="fade" start="100" end="0" time="150"/>', "    </animation>"]
    return "\n".join(head + ["    <controls>"] + controls + ["    </controls>", "</window>", ""])


# -- Source Select ---------------------------------------------------------------------------------------
# Row columns (mock-up grid 112 | 1fr | 140 | 210 | 200, gap 24, padding 26) inside a 1280 px row.
COL_Q, COL_REL, COL_SIZE, COL_STATUS, COL_FROM = 26, 162, 656, 820, 1054
ROW_W, ROW_H, ROW_GAP = 1280, 78, 10


def source_row(focused):
    i = "                "
    parts = []
    if focused:
        parts.append(image(0, 0, ROW_W, ROW_H, "spongetv-r16.png", ROW_FOCUS, 16, visible="Control.HasFocus(1000)", indent=i))
        parts.append(image(0, 0, ROW_W, ROW_H, "spongetv-r16-line3.png", AMBER, 16, visible="Control.HasFocus(1000)", indent=i))
        parts.append(image(0, 0, ROW_W, ROW_H, "spongetv-r16.png", NAVY, 16, visible="!Control.HasFocus(1000)", indent=i))
    else:
        parts.append(image(0, 0, ROW_W, ROW_H, "spongetv-r16.png", NAVY, 16, indent=i))
    parts.append(image(COL_Q, 15, 112, 48, "spongetv-r12.png", item("badge_bg"), 12, indent=i))
    # Text colours are fixed, chosen by visibility: Kodi only re-reads a colour taken from the list item
    # while the list has focus, so text coloured that way vanished when you moved to Play best source.
    dark_badge = "[String.IsEqual(ListItem.Property(quality),4K) | String.IsEqual(ListItem.Property(quality),1080p)]"
    parts.append(label(COL_Q, 15, 112, 48, "font20_title", NAVY_DEEP, item("quality"), align="center",
                       visible=dark_badge, indent=i))
    parts.append(label(COL_Q, 15, 112, 48, "font20_title", TEXT, item("quality"), align="center",
                       visible="!" + dark_badge, indent=i))
    parts.append(label(COL_REL, 6, 470, 38, "font25_title", TEXT, "$INFO[ListItem.Label]", indent=i))
    parts.append(label(COL_REL, 42, 470, 30, "font_flag", TEXT2, "$INFO[ListItem.Label2]", indent=i))
    parts.append(label(COL_SIZE, 0, 140, ROW_H, "font10", TEXT, item("size"), indent=i))
    parts.append(image(COL_STATUS, 33, 12, 12, "spongetv-dot.png", item("status_colour"), indent=i))
    for kind_test, colour in (("String.IsEqual(ListItem.Property(status_kind),cached)", TEAL),
                              ("String.IsEqual(ListItem.Property(status_kind),cloud)", MINT),
                              ("!String.IsEqual(ListItem.Property(status_kind),cached) + "
                               "!String.IsEqual(ListItem.Property(status_kind),cloud)", MUTED)):
        parts.append(label(COL_STATUS + 22, 0, 188, ROW_H, "font20_title", colour, item("status"), visible=kind_test,
                           indent=i))
    parts.append(label(COL_FROM, 0, 200, ROW_H, "font10", TEXT2, item("from"), indent=i))
    return "\n".join(parts)


def source_select():
    c = []
    c.append(image(0, 0, 1920, 1080, "spongetv-white.png", NAVY_DEEP))
    # header: logo, title, subtitle, Filter and Sort
    c.append(image(96, 64, 88, 88, prop("logo"), aspect="keep"))
    c.append(label(212, 62, 920, 56, "font45_title", TEXT, prop("heading")))
    c.append(label(212, 118, 932, 34, "font12", TEXT2, prop("subheading")))
    c.append(button(2002, 1168, 78, 320, 60, prop("filter_label"), "font20_title", radius=32,
                    icon=("spongetv-filter.png", TEAL, 30),
                    nav="            <onright>2003</onright><ondown>1000</ondown>"))
    c.append(button(2003, 1504, 78, 320, 60, prop("sort_label"), "font20_title", radius=32,
                    icon=("spongetv-sort.png", TEAL, 30),
                    nav="            <onleft>2002</onleft><ondown>1000</ondown>"))
    # left: poster, details, Play best source
    c.append(image(96, 192, 400, 560, "spongetv-r20.png", NAVY_LIGHT, 20))
    c.append(image(96, 192, 400, 560, prop("poster"), aspect="scale",
                   visible="!String.IsEmpty(Window.Property(poster))"))
    c.append(image(96, 192, 400, 560, "spongetv-r20-line2.png", BORDER, 20))
    c.append(label(124, 600, 344, 130, "font30_title", TEXT, prop("title"), aligny=None, textbox=True,
                   visible="String.IsEmpty(Window.Property(poster))"))
    c.append(label(96, 776, 400, 34, "font10", TEXT2, prop("meta")))
    c.append(button(2001, 96, 834, 400, 78, prop("play_best"), "font25_title", main=True,
                    icon=("spongetv-play.png", AMBER, 78),
                    nav="            <onright>1000</onright><onup>2002</onup>"))
    # column headings
    for x, w, key in ((COL_Q, 112, "col_quality"), (COL_REL, 470, "col_release"), (COL_SIZE, 140, "col_size"),
                      (COL_STATUS, 210, "col_status"), (COL_FROM, 200, "col_from")):
        c.append(label(544 + x + 2, 192, w, 28, "font_flag", MUTED, f"[UPPERCASE]{prop(key)}[/UPPERCASE]"))
    # the sources
    c.append("\n".join([
        '        <control type="list" id="1000">',
        "            <left>544</left><top>232</top><width>1280</width><height>704</height>",
        "            <orientation>vertical</orientation>",
        "            <onleft>2001</onleft><onup>2002</onup>",
        '            <scrolltime tween="quadratic">200</scrolltime>',
        f'            <itemlayout height="{ROW_H + ROW_GAP}" width="{ROW_W}">',
        source_row(False),
        "            </itemlayout>",
        f'            <focusedlayout height="{ROW_H + ROW_GAP}" width="{ROW_W}">',
        source_row(True),
        "            </focusedlayout>",
        "        </control>"]))
    # footer: a rule and the one hint
    c.append(image(96, 978, 1728, 2, "spongetv-white.png", NAVY_LIGHT))
    c.append(label(96, 1000, 1728, 34, "font10", TEXT2, prop("hints")))
    return window(1000, c, "SpongeTV Source Select, from the approved mock-up.")


# -- source search -----------------------------------------------------------------------------------------
def source_search():
    x0, y0, w0, h0 = 400, 185, 1120, 710        # the panel, centred
    ix, iw = x0 + 64, w0 - 128                   # inside the padding
    c = []
    c.append(image(0, 0, 1920, 1080, "spongetv-white.png", "FF060C18"))
    c.append(image(0, 0, 1920, 1080, prop("fanart"), aspect="scale"))
    c.append(image(0, 0, 1920, 1080, "spongetv-white.png", "990D1A30"))     # dims the fanart
    c.append(image(x0, y0, w0, h0, "spongetv-r32.png", NAVY, 32))
    c.append(image(x0, y0, w0, h0, "spongetv-r32-line2.png", BORDER, 32))
    top = y0 + 56
    c.append(image(ix, top, 80, 80, prop("logo"), aspect="keep"))
    c.append(label(ix + 104, top - 2, 640, 52, "font40_title", TEXT, prop("heading")))
    c.append(label(ix + 104, top + 48, 640, 34, "font12", TEXT2, prop("title")))
    c.append(label(ix + iw - 200, top, 200, 80, "font32_title", MINT, prop("elapsed"), align="right"))
    top += 80 + 36
    c.append(image(ix, top, iw, 18, "spongetv-bar.png", NAVY_DEEP, 9))
    c.append("\n".join([
        '        <control type="progress" id="3100">',
        f"            <left>{ix}</left><top>{top}</top><width>{iw}</width><height>18</height>",
        '            <texturebg colordiffuse="00FFFFFF">spongetv-bar.png</texturebg>',
        f'            <midtexture border="9" colordiffuse="{TEAL}">spongetv-bar.png</midtexture>',
        "        </control>"]))
    c.append(label(ix, top + 32, iw, 30, "font10", TEXT2, prop("providers_line")))
    top += 62 + 36
    tile_w = (iw - 60) // 4
    for n, (key, colour) in enumerate((("4K", AMBER), ("1080p", TEAL), ("720p", TEXT2), ("other", TEXT2))):
        tx = ix + n * (tile_w + 20)
        c.append(image(tx, top, tile_w, 122, "spongetv-r20.png", NAVY_DEEP, 20))
        text = prop("other_label") if key == "other" else key
        c.append(label(tx + 24, top + 18, tile_w - 48, 28, "font20_title", colour, text))
        c.append(label(tx + 24, top + 50, tile_w - 48, 58, "font52_title", TEXT, prop("count_" + key.lower())))
    top += 122 + 36
    for n, (key, colour, text_colour) in enumerate((("ready_line", TEAL, TEXT), ("early_line", AMBER, TEXT),
                                                    ("searching_line", MUTED, TEXT2))):
        ly = top + n * 44
        visible = f"!String.IsEmpty(Window.Property({key}))"
        c.append(image(ix, ly + 8, 14, 14, "spongetv-dot.png", colour, visible=visible))
        c.append(label(ix + 28, ly, iw - 28, 30, "font10", text_colour, prop(key), visible=visible))
    top += 118 + 36
    c.append(button(3001, ix, top, 420, 72, prop("choose_label"), "font25_title", main=True,
                    enable="!String.IsEmpty(Window.Property(can_choose))",
                    nav="            <onright>3002</onright>"))
    c.append(button(3002, ix + 440, top, 200, 72, prop("cancel_label"), "font25_title",
                    nav="            <onleft>3001</onleft>"))
    return window(3002, c, "SpongeTV source search progress, from the approved mock-up.")


# -- Playing Next -------------------------------------------------------------------------------------------
def playing_next():
    x0, w0, h0 = 1020, 820, 322
    y0 = 1080 - 80 - h0
    ix, iy = x0 + 32, y0 + 32
    c = []
    c.append(image(x0, y0, w0, h0, "spongetv-r28.png", NAVY, 28))
    c.append(image(x0, y0, w0, h0, "spongetv-r28-line2.png", BORDER, 28))
    c.append(image(ix, iy, 288, 162, "spongetv-r16.png", NAVY_LIGHT, 16))
    c.append(image(ix, iy, 288, 162, prop("thumb"), aspect="scale"))
    c.append(image(ix, iy, 288, 162, "spongetv-r16-line2.png", BORDER, 16))
    tx, tw = ix + 288 + 28, 820 - 64 - 288 - 28 - 88 - 28
    c.append(label(tx, iy - 2, tw, 28, "font20_title", TEAL, f"[UPPERCASE]{prop('heading')}[/UPPERCASE]"))
    c.append(label(tx, iy + 26, tw, 44, "font32_title", TEXT, prop("show")))
    c.append(label(tx, iy + 72, tw, 32, "font10", TEXT2, prop("episode")))
    c.append(image(tx, iy + 124, 12, 12, "spongetv-dot.png", prop("status_colour")))
    c.append(label(tx + 22, iy + 114, x0 + w0 - 32 - tx - 22, 32, "font10", MINT, prop("status")))  # under the ring
    rx = x0 + w0 - 32 - 88
    c.append(image(rx, iy, 88, 88, "spongetv-ring-track.png", BORDER))
    c.append(image(rx, iy, 88, 88, prop("ring"), AMBER))
    c.append(label(rx, iy, 88, 88, "font30_title", TEXT, prop("seconds"), align="center"))
    by = iy + 162 + 28
    c.append(button(4001, ix, by, 230, 68, prop("play_now"), "font25_title", main=True,
                    icon=("spongetv-play.png", AMBER, 32), nav="            <onright>4002</onright>"))
    c.append(button(4002, ix + 248, by, 370, 68, prop("stop_after"), "font25_title",
                    nav="            <onleft>4001</onleft>"))
    out = window(4001, c, "SpongeTV Playing Next, a card over the video, from the approved mock-up.", fade=False)
    return out.replace("    <controls>", '    <animation type="WindowOpen" reversible="false">\n'
                       '        <effect type="slide" start="0,40" end="0,0" time="250" tween="cubic" easing="out"/>\n'
                       '        <effect type="fade" start="0" end="100" time="250"/>\n    </animation>\n'
                       '    <animation type="WindowClose" reversible="false">\n'
                       '        <effect type="fade" start="100" end="0" time="200"/>\n    </animation>\n'
                       "    <controls>", 1)


if __name__ == "__main__":
    for name, build in (("spongetv-sourceselect.xml", source_select), ("spongetv-sourcesearch.xml", source_search),
                        ("spongetv-playingnext.xml", playing_next)):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as handle:
            handle.write(build())
        print("wrote", name)
