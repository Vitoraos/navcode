import { ChatRequest } from "./types";

export async function sendChatRequest(payload: ChatRequest) {
  const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  return res;
}
export async function streamChatResponse(
  response: Response,
  onToken: (text: string) => void,
  onDone: () => void,
  onError: (err: string) => void
) {
  const reader = response.body?.getReader();
  const decoder = new TextDecoder();
  if (!reader) return;

  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6).trim();
      if (payload === "[DONE]") {
        onDone();
        return;
      }
      try {
        const parsed = JSON.parse(payload);
        if (parsed.text) onToken(parsed.text);
        if (parsed.error) onError(parsed.error);
      } catch (e) {
        console.warn("SSE parse error:", e);
      }
    }
  }
  onDone();
}
