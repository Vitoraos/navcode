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
  onDone: () => void
) {
  const reader = response.body?.getReader();
  const decoder = new TextDecoder();

  if (!reader) return;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split("\n");

    for (const line of lines) {
      if (!line.startsWith("data:")) continue;

      const data = line.replace("data:", "").trim();

      if (data === "[DONE]") {
        onDone();
        return;
      }

      try {
        const parsed = JSON.parse(data);
        if (parsed.text) onToken(parsed.text);
      } catch }
    }
  }

  onDone();
}
