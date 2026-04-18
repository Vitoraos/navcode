export type RepoTreeItem = {
  path: string;
  type: "blob" | "tree";
};

export type ChatRequest = {
  prompt: string;
  session_id: string;
  pat: string;
  repo: string;
  branch: string;
  skill_md: string;
  selected_files: string[];
};
