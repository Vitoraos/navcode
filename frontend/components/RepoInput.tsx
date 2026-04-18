export default function RepoInput({
  repo,
  setRepo,
  branch,
  setBranch,
  pat,
  setPat,
  onLoad,
}: any) {
  return (
    <div className="space-y-2">
      <input className="input" placeholder="owner/repo"
        value={repo} onChange={(e) => setRepo(e.target.value)} />

      <input className="input" placeholder="branch"
        value={branch} onChange={(e) => setBranch(e.target.value)} />

      <input className="input" placeholder="GitHub PAT"
        type="password"
        value={pat} onChange={(e) => setPat(e.target.value)} />

      <button onClick={onLoad} className="btn">
        Load Repo Files
      </button>
    </div>
  );
}
