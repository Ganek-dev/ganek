import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { companyApi, type CompanyAdmin } from "@/lib/api";

import BrandingPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/branding",
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    companyApi: { get: vi.fn(), updateBranding: vi.fn() },
  };
});

const mocked = vi.mocked(companyApi);

function makeCompany(overrides: Partial<CompanyAdmin> = {}): CompanyAdmin {
  return {
    slug: "northwind",
    name: "Northwind Robotics",
    description: "",
    logo_url: null,
    website: null,
    socials: {},
    theme: {},
    ...overrides,
  };
}

describe("BrandingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.get.mockResolvedValue(makeCompany());
    mocked.updateBranding.mockImplementation((patch) =>
      Promise.resolve(
        makeCompany({
          theme: {
            ...(patch.primary_color ? { primary_color: patch.primary_color } : {}),
            ...(patch.radius ? { radius: patch.radius } : {}),
          },
        }),
      ),
    );
  });

  it("loads company branding, shows domain and preview", async () => {
    render(<BrandingPage />);
    expect(await screen.findByText("northwind.vetd.dev")).toBeInTheDocument();
    expect(screen.getByText("Work at Northwind Robotics")).toBeInTheDocument();
    expect(screen.getByText("AA contrast ok")).toBeInTheDocument();
    expect(screen.getByLabelText("Brand color hex")).toHaveValue("#18181b");
    expect(screen.getByRole("radio", { name: "default" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("hydrates saved theme values", async () => {
    mocked.get.mockResolvedValue(
      makeCompany({ theme: { primary_color: "#E4572E", radius: "round" } }),
    );
    render(<BrandingPage />);
    expect(await screen.findByLabelText("Brand color hex")).toHaveValue("#E4572E");
    expect(screen.getByRole("radio", { name: "round" })).toHaveAttribute("aria-checked", "true");
  });

  it("saves color and radius, sending null for defaults", async () => {
    render(<BrandingPage />);
    const hex = await screen.findByLabelText("Brand color hex");
    await userEvent.clear(hex);
    await userEvent.type(hex, "#7E14FF");
    await userEvent.click(screen.getByRole("radio", { name: "round" }));
    await userEvent.click(screen.getByRole("button", { name: "Save branding" }));
    await waitFor(() =>
      expect(mocked.updateBranding).toHaveBeenCalledWith({
        primary_color: "#7E14FF",
        radius: "round",
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Branding saved");
  });

  it("resets to defaults with nulls when saving the default color", async () => {
    mocked.get.mockResolvedValue(
      makeCompany({ theme: { primary_color: "#E4572E", radius: "round" } }),
    );
    render(<BrandingPage />);
    const hex = await screen.findByLabelText("Brand color hex");
    await userEvent.clear(hex);
    await userEvent.type(hex, "#18181b");
    await userEvent.click(screen.getByRole("radio", { name: "default" }));
    await userEvent.click(screen.getByRole("button", { name: "Save branding" }));
    await waitFor(() =>
      expect(mocked.updateBranding).toHaveBeenCalledWith({
        primary_color: null,
        radius: null,
      }),
    );
  });

  it("flags invalid hex and disables save", async () => {
    render(<BrandingPage />);
    const hex = await screen.findByLabelText("Brand color hex");
    await userEvent.clear(hex);
    await userEvent.type(hex, "#zzz");
    expect(screen.getByText("enter #rrggbb")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save branding" })).toBeDisabled();
  });

  it("warns when the brand color misses AA contrast", async () => {
    // mid gray pairs with white text at ~3.9:1 — under the 4.5 AA bar
    mocked.get.mockResolvedValue(makeCompany({ theme: { primary_color: "#808080" } }));
    render(<BrandingPage />);
    expect(await screen.findByText("contrast below AA")).toBeInTheDocument();
    expect(screen.queryByText("AA contrast ok")).not.toBeInTheDocument();
  });

  it("keeps the logo Replace button disabled until upload ships", async () => {
    render(<BrandingPage />);
    expect(await screen.findByRole("button", { name: "Replace" })).toBeDisabled();
  });
});
