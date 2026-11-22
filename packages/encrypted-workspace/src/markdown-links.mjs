/** Pure destination collection for schema-bounded, already normalized Markdown. */
export function markdownDestinations(text) {
  if (typeof text !== "string") throw new TypeError("Markdown text must be a string.");
  const size = text.length;
  const whitespace = new Uint32Array(size + 1);
  const nonWhitespace = new Uint32Array(size + 1);
  const inlineStop = new Uint32Array(size + 1);
  const rightBracket = new Uint32Array(size + 1);
  const greaterThan = new Uint32Array(size + 1);
  const angleStop = new Uint32Array(size + 1);
  const colonBefore = new Uint32Array(size + 1);
  for (const index of [whitespace, nonWhitespace, inlineStop, rightBracket, greaterThan, angleStop])
    index.fill(size, -1);
  for (let i = size - 1; i >= 0; i--) {
    const char = text[i];
    // Use JavaScript's exact single-code-unit \s classification, including its
    // Unicode whitespace, without rescanning a suffix from each candidate.
    const space = /\s/.test(char);
    whitespace[i] = space ? i : whitespace[i + 1];
    nonWhitespace[i] = space ? nonWhitespace[i + 1] : i;
    inlineStop[i] = space || char === ")" ? i : inlineStop[i + 1];
    rightBracket[i] = char === "]" ? i : rightBracket[i + 1];
    greaterThan[i] = char === ">" ? i : greaterThan[i + 1];
    angleStop[i] = space || char === "<" || char === ">" ? i : angleStop[i + 1];
  }
  for (let i = 0; i < size; i++) colonBefore[i + 1] = text[i] === ":" ? i + 1 : colonBefore[i];

  const destinations = [];
  let cursor = 0;
  while (cursor < size) {
    const marker = text.indexOf("](", cursor);
    if (marker === -1) break;
    cursor = marker + 2;
    const start = nonWhitespace[cursor];
    if (start === size) continue;
    const close = greaterThan[start + 1];
    // The angle alternative takes precedence only when it has a nonempty body
    // and closing >. Otherwise the original non-whitespace alternative applies.
    const end =
      text[start] === "<" && close < size && close > start + 1 ? close + 1 : inlineStop[start];
    if (end > start) {
      destinations.push(text.slice(start, end));
      cursor = end;
    }
  }

  cursor = 0;
  for (let line = 0; line < size; line++) {
    if (line < cursor) continue;
    const previous = text.charCodeAt(line - 1);
    if (line !== 0 && ![10, 13, 0x2028, 0x2029].includes(previous)) continue;
    const open = nonWhitespace[line];
    if (text[open] !== "[") continue;
    const close = rightBracket[open + 1];
    if (close === size || close === open + 1 || text[close + 1] !== ":") continue;
    const start = nonWhitespace[close + 2];
    if (start === size) continue;
    cursor = whitespace[start];
    destinations.push(text.slice(start, cursor));
  }

  cursor = 0;
  while (cursor < size) {
    const open = text.indexOf("<", cursor);
    if (open === -1) break;
    cursor = open + 1;
    const end = angleStop[cursor];
    // The group covers the entire body. Its separator must follow at least one
    // body character; choosing the last colon preserves the greedy alternative.
    if (text[end] === ">" && colonBefore[end] > cursor + 1) {
      destinations.push(text.slice(cursor, end));
      cursor = end + 1;
    }
  }
  return destinations;
}
