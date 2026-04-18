export function parseSkillMd(text: string) {
  // format: file.ts: description
  const lines = text.split("\n").filter(Boolean);

  const map: Record<string, string> = {};

  for (const line of lines) {
    const [file, ...desc] = line.split(":");
    if (!file || !desc) continue;
    map[file.trim()] = desc.join(":").trim();
  }

  return map;
}
