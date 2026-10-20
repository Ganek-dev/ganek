// The ALTCHA widget (package "altcha", 2.x) registers the <altcha-widget>
// custom element on import; this makes it a known JSX element with the
// attributes the Captcha component uses.
import type { DetailedHTMLProps, HTMLAttributes } from "react";

declare module "altcha";

declare global {
  namespace React {
    namespace JSX {
      interface IntrinsicElements {
        "altcha-widget": DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
          challengejson?: string;
          challengeurl?: string;
          name?: string;
          auto?: "off" | "onfocus" | "onload" | "onsubmit";
          hidefooter?: string;
          hidelogo?: string;
          maxnumber?: number;
          workers?: number;
        };
      }
    }
  }
}
