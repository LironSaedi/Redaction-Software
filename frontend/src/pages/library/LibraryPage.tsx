import { useNavigate, useParams } from "react-router-dom";
import { Tabs } from "../../components/ui";
import { ListsTab } from "./ListsTab";
import { TemplatesTab } from "./TemplatesTab";
import { CodesTab, PresetsTab } from "./PresetsTab";

type Key = "lists" | "templates" | "presets" | "codes";

export function LibraryPage() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const active: Key = (["lists", "templates", "presets", "codes"] as Key[]).includes(tab as Key) ? (tab as Key) : "lists";
  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Library</h1>
          <p className="muted">Reusable term lists, zone templates, analysis presets and exemption codes.</p>
        </div>
      </div>
      <Tabs<Key>
        label="Library sections"
        active={active}
        onChange={(k) => navigate(`/library/${k}`)}
        tabs={[
          { key: "lists", label: "Term lists" },
          { key: "templates", label: "Templates" },
          { key: "presets", label: "Presets" },
          { key: "codes", label: "Exemption codes" },
        ]}
      />
      <div className="tab-panel" role="tabpanel" aria-labelledby={`tab-${active}`}>
        {active === "lists" && <ListsTab />}
        {active === "templates" && <TemplatesTab />}
        {active === "presets" && <PresetsTab />}
        {active === "codes" && <CodesTab />}
      </div>
    </div>
  );
}
