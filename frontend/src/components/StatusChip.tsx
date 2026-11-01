import { CircleCheck, CircleDashed, CirclePause, Clock } from "lucide-react";

import type { BoardStatus } from "@/lib/api";

/** Board status chip (R3 17). Describes the process of a role, never a
 * person. The reason sentence is built by the API and repeated as the title. */

const CHIPS = {
  stalled: { label: "Stalled", Icon: CirclePause, tone: "bg-danger-soft text-danger" },
  attention: { label: "Needs attention", Icon: Clock, tone: "bg-warn-soft text-warn" },
  on_track: { label: "On track", Icon: CircleCheck, tone: "bg-ok-soft text-ok" },
  empty: { label: "Empty", Icon: CircleDashed, tone: "bg-muted-fill text-g600" },
} as const;

export function StatusChip({ status, reason }: { status: BoardStatus; reason: string }) {
  const { label, Icon, tone } = CHIPS[status];
  return (
    <span
      title={reason}
      className={`inline-flex h-[22px] items-center gap-1 rounded-full pr-2 pl-1.5 text-[11.5px] font-medium whitespace-nowrap ${tone}`}
    >
      <Icon aria-hidden className="h-3 w-3 shrink-0" />
      {label}
    </span>
  );
}
