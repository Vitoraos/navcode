import { ChatRequest } from "./types";

export async function sendChatRequest(payload: ChatRequest) {
  // Ensure you have NEXT_PUBLIC_BACKEND_URL set in your .env.local
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  
  const res = await fetch(`${backendUrl}/chat`, {
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
  onError?: (err: string) => void // Added optional error handler
) {
  const reader = response.body?.getReader();
  const decoder = new TextDecoder();
  
  if (!reader) {
    onError?.("No response body");
    return;
  }

  let buffer = "";
  
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || ""; // Keep incomplete line in buffer

      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        
        const data = line.slice(5).trim(); // Remove "data:"
        
        if (data === "[DONE]") {
          onDone();
          return;
        }

        try {
          const parsed = JSON.parse(data);
          if (parsed.text) {
            onToken(parsed.text);
          }
          if (parsed.error) {
            onError?.(parsed.error);
          }
        } catch (e) {
          console.warn("Failed to parse SSE chunk:", line);
        }
      }
    }
    onDone();
  } catch (err) {
    console.error("Stream reading error:", err);
    onError?.("Stream interrupted");
  }
}
