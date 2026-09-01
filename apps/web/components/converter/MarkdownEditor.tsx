"use client";

/**
 * Markdown source editor.
 *
 * CodeMirror rather than Monaco: it provides the editing this tool actually
 * needs - syntax highlighting, wrapping, search, undo, keyboard navigation -
 * at a fraction of the bundle size. Monaco's extra capability (IntelliSense,
 * multi-file models, a language server) is irrelevant for editing one Markdown
 * document, and it would dominate the page weight.
 *
 * Loaded lazily by `Workspace`, so it costs nothing until a result exists.
 */

import { markdown as markdownLang } from "@codemirror/lang-markdown";
import { EditorView } from "@codemirror/view";
import CodeMirror from "@uiw/react-codemirror";
import { useMemo } from "react";

import { useTheme } from "@/components/theme/ThemeProvider";

interface Props {
  value: string;
  onChange: (value: string) => void;
  label?: string;
}

/** Editor chrome driven by the same CSS variables as the rest of the app. */
function editorTheme(isDark: boolean) {
  return EditorView.theme(
    {
      "&": {
        backgroundColor: "transparent",
        color: "var(--text)",
        fontSize: "13px",
        height: "100%",
      },
      ".cm-content": {
        fontFamily: "var(--font-mono)",
        padding: "16px 12px 40px",
        caretColor: "var(--accent)",
      },
      ".cm-gutters": {
        backgroundColor: "transparent",
        borderRight: "1px solid var(--border)",
        color: "var(--text-faint)",
      },
      ".cm-activeLine": { backgroundColor: "var(--surface-sunken)" },
      ".cm-activeLineGutter": {
        backgroundColor: "var(--surface-sunken)",
        color: "var(--text-muted)",
      },
      "&.cm-focused": { outline: "none" },
      ".cm-selectionBackground, ::selection": {
        backgroundColor: "var(--accent-subtle) !important",
      },
      "&.cm-focused .cm-selectionBackground": {
        backgroundColor: "var(--accent-subtle) !important",
      },
      ".cm-cursor": { borderLeftColor: "var(--accent)" },
      ".cm-panels": {
        backgroundColor: "var(--surface-raised)",
        color: "var(--text)",
      },
      ".cm-searchMatch": { backgroundColor: "var(--warning-subtle)" },
      ".cm-searchMatch.cm-searchMatch-selected": {
        backgroundColor: "var(--accent-subtle)",
      },
    },
    { dark: isDark },
  );
}

export default function MarkdownEditor({ value, onChange, label }: Props) {
  const { resolved } = useTheme();

  const extensions = useMemo(
    () => [
      markdownLang(),
      EditorView.lineWrapping,
      editorTheme(resolved === "dark"),
      EditorView.contentAttributes.of({
        "aria-label": label ?? "Markdown source",
      }),
    ],
    [resolved, label],
  );

  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={extensions}
      height="100%"
      className="h-full"
      basicSetup={{
        lineNumbers: true,
        foldGutter: false,
        highlightActiveLine: true,
        searchKeymap: true,
        autocompletion: false,
        bracketMatching: false,
        closeBrackets: false,
      }}
    />
  );
}
