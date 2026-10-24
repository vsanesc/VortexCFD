"""Layout checks for the screen tests (D-155): no two visible widgets overlap, and no label's text is clipped.

Only leaf widgets are compared (a widget with visible children is a container: its children are checked instead);
a widget marked with the ``overlay`` property (drawn on top of another on purpose) is skipped.
"""

import math

from PySide6.QtCore import QRect, Qt
from PySide6 import QtGui
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QAbstractScrollArea, QLabel, QWidget


def _visible_children(widget: QWidget) -> list[QWidget]:
    direct = widget.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
    return [c for c in direct if c.isVisible() and not c.isWindow()]


def _clip_rect(widget: QWidget, root: QWidget) -> QRect:
    """The part of ``widget`` that is on screen within ``root``: its rect cut by every ancestor's (a scroll area's
    viewport hides what is scrolled away)."""
    rect = QRect(widget.mapTo(root, widget.rect().topLeft()), widget.size())
    parent = widget.parentWidget()
    while parent is not None and parent is not root:
        rect = rect.intersected(QRect(parent.mapTo(root, parent.rect().topLeft()), parent.size()))
        parent = parent.parentWidget()
    return rect.intersected(root.rect())


def leaves(root: QWidget) -> list[QWidget]:
    out = []
    stack = [root]
    while stack:
        widget = stack.pop()
        children = _visible_children(widget)
        if isinstance(widget, QAbstractScrollArea):
            out.extend(c for c in children if c is not widget.viewport() or not _visible_children(c))
            stack.extend(c for c in children if c is widget.viewport() and _visible_children(c))
            continue
        if children:
            stack.extend(children)
        elif widget is not root and not widget.property("overlay"):
            out.append(widget)
    return out


def overlaps(root: QWidget, tolerance: int = 1) -> list[str]:
    """Pairs of visible leaf widgets whose on-screen rectangles overlap (by more than ``tolerance`` pixels in both
    directions)."""
    rects = [(w, _clip_rect(w, root)) for w in leaves(root)]
    rects = [(w, r) for w, r in rects if r.width() > 0 and r.height() > 0]
    out = []
    for i, (a, ra) in enumerate(rects):
        for b, rb in rects[i + 1:]:
            if a.isAncestorOf(b) or b.isAncestorOf(a):
                continue
            inter = ra.intersected(rb)
            if inter.width() > tolerance and inter.height() > tolerance:
                out.append(f"{describe(a)} overlaps {describe(b)} ({inter.width()}x{inter.height()})")
    return out


def describe(widget: QWidget) -> str:
    text = widget.text() if hasattr(widget, "text") and callable(widget.text) else ""
    text = text if isinstance(text, str) else ""
    parent = widget.parentWidget()
    where = f" in {type(parent).__name__}#{parent.objectName()}" if parent is not None else ""
    return f"{type(widget).__name__}#{widget.objectName()} {text[:40]!r}{where}"


def _rich(label: QLabel) -> bool:
    fmt = label.textFormat()
    return fmt == Qt.TextFormat.RichText or fmt == Qt.TextFormat.AutoText and QtGui.Qt.mightBeRichText(QLabel.text(label))


def text_height(label: QLabel, width: int) -> int:
    """A word-wrapped label's text height at the content width ``width`` (QLabel.heightForWidth overestimates)."""
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(label.font())
    if _rich(label):
        document.setHtml(QLabel.text(label))
    else:
        document.setPlainText(QLabel.text(label))
    document.setTextWidth(max(width, 1))
    return math.ceil(document.size().height())


def clipped_labels(root: QWidget) -> list[str]:
    """Visible labels whose text does not fit: a one-line label narrower or lower than its size hint (descenders
    included), a wrapped one lower than its text at its width. An elided label (its text set to fit) passes."""
    out = []
    for label in root.findChildren(QLabel):
        shown = QLabel.text(label)  # what Qt draws (a subclass's text() may return a full, unelided text)
        if not label.isVisible() or not shown or label.pixmap() is not None and not label.pixmap().isNull():
            continue
        margins = label.contentsMargins()
        inner_w = label.width() - margins.left() - margins.right()
        inner_h = label.height() - margins.top() - margins.bottom()
        if label.wordWrap():
            need = text_height(label, inner_w)
            if need > inner_h + 1:
                out.append(f"{describe(label)}: wrapped text {need} px high in {inner_h}")
            continue
        fm = label.fontMetrics()
        lines = shown.split("\n")
        if _rich(label):
            need_h, need_w = text_height(label, 1 << 20), 0
        else:
            need_h = fm.height() * len(lines)
            need_w = max(fm.horizontalAdvance(line) for line in lines)
        if need_h > inner_h:
            out.append(f"{describe(label)}: {need_h} px of text in {inner_h}")
        if need_w > inner_w + 1:
            out.append(f"{describe(label)}: {need_w} px wide text in {inner_w}")
    return out


def _in_scroll_area(widget: QWidget, root: QWidget) -> bool:
    """Whether ``widget`` is the content of a scroll area under ``root`` (cut by its viewport on purpose)."""
    parent = widget.parentWidget()
    while parent is not None and parent is not root:
        scroll = parent.parentWidget()
        if isinstance(scroll, QAbstractScrollArea) and parent is scroll.viewport():
            return True
        parent = parent.parentWidget()
    return False


def cut_off(root: QWidget) -> list[str]:
    """Visible widgets that are partly or wholly outside their parents (a squeezed container cuts them), or
    collapsed to nothing; a scroll area's content is cut by its viewport on purpose and is not counted."""
    out = []
    for widget in leaves(root):
        if _in_scroll_area(widget, root):
            continue
        full = QRect(widget.mapTo(root, widget.rect().topLeft()), widget.size())
        if widget.width() <= 0 or widget.height() <= 0:
            out.append(f"{describe(widget)}: collapsed to {widget.width()}x{widget.height()}")
        elif _clip_rect(widget, root) != full.intersected(root.rect()) or not root.rect().contains(full):
            seen = _clip_rect(widget, root)
            out.append(f"{describe(widget)}: {seen.width()}x{seen.height()} of {full.width()}x{full.height()} shown")
    return out


def problems(root: QWidget) -> list[str]:
    return overlaps(root) + clipped_labels(root) + cut_off(root)
