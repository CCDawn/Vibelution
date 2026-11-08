/**
 * Currency guard for single-dollar LaTeX math in agent markdown.
 *
 * Enabling single-dollar inline math (`$x^2$`) also makes ordinary dollar
 * amounts pair up and vanish into KaTeX: `$5-$10` would render as a formula
 * `5-`, `$100 … $200` would swallow the prose in between. This pass escapes
 * every `$` that pairs with a following `$` but whose content is not plausible
 * math, so currency text keeps rendering as literal text while real formulas
 * pass through untouched (semantics aligned with ZCode's message math
 * normalization). Block math (`$$…$$`) is never touched: double dollars are
 * excluded from single-delimiter detection by construction.
 *
 * Idempotent: an already-escaped `\$` is skipped by delimiter detection, so
 * repeated passes over re-parsed streaming content are no-ops.
 */

/** `\alpha`-style TeX commands are unambiguous math. */
const TEX_COMMAND_PATTERN = /\\[A-Za-z]+/;
/** Glyphs and operators that almost only appear inside formulas. */
const LIKELY_MATH_SYNTAX_PATTERN = /[\\{}^_=+\-*/<>|()[\]∇∂∫∑√∞≈≠≤≥±×÷πΠα-ωΑ-Ω]/u;
/** Bare identifiers (`$x$`, `$abc$`, `$5$`) count as math when unspaced. */
const SIMPLE_MATH_IDENTIFIER_PATTERN = /^(?:[A-Za-z]|[a-z][A-Za-z0-9]{1,2}|\d+(?:\.\d+)?)$/;
/** `5-` / `1,200+` — a compact amount ending right before a closing `$`. */
const COMPACT_CURRENCY_RANGE_PREFIX_PATTERN = /^(?:\d[\d,]*(?:\.\d+)?|\.\d+)[+\-*/]$/;
/** A digit right after the closing `$`: the head of the next amount (`…$10`). */
const COMPACT_CURRENCY_AMOUNT_START_PATTERN = /^(?:\d|\.\d)/;
/** Fence openers, mirroring the markdown normalize pass (` ≥3 backticks/tildes). */
const FENCE_PATTERN = /^\s{0,3}(`{3,}|~{3,})/;

/** True when the character at `index` is preceded by an odd run of backslashes. */
function isEscapedMarkdownCharacter(text: string, index: number): boolean {
  let slashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && text[cursor] === "\\"; cursor--) {
    slashCount++;
  }
  return slashCount % 2 === 1;
}

/**
 * A `$` that opens/closes single-dollar math: isolated from `$$` block math on
 * both sides and not backslash-escaped.
 */
function isSingleDollarDelimiter(text: string, index: number): boolean {
  return (
    text[index] === "$" &&
    text[index - 1] !== "$" &&
    text[index + 1] !== "$" &&
    !isEscapedMarkdownCharacter(text, index)
  );
}

function findClosingSingleDollarDelimiter(text: string, startIndex: number): number {
  for (let index = startIndex; index < text.length; index++) {
    if (isSingleDollarDelimiter(text, index)) {
      return index;
    }
  }
  return -1;
}

/** Heuristic: could this `$…$` content plausibly be a formula? */
function isLikelySingleDollarMath(content: string): boolean {
  if (!content || content !== content.trim() || /[\r\n]/.test(content)) {
    return false;
  }
  if (TEX_COMMAND_PATTERN.test(content) || LIKELY_MATH_SYNTAX_PATTERN.test(content)) {
    return true;
  }
  if (!/\s/.test(content) && SIMPLE_MATH_IDENTIFIER_PATTERN.test(content)) {
    return true;
  }
  return false;
}

/**
 * `$5-$10` shape: the pair content ends with an amount followed by an operator
 * and the next amount starts right after the closing `$`. The closing `$` of
 * such a pair would be misread as a formula terminator.
 */
function isLikelyCompactCurrencyRangeText(text: string, closingIndex: number, content: string): boolean {
  if (!COMPACT_CURRENCY_RANGE_PREFIX_PATTERN.test(content)) {
    return false;
  }
  return COMPACT_CURRENCY_AMOUNT_START_PATTERN.test(text.slice(closingIndex + 1));
}

/** Escape-or-keep scan for one stretch of text without inline code. */
function normalizeSingleDollarMathInText(text: string): string {
  if (!text.includes("$")) {
    return text;
  }

  let output = "";
  for (let index = 0; index < text.length; index++) {
    if (!isSingleDollarDelimiter(text, index)) {
      output += text[index];
      continue;
    }

    const closingIndex = findClosingSingleDollarDelimiter(text, index + 1);
    if (closingIndex === -1) {
      // Unpaired `$` cannot form math by itself; keep it so a closing `$`
      // arriving in later streaming frames can still pair with it.
      output += text[index];
      continue;
    }

    const content = text.slice(index + 1, closingIndex);

    if (isLikelyCompactCurrencyRangeText(text, closingIndex, content)) {
      // Only escape the opening `$`; the closing one is rescanned below and
      // keeps the whole run rendering as plain text with both dollars visible.
      output += "\\$";
      continue;
    }

    if (isLikelySingleDollarMath(content)) {
      output += text.slice(index, closingIndex + 1);
      index = closingIndex;
      continue;
    }

    // `$5 … $10` / `$HOME … $PATH`: paired but not math. Escaping only the
    // current `$` lets the later one stay scannable as its own candidate.
    output += "\\$";
  }

  return output;
}

/**
 * True when this (already guarded) markdown contains math the remark-math pass
 * will actually parse: `$$…$$` block math (never touched by the guard) or a
 * surviving unescaped `$…$` pair passing the same plausibility heuristic the
 * guard keeps. Used to lazy-load the KaTeX pipeline only for messages that
 * render formulas — by construction it agrees with the guard's decisions.
 */
export function containsDeliberateConversationMath(markdown: string): boolean {
  if (!markdown.includes("$")) {
    return false;
  }
  if (markdown.includes("$$")) {
    return true;
  }
  let fence: { marker: string; length: number } | null = null;
  for (const line of markdown.split("\n")) {
    const fenceMatch = FENCE_PATTERN.exec(line);
    const lineFence = fenceMatch
      ? { marker: fenceMatch[1]![0]!, length: fenceMatch[1]!.length }
      : null;
    if (fence) {
      if (lineFence && lineFence.marker === fence.marker && lineFence.length >= fence.length) {
        fence = null;
      }
      continue;
    }
    if (lineFence) {
      fence = lineFence;
      continue;
    }
    // Mirror normalizeSingleDollarMathOutsideInlineCode's code-span skipping:
    // scan outside inline code spans only.
    let cursor = 0;
    while (cursor <= line.length) {
      const codeStart = line.indexOf("`", cursor);
      const segmentEnd = codeStart === -1 ? line.length : codeStart;
      if (hasKeptMathPair(line.slice(cursor, segmentEnd))) {
        return true;
      }
      if (codeStart === -1) {
        break;
      }
      let codeFenceEnd = codeStart + 1;
      while (line[codeFenceEnd] === "`") {
        codeFenceEnd++;
      }
      const codeMarker = line.slice(codeStart, codeFenceEnd);
      const codeEnd = line.indexOf(codeMarker, codeFenceEnd);
      if (codeEnd === -1) {
        // Unterminated inline-code span: the guard scans the rest as text, so
        // mirror that here.
        if (hasKeptMathPair(line.slice(codeStart))) {
          return true;
        }
        break;
      }
      cursor = codeEnd + codeMarker.length;
    }
  }
  return false;
}

/** Guard's keep-criterion applied to one stretch of text without inline code. */
function hasKeptMathPair(text: string): boolean {
  for (let index = 0; index < text.length; index++) {
    if (!isSingleDollarDelimiter(text, index)) {
      continue;
    }
    const closingIndex = findClosingSingleDollarDelimiter(text, index + 1);
    if (closingIndex === -1) {
      break;
    }
    const content = text.slice(index + 1, closingIndex);
    if (!isLikelyCompactCurrencyRangeText(text, closingIndex, content) && isLikelySingleDollarMath(content)) {
      return true;
    }
    index = closingIndex;
  }
  return false;
}
function normalizeSingleDollarMathOutsideInlineCode(line: string): string {
  let output = "";
  let cursor = 0;

  while (cursor < line.length) {
    const codeStart = line.indexOf("`", cursor);
    if (codeStart === -1) {
      output += normalizeSingleDollarMathInText(line.slice(cursor));
      break;
    }

    output += normalizeSingleDollarMathInText(line.slice(cursor, codeStart));

    let codeFenceEnd = codeStart + 1;
    while (line[codeFenceEnd] === "`") {
      codeFenceEnd++;
    }
    const codeMarker = line.slice(codeStart, codeFenceEnd);
    const codeEnd = line.indexOf(codeMarker, codeFenceEnd);
    if (codeEnd === -1) {
      output += normalizeSingleDollarMathInText(line.slice(codeStart));
      break;
    }

    output += line.slice(codeStart, codeEnd + codeMarker.length);
    cursor = codeEnd + codeMarker.length;
  }

  return output;
}

/**
 * Entry point: escape currency-style `$` pairs outside fenced code blocks and
 * inline code so the remark-math pass only sees deliberate formulas.
 */
export function guardConversationMarkdownMath(markdown: string): string {
  if (!markdown.includes("$")) {
    return markdown;
  }

  let output = "";
  let cursor = 0;
  let activeFence: { marker: string; length: number } | null = null;

  while (cursor < markdown.length) {
    const newlineIndex = markdown.indexOf("\n", cursor);
    const lineEnd = newlineIndex === -1 ? markdown.length : newlineIndex;
    const line = markdown.slice(cursor, lineEnd);
    const newline = newlineIndex === -1 ? "" : "\n";
    const fenceMatch = FENCE_PATTERN.exec(line);
    const fence = fenceMatch
      ? { marker: fenceMatch[1]![0]!, length: fenceMatch[1]!.length }
      : null;

    if (activeFence) {
      output += line + newline;
      if (fence && fence.marker === activeFence.marker && fence.length >= activeFence.length) {
        activeFence = null;
      }
    } else {
      output += normalizeSingleDollarMathOutsideInlineCode(line) + newline;
      if (fence) {
        activeFence = fence;
      }
    }

    cursor = lineEnd + newline.length;
  }

  return output;
}
