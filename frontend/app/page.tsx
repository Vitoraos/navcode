"use client";

import { useState, useEffect } from "react";
import RepoInput from "@/components/RepoInput";
import FileExplorer from "@/components/FileExplorer";
import ChatBox from "@/components/ChatBox";
import StreamViewer from "@/components/StreamViewer";
import { fetchRepoTree } from "@/lib/github";
import { sendChatRequest, streamChatResponse } from "@/lib/api";

export default function Page() {
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("main");
  const [pat, setPat] = useState("");
  const [skillMd, setSkillMd] = useState("");
  const [tree, setTree] = useState<any[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [output, setOutput] = useState("");
  const [sessionId, setSessionId] = useState("");

  useEffect(() => {
    const id = localStorage.getItem("session_id") || crypto.randomUUID();
    localStorage.setItem("session_id", id);
    setSessionId(id);
  }, []);

  async function loadRepo() {
    const data = await fetchRepoTree(repo, branch, pat);
    setTree(data);
  }

  async function sendPrompt(prompt: string) {
    setOutput("");

    const res = await sendChatRequest({
      prompt,
      session_id: sessionId,
      pat,
      repo,
      branch,
      skill_md: skillMd,
      selected_files: selected,
    });

    await streamChatResponse(
      res,
      (token) => setOutput((prev) => prev + token),
      () => console.log("done")
    );
  }

  return (
    <div className="grid grid-cols-2 h-screen">
      
      {/* LEFT PANEL */}
      <div className="p-4 border-r border-zinc-800 space-y-4">
        <RepoInput
          repo={repo}
          setRepo={setRepo}
          branch={branch}
          setBranch={setBranch}
          pat={pat}
          setPat={setPat}
          onLoad={loadRepo}
        />

        <textarea
          className="w-full h-40 bg-zinc-900 p-2"
          placeholder="SKILL.md"
          value={skillMd}
          onChange={(e) => setSkillMd(e.target.value)}
        />
      </div>

      {/* RIGHT PANEL */}
      <div className="p-4 overflow-auto">
        <FileExplorer
          tree={tree}
          selected={selected}
          setSelected={setSelected}
        />
      </div>

      {/* CHAT SECTION */}
      <div className="col-span-2 border-t border-zinc-800 p-4">
        <StreamViewer output={output} />

        <ChatBox
          onSend={sendPrompt}
          disabled={selected.length === 0}
        />
      </div>
    </div>
  );
}
