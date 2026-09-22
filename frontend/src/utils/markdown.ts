export type Inline =
  | { kind: 'text'; value: string }
  | { kind: 'bold'; value: string }
  | { kind: 'code'; value: string }
  | { kind: 'cite'; id: string }

export type Block =
  | { kind: 'heading'; level: number; parts: Inline[] }
  | { kind: 'paragraph'; parts: Inline[] }
  | { kind: 'list'; ordered: boolean; items: Inline[][] }
  | { kind: 'table'; header: Inline[][]; rows: Inline[][][] }

const INLINE_TOKEN = /(\[evidence:[^\]]+\])|(\*\*[^*]+\*\*)|(`[^`]+`)/g

export function parseInline(text: string): Inline[] {
  const parts: Inline[] = []
  let cursor = 0
  let match: RegExpExecArray | null
  INLINE_TOKEN.lastIndex = 0
  while ((match = INLINE_TOKEN.exec(text))) {
    if (match.index > cursor) parts.push({ kind: 'text', value: text.slice(cursor, match.index) })
    const token = match[0]
    if (token.startsWith('[evidence:')) {
      parts.push({ kind: 'cite', id: token.slice(10, -1) })
    } else if (token.startsWith('**')) {
      parts.push({ kind: 'bold', value: token.slice(2, -2) })
    } else {
      parts.push({ kind: 'code', value: token.slice(1, -1) })
    }
    cursor = match.index + token.length
  }
  if (cursor < text.length) parts.push({ kind: 'text', value: text.slice(cursor) })
  return parts
}

const isTableRow = (line: string) => /^\s*\|.*\|\s*$/.test(line)
const isTableSeparator = (line: string) => line.includes('-') && /^\s*\|?[\s:|-]+\|?\s*$/.test(line)
const isHeading = (line: string) => /^(#{1,6})\s+/.test(line)
const isUnordered = (line: string) => /^\s*[-*]\s+/.test(line)
const isOrdered = (line: string) => /^\s*\d+\.\s+/.test(line)

function splitRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => parseInline(cell.trim()))
}

export function parseMarkdown(content: string): Block[] {
  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const blocks: Block[] = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }

    if (isHeading(line)) {
      const match = /^(#{1,6})\s+(.*)$/.exec(line)!
      blocks.push({ kind: 'heading', level: match[1].length, parts: parseInline(match[2].trim()) })
      index += 1
      continue
    }

    if (isTableRow(line)) {
      const rows: string[] = []
      while (index < lines.length && isTableRow(lines[index])) {
        rows.push(lines[index])
        index += 1
      }
      const cells = rows.filter((row) => !isTableSeparator(row)).map(splitRow)
      if (cells.length) blocks.push({ kind: 'table', header: cells[0], rows: cells.slice(1) })
      continue
    }

    if (isUnordered(line) || isOrdered(line)) {
      const ordered = isOrdered(line)
      const items: Inline[][] = []
      const pattern = ordered ? /^\s*\d+\.\s+(.*)$/ : /^\s*[-*]\s+(.*)$/
      while (index < lines.length && (ordered ? isOrdered(lines[index]) : isUnordered(lines[index]))) {
        items.push(parseInline(pattern.exec(lines[index])![1].trim()))
        index += 1
      }
      blocks.push({ kind: 'list', ordered, items })
      continue
    }

    const paragraph: string[] = []
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isHeading(lines[index]) &&
      !isTableRow(lines[index]) &&
      !isUnordered(lines[index]) &&
      !isOrdered(lines[index])
    ) {
      paragraph.push(lines[index].trim())
      index += 1
    }
    blocks.push({ kind: 'paragraph', parts: parseInline(paragraph.join(' ')) })
  }

  return blocks
}

export function hasInlineCitation(content: string) {
  return /\[evidence:[^\]]+\]/.test(content)
}
