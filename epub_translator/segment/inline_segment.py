from collections.abc import Generator, Iterable, Iterator
from dataclasses import dataclass
from xml.etree.ElementTree import Element

from ..utils import ensure_list, is_the_same, nest, normalize_whitespace


def _normalize_fill_content(text: str, original: str | None, *, tail: bool = False) -> str:
    """Normalize text from an indented fill LLM response.

    When the fill LLM indents its output, every ``\n  `` sequence replaces a
    meaningful space (or no space).  We cannot recover the correct spacing from
    the indented text alone, so we use *original* — the corresponding text node
    from ``self.create_element()`` — as the authoritative source for leading and
    trailing spaces.

    For compact (non-indented) fill responses there are no newlines, so the text
    is mostly returned unchanged.  Two structural separators are still restored:

    * **Tail leading space** (Tier-2): if the fill tail starts with a word
      character but the original tail did not (started with a space or was
      empty/punctuation), restore the leading space.
    * **Text trailing space**: if the fill text (non-tail) ends with a word
      character but the original text ended with a space (separator before a
      child element), restore the trailing space.

    When ``tail=True`` the leading-space decision uses a word-boundary heuristic
    with three tiers:

    1. Content starts with punctuation/symbol (not alphanumeric): never add a
       leading space.  A comma or period never needs a space before it in a tail,
       regardless of what the original tail looked like.

    2. Content starts with a word character AND the original tail did not (None,
       empty, or punctuation/space): add a leading space.  Covers cases where the
       fill LLM added new content (e.g. Hungarian "cimű") or reordered words so
       that a word now follows the element (e.g. "nevezhetnénk." where the source
       had only ".").

    3. Both content and original start with a word character: use the original
       tail's leading space (or lack thereof) as-is.  This preserves no-space
       direct attachments like "<em>Freud</em>ian".
    """
    if "\n" not in text:
        # Compact mode: mostly trust the LLM, but restore structural separators
        # that the LLM silently dropped when translating.
        orig = original or ""
        result = text
        if tail:
            # Leading edge — Tier-2: word content where original had non-word
            # (space or punctuation) means the separator was dropped.
            if result and result[0].isalnum() and (not orig or not orig[0].isalnum()):
                result = " " + result
        else:
            # Trailing edge: space before a child element is structural; if the
            # original had it and the fill lost it, restore it.
            if result and result[-1].isalnum() and orig.endswith(" "):
                result = result + " "
        return result
    content = normalize_whitespace(text).strip()
    if not content:
        return ""
    orig = original or ""
    if tail:
        content_starts_word = content[0].isalnum()
        orig_starts_word = bool(orig) and orig[0].isalnum()
        if not content_starts_word:
            leading = ""  # punctuation/symbol: never a leading space
        elif not orig_starts_word:
            leading = " "  # word where original had non-word: add separator
        else:
            leading = " " if orig.startswith(" ") else ""
    else:
        leading = " " if orig.startswith(" ") else ""
    trailing = " " if orig.endswith(" ") else ""
    return leading + content + trailing
from ..xml import ID_KEY, append_text_in_element, iter_with_stack, plain_text
from .common import FoundInvalidIDError, validate_id_in_element
from .text_segment import TextSegment
from .utils import IDGenerator, element_fingerprint, id_in_element


@dataclass
class InlineLostIDError:
    element: Element
    stack: list[Element]


@dataclass
class InlineUnexpectedIDError:
    id: int
    element: Element


@dataclass
class InlineExpectedIDsError:
    id2element: dict[int, Element]


@dataclass
class InlineWrongTagCountError:
    expected_count: int
    found_elements: list[Element]
    stack: list[Element]


InlineError = InlineLostIDError | InlineUnexpectedIDError | InlineExpectedIDsError | InlineWrongTagCountError


def search_inline_segments(text_segments: Iterable[TextSegment]) -> Generator["InlineSegment", None, None]:
    stack_data: tuple[list[list[TextSegment | InlineSegment]], Element, int] | None = None
    inline_segment: InlineSegment | None = None

    for text_segment in text_segments:
        if stack_data is not None:
            stack, stack_block, stack_base_depth = stack_data
            if stack_block is not text_segment.block_parent:
                inline_segment = _pop_stack_data(stack_data)
                stack_data = None
                if inline_segment:
                    inline_segment.id = 0
                    yield inline_segment

        if stack_data is None:
            stack_data = (
                [],
                text_segment.block_parent,
                text_segment.block_depth,
            )

        stack, stack_block, stack_base_depth = stack_data

        while len(stack) < text_segment.depth + 1:
            stack.append([])

        while len(stack) > text_segment.depth + 1:
            _pop_stack(
                stack=stack,
                stack_base_depth=stack_base_depth,
            )

        # When adjacent sibling inline elements switch parent at the same depth
        # (e.g. <span>T</span><small>HIS</small>), pop to the common depth so they
        # form separate InlineSegments rather than being merged into one.
        if text_segment.left_common_depth >= stack_base_depth:
            target_len = text_segment.left_common_depth - stack_base_depth + 1
            while len(stack) > target_len:
                _pop_stack(stack=stack, stack_base_depth=stack_base_depth)
            while len(stack) < text_segment.depth + 1:
                stack.append([])

        # text_segment.depth 可视为它在 stack 中的 index，必须令 len(stack) == text_segment.depth + 1
        stack[-1].append(text_segment)

    if stack_data is not None:
        inline_segment = _pop_stack_data(stack_data)
        if inline_segment:
            inline_segment.id = 0
            yield inline_segment


def _pop_stack_data(stack_data: tuple[list[list["TextSegment | InlineSegment"]], Element, int]):
    stack, _, stack_base_depth = stack_data
    inline_segment: InlineSegment | None = None
    while stack:
        inline_segment = _pop_stack(
            stack=stack,
            stack_base_depth=stack_base_depth,
        )
    return inline_segment


def _pop_stack(
    stack: list[list["TextSegment | InlineSegment"]],
    stack_base_depth: int,
) -> "InlineSegment | None":
    inline_segment: InlineSegment | None = None
    depth = len(stack) + stack_base_depth - 1
    popped = stack.pop()
    if popped:
        inline_segment = InlineSegment(depth, popped)
    if stack and inline_segment is not None:
        stack[-1].append(inline_segment)
    return inline_segment


class InlineSegment:
    def __init__(self, depth: int, children: list["TextSegment | InlineSegment"]) -> None:
        assert depth > 0
        self.id: int | None = None
        self._children: list[TextSegment | InlineSegment] = children
        self._parent_stack: list[Element] = children[0].parent_stack[:depth]

        # 每一组 tag 都对应一个 ids 列表。
        # 若为空，说明该 tag 属性结构全同，没必要分配 id 以区分。
        # 若非空，则表示 tag 下每一个 element 都有 id 属性。
        # 注意，相同 tag 下的 element 要么全部有 id，要么全部都没有 id
        self._child_tag2ids: dict[str, list[int]] = {}
        self._child_tag2count: dict[str, int] = {}

        next_temp_id: int = 1
        terms = nest((child.parent.tag, child) for child in children if isinstance(child, InlineSegment))

        for tag, child_terms in terms.items():
            self._child_tag2count[tag] = len(child_terms)
            if not is_the_same(  # 仅当 tag 彼此无法区分时才分配 id，以尽可能减少 id 的数量
                elements=(element_fingerprint(t.parent) for t in child_terms),
            ):
                for child in child_terms:
                    child.id = next_temp_id
                    next_temp_id += 1

    @property
    def head(self) -> TextSegment:
        first_child = self._children[0]
        if isinstance(first_child, TextSegment):
            return first_child
        else:
            return first_child.head

    @property
    def tail(self) -> TextSegment:
        last_child = self._children[-1]
        if isinstance(last_child, TextSegment):
            return last_child
        else:
            return last_child.tail

    @property
    def children(self) -> list["TextSegment | InlineSegment"]:
        return self._children

    @property
    def parent(self) -> Element:
        return self._parent_stack[-1]

    @property
    def parent_stack(self) -> list[Element]:
        return self._parent_stack

    def __iter__(self) -> Iterator[TextSegment]:
        for child in self._children:
            if isinstance(child, TextSegment):
                yield child
            elif isinstance(child, InlineSegment):
                yield from child

    def clone(self) -> "InlineSegment":
        cloned_segment = InlineSegment(
            depth=len(self._parent_stack),
            children=[child.clone() for child in self._children],
        )
        cloned_segment.id = self.id
        return cloned_segment

    def recreate_ids(self, id_generator: IDGenerator) -> None:
        self._child_tag2count.clear()
        self._child_tag2ids.clear()

        for child in self._children:
            if isinstance(child, InlineSegment):
                child_tag = child.parent.tag
                ids = ensure_list(self._child_tag2ids, child_tag)
                if child.id is not None:
                    child.id = id_generator.next_id()
                    ids.append(child.id)
                child.recreate_ids(id_generator)
                self._child_tag2count[child_tag] = self._child_tag2count.get(child_tag, 0) + 1

    def create_element(self) -> Element:
        element = Element(self.parent.tag)
        previous_element: Element | None = None
        for child in self._children:
            if isinstance(child, InlineSegment):
                previous_element = child.create_element()
                element.append(previous_element)

            elif isinstance(child, TextSegment):
                if previous_element is None:
                    element.text = append_text_in_element(
                        origin_text=element.text,
                        append_text=child.text,
                    )
                else:
                    previous_element.tail = append_text_in_element(
                        origin_text=previous_element.tail,
                        append_text=child.text,
                    )
        if self.id is not None:
            element.set(ID_KEY, str(self.id))
        return element

    def validate(self, validated_element: Element) -> Generator[InlineError | FoundInvalidIDError, None, None]:
        remain_expected_elements: dict[int, Element] = {}
        for child in self._child_inline_segments():
            if child.id is not None:
                remain_expected_elements[child.id] = child.parent

        for _, child_element in iter_with_stack(validated_element):
            if child_element is validated_element:
                continue  # skip the root self

            element_id = id_in_element(child_element)
            if element_id is None:
                validated_id = validate_id_in_element(
                    element=child_element,
                    enable_no_id=True,
                )
                if isinstance(validated_id, FoundInvalidIDError):
                    yield validated_id
                continue

            remain_expected_element = remain_expected_elements.pop(element_id, None)
            if remain_expected_element is None:
                yield InlineUnexpectedIDError(
                    id=element_id,
                    element=child_element,
                )

        if remain_expected_elements:
            yield InlineExpectedIDsError(
                id2element=remain_expected_elements,
            )

        yield from self._validate_children_structure(validated_element)

    def _child_inline_segments(self) -> Generator["InlineSegment", None, None]:
        for child in self._children:
            if isinstance(child, InlineSegment):
                yield child
                yield from child._child_inline_segments()  # pylint: disable=protected-access

    def _validate_children_structure(self, validated_element: Element):
        tag2found_elements: dict[str, list[Element]] = {}

        for child_element in validated_element:
            ids = self._child_tag2ids.get(child_element.tag, None)
            if not ids:
                found_elements = ensure_list(tag2found_elements, child_element.tag)
                found_elements.append(child_element)
            else:
                id_str = child_element.get(ID_KEY, None)
                if id_str is None:
                    yield InlineLostIDError(
                        element=child_element,
                        stack=[self.parent],
                    )

        for tag, found_elements in tag2found_elements.items():
            expected_count = self._child_tag2count.get(tag, 0)
            if len(found_elements) != expected_count:
                yield InlineWrongTagCountError(
                    expected_count=expected_count,
                    found_elements=found_elements,
                    stack=[self.parent],
                )

        for child, child_element in self._match_children(validated_element):
            # pylint: disable=protected-access
            for error in child._validate_children_structure(child_element):
                error.stack.insert(0, self.parent)
                yield error

    # 即便 self.validate(...) 的错误没有排除干净，也要尽可能匹配一个质量较高（尽力而为）的版本
    def assign_attributes(self, template_element: Element) -> Element:
        # original_element carries the authoritative spacing for this segment.
        original_element = self.create_element()
        assigned_element = Element(self.parent.tag, self.parent.attrib)
        if template_element.text and template_element.text.strip():
            text = _normalize_fill_content(template_element.text, original_element.text)
            if text:
                assigned_element.text = append_text_in_element(
                    origin_text=assigned_element.text,
                    append_text=text,
                )

        matched_child_element_ids: set[int] = set()
        for child, child_element in self._match_children(template_element):
            child_assigned_element = child.assign_attributes(child_element)
            assigned_element.append(child_assigned_element)
            matched_child_element_ids.add(id(child_element))

        assigned_child_element_stack = list(assigned_element)
        assigned_child_element_stack.reverse()
        original_child_stack = list(original_element)
        original_child_stack.reverse()

        previous_assigned_child_element: Element | None = None
        previous_original_child: Element | None = None
        for child_element in template_element:
            # 只关心 child_element 是否是分割点，不关心它真实对应。极端情况下可能乱序，只好大致对上就行
            child_text: str = ""
            if id(child_element) not in matched_child_element_ids:
                child_text = plain_text(child_element)
            elif assigned_child_element_stack:
                previous_assigned_child_element = assigned_child_element_stack.pop()
                previous_original_child = original_child_stack.pop() if original_child_stack else None
            if child_element.tail is not None:
                orig_tail = previous_original_child.tail if previous_original_child is not None else None
                child_text += _normalize_fill_content(child_element.tail, orig_tail, tail=True)
            if not child_text.strip():
                continue
            if previous_assigned_child_element is None:
                assigned_element.text = append_text_in_element(
                    origin_text=assigned_element.text,
                    append_text=child_text,
                )
            else:
                previous_assigned_child_element.tail = append_text_in_element(
                    origin_text=previous_assigned_child_element.tail,
                    append_text=child_text,
                )
        return assigned_element

    def _match_children(self, element: Element) -> Generator[tuple["InlineSegment", Element], None, None]:
        tag2elements = nest((c.tag, c) for c in element)
        tag2children = nest(
            (c.parent.tag, (i, c)) for i, c in enumerate(c for c in self._children if isinstance(c, InlineSegment))
        )
        used_ids: set[int] = set()
        children_and_elements: list[tuple[int, InlineSegment, Element]] = []

        for tag, orders_and_children in tag2children.items():
            # 优先考虑 id 匹配，剩下的以自然顺序尽可能匹配
            ids = self._child_tag2ids.get(tag, [])
            matched_children_elements: list[Element | None] = [None] * len(orders_and_children)
            not_matched_elements: list[Element] = []

            for child_element in tag2elements.get(tag, []):
                id_order: int | None = None
                child_id = id_in_element(child_element)
                if child_id is not None and child_id not in used_ids:
                    used_ids.add(child_id)  # 一个 id 只能用一次，防止重复
                    try:
                        id_order = ids.index(child_id)
                    except ValueError:
                        pass
                if id_order is None:
                    not_matched_elements.append(child_element)
                else:
                    matched_children_elements[id_order] = child_element

            not_matched_elements.reverse()
            for i in range(len(matched_children_elements)):
                if not not_matched_elements:
                    break
                matched_element = matched_children_elements[i]
                if matched_element is None:
                    matched_children_elements[i] = not_matched_elements.pop()

            for (order, child), child_element in zip(orders_and_children, matched_children_elements):
                if child_element is not None:
                    children_and_elements.append((order, child, child_element))

        for _, child, child_element in sorted(children_and_elements, key=lambda x: x[0]):
            yield child, child_element
