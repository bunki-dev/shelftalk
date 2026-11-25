import { useState } from "react";
import type { ModelSettings } from "../runtime";

export function Settings({
  value,
  onSave,
  onClose,
}: {
  value: ModelSettings;
  onSave: (s: ModelSettings) => void;
  onClose: () => void;
}) {
  const [s, setS] = useState(value);
  const set = (k: keyof ModelSettings) => (e: { target: { value: string } }) => setS({ ...s, [k]: e.target.value });
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <form
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          onSave(s);
        }}
      >
        <h2 id="settings-title">AI model</h2>
        <p>
          Common questions are answered by a built-in planner without any model. Connect one for open-ended
          questions. Your key is stored only in this browser and sent only to the provider you choose.
        </p>
        <fieldset className="providers">
          <legend className="sr-only">Provider</legend>
          {(
            [
              ["none", "None"],
              ["anthropic", "Claude"],
              ["azure", "Azure AI Foundry"],
            ] as const
          ).map(([k, label]) => (
            <label key={k} className={s.provider === k ? "on" : ""}>
              <input
                type="radio"
                name="provider"
                checked={s.provider === k}
                onChange={() => setS({ ...s, provider: k })}
              />
              {label}
            </label>
          ))}
        </fieldset>
        {s.provider !== "none" && (
          <label>
            API key
            <input type="password" value={s.api_key} onChange={set("api_key")} autoComplete="off" />
          </label>
        )}
        {s.provider === "anthropic" && (
          <label>
            Model
            <input value={s.model} onChange={set("model")} />
          </label>
        )}
        {s.provider === "azure" && (
          <>
            <label>
              Endpoint
              <input value={s.endpoint} onChange={set("endpoint")} placeholder="https://my-resource.openai.azure.com" />
            </label>
            <label>
              Deployment
              <input value={s.deployment} onChange={set("deployment")} placeholder="gpt-4o" />
            </label>
          </>
        )}
        <div className="sheet-actions">
          <button type="button" className="link" onClick={() => setS({ ...s, api_key: "" })}>
            Forget key
          </button>
          <button type="submit" className="primary">
            Save
          </button>
        </div>
      </form>
    </div>
  );
}
