/** The API's rule-based sentences, verbatim, in a muted callout. No icon, no
 * advice: this only says where candidates left and where they waited. */
export function Diagnosis({ lines }: { lines: string[] }) {
  if (lines.length === 0) return null;
  return (
    <div className="rounded-[10px] bg-muted-fill px-3.5 py-3">
      {lines.map((line) => (
        <p key={line} className="text-[13.5px] leading-5 text-g700">
          {line}
        </p>
      ))}
    </div>
  );
}
