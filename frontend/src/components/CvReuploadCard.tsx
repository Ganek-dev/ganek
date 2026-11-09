"use client";

import { useRef, useState } from "react";

import { ShieldAlert } from "lucide-react";

import { ApiError, publicApplications, publicApply } from "@/lib/api";

/** Status page ask for a new CV after the virus scanner flagged the upload
 * (board card "CV virus scanning (ClamAV container)"). The replacement goes
 * through the same presigned upload as the apply form and is scanned again;
 * the signature name stays with the hiring team. */
export function CvReuploadCard({
  token,
  companyName,
  onReplaced,
}: {
  token: string;
  companyName: string;
  onReplaced: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(event: React.ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = "";
    setError(null);
    if (!file || file.size === 0) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Your CV must be a PDF file.");
      return;
    }
    setBusy(0);
    try {
      const ticket = await publicApplications.cvUploadTicket(token);
      if (file.size > ticket.max_size_mb * 1024 * 1024) {
        throw new ApiError(413, `Your CV exceeds the ${ticket.max_size_mb} MB limit.`);
      }
      await publicApply.uploadCv(ticket, file, (fraction) => setBusy(fraction));
      await publicApplications.replaceCv(token, {
        cv_object_key: ticket.object_key,
        cv_filename: file.name,
      });
      onReplaced();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "CV upload failed - please try again");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section
      aria-labelledby="cv-reupload-title"
      className="mt-7 rounded-lg border border-edge p-4"
      style={{ background: "color-mix(in oklab, var(--danger) 6%, var(--surface))" }}
    >
      <div className="flex items-start gap-3">
        <ShieldAlert
          aria-hidden
          className="mt-0.5 h-[18px] w-[18px] shrink-0"
          style={{ color: "var(--danger)" }}
        />
        <div className="min-w-0">
          <h2 id="cv-reupload-title" className="text-[15px] leading-6 font-semibold">
            Please upload your CV again
          </h2>
          <p className="mt-1 text-[13.5px] leading-5 text-g600">
            {`Our virus scanner flagged the file you sent, so ${companyName} cannot open it. This often happens with files from some editors or shared drives. Export your CV as a fresh PDF and upload it here - your application stays as it is.`}
          </p>
          <input
            ref={inputRef}
            id="cv-reupload"
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            aria-label="Upload a new CV (PDF)"
            onChange={handleFile}
            disabled={busy !== null}
          />
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy !== null}
            className="mt-3 rounded-md bg-brand px-3 py-1.5 text-[13px] font-medium text-brand-foreground disabled:opacity-60"
          >
            {busy === null ? "Choose a new PDF" : `Uploading - ${Math.round(busy * 100)}%`}
          </button>
          {error ? (
            <p role="alert" className="mt-2 text-[13px]" style={{ color: "var(--danger)" }}>
              {error}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
