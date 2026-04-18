export async function fetchRepoTree(repo: string, branch: string, pat: string) {
  const res = await fetch(
    `https://api.github.com/repos/${repo}/git/trees/${branch}?recursive=1`,
    {
      headers: {
        Authorization: `Bearer ${pat}`,
      },
    }
  );

  if (!res.ok) throw new Error("Failed to fetch repo tree");

  const data = await res.json();
  return data.tree as { path: string; type: string }[];
}
