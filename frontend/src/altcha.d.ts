// The ALTCHA widget (package "altcha", 3.x) registers the <altcha-widget>
// custom element on import; this makes it a known JSX element with the
// HTML attributes 3.x actually reads (WidgetAttributes in the package's
// types). Anything else, e.g. hideFooter, goes through `configuration`.
import type { DetailedHTMLProps, HTMLAttributes } from "react";

declare module "altcha";

declare global {
  namespace React {
    namespace JSX {
      interface IntrinsicElements {
        "altcha-widget": DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
          /** Challenge JSON (starts with "{") or a URL to fetch one from. */
          challenge?: string;
          /** JSON of partial widget Configuration. */
          configuration?: string;
          name?: string;
          auto?: "off" | "onfocus" | "onload" | "onsubmit";
          display?: "standard" | "bar" | "floating" | "overlay" | "invisible";
          type?: "native" | "checkbox" | "switch";
          language?: string;
          workers?: number;
          form?: string;
          theme?: string;
        };
      }
    }
  }
}
