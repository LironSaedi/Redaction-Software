import { Kbd, Modal } from "../../components/ui";

type Row = [keys: string[], what: string];
interface Section {
  title: string;
  rows: Row[];
}

const MOD = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";

const HISTORY: Section = {
  title: "Undo & help",
  rows: [
    [[`${MOD} Z`], "Undo the last change"],
    [[`${MOD} ⇧ Z`, `${MOD} Y`], "Redo"],
    [["?"], "Show this list"],
    [["Esc"], "Cancel / close"],
  ],
};

const LIST: Section = {
  title: "Detection list",
  rows: [
    [["↑", "↓"], "Move through the list"],
    [["Space"], "Redact / un-redact the highlighted item"],
    [["Enter"], "Show it in the document"],
  ],
};

function sections(kind: string): Section[] {
  if (kind === "video")
    return [
      {
        title: "Playback",
        rows: [
          [["Space"], "Play / pause"],
          [["←", "→"], "Previous / next frame (pauses)"],
          [[",", "."], "Previous / next frame"],
          [["⇧ ←", "⇧ →"], "Back / forward one second"],
        ],
      },
      {
        title: "Redaction",
        rows: [
          [["A", "D"], "Add a redaction: draw on the current frame"],
          [["R", "E"], "While adding: rectangle / ellipse shape"],
          [["I", "O"], "Set the in / out point on the timeline"],
          [["F"], "Full-frame effect for the in → out range"],
          [["X"], "Redact / keep visible the selected track"],
          [["P"], "Live preview of the effects"],
        ],
      },
      LIST,
      HISTORY,
    ];
  if (kind === "audio")
    return [
      {
        title: "Playback & review",
        rows: [
          [["Space"], "Play / pause"],
          [["P"], "Preview the redacted transcript"],
        ],
      },
      LIST,
      HISTORY,
    ];
  if (kind === "docx" || kind === "pptx" || kind === "xlsx" || kind === "text")
    return [
      {
        title: "Review",
        rows: [
          [["P"], "Preview redacted"],
          [["S"], "Show / hide suggestions"],
        ],
      },
      LIST,
      HISTORY,
    ];
  return [
    {
      title: "Tools",
      rows: [
        [["V"], "Select / move (default)"],
        [["R", "D"], "Rectangle"],
        [["E"], "Ellipse"],
        [["G"], "Polygon — click points, double-click or Enter to close"],
        [["T"], "Text selection (PDF)"],
        [["H"], "Hand (pan)"],
        [["Space (hold)"], "Pan temporarily"],
        [["⇧ drag"], "Square / circle while drawing"],
        [["⌫"], "Polygon: remove the last point"],
      ],
    },
    {
      title: "Selected redaction",
      rows: [
        [["Enter"], "Redact / un-redact"],
        [["Delete"], "Delete"],
        [["Drag"], "Move; drag a handle to resize"],
      ],
    },
    {
      title: "View",
      rows: [
        [["P"], "Edit ↔ preview redacted"],
        [["S"], "Show / hide suggestions"],
        [["+", "−"], "Zoom in / out"],
        [[`${MOD} scroll`], "Zoom at the pointer"],
        [["0"], "Fit width"],
        [["F"], "Fit page"],
        [["←", "→"], "Previous / next page"],
        [["Home", "End"], "First / last page"],
      ],
    },
    LIST,
    HISTORY,
  ];
}

export function ShortcutsHelp({ kind, onClose }: { kind: string; onClose: () => void }) {
  return (
    <Modal title="Keyboard shortcuts" onClose={onClose} size="lg">
      <div className="shortcut-grid">
        {sections(kind).map((s) => (
          <section key={s.title} className="shortcut-section">
            <h3>{s.title}</h3>
            <dl className="shortcut-list">
              {s.rows.map(([keys, what]) => (
                <div key={what} className="shortcut-row">
                  <dt>
                    {keys.map((k, i) => (
                      <span key={k}>
                        {i > 0 && <span className="muted tiny"> or </span>}
                        <Kbd>{k}</Kbd>
                      </span>
                    ))}
                  </dt>
                  <dd>{what}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </Modal>
  );
}
