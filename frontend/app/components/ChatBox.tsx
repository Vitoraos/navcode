import { useState } from "react";

export default function ChatBox({ onSend, disabled }: any) {
  const [text, setText] = useState("");

  return (
    <div className="flex gap-2 mt-3">
      <input
        className="flex-1 bg-zinc-900 p-2"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Ask NavGuard..."
      />

      <button
        disabled={disabled}
        onClick={() => {
          onSend(text);
          setText("");
        }}
        className="btn"
      >
        Send
      </button>
    </div>
  );
}
