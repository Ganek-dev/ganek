/* Ganek jobs widget — drop your open roles into any site.
 *
 * <script src="https://YOUR-GANEK/embed/jobs.js" data-workspace="acmelabs"></script>
 *
 * Attributes: data-workspace (required — your careers slug),
 * data-theme "auto" | "light" | "dark" (default auto),
 * data-tags "false" to hide tag chips.
 *
 * No framework, no tracking; one fetch to the public jobs feed (CORS-open,
 * cached 60s). Renders nothing if the feed is unreachable.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script || !script.src) return;
  var origin = new URL(script.src).origin;
  var workspace = script.getAttribute("data-workspace");
  if (!workspace) return;
  var themeAttr = script.getAttribute("data-theme") || "auto";
  var showTags = script.getAttribute("data-tags") !== "false";
  var feedUrl =
    origin + "/api/v1/public/companies/" + encodeURIComponent(workspace) + "/jobs-feed";

  var dark =
    themeAttr === "dark" ||
    (themeAttr === "auto" &&
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);

  var palette = dark
    ? { bg: "#18181b", fg: "#fafafa", muted: "#a1a1aa", line: "#27272a", chipBg: "#27272a" }
    : { bg: "#ffffff", fg: "#18181b", muted: "#71717a", line: "#e4e4e7", chipBg: "#f4f4f5" };

  var container = document.createElement("div");
  container.setAttribute("data-ganek-jobs", "");
  container.style.cssText =
    "box-sizing:border-box;max-width:560px;border:1px solid " +
    palette.line +
    ";border-radius:12px;background:" +
    palette.bg +
    ";color:" +
    palette.fg +
    ";font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;overflow:hidden";
  script.parentNode.insertBefore(container, script.nextSibling);

  function el(tag, css, text) {
    var node = document.createElement(tag);
    if (css) node.style.cssText = css;
    if (text) node.textContent = text;
    return node;
  }

  fetch(feedUrl)
    .then(function (resp) {
      if (!resp.ok) throw new Error("feed unavailable");
      return resp.json();
    })
    .then(function (feed) {
      var brand = /^#[0-9a-fA-F]{6}$/.test(feed.brand_primary || "")
        ? feed.brand_primary
        : palette.fg;
      var head = el(
        "div",
        "display:flex;align-items:baseline;justify-content:space-between;padding:14px 18px;border-bottom:1px solid " +
          palette.line,
      );
      head.appendChild(el("span", "font-size:15px;font-weight:600", "Open positions"));
      head.appendChild(
        el(
          "span",
          "font-size:12px;color:" + palette.muted,
          feed.jobs.length + " role" + (feed.jobs.length === 1 ? "" : "s"),
        ),
      );
      container.appendChild(head);

      feed.jobs.forEach(function (job, index) {
        var row = el(
          "a",
          "display:block;padding:12px 18px;text-decoration:none;color:inherit" +
            (index > 0 ? ";border-top:1px solid " + palette.line : ""),
        );
        // trust but verify our own feed: never let a non-http(s) value
        // (e.g. javascript:) become a clickable link on the host page
        if (/^https?:\/\//i.test(job.apply_url)) row.href = job.apply_url;
        row.target = "_blank";
        row.rel = "noreferrer";
        var title = el("div", "font-size:14px;font-weight:600;color:" + brand, job.title);
        row.appendChild(title);
        var meta = el(
          "div",
          "margin-top:2px;font-size:12px;color:" + palette.muted,
          job.location || "",
        );
        row.appendChild(meta);
        if (showTags && job.tags && job.tags.length) {
          var tags = el("div", "margin-top:6px");
          job.tags.slice(0, 4).forEach(function (tag) {
            tags.appendChild(
              el(
                "span",
                "display:inline-block;margin-right:6px;padding:2px 8px;border-radius:999px;font-size:11px;background:" +
                  palette.chipBg +
                  ";color:" +
                  palette.muted,
                tag,
              ),
            );
          });
          row.appendChild(tags);
        }
        container.appendChild(row);
      });

      if (feed.jobs.length === 0) {
        container.appendChild(
          el(
            "div",
            "padding:16px 18px;font-size:13px;color:" + palette.muted,
            "No open positions right now.",
          ),
        );
      }

      var foot = el("a", "display:block;padding:10px 18px;border-top:1px solid " + palette.line);
      foot.href = origin + "/c/" + encodeURIComponent(workspace);
      foot.target = "_blank";
      foot.rel = "noreferrer";
      foot.style.textDecoration = "none";
      foot.appendChild(
        el("span", "font-size:11px;color:" + palette.muted, "Careers powered by Ganek"),
      );
      container.appendChild(foot);
    })
    .catch(function () {
      container.remove();
    });
})();
