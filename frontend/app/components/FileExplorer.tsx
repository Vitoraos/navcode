export default function FileExplorer({
  tree,
  selected,
  setSelected,
}: any) {
  function toggle(path: string) {
    setSelected((prev: string[]) =>
      prev.includes(path)
        ? prev.filter((p) => p !== path)
        : [...prev, path]
    );
  }

  return (
    <div className="text-sm space-y-1">
      {tree.map((file: any) => (
        <div key={file.path} className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={selected.includes(file.path)}
            onChange={() => toggle(file.path)}
          />
          <span>{file.path}</span>
        </div>
      ))}
    </div>
  );
}
