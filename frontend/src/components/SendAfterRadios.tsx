"use client";

import { formatSendAfter, presetSendAfter, PRESET_LABELS, type SendAfterPreset } from "@/lib/send-after";

const PRESETS: SendAfterPreset[] = ["now", "tomorrow", "in_3_days"];

/** The "When" radio group for a rejection email (delayed rejection card).
 * Shared by the stage dialog and the bulk bar. */
export function SendAfterRadios({
  value,
  onChange,
}: {
  value: SendAfterPreset;
  onChange: (next: SendAfterPreset) => void;
}) {
  return (
    <fieldset className="space-y-1">
      <legend className="text-[13px] font-medium text-g700">When</legend>
      {PRESETS.map((preset) => {
        const at = presetSendAfter(preset);
        return (
          <label key={preset} className="flex items-center gap-2 text-[13px] text-foreground">
            <input
              type="radio"
              name="send-after"
              value={preset}
              checked={value === preset}
              onChange={() => onChange(preset)}
            />
            {PRESET_LABELS[preset]}
            {at ? ` (${formatSendAfter(at)})` : ""}
          </label>
        );
      })}
    </fieldset>
  );
}
