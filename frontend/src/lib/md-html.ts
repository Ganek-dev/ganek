import rehypeStringify from "rehype-stringify";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified } from "unified";

interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

/** Mirror the on-page policy (G4): markdown images never render as <img> —
 * their alt text survives as plain text, alt-less images vanish. */
function imagesToAltText() {
  const walk = (node: HastNode): void => {
    if (!node.children) return;
    node.children = node.children.map((child) => {
      if (child.type === "element" && child.tagName === "img") {
        const alt = typeof child.properties?.alt === "string" ? child.properties.alt : "";
        return { type: "text", value: alt } satisfies HastNode;
      }
      walk(child);
      return child;
    });
  };
  return walk;
}

const processor = unified()
  .use(remarkParse)
  .use(remarkRehype) // raw HTML in the markdown is dropped, not passed through
  .use(imagesToAltText)
  .use(rehypeStringify);

/** Markdown → HTML string for JSON-LD descriptions (Google wants HTML, not
 * raw markdown). Output contains only elements generated from markdown. */
export function mdToHtml(markdown: string): string {
  return String(processor.processSync(markdown));
}
