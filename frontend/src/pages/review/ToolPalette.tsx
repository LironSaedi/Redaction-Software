import type { ReactNode } from "react";
import { Circle, Hand, MousePointer2, Pentagon, Square, TextCursor } from "lucide-react";
import type { Tool } from "./workspace";

interface ToolDef {
  tool: Tool;
  label: string;
  keys: string;
  icon: ReactNode;
  hint: string;
}

const TOOLS: ToolDef[] = [
  { tool: "select", label: "Select", keys: "V", icon: <MousePointer2 size={16} aria-hidden />, hint: "Select, move and resize redactions" },
  { tool: "rect", label: "Rectangle", keys: "R", icon: <Square size={16} aria-hidden />, hint: "Drag to draw a rectangle (Shift = square)" },
  { tool: "ellipse", label: "Ellipse", keys: "E", icon: <Circle size={16} aria-hidden />, hint: "Drag to draw an ellipse (Shift = circle)" },
  { tool: "polygon", label: "Polygon", keys: "G", icon: <Pentagon size={16} aria-hidden />, hint: "Click points; double-click or Enter to close" },
  { tool: "text", label: "Text", keys: "T", icon: <TextCursor size={16} aria-hidden />, hint: "Drag across words to redact them" },
  { tool: "pan", label: "Hand", keys: "H", icon: <Hand size={16} aria-hidden />, hint: "Drag to pan (or hold Space)" },
];

export const TOOL_HINTS: Record<Tool, string> = Object.fromEntries(TOOLS.map((t) => [t.tool, t.hint])) as Record<Tool, string>;

interface Props {
  tool: Tool;
  onChange: (t: Tool) => void;
  /** tools that cannot be used here (e.g. text on an image) */
  disabled?: Partial<Record<Tool, string>>;
  hidden?: Tool[];
  readOnly?: boolean;
}

/** Vertical palette of review tools, CaseGuard-style. */
export function ToolPalette({ tool, onChange, disabled = {}, hidden = [], readOnly = false }: Props) {
  return (
    <div className="tool-palette" role="radiogroup" aria-label="Redaction tools" aria-orientation="vertical">
      {TOOLS.filter((t) => !hidden.includes(t.tool) && (!readOnly || t.tool === "select" || t.tool === "pan")).map((t, i) => {
        const why = disabled[t.tool];
        return (
          <span key={t.tool} className="tool-palette-item">
            {i === 1 && <span className="tool-palette-sep" aria-hidden />}
            {t.tool === "pan" && <span className="tool-palette-sep" aria-hidden />}
            <button
              type="button"
              role="radio"
              aria-checked={tool === t.tool}
              aria-label={`${t.label} (${t.keys})`}
              className={`palette-btn ${tool === t.tool ? "active" : ""}`}
              disabled={!!why}
              data-tip={why ? `${t.label}: ${why}` : `${t.label} · ${t.keys}`}
              data-tip-side="right"
              onClick={() => onChange(t.tool)}
            >
              {t.icon}
              <span className="palette-key" aria-hidden>
                {t.keys}
              </span>
            </button>
          </span>
        );
      })}
    </div>
  );
}
