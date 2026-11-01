import Link from "next/link";

import { StatusChip } from "@/components/StatusChip";
import type { BoardJob, BoardOut, StageCounts } from "@/lib/api";

/** Open roles board (R3 01 table, R3 03 cards). Rows keep the API order. The
 * rule sentence sits under the title at both widths so reading it never
 * depends on hover. */

const STAGES: (keyof StageCounts)[] = ["new", "screening", "interview", "offer"];

const MONO = "font-mono tabular-nums";
const TH = "pb-2 pl-2.5 text-right font-mono text-[11px] font-normal text-g500 align-bottom";
const TD = "border-t border-divider py-3 pl-2.5 text-right align-top";

function daysOpen(job: BoardJob): string | null {
  if (job.days_open === null) return null;
  return job.job_status === "closed" ? `${job.days_open} d, closed` : `${job.days_open} d`;
}

function ClosedTag() {
  return (
    <span className="inline-flex h-[18px] items-center rounded-md bg-muted-fill px-1.5 font-mono text-[11px] text-g600">
      Closed
    </span>
  );
}

function count(value: number) {
  return value === 0 ? "text-g500" : "text-strong";
}

function WaitingCell({ job }: { job: BoardJob }) {
  const body = (
    <>
      <span className={`${MONO} text-[13px] font-medium ${count(job.waiting_on_team)}`}>
        {job.waiting_on_team}
      </span>
      {job.longest_wait_days !== null ? (
        <span className="mt-0.5 block font-mono text-[11px] whitespace-nowrap text-g500">
          longest {job.longest_wait_days} d
        </span>
      ) : null}
    </>
  );
  if (job.waiting_on_team === 0) return <div>{body}</div>;
  return (
    <Link
      href={`/admin/applicants?job=${job.job_id}&waiting=team`}
      title="Open applicants waiting on you"
      className="block"
    >
      {body}
    </Link>
  );
}

function RoleTable({ jobs, limit }: { jobs: BoardJob[]; limit: number }) {
  return (
    <table aria-label="Open roles" className="mt-3.5 hidden w-full border-collapse lg:table">
      <caption className="sr-only">Stage limit {limit} days</caption>
      <colgroup>
        <col />
        <col className="w-[136px]" />
        {STAGES.map((stage) => (
          <col key={stage} className="w-[60px]" />
        ))}
        <col className="w-[96px]" />
        <col className="w-[68px]" />
        <col className="w-[62px]" />
        <col className="w-[62px]" />
        <col className="w-[108px]" />
      </colgroup>
      <thead>
        <tr>
          <th colSpan={2} />
          <th colSpan={4} className={TH}>
            <span className="block border-b border-edge pb-1 text-center">Live by stage</span>
          </th>
          <th colSpan={5} />
        </tr>
        <tr>
          <th scope="col" className={`${TH} !pl-0 !text-left`}>
            Role
          </th>
          <th scope="col" className={`${TH} !text-left`}>
            Status
          </th>
          {STAGES.map((stage) => (
            <th key={stage} scope="col" className={TH}>
              {stage}
            </th>
          ))}
          <th scope="col" className={TH}>
            Waiting on you
          </th>
          <th scope="col" className={TH}>
            Overdue
          </th>
          <th scope="col" className={TH}>
            New this week
          </th>
          <th scope="col" className={TH}>
            Moved this week
          </th>
          <th scope="col" className={TH}>
            Days open
          </th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <tr key={job.job_id}>
            <td className={`${TD} !pl-0 !text-left`}>
              <div className="flex items-center gap-2">
                <Link
                  href={`/admin/applicants?job=${job.job_id}`}
                  className="text-[13.5px] font-medium text-strong underline decoration-edge underline-offset-[3px] hover:decoration-current"
                >
                  {job.title}
                </Link>
                {job.job_status === "closed" ? <ClosedTag /> : null}
              </div>
              <p className="mt-[3px] text-xs leading-[17px] text-g500">{job.reason}</p>
            </td>
            <td className={`${TD} !text-left`}>
              <StatusChip status={job.status} reason={job.reason} />
            </td>
            {STAGES.map((stage) => (
              <td key={stage} className={TD}>
                <span
                  className={`${MONO} text-[13px] font-medium ${count(job.live_by_stage[stage])}`}
                >
                  {job.live_by_stage[stage]}
                </span>
              </td>
            ))}
            <td className={TD}>
              <WaitingCell job={job} />
            </td>
            <td className={TD}>
              <span
                data-testid={`overdue-${job.job_id}`}
                className={`${MONO} text-[13px] ${
                  job.overdue > 0 ? "font-semibold text-warn" : "font-medium text-g500"
                }`}
              >
                {job.overdue}
              </span>
            </td>
            <td className={TD}>
              <span className={`${MONO} text-[13px] font-medium ${count(job.new_7d)}`}>
                {job.new_7d}
              </span>
            </td>
            <td className={TD}>
              <span className={`${MONO} text-[13px] font-medium ${count(job.moved_7d)}`}>
                {job.moved_7d}
              </span>
            </td>
            <td className={TD}>
              <span className="font-mono text-xs whitespace-nowrap text-g600">
                {daysOpen(job) ?? "-"}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Fact({
  label,
  value,
  valueClass = "text-strong",
}: {
  label: string;
  value: string | number;
  valueClass?: string;
}) {
  return (
    <div className="flex justify-between gap-2 font-mono text-xs text-g500">
      <span>{label}</span>
      <span className={valueClass}>{value}</span>
    </div>
  );
}

function RoleCards({ jobs }: { jobs: BoardJob[] }) {
  return (
    <ul aria-label="Open roles" className="mt-3.5 space-y-2 lg:hidden">
      {jobs.map((job) => (
        <li key={job.job_id} className="rounded-lg bg-muted-fill/50 px-4 py-3.5">
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              <Link
                href={`/admin/applicants?job=${job.job_id}`}
                className="font-heading text-[14.5px] leading-[22px] font-semibold text-strong"
              >
                {job.title}
              </Link>
              {job.job_status === "closed" ? <ClosedTag /> : null}
            </div>
            <StatusChip status={job.status} reason={job.reason} />
          </div>
          <p className="mt-1.5 text-[12.5px] leading-[18px] text-g600">{job.reason}</p>
          <div className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1">
            <Fact label="new" value={job.live_by_stage.new} />
            <Fact label="waiting on you" value={job.waiting_on_team} />
            <Fact label="screening" value={job.live_by_stage.screening} />
            <Fact
              label="longest wait"
              value={job.longest_wait_days === null ? "-" : `${job.longest_wait_days} d`}
            />
            <Fact label="interview" value={job.live_by_stage.interview} />
            <Fact
              label="overdue"
              value={job.overdue}
              valueClass={job.overdue > 0 ? "font-semibold text-warn" : "text-g500"}
            />
            <Fact label="offer" value={job.live_by_stage.offer} />
            <Fact label="new this week" value={job.new_7d} />
            <span className="font-mono text-xs text-g500">
              {daysOpen(job) === null ? "open -" : `open ${daysOpen(job)}`}
            </span>
            <Fact label="moved this week" value={job.moved_7d} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function OpenRolesBoard({ board }: { board: BoardOut }) {
  return (
    <section className="card px-5 pt-[18px] pb-4 lg:pb-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-heading text-[15px] font-semibold">Open roles</h2>
        <span className="font-mono text-[11px] text-g500">
          stage limit {board.stage_limit_days} days
        </span>
      </div>
      {board.jobs.length === 0 ? (
        <p className="py-6 text-sm text-g500">Publish a job to see its pipeline here.</p>
      ) : (
        <>
          <RoleTable jobs={board.jobs} limit={board.stage_limit_days} />
          <RoleCards jobs={board.jobs} />
        </>
      )}
    </section>
  );
}
