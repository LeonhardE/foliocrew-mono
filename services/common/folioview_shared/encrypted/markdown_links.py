"""Internal linear destination collection for schema-bounded normalized text.

This preserves Python's original three ``re.findall`` capture lists, including
their order and duplicates. URL policy and content validation belong to callers.
"""


def markdown_destinations(text: str) -> list[str]:
    size = len(text)
    whitespace = [size] * (size + 1)
    non_whitespace = [size] * (size + 1)
    inline_stop = [size] * (size + 1)
    right_bracket = [size] * (size + 1)
    greater_than = [size] * (size + 1)
    angle_stop = [size] * (size + 1)
    colon_before = [0] * (size + 1)
    for i in range(size - 1, -1, -1):
        char = text[i]
        # Python's Unicode regex \s matches the same single-character set as
        # str.isspace(), including separators not considered whitespace by JS.
        space = char.isspace()
        whitespace[i] = i if space else whitespace[i + 1]
        non_whitespace[i] = non_whitespace[i + 1] if space else i
        inline_stop[i] = i if space or char == ")" else inline_stop[i + 1]
        right_bracket[i] = i if char == "]" else right_bracket[i + 1]
        greater_than[i] = i if char == ">" else greater_than[i + 1]
        angle_stop[i] = i if space or char in "<>" else angle_stop[i + 1]
    for i, char in enumerate(text):
        colon_before[i + 1] = i + 1 if char == ":" else colon_before[i]

    destinations = []
    cursor = 0
    while cursor < size:
        marker = text.find("](", cursor)
        if marker == -1:
            break
        cursor = marker + 2
        start = non_whitespace[cursor]
        if start == size:
            continue
        close = greater_than[start + 1]
        end = close + 1 if text[start] == "<" and start + 1 < close < size else inline_stop[start]
        if end > start:
            destinations.append(text[start:end])
            cursor = end

    cursor = 0
    for line in range(size):
        # Unlike JS multiline ^, Python's original (?m)^ recognizes only LF.
        if line < cursor or (line and text[line - 1] != "\n"):
            continue
        opening = non_whitespace[line]
        if opening == size or text[opening] != "[":
            continue
        close = right_bracket[opening + 1]
        if close >= size - 1 or close == opening + 1 or text[close + 1] != ":":
            continue
        start = non_whitespace[close + 2]
        if start == size:
            continue
        cursor = whitespace[start]
        destinations.append(text[start:cursor])

    cursor = 0
    while cursor < size:
        opening = text.find("<", cursor)
        if opening == -1:
            break
        cursor = opening + 1
        end = angle_stop[cursor]
        if end < size and text[end] == ">" and colon_before[end] > cursor + 1:
            destinations.append(text[cursor:end])
            cursor = end + 1
    return destinations
