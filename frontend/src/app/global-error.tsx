"use client";

/** Last-resort boundary: catches errors thrown by the root layout itself,
 * so it must render its own <html>/<body> and use no app CSS (globals.css
 * may not have loaded). Deliberately minimal and dependency-free. */
export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
          background: "#fafafa",
          color: "#18181b",
        }}
      >
        <div style={{ maxWidth: 380, textAlign: "center", padding: 24 }}>
          <p style={{ fontWeight: 700, letterSpacing: "-0.01em", fontSize: 20 }}>vetd</p>
          <h1 style={{ fontSize: 24, margin: "18px 0 8px" }}>Something broke</h1>
          <p style={{ fontSize: 14.5, lineHeight: "22px", color: "#52525b" }}>
            The app hit an unexpected error at the very top. Reload, and if it keeps
            happening the instance logs will say why.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: 20,
              height: 40,
              padding: "0 18px",
              borderRadius: 6,
              border: "1.5px solid #d4d4d8",
              background: "transparent",
              fontSize: 13.5,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
