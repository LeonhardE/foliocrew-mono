const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const { compile } = require("./resource-library-helpers.cjs");

const markdown = compile(
  "../components/SafeReportMarkdown.tsx",
  { "react/jsx-runtime": require("react/jsx-runtime") },
  {
    URL,
    fetch() {
      assert.fail("Rendering a report must not fetch content.");
    },
  },
);

test("report Markdown escapes markup and does not turn unsafe links or images into navigation", () => {
  const payload = '<img src=x onerror="window.EXECUTED=true"><script>SECRET_SCRIPT</script>';
  const html = renderToStaticMarkup(
    React.createElement(markdown.SafeReportMarkdown, {
      markdown:
        payload +
        "\n\n[script](javascript:alert(1))\n![image](https://example.test/never-fetch.png)",
    }),
  );
  assert.ok(!/<(?:img|script|iframe|object|embed)\b/i.test(html));
  assert.ok(!/\shref="(?:javascript|data|http):/i.test(html));
  assert.ok(html.includes("&lt;img"));
  assert.ok(html.includes("SECRET_SCRIPT"));
  assert.ok(!html.includes('href="https://example.test/never-fetch.png"'));
});

test("safe navigation requires explicit credential-free HTTPS without whitespace or alternate ports", () => {
  for (const url of [
    "javascript:alert(1)",
    "data:text/html,hi",
    "http://example.test",
    "//example.test",
    "/relative",
    "https://user:secret@example.test",
    "https://example.test:444/a",
    "https://example.test/ spaced",
    "https://example.test\\path",
    " https://example.test",
    "https://example.test/\n",
  ])
    assert.equal(markdown.reportLink(url), null, url);
  for (const url of ["https://example.test/a?x=1#source", "https://example.test:443/a"])
    assert.equal(markdown.reportLink(url), url);
});

test("restricted Markdown formats text and code but bounds large line counts without truncating the report", () => {
  const html = renderToStaticMarkup(
    React.createElement(markdown.SafeReportMarkdown, {
      markdown:
        "## Heading\n\n**Bold** and `sample`\n\n- First\n- Second\n\n```text\n<img src=x>\n```",
    }),
  );
  assert.match(html, /<h3>Heading<\/h3>/);
  assert.match(html, /<strong>Bold<\/strong>/);
  assert.match(html, /<ul><li>First<\/li><li>Second<\/li><\/ul>/);
  assert.match(html, /<pre><code>&lt;img src=x&gt;<\/code><\/pre>/);
  const large = "line\n".repeat(500) + "FINAL_SENTINEL";
  const bounded = renderToStaticMarkup(
    React.createElement(markdown.SafeReportMarkdown, { markdown: large }),
  );
  assert.equal((bounded.match(/<p/g) ?? []).length, 1);
  assert.ok(bounded.includes("FINAL_SENTINEL"));
});
