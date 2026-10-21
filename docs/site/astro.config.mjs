import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";

// ganek.dev: static, self-contained. No analytics, no external fonts, no
// third-party requests - the same rule as the landing and the product.
export default defineConfig({
  site: "https://ganek.dev",
  integrations: [
    starlight({
      title: "Ganek docs",
      description:
        "Self-host Ganek: careers page, skill screening quizzes and an ATS-lite, GDPR-ready.",
      social: [
        { icon: "github", label: "GitHub", href: "https://github.com/Ganek-dev/ganek" },
      ],
      editLink: { baseUrl: "https://github.com/Ganek-dev/ganek/edit/main/docs/site/" },
      sidebar: [
        {
          label: "Run it",
          items: [{ slug: "quickstart" }, { slug: "configuration" }, { slug: "self-hosting" }],
        },
        {
          label: "Extend it",
          items: [{ slug: "question-packs" }, { slug: "api-embed" }],
        },
        {
          label: "Compliance pack",
          items: [{ autogenerate: { directory: "compliance" } }],
        },
      ],
      customCss: ["./src/styles/custom.css"],
      lastUpdated: false,
      credits: false,
    }),
  ],
});
