/** 5-dot difficulty scale from the design handoff (screen 09):
 *  filled dots = level; green ≤2, amber 3, red ≥4. */

const BAND_TONES = {
  green: "bg-green-600 dark:bg-green-400",
  amber: "bg-amber-500 dark:bg-amber-400",
  red: "bg-red-600 dark:bg-red-400",
};

function band(level: number): keyof typeof BAND_TONES {
  if (level <= 2) return "green";
  if (level === 3) return "amber";
  return "red";
}

export function DifficultyDots({ level }: { level: number }) {
  const tone = BAND_TONES[band(level)];
  return (
    <span
      role="img"
      aria-label={`Difficulty ${level} of 5`}
      title={`Difficulty ${level}/5`}
      className="inline-flex items-center gap-0.5"
    >
      {[1, 2, 3, 4, 5].map((dot) => (
        <span
          key={dot}
          className={`h-1.5 w-1.5 rounded-full ${
            dot <= level ? tone : "bg-zinc-200 dark:bg-zinc-700"
          }`}
        />
      ))}
    </span>
  );
}
