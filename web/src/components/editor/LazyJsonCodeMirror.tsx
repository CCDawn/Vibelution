import { lazy, Suspense, useMemo, type ComponentType } from "react";

type JsonCodeMirrorProps = {
  value: string;
  onChange: (value: string) => void;
};

const JsonCodeMirrorImpl = lazy(() =>
  Promise.all([
    import("@uiw/react-codemirror"),
    import("@codemirror/lang-json"),
    import("@codemirror/view"),
    import("../../design/codeMirrorTheme"),
  ]).then(([codeMirrorModule, jsonModule, viewModule, themeModule]) => {
    const CodeMirror = codeMirrorModule.default as ComponentType<Record<string, unknown>>;

    function JsonCodeMirrorEditor({ value, onChange }: JsonCodeMirrorProps) {
      const extensions = useMemo(() => [jsonModule.json(), viewModule.EditorView.lineWrapping], []);
      return (
        <CodeMirror
          value={value}
          theme={themeModule.workbenchCodeMirrorTheme}
          height="100%"
          extensions={extensions}
          onChange={onChange}
          basicSetup={{
            foldGutter: false,
            allowMultipleSelections: false,
          }}
        />
      );
    }

    return { default: JsonCodeMirrorEditor };
  }),
);

export function LazyJsonCodeMirror({ value, onChange }: JsonCodeMirrorProps) {
  return (
    <Suspense fallback={<div style={{ minHeight: "100%" }} />}>
      <JsonCodeMirrorImpl value={value} onChange={onChange} />
    </Suspense>
  );
}
