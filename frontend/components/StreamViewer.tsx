export default function StreamViewer({ output }: any) {
  return (
    <div className="bg-zinc-900 p-3 h-60 overflow-auto">
      <pre className="whitespace-pre-wrap">{output}</pre>
    </div>
  );
}
