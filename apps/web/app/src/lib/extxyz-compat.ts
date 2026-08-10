export interface ExtxyzNormalization {
  content: string;
  omittedFields: readonly string[];
  omittedOccurrences: number;
  numericLabels: ReadonlyMap<string, Float64Array>;
}

const JSON_METADATA = /\s+([A-Za-z_][\w.-]*)="_JSON\s+(?:\\.|[^"\\])*"/g;
const NUMERIC_METADATA =
  /(?:^|\s)([A-Za-z_][\w.-]*)=([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)(?=\s|$)/g;

/**
 * Remove ASE `_JSON` comment fields that molrs cannot currently represent.
 * Atom rows, frame boundaries, scalar labels, lattice, and PBC remain byte-for-byte equivalent.
 */
export function normalizeExtxyzForMolvis(input: string): ExtxyzNormalization {
  const lines = input.split("\n");
  const omittedFields = new Set<string>();
  const numericValues = new Map<string, number[]>();
  let omittedOccurrences = 0;
  let cursor = 0;
  let frame = 0;

  while (cursor < lines.length) {
    if (lines[cursor]?.trim() === "") {
      cursor += 1;
      continue;
    }
    const countText = lines[cursor]?.trim() ?? "";
    if (!/^\d+$/.test(countText)) {
      throw new Error(`Extended XYZ frame ${frame} has an invalid atom count.`);
    }
    const atomCount = Number(countText);
    const commentIndex = cursor + 1;
    const nextFrame = commentIndex + 1 + atomCount;
    const atomRows = lines.slice(commentIndex + 1, nextFrame);
    if (
      commentIndex >= lines.length ||
      nextFrame > lines.length ||
      atomRows.length !== atomCount ||
      atomRows.some((line) => line.trim() === "")
    ) {
      throw new Error(`Extended XYZ frame ${frame} is truncated.`);
    }
    const comment = lines[commentIndex] ?? "";
    for (const match of comment.matchAll(NUMERIC_METADATA)) {
      const name = match[1];
      const value = Number(match[2]);
      if (name && Number.isFinite(value)) {
        const values = numericValues.get(name) ?? [];
        values.push(value);
        numericValues.set(name, values);
      }
    }
    lines[commentIndex] = comment.replace(JSON_METADATA, (_match, field: string) => {
      omittedFields.add(field);
      omittedOccurrences += 1;
      return "";
    });
    cursor = nextFrame;
    frame += 1;
  }

  return {
    content: lines.join("\n"),
    omittedFields: [...omittedFields].sort(),
    omittedOccurrences,
    numericLabels: new Map(
      [...numericValues.entries()]
        .filter(([, values]) => values.length === frame)
        .map(([name, values]) => [name, Float64Array.from(values)]),
    ),
  };
}

export async function readBoundedText(response: Response, maxBytes: number): Promise<string> {
  const declaredLength = response.headers.get("content-length");
  if (declaredLength && Number(declaredLength) > maxBytes) {
    await response.body?.cancel();
    throw new Error(`The source is larger than the ${formatLimit(maxBytes)} browser limit.`);
  }
  if (!response.body) throw new Error("The source returned an empty response body.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let total = 0;
  let text = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel();
        throw new Error(`The source is larger than the ${formatLimit(maxBytes)} browser limit.`);
      }
      text += decoder.decode(value, { stream: true });
    }
    return text + decoder.decode();
  } finally {
    reader.releaseLock();
  }
}

function formatLimit(bytes: number): string {
  return `${Math.floor(bytes / (1024 * 1024))} MiB`;
}
